"""Common interface for price sources."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol


class PriceSourceError(Exception):
    pass


@dataclass
class PricePoint:
    date: date
    close: Decimal
    currency: str


@dataclass
class SearchResult:
    symbol: str
    name: str
    exchange: str
    type: str


class PriceSource(Protocol):
    name: str
    label: str

    def search(self, query: str) -> list[SearchResult]: ...

    def history(self, symbol: str, start: date, end: date) -> list[PricePoint]: ...
