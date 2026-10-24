"""Compact JWS (ES256) encode/decode.

Signing is pluggable: the signer callback receives the raw signing input
(b"<b64 header>.<b64 payload>") and returns a 64-byte raw r||s signature.
This lets the Secure Enclave CLI and a software key share one code path.
"""
from __future__ import annotations

import base64
import json
from typing import Callable

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature, encode_dss_signature,
)
from cryptography.exceptions import InvalidSignature


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def encode(payload: dict, sign_raw: Callable[[bytes], bytes]) -> str:
    """Build a compact JWS. sign_raw returns raw r||s (64 bytes) over SHA-256."""
    header = {"alg": "ES256", "typ": "JWT"}
    signing_input = f"{b64u(json.dumps(header, separators=(',', ':')).encode())}." \
                    f"{b64u(json.dumps(payload, separators=(',', ':')).encode())}"
    sig = sign_raw(signing_input.encode())
    if len(sig) != 64:
        raise ValueError(f"expected raw r||s signature (64 bytes), got {len(sig)}")
    return f"{signing_input}.{b64u(sig)}"


def decode_unverified(jws: str) -> dict:
    parts = jws.split(".")
    if len(parts) != 3:
        raise ValueError("malformed JWS")
    return json.loads(b64u_decode(parts[1]))


def verify(jws: str, public_key: ec.EllipticCurvePublicKey) -> dict:
    """Verify signature; return payload. Raises on any failure."""
    parts = jws.split(".")
    if len(parts) != 3:
        raise ValueError("malformed JWS")
    header = json.loads(b64u_decode(parts[0]))
    if header.get("alg") != "ES256":
        raise ValueError(f"unsupported alg {header.get('alg')}")
    raw = b64u_decode(parts[2])
    if len(raw) != 64:
        raise InvalidSignature("bad signature length")
    r = int.from_bytes(raw[:32], "big")
    s = int.from_bytes(raw[32:], "big")
    der = encode_dss_signature(r, s)
    signing_input = f"{parts[0]}.{parts[1]}".encode()
    public_key.verify(der, signing_input, ec.ECDSA(hashes.SHA256()))
    return json.loads(b64u_decode(parts[1]))


def der_to_raw(der_sig: bytes) -> bytes:
    r, s = decode_dss_signature(der_sig)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")
