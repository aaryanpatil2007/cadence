"""Runtime model bundle: load trained artifacts, score window records.

Shared by the daemon scorer and offline evaluation so stage and eval agree.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from gait.features.schema import WindowRecord, KEY_STAT_NAMES, POINTER_STAT_NAMES
from gait.paths import models_dir
from .baseline import ScaledManhattan
from .fusion import Calibration, robotic_keys, robotic_pointer

_HOLD_MEAN = KEY_STAT_NAMES.index("hold_mean")
_DD_MEAN = KEY_STAT_NAMES.index("dd_mean")
_STRAIGHT = POINTER_STAT_NAMES.index("straightness_mean")
_SUBMOVE = POINTER_STAT_NAMES.index("submovement_mean")
_NMOVE = POINTER_STAT_NAMES.index("n_movements")
_HOLD_STD = KEY_STAT_NAMES.index("hold_std")
_DD_STD = KEY_STAT_NAMES.index("dd_std")


class ModelBundle:
    def __init__(self, models_dir: Path):
        self.dir = models_dir
        self.baseline_keys: ScaledManhattan | None = None
        self.baseline_pointer: ScaledManhattan | None = None
        self.encoder = None          # torch module (lazy)
        self.prototype: np.ndarray | None = None
        self.pointer_model = None    # PointerModel
        self.calib: dict[str, Calibration] = {}
        self.active_keys_model = "l0"
        self.policy = {"t_high": 0.70, "t_low": 0.40}

    @staticmethod
    def load(mdir: Path | None = None) -> "ModelBundle":
        mdir = mdir or models_dir()
        b = ModelBundle(mdir)
        bk = mdir / "baseline_keys.json"
        if bk.exists():
            b.baseline_keys = ScaledManhattan.from_dict(json.loads(bk.read_text()))
        bp = mdir / "baseline_pointer.json"
        if bp.exists():
            b.baseline_pointer = ScaledManhattan.from_dict(json.loads(bp.read_text()))
        cal = mdir / "calib.json"
        if cal.exists():
            d = json.loads(cal.read_text())
            b.active_keys_model = d.get("active_keys_model", "l0")
            for name, ab in d.get("calibrations", {}).items():
                b.calib[name] = Calibration(a=ab["a"], b=ab["b"])
        pol = mdir / "policy.json"
        if pol.exists():
            b.policy = json.loads(pol.read_text())
        enc = mdir / "encoder.pt"
        proto = mdir / "prototype.npy"
        if enc.exists() and proto.exists() and b.active_keys_model == "l1":
            import torch
            from .encoder import KeystrokeEncoder
            b.encoder = KeystrokeEncoder()
            b.encoder.load_state_dict(torch.load(enc, map_location="cpu"))
            b.encoder.eval()
            b.prototype = np.load(proto)
        pm = mdir / "pointer_model.pkl"
        if pm.exists():
            from .pointer_gmm import PointerModel
            b.pointer_model = PointerModel.load(pm)
        return b

    # --- raw scores ---

    def keys_raw_l0(self, rec: WindowRecord) -> float:
        return float(self.baseline_keys.score(np.array(rec.feats))[0])

    def keys_raw_l1(self, rec: WindowRecord) -> float:
        import torch
        from .encoder import pad_batch
        rows, mask = pad_batch([np.array(rec.seq, dtype=np.float32)])
        with torch.no_grad():
            emb = self.encoder(rows, mask).numpy()[0]
        return float(np.dot(emb, self.prototype))

    def pointer_raw(self, rec: WindowRecord) -> float:
        x = np.array(rec.feats)
        if self.pointer_model is not None:
            return float(self.pointer_model.llr(x)[0])
        return float(self.baseline_pointer.score(x)[0])

    # --- calibrated probabilities ---

    def p_keys(self, rec: WindowRecord) -> float:
        if self.active_keys_model == "l1" and self.encoder is not None and rec.seq:
            return self.calib["keys_l1"](self.keys_raw_l1(rec))
        return self.calib["keys_l0"](self.keys_raw_l0(rec))

    def p_pointer(self, rec: WindowRecord) -> float:
        return self.calib["pointer"](self.pointer_raw(rec))

    # --- bot detection on raw window stats ---

    def is_bot_window(self, rec: WindowRecord) -> bool:
        if rec.modality == "keys":
            f = rec.feats
            hold_cov = f[_HOLD_STD] / max(f[_HOLD_MEAN], 1e-6)
            dd_cov = f[_DD_STD] / max(f[_DD_MEAN], 1e-6)
            return min(hold_cov, dd_cov) < 0.05
        f = rec.feats
        return robotic_pointer(f[_STRAIGHT], f[_SUBMOVE], f[_NMOVE])

    def ready(self) -> bool:
        return self.baseline_keys is not None and "keys_l0" in self.calib
