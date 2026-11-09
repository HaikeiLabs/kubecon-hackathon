#!/usr/bin/env bash
# Stop the launchd agents started by demo/up.sh. Leaves logs in demo/logs/.
set -uo pipefail
DOMAIN="gui/$(id -u)"
for label in dev.friction-desk.ui dev.friction-desk.api; do
  if launchctl bootout "$DOMAIN/$label" 2>/dev/null; then echo "stopped $label"; else echo "$label not running"; fi
done
