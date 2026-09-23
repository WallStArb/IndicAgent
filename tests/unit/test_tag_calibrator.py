"""Unit tests: TagCalibrator decision-logic (Phase 146, TAG-01).

Six behaviors from RESEARCH.md's Validation Architecture table, each testable against
a pure/importable function without a live DB:
  1. test_skips_self_regression       -- F6.1: symbol == factor_series is excluded
  2. test_run_level_fdr               -- F1: BH-FDR applied once per run, not per-pair
  3. test_expiry_hysteresis           -- F2: consecutive_fails gate before valid_to
  4. test_vol_beta_uses_breadth_vol_proxy -- SPY_REALIZED_VOL path calls the causal proxy
  5. test_skips_definitional_tags     -- definitional tags never measured/written
  6. test_skips_null_factor_series    -- Blocker-2 defensive guard (T-146-11)

No DB, no Kafka, no network. Pure Python / numpy / pandas / monkeypatch.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from services.tag_calibrator import (
    _UPDATE_FAILING_OR_EXPIRE_EMPIRICAL_SQL,
    _UPSERT_EMPIRICAL_SQL,
    MaterialityConfig,
    TagCalibratorConfig,
    _apply_decision,
    _build_factor_return_series,
    _is_self_regression,
    _log_returns,
    _next_evidence,
    apply_run_level_fdr,
    build_control_return_matrix,
    build_factor_series_cache,
    compute_factor_correlations,
    decide_materiality,
    decide_outcome,
    filter_measurable_tag_rows,
    is_materiality_eligible,
    measure_matrix,
    measure_partial_loadings,
    select_control_factor_series,
)

_CONFIG = TagCalibratorConfig(
    fdr_alpha=0.05,
    expiry_consecutive_fails=3,
    discovery_oos_days=63,
    min_sample_n=10,
    hac_max_lag=2,
    half_life_min_days=30,
    half_life_max_days=365,
)


def _synthetic_close(seed: int, n: int = 260, start: float = 100.0) -> pd.Series:
    """Deterministic synthetic daily-close series, geometric-Brownian-ish, with a real
    business-day index so pd.concat(..., join='inner') alignment behaves like live data."""
    rng = np.random.default_rng(seed)
    log_rets = rng.normal(0.0, 0.01, size=n)
    closes = start * np.exp(np.cumsum(log_rets))
    idx = pd.bdate_range("2024-01-02", periods=n)
    return pd.Series(closes, index=idx)


# ---------------------------------------------------------------------------
# 1. test_skips_self_regression (F6.1)
# ---------------------------------------------------------------------------


def test_skips_self_regression():
    """A pair with symbol == factor_series is excluded from the measured matrix, both
    at the single-pair helper level and inside the full measure_matrix loop. Also
    covers the long-short leg-inclusion case (code review finding CR-01): a symbol
    that is one leg of a hyphenated long-short factor series (e.g. HYG vs HYG-IEF)
    must be excluded too, since the "factor" mathematically contains that symbol's
    own return as an additive term -- a plain string-equality check misses this."""
    assert _is_self_regression("TLT", "TLT") is True
    assert _is_self_regression("TLT", "UUP") is False
    assert _is_self_regression("HYG", "HYG-IEF") is True
    assert _is_self_regression("IEF", "HYG-IEF") is True
    assert _is_self_regression("TLT", "HYG-IEF") is False

    price_cache = {"TLT": _synthetic_close(seed=1)}
    measurable_rows = [
        {
            "tag": "rate_sensitive",
            "factor_series": "TLT",
            "lookback_days": 100,
            "loading_threshold": 0.1,
            "half_life_days": 180,
        }
    ]

    measured, n_self_regression, n_insufficient = measure_matrix(
        active_symbols=["TLT"],
        measurable_rows=measurable_rows,
        price_cache=price_cache,
        config=_CONFIG,
        condition_max=1000.0,
        realized_vol_window=20,
        vix_z_window=252,
    )

    assert measured == []
    assert n_self_regression == 1
    assert n_insufficient == 0


# ---------------------------------------------------------------------------
# 2. test_run_level_fdr (F1)
# ---------------------------------------------------------------------------


def test_run_level_fdr(monkeypatch: pytest.MonkeyPatch):
    """apply_run_level_fdr calls apply_bh_fdr exactly ONCE per run over the full
    p-vector, never once per pair -- regression guard against a per-hypothesis loop."""
    call_count = 0
    call_sizes: list[int] = []

    def _counting_apply_bh_fdr(p_values, alpha):
        nonlocal call_count
        call_count += 1
        call_sizes.append(len(p_values))
        reject = [p < 0.01 for p in p_values]
        p_corrected = list(p_values)
        return np.array(reject), np.array(p_corrected)

    monkeypatch.setattr("services.tag_calibrator.apply_bh_fdr", _counting_apply_bh_fdr)

    measured = [
        {"symbol": "TLT", "tag": "rate_sensitive", "p_value": 0.001, "loading": 0.5},
        {"symbol": "UUP", "tag": "dollar_strength", "p_value": 0.4, "loading": 0.1},
        {"symbol": "FXI", "tag": "china_demand", "p_value": 0.6, "loading": 0.05},
    ]

    apply_run_level_fdr(measured, _CONFIG.fdr_alpha)

    assert call_count == 1, "apply_bh_fdr must be called exactly once per run"
    assert call_sizes == [3], "the single call must cover the full p-vector, not a subset"
    assert all("passes_fdr" in m and "bh_adjusted_p" in m for m in measured)


def test_run_level_fdr_empty_measured_is_noop(monkeypatch: pytest.MonkeyPatch):
    """An empty measured list must not call apply_bh_fdr at all (no family to correct)."""
    call_count = 0

    def _counting_apply_bh_fdr(p_values, alpha):
        nonlocal call_count
        call_count += 1
        return np.array([]), np.array([])

    monkeypatch.setattr("services.tag_calibrator.apply_bh_fdr", _counting_apply_bh_fdr)

    apply_run_level_fdr([], _CONFIG.fdr_alpha)

    assert call_count == 0


# ---------------------------------------------------------------------------
# 3. test_expiry_hysteresis (F2)
# ---------------------------------------------------------------------------


def test_expiry_hysteresis():
    """A single failing run against an empirical row increments consecutive_fails but
    does NOT expire (valid_to) until consecutive_fails >= expiry_consecutive_fails."""
    existing_row = {"source": "empirical", "consecutive_fails": 0}

    # Run 1: fails, consecutive_fails 0 -> 1. Must NOT expire (threshold is 3).
    decision_1 = decide_outcome(keep=False, existing_row=existing_row, expiry_consecutive_fails=3)
    assert decision_1["action"] == "increment_fails"
    assert decision_1["consecutive_fails"] == 1

    # Run 2: fails again, consecutive_fails 1 -> 2. Still must NOT expire.
    existing_row["consecutive_fails"] = decision_1["consecutive_fails"]
    decision_2 = decide_outcome(keep=False, existing_row=existing_row, expiry_consecutive_fails=3)
    assert decision_2["action"] == "increment_fails"
    assert decision_2["consecutive_fails"] == 2

    # Run 3: fails a third consecutive time, consecutive_fails 2 -> 3 == threshold.
    # NOW it must expire.
    existing_row["consecutive_fails"] = decision_2["consecutive_fails"]
    decision_3 = decide_outcome(keep=False, existing_row=existing_row, expiry_consecutive_fails=3)
    assert decision_3["action"] == "expire"
    assert decision_3["consecutive_fails"] == 3


def test_expired_row_does_not_re_expire_on_repeated_failure():
    """Once a tag has expired (valid_to already set), a subsequent failing run must be
    a no-op, not another 'expire' decision (code review finding WR-01) -- otherwise
    every later failing run would re-execute the expire SQL and reset valid_to to that
    run's own timestamp, corrupting the recorded "when did this actually expire" time
    into "most recent calibration run" instead."""
    existing_row = {
        "source": "empirical",
        "consecutive_fails": 5,
        "valid_to": "2026-01-01T00:00:00+00:00",
    }
    decision = decide_outcome(keep=False, existing_row=existing_row, expiry_consecutive_fails=3)
    assert decision["action"] == "no_op"
    assert decision["consecutive_fails"] == 5


def test_expiry_hysteresis_keep_resets_consecutive_fails():
    """A keep decision against an existing empirical row resets consecutive_fails to 0
    (a single good run un-does accumulated near-expiry state)."""
    existing_row = {"source": "empirical", "consecutive_fails": 2}
    decision = decide_outcome(keep=True, existing_row=existing_row, expiry_consecutive_fails=3)
    assert decision["action"] == "upsert_empirical"
    assert decision["consecutive_fails"] == 0


def test_human_row_never_expires_only_annotated():
    """A failing measurement against a human-asserted row is never expired -- only
    annotated. Human assertions are seed priors, never auto-expired."""
    existing_row = {"source": "human", "consecutive_fails": 0}
    decision = decide_outcome(keep=False, existing_row=existing_row, expiry_consecutive_fails=1)
    assert decision["action"] == "annotate_contradiction"

    keep_decision = decide_outcome(keep=True, existing_row=existing_row, expiry_consecutive_fails=1)
    assert keep_decision["action"] == "confirm_human"


# ---------------------------------------------------------------------------
# 4. test_vol_beta_uses_breadth_vol_proxy (D-02/T-146-06)
# ---------------------------------------------------------------------------


def test_vol_beta_uses_breadth_vol_proxy(monkeypatch: pytest.MonkeyPatch):
    """The 'SPY_REALIZED_VOL' factor_series path calls factor_math.spy_realized_vol_factor
    (the breadth_vol._compute_vix_pct_rank adapter) -- never a re-derivation."""
    call_args: list[tuple] = []

    def _fake_spy_realized_vol_factor(spy_close, realized_vol_window, vix_z_window):
        call_args.append((spy_close, realized_vol_window, vix_z_window))
        return pd.Series(np.linspace(0.1, 0.9, len(spy_close)), index=spy_close.index)

    monkeypatch.setattr(
        "services.tag_calibrator.spy_realized_vol_factor", _fake_spy_realized_vol_factor
    )

    spy_close = _synthetic_close(seed=42, n=50)
    price_cache = {"SPY": spy_close}

    series, extra_fitted_params = _build_factor_return_series(
        "SPY_REALIZED_VOL", price_cache, realized_vol_window=20, vix_z_window=252
    )

    assert len(call_args) == 1, "spy_realized_vol_factor must be called exactly once"
    called_spy_close, called_rv_window, called_vix_window = call_args[0]
    assert called_spy_close is spy_close
    assert called_rv_window == 20
    assert called_vix_window == 252
    assert extra_fitted_params == 0
    assert series is not None
    # The vol factor is differenced into a change series before being handed to
    # _measure_pair (which always regresses instrument RETURNS against factor_ret) --
    # every other factor_series branch is already return-based, so this keeps the vol
    # sentinel consistent rather than pairing returns against a raw level, which
    # verified live to produce a wrong-signed, below-threshold loading even for VIXY.
    # One row shorter than the input: diff() drops the first point.
    assert len(series) == len(spy_close) - 1
    linear_level = np.linspace(0.1, 0.9, len(spy_close))
    expected_diff = linear_level[1] - linear_level[0]
    assert series.iloc[0] == pytest.approx(expected_diff)


def test_vol_beta_missing_spy_returns_none():
    """No SPY in the price cache -> None, never a crash or a fabricated series."""
    series, extra_fitted_params = _build_factor_return_series(
        "SPY_REALIZED_VOL", {}, realized_vol_window=20, vix_z_window=252
    )
    assert series is None
    assert extra_fitted_params == 0


# ---------------------------------------------------------------------------
# 5. test_skips_definitional_tags
# ---------------------------------------------------------------------------


def test_skips_definitional_tags():
    """Definitional tags (fed_policy, geopolitical, etc.) are never measured or written
    by the calibration loop -- excluded before pass 1 even builds the matrix."""
    vocab_rows = [
        {
            "tag": "fed_policy",
            "factor_series": None,
            "measurement_type": "definitional",
            "lookback_days": 252,
            "loading_threshold": None,
            "half_life_days": 180,
        },
        {
            "tag": "geopolitical",
            "factor_series": None,
            "measurement_type": "definitional",
            "lookback_days": 252,
            "loading_threshold": None,
            "half_life_days": 180,
        },
        {
            "tag": "rate_sensitive",
            "factor_series": "TLT",
            "measurement_type": "beta_regression",
            "lookback_days": 252,
            "loading_threshold": 0.2,
            "half_life_days": 180,
        },
    ]

    measurable_rows, null_factor_tags = filter_measurable_tag_rows(vocab_rows)

    measurable_tags = {row["tag"] for row in measurable_rows}
    assert measurable_tags == {"rate_sensitive"}
    assert "fed_policy" not in measurable_tags
    assert "geopolitical" not in measurable_tags
    assert null_factor_tags == []


# ---------------------------------------------------------------------------
# 6. test_skips_null_factor_series (Blocker-2 / T-146-11)
# ---------------------------------------------------------------------------


def test_skips_null_factor_series():
    """A measurement_type='beta_regression' row with factor_series IS NULL (the
    data-integrity anomaly migration 238 should make impossible) is skipped with a
    warning path taken, never measured, never written, never raises."""
    vocab_rows = [
        {
            "tag": "anomalous_tag",
            "factor_series": None,
            "measurement_type": "beta_regression",
            "lookback_days": 252,
            "loading_threshold": 0.2,
            "half_life_days": 180,
        },
        {
            "tag": "rate_sensitive",
            "factor_series": "TLT",
            "measurement_type": "beta_regression",
            "lookback_days": 252,
            "loading_threshold": 0.2,
            "half_life_days": 180,
        },
    ]

    # No exception raised (this alone would fail the test if filter_measurable_tag_rows
    # attempted to build a return series for the anomalous row).
    measurable_rows, null_factor_tags = filter_measurable_tag_rows(vocab_rows)

    assert null_factor_tags == ["anomalous_tag"]
    measurable_tags = {row["tag"] for row in measurable_rows}
    assert measurable_tags == {"rate_sensitive"}
    assert "anomalous_tag" not in measurable_tags

    # End-to-end: the anomalous tag can never enter measure_matrix's matrix at all,
    # since only measurable_rows (already filtered) is passed to it.
    price_cache = {"TLT": _synthetic_close(seed=7)}
    measured, _n_self_regression, _n_insufficient = measure_matrix(
        active_symbols=["TLT"],
        measurable_rows=measurable_rows,
        price_cache=price_cache,
        config=_CONFIG,
        condition_max=1000.0,
        realized_vol_window=20,
        vix_z_window=252,
    )
    assert all(m["tag"] != "anomalous_tag" for m in measured)


# ---------------------------------------------------------------------------
# 7. compute_factor_correlations / build_factor_series_cache (Phase 174 follow-on)
# ---------------------------------------------------------------------------


def test_build_factor_series_cache_reused_by_measure_matrix():
    """measure_matrix's cache and a standalone build_factor_series_cache() call must
    produce identical series for the same inputs -- they are the same function, not two
    independent implementations (E12-class drift risk)."""
    price_cache = {"TLT": _synthetic_close(seed=1), "UUP": _synthetic_close(seed=2)}
    measurable_rows = [
        {
            "tag": "rate_sensitive",
            "factor_series": "TLT",
            "lookback_days": 100,
            "loading_threshold": 0.1,
            "half_life_days": 180,
        },
        {
            "tag": "dollar_strength",
            "factor_series": "UUP",
            "lookback_days": 100,
            "loading_threshold": 0.1,
            "half_life_days": 180,
        },
    ]
    cache = build_factor_series_cache(measurable_rows, price_cache, 20, 252)
    assert set(cache.keys()) == {"TLT", "UUP"}
    assert cache["TLT"][0] is not None
    assert cache["UUP"][0] is not None


def test_compute_factor_correlations_canonical_ordering_and_no_self_pairs():
    """Every unordered pair appears exactly once (factor_a < factor_b alphabetically),
    and no factor is ever paired with itself."""
    cache = {
        "TLT": (_synthetic_close(seed=1).pct_change().dropna(), 0),
        "UUP": (_synthetic_close(seed=2).pct_change().dropna(), 0),
        "GLD": (_synthetic_close(seed=3).pct_change().dropna(), 0),
    }
    rows = compute_factor_correlations(cache, min_sample_n=10)
    pairs = {(r["factor_a"], r["factor_b"]) for r in rows}
    assert len(pairs) == 3  # C(3,2), never 6 -- no (A,B)+(B,A) duplicates
    for a, b in pairs:
        assert a < b  # canonical ordering
        assert a != b  # no self-pairs


def test_compute_factor_correlations_skips_none_and_thin_series():
    """A factor whose return series is None (missing price data) never appears in any
    pair, and a pair with fewer than min_sample_n overlapping observations is dropped."""
    long_series = _synthetic_close(seed=1, n=260).pct_change().dropna()
    short_series = long_series.iloc[:5]  # too few overlapping observations
    cache = {
        "TLT": (long_series, 0),
        "MISSING": (None, 0),
        "THIN": (short_series, 0),
    }
    rows = compute_factor_correlations(cache, min_sample_n=10)
    involved = {r["factor_a"] for r in rows} | {r["factor_b"] for r in rows}
    assert "MISSING" not in involved
    assert "THIN" not in involved


def test_compute_factor_correlations_known_correlation_value():
    """A pair built from the identical underlying series (perfectly correlated) must
    report correlation == 1.0, and n_obs matches the aligned overlap exactly."""
    base = _synthetic_close(seed=7, n=100).pct_change().dropna()
    cache = {"A": (base, 0), "B": (base.copy(), 0)}
    rows = compute_factor_correlations(cache, min_sample_n=10)
    assert len(rows) == 1
    assert rows[0]["factor_a"] == "A"
    assert rows[0]["factor_b"] == "B"
    assert rows[0]["correlation"] == pytest.approx(1.0)
    assert rows[0]["n_obs"] == len(base)


# ---------------------------------------------------------------------------
# 8. MaterialityConfig / select_control_factor_series / build_control_return_matrix
#    (Phase 175 Task 1)
# ---------------------------------------------------------------------------


def test_materiality_config_from_apr_defaults():
    """MaterialityConfig.from_apr({}) returns the eleven seeded defaults (P175-04)."""
    materiality = MaterialityConfig.from_apr({})
    assert materiality.min_partial_loading == 0.35
    assert materiality.min_partial_loading_ci_low == 0.20
    assert materiality.min_incremental_r2 == 0.05
    assert materiality.min_sample_n == 756
    assert materiality.sign_stability_window_days == 252
    assert materiality.sign_stability_window_count == 4
    assert materiality.min_sign_stable_windows == 3
    assert materiality.null_arm_alpha == 0.05
    assert materiality.null_arm_draws == 1000
    assert materiality.null_arm_seed == 42
    assert materiality.control_factor_series == ("SPY", "TLT", "HYG-IEF", "UUP")


def test_select_control_factor_series_excludes_own_factor_series():
    """A control equal to the tag's own factor_series is excluded even when the
    candidate symbol has nothing to do with it -- residualizing a factor against
    itself would drive the partial loading identically to zero."""
    controls = ["SPY", "TLT", "HYG-IEF", "UUP"]
    assert select_control_factor_series("SPY", "equity_beta", controls) == [
        "TLT",
        "HYG-IEF",
        "UUP",
    ]


def test_select_control_factor_series_excludes_self_regression_leg():
    """A control the candidate symbol is itself a leg of is excluded (HYG is one leg
    of HYG-IEF), in addition to the tag's own factor_series (TLT here)."""
    controls = ["SPY", "TLT", "HYG-IEF", "UUP"]
    assert select_control_factor_series("HYG", "TLT", controls) == ["SPY", "UUP"]


