# macOS Actions Gateway – Setup Guide

Use this checklist to deploy the automation gateway on your corporate Mac. The
mail automations continue to rely on AppleScript, while the calendar workflow
now uses a Python + EventKit helper (`scripts/today_events.py`) so recurring
meetings produce the correct “today” occurrence times.

---

## 1. Prerequisites

1. **macOS account:** use the user account that will run the automations (admin
   not required).
2. **Python 3.11+** installed via Xcode Command Line Tools or your corporate
   package manager (`python3 --version`).
3. **AppleScripts for mail:** keep the unread/new-mail AppleScripts you already
   use. They should return plain text or JSON when run via `osascript`.
4. **Calendar via EventKit:** `macos_actions/scripts/today_events.py` is bundled
   and returns today’s occurrences as JSON; no AppleScript needed for meetings.
5. **Identify script locations** – e.g.:

   - `~/Library/Scripts/LLM/unread_email_yesterday.scpt`
   - `~/Library/Scripts/LLM/new_mail_since_hour.scpt`
   - `~/macos_actions/scripts/today_events.py` (provided)

---

## 2. Copy the service files

1. On your workstation, copy the `macos_actions/` directory from this repo to
   the target Mac. Recommended destination: `~/macos_actions`.
2. Ensure the EventKit helper is executable:

   ```bash
   chmod +x ~/macos_actions/scripts/today_events.py
   ```

3. Inside `~/macos_actions`, create the configuration folder:

   ```bash
   mkdir -p "${HOME}/Library/Application Support/macos_actions"
   cp macos_actions/config/actions.example.yml \
      "${HOME}/Library/Application Support/macos_actions/actions.yml"
   ```

4. Edit `actions.yml` and update each script path. For calendar meetings, keep
   the default pointing to `scripts/today_events.py` unless you move it.

---

## 3. Prepare the dedicated virtual environment

```bash
cd ~/macos_actions
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r macos_actions/requirements.txt
```

> Installing `pyobjc` (bundled in the requirements file) downloads many wheels
> and can take several minutes—this is normal.

Freeze the versions so future installs stay consistent:

```bash
pip freeze > macos_actions/requirements.lock
```

Keep the virtualenv for the LaunchAgent step.

---

## 4. Authorize calendar access (EventKit)

> Do these steps in **Terminal.app** (not VS Code’s integrated terminal) so the
> macOS permission dialog appears and the decision is stored for the correct
> binary.

```bash
source ~/macos_actions/.venv/bin/activate
python macos_actions/scripts/today_events.py
```

- The first run pops up “python wants to access your Calendars.” Click **OK**.
- If you previously denied access, reset the permission with
  `tccutil reset Calendar` and run the command again.
- Verify the script now prints JSON with today’s events. If you still see an
  empty payload, check **System Settings → Privacy & Security → Calendars** and
  ensure the entry for your virtualenv’s `python` binary is enabled.

You can re-run the script at any time to confirm permission sticks.

---

## 5. Secure the API key

Pick a long random string and store it in the macOS Keychain:

```bash
export OSX_ACTIONS_KEY="$(openssl rand -base64 32)"
security add-generic-password -a "$USER" -s osx_actions_key -w "$OSX_ACTIONS_KEY"
unset OSX_ACTIONS_KEY
```

(If corporate policy prevents new Keychain items, set `OSX_ACTIONS_KEY` in the
LaunchAgent environment instead. Keychain is recommended.)

---

## 6. Test the service manually

1. Start the API with uvicorn inside the virtualenv:

   ```bash
   source ~/macos_actions/.venv/bin/activate
   OSX_ACTIONS_KEY="$(security find-generic-password -s osx_actions_key -w)"
   OSX_ACTIONS_CONFIG="${HOME}/Library/Application Support/macos_actions/actions.yml"
   uvicorn macos_actions.service.main:app --host 127.0.0.1 --port 8765
   ```

2. In another terminal, call the health endpoint:

   ```bash
   curl http://127.0.0.1:8765/health
   ```

3. Exercise each script (replace key names if you customized them):

   ```bash
   API_KEY=$(security find-generic-password -s osx_actions_key -w)
   curl -X POST http://127.0.0.1:8765/scripts/unread_email_yesterday/run \
     -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -d '{}'

    curl -X POST http://127.0.0.1:8765/scripts/meetings_today/run \
      -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -d '{}'
   ```

