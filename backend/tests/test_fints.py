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


BANK_FIELDS = ("name", "blz", "server_url")


def new_login(client, fields: dict):
    """Creates a shared bank and the current user's login there (the old one-step form)."""
    bank = client.post("/api/banks", json={k: fields[k] for k in BANK_FIELDS}, headers=ORIGIN)
    if bank.status_code != 201:
        return bank
    return client.post(f"/api/banks/{bank.json()['id']}/logins", json={k: v for k, v in fields.items() if k not in BANK_FIELDS}, headers=ORIGIN)


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
    bank = new_login(client, {"name": "Sparkasse", "blz": "12345678", "server_url": "https://fints.example.org/fints", "username": "max"}).json()
    assert bank["has_pin"] is False

    scenario["init_tan"] = True
    job = client.post(f"/api/bank-logins/{bank['id']}/discover", json={"pin": "1234"}, headers=ORIGIN).json()
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

    banks = client.get("/api/bank-logins").json()
    assert banks[0]["tan_mechanism_name"] == "chipTAN optisch"

    linked = client.post(
        f"/api/bank-logins/{bank['id']}/link",
        json={"items": [
            {"iban": "DE11", "accountnumber": "111", "create_kind": "giro", "create_name": "Giro Sparkasse"},
            {"accountnumber": "999", "create_kind": "depot", "create_name": "Depot Sparkasse"},
        ]},
        headers=ORIGIN,
    ).json()["linked"]
    giro_id, depot_id = linked

    scenario["init_tan"] = False
    scenario["tan"] = True
    job = client.post(f"/api/bank-logins/{bank['id']}/sync", json={"pin": "1234"}, headers=ORIGIN).json()
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
    job = client.post(f"/api/bank-logins/{bank['id']}/sync", json={"pin": "1234"}, headers=ORIGIN).json()
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
    bank = new_login(client, {"name": "DKB", "blz": "12030000", "server_url": "https://fints.example.org/", "username": "max", "store_pin": True, "pin": "1234", "auto_sync": True}).json()
    assert bank["has_pin"] and bank["auto_sync"]
    assert "1234" not in str(client.get("/api/bank-logins").json())
    client.post(f"/api/bank-logins/{bank['id']}/link", json={"items": [{"iban": "DE11", "accountnumber": "111", "create_kind": "giro"}]}, headers=ORIGIN)

    # decoupled: the job polls until the app approval arrives, no TAN input needed
    scenario["decoupled"] = True
    job = client.post(f"/api/bank-logins/{bank['id']}/sync", json={}, headers=ORIGIN).json()
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
    assert client.get("/api/bank-logins").json()[0]["needs_tan"] is True

    # wrong PIN
    scenario["decoupled"] = False
    job = client.post(f"/api/bank-logins/{bank['id']}/sync", json={"pin": "0000"}, headers=ORIGIN).json()
    job = wait_for(client, job["id"], {"done", "error"})
    assert job["status"] == "error" and "PIN" in job["error"]


def test_validation(fints_client):
    client, _ = fints_client
    login(client)
    bad = new_login(client, {"name": "X", "blz": "123", "server_url": "http://x", "username": "a"})
    assert bad.status_code == 422
    bank = new_login(client, {"name": "X", "blz": "12345678", "server_url": "https://x.example.org", "username": "a"}).json()
    assert client.post(f"/api/bank-logins/{bank['id']}/sync", json={}, headers=ORIGIN).status_code == 422  # no PIN


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
    bank = new_login(client, {"name": "DKB", "blz": "12030000", "server_url": "https://fints.example.org", "username": "x"}).json()
    job = client.post(f"/api/bank-logins/{bank['id']}/discover", json={"pin": "1234"}, headers=ORIGIN).json()
    job = wait_for(client, job["id"], {"need_choice", "error"})
    if job["status"] == "need_choice":
        client.post(f"/api/fints/jobs/{job['id']}/answer", json={"value": "921"}, headers=ORIGIN)
        job = wait_for(client, job["id"], {"error", "done"})
    assert job["status"] == "error"
    assert "Produkt-ID" in job["error"]
    assert "Produkt-ID" in client.get("/api/bank-logins").json()[0]["last_error"]