def test_select_control_factor_series_empty_when_all_excluded():
    """Every control excluded -> empty list, caller treats as unmeasurable."""
    assert select_control_factor_series("SPY", "SPY", ["SPY"]) == []


def test_build_control_return_matrix_none_when_instrument_ret_none():
    factor = pd.Series([1.0, 2.0, 3.0])
    controls = [pd.Series([1.0, 2.0, 3.0])]
    assert build_control_return_matrix(None, factor, controls) is None


def test_build_control_return_matrix_none_when_factor_ret_none():
    instrument = pd.Series([1.0, 2.0, 3.0])
    controls = [pd.Series([1.0, 2.0, 3.0])]
    assert build_control_return_matrix(instrument, None, controls) is None


def test_build_control_return_matrix_none_when_controls_empty():
    instrument = pd.Series([1.0, 2.0, 3.0])
    factor = pd.Series([1.0, 2.0, 3.0])
    assert build_control_return_matrix(instrument, factor, []) is None


def test_build_control_return_matrix_none_when_control_series_missing():
    instrument = pd.Series([1.0, 2.0, 3.0])
    factor = pd.Series([1.0, 2.0, 3.0])
    controls = [pd.Series([1.0, 2.0, 3.0]), None]
    assert build_control_return_matrix(instrument, factor, controls) is None


