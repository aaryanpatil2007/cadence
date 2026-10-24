#!/usr/bin/env bash
# Launch the full Cadence stack in DEMO mode (scripted scorer, seeded console
# population, live pulse). Everything real underneath; presence is scripted via
# POST http://127.0.0.1:7777/demo/set?score=<0..1>.
#
#   verifier + console :7800   bank (Meridian) :7900   daemon :7777 + dashboard
set -u
cd "$(dirname "$0")/.."
PY=.venv/bin/python
export CADENCE_DEMO=1

# fresh demo data each run
rm -f data/verifier.sqlite* data/bank.sqlite* data/nessie.json 2>/dev/null

$PY -m gait.verify.app > /tmp/cadence_verifier.log 2>&1 &
VPID=$!
$PY -m bank.app > /tmp/cadence_bank.log 2>&1 &
BPID=$!
sleep 3
$PY -m gait.daemon.app --demo > /tmp/cadence_daemon.log 2>&1 &
DPID=$!
trap 'kill $VPID $BPID $DPID 2>/dev/null' EXIT

echo "Cadence demo stack:"
echo "  Console : http://127.0.0.1:7800        (trust console — hero)"
echo "  Meridian: http://127.0.0.1:7900        (consumer bank)"
echo "  Monitor : http://127.0.0.1:7777        (behavioral dashboard)"
echo "  drive presence: curl -X POST '127.0.0.1:7777/demo/set?score=0.94'"
wait
