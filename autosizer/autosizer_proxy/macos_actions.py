from __future__ import annotations

import json
from typing import Any, Dict, Optional

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


def _logger():
    return current_app.logger


def _base_url() -> Optional[str]:
    if not OSX_ACTIONS_BASE:
        return None
    return OSX_ACTIONS_BASE


def call_script(script: str, payload: Optional[Dict[str, Any]] = None) -> Response:
    base = _base_url()
    if not base:
        return Response(
            json.dumps({"error": "macos_actions gateway not configured"}),
            status=503,
            mimetype="application/json",
        )

    endpoint = _ENDPOINTS.get(script)
    if not endpoint:
        return Response(
            json.dumps({"error": f"unknown script '{script}'"}),
            status=404,
            mimetype="application/json",
        )

    if not OSX_ACTIONS_KEY:
        return Response(
            json.dumps({"error": "macos_actions key not configured"}),
            status=503,
            mimetype="application/json",
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
        return Response(
            json.dumps({"error": "macos_actions upstream unavailable"}),
            status=502,
            mimetype="application/json",
        )

    mimetype = upstream.headers.get("Content-Type", "application/json")
    return Response(upstream.content, status=upstream.status_code, mimetype=mimetype)


__all__ = ["call_script"]
