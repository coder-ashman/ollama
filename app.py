import os, json
from flask import Flask, request, Response, stream_with_context
import requests
import re

# ---------- config ----------
OLLAMA = os.environ.get("TARGET_OLLAMA", "http://ollama:11434")
READ_TIMEOUT = float(os.environ.get("UPSTREAM_TIMEOUT", "300"))  # seconds

SHORT_MAX  = int(os.environ.get("SHORT_MAX_WORDS",  "12"))
NORMAL_MAX = int(os.environ.get("NORMAL_MAX_WORDS", "60"))

# Reasonable defaults; caller-specified options still win
CAP_SHORT  = json.loads(os.environ.get(
    "CAP_SHORT",
    '{"num_predict":160,"num_ctx":1024,"temperature":0.6,"repeat_penalty":1.2", "stop": ["<|im_end|>"]}'
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
_SENT_SPLIT = re.compile(r'(?<=[\.!\?。！？])\s+')
INF = 10**9

# ---------- helpers ----------
def keep_first_sentences(text: str, n: int = 2) -> str:
    parts = _SENT_SPLIT.split(text.strip())
    if not parts:
        return text
    return " ".join(parts[:n])


def choose_caps(body: dict):
    """Pick caps based on prompt length or RAG signals."""
    prompt = (body.get("prompt") or "").strip()
    if not prompt and isinstance(body.get("messages"), list):
        # crude collapse of user messages for chat payloads
        prompt = " ".join(m.get("content", "") for m in body["messages"] if m.get("role") == "user")

    # If caller attached collections/files, assume deeper answer
    if body.get("files") or body.get("collection") or body.get("collections"):
        return CAP_DEEP

    n = len(prompt.split())
    if n <= SHORT_MAX:   return CAP_SHORT
    if n <= NORMAL_MAX:  return CAP_NORMAL
    return CAP_DEEP


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


# at top of app.py (keep your existing imports)
DEFAULT_SYSTEM_SHORT = os.getenv(
    "DEFAULT_SYSTEM_SHORT",
    "Be brief. Answer in 1–3 sentences unless asked for more."
)

def inject_concise_system(body: dict, chosen: dict) -> dict:
    """Prepend a concise system message for short, non-RAG prompts if none exists."""
    # short cap?
    if int(chosen.get("num_predict", 0)) > 200:
        return body
    # RAG on? (collections/files attached) → do not constrain
    if body.get("files") or body.get("collection") or body.get("collections"):
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
    """Proxy to Ollama with chunked streaming; no full buffering."""
    url = f"{OLLAMA}{path}"
    r = requests.request(
        method, url,
        json=json_body, data=data,
        headers=headers, params=params,
        stream=True,
        timeout=(10, READ_TIMEOUT)  # (connect, read)
    )

    # Drop content-length so chunked transfer works
    resp_headers = [(k, v) for k, v in r.headers.items() if k.lower() != "content-length"]

    def gen():
        try:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        finally:
            r.close()

    return Response(
        stream_with_context(gen()),
        status=r.status_code,
        headers=resp_headers,
        mimetype=r.headers.get("Content-Type", "application/json")
    )

def nonstream_upstream(method: str, path: str, *, json_body=None, headers=None, params=None):
    url = f"{OLLAMA}{path}"
    r = requests.request(method, url,
                         json=json_body, headers=headers, params=params,
                         stream=False, timeout=(10, READ_TIMEOUT))
    # Pass through content-type, drop content-length if desired
    resp_headers = [(k, v) for k, v in r.headers.items()]
    return Response(r.content, status=r.status_code, headers=resp_headers,
                    mimetype=r.headers.get("Content-Type", "application/json"))

MODEL_DOWNGRADE = os.getenv("MODEL_DOWNGRADE", "1") == "1"  # toggle via env
SEVEN_B = os.getenv("FALLBACK_7B", "qwen2.5-7b-instruct-q5_K_M")

def maybe_downgrade_model(body, chosen):
    is_short = _as_int(chosen.get("num_predict"), INF) <= 200
    has_rag  = bool(body.get("files") or body.get("collection") or body.get("collections"))
    m = (body.get("model") or "")
    if MODEL_DOWNGRADE and is_short and not has_rag and "14b" in m.lower():
        body["model"] = SEVEN_B
        app.logger.info("DOWNGRADE model 14B -> %s for short prompt", SEVEN_B)
    return body



# ---------- routes ----------
@app.route("/healthz", methods=["GET"])
def health():
    return {"ok": True, "target": OLLAMA}

@app.route("/api/generate", methods=["POST"])
def api_generate():
    body   = request.get_json(force=True, silent=True) or {}
    chosen = choose_caps(body)
    body = maybe_downgrade_model(body, chosen)

    client_opts = extract_client_options(body)
    final_opts  = clamp_options(chosen, client_opts)

    # scrub OpenAI top-level knobs so upstream only sees Ollama options
    for k in ("max_tokens", "temperature", "stop", "stream"):
        body.pop(k, None)

    body["options"] = final_opts
    want_stream = bool(final_opts.get("stream", True))
    body["stream"] = want_stream

    # ✅ inject concise bias for short, non-RAG prompts
    body = inject_concise_system(body, chosen)

    # DEBUG: log what we will actually send upstream
    app.logger.info("APPLY model=%s stream=%s chosen=%s final=%s",
        body.get("model"), want_stream, chosen,
        {k: final_opts.get(k) for k in ("num_predict","num_ctx","temperature","repeat_penalty")})


    if want_stream:
        # stream pass-through
        return stream_upstream("POST", "/api/generate",
            json_body=body, headers={"Accept":"application/json"})
    else:
        # single JSON object (no streaming)
        return nonstream_upstream("POST", "/api/generate",
            json_body=body, headers={"Accept":"application/json"})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    body   = request.get_json(force=True, silent=True) or {}
    chosen = choose_caps(body)
    body = maybe_downgrade_model(body, chosen)

    client_opts = extract_client_options(body)
    final_opts  = clamp_options(chosen, client_opts)

    # scrub OpenAI top-level knobs so upstream only sees Ollama options
    for k in ("max_tokens", "temperature", "stop", "stream"):
        body.pop(k, None)

    body["options"] = final_opts
    want_stream = bool(final_opts.get("stream", True))
    body["stream"] = want_stream

    # ✅ inject concise bias for short, non-RAG prompts
    body = inject_concise_system(body, chosen)

    # DEBUG: log what we will actually send upstream
    app.logger.info("APPLY model=%s stream=%s chosen=%s final=%s",
        body.get("model"), want_stream, chosen,
        {k: final_opts.get(k) for k in ("num_predict","num_ctx","temperature","repeat_penalty")})


    if want_stream:
        return stream_upstream("POST", "/api/chat",
            json_body=body, headers={"Accept":"application/json"})
    else:
        return nonstream_upstream("POST", "/api/chat",
            json_body=body, headers={"Accept":"application/json"})



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