import json
import struct
from datetime import date, timedelta
from decimal import Decimal as D

import jwt
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from finanzen.config import Settings
from finanzen.models import Bank, BankLogin, NotificationLog, User
from finanzen.services import notify, webpush

from .conftest import login

ORIGIN = {"Origin": "https://finanzen.example.org"}


def _hkdf(salt, ikm, info, n):
    return HKDF(algorithm=hashes.SHA256(), length=n, salt=salt, info=info).derive(ikm)


def receiver():
    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = b"0123456789abcdef"
    return key, webpush.b64u_encode(pub), webpush.b64u_encode(auth)


def decrypt(body: bytes, key, p256dh: str, auth: str) -> bytes:
    salt, rs, idlen = body[:16], *struct.unpack("!IB", body[16:21])
    as_public = body[21 : 21 + idlen]
    assert rs == 4096 and idlen == 65
    sender = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public)
    shared = key.exchange(ec.ECDH(), sender)
    ua_public = webpush.b64u_decode(p256dh)
    ikm = _hkdf(webpush.b64u_decode(auth), shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    plain = AESGCM(cek).decrypt(nonce, body[21 + idlen :], None)
    assert plain.endswith(b"\x02")
    return plain[:-1]


def test_webpush_encryption_and_vapid():
    key, p256dh, auth = receiver()
    body = webpush.encrypt(b'{"title":"Hallo"}', p256dh, auth)
    assert decrypt(body, key, p256dh, auth) == b'{"title":"Hallo"}'
    public, private = webpush.generate_vapid_keys()
    headers = webpush.vapid_headers("https://push.example.com/send/abc", public, private, "mailto:x@example.org")
    token = headers["Authorization"].split("t=")[1].split(",")[0]
    verifier = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), webpush.b64u_decode(public))
    claims = jwt.decode(token, verifier, algorithms=["ES256"], audience="https://push.example.com")
    assert claims["sub"] == "mailto:x@example.org"
    assert headers["Authorization"].endswith(f"k={public}")


class Outbox:
    def __init__(self):
        self.push: list[dict] = []
        self.mail: list[tuple[str, str, str]] = []
        self.gone: set[str] = set()

    def send_push(self, endpoint, p256dh, auth, message, **kw):
        body = webpush.encrypt(json.dumps(message).encode(), p256dh, auth)  # exercise the real encryption
        assert body
        if endpoint in self.gone:
            return webpush.PushResult(False, True, 410)
        self.push.append({"endpoint": endpoint, **message})
        return webpush.PushResult(True, False, 201)

    def send_mail(self, settings, to, subject, text, html=None):
        self.mail.append((to, subject, text))


@pytest.fixture
def setup(client, monkeypatch):
    public, private = webpush.generate_vapid_keys()
    s = client.app.state.settings
    client.app.state.settings = Settings(**{**s.__dict__, "vapid_public_key": public, "vapid_private_key": private, "smtp_host": "mail.example.org", "smtp_from": "Finanzen <f@example.org>"})
    box = Outbox()
    monkeypatch.setattr(notify, "push_sender", box.send_push)
    monkeypatch.setattr(notify, "mail_sender", box.send_mail)
    login(client, "Anna Muster")
    with client.app.state.sessionmaker() as db:
        user = db.scalars(__import__("sqlalchemy").select(User)).first()
        user.email = "anna@example.org"
        db.commit()
    return client, box


def subscribe(client, endpoint="https://push.example.com/send/1"):
    _, p256dh, auth = receiver()
    res = client.post("/api/notifications/subscriptions", json={"endpoint": endpoint, "p256dh": p256dh, "auth": auth, "device": "Pixel"}, headers=ORIGIN)
    assert res.status_code == 201, res.text
    return res.json()


def test_settings_subscribe_and_test_message(setup):
    client, box = setup
    state = client.get("/api/notifications").json()
    assert state["push_available"] and state["email_available"] and state["vapid_public_key"]
    assert state["prefs"]["maturity"]["days"] == 30 and state["prefs"]["monthly_report"]["email"] is False and not any(p["email"] for p in state["prefs"].values())
    state = subscribe(client)
    assert state["devices"][0]["device"] == "Pixel"
    prefs = state["prefs"]
    prefs["value_change"].update({"push": True, "percent": "5,5", "period": "week"})
    prefs["monthly_report"]["push"] = True  # not a channel of this event
    prefs["maturity"]["days"] = "abc"
    state = client.put("/api/notifications/prefs", json=prefs, headers=ORIGIN).json()
    assert state["prefs"]["value_change"] == {"push": True, "email": False, "period": "week", "percent": "5.5", "amount": ""}
    assert state["prefs"]["monthly_report"]["push"] is False
    assert state["prefs"]["maturity"]["days"] == 30
    res = client.post("/api/notifications/test", headers=ORIGIN).json()
    assert res == {"push": 1, "email": True}
    assert box.push[0]["title"] == "Testnachricht" and box.mail[0][0] == "anna@example.org"
    # expired subscription is removed on the next delivery
    box.gone.add("https://push.example.com/send/1")
    client.post("/api/notifications/test", headers=ORIGIN)
    assert client.get("/api/notifications").json()["devices"] == []
    state = subscribe(client, "https://push.example.com/send/2")
    state = client.post("/api/notifications/subscriptions/remove", json={"endpoint": "https://push.example.com/send/2"}, headers=ORIGIN).json()
    assert state["devices"] == []


