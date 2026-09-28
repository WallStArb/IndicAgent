"""D-14 parity tests: the ported bar flags match forward_return_writer's formulas.

forward_return_writer (deleted by phase 186, UD-25) computed, per bar T:

    return_fast = ln(open[T+2] / open[T+1])          -- suspect when > ceiling
    has_gap_before_entry = entry_ts - bar_ts > gap_multiplier * tf_seconds
                           AND entry_ts - bar_ts < gap_max_seconds

The bar rules attribute the same quantities to the entry bar instead of the signal
bar: return_magnitude flags bar i for |ln(open[i+1] / open[i])| (= return_fast at
T = i-1) and gap_before_next flags bar i for the gap to ts[i+1] (= has_gap_before_
entry at T = i). These tests compute the SQL formulas directly and require the same
set of values to be flagged.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from src.intelligence.bars.scrub_rules import (
    ScrubParams,
    SymbolBars,
    gap_before_next,
    return_magnitude,
)
from tests.unit.bars._builders import seeded_apr

_FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "bars"


def _params(tf: str = "1d") -> ScrubParams:
    return ScrubParams.from_apr(seeded_apr(), tf)


def _spiky_opens(n: int, seed: int) -> np.ndarray:
    """Random-walk opens with two persistent level breaks (one up, one down)."""
    rng = np.random.default_rng(seed)
    opens = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, n)))
    opens[40:] = opens[40:] * 2.0  # ln(2) = 0.69: above every ceiling
    opens[80:] = opens[80:] * 0.5  # back down
    return np.round(opens, 4)


def _bars_from_opens(opens: np.ndarray, *, tf: str, step_seconds: int) -> SymbolBars:
    opens = np.asarray(opens, dtype=np.float64)
    ts = 1_700_000_000 + np.arange(opens.size, dtype=np.int64) * step_seconds
    return SymbolBars(
        symbol="TEST",
        tf=tf,
        ts_seconds=ts,
        open=opens,
        close=opens * 1.001,
        high=np.maximum(opens, opens * 1.001) * 1.002,
        low=np.minimum(opens, opens * 1.001) * 0.998,
        volume=np.full(opens.size, 1_000_000.0),
    )


def test_return_magnitude_matches_return_fast_suspect_formula():
    opens = _spiky_opens(120, seed=21)
    for tf, ceiling in (("1d", 0.50), ("5m", 0.25)):
        params = _params(tf)
        assert params.max_abs_return == ceiling, tf
        bars = _bars_from_opens(opens, tf=tf, step_seconds=300 if tf == "5m" else 86_400)
        rule_flagged = {f.index for f in return_magnitude(bars, params)}
        # The SQL formula, computed directly: bar T is suspect when
        # |ln(open[T+2]/open[T+1])| > ceiling. The bar rule flags the entry bar
        # T+1 for the same value.
        sql_suspect = {
            t + 1
            for t in range(opens.size - 2)
            if opens[t + 1] > 0
            and opens[t + 2] > 0
            and abs(float(np.log(opens[t + 2] / opens[t + 1]))) > ceiling
        }
        assert rule_flagged == sql_suspect, tf
        # the injected breaks are flagged at both ceilings: the ratio between
        # bars 39/40 (and 79/80) is the break, attributed to the earlier bar
        assert 39 in rule_flagged and 79 in rule_flagged, tf


def test_gap_before_next_matches_has_gap_before_entry_formula():
    tf_seconds = 300
    gaps = [
        tf_seconds,  # normal spacing
        20 * 60,  # 20 min: > 3 x 300 and < 14400 -> flagged
        10 * 60,  # 10 min: below the multiplier floor
        tf_seconds * 3,  # exactly 3 x tf: not > floor -> not flagged
        tf_seconds * 3 + 1,  # just above the floor -> flagged
        14_399,  # just under the ceiling -> flagged
        14_400,  # exactly gap_max_seconds -> not flagged
        61_200,  # overnight: above the ceiling -> not flagged (known calendar)
    ]
    ts: list[int] = []
    cursor = 1_700_000_000
    for gap in gaps:
        ts.append(cursor)
        cursor += gap
    opens = 100.0 + 0.01 * np.arange(len(ts))
    bars = _bars_from_opens(opens, tf="5m", step_seconds=tf_seconds)
    bars.ts_seconds[:] = ts  # explicit spacing (including the non-uniform gaps)
    rule_flagged = {f.index for f in gap_before_next(bars, _params("5m"))}
    sql_flagged = {i for i, gap in enumerate(gaps[:-1]) if gap > 3 * tf_seconds and gap < 14_400}
    assert rule_flagged == sql_flagged == {1, 4, 5}


def test_gap_before_next_never_fires_at_1d_on_real_weekend_gaps():
    with (_FIXTURE_DIR / "spy_1d_2024.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    ts = np.array(
        [
            int(
                np.datetime64(r["timestamp"].replace("Z", ""))
                .astype("datetime64[s]")
                .astype(np.int64)
            )
            for r in rows
        ],
        dtype=np.int64,
    )
    gaps = ts[1:] - ts[:-1]
    assert gaps.max() > 3 * 86_400  # the fixture really contains weekend gaps
    bars = SymbolBars(
        symbol="SPY",
        tf="1d",
        ts_seconds=ts,
        open=np.array([float(r["open"]) for r in rows]),
        high=np.array([float(r["high"]) for r in rows]),
        low=np.array([float(r["low"]) for r in rows]),
        close=np.array([float(r["close"]) for r in rows]),
        volume=np.array([float(r["volume"]) for r in rows]),
    )
    assert gap_before_next(bars, _params("1d")) == []