def test_build_control_return_matrix_inner_joins_and_aligns():
    """The candidate, factor, and every retained control are aligned on a shared
    index via a single inner join -- all three outputs share an identical length,
    with no NaN, even when one control's series is shorter than the others."""
    idx = pd.bdate_range("2024-01-02", periods=10)
    instrument = pd.Series(np.arange(10.0), index=idx)
    factor = pd.Series(np.arange(10.0) * 2.0, index=idx)
    control_a = pd.Series(np.arange(10.0) * 3.0, index=idx)
    control_b = pd.Series(np.arange(8.0) * 4.0, index=idx[:8])  # shorter -> forces inner join

    result = build_control_return_matrix(instrument, factor, [control_a, control_b])
    assert result is not None
    instrument_arr, factor_arr, controls_2d = result
    assert len(instrument_arr) == 8
    assert len(factor_arr) == 8
    assert controls_2d.shape == (8, 2)
    assert not np.isnan(instrument_arr).any()
    assert not np.isnan(factor_arr).any()
    assert not np.isnan(controls_2d).any()


# ---------------------------------------------------------------------------
# 9. measure_partial_loadings / decide_materiality / is_materiality_eligible
#    (Phase 175 Task 2)
# ---------------------------------------------------------------------------

_SMALL_MATERIALITY = MaterialityConfig(
    min_partial_loading=0.0,
    min_partial_loading_ci_low=0.0,
    min_incremental_r2=0.0,
    min_sample_n=50,
    sign_stability_window_days=20,
    sign_stability_window_count=3,
    min_sign_stable_windows=1,
    null_arm_alpha=0.5,
    null_arm_draws=30,
    null_arm_seed=42,
    control_factor_series=("TLT",),
)