def test_daily_checks(setup):
    client, box = setup
    subscribe(client)
    today = date(2026, 11, 24)
    fg = client.post("/api/accounts", json={"name": "Festgeld 1 Jahr", "kind": "festgeld", "details": {"amount": "10000", "rate": "2.5", "start": "2025-12-04", "end": "2025-12-04"}}, headers=ORIGIN).json()
    client.put(f"/api/accounts/{fg['id']}", json={**fg, "details": {"amount": "10000", "rate": "2.5", "start": "2025-12-04", "end": (today + timedelta(days=10)).isoformat()}}, headers=ORIGIN)
    later = client.post("/api/accounts", json={"name": "Festgeld lang", "kind": "festgeld", "details": {"amount": "1", "rate": "1", "start": "2025-01-01", "end": "2027-12-31"}}, headers=ORIGIN).json()
    assert later["id"]
    rente = client.post("/api/accounts", json={"name": "HDI Privatrente", "kind": "altersvorsorge"}, headers=ORIGIN).json()
    client.post(f"/api/accounts/{rente['id']}/valuations", json={"date": "2025-10-01", "value": "12000"}, headers=ORIGIN)
    fresh = client.post("/api/accounts", json={"name": "Generali", "kind": "altersvorsorge"}, headers=ORIGIN).json()
    client.post(f"/api/accounts/{fresh['id']}/valuations", json={"date": "2026-05-01", "value": "25990"}, headers=ORIGIN)
    settings, make = client.app.state.settings, client.app.state.sessionmaker
    result = notify.run_daily(settings, make, today=today)
    assert result["maturity"] == 1 and result["valuation_due"] == 1
    titles = [p["title"] for p in box.push]
    assert "Festgeld „Festgeld 1 Jahr“ endet am 04.12.2026" in titles
    assert "Neuer Wert für „HDI Privatrente“?" in titles
    assert box.mail == []  # e-mail is opt-in
    # nothing twice
    assert notify.run_daily(settings, make, today=today + timedelta(days=1)) == {"maturity": 0, "valuation_due": 0, "value_change": 0}


def test_value_change_and_report(setup):
    client, box = setup
    subscribe(client)
    giro = client.post("/api/accounts", json={"name": "Giro", "kind": "giro"}, headers=ORIGIN).json()
    today = date.today()
    first_of_month = today.replace(day=1)
    client.post(f"/api/accounts/{giro['id']}/balances", json={"date": (first_of_month - timedelta(days=40)).isoformat(), "amount": "1000"}, headers=ORIGIN)
    client.post(f"/api/accounts/{giro['id']}/balances", json={"date": (first_of_month - timedelta(days=5)).isoformat(), "amount": "1500"}, headers=ORIGIN)
    client.post(f"/api/accounts/{giro['id']}/balances", json={"date": today.isoformat(), "amount": "3000"}, headers=ORIGIN)
    if (today - timedelta(days=1)).day == today.day:  # pragma: no cover
        return
    client.put("/api/notifications/prefs", json={"value_change": {"push": True, "email": False, "period": "day", "percent": "10", "amount": ""}}, headers=ORIGIN)
    settings, make = client.app.state.settings, client.app.state.sessionmaker
    res = notify.run_daily(settings, make, today=today)
    if (first_of_month - timedelta(days=5)) < today - timedelta(days=1):
        assert res["value_change"] == 1
        assert box.push[-1]["title"].startswith("Nettovermögen seit gestern +1.500,00 €")
    assert notify.run_report(settings, make, today=today) == 0  # not opted in
    client.put("/api/notifications/prefs", json={"monthly_report": {"email": True}}, headers=ORIGIN)
    sent = notify.run_report(settings, make, today=today)
    assert sent == 1
    to, subject, text = box.mail[-1]
    assert subject.startswith("Finanzen: Monatsbericht") and "Nettovermögen: 1.500,00 €" in text and "Giro: +500,00 €" in text
    assert notify.run_report(settings, make, today=today) == 0  # once per month


def test_bank_failure_goes_to_login_owner(setup):
    client, box = setup
    subscribe(client)
    settings, make = client.app.state.settings, client.app.state.sessionmaker
    with make() as db:
        user = db.scalars(__import__("sqlalchemy").select(User)).first()
        bank = Bank(name="DKB", blz="12030000", server_url="https://fints.example.org")
        lg = BankLogin(bank=bank, user_id=user.id, username="x", needs_tan=True)
        db.add(lg)
        db.commit()
        notify.bank_job_failed(db, settings, lg, "TAN nötig")
        lg.needs_tan = False
        db.commit()
        notify.bank_job_failed(db, settings, lg, "Die Bank lehnt ab: 9078")
        assert db.scalar(__import__("sqlalchemy").select(__import__("sqlalchemy").func.count()).select_from(NotificationLog)) == 2
    assert [p["title"] for p in box.push] == ["DKB: TAN-Freigabe nötig", "DKB: Abruf fehlgeschlagen"]
    assert box.mail == []  # push only unless e-mail is switched on


def test_formatting():
    assert notify.eur(D("1234567.891")) == "1.234.567,89 €"
    assert notify.eur(D("-5"), signed=True) == "−5,00 €"
    assert notify.pct(D("0.0123")) == "+1,2 %"
