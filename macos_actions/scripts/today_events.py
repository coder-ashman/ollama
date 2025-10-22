#!/usr/bin/env python3
"""Return today's calendar events (including recurring occurrences) as JSON.

The script accepts optional arguments:

- ``--index <N>`` (or simply ``N``) to emit a single expanded record.
- ``--start-time <HH:MM AM/PM>`` to filter events that begin at or after the
  supplied local time.

When no options are provided it returns the full list for today.
"""

import json
import sys
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from Foundation import NSDate, NSRunLoop
from EventKit import (
    EKAuthorizationStatusAuthorized,
    EKEntityTypeEvent,
    EKEventStore,
)

try:
    from EventKit import EKParticipantRoleOptional
except ImportError:  # constant name differs on some macOS versions
    EKParticipantRoleOptional = 1

LOCAL_TZ = datetime.now().astimezone().tzinfo or timezone.utc
MAX_REQUIRED = 5
MAX_OPTIONAL = 5
SUMMARY_LENGTH = 160


def nsdate_to_local_iso(nsdate: Optional[NSDate]) -> str:
    if nsdate is None:
        return ""
    return datetime.fromtimestamp(nsdate.timeIntervalSince1970(), tz=LOCAL_TZ).isoformat()


def request_calendar_access(store: EKEventStore) -> bool:
    status = EKEventStore.authorizationStatusForEntityType_(EKEntityTypeEvent)
    if status == EKAuthorizationStatusAuthorized:
        return True
    if status == 2:  # denied
        return False

    gate = threading.Event()
    result = {"granted": False}

    def completion(granted, error):  # signature prescribed by EventKit callback
        result["granted"] = bool(granted)
        gate.set()

    store.requestAccessToEntityType_completion_(EKEntityTypeEvent, completion)

    # Keep the run loop alive until the user responds to the permission dialog.
    while not gate.is_set():
        NSRunLoop.currentRunLoop().runMode_beforeDate_("default", NSDate.dateWithTimeIntervalSinceNow_(0.1))

    return result["granted"]


def attendees_by_role(attendees) -> Tuple[List[str], List[str]]:
    required: List[str] = []
    optional: List[str] = []
    if not attendees:
        return required, optional

    for participant in attendees:
        label = participant.name() or participant.emailAddress() or ""
        if not label:
            continue
        if participant.participantRole() == EKParticipantRoleOptional:
            optional.append(label)
        else:
            required.append(label)
    return required, optional


def render_event_record(event, ordinal: int) -> Dict[str, Any]:
    start_iso = nsdate_to_local_iso(event.startDate())
    end_iso = nsdate_to_local_iso(event.endDate())

    required_full, optional_full = attendees_by_role(event.attendees())
    organiser = ""
    if event.organizer():
        organiser = event.organizer().name() or event.organizer().emailAddress() or ""

    notes = (event.notes() or "").strip()
    summary = notes[:SUMMARY_LENGTH]
    calendar_title = ""
    if event.calendar():
        calendar_title = event.calendar().title() or ""

    url_value = ""
    if event.URL():
        try:
            url_value = str(event.URL().absoluteString())
        except Exception:
            url_value = str(event.URL())

    try:
        is_all_day = bool(event.isAllDay())
    except Exception:
        try:
            is_all_day = bool(event.allDay())
        except Exception:
            is_all_day = False

    record: Dict[str, Any] = {
        "ordinal": ordinal,
        "id": event.eventIdentifier() or "",
        "title": event.title() or "",
        "start": start_iso,
        "end": end_iso,
        "organizer": organiser,
        "calendar": calendar_title,
        "location": event.location() or "",
        "is_all_day": is_all_day,
        "url": url_value,
        "required_attendees": required_full[:MAX_REQUIRED],
        "optional_attendees": optional_full[:MAX_OPTIONAL],
        "required_attendees_full": required_full,
        "optional_attendees_full": optional_full,
        "summary": summary,
        "notes": notes,
    }
    return record


