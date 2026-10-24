"""Verifier decisions: unknown device, nonce misuse, expiry, score bands."""
import time

from fastapi.testclient import TestClient

from gait.attest import jws as jws_mod
from gait.verify.app import create_app
from gait.verify.store import Store

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


def make_env(tmp_path):
    store = Store(tmp_path / "v.sqlite")
    client = TestClient(create_app(store))
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo).decode()

    def sign_raw(data: bytes) -> bytes:
        return jws_mod.der_to_raw(key.sign(data, ec.ECDSA(hashes.SHA256())))

    client.post("/register", json={"device_id": "dev1", "pubkey_pem": pem,
                                   "label": "test"})
    return client, sign_raw, store


def attestation(sign_raw, nonce, score, iat=None, exp=None, device="dev1"):
    now = int(time.time())
    return jws_mod.encode({
        "iss": "gait-daemon", "device_id": device, "nonce": nonce,
        "score": score, "window_ms": 5000, "modalities": {},
        "iat": iat if iat is not None else now,
        "exp": exp if exp is not None else now + 10,
        "key_backend": "software"}, sign_raw)


def _nonce(client):
    return client.get("/nonce").json()["nonce"]


def test_score_bands(tmp_data_dir, tmp_path):
    client, sign, _ = make_env(tmp_path)
    for score, expected in [(0.9, "allow"), (0.5, "stepup"), (0.2, "deny")]:
        token = attestation(sign, _nonce(client), score)
        r = client.post("/verify", json={"jws": token, "action": "t"}).json()
        assert r["decision"] == expected, r


def test_unknown_device(tmp_data_dir, tmp_path):
    client, sign, _ = make_env(tmp_path)
    token = attestation(sign, _nonce(client), 0.9, device="ghost")
    r = client.post("/verify", json={"jws": token}).json()
    assert r["decision"] == "deny" and "unknown device" in r["reason"]


def test_reused_nonce(tmp_data_dir, tmp_path):
    client, sign, _ = make_env(tmp_path)
    n = _nonce(client)
    token = attestation(sign, n, 0.9)
    assert client.post("/verify", json={"jws": token}).json()["decision"] == "allow"
    r = client.post("/verify", json={"jws": token}).json()
    assert r["decision"] == "deny" and "nonce used" in r["reason"]


def test_expired_nonce(tmp_data_dir, tmp_path):
    client, sign, store = make_env(tmp_path)
    n = _nonce(client)
    store.db.execute("UPDATE nonces SET issued_at=? WHERE nonce=?",
                     (time.time() - 60, n))
    store.db.commit()
    token = attestation(sign, n, 0.9)
    r = client.post("/verify", json={"jws": token}).json()
    assert r["decision"] == "deny" and "expired" in r["reason"]


def test_expired_attestation(tmp_data_dir, tmp_path):
    client, sign, _ = make_env(tmp_path)
    now = int(time.time())
    token = attestation(sign, _nonce(client), 0.9, iat=now - 30, exp=now - 20)
    r = client.post("/verify", json={"jws": token}).json()
    assert r["decision"] == "deny" and "attestation expired" in r["reason"]


def test_wrong_key_signature(tmp_data_dir, tmp_path):
    client, _, _ = make_env(tmp_path)
    other = ec.generate_private_key(ec.SECP256R1())

    def evil_sign(data):
        return jws_mod.der_to_raw(other.sign(data, ec.ECDSA(hashes.SHA256())))

    token = attestation(evil_sign, _nonce(client), 0.95)
    r = client.post("/verify", json={"jws": token}).json()
    assert r["decision"] == "deny" and "bad signature" in r["reason"]


def test_audit_log(tmp_data_dir, tmp_path):
    client, sign, _ = make_env(tmp_path)
    token = attestation(sign, _nonce(client), 0.9)
    client.post("/verify", json={"jws": token, "action": "transfer:500"})
    entries = client.get("/audit").json()["entries"]
    assert any(e["action"] == "transfer:500" and e["decision"] == "allow"
               for e in entries)
