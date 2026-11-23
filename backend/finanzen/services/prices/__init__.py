"""Price sources. Each source is an adapter; more can be registered later (see SOURCES)."""

from .base import PricePoint, PriceSource, PriceSourceError, SearchResult
from .yahoo import YahooSource

SOURCES: dict[str, PriceSource] = {"yahoo": YahooSource()}

__all__ = ["SOURCES", "PricePoint", "PriceSource", "PriceSourceError", "SearchResult"]