def test_banks_are_shared_logins_are_personal(fints_client):
    client, _ = fints_client
    login(client, "Anna Muster")
    mine = new_login(client, {"name": "DKB", "blz": "12030000", "server_url": "https://fints.example.org", "username": "anna", "store_pin": True, "pin": "1234"}).json()
    assert mine["mine"] and mine["owner"] == "Anna Muster"
    client.post(f"/api/bank-logins/{mine['id']}/link", json={"items": [{"iban": "DE11", "accountnumber": "111", "create_kind": "giro"}]}, headers=ORIGIN)

    # Ben sees the bank and Anna's login, but not her access data, and cannot use it.
    client.cookies.clear()
    login(client, "Ben Muster", admin=False)
    banks = client.get("/api/banks").json()
    assert len(banks) == 1 and banks[0]["blz"] == "12030000"
    other = banks[0]["logins"][0]
    assert other["owner"] == "Anna Muster" and not other["mine"] and other["username"] == "" and other["account_ids"]
    assert "anna" not in str(banks).replace("Anna", "")
    for path in ("sync", "discover"):
        assert client.post(f"/api/bank-logins/{other['id']}/{path}", json={"pin": "1"}, headers=ORIGIN).status_code == 403
    assert client.put(f"/api/bank-logins/{other['id']}", json={"username": "ben"}, headers=ORIGIN).status_code == 403
    assert client.delete(f"/api/bank-logins/{other['id']}", headers=ORIGIN).status_code == 403

    # Ben adds his own login at the same bank
    own = client.post(f"/api/banks/{banks[0]['id']}/logins", json={"username": "ben"}, headers=ORIGIN).json()
    assert own["mine"] and own["blz"] == "12030000"
    banks = client.get("/api/banks").json()
    assert [lg["mine"] for lg in banks[0]["logins"]] == [True, False]
    # Changing the shared address resets the TAN setup of every login
    assert client.put(f"/api/banks/{banks[0]['id']}", json={"name": "DKB AG", "blz": "12030000", "server_url": "https://fints2.example.org"}, headers=ORIGIN).status_code == 200
    assert client.get("/api/bank-logins").json()[0]["name"] == "DKB AG"
    assert client.delete(f"/api/banks/{banks[0]['id']}", headers=ORIGIN).status_code == 409
    assert client.delete(f"/api/bank-logins/{own['id']}", headers=ORIGIN).status_code == 204


# Real answer of a bank (DKB) to a dialog with an unregistered product ID (made-up user): the codes are in a
# normal HTTP 200 answer; the following dialog end is answered with an empty HTTP 400.
DKB_9078 = (
    "SE5IQks6MTozKzAwMDAwMDAwMDIzNiszMDArdW5iZWthbm50KzErdW5iZWthbm50OjEnSElSTUc6MjoyKzk4MDA6OkRpYWxvZyBhYmdlYnJvY2hlbi4r"
    "OTA3ODo6RGlhbG9nIGFiZ2Vicm9jaGVuIBMgRmluVFMtUHJvZHVrdCBpc3QgbmljaHQgcmVnaXN0cmllcnQuKzMwNzk6OkJpdHRlIHdlbmRlbiBTaWUg"
    "c2ljaCBhbiBkZW4gSGVyc3RlbGxlciBJaHJlcyBCYW5raW5nIC0gUHJvZ3JhbW1zLidITkhCUzozOjErMSc="
)


def test_connection_keeps_codes_before_empty_http_400():
    from finanzen.services.fints_sync import BankRejected, _connection, _friendly_error

    class Res:
        def __init__(self, status, content):
            self.status_code, self.content = status, content

    answers = [Res(200, DKB_9078.encode()), Res(400, b"")]
    conn = _connection("https://fints.example.org")
    conn.session.post = lambda *a, **k: answers.pop(0)
    sent = type("Msg", (), {"render_bytes": lambda self: b"x", "print_nested": lambda self, **k: None})()
    import fints.connection as fc

    original = fc.reduce_message_for_log
    fc.reduce_message_for_log = lambda m: m
    try:
        conn.send(sent)  # first answer is parsed normally
        with pytest.raises(BankRejected) as info:
            conn.send(sent)
    finally:
        fc.reduce_message_for_log = original
    assert ("9078", "Dialog abgebrochen \x13 FinTS-Produkt ist nicht registriert.") in conn.codes
    assert "Produkt-ID" in _friendly_error(info.value, conn.codes)


def test_generic_client_error_shows_pin_hint():
    from finanzen.services.fints_sync import _friendly_error

    exc = type("FinTSClientError", (Exception,), {})("Error during dialog initialization, could not fetch BPD.")
    text = _friendly_error(exc, [("9050", "Die Nachricht enthält Fehler."), ("9010", "PIN/TAN Prüfung fehlgeschlagen"), ("9931", "Anmeldename oder PIN ist falsch.")])
    assert "Anmeldename oder PIN ist falsch" in text and "drei falschen" in text


def test_username_is_stored_composed(fints_client):
    client, _ = fints_client
    login(client)
    decomposed = "Sönke Jacobs"
    res = new_login(client, {"name": "Sparkasse", "blz": "39050000", "server_url": "https://fints.example.org", "username": f" {decomposed} "})
    assert res.status_code == 201
    assert res.json()["username"] == "Sönke Jacobs"
    assert res.json()["username"].encode("iso-8859-1") == b"S\xf6nke Jacobs"


