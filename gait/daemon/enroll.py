"""Enrollment session controller (+ headless CLI fallback).

Raw events stay in RAM for the session; on finish only feature windows are
written to data/enroll/<profile_id>/<session_id>.jsonl.
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
import time
import uuid
from pathlib import Path

from gait.features.keystroke import extract_key_windows
from gait.features.pointer import extract_pointer_windows
from gait.paths import enroll_dir, models_dir
from .pump import EventPump, Subscriber
from .sentences import SENTENCES

GAIT_DIR = Path.home() / ".gait"
DEVICE_FILE = GAIT_DIR / "device.json"


def device_id() -> str:
    GAIT_DIR.mkdir(mode=0o700, exist_ok=True)
    if DEVICE_FILE.exists():
        return json.loads(DEVICE_FILE.read_text())["device_id"]
    did = str(uuid.uuid4())
    DEVICE_FILE.write_text(json.dumps({"device_id": did}))
    return did


class EnrollmentManager:
    def __init__(self, pump: EventPump):
        self.pump = pump
        self.active: dict | None = None
        self.sub: Subscriber | None = None

    def start(self, profile_id: str, display_name: str, role: str) -> dict:
        if self.active:
            self.pump.unsubscribe(self.sub)
        self.sub = self.pump.subscribe(horizon_s=None)  # keep whole session in RAM
        session_id = time.strftime("%Y%m%d_%H%M%S")
        sentences = random.sample(SENTENCES, 12)
        self.active = {
            "profile_id": profile_id, "display_name": display_name,
            "role": role, "session_id": session_id, "t0": time.monotonic(),
            "sentences": sentences,
        }
        return {"session_id": session_id, "sentences": sentences}

    def progress(self) -> dict:
        if not self.active or not self.sub:
            return {"active": False}
        keys, pointer = self.sub.snapshot()
        return {
            "active": True,
            "profile_id": self.active["profile_id"],
            "elapsed_s": time.monotonic() - self.active["t0"],
            "keystrokes": sum(1 for e in keys if e["type"] == "down"),
            "pointer_samples": sum(1 for e in pointer if e["type"] in ("move", "drag")),
            "clicks": sum(1 for e in pointer if e["type"] == "down"),
            "scrolls": sum(1 for e in pointer if e["type"] == "scroll"),
        }

    def finish(self, train_after: bool | None = None) -> dict:
        if not self.active or not self.sub:
            raise RuntimeError("no active enrollment")
        keys, pointer = self.sub.drain()
        self.pump.unsubscribe(self.sub)
        info = self.active
        self.active, self.sub = None, None

        pid, sid = info["profile_id"], info["session_id"]
        recs = (extract_key_windows(keys, pid, sid)
                + extract_pointer_windows(pointer, pid, sid))
        pdir = enroll_dir() / pid
        pdir.mkdir(parents=True, exist_ok=True)
        with open(pdir / f"{sid}.jsonl", "w") as f:
            for r in recs:
                f.write(r.to_json() + "\n")
        meta = {"display_name": info["display_name"], "role": info["role"]}
        (pdir / "profile.json").write_text(json.dumps(meta))

        result = {"profile_id": pid, "session_id": sid, "windows": len(recs),
                  "keys": sum(1 for r in recs if r.modality == "keys"),
                  "pointer": sum(1 for r in recs if r.modality == "pointer")}

        should_train = train_after if train_after is not None else (info["role"] == "user")
        if should_train:
            result["training"] = "started"
            subprocess.Popen(
                [sys.executable, "-m", "gait.model.train_and_register"],
                cwd=str(Path(__file__).resolve().parent.parent.parent))
        return result


def register_device(verifier_url: str) -> bool:
    """Register this device's public key with the verifier."""
    import httpx
    from gait.attest.signer import get_signer
    s = get_signer()
    try:
        r = httpx.post(f"{verifier_url}/register", json={
            "device_id": device_id(),
            "pubkey_pem": s.public_key_pem,
            "label": "gait demo mac",
        }, timeout=5)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[enroll] verifier registration failed: {e}", file=sys.stderr)
        return False


# ---------- headless CLI enrollment ----------

def run_cli(profile_id: str) -> None:
    """Terminal enrollment: capture runs globally; user types in ANY window."""
    from gait.capture.buffer import RingBuffer
    from gait.capture.eventtap import start_capture_thread

    buffer = RingBuffer()
    start_capture_thread(buffer)
    pump = EventPump(buffer)
    pump.start()
    mgr = EnrollmentManager(pump)

    role = "user" if profile_id == "user" else "impostor"
    info = mgr.start(profile_id, profile_id, role)
    print(f"\n=== GAIT CLI enrollment: {profile_id} ({role}) ===")
    print("Type each sentence below (typos fine), press Enter after each.\n")
    time.sleep(1)
    for i, s in enumerate(info["sentences"], 1):
        print(f"[{i}/12] {s}")
        input("> ")
    print("\nFree-type for 60 seconds: describe your morning in detail.")
    print("(Your text is never stored — timing features only.)")
    t0 = time.time()
    while time.time() - t0 < 60:
        try:
            input("> ")
        except EOFError:
            break
    print("\nNow 2 minutes of pointer work: move the mouse between windows,")
    print("click things, drag, and scroll naturally. Timer running...")
    for remaining in range(120, 0, -15):
        print(f"  {remaining}s left (keep moving/scrolling/clicking)")
        time.sleep(15)
    result = mgr.finish()
    print(f"\nDone: {result}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", action="store_true")
    ap.add_argument("--profile", required=True)
    args = ap.parse_args()
    run_cli(args.profile)