def test_measure_partial_loadings_determinism_and_seed_sensitivity():
    """Two runs over the same inputs produce identical null_arm_p_value (per-pair
    deterministic seeding); differing ONLY null_arm_seed produces at least one
    differing null_arm_p_value (proving the APR-backed seed is actually mixed
    in, not an unused field)."""
    price_cache = {
        "AAA": _synthetic_close(seed=1, n=300),
        "SPY": _synthetic_close(seed=2, n=300),
        "TLT": _synthetic_close(seed=3, n=300),
    }
    kept_measurements = [{"symbol": "AAA", "tag": "rate_sensitive"}]
    factor_series_by_tag = {"rate_sensitive": "SPY"}
    factor_series_cache = build_factor_series_cache(
        [{"tag": "rate_sensitive", "factor_series": "SPY"}], price_cache, 20, 252
    )
    control_series_by_name = build_factor_series_cache(
        [{"factor_series": "TLT"}], price_cache, 20, 252
    )
    instrument_full_ret = {sym: _log_returns(close) for sym, close in price_cache.items()}

    def _run(materiality):
        return measure_partial_loadings(
            kept_measurements,
            factor_series_by_tag,
            factor_series_cache,
            control_series_by_name,
            instrument_full_ret,
            materiality,
            hac_max_lag=2,
            condition_max=1000.0,
        )

    rows_1, n_no_controls_1, n_insufficient_1 = _run(_SMALL_MATERIALITY)
    rows_2, _n_no_controls_2, _n_insufficient_2 = _run(_SMALL_MATERIALITY)

    assert len(rows_1) == 1
    assert n_no_controls_1 == 0
    assert n_insufficient_1 == 0
    assert rows_1[0]["null_arm_p_value"] == rows_2[0]["null_arm_p_value"]

    materiality_diff_seed = dataclasses.replace(_SMALL_MATERIALITY, null_arm_seed=999)
    rows_3, _n_no_controls_3, _n_insufficient_3 = _run(materiality_diff_seed)
    assert rows_3[0]["null_arm_p_value"] != rows_1[0]["null_arm_p_value"]


