# Local LLM Stack & macOS Automation

This repository now contains two coordinated components:

- `autosizer/` – the containerised proxy that fronts Ollama for Open WebUI and
  applies dynamic generation caps, model downgrades, and short-answer finishing.
- `macos_actions/` – a host-native FastAPI gateway that runs on macOS to expose
  approved host automations (AppleScript for mail, EventKit/Python for
  calendars) so your LLM can retrieve digests without leaving the corporate
  network.

## Getting started

1. **autosizer:** change directory into `autosizer/` for container build files
   (`Dockerfile`, `docker-compose.yml`, etc.). The existing workflows continue to
   work; just adjust any relative paths that assumed files lived at repo root.
2. **macOS actions gateway:** follow `macos_actions/SETUP.md` on your work
   MacBook to install the automation service, configure AppleScripts, and launch
   the macOS-only HTTP API.

## Structure

```
autosizer/           # existing autosizer proxy project (Flask)
macos_actions/       # macOS automation gateway + documentation
  service/           # FastAPI app and helpers
  scripts/today_events.py  # EventKit bridge for calendar occurrences
  config/actions.example.yml
  SETUP.md           # exhaustive setup instructions for host deployment
```

Each project has its own requirements file. Manage them separately depending on
whether you are working in the container stack (`autosizer`) or the host-native
automation service (`macos_actions`).
