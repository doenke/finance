"""onvista (unofficial JSON API, no key). Knows stocks, ETFs, funds, bonds, crypto and precious metals by ISIN.

Symbols have the form "TYPE:ID" (e.g. "FUND:16353294", "CRYPTO:BTCEUR") or "TYPE:ID@NOTATION" to pin a
trading venue. Without a notation the best EUR venue is picked (Xetra, Tradegate, Frankfurt, ...).
"""

import logging
import threading
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import httpx

from .base import PricePoint, PriceSourceError, SearchResult

log = logging.getLogger("finanzen.prices.onvista")

BASE = "https://api.onvista.de/api/v1"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
VENUES = ["GER", "GAT", "FRA", "TRO", "STU", "LSX", "@DE", "MUN", "BER", "DUS", "HAM", "QUO"]
BERLIN = ZoneInfo("Europe/Berlin")
INSTRUMENT_TYPES = {"STOCK", "FUND", "BOND", "CRYPTO", "PRECIOUS_METAL", "INDEX", "CURRENCY", "DERIVATIVE", "CERTIFICATE"}
MIN_INTERVAL = 0.4  # be polite: at most ~2.5 requests per second


def parse_symbol(symbol: str) -> tuple[str, str, int | None]:
    try:
        kind, rest = symbol.split(":", 1)
        ident, _, notation = rest.partition("@")
        return kind.upper(), ident, int(notation) if notation else None
    except ValueError as exc:
        raise PriceSourceError(f"„{symbol}“ ist kein onvista-Symbol (Form TYP:ID, z. B. FUND:16353294).") from exc


def pick_notation(snapshot: dict) -> tuple[int, str] | None:
    """Best venue: EUR quotes first, then by venue preference; falls back to the main quote."""
    quotes = (snapshot.get("quoteList") or {}).get("list") or []
    candidates = []
    for q in quotes:
        market = q.get("market") or {}
        notation = market.get("idNotation") or q.get("idNotation")
        if not notation:
            continue
        code = market.get("codeExchange") or ""
        currency = q.get("isoCurrency") or ""
        rank = (0 if currency == "EUR" else 1, VENUES.index(code) if code in VENUES else len(VENUES))
        candidates.append((rank, int(notation), currency))
    if candidates:
        candidates.sort()
        return candidates[0][1], candidates[0][2]
    main = snapshot.get("quote") or {}
    notation = main.get("idNotation") or (main.get("market") or {}).get("idNotation")
    return (int(notation), main.get("isoCurrency") or "EUR") if notation else None


def parse_history(data: dict) -> list[PricePoint]:
    currency = (data.get("isoCurrency") or "EUR").upper()
    factor = Decimal("1")
    if currency in ("GBX",):
        currency, factor = "GBP", Decimal("0.01")
    out: dict[date, PricePoint] = {}
    for ts, close in zip(data.get("datetimeLast") or [], data.get("last") or [], strict=False):
        if close is None:
            continue
        try:
            value = (Decimal(str(close)) * factor).quantize(Decimal("0.000001"))
        except InvalidOperation:
            continue
        day = datetime.fromtimestamp(ts, BERLIN).date()
        out[day] = PricePoint(day, value, currency)
    return [out[d] for d in sorted(out)]


class OnvistaSource:
    name = "onvista"
    label = "onvista"

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport
        self._client: httpx.Client | None = None
        self._lock = threading.Lock()
        self._last = 0.0

    def _get(self, path: str, params: dict | None = None) -> dict:
        with self._lock:
            if self._client is None:
                self._client = httpx.Client(headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=20.0, transport=self._transport)
            wait = self._last + MIN_INTERVAL - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                res = self._client.get(f"{BASE}{path}", params=params)
            except httpx.HTTPError as exc:
                raise PriceSourceError("onvista ist nicht erreichbar.") from exc
            finally:
                self._last = time.monotonic()
        if res.status_code == 429:
            raise PriceSourceError("onvista verweigert gerade den Zugriff (zu viele Anfragen).")
        try:
            data = res.json()
        except ValueError as exc:
            raise PriceSourceError(f"onvista antwortet nicht wie erwartet ({res.status_code}).") from exc
        if res.status_code != 200:
            if data.get("errorCode") == 4007:
                return {}
            raise PriceSourceError(f"onvista meldet: {data.get('displayErrorMessage') or res.status_code}")
        return data

    def search(self, query: str) -> list[SearchResult]:
        data = self._get("/instruments/search/facet", {"searchValue": query})
        results = []
        for facet in data.get("facets") or []:
            for r in facet.get("results") or []:
                if r.get("entityType") not in INSTRUMENT_TYPES:
                    continue
                results.append(
                    SearchResult(
                        symbol=f"{r['entityType']}:{r['entityValue']}",
                        name=r.get("name") or "",
                        exchange=r.get("isin") or r.get("wkn") or "",
                        type=r.get("displayType") or r.get("entitySubType") or r.get("entityType") or "",
                    )
                )
        return results

    def find_by_isin(self, isin: str) -> str | None:
        for r in self.search(isin):
            if r.exchange == isin:
                return r.symbol
        return None

    def history(self, symbol: str, start: date, end: date) -> list[PricePoint]:
        kind, ident, notation = parse_symbol(symbol)
        if notation is None:
            picked = pick_notation(self._get(f"/instruments/{kind}/{ident}/snapshot"))
            if picked is None:
                raise PriceSourceError("onvista hat für dieses Wertpapier keinen Handelsplatz.")
            notation = picked[0]
        data = self._get(
            f"/instruments/{kind}/{ident}/eod_history",
            {"idNotation": notation, "range": "MAX", "startDate": start.isoformat()},
        )
        return [p for p in parse_history(data) if start <= p.date <= end]
