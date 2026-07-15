from __future__ import annotations

import numpy as np
import pytest

from scripts.analysis.regime_boundary_churn_check import (
    WINDOW_STEP_MULTIPLIER,
    classify_timestamp_adjacency,
    derive_boundary_window,
)


def test_derive_boundary_window_scales_with_median_step():
    # Diffs: [0.01, 0.03, 0.01, 0.03, 0.01] -> median of all 5 diffs = 0.01 (three 0.01s,
    # two 0.03s) -> window = 2.0 * 0.01 = 0.02.
    series = np.array([0.10, 0.11, 0.14, 0.15, 0.18, 0.19])
    window = derive_boundary_window(series, multiplier=2.0)
    assert abs(window - 0.02) < 1e-9


def test_derive_boundary_window_empty_or_singleton_is_zero():
    assert derive_boundary_window(np.array([])) == 0.0
    assert derive_boundary_window(np.array([0.5])) == 0.0


def test_derive_boundary_window_default_multiplier_constant():
    series = np.array([0.0, 0.02, 0.04, 0.06])
    assert derive_boundary_window(series) == 0.02 * WINDOW_STEP_MULTIPLIER


_TIERS1 = [("low", 0.33), ("mid", 0.67), ("high", float("inf"))]
_TIERS2 = [("bear", 0.40), ("neutral", 0.60), ("bull", float("inf"))]


def test_classify_not_adjacent_when_far_from_any_boundary():
    result = classify_timestamp_adjacency(0.50, 0.50, _TIERS1, _TIERS2, window1=0.02, window2=0.02)
    assert result.actual_label == "mid_neutral"
    assert not result.axis1_adjacent
    assert not result.axis2_adjacent
    assert result.neighbor_labels == ()


def test_classify_single_axis_adjacent():
    # sig1=0.335 is within 0.02 of the 0.33 boundary; sig2=0.50 is far from both breadth cuts.
    result = classify_timestamp_adjacency(0.335, 0.50, _TIERS1, _TIERS2, window1=0.02, window2=0.02)
    assert result.actual_label == "mid_neutral"
    assert result.axis1_adjacent
    assert not result.axis2_adjacent
    assert result.neighbor_labels == ("low_neutral",)


def test_classify_corner_case_both_axes_adjacent():
    # sig1=0.335 near the low/mid vix cut; sig2=0.605 near the neutral/bull breadth cut.
    result = classify_timestamp_adjacency(
        0.335, 0.605, _TIERS1, _TIERS2, window1=0.02, window2=0.02
    )
    assert result.actual_label == "mid_bull"
    assert result.axis1_adjacent and result.axis2_adjacent
    assert set(result.neighbor_labels) == {"low_bull", "mid_neutral", "low_neutral"}


def test_classify_narrow_middle_tier_double_adjacency_on_one_axis():
    # sig1=0.50 sits in "mid" but within 0.20 of BOTH the 0.33 and 0.67 boundaries when
    # window1 is wide -- both neighbors on axis 1 must be reported, not just one.
    result = classify_timestamp_adjacency(0.50, 0.50, _TIERS1, _TIERS2, window1=0.20, window2=0.02)
    assert result.actual_label == "mid_neutral"
    assert result.axis1_adjacent
    assert set(result.neighbor_labels) == {"low_neutral", "high_neutral"}


from scripts.analysis.regime_boundary_churn_check import align_weight_vectors, score_bar


def test_align_weight_vectors_unions_and_zero_pads():
    a = {"momentum_z_fast": 0.6, "obv_z": 0.4}
    b = {"momentum_z_fast": 0.5, "range_pct": -0.5}
    aligned = align_weight_vectors(a, b)
    assert aligned.feature_names == ("momentum_z_fast", "obv_z", "range_pct")
    assert aligned.signed_weights_a.tolist() == [0.6, 0.4, 0.0]
    assert aligned.signed_weights_b.tolist() == [0.5, 0.0, -0.5]


