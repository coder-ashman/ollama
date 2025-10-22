from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Response, current_app

from .config import (
    CAP_DEEP,
    FALLBACK_7B,
    OLLAMA,
    OSX_ACTIONS_BASE,
    OSX_ACTIONS_KEY,
    OSX_ACTIONS_TIMEOUT,
    READ_TIMEOUT,
)

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
            json={"params": payload or {}},
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

        if name == "unread_last_hour" and re.fullmatch(r"\d{1,2}", args):
            return (name, {"hours": args.zfill(2)})

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


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_EMAIL_PREFIX_RE = re.compile(r"^(?:(re|fw|fwd|sv|aw|antwort|ref|rv)\s*[:：]\s*)+", re.IGNORECASE)
_EMAIL_BRACKET_RE = re.compile(r"<([^>]+)>")


def _strip_html(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    text = _HTML_TAG_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def _normalize_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _extract_event(payload: Any) -> Optional[Dict[str, Any]]:
    if isinstance(payload, dict):
        event = payload.get("event")
        if isinstance(event, dict):
            return event
        if all(key in payload for key in ("title", "start", "end")):
            return payload
    return None


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
    cleaned = [_strip_html(val) for val in values if _strip_html(val)]
    if not cleaned:
        return empty
    return ", ".join(f"`{_escape_md(person)}`" for person in cleaned)


def _format_people_list(values: List[str]) -> str:
    cleaned = [_strip_html(val) for val in values if _strip_html(val)]
    if not cleaned:
        return "- None"
    return "\n".join(f"- {_escape_md(person)}" for person in cleaned)


def _format_blockquote(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return ""
    lines = [line.rstrip() for line in cleaned.splitlines()]
    return "\n".join(f"> {_escape_md(line) or ' '}" for line in lines)


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


def _extract_email_window(payload: Dict[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    window = payload.get("window")
    if not isinstance(window, dict):
        return {}

    start_raw = window.get("start")
    end_raw = window.get("end")
    hours_back_val = window.get("hours_back")

    start_clean = _strip_html(start_raw)
    end_clean = _strip_html(end_raw)
    hours_back = _coerce_int(hours_back_val)

    return {
        "start_raw": str(start_raw) if start_raw is not None else "",
        "end_raw": str(end_raw) if end_raw is not None else "",
        "start": start_clean,
        "end": end_clean,
        "hours_back": hours_back,
    }


def _canonical_subject(subject: Any) -> str:
    cleaned = _strip_html(subject)
    if not cleaned:
        return "(no subject)"
    candidate = cleaned.strip()
    # Remove common reply/forward prefixes while preserving inner text.
    loop_guard = 0
    while True:
        loop_guard += 1
        if loop_guard > 5:
            break
        match = _EMAIL_PREFIX_RE.match(candidate)
        if not match:
            break
        candidate = candidate[match.end():].lstrip()
    candidate = re.sub(r"\s+", " ", candidate).strip()
    return candidate.lower() or "(no subject)"


def _excerpt(text: Any, limit: int = 480) -> str:
    cleaned = _strip_html(text)
    if not cleaned:
        return ""
    normalized = re.sub(r"\s+", " ", cleaned).strip()
    if len(normalized) <= limit:
        return normalized
    trimmed = normalized[: max(0, limit - 3)].rstrip()
    return f"{trimmed}..."


def _dedupe_people(values: List[Any]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        label = _strip_html(value)
        if not label:
            continue
        tokens = _candidate_identity_tokens(label)
        if not tokens:
            token_key = _normalize_name(label) or label.lower()
            tokens = [token_key]
        key = next((token for token in tokens if token), None)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(label)
    return result


def _candidate_identity_tokens(value: Any) -> List[str]:
    text = str(value or "")
    if not text:
        return []
    tokens: List[str] = []
    stripped = text.strip()
    normalized = _normalize_name(stripped)
    if normalized:
        tokens.append(normalized)
    bracket_match = _EMAIL_BRACKET_RE.search(stripped)
    if bracket_match:
        bracket_content = bracket_match.group(1)
        if bracket_content:
            normalized_bracket = _normalize_name(bracket_content)
            if normalized_bracket:
                tokens.append(normalized_bracket)
            if "@" in bracket_content:
                local = bracket_content.split("@", 1)[0]
                local_norm = _normalize_name(local)
                if local_norm:
                    tokens.append(local_norm)
    if "@" in stripped:
        local = stripped.split("@", 1)[0]
        local_norm = _normalize_name(local)
        if local_norm:
            tokens.append(local_norm)
    tokens = [token for token in tokens if token]
    # Preserve order while deduplicating.
    seen_tokens: set[str] = set()
    ordered: List[str] = []
    for token in tokens:
        if token in seen_tokens:
            continue
        seen_tokens.add(token)
        ordered.append(token)
    return ordered


def _is_self_identifier(value: Any) -> bool:
    tokens = _candidate_identity_tokens(value)
    if not tokens:
        return False
    for ident in _SELF_IDENTIFIERS:
        if not ident:
            continue
        if any(token == ident for token in tokens):
            return True
    return False


def _prepare_email_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    prepared: List[Dict[str, Any]] = []
    for idx, raw in enumerate(messages, start=1):
        subject_raw = raw.get("subject") if isinstance(raw, dict) else None
        subject_clean = _strip_html(subject_raw) or "(No Subject)"
        canonical = _canonical_subject(subject_raw)
        sender = _strip_html(raw.get("sender") if isinstance(raw, dict) else "")

        to_values = raw.get("to_recipients") if isinstance(raw, dict) else None
        cc_values = raw.get("cc_recipients") if isinstance(raw, dict) else None
        if not isinstance(to_values, list):
            to_values = []
        if not isinstance(cc_values, list):
            cc_values = []

        prepared.append(
            {
                "index": idx,
                "subject": subject_clean,
                "canonical_subject": canonical,
                "sender": sender,
                "sender_is_me": _is_self_identifier(sender),
                "recipients_to": _dedupe_people(to_values),
                "recipients_cc": _dedupe_people(cc_values),
                "mailbox": _strip_html(raw.get("mailbox") if isinstance(raw, dict) else ""),
                "date_received": _strip_html(raw.get("date_received") if isinstance(raw, dict) else ""),
                "is_unread": not bool(raw.get("read")) if isinstance(raw, dict) and "read" in raw else False,
                "body_preview": _excerpt(raw.get("body") if isinstance(raw, dict) else ""),
            }
        )
    return prepared


def _email_window_label(script: str, window_info: Optional[Dict[str, Any]] = None) -> str:
    labels = {
        "fetch_yesterday_emails": "Yesterday's Unread Emails",
        "fetch_weekend_emails": "Weekend Emails",
        "unread_last_hour": "Last Hour Unread Emails",
    }
    base = labels.get(script, "Email Digest")
    info = window_info or {}

    hours_back = info.get("hours_back")
    if isinstance(hours_back, int) and hours_back > 0:
        return f"{base} (last {hours_back}h)"

    start = (info.get("start") or "").strip()
    end = (info.get("end") or "").strip()

    if start and end:
        return f"{base} ({start} → {end})"
    if start:
        return f"{base} (since {start})"
    return base


def _email_system_prompt() -> str:
    return (
        "You are an executive assistant. Analyse the provided email metadata and craft concise Markdown "
        "summaries grouped by conversation threads. Base every statement strictly on the supplied data."
    )


def _email_user_prompt(
    prepared: List[Dict[str, Any]],
    script: str,
    window_info: Optional[Dict[str, Any]],
) -> str:
    window_label = _email_window_label(script, window_info)
    if _SELF_IDENTIFIERS:
        me_label = ", ".join(_SELF_IDENTIFIERS)
    else:
        me_label = "Not provided"

    info = window_info or {}
    start_desc = (info.get("start_raw") or info.get("start") or "").strip()
    end_desc = (info.get("end_raw") or info.get("end") or "").strip()
    hours_back = info.get("hours_back")

    window_details: List[str] = []
    if start_desc:
        window_details.append(f"start: {start_desc}")
    if end_desc:
        window_details.append(f"end: {end_desc}")
    if isinstance(hours_back, int) and hours_back > 0:
        window_details.append(f"lookback_hours: {hours_back}")
    if not window_details:
        window_details = ["start: midnight today (local)", "end: now (local)"]

    window_details_block = "\n".join(f"- {detail}" for detail in window_details)
    dataset = json.dumps(prepared, indent=2, ensure_ascii=False)
    instructions = (
        f"Window: {window_label}\n"
        f"{window_details_block}\n"
        f"My identifiers: {me_label}\n\n"
        "Instructions:\n"
        "- Group messages into threads representing the same conversation. Use canonical_subject as a hint;\n"
        "  merge messages that clearly belong together, even if the subject varies slightly (e.g., RE/FW prefixes).\n"
        "- For each thread produce Markdown exactly in this structure:\n"
        "#### Thread {n}: {thread title}\n"
        "- Sender: person who authored the latest email directed at me.\n"
        "- Recipients: unique To + Cc recipients (comma separated).\n"
        "- Replies: participants who replied after the original sender. Include me if sender_is_me is true on any entry beyond the first message.\n"
        "- Summary: 1-3 sentences capturing the current state or decisions in the thread. Mention if any message preview lacks detail (say 'Summary: Not enough info').\n"
        "- My Actions: concrete follow-ups expected of me. If none, respond with 'None'.\n"
        "- Note if the latest message in the thread is unread.\n\n"
        "End the report with a short '**Quick glance:**' bullet list highlighting any threads with pending actions for me.\n\n"
        "Message dataset (chronological order, earliest first):\n"
        "```json\n"
        f"{dataset}\n"
        "```"
    )
    return instructions


def _invoke_email_summary_llm(system_prompt: str, user_prompt: str, model: Optional[str]) -> Optional[str]:
    if not OLLAMA:
        _logger().warning("OLLAMA base URL not configured; skipping email summary call")
        return None

    payload = {
        "model": model or FALLBACK_7B,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": dict(CAP_DEEP),
    }

    try:
        resp = requests.post(
            f"{OLLAMA}/api/chat",
            json=payload,
            timeout=(10, READ_TIMEOUT),
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        _logger().error("Email summary LLM request failed: %s", exc)
        return None

    try:
        body = resp.json()
    except ValueError:
        text = resp.text.strip()
        return text or None

    if isinstance(body, dict):
        message = body.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
        response_text = body.get("response")
        if isinstance(response_text, str) and response_text.strip():
            return response_text.strip()
    return None


def _fallback_email_summary(
    prepared: List[Dict[str, Any]],
    script: str,
    window_info: Optional[Dict[str, Any]],
) -> str:
    window = _email_window_label(script, window_info)
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in prepared:
        key = item.get("canonical_subject") or "(no subject)"
        grouped.setdefault(key, []).append(item)

    lines = [f"### 📬 {_escape_md(window)}", ""]

    info = window_info or {}
    meta_fragments: List[str] = []
    start_display = (info.get("start") or "").strip()
    end_display = (info.get("end") or "").strip()
    hours_back = info.get("hours_back")

    if start_display:
        meta_fragments.append(f"Start: {_escape_md(start_display)}")
    if end_display:
        meta_fragments.append(f"End: {_escape_md(end_display)}")
    if isinstance(hours_back, int) and hours_back > 0:
        meta_fragments.append(f"Lookback: {hours_back}h")

    if meta_fragments:
        lines.append("_" + " • ".join(meta_fragments) + "_")
        lines.append("")

    lines.append("_LLM summary unavailable; raw highlights below._")
    lines.append("")

    for idx, (_key, items) in enumerate(grouped.items(), start=1):
        items_sorted = sorted(items, key=lambda entry: entry.get("index", 0))
        latest = items_sorted[-1]
        subject = latest.get("subject") or "(No Subject)"
        sender = latest.get("sender") or "Unknown sender"
        recipients = latest.get("recipients_to", []) + latest.get("recipients_cc", [])
        unread_flag = " (unread)" if latest.get("is_unread") else ""
        lines.append(f"#### Thread {idx}: {subject}{unread_flag}")
        lines.append(f"- Sender: {sender}")
        lines.append(f"- Recipients: {', '.join(recipients) if recipients else 'None listed'}")
        replies = {entry.get("sender") for entry in items_sorted[1:]} - {sender}
        reply_label = ", ".join(sorted(filter(None, replies))) if replies else "None noted"
        lines.append(f"- Replies: {reply_label}")
        preview = latest.get("body_preview") or "No preview available."
        lines.append(f"- Summary: {preview}")
        lines.append("- My Actions: Unknown")
        lines.append("")

    return "\n".join(lines).strip()


def _render_email_summary(
    messages: List[Dict[str, Any]],
    script: str,
    model: Optional[str],
    payload_dict: Optional[Dict[str, Any]],
) -> Optional[str]:
    prepared = _prepare_email_messages(messages)
    window_info = _extract_email_window(payload_dict)
    if not prepared:
        window = _email_window_label(script, window_info)
        return f"### 📬 {window}\n\n> No emails were found in this window."

    system_prompt = _email_system_prompt()
    user_prompt = _email_user_prompt(prepared, script, window_info)
    summary = _invoke_email_summary_llm(system_prompt, user_prompt, model)
    if summary:
        return summary
    return _fallback_email_summary(prepared, script, window_info)


_SELF_IDENTIFIERS: List[str] = []
for chunk in (
    globals().get("OSX_ACTIONS_SELF", ""),
    globals().get("OSX_ACTIONS_SELF_ALIASES", ""),
):
    if not chunk:
        continue
    for token in re.split(r"[,\n;]+", chunk):
        norm = _normalize_name(token)
        if norm:
            _SELF_IDENTIFIERS.append(norm)


def _event_should_skip(event: Dict[str, Any]) -> bool:
    title = _strip_html(event.get("title") or "").lower()
    start_dt = _parse_iso(event.get("start"))
    if (
        start_dt
        and start_dt.strftime("%H:%M") == "08:30"
        and title == "20/20 flight plan morning meeting"
    ):
        return True
    return False


def _is_me_required(event: Dict[str, Any]) -> bool:
    if not _SELF_IDENTIFIERS:
        return False
    attendees = event.get("required_attendees_full") or event.get("required_attendees") or []
    normalized: List[str] = []
    for attendee in attendees:
        stripped = _strip_html(attendee)
        if not stripped:
            continue
        normalized.append(_normalize_name(stripped))
        if "@" in stripped:
            local = stripped.split("@", 1)[0]
            normalized.append(_normalize_name(local))

    normalized = [value for value in normalized if value]
    for ident in _SELF_IDENTIFIERS:
        if not ident:
            continue
        for attendee in normalized:
            if attendee == ident:
                return True
    return False


def _render_meetings_summary(events: List[Dict[str, Any]]) -> str:
    filtered_events = [
        event for event in events if not _event_should_skip(event)
    ]

    if not filtered_events:
        return (
            "### 📅 Meetings Today\n\n"
            "> No meetings scheduled for today. Enjoy the breathing room!"
        )

    first_with_start = next((ev for ev in filtered_events if ev.get("start")), None)
    dt = _parse_iso(first_with_start.get("start")) if first_with_start else None
    heading = f"Meetings for {dt.strftime('%A, %B %d').replace(' 0', ' ')}" if dt else "Today's Meetings"

    total = len(filtered_events)
    earliest = _parse_iso(filtered_events[0].get("start"))
    start_label = _format_clock(earliest) if earliest else "—"

    generated = datetime.now(timezone.utc).astimezone()
    generated_label = _format_clock(generated)
    generated_date = _format_date(generated)

    rows: List[str] = []
    divider_row = "| -- | -- | -- | -- | -- | -- |"

    for idx, event in enumerate(filtered_events, start=1):
        if rows:
            rows.append(divider_row)

        ordinal = int(event.get("ordinal") or idx)
        start_dt = _parse_iso(event.get("start"))
        end_dt = _parse_iso(event.get("end"))

        if start_dt and end_dt:
            if start_dt.date() == end_dt.date():
                time_span = f"{_format_clock(start_dt)} – {_format_clock(end_dt)}"
            else:
                time_span = f"{_format_clock(start_dt)} → {_format_clock(end_dt)}"
        elif start_dt:
            time_span = _format_clock(start_dt)
        elif end_dt:
            time_span = _format_clock(end_dt)
        else:
            time_span = "—"

        date_value = start_dt.strftime("%a, %b %d").replace(" 0", " ") if start_dt else "—"
        schedule_cell = f"**{_escape_md(date_value)}** — **{_escape_md(time_span)}**"

        title = _escape_md(_strip_html(event.get("title") or "Untitled Meeting"))
        raw_summary = _strip_html(event.get("summary") or "")
        summary_block = f" — _{_escape_md(raw_summary)}_" if raw_summary else ""
        organizer = _escape_md(_strip_html(event.get("organizer") or "—"))

        optional_count = len(event.get("optional_attendees_full") or [])
        optional_fragment = f" _(optional attendees: {optional_count})_" if optional_count else ""
        command_hint = f"`meetings_today_detail({ordinal})`"

        session_cell = f"🔹 **{title}**{summary_block}{optional_fragment}"
        required_cell = "Y" if _is_me_required(event) else ""

        rows.append(
            "| {row} | {schedule} | {session} | {organizer} | {required} | {detail} |".format(
                row=f"{ordinal:02d}",
                schedule=schedule_cell,
                session=session_cell,
                organizer=organizer,
                required=required_cell,
                detail=command_hint,
            )
        )

    table_header = (
        "| Row | Schedule | Session | Organizer | Required | Detail |\n"
        "|:--|:------------------|:----------------|:-----------|:---------:|:-------|\n"
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
    title = _escape_md(_strip_html(event.get("title") or "Untitled Meeting"))
    time_range = _escape_md(_format_time_range(event.get("start"), event.get("end")))
    organizer = _escape_md(_strip_html(event.get("organizer") or "—"))
    calendar = _escape_md(_strip_html(event.get("calendar") or "—"))
    location = _escape_md(_strip_html(event.get("location") or "—"))
    is_all_day = bool(event.get("is_all_day"))
    url = event.get("url")

    header = f"### 🗒️ Meeting Detail #{ordinal}\n\n**{title}**\n"

    meta_lines = [
        f"- **When:** {time_range}",
        f"- **Organizer:** {organizer}",
        f"- **Calendar:** {calendar}",
        f"- **Location:** {location or '_Not set_'}",
        f"- **All-day:** {'Yes' if is_all_day else 'No'}",
        f"- **I'm required:** {'Yes' if _is_me_required(event) else 'No'}",
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

    notes = _strip_html(event.get("notes") or "")
    notes_section = ""
    if notes.strip():
        notes_section = "\n**Notes**\n" + _format_blockquote(notes)

    url_section = f"\n[Open meeting link]({url})" if url else ""

    parts = [header, *meta_lines, attendees_section, notes_section, url_section]
    return "\n".join(part for part in parts if part).strip()


def _format_script_message(
    script: str,
    status: int,
    mimetype: str,
    payload_bytes: bytes,
    *,
    model: Optional[str] = None,
) -> str:
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

            if script in {"fetch_yesterday_emails", "fetch_weekend_emails", "unread_last_hour"}:
                payload_dict: Optional[Dict[str, Any]] = parsed if isinstance(parsed, dict) else None

                if payload_dict is None and isinstance(stdout, str):
                    candidate = stdout.strip()
                    if candidate:
                        try:
                            maybe = json.loads(candidate)
                            if isinstance(maybe, dict):
                                payload_dict = maybe
                        except json.JSONDecodeError:
                            pass

                messages: List[Dict[str, Any]] = []
                if isinstance(payload_dict, dict):
                    extracted = payload_dict.get("messages")
                    if isinstance(extracted, list):
                        messages = [msg for msg in extracted if isinstance(msg, dict)]

                if not messages:
                    error_body = stderr or stdout or "No email messages found."
                    status_label = " (failed)" if not ok_flag else ""
                    return f"{heading}{status_label}\n\n{error_body}"

                summary_text = _render_email_summary(messages, script, model, payload_dict)
                if stderr:
                    summary_text = f"{summary_text}\n\n[stderr]\n{stderr}"
                if not ok_flag:
                    heading = f"{heading} (failed)"
                return f"{heading}\n\n{summary_text}"

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

                event_detail = _extract_event(parsed)
                if not isinstance(event_detail, dict):
                    raw_stdout = data.get("stdout")
                    if isinstance(raw_stdout, str):
                        candidate = raw_stdout.strip()
                        stdout_payload = None
                        try:
                            stdout_payload = json.loads(candidate)
                        except json.JSONDecodeError:
                            first_brace = candidate.find("{")
                            last_brace = candidate.rfind("}")
                            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                                snippet = candidate[first_brace : last_brace + 1]
                                try:
                                    stdout_payload = json.loads(snippet)
                                except json.JSONDecodeError:
                                    stdout_payload = None
                        event_detail = _extract_event(stdout_payload)

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
    model = body.get("model")
    message = _format_script_message(script_name, status, mimetype, content, model=model)
    return _chat_response(message, model)


__all__ = ["call_script", "maybe_handle_chat"]
