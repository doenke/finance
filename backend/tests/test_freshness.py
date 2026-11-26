from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

from finanzen.models import Account, Bank, BankLogin, Instrument, Price, Trade
from finanzen.services.freshness import freshness, savings_plan

from .conftest import login

ORIGIN = {"Origin": "https://finanzen.example.org"}
TODAY = date(2026, 11, 26)  # a Thursday


def test_savings_plan_detection():
    monthly = [date(2026, m, 20) for m in range(5, 12)]
    assert savings_plan(monthly, TODAY)
    assert not savings_plan([date(2026, 6, 5), date(2026, 9, 1)], TODAY)


def test_traffic_light(client):
    login(client)
    with client.app.state.sessionmaker() as db:
        etf = Instrument(kind="etf", name="World", price_source="onvista", currency="EUR")
        coin = Instrument(kind="crypto", name="Bitcoin", price_source="onvista", currency="EUR")
        db.add_all([etf, coin])
        db.flush()
        db.add(Price(instrument_id=etf.id, date=date(2026, 11, 25), close=D("100")))  # yesterday: fresh
        db.add(Price(instrument_id=coin.id, date=date(2026, 11, 25), close=D("50000")))
        plan = Account(name="Depot Sparplan", kind="depot", asset_class="securities", details={})
        crypto = Account(name="Krypto", kind="krypto", asset_class="crypto", details={})
        db.add_all([plan, crypto])
        db.flush()
        for m in range(4, 10):  # monthly savings plan up to September – October and November are missing
            db.add(Trade(account_id=plan.id, instrument_id=etf.id, date=date(2026, m, 20), type="buy", quantity=D("1"), price=D("100"), amount=D("100")))
        db.add(Trade(account_id=crypto.id, instrument_id=coin.id, date=date(2026, 7, 1), type="buy", quantity=D("0.1"), price=D("50000"), amount=D("5000")))
        bank = Bank(name="Sparkasse", blz="39050000", server_url="https://banking.example.org")
        db.add(bank)
        db.flush()
        bl = BankLogin(bank_id=bank.id, username="max", last_sync_at=datetime(2026, 11, 24, 8, tzinfo=UTC))
        db.add(bl)
        db.flush()
        giro = Account(name="Giro", kind="giro", asset_class="cash", bank_login_id=bl.id, details={})
        db.add(giro)
        db.commit()
        crypto_id = crypto.id
        data = freshness(db, TODAY)
    by_name = {i["name"]: i for i in data["items"]}
    assert by_name["World"]["status"] == "green"
    assert next(i for i in data["items"] if i["area"] == "bank")["status"] == "green"  # synced two days ago
    assert by_name["Depot Sparplan"]["status"] == "yellow" and "Sparplan" in by_name["Depot Sparplan"]["message"]
    assert by_name["Krypto"]["status"] == "green"  # bought in July: within half a year
    assert data["status"] == "yellow"

    # half a year later the crypto depot needs a look – "Bestand stimmt" makes it green again
    with client.app.state.sessionmaker() as db:
        later = freshness(db, date(2027, 2, 15))
    assert {i["name"]: i for i in later["items"]}["Krypto"]["status"] == "yellow"
    res = client.post(f"/api/accounts/{crypto_id}/confirm", headers=ORIGIN)
    assert res.status_code == 200
    api = client.get("/api/freshness").json()
    assert {i["name"]: i for i in api["items"]}["Krypto"]["status"] == "green"


def test_old_bank_sync_is_red(client):
    login(client)
    with client.app.state.sessionmaker() as db:
        bank = Bank(name="DKB", blz="12030000", server_url="https://banking.example.org")
        db.add(bank)
        db.flush()
        bl = BankLogin(bank_id=bank.id, username="anna", last_sync_at=datetime(2026, 9, 1, tzinfo=UTC))
        db.add(bl)
        db.flush()
        db.add(Account(name="DKB Giro", kind="giro", asset_class="cash", bank_login_id=bl.id, details={}))
        db.commit()
        data = freshness(db, TODAY)
    bank_item = next(i for i in data["items"] if i["area"] == "bank")
    assert bank_item["status"] == "red" and data["status"] == "red"