def test_unencodable_username_is_explained():
    from finanzen.services.fints_sync import _friendly_error

    exc = UnicodeEncodeError("iso-8859-1", "x€", 1, 2, "ordinal not in range")
    assert "Legitimations-ID" in _friendly_error(exc, [])


CAMT = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.052.001.08"><BkToCstmrAcctRpt><Rpt><Acct><Ccy>EUR</Ccy></Acct>
<Ntry><Amt Ccy="EUR">42.50</Amt><CdtDbtInd>DBIT</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>2026-11-20</Dt></BookgDt><ValDt><Dt>2026-11-21</Dt></ValDt>
<AddtlNtryInf>Kartenzahlung</AddtlNtryInf><NtryDtls><TxDtls><Refs><EndToEndId>NOTPROVIDED</EndToEndId></Refs>
<RltdPties><Cdtr><Pty><Nm>REWE Markt</Nm></Pty></Cdtr><CdtrAcct><Id><IBAN>DE11500105170000000001</IBAN></Id></CdtrAcct></RltdPties>
<RmtInf><Ustrd>Einkauf 20.11.</Ustrd><Ustrd/><Ustrd>Filiale 4711</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
<Ntry><Amt Ccy="EUR">2500.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>2026-11-25</Dt></BookgDt><ValDt><Dt>2026-11-25</Dt></ValDt>
<NtryDtls><TxDtls><RltdPties><Dbtr><Nm>Arbeitgeber GmbH</Nm></Dbtr></RltdPties><RmtInf><Ustrd>Gehalt 11/2026</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
<Ntry><Amt Ccy="EUR">10.00</Amt><CdtDbtInd>DBIT</CdtDbtInd><Sts><Cd>PDNG</Cd></Sts><BookgDt><Dt>2026-11-26</Dt></BookgDt></Ntry>
</Rpt></BkToCstmrAcctRpt></Document>"""


def test_camt_parser_tolerates_empty_repeated_elements():
    from finanzen.services.camt import parse_camt

    rows = parse_camt(CAMT)
    assert len(rows) == 2  # pending entry skipped
    rewe, salary = rows
    assert rewe["amount"] == D("-42.50") and rewe["date"] == date(2026, 11, 20) and rewe["entry_date"] == date(2026, 11, 21)
    assert rewe["applicant_name"] == "REWE Markt" and rewe["applicant_iban"] == "DE11500105170000000001"
    assert rewe["purpose"] == "Einkauf 20.11. Filiale 4711" and rewe["end_to_end_reference"] == ""
    assert salary["amount"] == D("2500.00") and salary["applicant_name"] == "Arbeitgeber GmbH"
    fields = fints_sync._tx_fields(rewe)
    assert fields["booking_date"] == date(2026, 11, 20) and fields["posting_text"] == "Kartenzahlung"


def test_fetch_falls_back_to_raw_camt():
    class Broken:
        def get_transactions(self, *a):
            raise TypeError("unsupported operand type(s) for +=: 'NoneType' and 'str'")

        def get_transactions_xml(self, *a):
            return ([CAMT], [])

    job = SimpleNamespace(interactive=False)
    rows = fints_sync._fetch_transactions(job, Broken(), None, date(2026, 11, 1), None)
    assert [r["applicant_name"] for r in rows] == ["REWE Markt", "Arbeitgeber GmbH"]


def test_sepa_account_gets_bic_from_bank_or_iban():
    from fints.models import SEPAAccount

    account = SimpleNamespace(details={"fints": {"iban": "DE11390500000000000001", "bic": None, "accountnumber": "1", "subaccount": None, "blz": "39050000"}})
    bank = SEPAAccount(iban="DE11 3905 0000 0000 0000 01", bic="AACSDE33XXX", accountnumber="1", subaccount=None, blz="39050000")
    sepa = fints_sync._sepa(account, [bank])
    assert sepa.bic == "AACSDE33XXX" and account.details["fints"]["bic"] == "AACSDE33XXX"  # remembered
    # without the bank's list the country for python-fints comes from the IBAN
    bare = SimpleNamespace(details={"fints": {"iban": "DE11390500000000000001", "bic": None, "accountnumber": "1", "blz": "39050000"}})
    assert fints_sync._sepa(bare, []).bic[4:6] == "DE"


def test_bic_is_master_data(client):
    login(client)
    acc = client.post("/api/accounts", json={"name": "Giro", "kind": "giro", "iban": "DE11 3905 0000 0000 0000 01", "bic": "aacs de33xxx"}, headers=ORIGIN).json()
    assert acc["bic"] == "AACSDE33XXX"
    with client.app.state.sessionmaker() as db:
        from finanzen.models import Account

        a = db.get(Account, acc["id"])
        a.details = {"fints": {"iban": "DE11390500000000000001", "accountnumber": "1"}}
        assert fints_sync._sepa(a, []).bic == "AACSDE33XXX"  # the account's BIC is used


def test_no_duplicates_with_csv_import(client):
    """Bookings that came via CSV are not added again by FinTS, and old FinTS doubles are removed."""
    login(client)
    from finanzen.models import Account, Transaction
    from finanzen.services.dedupe import remove_fints_duplicates

    with client.app.state.sessionmaker() as db:
        acc = Account(name="Giro", kind="giro", asset_class="cash", details={})
        db.add(acc)
        db.flush()
        d = date(2026, 11, 20)
        db.add(Transaction(account_id=acc.id, booking_date=d, amount=D("-42.50"), counterparty="REWE Markt GmbH", purpose="Kartenzahlung", external_id="csv:1"))
        db.add(Transaction(account_id=acc.id, booking_date=d, amount=D("-42.50"), counterparty="Aldi Süd", purpose="Kartenzahlung", external_id="csv:2"))
        # an older FinTS double of the REWE booking (value date one day later)
        db.add(Transaction(account_id=acc.id, booking_date=d + timedelta(days=1), amount=D("-42.50"), counterparty="REWE MARKT", purpose="Einkauf", external_id="fints:old"))
        db.commit()
        assert remove_fints_duplicates(db, acc.id) == 1
        db.commit()
        new = [
            {"date": d, "entry_date": d, "amount": D("-42.50"), "applicant_name": "ALDI SUED", "purpose": "Filiale 12"},  # twin of the Aldi CSV row
            {"date": d, "entry_date": d, "amount": D("-42.50"), "applicant_name": "Lidl", "purpose": "Einkauf"},  # same amount, other shop: new
        ]
        assert fints_sync.apply_transactions(db, acc, new) == 1
        db.commit()
        names = sorted(t.counterparty for t in db.query(Transaction).filter(Transaction.account_id == acc.id))
    assert names == ["Aldi Süd", "Lidl", "REWE Markt GmbH"]


def test_credit_card_without_bic_uses_bank_bic():
    from fints.models import SEPAAccount

    giro = SEPAAccount(iban="DE11390500000000000001", bic="AACSDE33XXX", accountnumber="1", subaccount=None, blz="39050000")
    card = SEPAAccount(iban=None, bic=None, accountnumber="4711", subaccount=None, blz="39050000")
    account = SimpleNamespace(bic="", details={"fints": {"iban": None, "accountnumber": "4711", "blz": "39050000"}})
    assert fints_sync._sepa(account, [giro, card]).bic == "AACSDE33XXX"
    alone = SimpleNamespace(bic="", details={"fints": {"accountnumber": "4711", "blz": "39050000"}})
    assert fints_sync._sepa(alone, []).bic[4:6] == "DE"



def test_balance_failure_still_fetches_transactions(client):
    """Credit cards: the bank refuses the balance – the transactions are tried anyway, then a clear message."""
    login(client)
    from finanzen.models import Account, Bank, BankLogin

    class Client:
        def get_sepa_accounts(self):
            return []

        def get_balance(self, sepa):
            raise RuntimeError("Error during dialog initialization, could not fetch BPD.")

        def get_transactions(self, sepa, start, end):
            if sepa.accountnumber == "4711":
                raise RuntimeError("Die Nachricht enthält Fehler.")
            return [SimpleNamespace(data={"date": date.today(), "amount": SimpleNamespace(amount=D("-9.99")), "applicant_name": "Shop", "purpose": "Kauf"})]

    with client.app.state.sessionmaker() as db:
        bank = Bank(name="Sparkasse", blz="39050000", server_url="https://banking.example.org/fints")
        db.add(bank)
        db.flush()
        bl = BankLogin(bank_id=bank.id, username="max")
        db.add(bl)
        db.flush()
        giro = Account(name="Giro", kind="giro", asset_class="cash", bank_login_id=bl.id, details={"fints": {"iban": "DE11390500000000000001", "accountnumber": "1", "blz": "39050000"}})
        card = Account(name="Karte", kind="kreditkarte", asset_class="liabilities", bank_login_id=bl.id, details={"fints": {"accountnumber": "4711", "blz": "39050000"}})
        db.add_all([giro, card])
        db.commit()
        job = SimpleNamespace(interactive=False, message="")
        res = {a["name"]: a for a in fints_sync._sync(job, Client(), db, bl, None)["accounts"]}
    assert res["Giro"]["new_transactions"] == 1 and "Saldo nicht abrufbar" in res["Giro"]["warning"]
    assert "per CSV" in res["Karte"]["error"]