def test_measure_partial_loadings_skips_when_no_controls_retained():
    """A control equal to the tag's own factor_series is excluded; with only one
    configured control this leaves zero retained -> n_no_controls, not
    n_insufficient_sample."""
    price_cache = {
        "AAA": _synthetic_close(seed=1, n=300),
        "SPY": _synthetic_close(seed=2, n=300),
    }
    materiality = dataclasses.replace(_SMALL_MATERIALITY, control_factor_series=("SPY",))
    kept_measurements = [{"symbol": "AAA", "tag": "rate_sensitive"}]
    factor_series_by_tag = {"rate_sensitive": "SPY"}
    factor_series_cache = build_factor_series_cache(
        [{"tag": "rate_sensitive", "factor_series": "SPY"}], price_cache, 20, 252
    )
    control_series_by_name = build_factor_series_cache(
        [{"factor_series": "SPY"}], price_cache, 20, 252
    )
    instrument_full_ret = {sym: _log_returns(close) for sym, close in price_cache.items()}

    rows, n_no_controls, n_insufficient = measure_partial_loadings(
        kept_measurements,
        factor_series_by_tag,
        factor_series_cache,
        control_series_by_name,
        instrument_full_ret,
        materiality,
        hac_max_lag=2,
        condition_max=1000.0,
    )
    assert rows == []
    assert n_no_controls == 1
    assert n_insufficient == 0


