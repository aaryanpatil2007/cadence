#!/usr/bin/env bash
# Run verifier + bank + daemon together (daemon in foreground for permission
# prompts). Ctrl-C stops everything.
set -u
cd "$(dirname "$0")/.."
PY=.venv/bin/python

$PY -m gait.verify.app &
VPID=$!
$PY -m bank.app &
BPID=$!
trap 'kill $VPID $BPID 2>/dev/null' EXIT

echo "verifier :7800  bank :7900  daemon :7777 (starting...)"
echo "dashboard: http://127.0.0.1:7777   bank: http://127.0.0.1:7900"
$PY -m gait.daemon.app "$@"
