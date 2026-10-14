"""Shared fixtures for tests/unit/scripts/ (plan 191-05: RawRow and ingress-result factories)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from services.ohlcv_ingress_contract import IngressResult, RefusedSeries
from services.ohlcv_raw_writer import RawRow


@pytest.fixture
def make_raw_row() -> Callable[..., RawRow]:
    """A RawRow with sane defaults; override any field."""

    def make(**fields) -> RawRow:
        values = dict(
            timestamp=datetime(2026, 9, 27, 13, 30, tzinfo=UTC),
            symbol="SPY",
            timeframe="5m",
            vendor="ibkr",
            kind="named",
            open=600.0,
            high=601.0,
            low=599.0,
            close=600.5,
            volume=1000,
        )
        values.update(fields)
        return RawRow(**values)

    return make


@pytest.fixture
def make_ingress_result() -> Callable[..., IngressResult]:
    """What apply_raw_contract returns for `n` offered rows: all new by default, or refused
    (a vendor restating its own stored rows: nothing written, every offered row held)."""

    def make(n: int, *, refused: bool = False, stamps: tuple = ()) -> IngressResult:
        series = (
            (
                RefusedSeries(
                    "SPY",
                    "5m",
                    "ibkr",
                    "named",
                    0.03,
                    0.02,
                    n,
                    n,
                    f"refused: ibkr restated {n} / its stored {n} = 0.0300 > max 0.0200",
                    n_held=n,
                ),
            )
            if refused
            else ()
        )
        return IngressResult(
            n_offered=n,
            n_new=0 if refused else n,
            n_changed=0,
            n_unchanged=0,
            refused=refused,
            selected_slots=0,
            refused_series=series,
            n_held=n if refused else 0,
            new_timestamps=() if refused else stamps,
        )

    return make
