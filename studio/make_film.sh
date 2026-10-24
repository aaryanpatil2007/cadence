#!/usr/bin/env bash
# Re-film Cadence end to end. Requires the demo stack running:
#   ../scripts/run_demo.sh   (in another terminal)
# Then:  ./make_film.sh          -> out/cadence.mp4
#        ./make_film.sh <scene>  -> capture one scene only, then assemble
set -e
cd "$(dirname "$0")"

echo "1/3  rendering captions…"
node captions.mjs

echo "2/3  capturing scenes (drives the real UI)…"
node film.mjs "$@"

echo "3/3  assembling…"
../.venv/bin/python assemble.py

echo "done -> out/cadence.mp4"
