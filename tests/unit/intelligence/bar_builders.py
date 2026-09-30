"""Synthetic bar builders shared by the kernel, alignment and pipeline tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np


def synthetic_daily_bars(n: int, seed: int, start_close: float = 100.0) -> list[dict]:
    """`n` oldest-first daily bars (ts/open/high/low/close/volume) on a seeded random walk."""
    rng = np.random.default_rng(seed)
    closes = start_close * np.cumprod(1 + rng.normal(0, 0.01, n))
    base = datetime(2020, 1, 2, 21, 0, tzinfo=UTC)
    return [
        {
            "ts": base + timedelta(days=i),
            "open": float(closes[i] * 0.999),
            "high": float(closes[i] * 1.001),
            "low": float(closes[i] * 0.999),
            "close": float(closes[i]),
            "volume": 1_000_000.0,
        }
        for i in range(n)
    ]
