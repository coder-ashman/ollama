import json
from typing import Any, Dict, Optional

import requests
from flask import Response, current_app, request, stream_with_context

from .caps import (
    clamp_options,
    compute_trim_config,
    extract_client_options,
    maybe_downgrade_model,
    safe_int,
    choose_caps,
)
from .config import INF, OLLAMA, READ_TIMEOUT
from .finishers import (
    END_PUNCT,
    apply_length_cutoff_finisher,
    apply_short_response_finisher,
    trim_to_boundary,
)
from .prompts import inject_concise_system


def _logger():
    return current_app.logger


def stream_upstream(method: str, path: str, *, json_body=None, data=None, headers=None, params=None):
    url = f"{OLLAMA}{path}"
    r = requests.request(
        method,
        url,
        json=json_body,
        data=data,
        headers=headers,
        params=params,
        stream=True,
        timeout=(10, READ_TIMEOUT),
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
                    _logger().info("FINISH stream cutoff tail=%s", tail.strip() if tail else "")
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
    r = requests.request(
        method,
        url,
        json=json_body,
        headers=headers,
        params=params,
        stream=False,
        timeout=(10, READ_TIMEOUT),
    )

    resp_headers = [(k, v) for k, v in r.headers.items()]
    mimetype = r.headers.get("Content-Type", "application/json")
    payload_bytes = r.content

    if "application/json" in (mimetype or "").lower():
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

    return Response(payload_bytes, status=r.status_code, headers=resp_headers, mimetype=mimetype)


def _scrub_openai_options(body: Dict[str, Any]) -> None:
    for key in ("max_tokens", "temperature", "stop", "stream"):
        body.pop(key, None)


def handle_model_request(target_path: str) -> Response:
    body = request.get_json(force=True, silent=True) or {}
    chosen = choose_caps(body)
    body = maybe_downgrade_model(body, chosen)

    client_opts = extract_client_options(body)
    final_opts = clamp_options(chosen, client_opts)

    base_predict = safe_int(final_opts.get("num_predict"), INF)
    want_stream = bool(final_opts.get("stream", True))
    trim_config = compute_trim_config(body, chosen, want_stream, client_opts, base_predict)

    _scrub_openai_options(body)

    if trim_config:
        tail_tokens = trim_config.get("tail_tokens") or 0
        base_tokens = trim_config.get("base_tokens")
        if tail_tokens and base_tokens and base_tokens < INF:
            final_opts = dict(final_opts)
            final_opts["num_predict"] = base_tokens + tail_tokens

    body["options"] = final_opts
    want_stream = bool(final_opts.get("stream", True))
    body["stream"] = want_stream

    body = inject_concise_system(body, chosen)

    final_log = {k: final_opts.get(k) for k in ("num_predict", "num_ctx", "temperature", "repeat_penalty")}
    _logger().info(
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


def passthrough_request(path: str) -> Response:
    headers = {k: v for k, v in request.headers if k.lower() != "host"}
    params = request.args

    raw = request.get_data(cache=False)
    json_body = None
    if request.is_json:
        try:
            json_body = request.get_json(silent=True)
            raw = None
        except Exception:
            pass

    return stream_upstream(
        request.method,
        f"/{path}",
        json_body=json_body,
        data=raw,
        headers=headers,
        params=params,
    )


__all__ = [
    "handle_model_request",
    "passthrough_request",
]
