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
    "meetings_today_detail": "/scripts/meetings_today_detail/run",
    "fetch_weekend_emails": "/scripts/fetch_weekend_emails/run",
    "email_digest": "/reports/email-digest",
}

_SIMPLE_CALL_RE = re.compile(r"^\s*(?P<name>[A-Za-z_][\w-]*)\s*\(\s*(?P<args>.*)\s*\)\s*$")
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
        name = simple.group("name")
        args = (simple.group("args") or "").strip()
        if not args:
            return (name, {})

        if args.startswith("{") and args.endswith("}"):
            payload = _parse_payload(args)
            if payload is None:
                return None
            return (name, payload)

        if re.fullmatch(r"\d+", args):
            return (name, {"index": int(args)})

        try:
            value = ast.literal_eval(args)
        except Exception:
            value = args.strip("'\"")

        if isinstance(value, dict):
            return (name, value)
        if isinstance(value, (int, float, str)):
            return (name, {"value": value})
        return (name, {"value": str(value)})

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


def _format_clock(dt: datetime) -> str:
    formatted = dt.strftime("%I:%M %p")
    return formatted[1:] if formatted.startswith("0") else formatted


def _format_date(dt: datetime) -> str:
    return dt.strftime("%b %d, %Y").replace(" 0", " ")


def _format_time_range(start_iso: Optional[str], end_iso: Optional[str]) -> str:
    start_dt = _parse_iso(start_iso)
    end_dt = _parse_iso(end_iso)
    if not start_dt and not end_dt:
        return "—"
    if start_dt and end_dt:
        if start_dt.date() == end_dt.date():
            date_label = start_dt.strftime("%b %d").replace(" 0", " ")
            return f"{date_label}, {_format_clock(start_dt)} – {_format_clock(end_dt)}"
        start_label = f"{start_dt.strftime('%b %d, %Y').replace(' 0', ' ')}, {_format_clock(start_dt)}"
        end_label = f"{end_dt.strftime('%b %d, %Y').replace(' 0', ' ')}, {_format_clock(end_dt)}"
        return f"{start_label} → {end_label}"
    dt = start_dt or end_dt
    return f"{dt.strftime('%b %d, %Y').replace(' 0', ' ')}, {_format_clock(dt)}"


def _escape_md(value: Any) -> str:
    text = str(value or "")
    for needle, repl in (
        ("\\", "\\\\"),
        ("`", "\\`"),
        ("*", "\\*"),
        ("_", "\\_"),
        ("{", "\\{"),
        ("}", "\\}"),
        ("[", "\\["),
        ("]", "\\]"),
        ("(", "\\("),
        (")", "\\)"),
        ("#", "\\#"),
        ("+", "\\+"),
        ("-", "\\-"),
        (".", "\\."),
        ("!", "\\!"),
        ("|", "\\|"),
    ):
        text = text.replace(needle, repl)
    return text


def _format_people(values: List[str], *, empty: str = "_None_") -> str:
    if not values:
        return empty
    return ", ".join(f"`{_escape_md(person)}`" for person in values)


def _format_people_list(values: List[str]) -> str:
    if not values:
        return "- None"
    return "\n".join(f"- {_escape_md(person)}" for person in values)


