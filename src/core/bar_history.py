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

Implementation: Wave 1 (44.1-02).
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

    @property
    def maxlen(self) -> int:
        """Configured per-(symbol, tf) capacity -- read-only, set at construction."""
        return self._maxlen

    def append(self, bar: BarMessage) -> None:
        """Append a completed bar to the deque for (bar.symbol, bar.tf).

        Creates the deque if it does not yet exist. If the deque is at maxlen,
        the oldest bar is automatically evicted.
        """
        key = f"{bar.symbol}:{bar.tf}"
        if key not in self._data:
            self._data[key] = deque(maxlen=self._maxlen)
        self._data[key].append(bar)

    def get(self, symbol: str, tf: str) -> deque[BarMessage]:
        """Return the deque for (symbol, tf).

        Returns an empty deque if no bars have been appended for this key.
        Callers must not mutate the returned deque directly.
        """
        return self._data.get(f"{symbol}:{tf}", deque())

    def to_dataframe(self, symbol: str, tf: str) -> pd.DataFrame:
        """Return a DataFrame of bars for (symbol, tf), ordered oldest-first.

        Columns: timestamp, open, high, low, close, volume
        Returns an empty DataFrame (correct columns, 0 rows) for unknown keys.
        """
        bars = self._data.get(f"{symbol}:{tf}")
        columns = ["timestamp", "open", "high", "low", "close", "volume"]
        if not bars:
            return pd.DataFrame(
                {
                    "timestamp": pd.Series(dtype="datetime64[ns, UTC]"),
                    "open": pd.Series(dtype="float64"),
                    "high": pd.Series(dtype="float64"),
                    "low": pd.Series(dtype="float64"),
                    "close": pd.Series(dtype="float64"),
                    "volume": pd.Series(dtype="int64"),
                }
            )
        rows = [
            {
                "timestamp": bar.ts,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
            for bar in bars
        ]
        df = pd.DataFrame(rows, columns=columns)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col].astype("float64")
        df["volume"] = df["volume"].astype("int64")
        return df

    def is_warm(self, symbol: str, tf: str, min_bars: int) -> bool:
        """Return True when the deque for (symbol, tf) has at least min_bars entries.

        Used by pipeline services as a warmup gate before plugin execution.
        """
        return len(self.get(symbol, tf)) >= min_bars

    def seed(self, symbol: str, tf: str, bars: list[BarMessage]) -> None:
        """Populate the deque for (symbol, tf) from a DB-loaded list.

        bars is assumed to be in ascending ts order. If len(bars) > maxlen,
        only the most recent maxlen bars are kept (maxlen is honored).
        Existing deque contents are replaced on seed.
        """
        key = f"{symbol}:{tf}"
        self._data[key] = deque(bars[-self._maxlen :], maxlen=self._maxlen)

    def migrate_symbol(self, old_symbol: str, new_symbol: str) -> None:
        """Atomically rename all (old_symbol, tf) keys to (new_symbol, tf).

        Used during futures contract rolls to transfer buffered bar history
        to the new front-month contract without dropping any bars.
        If old_symbol has no data, this method is a no-op (does not error).
        """
        prefix = f"{old_symbol}:"
        for old_key in [k for k in self._data if k.startswith(prefix)]:
            tf = old_key[len(prefix) :]
            self._data[f"{new_symbol}:{tf}"] = self._data.pop(old_key)
