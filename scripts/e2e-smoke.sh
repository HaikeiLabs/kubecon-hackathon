#!/usr/bin/env bash
# End-to-end smoke test for a running Friction Desk API.
#
#   API_URL=http://localhost:8080 scripts/e2e-smoke.sh
#   API_URL=http://localhost:8080 RESET=1 scripts/e2e-smoke.sh   # reseed v2 indices first
#
# It creates one report and one bucket. RESET=1 calls /api/admin/reset, which
# rebuilds only friction-desk-concepts-v1, friction-desk-reports-v2 and
# friction-desk-buckets-v2 from backend/seed/. Exits non-zero on the first failed check.
set -euo pipefail

API_URL="${API_URL:-http://localhost:8080}"
API_URL="${API_URL%/}"
PASS=0

ok()   { PASS=$((PASS + 1)); printf '  ok   %s\n' "$1"; }
fail() { printf '  FAIL %s\n' "$1" >&2; [ -n "${2:-}" ] && printf '       %s\n' "$2" >&2; exit 1; }

# json EXPR: evaluates a Python expression against stdin JSON bound to `d`.
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

# request METHOD PATH [BODY] [EXTRA_CURL_ARGS...]: sets STATUS and BODY.
request() {
  local method=$1 path=$2 data=${3:-}
  shift 3 2>/dev/null || shift $#
  local out
  out=$(curl -sS -X "$method" -w $'\n%{http_code}' \
    -H 'Content-Type: application/json' "$@" \
    ${data:+--data "$data"} "$API_URL$path") || fail "$method $path" "curl error"
  STATUS=${out##*$'\n'}
  BODY=${out%$'\n'*}
}

echo "Friction Desk smoke test against $API_URL"

request GET /health/ready
[ "$STATUS" = 200 ] || fail "API ready" "HTTP $STATUS: $BODY"
ok "API ready"

if [ "${RESET:-0}" = 1 ]; then
  request POST /api/admin/reset
  [ "$STATUS" = 200 ] || fail "reset and seed" "HTTP $STATUS: $BODY"
  ok "reset and seed: $BODY"
fi

request GET "/api/concepts?q=wifi%20keeps%20dropping"
[ "$STATUS" = 200 ] || fail "concept linking" "HTTP $STATUS: $BODY"
linked=$(echo "$BODY" | json '",".join(c["concept_id"] for c in d)')
[ -n "$linked" ] || fail "concept linking" "no concepts linked; are concepts loaded? try RESET=1"
ok "concept linking: $linked"

request POST /api/reports \
  '{"description":"The wifi keeps dropping in the main hall and I cannot get online for the demo","location":"Main hall"}'
[ "$STATUS" = 201 ] || fail "submit report" "HTTP $STATUS: $BODY"
REPORT_ID=$(echo "$BODY" | json 'd["id"]')
concepts=$(echo "$BODY" | json '",".join(d["concept_ids"])')
ok "submit report $REPORT_ID"

case "$(echo "$concepts" | tr '[:upper:]' '[:lower:]')" in
  *wifi*) ok "report tagged with a Wi-Fi concept ($concepts)" ;;
  *) fail "report tagged with a Wi-Fi concept" "got: ${concepts:-none}" ;;
esac

disposition=$(echo "$BODY" | json '(d.get("triage") or {}).get("disposition", "")')
[ -n "$disposition" ] || fail "triage proposal attached" "$BODY"
ok "triage proposal attached ($disposition)"

request GET "/api/buckets/search?q=cannot%20get%20online"
top=$(echo "$BODY" | json 'd[0]["bucket"]["title"] if d else ""')
[ "$STATUS" = 200 ] && [ -n "$top" ] || fail "bucket search returns results" "HTTP $STATUS: $BODY"
ok "bucket search top hit: $top"

request POST "/api/reports/$REPORT_ID/confirm" '{"new_bucket_title":"Smoke test: main hall wifi"}'
[ "$STATUS" = 403 ] || fail "confirm without organizer role is denied" "HTTP $STATUS: $BODY"
ok "confirm without organizer role denied (403)"

request GET "/api/reports/$REPORT_ID"
status=$(echo "$BODY" | json 'd["status"]')
[ "$status" != confirmed ] || fail "denied confirm left report unchanged" "status=$status"
ok "denied confirm left report unchanged ($status)"

request POST "/api/reports/$REPORT_ID/confirm" '{"new_bucket_title":"Smoke test: main hall wifi"}' -H 'X-Role: organizer'
[ "$STATUS" = 200 ] || fail "organizer confirm" "HTTP $STATUS: $BODY"
status=$(echo "$BODY" | json 'd["status"]')
[ "$status" = confirmed ] || fail "organizer confirm sets status" "status=$status"
ok "organizer confirm -> $status"

request GET "/api/audit?limit=50"
decisions=$(echo "$BODY" | REPORT_ID=$REPORT_ID json '",".join(sorted({e["decision"] for e in d if e.get("session_id") == __import__("os").environ["REPORT_ID"]}))')
[ "$decisions" = "allow,deny" ] || fail "audit records allow and deny for this report" "got: ${decisions:-none}"
ok "audit records allow and deny"

echo "PASS: $PASS checks"
