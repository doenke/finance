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


def test_breakdown_contributions_add_up(client):
    from datetime import date
    from decimal import Decimal as Dec

    from tests.conftest import login as do_login

    origin = {"Origin": "https://finanzen.example.org"}
    do_login(client)

    def make(body):
        res = client.post("/api/accounts", json=body, headers=origin)
        assert res.status_code == 201, res.text
        return res.json()["id"]

    a = make({"name": "Rente", "kind": "altersvorsorge"})
    b = make({"name": "Kunst", "kind": "sonstiges"})
    late = make({"name": "Neu", "kind": "sonstiges"})
    for acc, d, v in [(a, "2025-01-01", "10000"), (a, "2026-01-01", "11550"), (b, "2025-01-01", "5000"), (b, "2026-01-01", "4800"), (late, "2025-10-01", "1000"), (late, "2026-01-01", "1100")]:
        assert client.post(f"/api/accounts/{acc}/valuations", json={"date": d, "value": v}, headers=origin).status_code in (200, 201)
    client.post(f"/api/accounts/{a}/transactions", json={"booking_date": "2025-07-01", "amount": "1000", "kind": "contribution"}, headers=origin)
    res = client.get("/api/performance/breakdown", params={"period": "1Y", "to": "2026-01-01"}).json()
    items = {i["name"]: i for i in res["items"]}
    assert Dec(items["Rente"]["gain"]) == Dec("550")
    assert Dec(items["Kunst"]["gain"]) == Dec("-200")
    assert Dec(items["Neu"]["gain"]) == Dec("100")
    assert Dec(res["total"]["gain"]) == Dec("450")
    total = Dec(res["total"]["simple_return"])
    assert abs(sum(Dec(i["contribution"]) for i in res["items"]) - total) < Dec("1e-12")
    assert abs(sum(Dec(i["weight"]) for i in res["items"]) - 1) < Dec("1e-12")
    # average capital: start value plus flows weighted by the remaining part of the year
    assert abs(Dec(items["Rente"]["avg_capital"]) - (Dec(10000) + Dec(1000) * Dec(184) / Dec(365))) < Dec("0.01")
    assert abs(Dec(items["Neu"]["avg_capital"]) - Dec(1000) * Dec(92) / Dec(365)) < Dec("0.01")
    # sorted by IRR, best first
    assert [i["name"] for i in res["items"]][-1] == "Kunst"
    assert client.get("/api/performance/breakdown", params={"period": "x"}).status_code == 422


def test_breakdown_positions(client):
    from decimal import Decimal as Dec

    from tests.conftest import login as do_login

    origin = {"Origin": "https://finanzen.example.org"}
    do_login(client)

    def post(path, body):
        res = client.post(path, json=body, headers=origin)
        assert res.status_code in (200, 201), res.text
        return res.json()

    depot = post("/api/accounts", {"name": "Depot", "kind": "depot"})["id"]
    up = post("/api/instruments", {"kind": "etf", "name": "Steigt"})["id"]
    down = post("/api/instruments", {"kind": "stock", "name": "Fällt"})["id"]
    post(f"/api/accounts/{depot}/trades", {"date": "2025-01-01", "type": "buy", "instrument_id": up, "quantity": "10", "price": "100"})
    post(f"/api/accounts/{depot}/trades", {"date": "2025-01-01", "type": "buy", "instrument_id": down, "quantity": "10", "price": "50"})
    post(f"/api/accounts/{depot}/trades", {"date": "2025-07-01", "type": "dividend", "instrument_id": up, "amount": "20"})
    post(f"/api/instruments/{up}/prices", {"date": "2026-01-01", "close": "110"})
    post(f"/api/instruments/{down}/prices", {"date": "2026-01-01", "close": "40"})
    res = client.get("/api/performance/breakdown", params={"period": "1Y", "to": "2026-01-01"}).json()
    item = res["items"][0]
    pos = {p["name"]: p for p in item["positions"]}
    assert Dec(pos["Steigt"]["gain"]) == Dec("120")  # 100 price gain + 20 dividend
    assert Dec(pos["Fällt"]["gain"]) == Dec("-100")
    assert sum(Dec(p["gain"]) for p in item["positions"]) == Dec(item["gain"])
    assert abs(sum(Dec(p["contribution"]) for p in item["positions"]) - Dec(item["contribution"])) < Dec("1e-12")
    assert [p["name"] for p in item["positions"]] == ["Steigt", "Fällt"]  # best IRR first


