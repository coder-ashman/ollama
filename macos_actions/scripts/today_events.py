#!/usr/bin/env python3
"""Return today's calendar events (including recurring occurrences) as JSON."""
import json
import threading
from datetime import datetime, timedelta, timezone

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


def nsdate_to_local_iso(nsdate: NSDate) -> str:
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


def attendees_by_role(attendees):
    required, optional = [], []
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


def event_record(event):
    start_iso = nsdate_to_local_iso(event.startDate())
    end_iso = nsdate_to_local_iso(event.endDate())

    required, optional = attendees_by_role(event.attendees())
    organiser = ""
    if event.organizer():
        organiser = event.organizer().name() or event.organizer().emailAddress() or ""

    notes = event.notes() or ""

    max_required = 5
    max_optional = 5

    return {
        "title": event.title() or "",
        "start": start_iso,
        "end": end_iso,
        "organizer": organiser,
        "required_attendees": required[:max_required],
        "optional_attendees": optional[:max_optional],
        "summary": notes[:160],
    }


def main():
    store = EKEventStore.alloc().init()
    if not request_calendar_access(store):
        print(json.dumps({"events": [], "error": "calendar access not granted"}))
        return

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

    payload = {"events": [event_record(ev) for ev in events]}
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
