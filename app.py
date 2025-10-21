import json
import os
import re
from typing import Any, Dict, Optional

import requests
from flask import Flask, Response, request, stream_with_context

# ---------- config ----------
OLLAMA = os.environ.get("TARGET_OLLAMA", "http://ollama:11434")
READ_TIMEOUT = float(os.environ.get("UPSTREAM_TIMEOUT", "300"))  # seconds

SHORT_MAX  = int(os.environ.get("SHORT_MAX_WORDS",  "12"))
NORMAL_MAX = int(os.environ.get("NORMAL_MAX_WORDS", "60"))

# Reasonable defaults; caller-specified options still win
CAP_SHORT  = json.loads(os.environ.get(
    "CAP_SHORT",
    '{"num_predict":160,"num_ctx":1024,"temperature":0.6,"repeat_penalty":1.2,"stop":["<|im_end|>"]}'
))
CAP_NORMAL = json.loads(os.environ.get(
    "CAP_NORMAL",
    '{"num_predict":384,"num_ctx":2048,"temperature":0.7,"repeat_penalty":1.2, "stop": ["<|im_end|>"]}'
))
CAP_DEEP   = json.loads(os.environ.get(
    "CAP_DEEP",
    '{"num_predict":768,"num_ctx":2048,"temperature":0.7,"repeat_penalty":1.1}'
))

app = Flask(__name__)
_SENT_SPLIT = re.compile(r'(?<=[\.\!\?。！？])\s+')
END_PUNCT = (".", "?", "!", "。", "！", "？", "...")
TAIL_TOKENS = int(os.environ.get("TAIL_TOKENS", "0"))
CHARS_PER_TOKEN = float(os.environ.get("CHARS_PER_TOKEN", "4.0"))
SHORT_SENTENCES = int(os.environ.get("SHORT_SENTENCES", "2"))
INF = 10**9

# ---------- helpers ----------
def keep_first_sentences(text: str, n: int = 2) -> str:
    parts = _SENT_SPLIT.split(text.strip())
    if not parts:
        return text
    return " ".join(parts[:n])


def has_rag(body: Dict[str, Any]) -> bool:
    return bool(body.get("files") or body.get("collection") or body.get("collections"))


def _caps_with_mode(template: Dict[str, Any], mode: str) -> Dict[str, Any]:
    data = dict(template)
    data["_mode"] = mode
    return data


def _collapse_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return _collapse_content(value.get("text") or "")
    if isinstance(value, list):
        return " ".join(_collapse_content(v) for v in value)
    return str(value or "")


