"""Shared fixtures for tests/unit/scripts/ (plan 191-05: RawRow and ingress-result factories)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from services.ohlcv_ingress_contract import FlaggedSeries, IngressResult
from services.ohlcv_raw_writer import RawRow
from src.intelligence.bars.restatement import Restatement


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
    """What apply_raw_contract returns for `n` offered rows: all new by default; `flagged` adds a
    restatement flag (the rows land last-wins all the same, D-191-N)."""

    def make(
        n: int, *, flagged: bool = False, stamps: tuple = (), basis: bool = False
    ) -> IngressResult:
        signatures = ("share", "price_ratio") if basis else ("share",)
        flags = (
            (
                FlaggedSeries(
                    "SPY",
                    "5m",
                    "ibkr",
                    "named",
                    uuid.uuid4(),
                    Restatement(n, n, 1.0, signatures),
                ),
            )
            if flagged or basis
            else ()
        )
        return IngressResult(
            n_offered=n,
            n_new=n,
            n_changed=0,
            n_unchanged=0,
            selected_slots=0,
            new_timestamps=stamps,
            flagged=flags,
        )

    return make
