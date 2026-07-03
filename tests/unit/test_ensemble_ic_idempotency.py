"""Unit tests: scored_at run_ts pinning (D-142A-R2, review finding #3).

A single run_ts = datetime.now(UTC) is computed ONCE at the top of
EnsembleICEngine._execute_inner and reused as scored_at for EVERY row produced
during that invocation. This proves:
  1. All rows from one run share an identical scored_at.
  2. event_row_id = content_key(symbol, tf, regime, lookahead) is independent of
     run_ts -- two different run_ts values for the same cell produce the SAME
     event_row_id, so ON CONFLICT (event_row_id, scored_at) DO UPDATE fires
     within a run (retry) and separate runs accumulate distinct vintages.

No DB, no Kafka. Pure Python / datetime.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ensemble_ic_engine import build_ensemble_ic_row
from src.core.agent.base_batch import BaseBatch


def test_all_rows_in_one_run_share_identical_scored_at():
    """Given a list of cell results and one run_ts, every produced row's scored_at matches."""
    run_ts = datetime.now(UTC)
    cells = [
        {
            "symbol": "SPY",
            "tf": "5m",
            "regime": "low_bull",
            "lookahead": "fast",
            "lookahead_bars": 1,
        },
        {
            "symbol": "TLT",
            "tf": "1h",
            "regime": "high_bear",
            "lookahead": "mid",
            "lookahead_bars": 5,
        },
        {
            "symbol": "POOLED",
            "tf": "1d",
            "regime": "mid_neutral",
            "lookahead": "slow",
            "lookahead_bars": 20,
        },
    ]

    rows = [
        build_ensemble_ic_row(**cell, run_ts=run_ts, weight_version="v1", ic_value=0.05)
        for cell in cells
    ]

    scored_ats = {row["scored_at"] for row in rows}
    assert len(scored_ats) == 1, f"Expected one shared scored_at, got {scored_ats}"
    assert scored_ats == {run_ts}


def test_event_row_id_is_independent_of_run_ts():
    """The same cell processed under two different run_ts values yields the same event_row_id."""
    run_ts_a = datetime(2026, 7, 1, tzinfo=UTC)
    run_ts_b = datetime(2026, 7, 8, tzinfo=UTC)
    cell = {
        "symbol": "SPY",
        "tf": "5m",
        "regime": "low_bull",
        "lookahead": "fast",
        "lookahead_bars": 1,
    }

    row_a = build_ensemble_ic_row(**cell, run_ts=run_ts_a, weight_version="v1", ic_value=0.05)
    row_b = build_ensemble_ic_row(**cell, run_ts=run_ts_b, weight_version="v1", ic_value=0.07)

    assert row_a["event_row_id"] == row_b["event_row_id"], (
        "event_row_id must be run_ts-independent so ON CONFLICT (event_row_id, scored_at) "
        "correctly distinguishes within-run retries (same scored_at) from separate "
        "invocations (different scored_at, same event_row_id -> new vintage row)"
    )
    assert row_a["scored_at"] != row_b["scored_at"]


def test_event_row_id_matches_content_key_of_cell_identity():
    """event_row_id must equal BaseBatch.content_key(symbol, tf, regime, lookahead)."""
    run_ts = datetime.now(UTC)
    cell = {
        "symbol": "SPY",
        "tf": "5m",
        "regime": "low_bull",
        "lookahead": "fast",
        "lookahead_bars": 1,
    }
    row = build_ensemble_ic_row(**cell, run_ts=run_ts, weight_version="v1", ic_value=0.05)

    expected_key = BaseBatch.content_key("SPY", "5m", "low_bull", "fast")
    assert row["event_row_id"] == expected_key


def test_different_cells_produce_different_event_row_ids():
    """Distinct (symbol, tf, regime, lookahead) tuples must not collide."""
    run_ts = datetime.now(UTC)
    row_a = build_ensemble_ic_row(
        symbol="SPY",
        tf="5m",
        regime="low_bull",
        lookahead="fast",
        lookahead_bars=1,
        run_ts=run_ts,
        weight_version="v1",
        ic_value=0.05,
    )
    row_b = build_ensemble_ic_row(
        symbol="SPY",
        tf="5m",
        regime="low_bull",
        lookahead="mid",
        lookahead_bars=5,
        run_ts=run_ts,
        weight_version="v1",
        ic_value=0.05,
    )
    assert row_a["event_row_id"] != row_b["event_row_id"]
