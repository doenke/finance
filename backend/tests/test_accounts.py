from datetime import date, timedelta
from decimal import Decimal as D

from .conftest import login

ORIGIN = {"Origin": "https://finanzen.example.org"}


def create(client, path, body, status=201):
    res = client.post(path, json=body, headers=ORIGIN)
    assert res.status_code == status, res.text
    return res.json()


def test_meta(client):
    login(client)
    meta = client.get("/api/meta").json()
    assert {"giro", "depot", "kredit", "stak"} <= {k["key"] for k in meta["kinds"]}


def test_cash_account_balance_and_transactions(client):
    login(client)
    acc = create(client, "/api/accounts", {"name": "Giro Sparkasse", "kind": "giro", "institution": "Sparkasse", "iban": "de89 3704 0044 0532 0130 00"})
    assert acc["iban"] == "DE89370400440532013000"
    assert acc["asset_class"] == "cash"
    assert len(acc["owners"]) == 1 and D(acc["owners"][0]["share"]) == 1
    aid = acc["id"]
    create(client, f"/api/accounts/{aid}/balances", {"date": "2025-01-01", "amount": "1000.00"})
    create(client, f"/api/accounts/{aid}/transactions", {"booking_date": "2024-12-30", "amount": "-50", "counterparty": "vor dem Saldo"})
    create(client, f"/api/accounts/{aid}/transactions", {"booking_date": "2025-01-05", "amount": "-120.50", "counterparty": "Stadtwerke"})
    create(client, f"/api/accounts/{aid}/transactions", {"booking_date": "2025-01-31", "amount": "2500", "kind": "income", "counterparty": "Arbeitgeber"})
    assert D(client.get(f"/api/accounts/{aid}").json()["value"]) == D("3379.50")
    assert D(client.get(f"/api/accounts/{aid}", params={"on": "2025-01-10"}).json()["value"]) == D("879.50")
    found = client.get(f"/api/accounts/{aid}/transactions", params={"q": "stadt"}).json()
    assert [t["counterparty"] for t in found] == ["Stadtwerke"]


def test_shared_ownership_validation(client):
    login(client, "Anna")
    other = create(client, "/api/persons", {"name": "Ben"})
    me = client.get("/api/me").json()["person_id"]
    bad = client.post("/api/accounts", json={"name": "X", "kind": "giro", "owners": [{"person_id": me, "share": "0.5"}]}, headers=ORIGIN)
    assert bad.status_code == 422
    acc = create(client, "/api/accounts", {"name": "Gemeinsam", "kind": "tagesgeld", "owners": [{"person_id": me, "share": "0.5"}, {"person_id": other["id"], "share": "0.5"}]})
    assert len(acc["owners"]) == 2
    assert client.delete(f"/api/persons/{other['id']}").status_code == 409


def test_depot_positions(client):
    login(client)
    depot = create(client, "/api/accounts", {"name": "Depot", "kind": "depot"})
    etf = create(client, "/api/instruments", {"kind": "etf", "name": "iShares Core MSCI World", "isin": "ie00b4l5y983", "price_source": "yahoo", "price_symbol": "EUNL.DE"})
    assert etf["isin"] == "IE00B4L5Y983"
    assert client.post("/api/instruments", json={"kind": "etf", "name": "dup", "isin": "IE00B4L5Y983"}, headers=ORIGIN).status_code == 409
    did = depot["id"]
    create(client, f"/api/accounts/{did}/trades", {"date": "2024-01-10", "type": "buy", "instrument_id": etf["id"], "quantity": "10", "price": "80", "fees": "1"})
    create(client, f"/api/accounts/{did}/trades", {"date": "2024-06-10", "type": "sell", "instrument_id": etf["id"], "quantity": "4", "price": "90"})
    create(client, f"/api/accounts/{did}/trades", {"date": "2024-07-01", "type": "dividend", "instrument_id": etf["id"], "amount": "3.20"})
    assert client.post(f"/api/accounts/{did}/trades", json={"date": "2024-01-10", "type": "buy", "quantity": "1"}, headers=ORIGIN).status_code == 422
    # Without a price the last trade price is used
    positions = client.get(f"/api/accounts/{did}/positions").json()
    assert len(positions) == 1
    assert D(positions[0]["quantity"]) == 6
    assert D(positions[0]["value"]) == D("540.00")
    create(client, f"/api/instruments/{etf['id']}/prices", {"date": "2025-01-02", "close": "100"})
    positions = client.get(f"/api/accounts/{did}/positions").json()
    assert D(positions[0]["value"]) == D("600.00")
    assert D(positions[0]["cost"]) == D("480.60")  # 6/10 of 801
    assert D(positions[0]["realized"]) == D("360") - D("320.40")
    assert D(positions[0]["income"]) == D("3.20")
    assert D(client.get(f"/api/accounts/{did}").json()["value"]) == D("600.00")


