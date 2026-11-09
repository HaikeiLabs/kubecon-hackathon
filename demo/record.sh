#!/usr/bin/env bash
# Screen-record the scripted UI walkthrough, then convert it to a 1080p .mp4.
# Start the services first (demo/up.sh). macOS asks for Screen Recording
# permission for your terminal the first time.
#
#   demo/record.sh                     # whole main display, 90s
#   SECONDS_MAX=120 demo/record.sh     # longer cap (also with PACE=1.5)
#   REGION=x,y,w,h demo/record.sh      # only that rectangle (points)
#   DISPLAY_NUM=2 demo/record.sh       # a different display
#   OUT=demo/out/take-2.mov demo/record.sh
#
# screencapture stops at SECONDS_MAX; the walkthrough runs ~60s at PACE=1.
set -euo pipefail
cd "$(dirname "$0")"
OUT="${OUT:-out/friction-desk-demo.mov}"
SECONDS_MAX="${SECONDS_MAX:-90}"
mkdir -p "$(dirname "$OUT")"
rm -f "$OUT"

[ -d node_modules ] || npm ci --silent

echo "Recording up to ${SECONDS_MAX}s to $OUT ..."
screencapture -v -V "$SECONDS_MAX" ${DISPLAY_NUM:+-D "$DISPLAY_NUM"} ${REGION:+-R "$REGION"} "$OUT" &
CAP=$!
sleep 1.5
node walkthrough.mjs
wait "$CAP" || { echo "screencapture failed (Screen Recording permission?)" >&2; exit 1; }

MP4="${OUT%.*}.mp4"
rm -f "$MP4"
avconvert --preset Preset1920x1080 --source "$OUT" --output "$MP4" >/dev/null
ls -lh "$OUT" "$MP4"
