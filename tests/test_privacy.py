"""Privacy invariants: no key identity on disk, bounded raw buffer."""
import json
from pathlib import Path

from gait.capture.buffer import RingBuffer

ENROLL_DIR = Path(__file__).resolve().parent.parent / "data" / "enroll"
FORBIDDEN = ("keycode", "char", "text", "key_name", "string")


def test_enroll_dir_has_no_key_identity():
    if not ENROLL_DIR.exists():
        return
    for path in ENROLL_DIR.rglob("*.jsonl"):
        with open(path) as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                for field in FORBIDDEN:
                    assert field not in json.dumps(rec).lower().replace(" ", ""), \
                        f"{path} leaks '{field}'"
                assert set(rec.keys()) <= {
                    "profile_id", "session_id", "t_start", "t_end",
                    "modality", "feats", "seq"}


def test_ring_buffer_bounded_to_12s():
    buf = RingBuffer()
    for i in range(10000):
        buf.push_key({"t": i * 0.01, "type": "down", "keycode": 0})
    assert buf.span_s() <= 12.0 + 1e-6


def test_capture_package_opens_no_files():
    """No file handles in gait.capture: source must not call open()/Path.write*."""
    cap_dir = Path(__file__).resolve().parent.parent / "gait" / "capture"
    for p in cap_dir.glob("*.py"):
        src = p.read_text()
        assert "open(" not in src.replace("CFRunLoop", ""), f"{p} opens files"
        assert ".write_text" not in src and ".write_bytes" not in src