def test_position_compare(client):
    import math
    from datetime import date, timedelta
    from decimal import Decimal as Dec

    from finanzen.models import Price
    from tests.conftest import login as do_login

    origin = {"Origin": "https://finanzen.example.org"}
    do_login(client)
    acc = client.post("/api/accounts", json={"name": "Depot", "kind": "depot"}, headers=origin).json()
    other = client.post("/api/accounts", json={"name": "Zweitdepot", "kind": "depot"}, headers=origin).json()
    a = client.post("/api/instruments", json={"kind": "etf", "name": "World", "price_source": "manual"}, headers=origin).json()
    b = client.post("/api/instruments", json={"kind": "stock", "name": "Rakete", "price_source": "manual"}, headers=origin).json()
    end = date(2026, 6, 30)
    with client.app.state.sessionmaker() as db:
        for k in range(800):
            d = end - timedelta(days=799 - k)
            if d.weekday() >= 5:
                continue
            wave = math.sin(k / 7)
            db.add(Price(instrument_id=a["id"], date=d, close=Dec(str(round(100 * (1.0004 ** k) * (1 + 0.01 * wave), 4))), source="manual"))
            db.add(Price(instrument_id=b["id"], date=d, close=Dec(str(round(50 * (1.0002 ** k) * (1 + 0.05 * wave), 4))), source="manual"))
        db.commit()
    client.post(f"/api/accounts/{acc['id']}/trades", json={"date": "2026-06-01", "type": "deliver_in", "instrument_id": a["id"], "quantity": "10", "price": "100"}, headers=origin)
    client.post(f"/api/accounts/{acc['id']}/trades", json={"date": "2026-06-01", "type": "deliver_in", "instrument_id": b["id"], "quantity": "20", "price": "60"}, headers=origin)
    client.post(f"/api/accounts/{other['id']}/trades", json={"date": "2026-06-01", "type": "deliver_in", "instrument_id": a["id"], "quantity": "5", "price": "100"}, headers=origin)

    res = client.get("/api/positions/compare", params={"period": "1Y", "to": end.isoformat(), "account_id": acc["id"]}).json()
    assert [i["name"] for i in res["items"]] == ["World", "Rakete"]  # stable order by instrument
    world, rakete = res["items"]
    assert Dec(world["quantity"]) == 10  # only the chosen depot
    assert abs(sum(i["weight"] for i in res["items"]) - 1) < 1e-9
    assert len(world["points"]) == len(res["dates"]) and world["points"][0] == 0
    assert world["returns"]["1Y"] > 0 and world["returns"]["3Y"] is None  # not enough history for 3 years
    assert rakete["volatility"] > world["volatility"] > 0
    assert rakete["max_drawdown"] < 0
    corr = res["correlation"]
    assert corr[0][0] == 1.0 and 0.5 < corr[0][1] <= 1 and corr[0][1] == corr[1][0]
    every = client.get("/api/positions/compare", params={"period": "ALL", "to": end.isoformat()}).json()
    assert Dec(every["items"][0]["quantity"]) == 15  # both depots together
    assert every["from"] < "2024-06-01"


def test_purchase_costs_do_not_explode_ttwror(client):
    from datetime import date, timedelta
    from decimal import Decimal as Dec

    from tests.conftest import login as do_login

    origin = {"Origin": "https://finanzen.example.org"}
    do_login(client)
    today = date.today()
    giro = client.post("/api/accounts", json={"name": "Tagesgeld", "kind": "tagesgeld"}, headers=origin).json()["id"]
    client.post(f"/api/accounts/{giro}/balances", json={"date": (today - timedelta(days=60)).isoformat(), "amount": "10000"}, headers=origin)
    flat = {"purchase_date": (today - timedelta(days=30)).isoformat(), "purchase_price": "300000", "purchase_costs": "30000"}
    client.post("/api/accounts", json={"name": "Wohnung", "kind": "immobilie", "details": flat}, headers=origin)
    s = client.get("/api/performance", params={"period": "ALL"}).json()["summary"]
    assert Dec(s["gain"]) == Dec("-30000.00")  # the purchase costs are lost
    # ... but measured against the whole investment (~ -10 %), not against the 10k from the day before (-300 %)
    assert Dec("-0.11") < Dec(s["ttwror"]) < Dec("-0.08")


def test_cash_history_counts_back_from_the_known_balance(client):
    """Bookings imported for a part of the time only: earlier balances follow from today's balance backwards."""
    from datetime import date, timedelta
    from decimal import Decimal as Dec

    from tests.conftest import login as do_login

    origin = {"Origin": "https://finanzen.example.org"}
    do_login(client)
    today = date.today()
    acc = client.post("/api/accounts", json={"name": "Tagesgeld", "kind": "tagesgeld"}, headers=origin).json()["id"]
    d0 = today - timedelta(days=300)
    # money was there before the first imported booking; one withdrawal, one deposit, quarterly interest of ~1 %
    for d, amount, kind in [(d0, "-5000", "other"), (d0 + timedelta(days=90), "25", "interest"), (d0 + timedelta(days=100), "3000", "other"), (d0 + timedelta(days=180), "30", "interest")]:
        client.post(f"/api/accounts/{acc}/transactions", json={"booking_date": d.isoformat(), "amount": amount, "kind": kind}, headers=origin)
    client.post(f"/api/accounts/{acc}/balances", json={"date": today.isoformat(), "amount": "13055"}, headers=origin)
    s = client.get("/api/performance", params={"account_id": acc, "period": "ALL"}).json()["summary"]
    # 15000 were there before the first booking (13055 - (-5000 + 25 + 3000 + 30)): after the withdrawal on
    # the first day 10000 count as brought in, later 3000 more
    assert Dec(s["net_flows"]) == Dec("13000") and Dec(s["gain"]) == Dec("55")
    assert Dec("0.002") < Dec(s["ttwror"]) < Dec("0.006")  # about 0.5 %, not a fantasy value
    on_first_day = client.get(f"/api/accounts/{acc}", params={"on": d0.isoformat()}).json()
    assert Dec(on_first_day["value"]) == Dec("10000.00")