def test_score_bar_matches_manual_dot_product():
    feature_values = {"momentum_z_fast": 2.0, "obv_z": -1.0, "range_pct": 0.5}
    feature_names = ("momentum_z_fast", "obv_z", "range_pct")
    signed_weights = np.array([0.6, 0.4, 0.0])
    score = score_bar(feature_values, feature_names, signed_weights)
    expected = 2.0 * 0.6 + -1.0 * 0.4 + 0.5 * 0.0
    # Tolerance, not ==: np.dot and plain Python arithmetic aren't guaranteed
    # bit-identical (e.g. FMA on some platforms).
    assert abs(score - expected) < 1e-9


def test_score_bar_treats_missing_and_non_finite_as_zero():
    feature_values = {"momentum_z_fast": float("nan"), "obv_z": -1.0}
    feature_names = ("momentum_z_fast", "obv_z", "range_pct")
    signed_weights = np.array([0.6, 0.4, -0.5])
    score = score_bar(feature_values, feature_names, signed_weights)
    expected = 0.0 * 0.6 + -1.0 * 0.4 + 0.0 * -0.5
    assert abs(score - expected) < 1e-9


from scripts.analysis.regime_boundary_churn_check import compute_cell_verdict


def test_verdict_passes_when_both_criteria_met():
    verdict = compute_cell_verdict(
        regime_group="equity",
        tf="5m",
        n_boundary_adjacent_timestamps=600,
        n_total_timestamps=10_000,  # 6% >= 5% gate
        effect_sizes=np.array([0.30, 0.32, 0.35, 0.40]),  # median 0.335
        clean_noise_floor=0.20,  # 0.335 >= 1.5 * 0.20 = 0.30
        n_untrained_neighbor_bars=5,
        n_scored_bars=595,
    )
    assert verdict.boundary_adjacent_fraction == 0.06
    assert verdict.criterion_1_pass is True
    assert verdict.criterion_2_pass is True
    assert verdict.overall_pass is True


def test_verdict_fails_on_low_boundary_fraction():
    verdict = compute_cell_verdict(
        regime_group="equity",
        tf="1d",
        n_boundary_adjacent_timestamps=10,
        n_total_timestamps=10_000,  # 0.1% < 5% gate
        effect_sizes=np.array([0.50, 0.55]),
        clean_noise_floor=0.10,
        n_untrained_neighbor_bars=0,
        n_scored_bars=10,
    )
    assert verdict.criterion_1_pass is False
    assert verdict.overall_pass is False


def test_verdict_fails_when_effect_indistinguishable_from_noise():
    verdict = compute_cell_verdict(
        regime_group="equity",
        tf="1h",
        n_boundary_adjacent_timestamps=600,
        n_total_timestamps=10_000,
        effect_sizes=np.array([0.10, 0.11, 0.12]),  # median 0.11
        clean_noise_floor=0.20,  # 0.11 < 1.5 * 0.20 = 0.30
        n_untrained_neighbor_bars=0,
        n_scored_bars=600,
    )
    assert verdict.criterion_1_pass is True
    assert verdict.criterion_2_pass is False
    assert verdict.overall_pass is False


def test_verdict_handles_zero_noise_floor_without_dividing_by_zero():
    verdict = compute_cell_verdict(
        regime_group="equity",
        tf="1h",
        n_boundary_adjacent_timestamps=600,
        n_total_timestamps=10_000,
        effect_sizes=np.array([0.10]),
        clean_noise_floor=0.0,
        n_untrained_neighbor_bars=0,
        n_scored_bars=600,
    )
    assert verdict.criterion_2_pass is False


def test_verdict_handles_no_boundary_adjacent_timestamps():
    verdict = compute_cell_verdict(
        regime_group="equity",
        tf="1d",
        n_boundary_adjacent_timestamps=0,
        n_total_timestamps=10_000,
        effect_sizes=np.array([]),
        clean_noise_floor=0.10,
        n_untrained_neighbor_bars=0,
        n_scored_bars=0,
    )
    assert verdict.median_effect_size == 0.0
    assert verdict.overall_pass is False


from scripts.analysis.regime_boundary_churn_check import (
    _CLEAN_NOISE_FLOOR_SQL,
    _REGIME_SERIES_SQL,
    _SIGNED_WEIGHTS_SQL_TEMPLATE,
    fetch_signed_weights_by_regime,
    load_equity_tiers,
)