def test_metal_unit_conversion(client):
    login(client)
    acc = create(client, "/api/accounts", {"name": "Gold", "kind": "edelmetall"})
    gold = create(client, "/api/instruments", {"kind": "metal", "name": "Goldbarren 100 g", "unit": "g", "details": {"price_unit": "oz", "fineness": "0.9999"}})
    create(client, f"/api/accounts/{acc['id']}/trades", {"date": "2024-01-01", "type": "buy", "instrument_id": gold["id"], "quantity": "100", "amount": "6000"})
    create(client, f"/api/instruments/{gold['id']}/prices", {"date": "2025-01-01", "close": "2500"})
    value = D(client.get(f"/api/accounts/{acc['id']}").json()["value"])
    assert value == (D("100") * D("0.9999") / D("31.1034768") * 2500).quantize(D("0.01"))


def test_valuation_loan_and_deposit(client):
    login(client)
    home = create(client, "/api/accounts", {"name": "Wohnung", "kind": "immobilie", "details": {"purchase_price": "300000"}})
    create(client, f"/api/accounts/{home['id']}/valuations", {"date": "2024-12-31", "value": "350000"})
    assert D(client.get(f"/api/accounts/{home['id']}").json()["value"]) == 350000
    assert client.post(f"/api/accounts/{home['id']}/balances", json={"date": "2024-12-31", "amount": "1"}, headers=ORIGIN).status_code == 422

    loan = create(
        client,
        "/api/accounts",
        {
            "name": "Baufinanzierung",
            "kind": "kredit",
            "details": {"principal": "200000", "disbursed_on": "2024-01-01", "rate": "3.5", "first_payment": "2024-02-01", "initial_repayment": "2", "fixed_until": "2034-01-31", "prepayment_allowance_pct": "5", "planned_prepayments": [{"date": "2025-12-01", "amount": "5000", "repeat": "yearly"}]},
        },
    )
    value = D(client.get(f"/api/accounts/{loan['id']}").json()["value"])
    assert -200000 < value < -150000
    sched = client.get(f"/api/accounts/{loan['id']}/schedule").json()
    assert D(sched["prepayment_allowance"]) == 10000
    assert sched["end_date"] is not None
    without = client.get(f"/api/accounts/{loan['id']}/schedule", params={"planned": False}).json()
    assert without["end_date"] > sched["end_date"]
    # Bank statement re-anchors the schedule
    create(client, f"/api/accounts/{loan['id']}/balances", {"date": (date.today() - timedelta(days=1)).isoformat(), "amount": "-150000"})
    assert D(client.get(f"/api/accounts/{loan['id']}").json()["value"]) == D("-150000")

    fd = create(client, "/api/accounts", {"name": "Festgeld", "kind": "festgeld", "details": {"amount": "10000", "rate": "3", "start": "2024-01-01", "end": "2025-01-01"}})
    assert D(fd["value"]) == D("10300.83")  # 2024 has 366 days
