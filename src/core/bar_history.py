"""BarHistory — typed deque store for per-(symbol, tf) bar sequences.

BarHistory is the canonical in-memory store for completed bars flowing through
the feature pipeline. It replaces raw dict[str, deque] stores scattered across
services with a typed, testable, single-responsibility module.

Interface decisions (D-08, D-09, D-10, D-11):
- maxlen: configurable deque size (default 200)
- Keys: (symbol, tf) — same coordinate system as every other hot-path dict
- to_dataframe: returns DataFrame with canonical column names (open/high/low/close/volume)
  not the abbreviated OHLCVBar names (o/h/l/c/v)
- seed: DB-loaded bars; maxlen is honored so seed never grows beyond capacity
- migrate_symbol: contract-roll support — atomic rename of all (old_symbol, tf) keys
  to (new_symbol, tf) without dropping any buffered bars

Implementation: Wave 1 (44.1-02). This file is a class shell — all methods raise
NotImplementedError. Tests are in tests/unit/core/test_bar_history.py.
"""

from __future__ import annotations

from collections import deque

import pandas as pd

from src.core.schemas.bar_message import BarMessage


class BarHistory:
    """Per-(symbol, tf) deque store for completed bars.

    Args:
        maxlen: Maximum bars retained per (symbol, tf) key (default 200).
                Oldest bars are evicted when the deque is full.
    """

    def __init__(self, maxlen: int = 200) -> None:
        self._maxlen = maxlen
        self._data: dict[str, deque[BarMessage]] = {}

    def append(self, bar: BarMessage) -> None:
        """Append a completed bar to the deque for (bar.symbol, bar.tf).

        Creates the deque if it does not yet exist. If the deque is at maxlen,
        the oldest bar is automatically evicted.
        """
        raise NotImplementedError

    def get(self, symbol: str, tf: str) -> deque[BarMessage]:
        """Return the deque for (symbol, tf).

        Returns an empty deque if no bars have been appended for this key.
        Callers must not mutate the returned deque directly.
        """
        raise NotImplementedError

    def to_dataframe(self, symbol: str, tf: str) -> pd.DataFrame:
        """Return a DataFrame of bars for (symbol, tf), ordered oldest-first.

        Columns: timestamp, open, high, low, close, volume
        Returns an empty DataFrame (correct columns, 0 rows) for unknown keys.
        """
        raise NotImplementedError

    def is_warm(self, symbol: str, tf: str, min_bars: int) -> bool:
        """Return True when the deque for (symbol, tf) has at least min_bars entries.

        Used by pipeline services as a warmup gate before plugin execution.
        """
        raise NotImplementedError

    def seed(self, symbol: str, tf: str, bars: list[BarMessage]) -> None:
        """Populate the deque for (symbol, tf) from a DB-loaded list.

        bars is assumed to be in ascending ts order. If len(bars) > maxlen,
        only the most recent maxlen bars are kept (maxlen is honored).
        Existing deque contents are replaced on seed.
        """
        raise NotImplementedError

    def migrate_symbol(self, old_symbol: str, new_symbol: str) -> None:
        """Atomically rename all (old_symbol, tf) keys to (new_symbol, tf).

        Used during futures contract rolls to transfer buffered bar history
        to the new front-month contract without dropping any bars.
        If old_symbol has no data, this method is a no-op (does not error).
        """
        raise NotImplementedError
