"""Tiny in-process cache for expensive calculations, invalidated by a global data version."""

import threading
from collections import OrderedDict
from typing import Any

_lock = threading.Lock()
_version = 0
_entries: "OrderedDict[tuple, Any]" = OrderedDict()
MAX_ENTRIES = 32


def bump() -> None:
    """Call after any change to accounts, bookings, prices, ..."""
    global _version
    with _lock:
        _version += 1
        _entries.clear()


def get(key: tuple) -> Any | None:
    with _lock:
        value = _entries.get((_version, *key))
        if value is not None:
            _entries.move_to_end((_version, *key))
        return value


def put(key: tuple, value: Any) -> None:
    with _lock:
        _entries[(_version, *key)] = value
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)
