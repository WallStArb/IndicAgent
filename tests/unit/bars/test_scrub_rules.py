"""Behavioral tests for the remaining D2a rules (pure functions, no database).

ohlc_invariant, non_positive_price, vol_scaled_jump, stale_print, volume_outlier,
view_disagreement, return_magnitude, gap_before_next, plus ScrubParams.from_apr and
the known-answer no-quarantine fixtures (SPY 2024, MRNA/ALMS seam windows).
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from src.intelligence.bars.scrub_rules import (
    ScrubParams,
    SymbolBars,
    gap_before_next,
    is_quarantine,
    non_positive_price,
    ohlc_invariant,
    return_magnitude,
    run_rules,
    stale_print,
    view_disagreement,
    vol_scaled_jump,
    volume_outlier,
)
from tests.unit.bars._builders import seeded_apr

_FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "bars"


def _params(tf: str = "1d", **apr_overrides: object) -> ScrubParams:
    apr = seeded_apr() | apr_overrides
    return ScrubParams.from_apr(apr, tf)


def _series(
    closes: np.ndarray,
    *,
    tf: str = "1d",
    step_seconds: int = 86_400,
    volume: float = 1_000_000.0,
    ts_seconds: np.ndarray | None = None,
    corporate_action_indices: frozenset[int] = frozenset(),
) -> SymbolBars:
    closes = np.asarray(closes, dtype=np.float64)
    open_ = np.empty_like(closes)
    open_[0] = closes[0]
    open_[1:] = closes[:-1]
    high = np.maximum(open_, closes) * 1.002
    low = np.minimum(open_, closes) * 0.998
    if ts_seconds is None:
        ts_seconds = 1_700_000_000 + np.arange(closes.size, dtype=np.int64) * step_seconds
    return SymbolBars(
        symbol="TEST",
        tf=tf,
        ts_seconds=np.asarray(ts_seconds, dtype=np.int64),
        open=open_,
        high=high,
        low=low,
        close=closes,
        volume=np.full(closes.size, volume, dtype=np.float64),
        corporate_action_indices=corporate_action_indices,
    )


def _walk(n: int, seed: int, sigma: float = 0.01) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.round(100.0 * np.exp(np.cumsum(rng.normal(0.0, sigma, n))), 2)


def _flags(result, rule: str) -> list[int]:
    return sorted(f.index for f in result.flags if f.rule == rule)


# ---------------------------------------------------------------------------
# from_apr
# ---------------------------------------------------------------------------


def test_from_apr_pins_seeded_values_and_quarantine_list():
    params = _params()
    assert params.jump_sigma == 8.0
    assert params.jump_vol_window == 60
    assert params.stale_run_min == 5
    assert params.volume_outlier_mad == 10.0
    assert params.volume_window == 60
    assert params.corroboration_max_clearable_ratio == 2.5
    assert params.view_disagreement_rel == 0.02
    assert params.magnitude_threshold == 10.0
    assert params.neighbor_agreement_threshold == 2.0
    assert params.min_symbols == 4
    assert params.corroboration_window_seconds == 3600
    assert params.max_abs_return == 0.50
    assert params.gap_multiplier == 3
    assert params.gap_max_seconds == 14400
    assert params.quarantine_rules == frozenset(
        {
            "ohlc_invariant",
            "non_positive_price",
            "price_sanity",
            "split_seam",
            "legacy_price_sanity_status",
        }
    )
    # informational until validated (migration 381 seed)
    for informational in ("vol_scaled_jump", "stale_print", "volume_outlier"):
        assert informational not in params.quarantine_rules


def test_from_apr_accepts_config_state_text_values():
    text_form = {key: str(value) for key, value in seeded_apr().items()}
    assert ScrubParams.from_apr(text_form, "1d") == _params()
    assert ScrubParams.from_apr(seeded_apr(), "5m").max_abs_return == 0.25


# ---------------------------------------------------------------------------
# ohlc_invariant / non_positive_price
# ---------------------------------------------------------------------------


def test_ohlc_invariant_flags_each_violation_kind_with_offending_fields():
    bars = _series(_walk(12, seed=1))
    # high below the body but still above low: only the high field offends
    bars.high[3] = (min(bars.open[3], bars.close[3]) + bars.low[3]) / 2
    # low above the body but still below high: only the low field offends
    bars.low[5] = (max(bars.open[5], bars.close[5]) + bars.high[5]) / 2
    bars.high[7] = bars.low[7] - 1.0  # high below low (also below body)
    flags = ohlc_invariant(bars)
    by_index = {f.index: f for f in flags}
    assert sorted(by_index) == [3, 5, 7]
    assert by_index[3].fields == ("high",)
    assert by_index[5].fields == ("low",)
    assert by_index[7].fields == ("high", "low")
    assert all(f.rule == "ohlc_invariant" for f in flags)
    assert all(is_quarantine(f, _params()) for f in flags)


def test_ohlc_invariant_clean_series_flags_nothing():
    assert ohlc_invariant(_series(_walk(50, seed=2))) == []


def test_non_positive_price_names_each_offending_field():
    bars = _series(_walk(12, seed=3))
    bars.open[2] = 0.0
    bars.low[4] = -5.0
    bars.close[6] = 0.0
    flags = non_positive_price(bars)
    by_index = {f.index: f for f in flags}
    assert sorted(by_index) == [2, 4, 6]
    assert by_index[2].fields == ("open",)
    assert by_index[4].fields == ("low",)
    assert by_index[6].fields == ("close",)
    assert all(is_quarantine(f, _params()) for f in flags)


# ---------------------------------------------------------------------------
# vol_scaled_jump
# ---------------------------------------------------------------------------


def test_vol_scaled_jump_flags_unexplained_level_shift_only_at_the_seam():
    closes = _walk(120, seed=4)
    seam = 60
    closes[seam:] = closes[seam:] * 3.0  # unexplained 3x jump, persistent
    unexplained = _series(closes)
    jumps = vol_scaled_jump(unexplained, _params(**{"threshold.bar_scrub.jump_vol_window": 20}))
    seam_flags = [f for f in jumps if f.index == seam]
    assert len(seam_flags) == 1
    assert seam_flags[0].rule == "vol_scaled_jump"
    assert not is_quarantine(seam_flags[0], _params())  # informational until validated

    explained = _series(closes, corporate_action_indices=frozenset({seam}))
    assert [
        f
        for f in vol_scaled_jump(explained, _params(**{"threshold.bar_scrub.jump_vol_window": 20}))
        if f.index == seam
    ] == []


def test_vol_scaled_jump_ignores_real_moves_at_seed_sigma():
    bars = _series(_walk(200, seed=5))  # sigma 0.01 daily walk, window 60
    assert vol_scaled_jump(bars, _params()) == []


# ---------------------------------------------------------------------------
# stale_print
# ---------------------------------------------------------------------------


def test_stale_print_requires_run_length_and_positive_volume():
    closes = _walk(30, seed=6)
    bars = _series(closes)
    # qualifying run: bars 10..14 identical OHLC, volume > 0
    for i in range(10, 15):
        bars.open[i] = bars.open[10]
        bars.high[i] = bars.high[10]
        bars.low[i] = bars.low[10]
        bars.close[i] = bars.close[10]
    # too short: bars 20..23 (4 bars)
    for i in range(20, 24):
        bars.open[i] = bars.open[20]
        bars.high[i] = bars.high[20]
        bars.low[i] = bars.low[20]
        bars.close[i] = bars.close[20]
    # long enough but zero volume: bars 3..7
    for i in range(3, 8):
        bars.open[i] = bars.open[3]
        bars.high[i] = bars.high[3]
        bars.low[i] = bars.low[3]
        bars.close[i] = bars.close[3]
    bars.volume[3:8] = 0.0
    flags = stale_print(bars, _params())
    assert sorted(f.index for f in flags) == [10, 11, 12, 13, 14]
    assert all(f.detail["run_length"] == 5 for f in flags)
    assert all(not is_quarantine(f, _params()) for f in flags)


# ---------------------------------------------------------------------------
# volume_outlier
# ---------------------------------------------------------------------------


def test_volume_outlier_flags_wild_volume_not_flat_windows():
    n = 100
    rng = np.random.default_rng(7)
    closes = _walk(n, seed=8)
    bars = _series(closes)
    bars.volume[:] = 1_000_000.0 * np.exp(rng.normal(0.0, 0.3, n))
    bars.volume[50] = 1e13
    flags = volume_outlier(bars, _params(**{"threshold.bar_scrub.volume_window": 30}))
    assert [f.index for f in flags] == [50]
    assert flags[0].detail["robust_z"] > 10.0
    assert not is_quarantine(flags[0], _params())


def test_volume_outlier_skips_zero_mad_windows():
    bars = _series(_walk(40, seed=9), volume=5.0)  # constant volume: MAD 0
    bars.volume[20] = 9.9
    assert volume_outlier(bars, _params(**{"threshold.bar_scrub.volume_window": 20})) == []


# ---------------------------------------------------------------------------
# view_disagreement
# ---------------------------------------------------------------------------


def test_view_disagreement_flags_unexplained_ratio_steps():
    trades = _walk(60, seed=10)
    adjusted = trades.copy()
    adjusted[30:] = adjusted[30:] * 1.03  # 3% ratio step at 30
    adjusted[50:] = adjusted[50:] * 1.01  # 1% step at 50: below rel
    flags = view_disagreement(trades, adjusted, frozenset(), rel=0.02)
    assert [f.index for f in flags] == [30]
    assert flags[0].rule == "view_disagreement"
    assert flags[0].fields == ("close",)

    explained = view_disagreement(trades, adjusted, frozenset({30}), rel=0.02)
    assert explained == []


# ---------------------------------------------------------------------------
# return_magnitude / gap_before_next (behavioral; parity in test_flag_parity)
# ---------------------------------------------------------------------------


def test_return_magnitude_flags_one_bar_beyond_ceiling():
    closes = _walk(60, seed=11)
    closes[30] = closes[29] * 2.0  # open-to-next-open ln(2) at bar 30
    bars = _series(closes)
    flags = return_magnitude(bars, _params())
    assert 30 in [f.index for f in flags]
    assert all(f.rule == "return_magnitude" for f in flags)
    assert all(not is_quarantine(f, _params()) for f in flags)
    # a 2x move also exceeds the 5m ceiling; a 25% move exceeds neither 1d nor 5m
    small = _series(_walk(60, seed=12))
    assert return_magnitude(small, _params()) == []


def test_gap_before_next_flags_traded_gaps_within_bounds():
    tf_seconds = 300
    ts = []
    cursor = 1_700_000_000
    for gap in (tf_seconds, tf_seconds, 20 * 60, tf_seconds, 10 * 60, tf_seconds):
        ts.append(cursor)
        cursor += gap
    closes = 100.0 + 0.01 * np.arange(len(ts))
    bars = _series(closes, tf="5m", ts_seconds=np.array(ts))
    flags = gap_before_next(bars, _params("5m"))
    # 20-minute gap: > 3 x 300 s and < 14400 s -> flagged; 10-minute gap is not.
    assert [f.index for f in flags] == [2]


def test_run_rules_accumulates_counts_for_every_rule():
    closes = _walk(30, seed=13)
    bars = _series(closes)
    bars.open[2] = 0.0
    for i in range(10, 15):
        bars.open[i] = bars.open[10]
        bars.high[i] = bars.high[10]
        bars.low[i] = bars.low[10]
        bars.close[i] = bars.close[10]
    result = run_rules(bars, _params())
    assert set(result.counts) == {
        "ohlc_invariant",
        "non_positive_price",
        "price_sanity",
        "vol_scaled_jump",
        "stale_print",
        "volume_outlier",
        "return_magnitude",
        "gap_before_next",
    }
    for rule, count in result.counts.items():
        assert count == len([f for f in result.flags if f.rule == rule]), rule
    assert result.counts["non_positive_price"] == 1
    assert result.counts["stale_print"] == 5


# ---------------------------------------------------------------------------
# known-answer fixtures: no quarantine on real moves
# ---------------------------------------------------------------------------


def _load_csv_bars(name: str, symbol: str) -> SymbolBars:
    with (_FIXTURE_DIR / name).open(newline="") as handle:
        rows = [r for r in csv.DictReader(handle) if r["symbol"] == symbol]
    ts = [
        int(np.datetime64(r["timestamp"].replace("Z", "")).astype("datetime64[s]").astype(np.int64))
        for r in rows
    ]
    return SymbolBars(
        symbol=symbol,
        tf=rows[0]["timeframe"],
        ts_seconds=np.array(ts, dtype=np.int64),
        open=np.array([float(r["open"]) for r in rows]),
        high=np.array([float(r["high"]) for r in rows]),
        low=np.array([float(r["low"]) for r in rows]),
        close=np.array([float(r["close"]) for r in rows]),
        volume=np.array([float(r["volume"]) for r in rows]),
    )


def test_spy_2024_1d_raises_no_quarantine_flags():
    bars = _load_csv_bars("spy_1d_2024.csv", "SPY")
    assert bars.close.size == 252
    params = _params("1d")
    result = run_rules(bars, params)
    assert not [f for f in result.flags if is_quarantine(f, params)]


def test_mrna_and_alms_seam_windows_raise_no_quarantine_flags():
    params = _params("1d")
    for symbol in ("MRNA", "ALMS"):
        bars = _load_csv_bars("seam_candidates_mrna_alms.csv", symbol)
        result = run_rules(bars, params)
        assert not [f for f in result.flags if is_quarantine(f, params)], symbol
        # the seam itself IS a large one-bar return; the D-14 port must see it
        # (informational, never quarantine) even though the seeded jump window
        # (60) exceeds these 60/58-bar windows.
        assert result.flags, symbol


def test_synthetic_split_with_recorded_action_raises_no_jump_and_no_quarantine():
    closes = _walk(120, seed=14)
    seam = 60
    closes[seam:] = closes[seam:] / 2.0  # 2:1 split
    params = _params(**{"threshold.bar_scrub.jump_vol_window": 20})
    recorded = _series(closes, corporate_action_indices=frozenset({seam}))
    result = run_rules(recorded, params)
    assert [f for f in result.flags if f.rule == "vol_scaled_jump" and f.index == seam] == []
    assert not [f for f in result.flags if is_quarantine(f, params)]

    unrecorded = _series(closes)
    seam_jumps = [f for f in vol_scaled_jump(unrecorded, params) if f.index == seam]
    assert len(seam_jumps) == 1  # the exclusion is the corporate-action record
