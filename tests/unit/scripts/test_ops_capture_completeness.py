"""Unit tests for the capture completeness rule (todo 528 R6, phase 191 plan 11): the join
(`_build_report`) and the pure arithmetic (`_classify`) over the raw ledger and ohlcv_raw; the
SQL and printing stay untested here."""

from __future__ import annotations

import pandas as pd

from scripts.ops.bars import ops_capture_completeness as r6
from scripts.ops.bars.ops_capture_completeness import _build_report, _classify

_LEDGER = list(r6._COUNT_COLS[:-3])


def _frame(**overrides: int) -> pd.DataFrame:
    base = dict.fromkeys(r6._COUNT_COLS, 0)
    base.update(overrides)
    return pd.DataFrame([base], columns=list(r6._COUNT_COLS)).astype("int64")


def test_balanced_series_is_clean() -> None:
    out = _classify(_frame(served=10, new=6, changed=2, unchanged=2, revisions=2, current=8))
    assert out["unexplained"].iloc[0] == 0


def test_served_bar_with_no_outcome_is_unexplained() -> None:
    out = _classify(_frame(served=10, new=6, changed=2, unchanged=1, revisions=2, current=8))
    assert out["ledger_gap"].iloc[0] == 1
    assert out["unexplained"].iloc[0] == 1


def test_changed_value_without_revision_is_unexplained() -> None:
    out = _classify(_frame(served=4, new=2, changed=2, revisions=1, current=4))
    assert out["revision_gap"].iloc[0] == 1
    assert out["unexplained"].iloc[0] == 1


def test_removed_bar_is_explained_and_logged() -> None:
    out = _classify(_frame(served=5, new=3, removed=2, revisions=2, current=1))
    assert out["lost_new"].iloc[0] == 0
    assert out["unexplained"].iloc[0] == 0


def test_new_row_missing_from_raw_is_lost() -> None:
    out = _classify(_frame(served=5, new=5, current=3))
    assert out["lost_new"].iloc[0] == 2
    assert out["unexplained"].iloc[0] == 2


def test_raw_row_under_an_uncounted_load_is_unledgered() -> None:
    out = _classify(_frame(served=2, new=2, current=5))
    assert out["unledgered"].iloc[0] == 3
    assert out["unexplained"].iloc[0] == 3


def test_restamped_rows_are_explained_not_unledgered() -> None:
    out = _classify(
        _frame(
            served=3,
            changed=3,
            revisions=3,
            restamp_current=100,
            restamp_written=3,
        )
    )
    assert out["restamped"].iloc[0] == 97
    assert out["unledgered"].iloc[0] == 0
    assert out["unexplained"].iloc[0] == 0


def test_build_report_joins_ledger_and_current_on_source_and_timeframe() -> None:
    ledger = pd.DataFrame(
        [("ibkr", "1d", 4, 4, 0, 0, 0, 0, 0, 0), ("tradier", "1d", 1, 0, 1, 0, 0, 0, 0, 1)],
        columns=["source", "timeframe", *_LEDGER],
    )
    current = pd.DataFrame(
        [("ibkr", "1d", 4, 0, 0)],
        columns=["source", "timeframe", "current", "restamp_current", "restamp_written"],
    )
    out = _build_report(ledger, current)
    assert out.loc[("ibkr", "1d"), "unexplained"] == 0
    assert out.loc[("tradier", "1d"), "current"] == 0
    assert out.loc[("tradier", "1d"), "unexplained"] == 0