def build_event_payload(store: EKEventStore, start_filter: Optional[datetime] = None) -> List[Dict[str, Any]]:
    now = datetime.now(tz=LOCAL_TZ)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
        NSDate.dateWithTimeIntervalSince1970_(start_of_day.timestamp()),
        NSDate.dateWithTimeIntervalSince1970_(end_of_day.timestamp()),
        None,
    )

    events = store.eventsMatchingPredicate_(predicate) or []
    events.sort(key=lambda ev: ev.startDate())

    filtered_events = []
    for event in events:
        if start_filter is not None:
            event_start_nsdate = event.startDate()
            if event_start_nsdate is None:
                continue
            event_start = datetime.fromtimestamp(event_start_nsdate.timeIntervalSince1970(), tz=LOCAL_TZ)
            if event_start < start_filter:
                continue
        filtered_events.append(event)

    return [render_event_record(ev, idx) for idx, ev in enumerate(filtered_events, start=1)]


def _coerce_positive_int(value: Any) -> Optional[int]:
    try:
        candidate = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return candidate if candidate > 0 else None


def parse_cli_arguments(argv: List[str]) -> Tuple[Optional[int], Optional[str]]:
    if not argv:
        return None, None

    detail_index: Optional[int] = None
    start_time_value: Optional[str] = None

    normalized_args = [str(token) for token in argv if str(token).strip()]
    i = 0
    while i < len(normalized_args):
        token = normalized_args[i].strip()
        lower = token.lower()

        if lower == "--index":
            if i + 1 < len(normalized_args):
                maybe = _coerce_positive_int(normalized_args[i + 1])
                if maybe is not None:
                    detail_index = maybe
                i += 1
        elif lower.startswith("--index="):
            maybe = _coerce_positive_int(token.split("=", 1)[1])
            if maybe is not None:
                detail_index = maybe
        elif lower == "--start-time" or lower == "--start":
            if i + 1 < len(normalized_args):
                start_time_value = normalized_args[i + 1]
                i += 1
        elif lower.startswith("--start-time="):
            start_time_value = token.split("=", 1)[1]
        elif lower.startswith("--start="):
            start_time_value = token.split("=", 1)[1]
        else:
            maybe_index = _coerce_positive_int(token)
            if maybe_index is not None and detail_index is None:
                detail_index = maybe_index
            elif start_time_value is None:
                start_time_value = token
        i += 1

    start_time_value = start_time_value.strip() if start_time_value else None
    return detail_index, start_time_value


def resolve_start_filter(start_value: Optional[str]) -> Optional[datetime]:
    if not start_value:
        return None

    cleaned = start_value.strip()
    if not cleaned:
        return None

    for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            break
        except ValueError:
            parsed = None
    else:
        parsed = None

    if parsed is None:
        return None

    current = datetime.now(tz=LOCAL_TZ)
    start_of_day = current.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_of_day.replace(hour=parsed.hour, minute=parsed.minute)


def main():
    detail_index, start_time_value = parse_cli_arguments(sys.argv[1:])
    start_filter = resolve_start_filter(start_time_value)

    store = EKEventStore.alloc().init()
    if not request_calendar_access(store):
        print(json.dumps({"ok": False, "error": "calendar access not granted"}))
        return

    records = build_event_payload(store, start_filter=start_filter)

    if detail_index is not None:
        match = next((item for item in records if item["ordinal"] == detail_index), None)
        if not match:
            payload = {
                "ok": False,
                "error": f"No meeting found for index {detail_index}",
                "events_count": len(records),
            }
        else:
            payload = {
                "ok": True,
                "event": match,
                "events_count": len(records),
            }
    else:
        payload = {"ok": True, "events": records}

    if start_filter is not None:
        payload["start_filter"] = start_filter.isoformat()
        if start_time_value:
            payload["start_filter_label"] = start_time_value

    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
