# macOS Actions Gateway – Setup Guide

Use this checklist to deploy the automation gateway on your corporate Mac. The
steps assume you already have AppleScripts that extract unread email and
calendar data.

---

## 1. Prerequisites

1. **macOS account:** you must be logged into the account that will run the
   automations (no admin/root required).
2. **Python 3.11+** installed via Xcode Command Line Tools or your corporate
   package manager (`python3 --version`).
3. **AppleScripts ready:** ensure your scripts print either JSON or clear text
   when run via `osascript`. Example JSON payload (recommended):

   ```applescript
   -- unread_email_yesterday.scpt
   set emailItems to {¬
     {|thread_id|:"abc", subject:"Quarterly review", messages:3, summary:"Needs follow-up"},
     {|thread_id|:"xyz", subject:"Stand-up", messages:1, summary:"FYI only"}
   }
   set jsonText to "{\"threads\":" & (my encodeJSON(emailItems)) & "}"
   return jsonText
   ```

   (Adjust to match your scripts; plain text still works, but JSON unlocks
   automatic grouping.)

4. **Identify script locations** – e.g.:

   - `~/Library/Scripts/LLM/unread_email_yesterday.scpt`
   - `~/Library/Scripts/LLM/meetings_today.scpt`
   - `~/Library/Scripts/LLM/new_mail_since_hour.scpt`

---

## 2. Copy the service files

1. On your workstation, copy the `macos_actions/` directory from this repo to
   the target Mac. Recommended destination: `~/macos-actions`.
2. Inside `~/macos-actions`, create the configuration folder:

   ```bash
   mkdir -p "${HOME}/Library/Application Support/macos-actions"
   cp macos_actions/config/actions.example.yml \
      "${HOME}/Library/Application Support/macos-actions/actions.yml"
   ```

3. Edit `actions.yml` and update each script path to match your AppleScripts.
   If you renamed keys, keep the `reports.email_digest` section in sync.

---

## 3. Prepare the dedicated virtual environment

```bash
cd ~/macos-actions
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r macos_actions/requirements.txt
```

Freeze the versions so future installs stay consistent:

```bash
pip freeze > macos_actions/requirements.lock
```

Keep the virtualenv for the LaunchAgent step.

---

## 4. Secure the API key

Pick a long random string and store it in the macOS Keychain:

```bash
export OSX_ACTIONS_KEY="$(openssl rand -base64 32)"
security add-generic-password -a "$USER" -s osx_actions_key -w "$OSX_ACTIONS_KEY"
unset OSX_ACTIONS_KEY
```

(If corporate policy prevents new Keychain items, set `OSX_ACTIONS_KEY` in the
LaunchAgent environment instead. Keychain is recommended.)

---

## 5. Test the service manually

1. Start the API with uvicorn inside the virtualenv:

   ```bash
   source ~/macos-actions/.venv/bin/activate
   OSX_ACTIONS_KEY="$(security find-generic-password -s osx_actions_key -w)" \
   OSX_ACTIONS_CONFIG="${HOME}/Library/Application Support/macos-actions/actions.yml" \
   uvicorn macos_actions.service.main:app --host 127.0.0.1 --port 8765
   ```

2. In another terminal, call the health endpoint:

   ```bash
   curl http://127.0.0.1:8765/health
   ```

3. Exercise a script (replace key names if you customized them):

   ```bash
   API_KEY=$(security find-generic-password -s osx_actions_key -w)
   curl -X POST http://127.0.0.1:8765/scripts/unread_email_yesterday/run \
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

## 6. Install the LaunchAgent

1. Create a wrapper script that loads the API key from Keychain and launches
   uvicorn. Save as `~/macos-actions/bin/start-gateway.sh`:

   ```bash
   mkdir -p ~/macos-actions/bin
   cat <<'SH' > ~/macos-actions/bin/start-gateway.sh
   #!/bin/bash
   set -euo pipefail
   BASE_DIR="$HOME/macos-actions"
   source "$BASE_DIR/.venv/bin/activate"
   export OSX_ACTIONS_CONFIG="$HOME/Library/Application Support/macos-actions/actions.yml"
   export OSX_ACTIONS_KEY="$(/usr/bin/security find-generic-password -s osx_actions_key -w)"
   exec uvicorn macos_actions.service.main:app --host 127.0.0.1 --port 8765
   SH
   chmod 700 ~/macos-actions/bin/start-gateway.sh
   ```

2. Create `~/Library/LaunchAgents/com.you.macos-actions.plist`:

   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0"><dict>
     <key>Label</key><string>com.you.macos-actions</string>
     <key>ProgramArguments</key>
     <array>
       <string>/bin/bash</string>
       <string>$HOME/macos-actions/bin/start-gateway.sh</string>
     </array>
     <key>RunAtLoad</key><true/>
     <key>KeepAlive</key><true/>
     <key>StandardOutPath</key><string>$HOME/Library/Logs/macos-actions.out</string>
     <key>StandardErrorPath</key><string>$HOME/Library/Logs/macos-actions.err</string>
   </dict></plist>
   ```

3. Load the agent:

   ```bash
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.you.macos-actions.plist
   launchctl kickstart -k gui/$(id -u)/com.you.macos-actions
   ```

4. Verify:

   ```bash
   launchctl list | grep macos-actions
   tail -f ~/Library/Logs/macos-actions.out
   ```

macOS may prompt once to allow “start-gateway.sh” (or `osascript`) to control
Mail/Calendar. Approve these prompts.

---

## 7. Connect autosizer (or MCP clients)

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

## 8. Scheduling checks (optional)

To automate daily digests or hourly new-mail pings, create additional
LaunchAgents that `curl` the `/reports/email-digest` endpoint and post the
result to your LLM. A minimal hourly example:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.you.macos-actions.hourly</string>
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

## 9. Troubleshooting

- **`invalid api key`** – confirm the LaunchAgent exports the same key autosizer
  uses. Re-run the Keychain command to verify.
- **`osascript error`** – run the AppleScript manually (`osascript path.scpt`) to
  inspect the failure. Grant Automation permissions if prompted.
- **No JSON in `parsed`** – adjust your AppleScript to `return` a JSON string.
  Any raw text is still preserved in `stdout`.
- **Permission prompts** – approve access for Mail/Calendar once; macOS caches
  this for the calling binary (`osascript` and your shell script).

You now have a hardened, host-native gateway that your LLM stack can call to
summarize unread mail, list meetings, and poll for new messages.
