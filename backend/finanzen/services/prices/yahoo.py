"""Yahoo Finance (unofficial API, no key). Uses the cookie/crumb handshake when Yahoo asks for it."""

import logging
import threading
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import httpx

from .base import PricePoint, PriceSourceError, SearchResult

log = logging.getLogger("finanzen.prices.yahoo")

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
HOSTS = ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com")
# Prefer German exchanges, then other EUR venues.
EXCHANGE_ORDER = {"GER": 0, "FRA": 1, "STU": 2, "MUN": 3, "BER": 4, "DUS": 5, "HAM": 6, "AMS": 7, "PAR": 8, "MIL": 9, "CCC": 10}


class YahooSource:
    name = "yahoo"
    label = "Yahoo Finance"

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport
        self._client: httpx.Client | None = None
        self._crumb: str | None = None
        self._lock = threading.Lock()

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=15.0,
                follow_redirects=True,
                transport=self._transport,
            )
        return self._client

    def _refresh_crumb(self) -> None:
        client = self._http()
        try:
            client.get("https://fc.yahoo.com")
        except httpx.HTTPError:
            pass  # the cookie is set even on the error page
        res = client.get(f"{HOSTS[1]}/v1/test/getcrumb")
        crumb = res.text.strip()
        if res.status_code != 200 or not crumb or " " in crumb:
            raise PriceSourceError("Yahoo verweigert gerade den Zugriff (zu viele Anfragen).")
        self._crumb = crumb

    def _get(self, path: str, params: dict) -> dict:
        with self._lock:
            client = self._http()
            last_status = 0
            for attempt in range(3):
                for host in HOSTS:
                    query = dict(params)
                    if self._crumb:
                        query["crumb"] = self._crumb
                    try:
                        res = client.get(f"{host}{path}", params=query)
                    except httpx.HTTPError as exc:
                        log.info("yahoo request failed: %s", exc.__class__.__name__)
                        continue
                    last_status = res.status_code
                    if res.status_code == 200:
                        return res.json()
                    if res.status_code == 404:
                        raise PriceSourceError("Symbol bei Yahoo nicht gefunden.")
                if last_status in (401, 403, 429) and attempt == 0:
                    try:
                        self._refresh_crumb()
                    except (PriceSourceError, httpx.HTTPError):
                        pass
                time.sleep(1.5 * (attempt + 1))
            if last_status == 429:
                raise PriceSourceError("Yahoo verweigert gerade den Zugriff (zu viele Anfragen).")
            raise PriceSourceError(f"Yahoo antwortet nicht wie erwartet ({last_status or 'keine Verbindung'}).")

    def search(self, query: str) -> list[SearchResult]:
        data = self._get("/v1/finance/search", {"q": query, "quotesCount": 10, "newsCount": 0, "listsCount": 0})
        results = [
            SearchResult(
                symbol=q["symbol"],
                name=q.get("longname") or q.get("shortname") or q["symbol"],
                exchange=q.get("exchDisp") or q.get("exchange") or "",
                type=q.get("quoteType") or "",
            )
            for q in data.get("quotes", [])
            if q.get("symbol") and q.get("quoteType") not in ("FUTURE", "OPTION")
        ]
        order = {q["symbol"]: EXCHANGE_ORDER.get(q.get("exchange", ""), 50) for q in data.get("quotes", []) if q.get("symbol")}
        return sorted(results, key=lambda r: order.get(r.symbol, 50))

    def history(self, symbol: str, start: date, end: date) -> list[PricePoint]:
        period1 = int(datetime(start.year, start.month, start.day, tzinfo=UTC).timestamp())
        period2 = int((datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1)).timestamp())
        data = self._get(f"/v8/finance/chart/{symbol}", {"period1": period1, "period2": period2, "interval": "1d", "events": "div,splits"})
        return parse_chart(data)


def parse_chart(data: dict) -> list[PricePoint]:
    chart = data.get("chart") or {}
    if chart.get("error"):
        raise PriceSourceError(f"Yahoo meldet: {chart['error'].get('description') or chart['error'].get('code')}")
    results = chart.get("result") or []
    if not results:
        return []
    result = results[0]
    meta = result.get("meta") or {}
    currency = meta.get("currency") or "EUR"
    factor = Decimal("1")
    if currency in ("GBp", "GBX"):  # London quotes in pence
        currency, factor = "GBP", Decimal("0.01")
    elif currency == "ZAc":
        currency, factor = "ZAR", Decimal("0.01")
    try:
        tz = ZoneInfo(meta.get("exchangeTimezoneName") or "UTC")
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    stamps = result.get("timestamp") or []
    closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    by_day: dict[date, PricePoint] = {}
    for ts, close in zip(stamps, closes, strict=False):
        if close is None:
            continue
        try:
            value = (Decimal(str(close)) * factor).quantize(Decimal("0.000001"))
        except InvalidOperation:
            continue
        day = datetime.fromtimestamp(ts, tz).date()
        by_day[day] = PricePoint(day, value, currency.upper())
    return [by_day[d] for d in sorted(by_day)]
