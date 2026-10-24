"""Gait daemon: FastAPI on 127.0.0.1:7777 (loopback only).

Serves /status, /attest, /events (SSE), /stepup/*, /enroll/*, and the
dashboard web app.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from gait.attest import jws as jws_mod
from gait.paths import REPO_ROOT

DASH_DIST = REPO_ROOT / "web" / "dashboard" / "dist"
ATTEST_TTL_S = 10


class EnrollStart(BaseModel):
    profile_id: str
    display_name: str = ""
    role: str = "impostor"


def create_app(scorer, pump=None, enroll_mgr=None, stepup_mgr=None,
               profile: str = "user") -> FastAPI:
    app = FastAPI(title="gait-daemon")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
        allow_headers=["*"],
    )

    def _signer():
        from gait.attest.signer import get_signer
        return get_signer()

    def _device_id():
        from .enroll import device_id
        return device_id()

    last_attest: dict = {"payload": None}
    touchid: dict = {"until": 0.0}

    @app.get("/status")
    def status():
        st = scorer.status()
        s = _signer()
        return {
            "score": st["score"],
            "modalities": st["modalities"],
            "bot_flag": st["bot_flag"],
            "last_input_age_s": st["last_input_age_s"],
            "key_backend": s.backend,
            "profile": profile,
            "ready": st["ready"],
            "device_id": _device_id(),
        }

    def _require_loopback(request: Request):
        host = request.client.host if request.client else ""
        if host not in ("127.0.0.1", "::1", "testclient"):
            raise HTTPException(403, "attestation is loopback-only")

    @app.get("/attest")
    def attest(nonce: str, request: Request):
        _require_loopback(request)
        score = scorer.score
        if score is None:
            raise HTTPException(409, "no behavioral signal yet — type something")
        st = scorer.status()
        now = int(time.time())
        s = _signer()
        payload = {
            "iss": "gait-daemon",
            "device_id": _device_id(),
            "nonce": nonce,
            "score": round(float(score), 4),
            "window_ms": 5000,
            "modalities": {
                "keys": round(st["modalities"]["keys"], 4)
                if st["modalities"]["keys"] is not None else None,
                "pointer": round(st["modalities"]["pointer"], 4)
                if st["modalities"]["pointer"] is not None else None,
            },
            "iat": now,
            "exp": now + ATTEST_TTL_S,
            "key_backend": s.backend,
            "biometric": time.time() < touchid["until"],
        }
        token = jws_mod.encode(payload, s.sign_raw)
        last_attest["payload"] = payload
        from fastapi.responses import JSONResponse
        return JSONResponse({"jws": token, "payload": payload},
                            headers={"X-Gait-Attestation": token})

    @app.get("/last_attest")
    def get_last_attest():
        return {"payload": last_attest["payload"]}

    @app.post("/touchid")
    def touchid_prompt(request: Request):
        """Hardware recovery rung: prompt Touch ID via LocalAuthentication.
        Success arms the next 60s of attestations with biometric=true."""
        _require_loopback(request)
        import subprocess
        from gait.attest.signer import SWIFT_BIN
        if not SWIFT_BIN.exists():
            raise HTTPException(501, "biometric CLI not built")
        try:
            out = subprocess.run([str(SWIFT_BIN), "bio"], capture_output=True,
                                 text=True, timeout=60)
        except subprocess.TimeoutExpired:
            raise HTTPException(408, "Touch ID timed out")
        if out.returncode == 0:
            touchid["until"] = time.time() + 60
            return {"ok": True, "valid_for_s": 60}
        return {"ok": False}

    @app.post("/demo/set")
    def demo_set(score: float, signals: str = ""):
        """Demo-playback: drive the behavioral score along a scripted timeline
        (present -> absent -> fraud). Real attestation + verification underneath;
        only the presence value is scripted. No-op unless the scorer supports it."""
        if hasattr(scorer, "set"):
            scorer.set(score)
            if hasattr(scorer, "bot_flag"):
                scorer.bot_flag = score < 0.08
            return {"ok": True, "score": score}
        return {"ok": False, "reason": "live scorer; demo-set ignored"}

    @app.get("/events")
    async def events(request: Request):
        async def gen():
            while True:
                if await request.is_disconnected():
                    break
                st = scorer.status()
                yield {"event": "score", "data": json.dumps({
                    "t": time.time(),
                    "score": st["score"],
                    "keys": st["modalities"]["keys"],
                    "pointer": st["modalities"]["pointer"],
                    "bot_flag": st["bot_flag"],
                    "last_input_age_s": st["last_input_age_s"],
                    "ready": st["ready"],
                    "signals": st.get("signals", {}),
                })}
                await asyncio.sleep(0.5)
        return EventSourceResponse(gen())

    if stepup_mgr is not None:
        @app.post("/stepup/start")
        def stepup_start():
            return stepup_mgr.start()

        @app.post("/stepup/finish")
        def stepup_finish():
            result = stepup_mgr.finish()
            if "score" in result and hasattr(scorer, "rolling"):
                # freshest evidence wins: reset the rolling score to it
                scorer.rolling.S = result["score"]
            return result

    if enroll_mgr is not None:
        @app.post("/enroll/start")
        def enroll_start(body: EnrollStart):
            return enroll_mgr.start(body.profile_id, body.display_name, body.role)

        @app.get("/enroll/progress")
        def enroll_progress():
            return enroll_mgr.progress()

        @app.post("/enroll/finish")
        def enroll_finish():
            try:
                return enroll_mgr.finish()
            except RuntimeError as e:
                raise HTTPException(400, str(e))

    if DASH_DIST.exists():
        from fastapi.responses import RedirectResponse

        @app.get("/enroll")
        def enroll_redirect():
            return RedirectResponse("/#/enroll")

        app.mount("/", StaticFiles(directory=DASH_DIST, html=True), name="web")

    return app


def main() -> None:
    import argparse
    import threading
    import webbrowser

    import uvicorn

    from gait.capture.buffer import RingBuffer
    from gait.capture.eventtap import start_capture_thread
    from gait.model.runtime import ModelBundle
    from .pump import EventPump
    from .scorer import Scorer
    from .enroll import EnrollmentManager
    from .stepup import StepUpManager

    ap = argparse.ArgumentParser()
    ap.add_argument("--collect", action="store_true",
                    help="append genuine 'user' windows during normal use")
    ap.add_argument("--enroll-open", action="store_true",
                    help="open the enrollment UI in the browser")
    ap.add_argument("--guard", action="store_true",
                    help="lock the screen when someone else is at the keyboard")
    ap.add_argument("--demo", action="store_true",
                    help="demo-playback: scripted scorer driven by /demo/set, "
                         "auto-registers with the verifier (for filming)")
    ap.add_argument("--port", type=int, default=7777)
    args = ap.parse_args()

    import os
    demo = args.demo or os.environ.get("CADENCE_DEMO") == "1"

    buffer = RingBuffer()
    pump = EventPump(buffer)
    pump.start()
    enroll_mgr = EnrollmentManager(pump)

    if demo:
        from .scorer import FakeScorer
        scorer = FakeScorer(0.94)
        print("[daemon] DEMO mode — scripted scorer, drive with POST /demo/set?score=")

        def _register():
            import httpx
            from gait.attest.signer import get_signer
            from .enroll import device_id
            vurl = os.environ.get("GAIT_VERIFIER_URL", "http://127.0.0.1:7800")
            for _ in range(20):
                try:
                    httpx.post(f"{vurl}/register", json={
                        "device_id": device_id(),
                        "pubkey_pem": get_signer().public_key_pem,
                        "label": "cadence demo mac"}, timeout=4)
                    print("[daemon] registered device with verifier (demo)")
                    return
                except Exception:
                    time.sleep(1.5)
        threading.Thread(target=_register, daemon=True).start()
        stepup_mgr = StepUpManager(pump, lambda: None)
        bundle = None
    else:
        start_capture_thread(buffer)
        bundle = None
        try:
            b = ModelBundle.load()
            if b.ready():
                bundle = b
                print(f"[daemon] models loaded (keys model: {b.active_keys_model})")
            else:
                print("[daemon] no trained models yet — scoring disabled until enrollment+train")
        except Exception as e:
            print(f"[daemon] model load failed: {e}")
        scorer = Scorer(buffer, pump, bundle)
        scorer.start()
        stepup_mgr = StepUpManager(pump, lambda: scorer.bundle)

    if args.collect and bundle is not None:
        from gait.features.keystroke import extract_key_windows
        from gait.features.pointer import extract_pointer_windows
        from gait.paths import enroll_dir
        sub = pump.subscribe(horizon_s=None)
        sid = "collect_" + time.strftime("%Y%m%d_%H%M%S")

        def collector():
            pdir = enroll_dir() / "user"
            pdir.mkdir(parents=True, exist_ok=True)
            while True:
                time.sleep(60)
                keys, pointer = sub.drain()
                recs = (extract_key_windows(keys, "user", sid)
                        + extract_pointer_windows(pointer, "user", sid))
                if recs:
                    with open(pdir / f"{sid}.jsonl", "a") as f:
                        for r in recs:
                            f.write(r.to_json() + "\n")
        threading.Thread(target=collector, daemon=True).start()
        print("[daemon] --collect: appending genuine windows every 60s")

    if args.guard and bundle is not None:
        import subprocess
        from gait.model.runtime import ModelBundle as _MB

        def guard():
            t_low = (bundle.policy or {}).get("t_low", 0.40)
            below_since = None
            cooldown_until = 0.0
            while True:
                time.sleep(1.0)
                now = time.monotonic()
                s = scorer.score
                idle = scorer.last_input_age_s()
                active = idle is not None and idle < 5.0
                if s is not None and s < t_low and active and now > cooldown_until:
                    below_since = below_since or now
                    if now - below_since >= 6.0:
                        print(f"[guard] score {s:.2f} < {t_low} for 6s — locking screen")
                        subprocess.run(["osascript", "-e",
                                        'tell application "System Events" to '
                                        'key code 12 using {control down, command down}'])
                        cooldown_until = now + 45.0
                        below_since = None
                else:
                    below_since = None
        threading.Thread(target=guard, daemon=True).start()
        print("[daemon] --guard: screen locks after 6s of non-user input")

    app = create_app(scorer, pump, enroll_mgr, stepup_mgr)

    if args.enroll_open:
        threading.Timer(1.5, lambda: webbrowser.open(
            f"http://127.0.0.1:{args.port}/enroll")).start()

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
