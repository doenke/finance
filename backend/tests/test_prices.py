import json
from datetime import date
from decimal import Decimal as D

import httpx
import pytest

from finanzen.api.prices import is_stale
from finanzen.services import prices as prices_pkg
from finanzen.services.fx import parse_ecb
from finanzen.services.prices.base import PricePoint, PriceSourceError, SearchResult
from finanzen.services.prices.yahoo import YahooSource, parse_chart

from .conftest import login

ORIGIN = {"Origin": "https://finanzen.example.org"}

CHART = {
    "chart": {
        "result": [
            {
                "meta": {"currency": "EUR", "symbol": "EUNL.DE", "exchangeTimezoneName": "Europe/Berlin"},
                # 2026-11-19 08:00 and 2026-11-20 08:00 Berlin time, plus a gap (None)
                "timestamp": [1795590000, 1795676400, 1795762800],
                "indicators": {"quote": [{"close": [101.25, None, 102.5]}]},
            }
        ],
        "error": None,
    }
}


def test_parse_chart_dates_and_gaps():
    points = parse_chart(CHART)
    assert [p.close for p in points] == [D("101.250000"), D("102.500000")]
    assert all(p.currency == "EUR" for p in points)
    assert points[0].date < points[1].date


def test_parse_chart_pence_and_error():
    data = json.loads(json.dumps(CHART))
    data["chart"]["result"][0]["meta"]["currency"] = "GBp"
    points = parse_chart(data)
    assert points[0].currency == "GBP" and points[0].close == D("1.012500")
    with pytest.raises(PriceSourceError):
        parse_chart({"chart": {"result": None, "error": {"code": "Not Found", "description": "No data found"}}})


def test_yahoo_crumb_handshake_and_search_order():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host == "fc.yahoo.com":
            return httpx.Response(404, headers={"set-cookie": "A3=x; Domain=.yahoo.com; Path=/"})
        if request.url.path == "/v1/test/getcrumb":
            return httpx.Response(200, text="abc123")
        if request.url.path.startswith("/v8/finance/chart"):
            if request.url.params.get("crumb") != "abc123":
                return httpx.Response(429, text="Too Many Requests")
            return httpx.Response(200, json=CHART)
        if request.url.path == "/v1/finance/search":
            return httpx.Response(
                200,
                json={
                    "quotes": [
                        {"symbol": "IWDA.L", "exchange": "LSE", "quoteType": "ETF", "longname": "iShares Core MSCI World"},
                        {"symbol": "EUNL.DE", "exchange": "GER", "quoteType": "ETF", "longname": "iShares Core MSCI World", "exchDisp": "XETRA"},
                        {"symbol": "X=F", "exchange": "CME", "quoteType": "FUTURE"},
                    ]
                },
            )
        return httpx.Response(500)

    source = YahooSource(transport=httpx.MockTransport(handler))
    import finanzen.services.prices.yahoo as y

    y.time.sleep = lambda s: None
    points = source.history("EUNL.DE", date(2026, 11, 1), date(2026, 11, 21))
    assert len(points) == 2
    assert any("getcrumb" in c for c in calls)
    results = source.search("MSCI World")
    assert [r.symbol for r in results] == ["EUNL.DE", "IWDA.L"]


def test_ecb_parse():
    xml = """<?xml version="1.0" encoding="UTF-8"?><gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
    <Cube><Cube time="2026-11-20"><Cube currency="USD" rate="1.099"/><Cube currency="GBP" rate="0.83735"/></Cube>
    <Cube time="2026-11-19"><Cube currency="USD" rate="1.1"/></Cube></Cube></gesmes:Envelope>"""
    rows = parse_ecb(xml)
    assert (date(2026, 11, 20), "USD", D("1.099")) in rows
    assert len(rows) == 3


def test_is_stale():
    assert not is_stale(date(2026, 11, 20), 3, today=date(2026, 11, 23))  # Fri -> Mon = 1 trading day
    assert is_stale(date(2026, 11, 13), 3, today=date(2026, 11, 23))
    assert is_stale(None, 3)


class FakeSource:
    name = "yahoo"
    label = "Fake"

    def __init__(self, currency="EUR"):
        self.currency = currency
        self.requested = []

    def search(self, query):
        return [SearchResult("EUNL.DE", "iShares", "XETRA", "ETF")]

    def history(self, symbol, start, end):
        self.requested.append((symbol, start, end))
        return [PricePoint(date(2026, 11, 19), D("100"), self.currency), PricePoint(date(2026, 11, 20), D("110"), self.currency)]