def test_regime_series_sql_scopes_to_equity_group_and_orders_by_ts():
    assert "regime_group = 'equity'" in _REGIME_SERIES_SQL
    assert "ORDER BY ts" in _REGIME_SERIES_SQL
    assert "regime_prob_vector" in _REGIME_SERIES_SQL


def test_signed_weights_sql_joins_ic_sign_via_lateral_on_exact_selected_value():
    sql = _SIGNED_WEIGHTS_SQL_TEMPLATE.format(ic_input_column="ic_shrunk")
    assert "ensemble_weights" in sql
    assert "LATERAL" in sql
    assert "fic.lookahead_bars = ew.lookahead_bars" in sql
    assert "symbol = 'UNIVERSE'" in sql
    # The actual fix: match the exact stored value ensemble_trainer.py copied verbatim --
    # not select via training_window_end recency, since production's real selection
    # criterion is highest quality_weight, not most recent. training_window_end DESC is
    # still present, but only as a defensive tiebreak after the exact-match filter (in case
    # two different training windows ever produce a bit-identical statistic by coincidence),
    # never as the primary selection mechanism.
    assert "fic.ic_shrunk = ew.ic_sharpe" in sql
    assert "ORDER BY fic.training_window_end DESC" in sql


class _FakeConnSignedWeights:
    """Fake asyncpg.Connection returning canned rows for fetch_signed_weights_by_regime."""

    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, sql, *args):
        return self._rows


@pytest.mark.asyncio
async def test_fetch_signed_weights_by_regime_skips_null_ic_sign_and_counts_it():
    rows = [
        {"regime": "mid_neutral", "feature_name": "momentum_z_fast", "weight": 0.6, "ic_sign": 1},
        {"regime": "mid_neutral", "feature_name": "obv_z", "weight": 0.4, "ic_sign": None},
    ]
    conn = _FakeConnSignedWeights(rows)
    weights_by_regime, n_skipped = await fetch_signed_weights_by_regime(
        conn, "5m", "run_x", "ic_shrunk"
    )
    assert weights_by_regime == {"mid_neutral": {"momentum_z_fast": 0.6}}
    assert n_skipped == 1


def test_clean_noise_floor_sql_excludes_regime_transition_bars():
    # The whole point: the noise floor must NOT include the churn effect it's the
    # baseline for -- only consecutive same-symbol bars where regime_label held constant.
    assert "regime_label = prev_regime_label" in _CLEAN_NOISE_FLOOR_SQL
    assert "PARTITION BY" in _CLEAN_NOISE_FLOOR_SQL
    assert "regime_group = 'equity'" in _CLEAN_NOISE_FLOOR_SQL


class _FakeConfigService:
    """Records every key requested via get(), always returns the caller's default."""

    def __init__(self):
        self.requested_keys: list[str] = []

    async def get(self, key: str, default):
        self.requested_keys.append(key)
        return default


@pytest.mark.asyncio
async def test_load_equity_tiers_reads_the_live_equity_regime_apr_namespace():
    # Namespace is 'alpha.equity_regime' (the equity group's params_prefix in
    # cross_sectional_regime_model.py's group config) -- NOT 'alpha.regime.equity', a
    # namespace that doesn't exist in config_state at all (confirmed live 2026-07-15).
    # Uses get() (async), not get_sync() -- get_sync() only reads an already-warmed cache
    # and would silently return the default on a cold cache, masking the real bug this
    # test guards against.
    cfg = _FakeConfigService()
    await load_equity_tiers(cfg)
    assert cfg.requested_keys == [
        "alpha.equity_regime.vix_low_pct",
        "alpha.equity_regime.vix_high_pct",
        "alpha.equity_regime.breadth_bear",
        "alpha.equity_regime.breadth_bull",
    ]


from scripts.analysis.regime_boundary_churn_check import allocate_sample_sizes


def test_allocate_sample_sizes_proportional_to_boundary_counts():
    counts = {"5m": 8_000, "15m": 1_500, "1h": 400, "1d": 100}
    allocation = allocate_sample_sizes(counts, target_total=10_000, hard_cap=20_000)
    total = sum(counts.values())
    assert allocation["5m"] == round(10_000 * 8_000 / total)
    assert allocation["1d"] == round(10_000 * 100 / total)
    assert sum(allocation.values()) <= 10_000 + 4  # rounding slack, not a hard cap breach


