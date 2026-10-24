# Cadence demo film studio

Records the **real** Cadence UI (no mockups) into a ~80s investor/judge film.
Method (from the motion playbook): drive the live app with Playwright + an
animated cursor, capture smooth frames via Chromium screencast, assemble with
ffmpeg, score synthesized in code, sparse white-pill captions.

## Make the film

```bash
# 1. start the demo stack (scripted scorer, seeded console, live pulse)
../scripts/run_demo.sh            # in a separate terminal

# 2. render it
./make_film.sh                    # -> out/cadence.mp4  (1920x1080)
# or iterate one scene:
./make_film.sh console            # capture just that scene, then assemble
```

Presence is scripted per scene via `POST /demo/set?score=` (see `film.mjs`);
everything else is the real product (real CRS + Capital One calls, real
Secure-Enclave signing, real risk engine).

## Pieces

- `film.mjs` — scene list: what the cursor types/clicks/scrolls per beat.
- `capture.mjs` — drives the UI, injects the cursor, screencast-captures frames.
- `film.json` — cut list (trims/holds) + caption text and timing.
- `captions.mjs` — renders each caption to a transparent white-pill PNG.
- `score.py` — synthesizes the ambient score (numpy).
- `assemble.py` — clips → xfade crossfades → caption overlays → score → mux.
- `props/logo.html` — the 1.5s logo intro.

## Beats

logo → trained-on-you (our own model, 136M keystrokes) → the behavioral
model's live view (signals, Secure Enclave) → a normal payment approved
(Capital One, live) → the trust console → CRS identity vault (synthetic flagged)
→ someone else at the keyboard (blocked) → high-value → CRS bureau rejects a
synthetic identity → recover → close.

## Re-editing

Edit `film.json` (captions/timing/holds) or `film.mjs` (actions), then
`./make_film.sh`. `SKIP_CLIPS=1 python assemble.py` reuses captured clips for a
fast re-assemble when you only changed captions/timing.
