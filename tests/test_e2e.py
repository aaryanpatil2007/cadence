"""End-to-end: daemon (fake scorer) + verifier + bank over real HTTP.

Allow at 0.9, step-up at 0.5, deny at 0.2; replay denied; no-attestation 401.
"""
import httpx
import pytest

from gait.daemon.app import create_app as daemon_app
from gait.daemon.scorer import FakeScorer
from gait.verify.app import create_app as verifier_app
from gait.verify.store import Store
from bank.app import create_app as bank_app

from conftest import ServerThread

DP, VP, BP = 17777, 17800, 17900


@pytest.fixture
def stack(tmp_data_dir, tmp_path):
    fake = FakeScorer(0.9)
    store = Store(tmp_path / "v.sqlite")
    servers = [
        ServerThread(daemon_app(fake), DP).start(),
        ServerThread(verifier_app(store), VP).start(),
        ServerThread(bank_app(db_path=tmp_path / "b.sqlite",
                              verifier_url=f"http://127.0.0.1:{VP}"), BP).start(),
    ]
    # register the real device key (signer picks SE or software automatically)
    from gait.attest.signer import get_signer
    from gait.daemon.enroll import device_id
    httpx.post(f"http://127.0.0.1:{VP}/register", json={
        "device_id": device_id(), "pubkey_pem": get_signer().public_key_pem,
        "label": "e2e"})
    yield fake
    for s in servers:
        s.stop()


def _client():
    c = httpx.Client(timeout=5)
    c.post(f"http://127.0.0.1:{BP}/login")
    return c


def _attested_transfer(c, amount=500.0):
    nonce = c.get(f"http://127.0.0.1:{VP}/nonce").json()["nonce"]
    att = c.get(f"http://127.0.0.1:{DP}/attest", params={"nonce": nonce}).json()
    r = c.post(f"http://127.0.0.1:{BP}/transfer",
               json={"to": "savings", "amount": amount, "memo": "e2e",
                     "jws": att["jws"]})
    return att, r.json()


def test_full_flow_decisions(stack):
    c = _client()
    _, r = _attested_transfer(c)
    assert r["decision"] == "allow"

    stack.set(0.5)
    _, r = _attested_transfer(c)
    assert r["decision"] == "stepup"

    stack.set(0.2)
    _, r = _attested_transfer(c)
    assert r["decision"] == "deny"


def test_replay_denied(stack):
    c = _client()
    att, r = _attested_transfer(c)
    assert r["decision"] == "allow"
    # resend the exact same JWS: nonce already consumed
    r2 = c.post(f"http://127.0.0.1:{BP}/transfer",
                json={"to": "savings", "amount": 500, "memo": "replay",
                      "jws": att["jws"]}).json()
    assert r2["decision"] == "deny" and "nonce used" in r2["reason"]


def test_cookie_alone_is_not_enough(stack):
    c = _client()
    r = c.post(f"http://127.0.0.1:{BP}/transfer",
               json={"to": "savings", "amount": 500, "memo": "hijack"})
    assert r.status_code == 401


def test_attest_refused_without_score(stack):
    stack.set(None)
    c = httpx.Client(timeout=5)
    nonce = c.get(f"http://127.0.0.1:{VP}/nonce").json()["nonce"]
    r = c.get(f"http://127.0.0.1:{DP}/attest", params={"nonce": nonce})
    assert r.status_code == 409
    stack.set(0.9)


def test_balances_update_on_allow(stack):
    c = _client()
    before = {a["name"]: a["balance"]
              for a in c.get(f"http://127.0.0.1:{BP}/accounts").json()["accounts"]}
    _attested_transfer(c, amount=100.0)
    after = {a["name"]: a["balance"]
             for a in c.get(f"http://127.0.0.1:{BP}/accounts").json()["accounts"]}
    assert after["checking"] == before["checking"] - 100.0
    assert after["savings"] == before["savings"] + 100.0
