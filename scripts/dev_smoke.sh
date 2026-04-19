#!/usr/bin/env bash
# Backend-only smoke test: hits every REST surface without touching Claude,
# Gemini, or the Chrome extension. Useful for a quick "does it boot" after a refactor.
#
# Usage:
#   ./scripts/dev_smoke.sh [PORT]
#
# Assumes the backend is already running (uvicorn app.main:app --port 8787).
set -euo pipefail

PORT="${1:-8787}"
API="http://localhost:${PORT}"

say() { printf "\n\033[1;36m== %s ==\033[0m\n" "$1"; }

say "healthz"
curl -sf "$API/healthz" | python -m json.tool

say "status"
curl -sf "$API/api/status" | python -m json.tool

say "upsert business profile"
curl -sf -X PUT "$API/api/business-profile" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Smoke Inc.","description":"Dev-only test profile."}' \
  | python -m json.tool

say "create target"
curl -sf -X POST "$API/api/targets" \
  -H 'Content-Type: application/json' \
  -d '{"platform_id":"facebook","external_id":"https://www.facebook.com/groups/smoke","name":"Smoke Test Group"}' \
  | python -m json.tool || true

say "list targets"
curl -sf "$API/api/targets" | python -m json.tool

say "create manual draft post"
POST_ID=$(curl -sf -X POST "$API/api/posts" \
  -H 'Content-Type: application/json' \
  -d '{"post_type":"informative","text":"Manual draft for smoke test."}' \
  | python -c 'import json,sys;print(json.load(sys.stdin)["id"])')
echo "Draft id: $POST_ID"

say "list posts"
curl -sf "$API/api/posts" | python -m json.tool | head -40

say "feedback"
curl -sf -X POST "$API/api/feedback" \
  -H 'Content-Type: application/json' \
  -d "{\"post_id\": $POST_ID, \"rating\": \"up\"}" \
  | python -m json.tool

echo
echo "Smoke test done. Delete the test row if you care:"
echo "  curl -X DELETE $API/api/posts/$POST_ID"