def test_measure_partial_loadings_skips_when_below_min_sample_n():
    """A short-history pair aligns successfully but produces fewer observations
    than min_sample_n -> n_insufficient_sample, never n_no_controls."""
    price_cache = {
        "AAA": _synthetic_close(seed=1, n=40),
        "SPY": _synthetic_close(seed=2, n=40),
        "TLT": _synthetic_close(seed=3, n=40),
    }
    materiality = dataclasses.replace(_SMALL_MATERIALITY, min_sample_n=1000)
    kept_measurements = [{"symbol": "AAA", "tag": "rate_sensitive"}]
    factor_series_by_tag = {"rate_sensitive": "SPY"}
    factor_series_cache = build_factor_series_cache(
        [{"tag": "rate_sensitive", "factor_series": "SPY"}], price_cache, 20, 252
    )
    control_series_by_name = build_factor_series_cache(
        [{"factor_series": "TLT"}], price_cache, 20, 252
    )
    instrument_full_ret = {sym: _log_returns(close) for sym, close in price_cache.items()}

    rows, n_no_controls, n_insufficient = measure_partial_loadings(
        kept_measurements,
        factor_series_by_tag,
        factor_series_cache,
        control_series_by_name,
        instrument_full_ret,
        materiality,
        hac_max_lag=2,
        condition_max=1000.0,
    )
    assert rows == []
    assert n_no_controls == 0
    assert n_insufficient == 1


_MATERIALITY_DEFAULTS = MaterialityConfig(
    min_partial_loading=0.35,
    min_partial_loading_ci_low=0.20,
    min_incremental_r2=0.05,
    min_sample_n=756,
    sign_stability_window_days=252,
    sign_stability_window_count=4,
    min_sign_stable_windows=3,
    null_arm_alpha=0.05,
    null_arm_draws=1000,
    null_arm_seed=42,
    control_factor_series=("SPY", "TLT", "HYG-IEF", "UUP"),
)


def _passing_pass4_row() -> dict:
    return {
        "materiality_sample_n": 1000,
        "partial_loading": 0.5,
        "partial_loading_ci_low": 0.3,
        "incremental_r2": 0.1,
        "sign_stable_windows": 3,
        "sign_stable_windows_total": 3,
        "null_arm_passes_fdr": True,
    }