def test_allocate_sample_sizes_respects_hard_cap():
    counts = {"5m": 100_000, "15m": 100, "1h": 100, "1d": 100}
    allocation = allocate_sample_sizes(counts, target_total=50_000, hard_cap=20_000)
    assert allocation["5m"] == 20_000


def test_allocate_sample_sizes_never_exceeds_available_count():
    counts = {"5m": 30, "15m": 1_500, "1h": 400, "1d": 100}
    allocation = allocate_sample_sizes(counts, target_total=50_000, hard_cap=20_000)
    assert allocation["5m"] == 30


from datetime import UTC, datetime

from scripts.analysis.regime_boundary_churn_check import fetch_sampled_feature_vectors


class _FakeConnSampledFeatureVectors:
    """Fake asyncpg.Connection: fetchrow() returns a canned symbol count, fetch() returns
    canned rows and records the SQL + timestamp list it was called with."""

    def __init__(self, n_symbols: int, rows: list[dict]):
        self._n_symbols = n_symbols
        self._rows = rows
        self.fetch_calls: list[tuple[str, tuple]] = []

    async def fetchrow(self, sql, *args):
        return {"n": self._n_symbols}

    async def fetch(self, sql, *args):
        self.fetch_calls.append((sql, args))
        return self._rows


_TS = [datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, 0, 5, tzinfo=UTC)]


@pytest.mark.asyncio
async def test_fetch_sampled_feature_vectors_avoids_order_by_random_in_sql():
    # The whole point of the fix: no expensive full-relation sort in the actual query.
    conn = _FakeConnSampledFeatureVectors(n_symbols=2, rows=[{"symbol": "SPY", "bar_ts": _TS[0]}])
    await fetch_sampled_feature_vectors(conn, "5m", _TS, ("momentum_z_fast",), 10)
    assert len(conn.fetch_calls) == 1
    sql, args = conn.fetch_calls[0]
    assert "ORDER BY random()" not in sql
    assert "LIMIT" not in sql


@pytest.mark.asyncio
async def test_fetch_sampled_feature_vectors_truncates_to_n_in_python():
    rows = [{"symbol": f"S{i}", "bar_ts": _TS[0]} for i in range(5)]
    conn = _FakeConnSampledFeatureVectors(n_symbols=5, rows=rows)
    result = await fetch_sampled_feature_vectors(conn, "5m", _TS, ("momentum_z_fast",), 3)
    assert len(result) == 3


@pytest.mark.asyncio
async def test_fetch_sampled_feature_vectors_handles_empty_timestamps_and_zero_n():
    conn = _FakeConnSampledFeatureVectors(n_symbols=5, rows=[])
    assert await fetch_sampled_feature_vectors(conn, "5m", [], ("momentum_z_fast",), 10) == []
    assert await fetch_sampled_feature_vectors(conn, "5m", _TS, ("momentum_z_fast",), 0) == []


from scripts.analysis.regime_boundary_churn_check import score_sampled_bars


def test_score_sampled_bars_scores_trained_pairs_and_counts_untrained():
    # Two sampled bars at the same boundary-adjacent ts, different symbols.
    sampled_rows = [
        {"symbol": "SPY", "bar_ts": "t1", "momentum_z_fast": 2.0, "obv_z": -1.0},
        {"symbol": "QQQ", "bar_ts": "t1", "momentum_z_fast": 1.0, "obv_z": 1.0},
        {"symbol": "IWM", "bar_ts": "t2", "momentum_z_fast": 0.5, "obv_z": 0.5},
    ]
    adjacency_by_ts = {
        "t1": type("A", (), {"actual_label": "mid_neutral", "neighbor_labels": ("low_neutral",)})(),
        # t2's neighbor regime ("high_neutral") has no trained weights below.
        "t2": type(
            "A", (), {"actual_label": "mid_neutral", "neighbor_labels": ("high_neutral",)}
        )(),
    }
    weights_by_regime = {
        "mid_neutral": {"momentum_z_fast": 0.6, "obv_z": 0.4},
        "low_neutral": {"momentum_z_fast": 0.3, "obv_z": 0.2},
        # 'high_neutral' deliberately absent -- untrained neighbor for t2.
    }

    effect_sizes, n_untrained = score_sampled_bars(sampled_rows, adjacency_by_ts, weights_by_regime)

    # t1 (2 symbols) scored against both mid_neutral and low_neutral weights; t2 excluded
    # from effect_sizes (untrained neighbor) but counted.
    assert len(effect_sizes) == 2
    assert n_untrained == 1

    spy_actual = 2.0 * 0.6 + -1.0 * 0.4
    spy_neighbor = 2.0 * 0.3 + -1.0 * 0.2
    expected_spy_effect = abs(spy_actual - spy_neighbor)
    # Tolerance, not exact `in` membership: np.dot vs plain Python arithmetic
    # aren't guaranteed bit-identical.
    assert any(abs(e - expected_spy_effect) < 1e-9 for e in effect_sizes)


