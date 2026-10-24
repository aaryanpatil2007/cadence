"""Live diagnostic: capture N seconds of real typing, score every window
against L0, the deployed encoder, and the frozen pretrained encoder.

Run while the enrolled user types naturally. Prints per-window probabilities
so we can see which variant actually recognizes them live.
"""
import sys
import time

import numpy as np
import torch

from gait.capture.buffer import RingBuffer
from gait.capture.eventtap import start_capture_thread
from gait.daemon.pump import EventPump
from gait.features.keystroke import extract_key_windows
from gait.model.encoder import KeystrokeEncoder, pad_batch, topk_cos
from gait.model.runtime import ModelBundle
from gait.paths import models_dir

DURATION_S = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0


def main():
    buf = RingBuffer()
    start_capture_thread(buf)
    pump = EventPump(buf, poll_s=0.1)
    pump.start()
    sub = pump.subscribe(horizon_s=None)
    print(f"[diagnose] capturing {DURATION_S:.0f}s — TYPE NATURALLY NOW", flush=True)
    time.sleep(DURATION_S)
    keys, _ = sub.drain()
    n_down = sum(1 for e in keys if e["type"] == "down")
    print(f"[diagnose] captured {n_down} keydowns")
    recs = extract_key_windows(keys, "diag", "diag")
    recs = [r for r in recs if r.seq]
    if not recs:
        print("[diagnose] no scoreable windows — too little typing")
        return

    b = ModelBundle.load()
    enroll = np.load(models_dir() / "enroll_embs.npy")

    frozen = KeystrokeEncoder()
    frozen.load_state_dict(torch.load(models_dir() / "encoder_pretrained.pt",
                                      map_location="cpu"))
    frozen.eval()
    # frozen variant needs its own enrollment embeddings
    from gait.model.train import load_records, split_user, _by_modality, _seq_arrays, _embed
    profiles = load_records()
    ut, _ = split_user(profiles["user"])
    enroll_frozen = _embed(frozen, _seq_arrays(_by_modality(ut, "keys")))

    print(f"\n{'win':>3} {'keys':>5} {'L0 raw':>8} {'p_deployed':>10} "
          f"{'cos_deploy':>10} {'cos_frozen':>10}")
    cos_d, cos_f, p_dep = [], [], []
    for i, r in enumerate(recs):
        raw0 = b.keys_raw_l0(r)
        c_d = b.keys_raw_l1(r)
        rows, mask = pad_batch([np.array(r.seq, dtype=np.float32)])
        with torch.no_grad():
            emb = frozen(rows, mask).numpy()[0]
        c_f = float(topk_cos(enroll_frozen, emb)[0])
        p = b.p_keys(r)
        cos_d.append(c_d); cos_f.append(c_f); p_dep.append(p)
        print(f"{i:>3} {len(r.seq):>5} {raw0:>8.1f} {p:>10.3f} "
              f"{c_d:>10.3f} {c_f:>10.3f}")
    print(f"\nmedians: p_deployed={np.median(p_dep):.3f}  "
          f"cos_deployed={np.median(cos_d):.3f}  cos_frozen={np.median(cos_f):.3f}")
    print("(enrollment-time genuine cos was ~0.5-0.9; impostors ~0.2 and below)")


if __name__ == "__main__":
    main()
