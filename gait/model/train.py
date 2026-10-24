"""Train everything from data/enroll/*: L0 baselines, L1 encoder, L2 pointer GMM.

Profiles: `user` is the enrolled presenter; other non-bot profiles are human
impostors; bot_synth_* are synthetic negatives (generated here if missing).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from gait.features.schema import WindowRecord
from gait.paths import enroll_dir, models_dir
from .baseline import ScaledManhattan
from . import synth

import os

TRAIN_FRACTION = 0.7
ENCODER_TIME_BUDGET_S = float(os.environ.get("GAIT_ENCODER_BUDGET_S", "90"))


def load_records(edir: Path | None = None) -> dict[str, list[WindowRecord]]:
    edir = edir or enroll_dir()
    out: dict[str, list[WindowRecord]] = {}
    if not edir.exists():
        return out
    for pdir in sorted(edir.iterdir()):
        if not pdir.is_dir():
            continue
        recs = []
        for f in sorted(pdir.glob("*.jsonl")):
            for line in f.read_text().splitlines():
                if line.strip():
                    recs.append(WindowRecord.from_json(line))
        if recs:
            out[pdir.name] = sorted(recs, key=lambda r: (r.session_id, r.t_start))
    return out


def split_user(recs: list[WindowRecord]) -> tuple[list[WindowRecord], list[WindowRecord]]:
    """70/30 time split PER MODALITY — enrollment is typing-first/pointer-last,
    so a global chronological split would starve one side of the other."""
    train, held = [], []
    for modality in ("keys", "pointer"):
        m = [r for r in recs if r.modality == modality]
        cut = int(len(m) * TRAIN_FRACTION)
        train.extend(m[:cut])
        held.extend(m[cut:])
    train.sort(key=lambda r: (r.session_id, r.t_start))
    held.sort(key=lambda r: (r.session_id, r.t_start))
    return train, held


def _by_modality(recs: list[WindowRecord], modality: str) -> list[WindowRecord]:
    return [r for r in recs if r.modality == modality]


def stats_matrix(recs: list[WindowRecord]) -> np.ndarray:
    return np.array([r.feats for r in recs]) if recs else np.zeros((0, 1))


def train_encoder(profiles: dict[str, list[WindowRecord]],
                  user_train_keys: list[WindowRecord]) -> tuple[object, np.ndarray] | None:
    """SupCon training over identities. Returns (model, user prototype) or None."""
    import torch
    from .encoder import (KeystrokeEncoder, pad_batch, supcon_loss, augment,
                          device, count_params)

    seqs, labels = [], []
    label_map: dict[str, int] = {}
    for pid, recs in profiles.items():
        for r in _by_modality(recs, "keys"):
            if len(r.seq) >= 8:
                seqs.append(np.array(r.seq, dtype=np.float32))
                labels.append(label_map.setdefault(pid, len(label_map)))
    if len(label_map) < 2 or len(seqs) < 60:
        print(f"[train] encoder skipped: {len(seqs)} seqs, {len(label_map)} identities")
        return None

    labels = np.array(labels)
    dev = device()
    model = KeystrokeEncoder().to(dev)
    print(f"[train] encoder params: {count_params(model)}")
    opt = torch.optim.AdamW(model.parameters(), lr=3e-3)
    epochs = 60
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    rng = np.random.default_rng(0)
    batch = min(256, len(seqs))
    t0 = time.monotonic()
    for ep in range(epochs):
        idx = rng.permutation(len(seqs))
        losses = []
        for i in range(0, len(idx), batch):
            bidx = idx[i:i + batch]
            aug = [augment(seqs[j], rng) for j in bidx]
            rows, mask = pad_batch(aug)
            rows, mask = rows.to(dev), mask.to(dev)
            lab = torch.tensor(labels[bidx], device=dev)
            emb = model(rows, mask)
            loss = supcon_loss(emb, lab)
            opt.zero_grad()
            loss.backward()
            opt.step()
            losses.append(float(loss))
        sched.step()
        if time.monotonic() - t0 > ENCODER_TIME_BUDGET_S:
            print(f"[train] encoder time budget hit at epoch {ep}")
            break
    train_s = time.monotonic() - t0
    print(f"[train] encoder done in {train_s:.1f}s, last loss {np.mean(losses):.3f}")

    model.eval().to("cpu")
    proto_seqs = [np.array(r.seq, dtype=np.float32)
                  for r in user_train_keys if len(r.seq) >= 8]
    rows, mask = pad_batch(proto_seqs)
    with torch.no_grad():
        embs = model(rows, mask).numpy()
    proto = embs.mean(axis=0)
    proto /= np.linalg.norm(proto)
    meta = {"params": count_params(model), "train_seconds": round(train_s, 1),
            "identities": len(label_map), "sequences": len(seqs)}
    (models_dir() / "encoder_meta.json").write_text(json.dumps(meta))
    return model, proto


def main() -> None:
    mdir = models_dir()

    # ensure synthetic bot negatives exist
    if not any(enroll_dir().glob("bot_synth_*")):
        print("[train] generating synthetic bot sessions")
        synth.generate_all(enroll_dir())

    profiles = load_records()
    if "user" not in profiles:
        raise SystemExit("[train] no 'user' profile in data/enroll — enroll first")

    user_train, user_held = split_user(profiles["user"])
    ut_keys = _by_modality(user_train, "keys")
    ut_ptr = _by_modality(user_train, "pointer")
    print(f"[train] user train: {len(ut_keys)} key windows, {len(ut_ptr)} pointer windows")

    # L0 baselines
    if ut_keys:
        m = ScaledManhattan().fit(stats_matrix(ut_keys))
        (mdir / "baseline_keys.json").write_text(json.dumps(m.to_dict()))
    if ut_ptr:
        m = ScaledManhattan().fit(stats_matrix(ut_ptr))
        (mdir / "baseline_pointer.json").write_text(json.dumps(m.to_dict()))

    # L1 encoder
    train_profiles = dict(profiles)
    train_profiles["user"] = user_train  # never train on held-out
    result = train_encoder(train_profiles, ut_keys)
    if result is not None:
        import torch
        model, proto = result
        torch.save(model.state_dict(), mdir / "encoder.pt")
        np.save(mdir / "prototype.npy", proto)

    # L2 pointer GMM
    imp_ptr = [r for pid, recs in profiles.items() if pid != "user"
               for r in _by_modality(recs, "pointer")]
    if len(ut_ptr) >= 20 and len(imp_ptr) >= 20:
        from .pointer_gmm import PointerModel
        pm = PointerModel().fit(stats_matrix(ut_ptr), stats_matrix(imp_ptr))
        pm.save(mdir / "pointer_model.pkl")
        print("[train] pointer GMM trained")
    else:
        print(f"[train] pointer GMM skipped ({len(ut_ptr)} user / {len(imp_ptr)} imp)")

    print("[train] done; now run calibrate")


if __name__ == "__main__":
    main()
