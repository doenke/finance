import time
from datetime import date, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from finanzen.secrets import SecretsError, decrypt, encrypt
from finanzen.services import fints_sync

from .conftest import login

ORIGIN = {"Origin": "https://finanzen.example.org"}
KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="  # 32 bytes, test only


class TanResp:
    _needs_tan = True

    def __init__(self, result, decoupled=False, polls=0):
        self.result = result
        self.decoupled = decoupled
        self.challenge = "Bitte TAN für Umsatzabruf" if not decoupled else "Freigabe in der App"
        self.challenge_html = None
        self.challenge_matrix = ("image/png", b"\x89PNG") if not decoupled else None
        self.challenge_hhduc = None
        self.polls = polls


class FakeClient:
    instances = []

    def __init__(self, login, pin, product_id, scenario):
        self.pin = pin
        self.product_id = product_id
        self.scenario = scenario
        self.mechanism = None
        self.accounts = []
        self.init_tan_response = TanResp(None) if scenario.get("init_tan") else None
        self.sent = []
        FakeClient.instances.append(self)

    # TAN setup
    def fetch_tan_mechanisms(self):
        return None

    def get_tan_mechanisms(self):
        return {"921": SimpleNamespace(name="pushTAN 2.0"), "912": SimpleNamespace(name="chipTAN optisch")}

    def set_tan_mechanism(self, sf):
        self.mechanism = sf

    def is_tan_media_required(self):
        return False

    def __enter__(self):
        if self.pin != "1234":
            raise type("FinTSClientPINError", (Exception,), {})()
        return self

    def __exit__(self, *a):
        return False

    def send_tan(self, resp, tan):
        self.sent.append(tan)
        if resp.decoupled and resp.polls > 0:
            resp.polls -= 1
            return resp
        if not resp.decoupled and tan != "123456":
            raise RuntimeError("TAN falsch")
        return resp.result

    def get_sepa_accounts(self):
        return ["ok"]

    def get_information(self):
        return {
            "bank": {"name": "Sparkasse Test"},
            "accounts": [
                {"iban": "DE11", "account_number": "111", "subaccount_number": None, "type": 1, "product_name": "Giro", "owner_name": ["S J"], "currency": "EUR"},
                {"iban": None, "account_number": "999", "subaccount_number": None, "type": 30, "product_name": "Depot", "owner_name": ["S J"], "currency": "EUR"},
            ],
        }

    def get_balance(self, account):
        return SimpleNamespace(amount=SimpleNamespace(amount=D("1500.25"), currency="EUR"), date=date.today())

    def get_transactions(self, account, start, end):
        txs = [
            SimpleNamespace(data={"date": date.today() - timedelta(days=2), "entry_date": date.today() - timedelta(days=2), "amount": SimpleNamespace(amount=D("-42.00")), "applicant_name": "REWE", "purpose": "Einkauf", "posting_text": "Kartenzahlung"}),
            SimpleNamespace(data={"date": date.today() - timedelta(days=1), "amount": SimpleNamespace(amount=D("2.10")), "applicant_name": "Sparkasse", "purpose": "Zinsen", "posting_text": "Zinsgutschrift"}),
        ]
        if self.scenario.get("decoupled"):
            return TanResp(txs, decoupled=True, polls=1)
        if self.scenario.get("tan"):
            return TanResp(txs)
        return txs

    def get_holdings(self, account):
        return self.scenario.get(
            "holdings",
            [SimpleNamespace(ISIN="IE00B4L5Y983", name="iShares Core MSCI World", market_value=100.5, value_symbol="EUR", valuation_date=date.today(), pieces=12.0, total_value=1206.0, acquisitionprice=80.0)],
        )

    def deconstruct(self, including_private=False):
        return b"state"


@pytest.fixture
def fints_client(client, monkeypatch):
    from finanzen.config import Settings

    s = client.app.state.settings
    client.app.state.settings = Settings(**{**s.__dict__, "fints_product_id": "TESTPRODUCT", "secrets_key": KEY})
    scenario: dict = {}
    client.app.state.fints_factory = lambda login, pin, product: FakeClient(login, pin, product, scenario)
    monkeypatch.setattr(fints_sync, "DECOUPLED_POLL", 0.05)
    FakeClient.instances = []
    yield client, scenario
    fints_sync.jobs.cancel_all()
    time.sleep(0.2)


