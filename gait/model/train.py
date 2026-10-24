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
    """70/30 split per modality, interleaved in blocks (last 3 of every 10
    windows held out). Enrollment phases differ a lot (transcribe vs free-type
    vs form), so a chronological tail split evaluates the model on an activity
    it never trained on; block interleaving puts every phase on both sides.
    Adjacent windows overlap 50%, so block boundaries leak a little — accepted
    trade-off for matched distributions on 5-minute enrollments."""
    train, held = [], []
    for modality in ("keys", "pointer"):
        m = [r for r in recs if r.modality == modality]
        for i, r in enumerate(m):
            (held if i % 10 >= 7 else train).append(r)
    train.sort(key=lambda r: (r.session_id, r.t_start))
    held.sort(key=lambda r: (r.session_id, r.t_start))
    return train, held


def _by_modality(recs: list[WindowRecord], modality: str) -> list[WindowRecord]:
    return [r for r in recs if r.modality == modality]


def stats_matrix(recs: list[WindowRecord]) -> np.ndarray:
    return np.array([r.feats for r in recs]) if recs else np.zeros((0, 1))


def _seq_arrays(recs: list[WindowRecord]) -> list[np.ndarray]:
    return [np.array(r.seq, dtype=np.float32) for r in recs if len(r.seq) >= 8]


def _prototype(model, seqs: list[np.ndarray]) -> np.ndarray:
    import torch
    from .encoder import pad_batch
    rows, mask = pad_batch(seqs)
    with torch.no_grad():
        embs = model(rows, mask).numpy()
    proto = embs.mean(axis=0)
    return proto / (np.linalg.norm(proto) + 1e-9)


def _cos_scores(model, proto: np.ndarray, seqs: list[np.ndarray]) -> np.ndarray:
    import torch
    from .encoder import pad_batch
    rows, mask = pad_batch(seqs)
    with torch.no_grad():
        embs = model(rows, mask).numpy()
    return embs @ proto


def _encoder_auc(model, user_train_seqs, genuine_seqs, impostor_seqs) -> float:
    from sklearn.metrics import roc_auc_score
    proto = _prototype(model, user_train_seqs)
    g = _cos_scores(model, proto, genuine_seqs)
    i = _cos_scores(model, proto, impostor_seqs)
    y = np.concatenate([np.ones(len(g)), np.zeros(len(i))])
    return float(roc_auc_score(y, np.concatenate([g, i])))


