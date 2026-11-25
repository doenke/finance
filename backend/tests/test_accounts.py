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


def test_loan_with_past_installment_change(client):
    login(client)
    base = {"principal": "100000", "disbursed_on": "2020-01-01", "rate": "2", "first_payment": "2020-02-01", "installment": "400"}
    plain = create(client, "/api/accounts", {"name": "A", "kind": "kredit", "details": base})
    changed = create(client, "/api/accounts", {"name": "B", "kind": "kredit", "details": {**base, "installment_changes": [{"date": "2022-01-01", "installment": "800"}]}})
    a = client.get(f"/api/accounts/{plain['id']}/schedule").json()
    b = client.get(f"/api/accounts/{changed['id']}/schedule").json()
    assert D(b["balance_today"]) < D(a["balance_today"]) - D("10000")
    assert D(changed["value"]) == -D(b["balance_today"])
    row = next(r for r in b["rows"] if r["date"] == "2022-01-01")
    assert D(row["payment"]) == D("800")


def test_holding_period_crypto(client):
    from datetime import date

    from finanzen.services.holdings import free_from

    assert free_from(date(2025, 3, 10)) == date(2026, 3, 11)
    assert free_from(date(2024, 2, 29)) == date(2025, 3, 1)

    login(client)
    acc = create(client, "/api/accounts", {"name": "Wallet", "kind": "krypto"})
    btc = create(client, "/api/instruments", {"kind": "crypto", "name": "Bitcoin"})
    create(client, f"/api/instruments/{btc['id']}/prices", {"date": "2026-06-30", "close": "50000"})
    url = f"/api/accounts/{acc['id']}/trades"
    create(client, url, {"date": "2024-01-15", "type": "buy", "instrument_id": btc["id"], "quantity": "1", "amount": "40000"})
    create(client, url, {"date": "2026-03-01", "type": "buy", "instrument_id": btc["id"], "quantity": "1", "amount": "60000"})
    # 2025-01-10: half of the first lot, not yet free -> taxable
    create(client, url, {"date": "2025-01-10", "type": "sell", "instrument_id": btc["id"], "quantity": "0.5", "amount": "45000"})
    # 2025-02-01: rest of the first lot, now free
    create(client, url, {"date": "2025-02-01", "type": "sell", "instrument_id": btc["id"], "quantity": "0.25", "amount": "25000"})
    res = client.get(f"/api/accounts/{acc['id']}/holding-period", params={"on": "2026-06-30"}).json()
    pos = res["positions"][0]
    assert D(pos["free_quantity"]) == D("0.25") and D(pos["locked_quantity"]) == D("1")
    assert D(pos["free_value"]) == D("12500.00") and D(pos["free_gain"]) == D("2500.00")
    assert D(pos["locked_gain"]) == D("-10000.00")
    assert pos["next_free_date"] == "2027-03-02"
    years = {y["year"]: y for y in res["years"]}
    assert D(years[2025]["short_gain"]) == D("25000.00")  # 45000 - 20000
    assert D(years[2025]["long_gain"]) == D("15000.00")  # 25000 - 10000
    assert D(years[2025]["exemption"]) == D("1000")
    giro = create(client, "/api/accounts", {"name": "Giro", "kind": "giro"})
    assert client.get(f"/api/accounts/{giro['id']}/holding-period").status_code == 422
    from finanzen.mcp.server import t_get_holding_period

    with client.app.state.sessionmaker() as db:
        data = t_get_holding_period(db, None, {"account_id": acc["id"], "on": "2026-06-30"})
    assert data["positions"][0]["instrument"]["name"] == "Bitcoin"


