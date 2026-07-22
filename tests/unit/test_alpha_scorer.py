"""Unit tests: AlphaScorer (SCORE-01) decile bucketing + monotonicity diagnostic.

Pure-function tests against services.alpha_scorer.score_cells -- no DB, no Kafka, mirroring
tests/unit/test_ensemble_ic_gate.py's shape. score_cells is the aggregation core AlphaScorer
calls per-cohort with a 2-tuple group_key into evaluate_frame_gate (STEP 0 verified against
the live source, services/counterfactual_tracker.py evaluate_frame_gate line ~954 -- the
helper only accepts a 2-tuple group key; a 4-tuple raises ValueError).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from services.alpha_scorer import score_cells

# bootstrap_max_n=1 forces evaluate_frame_gate's analytic-CLT branch (any cohort with >=2
# day-clusters exceeds this floor) instead of scipy.stats.bootstrap's BCa resampling --
# keeps these unit tests fast and fully deterministic while exercising the exact same
# evaluate_frame_gate call path AlphaScorer uses in production.
_FAST_BOOTSTRAP_KWARGS = {
    "bootstrap_max_n": 1,
    "bootstrap_batch": 1000,
    "bootstrap_random_state": 42,
}


def _make_decile_rows(
    symbol: str, tf: str, regime: str, decile: int, n: int, mean_pnl: float, noise: float = 0.01
) -> list[dict]:
    """n synthetic rows for one (symbol, tf, regime, decile) cell, spread across ceil(n/2)
    distinct calendar days so evaluate_frame_gate's day-clustered bootstrap has >=2 clusters."""
    rows = []
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(n):
        day = i % max(n // 2, 1)
        pnl = mean_pnl + (noise if i % 2 == 0 else -noise)
        rows.append(
            {
                "symbol": symbol,
                "tf": tf,
                "regime": regime,
                "alpha_score_decile": decile,
                "bar_ts": base + timedelta(days=day, hours=i),
                "cluster_id": (base + timedelta(days=day)).date(),
                "pnl_r": pnl,
            }
        )
    return rows


def test_buckets_deciles_and_filters_min_strategy_n():
    """AlphaScorer buckets alpha_frames into (symbol, tf, regime, decile) cells and
    filters out cells with sample_n < alpha.scoring.min_strategy_n.

    Also exercises the per-cohort 2-tuple evaluate_frame_gate call path and asserts the
    remap (verdict["tf"] -> alpha_score_decile) lands the decile in the correct output
    column -- the group-key round-trip is asserted here, not just eyeballed.
    """
    min_strategy_n = 30

    # Cohort A (SPY, 1h, bull): decile 1 has 35 rows (clears the floor), decile 2 has only
    # 5 rows (below the floor -- must be dropped, not written).
    rows = _make_decile_rows("SPY", "1h", "bull", decile=1, n=35, mean_pnl=0.1)
    rows += _make_decile_rows("SPY", "1h", "bull", decile=2, n=5, mean_pnl=0.2)

    # Cohort B (QQQ, 1h, bull): same decile number (1) as cohort A's surviving cell, but a
    # DIFFERENT symbol -- proves decile assignment/grouping is per-cohort, not merged
    # across cohorts that happen to share a decile number.
    rows += _make_decile_rows("QQQ", "1h", "bull", decile=1, n=35, mean_pnl=-0.05)

    result = score_cells(rows, min_strategy_n=min_strategy_n, **_FAST_BOOTSTRAP_KWARGS)

    # Only the two >=30-row cells survive; the 5-row cell is dropped entirely.
    assert len(result) == 2
    for cell in result:
        assert cell["sample_n"] >= min_strategy_n

    by_symbol = {cell["symbol"]: cell for cell in result}
    assert set(by_symbol) == {"SPY", "QQQ"}

    # Round-trip assertion: verdict["tf"] (evaluate_frame_gate's first group_key element,
    # the decile) must land in the alpha_score_decile output column, not the tf column.
    assert by_symbol["SPY"]["alpha_score_decile"] == 1
    assert by_symbol["SPY"]["tf"] == "1h"
    assert by_symbol["QQQ"]["alpha_score_decile"] == 1
    assert by_symbol["QQQ"]["tf"] == "1h"
    # regime comes through the remap (verdict["regime"], group_key's second element).
    assert by_symbol["SPY"]["regime"] == "bull"
    assert by_symbol["QQQ"]["regime"] == "bull"

    # win_rate reflects each cell's own pnl_r sign distribution.
    assert by_symbol["SPY"]["win_rate"] == 1.0  # mean_pnl=0.1, noise=+/-0.01 -- always positive
    assert by_symbol["QQQ"]["win_rate"] == 0.0  # mean_pnl=-0.05 -- always negative


def test_ic_alpha_score_corr_monotonic():
    """ic_alpha_score_corr (correlation between alpha_score_decile rank and
    mean_pnl_r) is computed correctly as a monotonicity diagnostic -- DIAGNOSTIC-ONLY,
    not a gate threshold (alpha.scoring.min_ic_alpha_score_corr, migration 248).
    """
    min_strategy_n = 30

    # Monotone cohort: mean pnl_r increases linearly with decile -> high positive corr.
    monotone_rows = []
    for decile in range(1, 11):
        monotone_rows += _make_decile_rows(
            "SPY", "5m", "mid_bull", decile=decile, n=30, mean_pnl=decile * 0.05, noise=0.001
        )

    # Flat/non-monotonic cohort: mean pnl_r alternates independent of decile rank -> near-zero
    # corr (pre-computed via scipy.stats.spearmanr against this exact decile/mean pairing:
    # statistic == -0.174, well within the |corr| < 0.3 "near zero" bound asserted below).
    flat_rows = []
    for decile in range(1, 11):
        mean_pnl = 0.06 if decile % 2 == 1 else 0.05
        flat_rows += _make_decile_rows(
            "QQQ", "5m", "mid_bull", decile=decile, n=30, mean_pnl=mean_pnl, noise=0.001
        )

    monotone_result = score_cells(
        monotone_rows, min_strategy_n=min_strategy_n, **_FAST_BOOTSTRAP_KWARGS
    )
    flat_result = score_cells(flat_rows, min_strategy_n=min_strategy_n, **_FAST_BOOTSTRAP_KWARGS)

    assert len(monotone_result) == 10
    assert len(flat_result) == 10

    # ic_alpha_score_corr is a per-cohort value -- identical across every cell in the cohort.
    monotone_corrs = {cell["ic_alpha_score_corr"] for cell in monotone_result}
    flat_corrs = {cell["ic_alpha_score_corr"] for cell in flat_result}
    assert len(monotone_corrs) == 1
    assert len(flat_corrs) == 1

    monotone_corr = monotone_corrs.pop()
    flat_corr = flat_corrs.pop()

    assert monotone_corr > 0.9
    assert abs(flat_corr) < 0.3
