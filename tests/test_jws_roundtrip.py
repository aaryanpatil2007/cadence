"""JWS sign -> verify; tampering and wrong-key failures."""
import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from gait.attest import jws


def _sw_pair():
    key = ec.generate_private_key(ec.SECP256R1())

    def sign_raw(data: bytes) -> bytes:
        return jws.der_to_raw(key.sign(data, ec.ECDSA(hashes.SHA256())))

    return key.public_key(), sign_raw


def test_roundtrip():
    pub, sign = _sw_pair()
    token = jws.encode({"score": 0.91, "nonce": "abc"}, sign)
    payload = jws.verify(token, pub)
    assert payload["score"] == 0.91


def test_tampered_payload_fails():
    pub, sign = _sw_pair()
    token = jws.encode({"score": 0.2}, sign)
    h, p, s = token.split(".")
    evil = jws.b64u(b'{"score":0.99}')
    with pytest.raises(Exception):
        jws.verify(f"{h}.{evil}.{s}", pub)


def test_wrong_key_fails():
    _, sign = _sw_pair()
    other_pub, _ = _sw_pair()
    token = jws.encode({"score": 0.9}, sign)
    with pytest.raises(InvalidSignature):
        jws.verify(token, other_pub)


def test_signer_backend():
    from gait.attest.signer import get_signer
    s = get_signer()
    assert s.backend in ("secure_enclave", "software")
    pub = serialization.load_pem_public_key(s.public_key_pem.encode())
    token = jws.encode({"x": 1}, s.sign_raw)
    assert jws.verify(token, pub)["x"] == 1