def _format_blockquote(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return ""
    lines = [line.rstrip() for line in cleaned.splitlines()]
    return "\n".join(f"> {_escape_md(line) or ' '}" for line in lines)


def _render_meetings_summary(events: List[Dict[str, Any]]) -> str:
    if not events:
        return (
            "### 📅 Meetings Today\n\n"
            "> No meetings scheduled for today. Enjoy the breathing room!"
        )

    first_with_start = next((ev for ev in events if ev.get("start")), None)
    dt = _parse_iso(first_with_start.get("start")) if first_with_start else None
    heading = f"Meetings for {dt.strftime('%A, %B %d').replace(' 0', ' ')}" if dt else "Today's Meetings"

    total = len(events)
    earliest = _parse_iso(events[0].get("start"))
    start_label = _format_clock(earliest) if earliest else "—"

    generated = datetime.now(timezone.utc).astimezone()
    generated_label = _format_clock(generated)
    generated_date = _format_date(generated)

    rows: List[str] = []
    for event in events:
        ordinal = int(event.get("ordinal") or len(rows) + 1)
        time_range = _escape_md(_format_time_range(event.get("start"), event.get("end")))
        title = _escape_md(event.get("title") or "Untitled Meeting")
        summary = event.get("summary") or ""
        summary_block = f" — _{_escape_md(summary)}_" if summary else ""
        organizer = _escape_md(event.get("organizer") or "—")

        required_trimmed = event.get("required_attendees") or []
        required_full = event.get("required_attendees_full") or required_trimmed
        overflow = max(len(required_full) - len(required_trimmed), 0)
        required_text = _format_people(required_trimmed)
        if overflow:
            required_text = f"{required_text} +{overflow} more"

        optional_count = len(event.get("optional_attendees_full") or [])
        optional_fragment = f" _(optional attendees: {optional_count})_" if optional_count else ""
        command_hint = f"`meetings_today_detail({ordinal})`"

        session_cell = f"**{title}**{summary_block}{optional_fragment}"

        rows.append(
            f"| {ordinal:02d} | {time_range} | {session_cell} | {organizer} | {required_text} | {command_hint} |"
        )

    table_header = (
        "| # | Time | Session | Organizer | Required | Detail |\n"
        "|---|------|---------|-----------|----------|--------|\n"
    )
    table_rows = "\n".join(rows)

    intro = (
        f"### 📅 {heading}\n"
        f"> Meetings scheduled: **{total}** | First start: **{start_label}** | Generated: **{generated_label}**, {generated_date}\n\n"
    )

    footer = (
        "\n_Run `meetings_today_detail(<number>)` to fetch the expanded view for any row._\n"
        "\n_Provided by macOS Actions • Meetings Today_\n"
    )

    return f"{intro}{table_header}{table_rows}{footer}"


def _render_meeting_detail(event: Dict[str, Any]) -> str:
    ordinal = event.get("ordinal")
    title = _escape_md(event.get("title") or "Untitled Meeting")
    time_range = _escape_md(_format_time_range(event.get("start"), event.get("end")))
    organizer = _escape_md(event.get("organizer") or "—")
    calendar = _escape_md(event.get("calendar") or "—")
    location = _escape_md(event.get("location") or "—")
    is_all_day = bool(event.get("is_all_day"))
    url = event.get("url")

    header = f"### 🗒️ Meeting Detail #{ordinal}\n\n**{title}**\n"

    meta_lines = [
        f"- **When:** {time_range}",
        f"- **Organizer:** {organizer}",
        f"- **Calendar:** {calendar}",
        f"- **Location:** {location or '_Not set_'}",
        f"- **All-day:** {'Yes' if is_all_day else 'No'}",
    ]

    required_full = event.get("required_attendees_full") or []
    optional_full = event.get("optional_attendees_full") or []

    attendees_section = "\n".join(
        [
            "\n**Required attendees**",
            _format_people_list(required_full),
            "\n**Optional attendees**",
            _format_people_list(optional_full),
        ]
    )

    notes = event.get("notes") or ""
    notes_section = ""
    if notes.strip():
        notes_section = "\n**Notes**\n" + _format_blockquote(notes)

    url_section = f"\n[Open meeting link]({url})" if url else ""

    parts = [header, *meta_lines, attendees_section, notes_section, url_section]
    return "\n".join(part for part in parts if part).strip()


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
            ok_flag = data.get("ok", True)
            parsed = data.get("parsed")
            stdout = data.get("stdout")
            stderr = data.get("stderr")

            if script in {"meetings_today", "meetings_today_detail"} and isinstance(parsed, dict):
                payload_ok = parsed.get("ok", True)
                if not (ok_flag and payload_ok):
                    error_body = parsed.get("error") or stdout or json.dumps(data, indent=2, ensure_ascii=False)
                    if stderr:
                        error_body = f"{error_body}\n\n[stderr]\n{stderr}"
                    return f"{heading} (failed)\n\n{error_body}"

                if script == "meetings_today":
                    events = parsed.get("events") or []
                    return f"{heading}\n\n{_render_meetings_summary(events)}"

                event_detail = parsed.get("event")
                if isinstance(event_detail, dict):
                    return f"{heading}\n\n{_render_meeting_detail(event_detail)}"
                return f"{heading}\n\n_No meeting detail available._"

            if parsed is not None:
                body = _pretty(parsed)
            elif stdout:
                body = stdout
            else:
                body = json.dumps(data, indent=2, ensure_ascii=False)

            if stderr:
                body = f"{body}\n\n[stderr]\n{stderr}"

            if not ok_flag:
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