def test_liquidity_available_vs_bound(client):
    login(client)
    today = date.today()
    giro = create(client, "/api/accounts", {"name": "Giro", "kind": "giro"})
    create(client, f"/api/accounts/{giro['id']}/balances", {"date": today.isoformat(), "amount": "2000"})
    card = create(client, "/api/accounts", {"name": "Karte", "kind": "kreditkarte"})
    create(client, f"/api/accounts/{card['id']}/balances", {"date": today.isoformat(), "amount": "-300"})
    end = (today + timedelta(days=200)).isoformat()
    create(client, "/api/accounts", {"name": "Festgeld", "kind": "festgeld", "details": {"amount": "10000", "rate": "0", "start": (today - timedelta(days=10)).isoformat(), "end": end}})
    rente = create(client, "/api/accounts", {"name": "Rente", "kind": "altersvorsorge", "details": {"payout_start": "2046-05-01"}})
    create(client, f"/api/accounts/{rente['id']}/valuations", {"date": today.isoformat(), "value": "25000"})
    gold = create(client, "/api/accounts", {"name": "Goldmünzen im Safe", "kind": "sonstiges", "details": {"liquidity": "available"}})
    create(client, f"/api/accounts/{gold['id']}/valuations", {"date": today.isoformat(), "value": "1500"})
    create(client, "/api/accounts", {"name": "Kredit", "kind": "kredit", "details": {"principal": "50000", "disbursed_on": (today - timedelta(days=40)).isoformat(), "rate": "3", "first_payment": (today + timedelta(days=5)).isoformat(), "installment": "500"}})

    res = client.get("/api/liquidity").json()
    assert D(res["available"]) == D("3200.00")  # 2000 - 300 + 1500
    assert D(res["bound"]) == D("35000.00")
    assert D(res["liabilities"]) < D("-49000")
    assert abs(D(res["net"]) - (D(res["available"]) + D(res["bound"]) + D(res["liabilities"]))) < D("0.01")
    items = {i["name"]: i for i in res["items"]}
    assert items["Festgeld"]["free_from"] == end and items["Festgeld"]["free_reason"] == "Fälligkeit"
    assert items["Rente"]["free_from"] == "2046-05-01" and items["Rente"]["free_reason"] == "Rentenbeginn"
    assert items["Goldmünzen im Safe"]["bucket"] == "available" and items["Goldmünzen im Safe"]["automatic"] is False
    assert items["Kredit"]["bucket"] == "liability"
    bound = [i["name"] for i in res["items"] if i["bucket"] == "bound"]
    assert bound == ["Festgeld", "Rente"]  # sorted by the date they become free


def test_liquidity_splits_available(client):
    login(client)
    today = date.today().isoformat()
    giro = create(client, "/api/accounts", {"name": "Giro", "kind": "giro"})
    create(client, f"/api/accounts/{giro['id']}/balances", {"date": today, "amount": "2000"})
    tg = create(client, "/api/accounts", {"name": "Tagesgeld", "kind": "tagesgeld"})
    create(client, f"/api/accounts/{tg['id']}/balances", {"date": today, "amount": "15000"})
    res = client.get("/api/liquidity").json()
    assert D(res["current"]) == D("2000.00") and D(res["invested"]) == D("15000.00")
    assert D(res["available"]) == D("17000.00")
    groups = {i["name"]: i["group"] for i in res["items"]}
    assert groups == {"Giro": "current", "Tagesgeld": "invested"}


def test_liquidity_lists_positions(client):
    login(client)
    depot = create(client, "/api/accounts", {"name": "Depot", "kind": "depot"})
    world = create(client, "/api/instruments", {"kind": "etf", "name": "World ETF", "isin": "IE00B4L5Y983"})
    stock = create(client, "/api/instruments", {"kind": "stock", "name": "Ohne Kurs AG"})
    url = f"/api/accounts/{depot['id']}/trades"
    create(client, url, {"date": "2024-01-10", "type": "buy", "instrument_id": world["id"], "quantity": "10", "price": "80"})
    create(client, url, {"date": "2024-01-10", "type": "buy", "instrument_id": stock["id"], "quantity": "5", "price": "20"})
    create(client, f"/api/instruments/{world['id']}/prices", {"date": "2025-01-02", "close": "100"})
    item = next(i for i in client.get("/api/liquidity").json()["items"] if i["name"] == "Depot")
    assert D(item["value"]) == D("1100.00")
    first, second = item["positions"]
    assert first["name"] == "World ETF" and D(first["value"]) == D("1000.00") and D(first["gain"]) == D("200.00")
    assert abs(D(first["gain_pct"]) - D("0.25")) < D("0.0001")
    assert second["name"] == "Ohne Kurs AG" and D(second["value"]) == D("100.00")
