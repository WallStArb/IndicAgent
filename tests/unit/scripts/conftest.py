"""Shared fixtures for tests/unit/scripts/."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pytest

from services.ohlcv_ingress_contract import RevisionRefused, SeriesLoad


@pytest.fixture
def make_refusal() -> Callable[..., RevisionRefused]:
    """A RevisionRefused as the ingress contract raises it (ratio 0.03 over max 0.02), carrying
    `rows` as the served rows the raw archive captures."""

    def make(rows: list[tuple] | None = None) -> RevisionRefused:
        load = SeriesLoad(
            symbol="SPY",
            timeframe="15m",
            destination="archive",
            caller="ibkr-history-fetch",
            source="ibkr",
            n_bars=1000,
            n_stored=1000,
            n_new=0,
            n_changed=30,
            n_unchanged=970,
            first_bar=date(2026, 9, 27),
            last_bar=date(2026, 9, 27),
        )
        return RevisionRefused(load, ratio=0.03, max_ratio=0.02, rows=rows)

    return make