def test_score_sampled_bars_excludes_bars_with_untrained_actual_regime_too():
    sampled_rows = [{"symbol": "SPY", "bar_ts": "t1", "momentum_z_fast": 2.0}]
    adjacency_by_ts = {
        "t1": type("A", (), {"actual_label": "high_bull", "neighbor_labels": ("mid_bull",)})()
    }
    weights_by_regime = {"mid_bull": {"momentum_z_fast": 0.5}}  # 'high_bull' never trained

    effect_sizes, n_untrained = score_sampled_bars(sampled_rows, adjacency_by_ts, weights_by_regime)
    assert len(effect_sizes) == 0
    assert n_untrained == 1


from scripts.analysis.regime_boundary_churn_check import run_diagnostic


class _FakeConfigServiceForDiagnostic:
    async def get(self, key, default):
        return default


class _FakeConnForRunDiagnostic:
    """Routes conn.fetch()/fetchrow() by inspecting the SQL text -- exercises
    run_diagnostic's real control flow end-to-end without a live database.
    Regression guard for exactly the class of bug already caught in Task 6:
    fetch_signed_weights_by_regime's signature drifting out from under run_diagnostic's
    call site (argument count/order changed, tuple return unpacked wrong, etc.) would
    raise here instead of only being caught by a manual live-DB smoke test.
    """

    def __init__(self):
        self.fetch_calls: list[str] = []

    async def fetch(self, sql, *args):
        self.fetch_calls.append(sql)
        if "regime_prob_vector" in sql:
            # Only tf='5m' (3rd positional arg) gets synthetic rows; other tfs get none
            # so run_diagnostic's `if len(series) < 2: continue` skips them (Task 8's own
            # early-exit path, exercised for free).
            if args[2] == "5m":
                return [
                    {"ts": "t1", "regime_label": "mid_neutral", "sig1": 0.50, "sig2": 0.50},
                    {"ts": "t2", "regime_label": "mid_neutral", "sig1": 0.50, "sig2": 0.50},
                ]
            return []
        if "ensemble_weights" in sql:
            return []  # no trained regimes -- matches the current live DB state
        if "ensemble_alpha" in sql:
            return []
        raise AssertionError(f"unexpected SQL in fake conn.fetch: {sql[:80]}")

    async def fetchrow(self, sql, *args):
        raise AssertionError(
            "fetchrow should not be called: no boundary-adjacent bars in this fixture"
        )


@pytest.mark.asyncio
async def test_run_diagnostic_completes_and_returns_one_verdict_per_tf_with_data():
    conn = _FakeConnForRunDiagnostic()
    cfg = _FakeConfigServiceForDiagnostic()
    verdicts = await run_diagnostic(conn, cfg, "run_x")
    assert len(verdicts) == 1  # only '5m' had >= 2 regime rows
    v = verdicts[0]
    assert v.tf == "5m"
    assert v.n_total_timestamps == 2
    # sig1=sig2=0.50 for both rows -- far from every tier boundary, so no boundary-adjacent
    # timestamps and both gate criteria correctly fail (matches the shape of a real run
    # against the current live DB, where ensemble_weights/ensemble_alpha are also empty).
    assert v.n_boundary_adjacent_timestamps == 0
    assert v.overall_pass is False
