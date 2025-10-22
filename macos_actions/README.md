# macOS Actions Gateway

This package hosts a small FastAPI service that runs directly on macOS to expose
approved host automations over HTTP. Most actions remain AppleScript/Shortcuts,
but the calendar workflow now uses a Python + EventKit helper so recurring
meetings resolve to the correct “today” occurrence. The gateway is designed to
work alongside the autosizer proxy so your local LLM can request high-trust
host actions (mail digests, calendar summaries, etc.) without leaking sensitive
context to the public internet.

## Components

- `service/`: FastAPI app and helpers for loading configuration, enforcing API
  keys, and executing whitelisted scripts.
- `config/actions.example.yml`: sample configuration mapping friendly script
  names to the AppleScripts you already maintain, plus the EventKit-powered
  `meetings_today` Python helper.
- `scripts/today_events.py`: EventKit bridge that emits today’s calendar
  occurrences as JSON (recurring events included).
- `requirements.txt`: pinned dependency list for the dedicated virtualenv on
  your corporate Mac (now includes `pyobjc`). Use Python 3.11 when creating
  this environment—e.g. `/opt/homebrew/bin/python3.11 -m venv .venv`. PyObjC 12
  (required for EventKit) does not yet ship wheels for newer interpreters
  (status as of 2025-10-22).
- `SETUP.md`: exhaustive, step-by-step instructions for installing and running
  the gateway on macOS (virtualenv, LaunchAgent, permissions, etc.).

## High-level flow

1. The gateway listens on `127.0.0.1:<port>` (default 8765) and exposes a
   minimal API guarded by `X-API-Key`.
2. When an endpoint such as `/reports/email-digest` is invoked, the gateway
   executes the configured AppleScripts, captures their JSON (or plain-text)
   output, and returns a structured response to the caller.
3. Your autosizer proxy (or any MCP client) connects to the gateway via
   `host.lima.internal:<port>`, providing the API key and receiving the digest.

See `SETUP.md` for detailed deployment steps, including how to wire in your
existing AppleScripts for unread email, daily meetings, and top-of-hour inbox
checks.
