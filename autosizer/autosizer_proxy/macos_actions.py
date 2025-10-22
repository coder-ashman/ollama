from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

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


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def _format_time_range(start_iso: Optional[str], end_iso: Optional[str]) -> str:
    start_dt = _parse_iso(start_iso)
    end_dt = _parse_iso(end_iso)
    if not start_dt and not end_dt:
        return "—"
    if start_dt and end_dt:
        if start_dt.date() == end_dt.date():
            date_label = start_dt.strftime('%b %d').replace(' 0', ' ')
            return f"{date_label}, {_format_clock(start_dt)} – {_format_clock(end_dt)}"
        start_label = f"{start_dt.strftime('%b %d, %Y').replace(' 0', ' ')}, {_format_clock(start_dt)}"
        end_label = f"{end_dt.strftime('%b %d, %Y').replace(' 0', ' ')}, {_format_clock(end_dt)}"
        return f"{start_label} → {end_label}"
    dt = start_dt or end_dt
    return f"{dt.strftime('%b %d, %Y').replace(' 0', ' ')}, {_format_clock(dt)}"


def _format_clock(dt: datetime) -> str:
    formatted = dt.strftime("%I:%M %p")
    return formatted[1:] if formatted.startswith("0") else formatted


def _format_date(dt: datetime) -> str:
    return dt.strftime("%b %d, %Y").replace(" 0", " ")


def _badge_list(values: List[str], variant: str) -> str:
    if not values:
        return '<span class="text-muted">None</span>'
    badges = "".join(f'<span class="badge bg-{variant} me-1 mb-1">{_escape_html(v)}</span>' for v in values)
    return badges