def _chat_prompt_excerpt(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""

    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = _collapse_content(msg.get("content"))
            if content.strip():
                return content.strip()
    return " ".join(
        _collapse_content(m.get("content")) for m in messages if m.get("role") == "user"
    ).strip()


def _prompt_excerpt(body: Dict[str, Any]) -> str:
    prompt = (body.get("prompt") or "").strip()
    if prompt:
        return prompt
    return _chat_prompt_excerpt(body.get("messages"))


def choose_caps(body: Dict[str, Any]) -> Dict[str, Any]:
    """Pick caps based on prompt length or RAG signals."""
    if has_rag(body):
        return _caps_with_mode(CAP_DEEP, "deep")

    excerpt = _prompt_excerpt(body)
    n = len(excerpt.split())
    if n <= SHORT_MAX:
        return _caps_with_mode(CAP_SHORT, "short")
    if n <= NORMAL_MAX:
        return _caps_with_mode(CAP_NORMAL, "normal")
    return _caps_with_mode(CAP_DEEP, "deep")


def _as_int(val, default):
    try:
        if val is None:
            return default
        return int(val)
    except Exception:
        return default

def extract_client_options(body: dict) -> dict:
    """
    Normalize options from either OpenAI-style (top-level) or Ollama-style (options).
    If options has None values, we still fill from top-level when available.
    """
    opts = dict(body.get("options") or {})

    # stream can be top-level or in options
    if "stream" in body and "stream" not in opts:
        opts["stream"] = body["stream"]

    # temperature / stop at top-level
    if "temperature" in body and ("temperature" not in opts or opts["temperature"] is None):
        opts["temperature"] = body["temperature"]
    if "stop" in body and ("stop" not in opts or opts["stop"] is None):
        opts["stop"] = body["stop"]

    # OpenAI style max_tokens -> num_predict (override if missing or None)
    if "max_tokens" in body and (_as_int(opts.get("num_predict"), None) is None):
        opts["num_predict"] = body["max_tokens"]

    # Ensure keys exist (None -> missing) so clamp can set defaults
    if "num_predict" not in opts or opts["num_predict"] is None:
        opts.pop("num_predict", None)
    if "num_ctx" not in opts or opts["num_ctx"] is None:
        opts.pop("num_ctx", None)

    return opts

def clamp_options(chosen: dict, client: dict) -> dict:
    """
    Enforce hard caps for num_predict/num_ctx, keep any stricter client request.
    """
    out = dict(client)

    if "num_predict" in chosen:
        out["num_predict"] = min(
            _as_int(out.get("num_predict"), INF),
            _as_int(chosen["num_predict"], INF)
        )
    if "num_ctx" in chosen:
        out["num_ctx"] = min(
            _as_int(out.get("num_ctx"), INF),
            _as_int(chosen["num_ctx"], INF)
        )
    out.setdefault("temperature", chosen.get("temperature", 0.7))
    out.setdefault("repeat_penalty", chosen.get("repeat_penalty", 1.2))
    if "stop" in chosen and "stop" not in out:
        out["stop"] = chosen["stop"]
    return out
DEFAULT_SYSTEM_SHORT = os.getenv(
    "DEFAULT_SYSTEM_SHORT",
    "Be brief. Answer in 1–3 sentences unless asked for more."
)

def inject_concise_system(body: dict, chosen: dict) -> dict:
    """Prepend a concise system message for short, non-RAG prompts if none exists."""
    if chosen.get("_mode") != "short":
        return body
    if has_rag(body):
        return body

    # Chat payload (messages) vs prompt payload
    msgs = body.get("messages")
    if isinstance(msgs, list) and msgs:
        if msgs[0].get("role") == "system":
            return body  # already has a system prompt
        # Prepend our concise bias
        body["messages"] = [{"role": "system", "content": DEFAULT_SYSTEM_SHORT}] + msgs
        app.logger.info("SYS: injected concise system (messages)")
    else:
        # Non-chat: add to prompt
        body["prompt"] = f"{DEFAULT_SYSTEM_SHORT}\n\n{(body.get('prompt') or '')}"
        app.logger.info("SYS: injected concise system (prompt)")
    return body




def stream_upstream(method: str, path: str, *, json_body=None, data=None, headers=None, params=None):
    """Proxy to Ollama with chunked streaming and graceful cutoff polish."""
    url = f"{OLLAMA}{path}"
    r = requests.request(
        method,
        url,
        json=json_body,
        data=data,
        headers=headers,
        params=params,
        stream=True,
        timeout=(10, READ_TIMEOUT),  # (connect, read)
    )

    resp_headers = [(k, v) for k, v in r.headers.items() if k.lower() != "content-length"]

    def gen():
        full_response_parts: list[str] = []
        pending_bytes: Optional[bytes] = None
        pending_parsed: Optional[Dict[str, Any]] = None

        try:
            for raw_line in r.iter_lines(chunk_size=8192, decode_unicode=False):
                if raw_line is None:
                    continue

                if pending_bytes is not None:
                    yield pending_bytes

                pending_bytes = raw_line + b"\n"
                pending_parsed = None

                try:
                    parsed = json.loads(raw_line.decode("utf-8", errors="ignore"))
                except Exception:
                    continue

                pending_parsed = parsed
                piece = parsed.get("response")
                if isinstance(piece, str):
                    full_response_parts.append(piece)

            if pending_bytes is not None:
                if isinstance(pending_parsed, dict) and pending_parsed.get("done") and pending_parsed.get("done_reason") == "length":
                    full_text = "".join(full_response_parts)
                    cleaned = full_text.strip()
                    bounded = trim_to_boundary(cleaned)
                    if bounded:
                        cleaned = bounded.strip()
                    if not cleaned:
                        cleaned = full_text.strip()
                    if cleaned and not cleaned.endswith(END_PUNCT):
                        cleaned = f"{cleaned} ..."

                    original_piece = pending_parsed.get("response") if isinstance(pending_parsed, dict) else ""
                    original_piece = original_piece if isinstance(original_piece, str) else ""

                    tail = ""
                    if cleaned.startswith(full_text):
                        tail = cleaned[len(full_text):]

                    combined_piece = f"{original_piece}{tail}" if original_piece or tail else ""

                    if combined_piece:
                        tail_chunk: Dict[str, Any] = {
                            "response": combined_piece,
                            "done": False,
                        }
                        if isinstance(pending_parsed, dict):
                            for meta_key in ("model", "created_at", "conversation_id", "id"):
                                if meta_key in pending_parsed:
                                    tail_chunk[meta_key] = pending_parsed[meta_key]
                        yield (json.dumps(tail_chunk) + "\n").encode("utf-8")

                    final_chunk = dict(pending_parsed)
                    if isinstance(final_chunk.get("message"), dict):
                        msg = dict(final_chunk["message"])
                        msg["content"] = cleaned
                        final_chunk["message"] = msg

                    final_chunk["response"] = ""
                    yield (json.dumps(final_chunk) + "\n").encode("utf-8")
                    app.logger.info("FINISH stream cutoff tail=%s", tail.strip() if tail else "")
                else:
                    yield pending_bytes
        finally:
            r.close()

    return Response(
        stream_with_context(gen()),
        status=r.status_code,
        headers=resp_headers,
        mimetype=r.headers.get("Content-Type", "application/json"),
    )

def nonstream_upstream(
    method: str,
    path: str,
    *,
    json_body=None,
    headers=None,
    params=None,
    trim_config: Optional[Dict[str, Any]] = None,
):
    url = f"{OLLAMA}{path}"
    r = requests.request(method, url,
                         json=json_body, headers=headers, params=params,
                         stream=False, timeout=(10, READ_TIMEOUT))
    # Pass through content-type, drop content-length if desired
    resp_headers = [(k, v) for k, v in r.headers.items()]
    mimetype = r.headers.get("Content-Type", "application/json")
    payload_bytes = r.content

    if trim_config and "application/json" in (mimetype or "").lower():
        try:
            payload = r.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            modified = False
            if trim_config and apply_short_response_finisher(payload, trim_config):
                modified = True
            if apply_length_cutoff_finisher(payload):
                modified = True
            if modified:
                payload_bytes = json.dumps(payload).encode("utf-8")
                resp_headers = [(k, v) for k, v in resp_headers if k.lower() != "content-length"]

    return Response(payload_bytes, status=r.status_code, headers=resp_headers,
                    mimetype=mimetype)

MODEL_DOWNGRADE = os.getenv("MODEL_DOWNGRADE", "1") == "1"  # toggle via env
SEVEN_B = os.getenv("FALLBACK_7B", "qwen2.5-7b-instruct-q5_K_M")

def maybe_downgrade_model(body, chosen):
    is_short = _as_int(chosen.get("num_predict"), INF) <= 200
    rag = has_rag(body)
    m = (body.get("model") or "")
    if MODEL_DOWNGRADE and is_short and not rag and "14b" in m.lower():
        body["model"] = SEVEN_B
        app.logger.info("DOWNGRADE model 14B -> %s for short prompt", SEVEN_B)
    return body


def should_trim_short(body: Dict[str, Any], chosen: Dict[str, Any], want_stream: bool) -> bool:
    if want_stream:
        return False
    if SHORT_SENTENCES <= 0:
        return False
    if chosen.get("_mode") != "short":
        return False
    if has_rag(body):
        return False
    return True


def compute_trim_config(
    body: Dict[str, Any],
    chosen: Dict[str, Any],
    want_stream: bool,
    client_opts: Dict[str, Any],
    base_predict: int,
) -> Optional[Dict[str, Any]]:
    if not should_trim_short(body, chosen, want_stream):
        return None

    client_limit = _as_int(client_opts.get("num_predict"), INF)
    tail_add = 0
    if TAIL_TOKENS > 0 and base_predict < INF:
        if client_limit == INF:
            tail_add = TAIL_TOKENS
        elif client_limit > base_predict:
            tail_add = min(TAIL_TOKENS, client_limit - base_predict)

    return {
        "sentences": max(1, SHORT_SENTENCES),
        "base_tokens": None if base_predict >= INF else base_predict,
        "tail_tokens": tail_add,
        "chars_per_token": max(0.1, CHARS_PER_TOKEN),
    }


_BOUNDARY_PUNCT = re.compile(r"([\.\!\?。！？]+[\)\]\'\"]?)\s*$")


def trim_to_boundary(text: str) -> str:
    text = (text or "").rstrip()
    if not text:
        return text

    for marker in ("```", "\n\n"):
        idx = text.find(marker)
        if idx != -1:
            return text[:idx].rstrip() or text

    match = _BOUNDARY_PUNCT.search(text)
    if match:
        return text[: match.end(1)].rstrip()

    for punct in ".?!。！？":
        idx = text.rfind(punct)
        if idx != -1:
            return text[: idx + 1].rstrip()

    return text


def finish_short_text(text: str, config: Dict[str, Any]) -> str:
    raw = (text or "").strip()
    if not raw:
        return text

    base_tokens = config.get("base_tokens") or 0
    tail_tokens = config.get("tail_tokens") or 0
    chars_per_token = config.get("chars_per_token") or CHARS_PER_TOKEN
    sentences = config.get("sentences") or SHORT_SENTENCES

    if base_tokens > 0 and chars_per_token > 0:
        window_tokens = base_tokens + max(0, tail_tokens)
        max_chars = int(window_tokens * chars_per_token)
        if max_chars > 0 and len(raw) > max_chars:
            raw = raw[:max_chars].rstrip()

    trimmed = keep_first_sentences(raw, max(1, sentences)).strip()

    if tail_tokens > 0:
        bounded = trim_to_boundary(trimmed)
        if bounded:
            trimmed = bounded

    return trimmed or text


def apply_short_response_finisher(payload: Dict[str, Any], config: Dict[str, Any]) -> bool:
    changed = False

    if "response" in payload and isinstance(payload["response"], str):
        finished = finish_short_text(payload["response"], config)
        if finished != payload["response"]:
            payload["response"] = finished
            changed = True

    message = payload.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        finished = finish_short_text(message["content"], config)
        if finished != message["content"]:
            message["content"] = finished
            changed = True

    if changed:
        app.logger.info(
            "FINISH short reply sentences=%s tail=%s",
            config.get("sentences"),
            config.get("tail_tokens"),
        )
    return changed


def apply_length_cutoff_finisher(payload: Dict[str, Any]) -> bool:
    if payload.get("done_reason") != "length":
        return False

    changed = False

    def _tidy(value: Optional[str]) -> Optional[str]:
        if not isinstance(value, str):
            return value
        trimmed = trim_to_boundary(value)
        if trimmed != value:
            return f"{trimmed} ..."
        if trimmed and not trimmed.endswith(END_PUNCT):
            return f"{trimmed} ..."
        return trimmed

    if "response" in payload:
        cleaned = _tidy(payload.get("response"))
        if cleaned is not None and cleaned != payload.get("response"):
            payload["response"] = cleaned
            changed = True

    message = payload.get("message")
    if isinstance(message, dict) and "content" in message:
        cleaned = _tidy(message.get("content"))
        if cleaned is not None and cleaned != message.get("content"):
            message["content"] = cleaned
            changed = True

    if changed:
        app.logger.info("FINISH cutoff done_reason=length")
    return changed


def handle_model_request(target_path: str) -> Response:
    body = request.get_json(force=True, silent=True) or {}
    chosen = choose_caps(body)
    body = maybe_downgrade_model(body, chosen)

    client_opts = extract_client_options(body)
    final_opts = clamp_options(chosen, client_opts)

    base_predict = _as_int(final_opts.get("num_predict"), INF)
    want_stream = bool(final_opts.get("stream", True))
    trim_config = compute_trim_config(body, chosen, want_stream, client_opts, base_predict)

    # scrub OpenAI top-level knobs so upstream only sees Ollama options
    for k in ("max_tokens", "temperature", "stop", "stream"):
        body.pop(k, None)

    if trim_config:
        tail_tokens = trim_config.get("tail_tokens") or 0
        base_tokens = trim_config.get("base_tokens")
        if tail_tokens and base_tokens and base_tokens < INF:
            final_opts = dict(final_opts)
            final_opts["num_predict"] = base_tokens + tail_tokens
    body["options"] = final_opts

    want_stream = bool(final_opts.get("stream", True))
    body["stream"] = want_stream

    # ✅ inject concise bias for short, non-RAG prompts
    body = inject_concise_system(body, chosen)

    # DEBUG: log what we will actually send upstream
    final_log = {k: final_opts.get(k) for k in ("num_predict", "num_ctx", "temperature", "repeat_penalty")}
    app.logger.info(
        "APPLY model=%s stream=%s chosen=%s final=%s",
        body.get("model"),
        want_stream,
        {k: chosen.get(k) for k in ("_mode", "num_predict", "num_ctx") if k in chosen},
        final_log,
    )

    headers = {"Accept": "application/json"}

    if want_stream:
        return stream_upstream("POST", target_path, json_body=body, headers=headers)

    return nonstream_upstream(
        "POST",
        target_path,
        json_body=body,
        headers=headers,
        trim_config=trim_config,
    )



# ---------- routes ----------
@app.route("/healthz", methods=["GET"])
def health():
    return {"ok": True, "target": OLLAMA}

@app.route("/api/generate", methods=["POST"])
def api_generate():
    return handle_model_request("/api/generate")


@app.route("/api/chat", methods=["POST"])
def api_chat():
    return handle_model_request("/api/chat")



# Passthrough for everything else (e.g., /api/tags, /api/embeddings, etc.)
@app.route("/<path:path>", methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS"])
def passthrough(path):
    headers = {k: v for k, v in request.headers if k.lower() != "host"}
    params  = request.args

    # Forward JSON as JSON; otherwise raw body
    raw = request.get_data(cache=False)
    json_body = None
    if request.is_json:
        try:
            json_body = request.get_json(silent=True)
            raw = None
        except Exception:
            pass

    return stream_upstream(request.method, f"/{path}",
                           json_body=json_body, data=raw,
                           headers=headers, params=params)

# Local dev convenience
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8089, debug=True)


import logging
app.logger.setLevel(logging.INFO)

@app.before_request
def _log_in():
    try:
        b = request.get_json(silent=True) or {}
        app.logger.info("IN %s %s model=%s stream=%s max_tokens=%s opts=%s",
                        request.method, request.path,
                        b.get("model"),
                        b.get("stream") or (b.get("options") or {}).get("stream"),
                        b.get("max_tokens"),
                        {k: (b.get("options") or {}).get(k) for k in ("num_predict","num_ctx","temperature")})
    except Exception:
        app.logger.info("IN %s %s (no json)", request.method, request.path)

@app.after_request
def _log_out(resp):
    app.logger.info("OUT %s %s %s", request.method, request.path, resp.status_code)
    return resp
