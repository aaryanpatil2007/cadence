"""EWMA response, idle decay, bot floor."""
import numpy as np

from gait.model.fusion import RollingScore, fuse, robotic_keys, BOT_FLOOR_P


def test_ewma_step_response_under_10s():
    rs = RollingScore()
    for _ in range(20):
        rs.update(0.9, 2.5)
    assert rs.S > 0.85
    t = 0.0
    while rs.S >= 0.4:
        rs.update(0.1, 2.5)
        t += 2.5
        assert t <= 10.0, "EWMA took too long to fall below 0.4"
    assert t <= 10.0


def test_idle_decay():
    rs = RollingScore()
    rs.update(0.9, 2.5)
    s0 = rs.S
    assert rs.apply_idle(10.0, now=100.0) == s0  # within grace
    rs.apply_idle(30.0, now=120.0)               # 15s past grace
    assert rs.S < s0 * 0.6


def test_bot_floor_on_robotic_cov():
    holds = [0.060] * 20                       # zero variance
    dds = list(np.random.default_rng(0).normal(0.09, 0.03, 20))
    assert robotic_keys(holds, dds)
    human_holds = list(np.random.default_rng(1).normal(0.09, 0.025, 20))
    assert not robotic_keys(human_holds, dds)
    assert fuse(0.95, 20, 0.95, 200, bot=True)[0] == BOT_FLOOR_P


def test_fuse_weights():
    assert fuse(None, 0, None, 0, bot=False) == (None, 0.0)
    assert fuse(0.8, 16, None, 0, bot=False)[0] == 0.8
    # 8 keys (w=0.5) at 0.8 + 100 samples (w=min(0.15, 100/600)) at 0.2:
    # pointer barely dents the keys verdict
    p, w = fuse(0.8, 8, 0.2, 100, bot=False)
    assert p > 0.63 and abs(w - (0.5 + 100 / 600)) < 1e-9
    # pointer weight is capped at 0.15 even with many samples (liveness only)
    assert fuse(None, 0, 0.9, 10000, bot=False)[1] == 0.15
