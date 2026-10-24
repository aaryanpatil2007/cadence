"""Device-bound signing. Prefers the Secure Enclave via swift/gait-sign;
falls back to a software P-256 key at ~/.gait/key_sw.pem (0600).

`get_signer()` returns a Signer with .sign_raw(bytes)->bytes (raw r||s over
SHA-256), .public_key_pem, and .backend ("secure_enclave" | "software").
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .jws import b64u, b64u_decode, der_to_raw

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SWIFT_BIN = REPO_ROOT / "swift" / "gait-sign" / ".build" / "release" / "gait-sign"
GAIT_DIR = Path.home() / ".gait"
SE_KEY = GAIT_DIR / "key.bin"
SW_KEY = GAIT_DIR / "key_sw.pem"


class Signer:
    def __init__(self, backend: str, public_key_pem: str, sign_raw):
        self.backend = backend
        self.public_key_pem = public_key_pem
        self.sign_raw = sign_raw  # (data: bytes) -> raw r||s bytes


def _run(args: list[str], timeout: float = 10) -> str:
    out = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError(f"{args[0]} failed: {out.stderr.strip()}")
    return out.stdout.strip()


def _se_signer() -> Signer:
    if not SWIFT_BIN.exists():
        raise RuntimeError("gait-sign binary not built")
    if not SE_KEY.exists():
        pem = _run([str(SWIFT_BIN), "gen"])
    else:
        pem = _run([str(SWIFT_BIN), "pub"])

    def sign_raw(data: bytes) -> bytes:
        # SE CLI signs the given bytes (CryptoKit hashes with SHA-256 internally)
        return b64u_decode(_run([str(SWIFT_BIN), "sign", b64u(data)]))

    # smoke: sign + verify locally before trusting the path
    pub = serialization.load_pem_public_key(pem.encode())
    test = b"gait-smoke-test"
    sig = sign_raw(test)
    r = int.from_bytes(sig[:32], "big")
    s = int.from_bytes(sig[32:], "big")
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    pub.verify(encode_dss_signature(r, s), test, ec.ECDSA(hashes.SHA256()))
    return Signer("secure_enclave", pem, sign_raw)


def _sw_signer() -> Signer:
    GAIT_DIR.mkdir(mode=0o700, exist_ok=True)
    if SW_KEY.exists():
        key = serialization.load_pem_private_key(SW_KEY.read_bytes(), password=None)
    else:
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        SW_KEY.touch(mode=0o600)
        SW_KEY.write_bytes(pem)
        os.chmod(SW_KEY, 0o600)
    pub_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    def sign_raw(data: bytes) -> bytes:
        der = key.sign(data, ec.ECDSA(hashes.SHA256()))
        return der_to_raw(der)

    return Signer("software", pub_pem, sign_raw)


_cached: Signer | None = None


def get_signer() -> Signer:
    global _cached
    if _cached is not None:
        return _cached
    try:
        _cached = _se_signer()
    except Exception as e:
        print(f"[signer] secure enclave path unavailable ({e}); using software key",
              file=sys.stderr)
        _cached = _sw_signer()
    return _cached


if __name__ == "__main__":
    s = get_signer()
    sig = s.sign_raw(b"hello")
    print(f"backend={s.backend} sig_len={len(sig)}")
    print(s.public_key_pem)