def test_decide_materiality_all_conditions_pass():
    assert decide_materiality(_passing_pass4_row(), _MATERIALITY_DEFAULTS) is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("materiality_sample_n", 100),
        ("partial_loading", 0.1),
        ("partial_loading_ci_low", 0.05),
        ("incremental_r2", 0.01),
        ("sign_stable_windows", 1),
        ("null_arm_passes_fdr", False),
    ],
)
def test_decide_materiality_each_condition_fails_independently(field, value):
    """Flipping exactly one field of an otherwise-passing row flips the decision
    to False, one parametrized case per condition."""
    row = _passing_pass4_row()
    row[field] = value
    assert decide_materiality(row, _MATERIALITY_DEFAULTS) is False


def test_decide_materiality_sign_stability_sliding_bar():
    """A deliberate discrete step, not a gradual slide: 3-of-3 PASSES, 3-of-4
    PASSES, 2-of-3 FAILS. The agreement bar is STRICTER for shorter-history
    symbols (fewer evaluable windows), not looser."""
    row_3_of_3 = _passing_pass4_row()
    row_3_of_3["sign_stable_windows"] = 3
    row_3_of_3["sign_stable_windows_total"] = 3
    assert decide_materiality(row_3_of_3, _MATERIALITY_DEFAULTS) is True

    row_3_of_4 = _passing_pass4_row()
    row_3_of_4["sign_stable_windows"] = 3
    row_3_of_4["sign_stable_windows_total"] = 4
    assert decide_materiality(row_3_of_4, _MATERIALITY_DEFAULTS) is True

    row_2_of_3 = _passing_pass4_row()
    row_2_of_3["sign_stable_windows"] = 2
    row_2_of_3["sign_stable_windows_total"] = 3
    assert decide_materiality(row_2_of_3, _MATERIALITY_DEFAULTS) is False


def test_decide_materiality_nan_field_returns_false():
    row = _passing_pass4_row()
    row["partial_loading"] = float("nan")
    assert decide_materiality(row, _MATERIALITY_DEFAULTS) is False


def test_decide_materiality_missing_field_returns_false():
    row = _passing_pass4_row()
    del row["incremental_r2"]
    assert decide_materiality(row, _MATERIALITY_DEFAULTS) is False


def test_decide_materiality_does_not_read_discovery_state():
    """R-04: a row with discovery_state='pending_oos' and an otherwise-passing
    statistical profile still returns True -- decide_materiality is the
    statistical gate only."""
    row = _passing_pass4_row()
    row["discovery_state"] = "pending_oos"
    assert decide_materiality(row, _MATERIALITY_DEFAULTS) is True


def test_is_materiality_eligible_requires_all_three_gates():
    base = {"passes_materiality": True, "discovery_state": "confirmed", "valid_to": None}
    assert is_materiality_eligible(base) is True

    not_statistical = dict(base, passes_materiality=False)
    assert is_materiality_eligible(not_statistical) is False

    not_confirmed = dict(base, discovery_state="pending_oos")
    assert is_materiality_eligible(not_confirmed) is False

    expired = dict(base, valid_to="2026-01-01T00:00:00+00:00")
    assert is_materiality_eligible(expired) is False


# ---------------------------------------------------------------------------
# 10. _next_evidence / _apply_decision persistence + todo-125 discovery-OOS gate
#    (Phase 175 Task 3)
# ---------------------------------------------------------------------------


class _FakeConn:
    """Minimal asyncpg.Connection stand-in: records every execute() call's SQL
    text and positional params without touching a real database."""

    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    async def execute(self, sql, *params):
        self.calls.append((sql, params))


def test_next_evidence_fresh_discovery_is_pending_oos():
    """_next_evidence for a row with no prior first_measured_at returns
    discovery_state == 'pending_oos' (unchanged Phase 146 behavior, now also
    written to a typed column by Task 3)."""
    run_ts = datetime(2026, 1, 1, tzinfo=UTC)
    evidence = _next_evidence(
        existing_row=None, run_ts=run_ts, discovery_oos_days=63, clamped_half_life=180
    )
    assert evidence["discovery_state"] == "pending_oos"
    assert evidence["first_measured_at"] == run_ts.isoformat()


def test_next_evidence_confirmed_after_oos_window_elapses():
    """_next_evidence for a row whose first_measured_at is discovery_oos_days + 1
    days before run_ts returns discovery_state == 'confirmed'."""
    first_measured_at = datetime(2026, 1, 1, tzinfo=UTC)
    run_ts = first_measured_at + timedelta(days=64)  # discovery_oos_days=63, +1 day
    existing_row = {"evidence": {"first_measured_at": first_measured_at.isoformat()}}
    evidence = _next_evidence(
        existing_row=existing_row, run_ts=run_ts, discovery_oos_days=63, clamped_half_life=180
    )
    assert evidence["discovery_state"] == "confirmed"


