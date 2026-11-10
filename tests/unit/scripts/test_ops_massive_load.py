"""Massive per-year loader: the day accounting and the guards that need no database."""

from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np

from scripts.ops.bars import ops_massive_load as loader
from src.intelligence.bars.massive_flat import FlatBars
from src.intelligence.bars.massive_symbol_map import TickerSpan

DAY = date(2024, 6, 11)
T0 = int(datetime(2024, 6, 11, 13, 30, tzinfo=UTC).timestamp()) * 1_000_000_000
STEP = 300 * 1_000_000_000


def _bars():
    # AAA two bars, BBB one bar, CCC one bar (CCC has no span that day)
    tickers = np.array(["AAA", "BBB", "CCC"])
    z = np.zeros(4)
    return FlatBars(
        tickers=tickers,
        ticker_index=np.array([0, 0, 1, 2], dtype=np.int32),
        t_ns=np.array([T0, T0 + STEP, T0, T0], dtype=np.int64),
        open=z,
        high=z,
        low=z,
        close=z,
        volume=np.zeros(4, dtype=np.int64),
        n_untraded_rows=3,
        traded_minutes=np.array([9, 4, 2]),
    )


def _mapping():
    return {
        "AAA": TickerSpan("e1", "AAA", "AAA", date(2003, 9, 10), None),
        "BBB": TickerSpan("e2", "BBX", "BBB", date(2003, 9, 10), None),
    }


def _slot(t_ns):
    return datetime.fromtimestamp(t_ns / 1_000_000_000, UTC)


def test_day_balance_counts_mapped_unmapped_and_massive_only_slots():
    incumbent = {
        ("AAA", datetime.fromtimestamp(T0 / 1_000_000_000, UTC))
    }  # held for AAA's first bar
    report = loader.account_day(DAY, _bars(), _mapping(), incumbent, _slot)
    assert (report.bars_out, report.bars_unmapped) == (3, 1)
    assert (report.mapped_tickers, report.unmapped_tickers) == (2, 1)
    assert (report.traded_minutes_in, report.traded_minutes_mapped) == (15, 13)
    assert report.untraded_rows == 3
    # AAA's second bar and BBX's bar have no incumbent row: the expected unselected slots
    assert report.massive_only == 2
    assert report.unmapped_sample == ["CCC"]


def test_instrument_symbol_not_the_file_ticker_keys_the_incumbent_slot():
    incumbent = {("BBX", datetime.fromtimestamp(T0 / 1_000_000_000, UTC))}
    report = loader.account_day(DAY, _bars(), _mapping(), incumbent, _slot)
    assert report.massive_only == 2  # AAA x2 unheld; BBX held


def test_an_empty_mapping_excludes_every_bar():
    report = loader.account_day(DAY, _bars(), {}, set(), _slot)
    assert (report.bars_out, report.bars_unmapped, report.massive_only) == (0, 4, 0)


def test_years_must_be_newest_first(capsys):
    import pytest

    with pytest.raises(SystemExit):
        loader.main(["--timeframe", "5m", "--years", "2023", "2024"])
