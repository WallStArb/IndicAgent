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

import numpy as np
import pandas as pd
import pytest

from services.tag_calibrator import (
    TagCalibratorConfig,
    _build_factor_return_series,
    _is_self_regression,
    apply_run_level_fdr,
    decide_outcome,
    filter_measurable_tag_rows,
    measure_matrix,
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
    assert len(series) == len(spy_close)


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
