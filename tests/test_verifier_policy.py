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


def test_high_value_requires_kyc(tmp_data_dir, tmp_path):
    client, sign, _ = make_env(tmp_path)
    token = attestation(sign, _nonce(client), 0.95)
    r = client.post("/verify", json={"jws": token,
                                     "action": "transfer:6000.00"}).json()
    assert r["decision"] == "stepup" and "identity verification" in r["reason"]
    assert r["kyc_required"] is True


def test_kyc_grants_one_time_exception(tmp_data_dir, tmp_path):
    client, sign, _ = make_env(tmp_path)
    # correct CRS test identity (mock mode) -> exception granted
    k = client.post("/kyc", json={"device_id": "dev1", "firstName": "MARGARET",
                                  "lastName": "OKAFOR", "ssn": "666701001",
                                  "dob": "1984-03-14",
                                  "street1": "1420 WILLOW CREEK DR",
                                  "city": "SAN JOSE", "state": "CA",
                                  "zip": "95125"}).json()
    assert k["verified"] is True
    token = attestation(sign, _nonce(client), 0.95)
    r = client.post("/verify", json={"jws": token,
                                     "action": "transfer:6000.00"}).json()
    assert r["decision"] == "allow" and "CRS" in r["reason"]
    # exception is one-time: the next high-value transfer demands KYC again
    token = attestation(sign, _nonce(client), 0.95)
    r = client.post("/verify", json={"jws": token,
                                     "action": "transfer:6000.00"}).json()
    assert r["decision"] == "stepup"


def test_kyc_rejects_wrong_identity(tmp_data_dir, tmp_path):
    client, _, _ = make_env(tmp_path)
    k = client.post("/kyc", json={"device_id": "dev1", "firstName": "KAYLA",
                                  "lastName": "BRENNAN",
                                  "ssn": "666701013"}).json()
    assert k["verified"] is False


def test_elevated_tier_raises_bar(tmp_data_dir, tmp_path):
    client, sign, _ = make_env(tmp_path)
    # 0.72 passes the base 0.70 threshold but not the elevated 0.80 tier
    token = attestation(sign, _nonce(client), 0.72)
    r = client.post("/verify", json={"jws": token,
                                     "action": "transfer:2000.00"}).json()
    assert r["decision"] == "stepup"
    token = attestation(sign, _nonce(client), 0.72)
    r = client.post("/verify", json={"jws": token,
                                     "action": "transfer:200.00"}).json()
    assert r["decision"] == "allow"


def test_register_anchors_identity(tmp_data_dir, tmp_path):
    client, _, _ = make_env(tmp_path)
    r = client.get("/identity/dev1").json()
    assert r["identity"]["verified"] is True
    assert "Okafor" in r["identity"]["name"]


def _verify_body(sign, client, score, action, **extra):
    token = attestation(sign, _nonce(client), score)
    return {"jws": token, "action": action, **extra}


def test_datacenter_ip_forces_stepup(tmp_data_dir, tmp_path):
    client, sign, _ = make_env(tmp_path)
    r = client.post("/verify", json=_verify_body(
        sign, client, 0.95, "transfer:300.00",
        fingerprint="fp-known", client_ip="52.1.2.3")).json()
    # cloud IP = high device risk -> step-up even with great presence
    assert r["decision"] == "stepup"
    assert any(f["label"] == "Datacenter / VPN IP" for f in r["factors"])


def test_pasted_ssn_is_a_factor(tmp_data_dir, tmp_path):
    client, sign, _ = make_env(tmp_path)
    r = client.post("/verify", json=_verify_body(
        sign, client, 0.95, "transfer:300.00",
        fingerprint="fp1", client_ip="24.5.6.7", pasted_ssn=True)).json()
    assert any(f["label"] == "Pasted identity data" for f in r["factors"])


def test_transaction_anomaly_new_payee_big_amount(tmp_data_dir, tmp_path):
    client, sign, _ = make_env(tmp_path)
    history = [{"amount": 200, "to": "savings", "ts": 0},
               {"amount": 150, "to": "savings", "ts": 0}]
    r = client.post("/verify", json=_verify_body(
        sign, client, 0.95, "transfer:4000.00", payee="stranger",
        fingerprint="fp1", client_ip="24.5.6.7", history=history)).json()
    labels = [f["label"] for f in r["factors"]]
    assert "Unusual amount" in labels and "New payee" in labels


def test_clean_transfer_allows_with_factors(tmp_data_dir, tmp_path):
    client, sign, _ = make_env(tmp_path)
    history = [{"amount": 500, "to": "savings", "ts": 0}]
    r = client.post("/verify", json=_verify_body(
        sign, client, 0.95, "transfer:400.00", payee="savings",
        fingerprint="fp-home", client_ip="24.5.6.7", history=history)).json()
    assert r["decision"] == "allow"
    assert r["trust"] > 0.8
    assert any(f["dimension"] == "Presence" for f in r["factors"])


def test_credit_ceiling_from_band(tmp_data_dir, tmp_path):
    client, sign, store = make_env(tmp_path)
    # force a subprime band on the device -> low ceiling
    store.set_identity("dev1", "Test User", True, True, "mock",
                       540, "subprime", 52, "medium")
    r = client.post("/verify", json=_verify_body(
        sign, client, 0.95, "transfer:3000.00",
        fingerprint="fp1", client_ip="24.5.6.7")).json()
    assert r["decision"] == "stepup"
    assert any(f["label"] == "Over account limit" for f in r["factors"])
    assert r["ceiling"] == 2500
