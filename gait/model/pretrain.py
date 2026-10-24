"""Pretrain the keystroke encoder on the Aalto 136M dataset (TypeNet-style).

SupCon over thousands of real typists -> a universal typist-embedding space.
Enrollment then only has to locate one person in that space.

Checkpoint selection by verification EER on held-out users never seen in
training. Saves data/models/encoder_pretrained.pt (+ meta).

Usage:  make pretrain
Env:    GAIT_PRETRAIN_USERS (default 2000), GAIT_PRETRAIN_SECONDS (default 1800)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
import torch

from gait.paths import REPO_ROOT, models_dir
from .aalto import load_users
from .encoder import KeystrokeEncoder, pad_batch, supcon_loss, augment, device, count_params

FILES_DIR = REPO_ROOT / "data" / "raw" / "aalto" / "extracted" / "Keystrokes" / "files"
N_USERS = int(os.environ.get("GAIT_PRETRAIN_USERS", "2000"))
TIME_BUDGET_S = float(os.environ.get("GAIT_PRETRAIN_SECONDS", "1800"))
N_VAL_USERS = 60
P_USERS, K_SEQS = 48, 4  # batch = P*K = 192
EVAL_EVERY_S = 120.0


def embed_all(model, seqs: list[np.ndarray], dev, bs: int = 512) -> np.ndarray:
    outs = []
    with torch.no_grad():
        for i in range(0, len(seqs), bs):
            rows, mask = pad_batch(seqs[i:i + bs])
            outs.append(model(rows.to(dev), mask.to(dev)).cpu().numpy())
    return np.concatenate(outs)


def verification_eer(model, val_users: dict[str, list[np.ndarray]], dev) -> float:
    """Prototype from half of each unseen user's seqs; score the other half
    (genuine) and other users' probes (impostor); return EER."""
    genuine, impostor = [], []
    protos, probes = {}, {}
    for uid, seqs in val_users.items():
        half = len(seqs) // 2
        if half < 3:
            continue
        emb = embed_all(model, seqs, dev)
        proto = emb[:half].mean(axis=0)
        proto /= (np.linalg.norm(proto) + 1e-9)
        protos[uid] = proto
        probes[uid] = emb[half:]
    uids = list(protos)
    for uid in uids:
        genuine.extend(probes[uid] @ protos[uid])
        for other in uids:
            if other != uid:
                impostor.extend(probes[other][:2] @ protos[uid])
    g, i = np.array(genuine), np.array(impostor)
    ths = np.sort(np.concatenate([g, i]))[::4]
    best, rate = 1.0, 1.0
    for t in ths:
        frr = float(np.mean(g < t))
        far = float(np.mean(i >= t))
        if abs(frr - far) < best:
            best, rate = abs(frr - far), (frr + far) / 2
    return rate


def main() -> None:
    if not FILES_DIR.exists():
        raise SystemExit(f"Aalto files not found at {FILES_DIR}")
    t_parse = time.monotonic()
    print(f"[pretrain] loading {N_USERS} train users + {N_VAL_USERS} val users …")
    val_users = load_users(FILES_DIR, N_VAL_USERS, seed=0, skip=0)
    train_users = load_users(FILES_DIR, N_USERS, seed=0, skip=N_VAL_USERS)
    n_seqs = sum(len(s) for s in train_users.values())
    print(f"[pretrain] parsed {len(train_users)} train users / {n_seqs} seqs, "
          f"{len(val_users)} val users in {time.monotonic()-t_parse:.0f}s")

    dev = device()
    model = KeystrokeEncoder().to(dev)
    print(f"[pretrain] params={count_params(model)} device={dev}")
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    rng = np.random.default_rng(0)
    uids = list(train_users)

    t0 = time.monotonic()
    last_eval = 0.0
    best_eer = 1.0
    step = 0
    mdir = models_dir()
    while time.monotonic() - t0 < TIME_BUDGET_S:
        batch_uids = rng.choice(len(uids), size=P_USERS, replace=False)
        seqs, labels = [], []
        for li, ui in enumerate(batch_uids):
            user_seqs = train_users[uids[ui]]
            idx = rng.choice(len(user_seqs), size=min(K_SEQS, len(user_seqs)),
                             replace=False)
            for j in idx:
                seqs.append(augment(user_seqs[j], rng))
                labels.append(li)
        rows, mask = pad_batch(seqs)
        emb = model(rows.to(dev), mask.to(dev))
        loss = supcon_loss(emb, torch.tensor(labels, device=dev))
        opt.zero_grad()
        loss.backward()
        opt.step()
        step += 1

        elapsed = time.monotonic() - t0
        if elapsed - last_eval > EVAL_EVERY_S:
            last_eval = elapsed
            model.eval()
            eer = verification_eer(model, val_users, dev)
            model.train()
            marker = ""
            if eer < best_eer:
                best_eer = eer
                torch.save({k: v.cpu() for k, v in model.state_dict().items()},
                           mdir / "encoder_pretrained.pt")
                marker = "  <- saved"
            print(f"[pretrain] t={elapsed:5.0f}s step={step} loss={float(loss):.3f} "
                  f"val-EER={eer:.3f} (best {best_eer:.3f}){marker}", flush=True)

    meta = {"params": count_params(model), "train_users": len(train_users),
            "sequences": n_seqs, "steps": step,
            "val_users": len(val_users), "best_val_eer": round(best_eer, 4),
            "budget_s": TIME_BUDGET_S}
    (mdir / "encoder_pretrained_meta.json").write_text(json.dumps(meta, indent=2))
    print(f"[pretrain] done: best val EER {best_eer:.3f} over {step} steps")


if __name__ == "__main__":
    main()