def fit_encoder(seqs: list[np.ndarray], labels: np.ndarray,
                init_state=None, lr: float = 3e-3, epochs: int = 300):
    """SupCon training over identities; returns (model_on_cpu, seconds)."""
    import torch
    from .encoder import KeystrokeEncoder, pad_batch, supcon_loss, augment, device

    dev = device()
    model = KeystrokeEncoder().to(dev)
    if init_state is not None:
        model.load_state_dict(init_state)
    opt = torch.optim.AdamW(model.parameters(), lr=lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    rng = np.random.default_rng(0)
    batch = min(256, len(seqs))
    t0 = time.monotonic()
    losses = [0.0]
    for ep in range(epochs):
        idx = rng.permutation(len(seqs))
        losses = []
        for i in range(0, len(idx), batch):
            bidx = idx[i:i + batch]
            aug = [augment(seqs[j], rng) for j in bidx]
            rows, mask = pad_batch(aug)
            lab = torch.tensor(labels[bidx], device=dev)
            emb = model(rows.to(dev), mask.to(dev))
            loss = supcon_loss(emb, lab)
            opt.zero_grad()
            loss.backward()
            opt.step()
            losses.append(float(loss))
        sched.step()
        if time.monotonic() - t0 > ENCODER_TIME_BUDGET_S:
            print(f"[train] encoder time budget hit at epoch {ep}")
            break
    model.eval().to("cpu")
    return model, time.monotonic() - t0


def train_encoder(profiles: dict[str, list[WindowRecord]],
                  user_train_keys: list[WindowRecord],
                  user_held_keys: list[WindowRecord],
                  imp_held_keys: list[WindowRecord]) -> tuple[object, np.ndarray] | None:
    """Train candidate encoders (scratch / pretrained-frozen / fine-tuned),
    pick the best by held-out AUC, return (model, user prototype)."""
    import torch
    from .encoder import KeystrokeEncoder, count_params

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

    user_train_seqs = _seq_arrays(user_train_keys)
    gen_seqs = _seq_arrays(user_held_keys)
    imp_seqs = _seq_arrays(imp_held_keys)
    can_eval = len(gen_seqs) >= 5 and len(imp_seqs) >= 5

    candidates: dict[str, tuple[object, float]] = {}
    model, secs = fit_encoder(seqs, labels, epochs=300 if len(seqs) < 600 else 60)
    candidates["scratch"] = (model, secs)

    pre_path = models_dir() / "encoder_pretrained.pt"
    if pre_path.exists():
        state = torch.load(pre_path, map_location="cpu")
        frozen = KeystrokeEncoder()
        frozen.load_state_dict(state)
        frozen.eval()
        candidates["pretrained_frozen"] = (frozen, 0.0)
        ft, ft_secs = fit_encoder(seqs, labels, init_state=state, lr=5e-4,
                                  epochs=120)
        candidates["pretrained_finetuned"] = (ft, ft_secs)

    best_name, best_model, best_auc, best_secs = None, None, -1.0, 0.0
    for name, (m, secs) in candidates.items():
        auc = (_encoder_auc(m, user_train_seqs, gen_seqs, imp_seqs)
               if can_eval else 0.5)
        print(f"[train] encoder candidate {name}: held-out AUC {auc:.3f}")
        if auc > best_auc:
            best_name, best_model, best_auc, best_secs = name, m, auc, secs
    print(f"[train] encoder selected: {best_name} (AUC {best_auc:.3f})")

    proto = _prototype(best_model, user_train_seqs)
    meta = {"params": count_params(best_model),
            "train_seconds": round(best_secs, 1),
            "identities": len(label_map), "sequences": len(seqs),
            "variant": best_name, "selection_auc": round(best_auc, 4)}
    pre_meta = models_dir() / "encoder_pretrained_meta.json"
    if pre_meta.exists() and best_name and best_name.startswith("pretrained"):
        meta["pretraining"] = json.loads(pre_meta.read_text())
    (models_dir() / "encoder_meta.json").write_text(json.dumps(meta))
    return best_model, proto


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

    # L1 encoder (candidates evaluated on held-out genuine vs impostors)
    train_profiles = dict(profiles)
    train_profiles["user"] = user_train  # never train on held-out
    uh_keys = _by_modality(user_held, "keys")
    imp_keys = [r for pid, recs in profiles.items()
                if pid != "user" and not pid.startswith("bot_synth")
                for r in _by_modality(recs, "keys")]
    result = train_encoder(train_profiles, ut_keys, uh_keys, imp_keys)
    if result is not None:
        import torch
        model, proto = result
        torch.save(model.state_dict(), mdir / "encoder.pt")
        np.save(mdir / "prototype.npy", proto)

    # L2 pointer GMM — optionally with Balabit population negatives;
    # keep whichever separates user-held from team impostors better
    imp_ptr = [r for pid, recs in profiles.items() if pid != "user"
               for r in _by_modality(recs, "pointer")]
    if len(ut_ptr) >= 12 and len(imp_ptr) >= 20:
        from sklearn.metrics import roc_auc_score
        from .pointer_gmm import PointerModel

        uh_ptr = _by_modality(user_held, "pointer")
        imp_team_ptr = [r for pid, recs in profiles.items()
                        if pid != "user" and not pid.startswith("bot_synth")
                        for r in _by_modality(recs, "pointer")]

        def ptr_auc(pm):
            if len(uh_ptr) < 5 or len(imp_team_ptr) < 5:
                return 0.5
            g = pm.llr(stats_matrix(uh_ptr))
            i = pm.llr(stats_matrix(imp_team_ptr))
            y = np.concatenate([np.ones(len(g)), np.zeros(len(i))])
            return float(roc_auc_score(y, np.concatenate([g, i])))

        cands = {"team": PointerModel().fit(stats_matrix(ut_ptr),
                                            stats_matrix(imp_ptr))}
        balabit_root = enroll_dir().parent / "raw" / "balabit"
        if balabit_root.exists():
            from .balabit import convert
            pop = [r for recs in convert(balabit_root).values() for r in recs]
            if len(pop) >= 50:
                cands["team+balabit"] = PointerModel().fit(
                    stats_matrix(ut_ptr), stats_matrix(imp_ptr + pop))
        best = max(cands, key=lambda k: ptr_auc(cands[k]))
        cands[best].save(mdir / "pointer_model.pkl")
        print(f"[train] pointer GMM trained (negatives: {best}, "
              f"AUC {ptr_auc(cands[best]):.3f})")
    else:
        print(f"[train] pointer GMM skipped ({len(ut_ptr)} user / {len(imp_ptr)} imp)")

    print("[train] done; now run calibrate")


if __name__ == "__main__":
    main()
