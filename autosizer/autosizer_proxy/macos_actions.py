from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import requests
from flask import Response, current_app

from .config import OSX_ACTIONS_BASE, OSX_ACTIONS_KEY, OSX_ACTIONS_TIMEOUT

_ENDPOINTS = {
    "fetch_yesterday_emails": "/scripts/fetch_yesterday_emails/run",
    "unread_last_hour": "/scripts/unread_last_hour/run",
    "meetings_today": "/scripts/meetings_today/run",
    "fetch_weekend_emails": "/scripts/fetch_weekend_emails/run",
    "email_digest": "/reports/email-digest",
}

_SIMPLE_CALL_RE = re.compile(r"^\s*(?P<name>[A-Za-z_][\w-]*)\s*\(\s*\)\s*$")
_CALL_SCRIPT_RE = re.compile(
    r'^\s*call_script\s*\(\s*(?P<quote>["\'])(?P<name>[\w-]+)(?P=quote)\s*(?:,\s*(?P<payload>\{.*\}))?\s*\)\s*$',
    re.DOTALL,
)


def _logger():
    return current_app.logger


def _base_url() -> Optional[str]:
    if not OSX_ACTIONS_BASE:
        return None
    return OSX_ACTIONS_BASE


def _lookup_script(script: str) -> Optional[Tuple[str, str]]:
    if not script:
        return None
    key = script.strip().lower()
    endpoint = _ENDPOINTS.get(key)
    if not endpoint:
        return None
    return key, endpoint


def _invoke_script(script: str, payload: Optional[Dict[str, Any]] = None) -> Tuple[int, str, bytes, Optional[str]]:
    base = _base_url()
    if not base:
        return (
            503,
            "application/json",
            json.dumps({"error": "macos_actions gateway not configured"}).encode("utf-8"),
            None,
        )

    lookup = _lookup_script(script)
    if not lookup:
        return (
            404,
            "application/json",
            json.dumps({"error": f"unknown script '{script}'"}).encode("utf-8"),
            None,
        )

    normalized, endpoint = lookup

    if not OSX_ACTIONS_KEY:
        return (
            503,
            "application/json",
            json.dumps({"error": "macos_actions key not configured"}).encode("utf-8"),
            normalized,
        )

    url = f"{base}{endpoint}"
    headers = {
        "X-API-Key": OSX_ACTIONS_KEY,
        "Content-Type": "application/json",
    }

    try:
        upstream = requests.post(
            url,
            json=payload or {},
            headers=headers,
            timeout=OSX_ACTIONS_TIMEOUT,
        )
    except requests.RequestException as exc:
        _logger().error("macos_actions request failed: %s", exc)
        return (
            502,
            "application/json",
            json.dumps({"error": "macos_actions upstream unavailable"}).encode("utf-8"),
            normalized,
        )

    mimetype = upstream.headers.get("Content-Type", "application/json")
    return upstream.status_code, mimetype or "application/json", upstream.content, normalized


def call_script(script: str, payload: Optional[Dict[str, Any]] = None) -> Response:
    status, mimetype, content, _ = _invoke_script(script, payload)
    return Response(content, status=status, mimetype=mimetype)


def _extract_script_call(body: Dict[str, Any]) -> Optional[Tuple[str, Dict[str, Any]]]:
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return None

    last = messages[-1]
    if not isinstance(last, dict):
        return None

    role = last.get("role", "user")
    if role != "user":
        return None

    content = last.get("content")
    if isinstance(content, str):
        return _parse_script_command(content)

    return None


def _parse_script_command(content: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    text = (content or "").strip()
    if not text:
        return None

    match = _CALL_SCRIPT_RE.match(text)
    if match:
        name = match.group("name")
        payload_text = match.group("payload")
        payload: Dict[str, Any] = {}
        if payload_text:
            payload = _parse_payload(payload_text)
            if payload is None:
                return None
        return (name, payload)

    simple = _SIMPLE_CALL_RE.match(text)
    if simple:
        return (simple.group("name"), {})

    return None


def _parse_payload(raw_payload: str) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(raw_payload)
    except json.JSONDecodeError:
        try:
            data = ast.literal_eval(raw_payload)
        except Exception:
            _logger().warning("Failed to parse payload for macos_actions call")
            return None

    if isinstance(data, dict):
        return data

    return {"value": data}


def _pretty(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2, ensure_ascii=False)
    return str(value)


def _format_script_message(script: str, status: int, mimetype: str, payload_bytes: bytes) -> str:
    decoded = payload_bytes.decode("utf-8", errors="replace").strip()
    heading = f"macOS Actions :: {script}"

    if status != 200:
        details = decoded or "No details provided."
        return f"{heading} (HTTP {status})\n\n{details}"

    if "json" in (mimetype or "").lower():
        try:
            data = json.loads(decoded or "{}")
        except json.JSONDecodeError:
            data = None

        if isinstance(data, dict):
            ok = data.get("ok", True)
            parsed = data.get("parsed")
            stdout = data.get("stdout")
            stderr = data.get("stderr")

            if parsed is not None:
                body = _pretty(parsed)
            elif stdout:
                body = stdout
            else:
                body = json.dumps(data, indent=2, ensure_ascii=False)

            if stderr:
                body = f"{body}\n\n[stderr]\n{stderr}"

            if not ok:
                heading = f"{heading} (failed)"

            return f"{heading}\n\n{body.strip() or '[no output]'}"

    body_text = decoded or "[no output]"
    return f"{heading}\n\n{body_text}"


def _chat_response(content: str, model: Optional[str]) -> Response:
    payload = {
        "model": model or "macos_actions",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "message": {"role": "assistant", "content": content},
        "done": True,
    }
    return Response(json.dumps(payload), mimetype="application/json")


def maybe_handle_chat(body: Dict[str, Any]) -> Optional[Response]:
    extraction = _extract_script_call(body)
    if not extraction:
        return None

    script, payload = extraction
    status, mimetype, content, normalized = _invoke_script(script, payload)
    script_name = normalized or script
    message = _format_script_message(script_name, status, mimetype, content)
    return _chat_response(message, body.get("model"))


__all__ = ["call_script", "maybe_handle_chat"]
