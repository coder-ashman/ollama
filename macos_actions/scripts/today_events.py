#!/usr/bin/env python3
"""Return today's calendar events (including recurring occurrences) as JSON.

The script can optionally accept an event index (1-based) to emit a single
expanded record. When no index is supplied it returns the full list for today.
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


def build_event_payload(store: EKEventStore) -> List[Dict[str, Any]]:
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

    return [render_event_record(ev, idx) for idx, ev in enumerate(events, start=1)]


def parse_index_argument(argv: List[str]) -> Optional[int]:
    if not argv:
        return None

    tokens = list(argv)
    if tokens[0] == "--index" and len(tokens) >= 2:
        tokens = [tokens[1]]

    candidate = tokens[0]
    if candidate.startswith("--index="):
        candidate = candidate.split("=", 1)[1]

    try:
        index = int(candidate)
    except ValueError:
        return None

    return index if index > 0 else None


def main():
    detail_index = parse_index_argument(sys.argv[1:])

    store = EKEventStore.alloc().init()
    if not request_calendar_access(store):
        print(json.dumps({"ok": False, "error": "calendar access not granted"}))
        return

    records = build_event_payload(store)

    if detail_index is not None:
        match = next((item for item in records if item["ordinal"] == detail_index), None)
        if not match:
            payload = {
                "ok": False,
                "error": f"No meeting found for index {detail_index}",
                "events_count": len(records),
            }
        else:
            payload = {"ok": True, "event": match, "events_count": len(records)}
    else:
        payload = {"ok": True, "events": records}

    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