def _escape_html(value: Any) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def _render_meetings_table(events: List[Dict[str, Any]]) -> str:
    if not events:
        return """
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
<style>
  .agenda-shell{max-width:900px;margin:32px auto;font-family:"Inter","SF Pro Display",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;}
  .agenda-empty{border-radius:20px;border:1px solid rgba(255,255,255,0.08);background:linear-gradient(135deg,#1d2331,#111521);padding:32px;text-align:center;box-shadow:0 24px 48px rgba(8,15,45,0.45);color:#e2e8f0;}
  .agenda-empty h5{font-weight:600;margin-bottom:12px;}
  .agenda-empty p{color:#94a3b8;margin:0;font-size:0.95rem;}
</style>
<div class="agenda-shell">
  <div class="agenda-empty">
    <h5>No meetings scheduled for today 🎉</h5>
    <p>Enjoy the breathing room—nothing else is booked on the calendar.</p>
  </div>
</div>
""".strip()

    def agenda_heading(events: List[Dict[str, Any]]) -> str:
        first = next((ev for ev in events if ev.get("start")), None)
        dt = _parse_iso(first.get("start")) if first else None
        if not dt:
            return "Today's Meetings"
        return f"Meetings for {dt.strftime('%A, %B %d').replace(' 0', ' ')}"

    heading = agenda_heading(events)
    total = len(events)
    earliest = _parse_iso(events[0].get("start"))
    start_label = _format_clock(earliest) if earliest else "—"

    rows = []
    for idx, event in enumerate(events, start=1):
        title = _escape_html(event.get("title") or "Untitled Meeting")
        organizer = _escape_html(event.get("organizer") or "—")
        summary = _escape_html(event.get("summary") or "")
        time_range = _format_time_range(event.get("start"), event.get("end"))
        required_html = _badge_list(event.get("required_attendees") or [], "primary")
        optional_html = _badge_list(event.get("optional_attendees") or [], "secondary")

        summary_block = f'<div class="agenda-summary">{summary}</div>' if summary else ""

        rows.append(
            f"""
        <tr>
          <td class="align-middle text-muted small" data-label="#">#{idx:02d}</td>
          <td class="align-middle agenda-time fw-semibold" data-label="Time">{time_range}</td>
          <td class="align-middle" data-label="Session">
            <div class="agenda-title">{title}</div>
            {summary_block}
          </td>
          <td class="align-middle agenda-owner" data-label="Organizer">{organizer}</td>
          <td class="align-middle" data-label="Required">{required_html}</td>
          <td class="align-middle" data-label="Optional">{optional_html}</td>
        </tr>
        """.strip()
        )

    generated = datetime.now(timezone.utc).astimezone()
    generated_label = _format_clock(generated)
    generated_date = _format_date(generated)

    table_html = "\n".join(rows)
    return f"""
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
<style>
  .agenda-shell{{max-width:1000px;margin:32px auto;font-family:"Inter","SF Pro Display",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#e2e8f0;}}
  .agenda-card{{border-radius:24px;background:radial-gradient(circle at 20% 20%,rgba(122,162,255,0.16),transparent 55%),linear-gradient(140deg,#111827,#0b101d);border:1px solid rgba(148,163,184,0.18);box-shadow:0 30px 60px rgba(7,11,30,0.45);overflow:hidden;}}
  .agenda-header{{padding:24px 28px 20px;border-bottom:1px solid rgba(148,163,184,0.18);}}
  .agenda-title{{font-size:1.1rem;font-weight:600;color:#f8fafc;}}
  .agenda-summary{{color:#94a3b8;font-size:0.9rem;margin-top:6px;}}
  .agenda-meta{{display:flex;gap:16px;flex-wrap:wrap;color:#94a3b8;font-size:0.85rem;margin-top:10px;}}
  .agenda-meta .chip{{display:inline-flex;align-items:center;gap:8px;padding:6px 12px;border-radius:999px;background:rgba(15,23,42,0.65);border:1px solid rgba(148,163,184,0.18);}}
  .agenda-meta .chip strong{{color:#f8fafc;font-weight:600;}}
  .agenda-table{{background:rgba(15,23,42,0.78);}}
  .agenda-table thead th{{background:rgba(148,163,184,0.08);border-bottom:1px solid rgba(148,163,184,0.2);color:#94a3b8;font-size:0.75rem;letter-spacing:0.05em;text-transform:uppercase;}}
  .agenda-table tbody tr{{border-bottom:1px solid rgba(148,163,184,0.14);}}
  .agenda-table tbody tr:last-child{{border-bottom:none;}}
  .agenda-table td{{padding:16px 18px;vertical-align:middle;}}
  .agenda-table tbody tr:hover{{background:rgba(59,130,246,0.08);}}
  .agenda-time{{font-size:0.95rem;}}
  .agenda-owner{{color:#cbd5f5;font-size:0.9rem;}}
  .badge.bg-primary{{background:rgba(59,130,246,0.25)!important;color:#9cbdfc;border:1px solid rgba(59,130,246,0.55);}}
  .badge.bg-secondary{{background:rgba(148,163,184,0.2)!important;color:#e2e8f0;border:1px solid rgba(148,163,184,0.4);}}
  .agenda-footer{{padding:18px 28px;border-top:1px solid rgba(148,163,184,0.18);display:flex;justify-content:space-between;align-items:center;font-size:0.82rem;color:#94a3b8;}}
  .agenda-footer .stat{{display:flex;align-items:center;gap:8px;}}
  @media (max-width: 768px){{ 
    .agenda-table thead{{display:none;}}
    .agenda-table tbody tr{{display:block;padding:20px 18px;}}
    .agenda-table tbody td{{display:flex;justify-content:space-between;border-bottom:1px solid rgba(148,163,184,0.12);padding:8px 0;}}
    .agenda-table tbody td::before{{content:attr(data-label);font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:0.04em;}}
    .agenda-table tbody td:last-child{{border-bottom:none;}}
    .agenda-meta{{flex-direction:column;align-items:flex-start;}}
  }}
</style>
<div class="agenda-shell">
  <div class="agenda-card">
    <div class="agenda-header">
      <h4 class="mb-2 text-uppercase text-muted small" style="letter-spacing:0.08em;">Calendar Snapshot</h4>
      <h2 class="mb-1" style="font-weight:700;color:#f8fafc;">{heading}</h2>
      <div class="agenda-meta">
        <span class="chip"><span class="badge bg-primary">{total}</span><strong>Meetings</strong></span>
        <span class="chip"><strong>First start</strong> {start_label}</span>
        <span class="chip"><strong>Generated</strong> {generated_label} • {generated_date}</span>
      </div>
    </div>
    <div class="table-responsive agenda-table">
      <table class="table table-dark table-hover mb-0">
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">Time</th>
            <th scope="col">Session</th>
            <th scope="col">Organizer</th>
            <th scope="col">Required</th>
            <th scope="col">Optional</th>
          </tr>
        </thead>
        <tbody>
          {table_html}
        </tbody>
      </table>
    </div>
    <div class="agenda-footer">
      <span class="stat">macOS Actions • Meetings Today</span>
      <span class="stat">Powered by your local gateway</span>
    </div>
  </div>
</div>
""".strip()

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

            if script == "meetings_today" and isinstance(parsed, dict):
                events = parsed.get("events")
                if isinstance(events, list):
                    if not ok:
                        error_body = stdout or json.dumps(data, indent=2, ensure_ascii=False)
                        if stderr:
                            error_body = f"{error_body}\n\n[stderr]\n{stderr}"
                        return f"{heading} (failed)\n\n{error_body}"
                    return _render_meetings_table(events)

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
