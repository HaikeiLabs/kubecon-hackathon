#!/usr/bin/env bash
# Local check of the production frontend image's same-origin contract.
# Builds frontend/Dockerfile (no push), runs it beside a stub API on a private
# Docker network, and asserts that:
#   - /, unknown SPA paths, and /index.html serve the built index.html
#   - /api/* and /health/* are proxied to API_UPSTREAM with method, path,
#     query, and body preserved
#   - missing /assets/* return 404 rather than index.html
#   - /frontend-healthz answers without the API
# No cluster, registry, or Elasticsearch access is needed or used.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ID="fd-proxy-check-$$"
IMAGE="friction-desk-frontend:proxy-check"
NET="$ID-net"
PORT="${PROXY_CHECK_PORT:-18081}"

cleanup() {
  docker rm -f "$ID-ui" "$ID-api" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "ok   $*"; }

docker build -q -t "$IMAGE" -f "$ROOT/frontend/Dockerfile" "$ROOT/frontend" >/dev/null
docker network create "$NET" >/dev/null

# Stub API: echoes method, path+query, and body as JSON so the proxy hop is observable.
docker run -d --name "$ID-api" --network "$NET" --network-alias friction-desk-api \
  python:3.13-slim python -c '
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def _reply(self):
        n = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(n).decode() if n else ""
        out = json.dumps({"stub": True, "method": self.command, "path": self.path, "body": body}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)
    do_GET = do_POST = _reply
HTTPServer(("0.0.0.0", 8080), H).serve_forever()
' >/dev/null

# Uses the image default API_UPSTREAM (http://friction-desk-api:8080) and the
# same read-only-root layout as the Helm chart (emptyDir mounts are world-writable).
docker run -d --name "$ID-ui" --network "$NET" -p "127.0.0.1:$PORT:8080" \
  --read-only --tmpfs /tmp:mode=1777 --tmpfs /etc/nginx/conf.d:mode=1777 --user 101:101 "$IMAGE" >/dev/null

BASE="http://127.0.0.1:$PORT"
for _ in $(seq 1 30); do
  curl -fsS "$BASE/frontend-healthz" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -fsS "$BASE/frontend-healthz" >/dev/null || { docker logs "$ID-ui" >&2; fail "frontend did not become ready"; }
pass "/frontend-healthz"

for path in / /organizer /some/deep/route /index.html; do
  body="$(curl -fsS "$BASE$path")" || fail "GET $path"
  grep -q '<div id="root">' <<<"$body" || fail "GET $path did not serve index.html"
  pass "GET $path -> index.html"
done

asset="$(curl -fsS "$BASE/" | grep -o '/assets/[^"]*\.js' | head -1)"
[ -n "$asset" ] || fail "no built JS asset referenced from index.html"
curl -fsS -o /dev/null "$BASE$asset" || fail "GET $asset"
pass "GET $asset"

code="$(curl -s -o /dev/null -w '%{http_code}' "$BASE/assets/does-not-exist.js")"
[ "$code" = 404 ] || fail "missing asset returned $code, want 404"
pass "missing asset -> 404"

expect_proxy() {
  local method="$1" path="$2" data="${3:-}" got
  if [ -n "$data" ]; then
    got="$(curl -fsS -X "$method" -H 'content-type: application/json' -d "$data" "$BASE$path")"
  else
    got="$(curl -fsS -X "$method" "$BASE$path")"
  fi
  python3 -c '
import json, sys
got = json.loads(sys.argv[1])
want = {"stub": True, "method": sys.argv[2], "path": sys.argv[3], "body": sys.argv[4]}
assert got == want, f"got {got}, want {want}"
' "$got" "$method" "$path" "$data" || fail "$method $path not proxied intact"
  pass "$method $path -> API"
}

expect_proxy GET /health/live
expect_proxy GET /health/ready
expect_proxy GET /api/reports
expect_proxy GET /api/buckets
expect_proxy GET '/api/buckets/search?q=accessible%20entrance&limit=5'
expect_proxy POST /api/reports '{"description":"Hall B entrance blocked","location":"Hall B"}'

echo "frontend same-origin proxy check passed"
