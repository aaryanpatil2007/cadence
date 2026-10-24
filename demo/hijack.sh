#!/usr/bin/env bash
# T3 + T4 attack demo, run from a SECOND laptop on the same Wi-Fi:
#   ./hijack.sh <mac-ip> <stolen-session-cookie> [captured-jws]
#
# 1. stolen cookie, no attestation      -> 401
# 2. replay a previously-allowed JWS    -> deny: nonce used
# 3. (same JWS 10s later)               -> deny: attestation expired
set -u
HOST="${1:?usage: hijack.sh <mac-ip> <session-cookie> [captured-jws]}"
COOKIE="${2:?need the stolen gait_session cookie value}"
JWS="${3:-}"

BANK="http://$HOST:7900"

echo "== attack 1: stolen session cookie, no attestation =="
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST "$BANK/transfer" \
  -H "Content-Type: application/json" \
  -b "gait_session=$COOKIE" \
  -d '{"to":"savings","amount":500,"memo":"hijacked"}'

if [ -n "$JWS" ]; then
  echo
  echo "== attack 2: replay a captured attestation =="
  curl -s -X POST "$BANK/transfer" \
    -H "Content-Type: application/json" \
    -b "gait_session=$COOKIE" \
    -d "{\"to\":\"savings\",\"amount\":500,\"memo\":\"replayed\",\"jws\":\"$JWS\"}"
  echo
fi
