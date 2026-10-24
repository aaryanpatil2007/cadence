"""Calibrate model scores -> probabilities, pick thresholds, write eval.md.

Run after train.py. Produces data/models/calib.json, policy.json, eval.md.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from gait.features.schema import WindowRecord
from gait.paths import models_dir
from .fusion import fit_calibration, RollingScore
from .train import load_records, split_user, _by_modality
from . import synth
from gait.features.keystroke import extract_key_windows

T_HIGH_DEFAULT = 0.70
T_LOW = 0.40
MAX_FRR = 0.05
HOP_S = 2.5


def auc(genuine: np.ndarray, impostor: np.ndarray) -> float:
    from sklearn.metrics import roc_auc_score
    y = np.concatenate([np.ones(len(genuine)), np.zeros(len(impostor))])
    s = np.concatenate([genuine, impostor])
    return float(roc_auc_score(y, s))


def simulate_takeover(bundle, first: list[WindowRecord], second: list[WindowRecord],
                      threshold: float) -> tuple[float | None, list[float]]:
    """Concatenate two window streams; return seconds after switch to cross
    below threshold, plus the full score trace."""
    rs = RollingScore()

    def p_w(rec):
        """Mirror the live scorer: sparse-key shrink; pointer sustains only."""
        if bundle.is_bot_window(rec):
            return 0.02, 1.5
        if rec.modality == "keys":
            n = len(rec.seq) if rec.seq else 16
            p = 0.5 + (bundle.p_keys(rec) - 0.5) * min(1.0, n / 20)
            return p, min(1.0, n / 16)
        if rs.S is None:
            return None, 0.0  # score initializes from typing only
        return min(bundle.p_pointer(rec), rs.S), 0.5

    trace = []
    for rec in first:
        p, w = p_w(rec)
        if p is not None:
            trace.append(rs.update(p, HOP_S, w))
    latency = None
    t = 0.0
    for rec in second:
        p, w = p_w(rec)
        t += HOP_S
        if p is None:
            continue
        s = rs.update(p, HOP_S, w)
        trace.append(s)
        if latency is None and s < threshold:
            latency = t
    return latency, trace


def main() -> None:
    profiles = load_records()
    if "user" not in profiles:
        raise SystemExit("[calibrate] no 'user' profile — enroll + train first")
    user_train, user_held = split_user(profiles["user"])
    impostors = {p: r for p, r in profiles.items() if p != "user"}
    imp_all = [r for recs in impostors.values() for r in recs]
    human_imps = {p: r for p, r in impostors.items() if not p.startswith("bot_synth")}

    # ---- raw scores per model ----
    from .runtime import ModelBundle
    bundle = ModelBundle.load()

    def raw_scores(recs, fn):
        return np.array([fn(r) for r in recs])

    gh_keys = _by_modality(user_held, "keys")
    gh_ptr = _by_modality(user_held, "pointer")
    imp_keys = _by_modality(imp_all, "keys")
    imp_ptr = _by_modality(imp_all, "pointer")

    calibrations = {}
    aucs = {}

    g0 = raw_scores(gh_keys, bundle.keys_raw_l0)
    i0 = raw_scores(imp_keys, bundle.keys_raw_l0)
    calibrations["keys_l0"] = fit_calibration(g0, i0)
    aucs["keys_l0"] = auc(g0, i0)

    active = "l0"
    enc_path = models_dir() / "encoder.pt"
    if enc_path.exists():
        import torch
        from .encoder import KeystrokeEncoder
        bundle.encoder = KeystrokeEncoder()
        bundle.encoder.load_state_dict(torch.load(enc_path, map_location="cpu"))
        bundle.encoder.eval()
        bundle.prototype = np.load(models_dir() / "prototype.npy")
        g1 = raw_scores([r for r in gh_keys if r.seq], bundle.keys_raw_l1)
        i1 = raw_scores([r for r in imp_keys if r.seq], bundle.keys_raw_l1)
        if len(g1) and len(i1):
            calibrations["keys_l1"] = fit_calibration(g1, i1)
            aucs["keys_l1"] = auc(g1, i1)
            # prefer L1 unless it is clearly worse than L0 on held-out
            if aucs["keys_l1"] >= aucs["keys_l0"] - 0.02:
                active = "l1"

    gp = raw_scores(gh_ptr, bundle.pointer_raw)
    ip = raw_scores(imp_ptr, bundle.pointer_raw)
    if len(gp) and len(ip):
        calibrations["pointer"] = fit_calibration(gp, ip)
        aucs["pointer"] = auc(gp, ip)
    else:
        calibrations["pointer"] = fit_calibration(np.array([1.0]), np.array([-1.0]))

    (models_dir() / "calib.json").write_text(json.dumps({
        "active_keys_model": active,
        "calibrations": {k: {"a": c.a, "b": c.b} for k, c in calibrations.items()},
        "auc": {k: round(v, 4) for k, v in aucs.items()},
    }, indent=2))

    # ---- thresholds ----
    bundle = ModelBundle.load()  # reload with calibrations + active model
    gen_p = np.array([bundle.p_keys(r) for r in gh_keys]
                     + [bundle.p_pointer(r) for r in gh_ptr])
    t_high = T_HIGH_DEFAULT
    if len(gen_p):
        frr = float(np.mean(gen_p < t_high))
        if frr > MAX_FRR:
            # relax toward the genuine 5th percentile, but never below 0.60
            t_high = max(float(np.quantile(gen_p, MAX_FRR)), 0.60)
    policy = {"t_high": round(t_high, 3), "t_low": T_LOW}
    (models_dir() / "policy.json").write_text(json.dumps(policy, indent=2))

    # ---- acceptance eval ----
    lines = ["# Gait model evaluation", ""]
    lines.append(f"- active keys model: **{active}**")
    for k, v in aucs.items():
        lines.append(f"- AUC {k}: **{v:.3f}**")
    enc_meta = models_dir() / "encoder_meta.json"
    if enc_meta.exists():
        m = json.loads(enc_meta.read_text())
        lines.append(f"- encoder: {m['params']:,} params, trained in "
                     f"{m['train_seconds']}s on {m['sequences']} sequences / "
                     f"{m['identities']} identities")
    lines.append(f"- thresholds: T_HIGH={policy['t_high']}, T_LOW={policy['t_low']}")

    # user held-out mean rolling score
    _, trace = simulate_takeover(bundle, user_held, [], T_LOW)
    mean_S = float(np.mean(trace)) if trace else float("nan")
    lines.append(f"- user held-out mean rolling score: **{mean_S:.3f}** (target >= 0.75)")
    frr_final = float(np.mean(gen_p < policy['t_high'])) if len(gen_p) else float("nan")
    lines.append(f"- user held-out false-reject rate at T_HIGH: **{frr_final:.3f}** (target <= 0.05)")

    # takeover latency: user -> each human impostor
    for pid, recs in human_imps.items():
        lat, _ = simulate_takeover(bundle, user_held, recs, T_LOW)
        lines.append(f"- takeover latency user->{pid}: "
                     f"**{lat if lat is not None else '>'+str(len(recs)*HOP_S)} s** (target <= 10)")

    # bot: fresh synthetic sessions through the full pipeline
    for kind in ("uniform", "jitter"):
        keys, ptr = synth.generate_bot_session(kind, seed=4242)
        from gait.features.pointer import extract_pointer_windows
        bot_recs = (extract_key_windows(keys, "eval_bot", "s")
                    + extract_pointer_windows(ptr, "eval_bot", "s"))
        bot_recs.sort(key=lambda r: r.t_start)
        lat, btrace = simulate_takeover(bundle, user_held, bot_recs, 0.20)
        final = btrace[-1] if btrace else float("nan")
        lines.append(f"- bot({kind}) latency to S<0.20: **{lat} s**, final S={final:.3f}")

    (models_dir() / "eval.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