def test_discovery_oos_gate_blocks_fresh_discovery():
    """todo 125's named gap, now closed: a fresh discovery whose statistical
    profile fully passes decide_materiality is NOT is_materiality_eligible,
    because its discovery_state is 'pending_oos' -- the same row with
    discovery_state='confirmed' IS eligible, with no change to any statistical
    field."""
    run_ts = datetime(2026, 1, 1, tzinfo=UTC)
    evidence = _next_evidence(
        existing_row=None, run_ts=run_ts, discovery_oos_days=63, clamped_half_life=180
    )
    assert evidence["discovery_state"] == "pending_oos"

    pass4_row = _passing_pass4_row()
    assert decide_materiality(pass4_row, _MATERIALITY_DEFAULTS) is True

    fresh_discovery_row = {
        "passes_materiality": True,
        "discovery_state": evidence["discovery_state"],
        "valid_to": None,
    }
    assert is_materiality_eligible(fresh_discovery_row) is False

    confirmed_row = dict(fresh_discovery_row, discovery_state="confirmed")
    assert is_materiality_eligible(confirmed_row) is True


async def test_apply_decision_upsert_binds_all_eleven_pass4_params_or_none():
    """The upsert_empirical/insert_discovery path binds all eleven new Pass 4
    columns through the SAME UPSERT statement; None for every one of the first
    nine Pass 4 fields when the pair has no Pass 4 row."""
    run_ts = datetime(2026, 1, 1, tzinfo=UTC)
    measurement = {
        "symbol": "AAA",
        "tag": "rate_sensitive",
        "loading": 0.5,
        "p_value": 0.01,
        "bh_adjusted_p": 0.02,
        "passes_fdr": True,
        "sample_n": 100,
        "half_life_days": 180,
    }
    decision = {"action": "upsert_empirical", "consecutive_fails": 0}

    conn_no_pass4 = _FakeConn()
    await _apply_decision(conn_no_pass4, run_ts, _CONFIG, measurement, None, decision, None)
    assert len(conn_no_pass4.calls) == 1
    sql, params = conn_no_pass4.calls[0]
    assert sql is _UPSERT_EMPIRICAL_SQL
    assert len(params) == 21
    assert params[10:19] == (None,) * 9

    pass4 = {
        "partial_loading": 0.42,
        "partial_loading_ci_low": 0.30,
        "incremental_r2": 0.08,
        "sign_stable_windows": 3,
        "sign_stable_windows_total": 4,
        "null_arm_p_value": 0.01,
        "null_arm_bh_p": 0.02,
        "materiality_sample_n": 900,
        "passes_materiality": True,
    }
    conn_with_pass4 = _FakeConn()
    await _apply_decision(conn_with_pass4, run_ts, _CONFIG, measurement, None, decision, pass4)
    _sql, params_with_pass4 = conn_with_pass4.calls[0]
    assert params_with_pass4[10:19] == (0.42, 0.30, 0.08, 3, 4, 0.01, 0.02, 900, True)


async def test_apply_decision_increment_fails_clears_passes_materiality():
    """A pair that falls to the increment_fails path has passes_materiality
    written false in the SQL text -- never left stale on a still-active row."""
    run_ts = datetime(2026, 1, 1, tzinfo=UTC)
    measurement = {
        "symbol": "AAA",
        "tag": "rate_sensitive",
        "loading": 0.1,
        "p_value": 0.5,
        "bh_adjusted_p": 0.6,
        "passes_fdr": False,
        "sample_n": 100,
    }
    decision = {"action": "increment_fails", "consecutive_fails": 1}
    conn = _FakeConn()
    await _apply_decision(
        conn, run_ts, _CONFIG, measurement, {"consecutive_fails": 0}, decision, None
    )
    assert len(conn.calls) == 1
    sql, _params = conn.calls[0]
    assert sql is _UPDATE_FAILING_OR_EXPIRE_EMPIRICAL_SQL
    assert "passes_materiality = false" in sql


async def test_apply_decision_confirm_human_and_no_op_write_nothing():
    """confirm_human and no_op perform zero writes to instrument_tags -- human
    seed priors are never touched, unaffected by the new pass4 parameter."""
    run_ts = datetime(2026, 1, 1, tzinfo=UTC)
    measurement = {
        "symbol": "AAA",
        "tag": "rate_sensitive",
        "loading": 0.5,
        "p_value": 0.01,
        "bh_adjusted_p": 0.02,
        "passes_fdr": True,
        "sample_n": 100,
    }
    conn = _FakeConn()
    await _apply_decision(
        conn,
        run_ts,
        _CONFIG,
        measurement,
        {"source": "human"},
        {"action": "confirm_human", "consecutive_fails": 0},
        None,
    )
    await _apply_decision(
        conn, run_ts, _CONFIG, measurement, None, {"action": "no_op", "consecutive_fails": 0}, None
    )
    assert conn.calls == []
