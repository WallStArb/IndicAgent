"""Unit tests for the capture completeness rule (todo 528, R6): the join wiring
(`_build_report`) and the pure arithmetic (`_classify`); the ledger SQL and printing stay
untested here."""

from __future__ import annotations

import pandas as pd

from scripts.ops.bars.ops_capture_completeness import _build_report, _classify

_COLS = [
    "served",
    "written",
    "removed",
    "refused_archived",
    "archive_served",
    "canonical",
    "archive",
]
_LEDGER_COLS = [
    "source",
    "timeframe",
    "destination",
    "outcome",
    "served",
    "written",
    "removed",
    "refused_archived",
]


def _frame(**overrides: int) -> pd.DataFrame:
    base = dict.fromkeys(_COLS, 0)
    base.update(overrides)
    return pd.DataFrame([base], columns=_COLS).astype("int64")


def _ledger(rows: list[dict]) -> pd.DataFrame:
    base = {col: 0 for col in _LEDGER_COLS}
    rows = [{**base, **row} for row in rows]
    return pd.DataFrame(rows, columns=_LEDGER_COLS)


def _store(label: str, **counts: int) -> pd.DataFrame:
    """A one-(source, timeframe) store frame; counts keyed by column name."""
    return pd.DataFrame(
        [{**{"source": "alpaca", "timeframe": "5m", label: 0}, **counts}]
    ).set_index(["source", "timeframe"])


def test_a_fully_archived_refusal_is_neither_loss_nor_remainder():
    # 100 served: 90 authored, 10 refused and archived; the archive holds the 10.
    report = _classify(
        _frame(served=100, written=90, refused_archived=10, canonical=90, archive=10)
    )
    row = report.iloc[0]
    assert row["refused_bars"] == 0
    assert row["unexplained"] == 0


def test_an_unarchived_refusal_stays_a_documented_remainder():
    # 100 served: 90 authored, 10 refused and not routed; the column separates it
    # from loss (the pre-528 behavior).
    report = _classify(_frame(served=100, written=90, canonical=90))
    row = report.iloc[0]
    assert row["refused_bars"] == 10
    assert row["unexplained"] == 0


def test_a_claimed_archive_row_absent_from_the_store_is_loss_once():
    # The refusal claims 10 archived, the archive holds 5: the missing 5 are loss,
    # counted once (the archive side), not again on the grid side.
    report = _classify(_frame(served=100, written=90, refused_archived=10, canonical=90, archive=5))
    row = report.iloc[0]
    assert row["refused_bars"] == 0
    assert row["unexplained"] == 5


def test_true_grid_loss_is_unexplained():
    report = _classify(_frame(served=100, written=90, canonical=85))
    row = report.iloc[0]
    assert row["refused_bars"] == 10
    assert row["unexplained"] == 5


def test_a_shorter_ledger_than_the_store_is_preledger_not_loss():
    # Legacy corpus: the archive holds rows the ledger never covered.
    report = _classify(_frame(archive_served=0, archive=40))
    row = report.iloc[0]
    assert row["preledger_rows"] == 40
    assert row["unexplained"] == 0


def test_the_join_wiring_keeps_a_cross_destination_refusal_archive_count():
    """The refusal's n_archived rides rows whose destination is the grid, but the
    archived bars sit in the archive store: the refused bucket must survive the
    destination partitioning (the report would KeyError on the column otherwise)."""
    ledger = _ledger(
        [
            {
                "source": "alpaca",
                "timeframe": "5m",
                "destination": "market_data_ohlcv",
                "outcome": "applied",
                "served": 90,
                "written": 90,
            },
            {
                "source": "alpaca",
                "timeframe": "5m",
                "destination": "market_data_ohlcv",
                "outcome": "refused",
                "served": 10,
                "refused_archived": 10,
            },
        ]
    )
    report = _build_report(
        ledger,
        _store("canonical", canonical=90),
        _store("archive", archive=10),
    )
    row = report.iloc[0]
    assert row["served"] == 100 and row["canonical"] == 90 and row["archive"] == 10
    assert row["refused_archived"] == 10
    assert row["refused_bars"] == 0
    assert row["unexplained"] == 0


def test_refused_archive_destination_rows_stay_out_of_the_cross_bucket():
    """A refusal whose destination is the archive itself: its served bars already count
    in archive_served and its upserted rows return to the same store, so its
    n_archived must NOT join the cross-destination adjustment (that would double-count)."""
    ledger = _ledger(
        [
            {
                "source": "alpaca",
                "timeframe": "5m",
                "destination": "archive",
                "outcome": "refused",
                "served": 10,
                "refused_archived": 10,
            }
        ]
    )
    report = _build_report(
        ledger,
        _store("canonical", canonical=0),
        _store("archive", archive=10),
    )
    row = report.iloc[0]
    assert row["archive_served"] == 10
    assert row["refused_archived"] == 0
    assert row["unexplained"] == 0
