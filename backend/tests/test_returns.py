from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from finanzen.services.performance import period_start
from finanzen.services.returns import compute_returns, ttwror_series, xirr

from .conftest import login

ORIGIN = {"Origin": "https://finanzen.example.org"}


def test_ttwror_ignores_timing_of_flows():
    # +10 %, then 100 added at the close (no gain), then +10 %
    values = [D("100"), D("110"), D("210"), D("231")]
    flows = [D("0"), D("0"), D("100"), D("0")]
    cum = ttwror_series(values, flows)
    assert cum[-1].quantize(D("0.000001")) == D("0.210000")


def test_xirr_reference_values():
    assert xirr([(date(2025, 1, 1), -1000.0), (date(2026, 1, 1), 1100.0)]) == pytest.approx(0.10, abs=1e-6)
    # Leap year: 366 days
    assert xirr([(date(2024, 1, 1), -1000.0), (date(2025, 1, 1), 1100.0)]) == pytest.approx(1.1 ** (365 / 366) - 1, abs=1e-6)
    # Two payments: Excel XIRR reference 0.0752 (approx.)
    r = xirr([(date(2020, 1, 1), -1000.0), (date(2021, 1, 1), -1000.0), (date(2022, 1, 1), 2200.0)])
    assert r == pytest.approx(0.0659, abs=1e-3)
    assert xirr([(date(2020, 1, 1), -1000.0)]) is None


def test_compute_returns_gain_and_irr():
    days = [date(2025, 1, 1) + timedelta(days=i) for i in range(366)]
    values = [D("1000")] * 365 + [D("1100")]
    flows = [D("0")] * 366
    r = compute_returns(days, values, flows)
    assert r.gain == D("100")
    assert r.ttwror == D("0.1")
    assert float(r.irr) == pytest.approx(0.10, abs=1e-4)


def test_period_start():
    inc = date(2020, 5, 1)
    end = date(2026, 11, 23)
    assert period_start("YTD", end, inc) == date(2025, 12, 31)
    assert period_start("1M", end, inc) == date(2026, 10, 23)
    assert period_start("3Y", end, inc) == date(2023, 11, 23)
    assert period_start("ALL", end, inc) == date(2020, 4, 30)
    assert period_start("5Y", end, date(2024, 1, 1)) == date(2023, 12, 31)


def post(client, path, body):
    res = client.post(path, json=body, headers=ORIGIN)
    assert res.status_code in (200, 201), res.text
    return res.json()


def test_depot_performance_end_to_end(client):
    login(client)
    depot = post(client, "/api/accounts", {"name": "Depot", "kind": "depot"})
    etf = post(client, "/api/instruments", {"kind": "etf", "name": "ETF", "price_source": "manual"})
    d0 = date.today() - timedelta(days=10)
    did, iid = depot["id"], etf["id"]
    post(client, f"/api/accounts/{did}/trades", {"date": d0.isoformat(), "type": "buy", "instrument_id": iid, "quantity": "10", "price": "100"})
    post(client, f"/api/instruments/{iid}/prices", {"date": d0.isoformat(), "close": "100"})
    post(client, f"/api/instruments/{iid}/prices", {"date": (d0 + timedelta(days=2)).isoformat(), "close": "110"})
    post(client, f"/api/accounts/{did}/trades", {"date": (d0 + timedelta(days=2)).isoformat(), "type": "buy", "instrument_id": iid, "quantity": "10", "price": "110"})
    post(client, f"/api/instruments/{iid}/prices", {"date": (d0 + timedelta(days=4)).isoformat(), "close": "121"})
    perf = client.get("/api/performance", params={"account_id": did}).json()
    s = perf["summary"]
    assert D(s["end_value"]) == D("2420.00")
    assert D(s["net_flows"]) == D("2100.00")
    assert D(s["gain"]) == D("320.00")
    assert D(s["ttwror"]).quantize(D("0.0001")) == D("0.2100")  # 1.1 x 1.1 - 1, independent of the second buy
    assert s["ttwror_pa"] is None  # shorter than a year
    assert perf["series"][-1]["ttwror"]
    assert set(perf["periods"]) == {"1M", "YTD", "1Y", "3Y", "5Y", "ALL"}


def test_household_networth_and_transfers(client):
    login(client)
    giro = post(client, "/api/accounts", {"name": "Giro", "kind": "giro"})
    depot = post(client, "/api/accounts", {"name": "Depot", "kind": "depot"})
    loan = post(client, "/api/accounts", {"name": "Kredit", "kind": "kredit"})
    etf = post(client, "/api/instruments", {"kind": "etf", "name": "ETF"})
    d0 = date.today() - timedelta(days=40)
    post(client, f"/api/accounts/{giro['id']}/balances", {"date": d0.isoformat(), "amount": "5000"})
    # money moves from giro to depot and is invested: no gain for the household
    post(client, f"/api/accounts/{giro['id']}/transactions", {"booking_date": (d0 + timedelta(days=5)).isoformat(), "amount": "-1000", "kind": "transfer"})
    post(client, f"/api/accounts/{depot['id']}/trades", {"date": (d0 + timedelta(days=5)).isoformat(), "type": "buy", "instrument_id": etf["id"], "quantity": "10", "price": "100"})
    post(client, f"/api/instruments/{etf['id']}/prices", {"date": (d0 + timedelta(days=20)).isoformat(), "close": "105"})
    post(client, f"/api/accounts/{loan['id']}/balances", {"date": d0.isoformat(), "amount": "-20000"})
    nw = client.get("/api/networth", params={"period": "ALL"}).json()
    cur = nw["current"]
    assert D(cur["assets"]) == D("4000") + D("1050.00")
    assert D(cur["liabilities"]) == D("-20000")
    assert D(cur["net"]) == D("-14950.00")
    perf = client.get("/api/performance").json()["summary"]
    assert D(perf["gain"]) == D("50.00")  # only the price gain, the transfer cancels out
    assert D(perf["net_flows"]) == D("5000")  # the opening balance is the capital brought in


def test_pension_contributions_between_statements(client):
    login(client)
    pension = post(client, "/api/accounts", {"name": "Rente", "kind": "altersvorsorge"})
    pid = pension["id"]
    start = date.today() - timedelta(days=400)
    for m in range(0, 360, 30):
        post(client, f"/api/accounts/{pid}/transactions", {"booking_date": (start + timedelta(days=m)).isoformat(), "amount": "100", "kind": "contribution"})
    post(client, f"/api/accounts/{pid}/valuations", {"date": (start + timedelta(days=365)).isoformat(), "value": "1300"})
    perf = client.get("/api/performance", params={"account_id": pid}).json()["summary"]
    assert D(perf["net_flows"]) == D("1200")
    assert D(perf["end_value"]) == D("1300")
    assert D(perf["gain"]) == D("100")
    assert D(perf["ttwror"]) > 0