4. Run the combined report:

   ```bash
   curl -X POST http://127.0.0.1:8765/reports/email-digest \
     -H "X-API-Key: $API_KEY"
   ```

Confirm the JSON response contains your script output (`parsed` will be populated
if your AppleScript returned JSON).

Stop uvicorn once satisfied (Ctrl+C).

---

## 7. Install the LaunchAgent

1. Create a wrapper script that loads the API key from Keychain and launches
   uvicorn. Save as `~/macos_actions/bin/start-gateway.sh`:

   ```bash
   mkdir -p ~/macos_actions/bin
   cat <<'SH' > ~/macos_actions/bin/start-gateway.sh
   #!/bin/bash
   set -euo pipefail
   BASE_DIR="$HOME/macos_actions"
   source "$BASE_DIR/.venv/bin/activate"
   export OSX_ACTIONS_CONFIG="$HOME/Library/Application Support/macos_actions/actions.yml"
   export OSX_ACTIONS_KEY="$(/usr/bin/security find-generic-password -s osx_actions_key -w)"
   exec uvicorn macos_actions.service.main:app --host 127.0.0.1 --port 8765
   SH
   chmod 700 ~/macos_actions/bin/start-gateway.sh
   ```

2. Create `~/Library/LaunchAgents/com.you.macos_actions.plist`:

   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0"><dict>
  <key>Label</key><string>com.you.macos_actions</string>
     <key>ProgramArguments</key>
     <array>
       <string>/bin/bash</string>
    <string>$HOME/macos_actions/bin/start-gateway.sh</string>
     </array>
     <key>RunAtLoad</key><true/>
     <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/macos_actions.out</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/macos_actions.err</string>
   </dict></plist>
   ```

3. Load the agent:

   ```bash
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.you.macos_actions.plist
   launchctl kickstart -k gui/$(id -u)/com.you.macos_actions
   ```

4. Verify:

   ```bash
   launchctl list | grep macos_actions
   tail -f ~/Library/Logs/macos_actions.out
   ```

macOS may prompt once to allow “start-gateway.sh” (or `osascript`) to control
Mail/Calendar. Approve these prompts.

---

## 8. Connect autosizer (or MCP clients)

1. Inside your Rancher `docker-compose.yml`, add the gateway coordinates and API
   key to the autosizer service:

   ```yaml
   environment:
     OSX_ACTIONS_BASE: "http://host.lima.internal:8765"
     OSX_ACTIONS_KEY: "<same key stored in Keychain>"
   extra_hosts:
     - "host.lima.internal:host-gateway"
   ```

2. Rebuild/restart autosizer so the environment variables are visible.

3. Invoke the new endpoints from Open WebUI / MCP by calling
   `POST http://autosizer:8089/tool/osx/run` (if you added the relay) or by
   making direct HTTP requests in a tool call.

---

## 9. Scheduling checks (optional)

To automate daily digests or hourly new-mail pings, create additional
LaunchAgents that `curl` the `/reports/email-digest` endpoint and post the
result to your LLM. A minimal hourly example:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.you.macos_actions.hourly</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/curl</string>
    <string>-X</string><string>POST</string>
    <string>-H</string><string>X-API-Key: $(/usr/bin/security find-generic-password -s osx_actions_key -w)</string>
    <string>http://127.0.0.1:8765/reports/email-digest</string>
  </array>
  <key>StartInterval</key><integer>3600</integer>
</dict></plist>
```

Feed the response into your LLM workflow (e.g., post to autosizer or write to a
file that the LLM ingests).

---

## 10. Troubleshooting

- **`invalid api key`** – confirm the LaunchAgent exports the same key autosizer
  uses. Re-run the Keychain command to verify.
- **`osascript error`** – run the AppleScript manually (`osascript path.scpt`) to
  inspect the failure. Grant Automation permissions if prompted.
- **No JSON in `parsed`** – adjust your AppleScript to `return` a JSON string.
  Any raw text is still preserved in `stdout`.
- **Calendar access denied / no popup** – reset with `tccutil reset Calendar`,
  re-run `today_events.py` from Terminal, and approve the dialog. Check
  System Settings → Privacy & Security → Calendars to ensure the virtualenv’s
  `python` entry is toggled on.
- **Installation takes a long time** – `pyobjc` installs dozens of wheels; the
  first `pip install` often takes several minutes.

You now have a hardened, host-native gateway that your LLM stack can call to
summarize unread mail, list meetings, and poll for new messages.
