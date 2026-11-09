# Recorded demo

Runs the API and UI as launchd user agents (so they keep running outside any
terminal), drives the real UI with a headed Playwright script that shows a
caption for each step, and screen-records it with `screencapture`.

```sh
demo/up.sh                    # API :8080 + UI :5173 under launchd (RESET=1 to reseed v2 indices)
cd demo && npm ci             # Playwright, pinned; uses your installed Google Chrome
node walkthrough.mjs          # run the scripted walkthrough (PACE=1.5 for slower)
./record.sh                   # record it to out/friction-desk-demo.mov + .mp4
demo/down.sh                  # stop the launchd agents
```

- `up.sh` renders `launchd/service.plist.tmpl` into `.run/` and runs `launchctl bootstrap gui/$UID`.
  The API sources `ENV_FILE` (default: repo-root `.env`, needs `ELASTICSEARCH_URL` and
  `ELASTICSEARCH_API_KEY`) at start. No secret values are written into the plists. Logs go to `logs/`.
- The walkthrough: an attendee files a report → the organizer inbox shows its ontology concept
  chips and the AI suggestion → confirming as the attendee agent is denied by policy (shown
  next to the audit deny) → the organizer confirms → the audit log shows the allow.
  Each run adds one report and confirms it.
- `SHOTS=1` saves a screenshot per caption to `out/shots/`. `VIDEO=1` makes Playwright write a `.webm`,
  which needs Playwright's own ffmpeg build (`npx playwright install ffmpeg`); `record.sh` doesn't.
- `record.sh` options: `SECONDS_MAX` (default 90), `REGION=x,y,w,h`, `DISPLAY_NUM`, `OUT`.
  macOS asks for Screen Recording permission the first time.
- The walkthrough adds recording-only CSS (shorter bucket list, pinned side column) so the
  Governance panel stays on screen. The app itself is unchanged.