def wait_for(client, job_id, statuses, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/fints/jobs/{job_id}").json()
        if job["status"] in statuses:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job stuck: {job}")


def test_secrets_roundtrip():
    token = encrypt(KEY, "12345", "bank_login:1")
    assert token.startswith("v1:") and "12345" not in token
    assert decrypt(KEY, token, "bank_login:1") == "12345"
    with pytest.raises(SecretsError):
        decrypt(KEY, token, "bank_login:2")  # bound to the login
    with pytest.raises(SecretsError):
        encrypt("", "x", "c")


def test_full_flow_with_tan_choice_init_tan_and_holdings(fints_client):
    client, scenario = fints_client
    login(client)
    bank = client.post("/api/banks", json={"name": "Sparkasse", "blz": "12345678", "server_url": "https://fints.example.org/fints", "username": "max"}, headers=ORIGIN).json()
    assert bank["has_pin"] is False

    scenario["init_tan"] = True
    job = client.post(f"/api/banks/{bank['id']}/discover", json={"pin": "1234"}, headers=ORIGIN).json()
    job = wait_for(client, job["id"], {"need_choice"})
    assert {c["label"] for c in job["choices"]} == {"pushTAN 2.0", "chipTAN optisch"}
    client.post(f"/api/fints/jobs/{job['id']}/answer", json={"value": "912"}, headers=ORIGIN)
    job = wait_for(client, job["id"], {"need_tan"})
    assert job["challenge"]["image"].startswith("data:image/png;base64,")
    client.post(f"/api/fints/jobs/{job['id']}/answer", json={"value": "123456"}, headers=ORIGIN)
    job = wait_for(client, job["id"], {"done", "error"})
    assert job["status"] == "done", job
    accounts = job["result"]["accounts"]
    assert [a["suggested_kind"] for a in accounts] == ["giro", "depot"]
    assert FakeClient.instances[-1].product_id == "TESTPRODUCT"

    banks = client.get("/api/banks").json()
    assert banks[0]["tan_mechanism_name"] == "chipTAN optisch"

    linked = client.post(
        f"/api/banks/{bank['id']}/link",
        json={"items": [
            {"iban": "DE11", "accountnumber": "111", "create_kind": "giro", "create_name": "Giro Sparkasse"},
            {"accountnumber": "999", "create_kind": "depot", "create_name": "Depot Sparkasse"},
        ]},
        headers=ORIGIN,
    ).json()["linked"]
    giro_id, depot_id = linked

    scenario["init_tan"] = False
    scenario["tan"] = True
    job = client.post(f"/api/banks/{bank['id']}/sync", json={"pin": "1234"}, headers=ORIGIN).json()
    job = wait_for(client, job["id"], {"need_tan"})
    client.post(f"/api/fints/jobs/{job['id']}/answer", json={"value": "123456"}, headers=ORIGIN)
    job = wait_for(client, job["id"], {"done", "error"})
    assert job["status"] == "done", job

    giro = client.get(f"/api/accounts/{giro_id}").json()
    assert D(giro["value"]) == D("1500.25")
    txs = client.get(f"/api/accounts/{giro_id}/transactions").json()
    assert {t["counterparty"] for t in txs} == {"REWE", "Sparkasse"}
    assert next(t for t in txs if t["counterparty"] == "Sparkasse")["kind"] == "interest"

    depot = client.get(f"/api/accounts/{depot_id}/positions").json()
    assert D(depot[0]["quantity"]) == 12
    assert D(depot[0]["cost"]) == D("960.00")
    assert D(depot[0]["price"]) == D("100.5")

    # Second sync: no duplicates, bank now has 15 pieces -> difference, then reconcile
    scenario["tan"] = False
    scenario["holdings"] = [SimpleNamespace(ISIN="IE00B4L5Y983", name="iShares", market_value=101, value_symbol="EUR", valuation_date=date.today(), pieces=15.0, total_value=0, acquisitionprice=80)]
    job = client.post(f"/api/banks/{bank['id']}/sync", json={"pin": "1234"}, headers=ORIGIN).json()
    job = wait_for(client, job["id"], {"done", "error"})
    assert job["status"] == "done", job
    assert len(client.get(f"/api/accounts/{giro_id}/transactions").json()) == 2
    acc = client.get(f"/api/accounts/{depot_id}").json()
    assert acc["details"]["fints_differences"][0]["bank"] == "15.0" or D(acc["details"]["fints_differences"][0]["bank"]) == 15
    assert client.post(f"/api/accounts/{depot_id}/reconcile", headers=ORIGIN).json()["created"] == 1
    assert D(client.get(f"/api/accounts/{depot_id}/positions").json()[0]["quantity"]) == 15


def test_decoupled_wrong_pin_and_stored_pin(fints_client):
    client, scenario = fints_client
    login(client)
    bank = client.post(
        "/api/banks",
        json={"name": "DKB", "blz": "12030000", "server_url": "https://fints.example.org/", "username": "max", "store_pin": True, "pin": "1234", "auto_sync": True},
        headers=ORIGIN,
    ).json()
    assert bank["has_pin"] and bank["auto_sync"]
    assert "1234" not in str(client.get("/api/banks").json())
    client.post(f"/api/banks/{bank['id']}/link", json={"items": [{"iban": "DE11", "accountnumber": "111", "create_kind": "giro"}]}, headers=ORIGIN)

    # decoupled: the job polls until the app approval arrives, no TAN input needed
    scenario["decoupled"] = True
    job = client.post(f"/api/banks/{bank['id']}/sync", json={}, headers=ORIGIN).json()
    job = wait_for(client, job["id"], {"need_choice"})
    client.post(f"/api/fints/jobs/{job['id']}/answer", json={"value": "921"}, headers=ORIGIN)
    job = wait_for(client, job["id"], {"need_tan"})
    assert job["challenge"]["decoupled"] is True
    job = wait_for(client, job["id"], {"done", "error"})
    assert job["status"] == "done", job

    # automatic (non-interactive) run stops when a TAN is needed and flags the login
    from finanzen.services.fints_sync import jobs

    settings = client.app.state.settings
    j = jobs.start("sync", bank["id"], None, settings, client.app.state.sessionmaker, interactive=False, background=False, factory=client.app.state.fints_factory)
    assert j.status == "error" and "TAN" in j.error
    assert client.get("/api/banks").json()[0]["needs_tan"] is True

    # wrong PIN
    scenario["decoupled"] = False
    job = client.post(f"/api/banks/{bank['id']}/sync", json={"pin": "0000"}, headers=ORIGIN).json()
    job = wait_for(client, job["id"], {"done", "error"})
    assert job["status"] == "error" and "PIN" in job["error"]


def test_validation(fints_client):
    client, _ = fints_client
    login(client)
    bad = client.post("/api/banks", json={"name": "X", "blz": "123", "server_url": "http://x", "username": "a"}, headers=ORIGIN)
    assert bad.status_code == 422
    bank = client.post("/api/banks", json={"name": "X", "blz": "12345678", "server_url": "https://x.example.org", "username": "a"}, headers=ORIGIN).json()
    assert client.post(f"/api/banks/{bank['id']}/sync", json={}, headers=ORIGIN).status_code == 422  # no PIN


def test_friendly_errors_use_bank_codes():
    from finanzen.services.fints_sync import BankRejected, _friendly_error, bank_messages

    exc = type("FinTSConnectionError", (Exception,), {})("Bad status code 400")
    msgs = [("9800", "Dialog abgebrochen."), ("9078", "FinTS-Produkt ist nicht registriert.")]
    assert "Produkt-ID" in _friendly_error(exc, msgs)
    assert "PIN" in _friendly_error(exc, [("9931", "PIN gesperrt")])
    assert _friendly_error(exc, [("9999", "Irgendwas")]) == "Die Bank meldet: 9999 Irgendwas"
    assert "ohne Begründung" in _friendly_error(BankRejected(400, []))
    unreachable = type("FinTSConnectionError", (Exception,), {})("Could not connect to FinTS endpoint: timeout")
    assert "nicht erreichbar" in _friendly_error(unreachable, [])
    assert bank_messages(b"not base64 fints") == []


def test_job_shows_bank_reason(fints_client):
    client, scenario = fints_client

    class Rejecting(FakeClient):
        def __init__(self, *a):
            super().__init__(*a)
            self.callbacks = []

        def add_response_callback(self, cb):
            self.callbacks.append(cb)

        def __enter__(self):
            for cb in self.callbacks:
                cb(None, SimpleNamespace(code="9078", text="FinTS-Produkt ist nicht registriert."))
            raise type("FinTSConnectionError", (Exception,), {})("Bad status code 400")

    client.app.state.fints_factory = lambda login, pin, product: Rejecting(login, pin, product, scenario)
    login(client)
    bank = client.post("/api/banks", json={"name": "DKB", "blz": "12030000", "server_url": "https://fints.example.org", "username": "x"}, headers=ORIGIN).json()
    job = client.post(f"/api/banks/{bank['id']}/discover", json={"pin": "1234"}, headers=ORIGIN).json()
    job = wait_for(client, job["id"], {"need_choice", "error"})
    if job["status"] == "need_choice":
        client.post(f"/api/fints/jobs/{job['id']}/answer", json={"value": "921"}, headers=ORIGIN)
        job = wait_for(client, job["id"], {"error", "done"})
    assert job["status"] == "error"
    assert "Produkt-ID" in job["error"]
    assert "Produkt-ID" in client.get("/api/banks").json()[0]["last_error"]
