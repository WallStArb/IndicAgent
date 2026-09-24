"""Tests for scripts/analysis/portfolio_covariance_weighting_diagnostic.py.

The instrument-level primitives it imports are tested in tests/unit/test_portfolio_weighting.py.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.analysis.portfolio_covariance_weighting_diagnostic import (
    causal_regime_labels,
    main,
    run_walk_forward,
)


def test_causal_regime_labels_bull_when_price_above_trailing_sma():
    # Strictly increasing series: every post-warmup point sits above its own trailing SMA.
    idx = pd.date_range("2026-01-01", periods=10)
    close = pd.Series(np.arange(1.0, 11.0), index=idx)
    labels = causal_regime_labels(close, window=5)
    # First 5 (warmup) are None; from index 5 on, price > trailing SMA -> "bull".
    assert labels.iloc[:5].isna().all()
    assert (labels.iloc[5:] == "bull").all()


def test_causal_regime_labels_bear_when_price_below_trailing_sma():
    idx = pd.date_range("2026-01-01", periods=10)
    close = pd.Series(np.arange(10.0, 0.0, -1.0), index=idx)
    labels = causal_regime_labels(close, window=5)
    assert (labels.iloc[5:] == "bear").all()


def test_causal_regime_labels_never_uses_same_bar_close():
    # A single-bar spike at t should not change t's OWN label -- the label at t is derived from
    # the SMA of bars strictly before t (1-bar shift), so it must be knowable before t's close
    # prints. Verify by comparing to a manually shifted SMA.
    idx = pd.date_range("2026-01-01", periods=8)
    close = pd.Series([1, 2, 3, 4, 5, 100, 7, 8], index=idx, dtype=float)
    labels = causal_regime_labels(close, window=3)
    manual_sma = close.rolling(3).mean().shift(1)
    expected = np.where(close > manual_sma, "bull", "bear")
    expected_masked = pd.Series(expected, index=idx).where(manual_sma.notna())
    pd.testing.assert_series_equal(labels, expected_masked, check_names=False)


def _synthetic_inputs(n_days: int = 520, n_symbols: int = 4, seed: int = 7):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n_days, freq="B")
    symbols = [f"SYM{i}" for i in range(n_symbols)]

    log_ret = rng.normal(0.0002, 0.01, size=(n_days, n_symbols))
    close = pd.DataFrame(100.0 * np.exp(np.cumsum(log_ret, axis=0)), index=idx, columns=symbols)
    alpha = pd.DataFrame(rng.normal(0.0, 1.0, size=(n_days, n_symbols)), index=idx, columns=symbols)
    # forward_returns.return_fast at bar t approximates the next bar's log return -- synthetic
    # stand-in consistent with "1-bar-ahead executable return" for this smoke test.
    fwd = pd.DataFrame(log_ret, index=idx, columns=symbols).shift(-1)
    # cost_hurdle: constant small per-instrument friction proxy, mirroring alpha_events.cost_hurdle.
    cost_hurdle = pd.DataFrame(0.0005, index=idx, columns=symbols)
    spy = pd.Series(100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.008, n_days))), index=idx)
    return close, alpha, fwd, cost_hurdle, spy


def test_run_walk_forward_smoke_produces_all_four_arms_and_diagnostics():
    close, alpha, fwd, cost_hurdle, spy = _synthetic_inputs()
    report = run_walk_forward(close, alpha, fwd, cost_hurdle, spy)

    assert set(report["arms"].keys()) == {
        "equal_weight",
        "ic_proportional",
        "vol_normalized",
        "mean_variance",
    }
    for arm_name, arm_report in report["arms"].items():
        assert "rebalance_steps" in arm_report
        assert len(arm_report["rebalance_steps"]) > 0
        first_step = arm_report["rebalance_steps"][0]
        assert set(first_step.keys()) >= {
            "date",
            "weights",
            "gross_exposure",
            "net_exposure",
            "effective_n",
            "turnover",
            "realized_return",
            "cost",
            "net_realized_return",
        }
        assert "aggregate" in arm_report
        assert "unconditional" in arm_report["aggregate"]
        assert "mean_net_realized_return" in arm_report["aggregate"]["unconditional"]
        assert "bull" in arm_report["aggregate"] or "bear" in arm_report["aggregate"]

    assert report["mean_variance_fallback_count"] >= 0
    assert report["n_rebalance_steps"] == len(report["arms"]["equal_weight"]["rebalance_steps"])


def test_run_walk_forward_cost_reduces_net_return_below_gross():
    # With a strictly positive cost_hurdle and nonzero turnover, net_realized_return must never
    # exceed gross realized_return for any step -- cost only ever subtracts.
    close, alpha, fwd, cost_hurdle, spy = _synthetic_inputs()
    report = run_walk_forward(close, alpha, fwd, cost_hurdle, spy)
    for arm_report in report["arms"].values():
        for step in arm_report["rebalance_steps"]:
            assert step["net_realized_return"] <= step["realized_return"] + 1e-12
            assert step["cost"] >= 0.0


def test_run_walk_forward_never_uses_embargoed_forward_return():
    # Regression guard for the embargo requirement: construct a fwd_return frame where the
    # LAST two rows are populated with an extreme outlier value that must never influence any
    # refit's IC calibration if the embargo is respected (those two rows fall inside the
    # embargo window relative to the final refit boundary).
    close, alpha, fwd, cost_hurdle, spy = _synthetic_inputs(n_days=520)
    fwd_poisoned = fwd.copy()
    fwd_poisoned.iloc[-2:] = 999.0  # would blow up IC/mu if leaked into calibration
    report_clean = run_walk_forward(close, alpha, fwd, cost_hurdle, spy)
    report_poisoned = run_walk_forward(close, alpha, fwd_poisoned, cost_hurdle, spy)
    # The LAST refit's calibration (ic_shrunk logged per refit) must be identical between the
    # two runs -- the poisoned rows fall inside the embargo window and must never be read.
    last_refit_clean = report_clean["refits"][-1]["ic_shrunk"]
    last_refit_poisoned = report_poisoned["refits"][-1]["ic_shrunk"]
    np.testing.assert_allclose(last_refit_clean, last_refit_poisoned)


def test_run_walk_forward_handles_active_symbol_set_changing_between_refits():
    # Regression guard: instrument_covariance's own trailing-coverage filter is point-in-time
    # (per the spec), so active_symbols is EXPECTED to differ across refits -- a symbol with
    # good coverage at refit 1 can legitimately drop out by refit 2. A prior version of this
    # code tracked prev_weights as a bare positional array, which either crashed (symbol count
    # changed) or silently misaligned turnover/cost against the wrong symbol (same count,
    # different membership) when this happened.
    close, alpha, fwd, cost_hurdle, spy = _synthetic_inputs(n_days=900, n_symbols=4)
    # SYM3 has real price data only through day 560. The first refit (~day 504, trailing
    # window ~[0, 502]) sees it on every row and admits it; by the second refit (~day 756,
    # window ~[252, 754]) it covers ~60% of the window, below _MIN_COVERAGE_FRACTION, and must
    # drop out of active_symbols.
    close = close.copy()
    close.loc[close.index[560:], "SYM3"] = np.nan

    report = run_walk_forward(close, alpha, fwd, cost_hurdle, spy)  # must not raise

    ic_prop_steps = report["arms"]["ic_proportional"]["rebalance_steps"]
    symbol_sets = [frozenset(step["weights"].keys()) for step in ic_prop_steps]
    # The active symbol set actually changed at some point during the run -- otherwise this
    # test would pass vacuously without ever exercising the entry/exit path being guarded.
    assert len(set(symbol_sets)) > 1

    # Find the first step where SYM3 drops out of the active set after having been in it --
    # that step's turnover must account for fully unwinding SYM3's previous weight, not silently
    # drop it (the bug this test guards against).
    drop_step_idx = next(
        i
        for i in range(1, len(ic_prop_steps))
        if "SYM3" in symbol_sets[i - 1] and "SYM3" not in symbol_sets[i]
    )
    prior_sym3_weight = ic_prop_steps[drop_step_idx - 1]["weights"]["SYM3"]
    drop_step_turnover = ic_prop_steps[drop_step_idx]["turnover"]
    assert drop_step_turnover >= abs(prior_sym3_weight) - 1e-9


def test_main_requires_symbols_argument():
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 2  # argparse's own usage-error exit code


def test_run_walk_forward_completes_with_scattered_gaps_across_symbols():
    """Realistic data has isolated missing bars on different days for different symbols.
    Each refit must still fit (joint admission drops the worst-covered symbol if needed)
    rather than abort the run."""
    close, alpha, fwd, cost_hurdle, spy = _synthetic_inputs(n_days=900, n_symbols=4)
    close = close.copy()
    rng = np.random.default_rng(5)
    for col in close.columns:
        close.loc[close.index[rng.choice(900, size=12, replace=False)], col] = np.nan

    report = run_walk_forward(close, alpha, fwd, cost_hurdle, spy)

    assert report["n_rebalance_steps"] > 0
    assert all(len(r["symbols"]) >= 2 for r in report["refits"])