def test_sync_and_fx_conversion(client, monkeypatch):
    fake = FakeSource("USD")
    monkeypatch.setitem(prices_pkg.SOURCES, "yahoo", fake)
    login(client)
    depot = client.post("/api/accounts", json={"name": "Depot", "kind": "depot"}, headers=ORIGIN).json()
    apple = client.post("/api/instruments", json={"kind": "stock", "name": "Apple", "isin": "US0378331005", "price_source": "yahoo", "price_symbol": "AAPL"}, headers=ORIGIN).json()
    client.post(f"/api/accounts/{depot['id']}/trades", json={"date": "2026-11-18", "type": "buy", "instrument_id": apple["id"], "quantity": "10", "amount": "900"}, headers=ORIGIN)
    res = client.post(f"/api/prices/instruments/{apple['id']}", headers=ORIGIN)
    assert res.json() == {"updated": 2}
    assert fake.requested[0][1] == date(2026, 11, 8)  # first trade minus 10 days
    # instrument currency follows the quote currency
    inst = next(i for i in client.get("/api/instruments").json() if i["id"] == apple["id"])
    assert inst["currency"] == "USD"
    # Without an FX rate the cost is used and the position counts as unpriced
    acc = client.get(f"/api/accounts/{depot['id']}").json()
    assert acc["missing_prices"] == 1
    # Add an ECB rate: 1 EUR = 1.10 USD
    from finanzen.models import FxRate

    with client.app.state.sessionmaker() as db:
        db.add(FxRate(currency="USD", date=date(2026, 11, 20), rate=D("1.10")))
        db.commit()
    acc = client.get(f"/api/accounts/{depot['id']}").json()
    assert acc["missing_prices"] == 0
    assert D(acc["value"]) == D("1000.00")  # 10 x 110 USD / 1.10
    pos = client.get(f"/api/accounts/{depot['id']}/positions").json()[0]
    assert D(pos["price"]) == 110 and D(pos["value"]) == D("1000.00")
    assert client.get("/api/prices/search", params={"q": "msci", "source": "yahoo"}).json()[0]["symbol"] == "EUNL.DE"
    status = client.get("/api/prices/status").json()
    assert status["schedule"]


ONVISTA_SEARCH = {"facets": [{"results": [{"entityType": "FUND", "entityValue": "16353294", "name": "Xtrackers II EUR Overnight Rate Swap UCITS ETF 1C", "isin": "LU0290358497", "displayType": "ETF"}]}]}
ONVISTA_SNAPSHOT = {
    "quote": {"market": {"idNotation": 1}, "isoCurrency": "EUR"},
    "quoteList": {"list": [
        {"market": {"codeExchange": "SWX", "idNotation": 9}, "isoCurrency": "CHF"},
        {"market": {"codeExchange": "GAT", "idNotation": 7}, "isoCurrency": "EUR"},
        {"market": {"codeExchange": "GER", "idNotation": 18271340}, "isoCurrency": "EUR"},
    ]},
}
ONVISTA_EOD = {"isoCurrency": "EUR", "datetimeLast": [1795176000, 1795435200], "last": [150.874, 150.9]}


def onvista_transport():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.endswith("/search/facet"):
            return httpx.Response(200, json=ONVISTA_SEARCH)
        if request.url.path.endswith("/snapshot"):
            return httpx.Response(200, json=ONVISTA_SNAPSHOT)
        if request.url.path.endswith("/eod_history"):
            assert request.url.params["idNotation"] == "18271340"  # Xetra preferred
            return httpx.Response(200, json=ONVISTA_EOD)
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler), calls


def test_onvista_adapter():
    from finanzen.services.prices import onvista

    onvista.MIN_INTERVAL = 0
    transport, calls = onvista_transport()
    src = onvista.OnvistaSource(transport=transport)
    assert src.find_by_isin("LU0290358497") == "FUND:16353294"
    points = src.history("FUND:16353294", date(2026, 11, 1), date(2026, 11, 30))
    assert [p.close for p in points] == [D("150.874000"), D("150.900000")]
    assert points[0].currency == "EUR"
    assert onvista.parse_symbol("FUND:1@2") == ("FUND", "1", 2)
    with pytest.raises(PriceSourceError):
        onvista.parse_symbol("EUNL.DE")


def test_fallback_to_onvista_and_switch(client, monkeypatch):
    from finanzen.services.prices import onvista

    onvista.MIN_INTERVAL = 0
    transport, _ = onvista_transport()
    monkeypatch.setitem(prices_pkg.SOURCES, "onvista", onvista.OnvistaSource(transport=transport))

    class Blocked:
        name = "yahoo"
        label = "Yahoo"

        def history(self, *a):
            raise PriceSourceError("Yahoo verweigert gerade den Zugriff (zu viele Anfragen).")

        def search(self, q):
            raise PriceSourceError("zu viele Anfragen")

    monkeypatch.setitem(prices_pkg.SOURCES, "yahoo", Blocked())
    login(client)
    xeon = client.post("/api/instruments", json={"kind": "etf", "name": "XEON", "isin": "LU0290358497", "price_source": "yahoo", "price_symbol": "XEON.DE"}, headers=ORIGIN).json()
    res = client.post(f"/api/prices/instruments/{xeon['id']}", headers=ORIGIN).json()
    assert res == {"updated": 2}
    inst = next(i for i in client.get("/api/instruments").json() if i["id"] == xeon["id"])
    assert inst["details"]["onvista_symbol"] == "FUND:16353294"
    assert D(inst["last_price"]) == D("150.9")
    sw = client.post("/api/prices/switch-to-onvista", headers=ORIGIN).json()
    assert sw["switched"] == 1
    inst = next(i for i in client.get("/api/instruments").json() if i["id"] == xeon["id"])
    assert (inst["price_source"], inst["price_symbol"]) == ("onvista", "FUND:16353294")
    assert client.get("/api/prices/search", params={"q": "LU0290358497"}).json()[0]["symbol"] == "FUND:16353294"
