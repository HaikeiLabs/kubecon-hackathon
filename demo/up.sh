#!/usr/bin/env bash
# Start the Friction Desk API and UI as launchd user agents so they outlive this
# terminal (handy while screen recording). Stop them with demo/down.sh.
#
#   demo/up.sh                 # API :8080, UI :5173
#   RESET=1 demo/up.sh         # also reseed the v2 indices from backend/seed/
#   ENV_FILE=/path/.env demo/up.sh
#
# ENV_FILE must define ELASTICSEARCH_URL and ELASTICSEARCH_API_KEY. It is sourced
# by the API process at start; its values are never written into the plists.
set -euo pipefail

DEMO_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$DEMO_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO/.env}"
API_PORT="${API_PORT:-8080}"
UI_PORT="${UI_PORT:-5173}"
RUN="$DEMO_DIR/.run"
LOGS="$DEMO_DIR/logs"
DOMAIN="gui/$(id -u)"
SVC_PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

[ -f "$ENV_FILE" ] || { echo "ENV_FILE not found: $ENV_FILE" >&2; exit 2; }
mkdir -p "$RUN" "$LOGS"

render() { # label workdir log command
  local esc
  esc=$(printf '%s' "$4" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/[\\&|]/\\&/g')
  sed -e "s|@LABEL@|$1|" -e "s|@WORKDIR@|$2|" -e "s|@LOG@|$3|" -e "s|@PATH@|$SVC_PATH|" -e "s|@COMMAND@|$esc|" \
    "$DEMO_DIR/launchd/service.plist.tmpl" > "$RUN/$1.plist"
  plutil -lint -s "$RUN/$1.plist"
}

start() { # label
  launchctl bootout "$DOMAIN/$1" 2>/dev/null || true
  launchctl bootstrap "$DOMAIN" "$RUN/$1.plist"
}

wait_for() { # name url seconds
  for _ in $(seq 1 "$3"); do curl -sf -o /dev/null "$2" && { echo "  $1 ready: $2"; return 0; }; sleep 1; done
  echo "  $1 not ready after $3s; see $LOGS/" >&2; return 1
}

render dev.friction-desk.api "$REPO/backend" "$LOGS/api.log" \
  "set -a; . '$ENV_FILE'; set +a; exec uv run --extra dev uvicorn app.main:app --host 127.0.0.1 --port $API_PORT"
render dev.friction-desk.ui "$REPO/frontend" "$LOGS/ui.log" \
  "[ -d node_modules ] || npm ci; API_URL=http://127.0.0.1:$API_PORT exec npm run dev:api -- --host 127.0.0.1 --port $UI_PORT --strictPort"

echo "Starting launchd agents in $DOMAIN"
start dev.friction-desk.api
start dev.friction-desk.ui
wait_for API "http://127.0.0.1:$API_PORT/health/ready" 90
wait_for UI "http://127.0.0.1:$UI_PORT/" 120

if [ "${RESET:-0}" = 1 ]; then
  echo "  reset: $(curl -sS -X POST "http://127.0.0.1:$API_PORT/api/admin/reset")"
fi

echo "UI:  http://127.0.0.1:$UI_PORT/#/report   (organizer: #/organizer)"
echo "Logs: $LOGS/   Stop: demo/down.sh"
