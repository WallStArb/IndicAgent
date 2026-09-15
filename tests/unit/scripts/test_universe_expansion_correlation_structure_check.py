"""Unit coverage for the three pure functions in
scripts/analysis/universe_expansion_correlation_structure_check.py (Phase 174 Plan 14, D-09/D-10):
correlation_structure(), evaluate_d10_gate(), residualize_against_factor().

Every case below drives synthetic frames built in-process against data with an analytically
known answer, or constructs the gate's input dicts directly -- no database, no network, no live
IBKR. This proves the statistics themselves, independent of whatever the live corpus happens to
contain, and pins both D-10 thresholds at their exact boundaries so a future edit to either one
fails this suite (the mechanism that makes the pre-registration enforceable, not aspirational).
"""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

import numpy as np
import pandas as pd
import pytest

from scripts.analysis.universe_expansion_correlation_structure_check import (  # noqa: E402
    _D10_GATE_HIGH_BEAR_MAX,
    _D10_GATE_UNCONDITIONAL_MAX,
    correlation_structure,
    evaluate_d10_gate,
    residualize_against_factor,
)

_SEED = 42


def _make_independent_returns(
    n_symbols: int = 30, n_obs: int = 2000, seed: int = _SEED
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    data = rng.standard_normal((n_obs, n_symbols))
    columns = [f"SYM{i:02d}" for i in range(n_symbols)]
    index = pd.date_range("2010-01-01", periods=n_obs, freq="D")
    return pd.DataFrame(data, index=index, columns=columns)


def _make_single_factor_returns(
    n_symbols: int, n_obs: int, loading: float, seed: int = _SEED
) -> pd.DataFrame:
    """r_i = b * f + sqrt(1 - b^2) * e_i, f and e_i independent standard normal -- population
    pairwise correlation is exactly b^2.
    """
    rng = np.random.default_rng(seed)
    factor = rng.standard_normal(n_obs)
    idio = rng.standard_normal((n_obs, n_symbols))
    data = loading * factor[:, None] + np.sqrt(1 - loading**2) * idio
    columns = [f"SYM{i:02d}" for i in range(n_symbols)]
    index = pd.date_range("2010-01-01", periods=n_obs, freq="D")
    return pd.DataFrame(data, index=index, columns=columns)


def _make_perfectly_correlated_returns(n_symbols: int = 10, n_obs: int = 500) -> pd.DataFrame:
    rng = np.random.default_rng(_SEED)
    series = rng.standard_normal(n_obs)
    columns = [f"SYM{i:02d}" for i in range(n_symbols)]
    index = pd.date_range("2010-01-01", periods=n_obs, freq="D")
    data = np.tile(series[:, None], (1, n_symbols))
    return pd.DataFrame(data, index=index, columns=columns)


def _make_two_block_returns(
    block_size: int = 15, n_obs: int = 1500, seed: int = _SEED
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    factor_a = rng.standard_normal(n_obs)
    factor_b = rng.standard_normal(n_obs)  # independent of factor_a
    loading = 0.7
    idio_a = rng.standard_normal((n_obs, block_size))
    idio_b = rng.standard_normal((n_obs, block_size))
    block_a = loading * factor_a[:, None] + np.sqrt(1 - loading**2) * idio_a
    block_b = loading * factor_b[:, None] + np.sqrt(1 - loading**2) * idio_b
    data = np.hstack([block_a, block_b])
    columns = [f"A{i:02d}" for i in range(block_size)] + [f"B{i:02d}" for i in range(block_size)]
    index = pd.date_range("2010-01-01", periods=n_obs, freq="D")
    return pd.DataFrame(data, index=index, columns=columns)


# ---------------------------------------------------------------------------
# correlation_structure() -- statistics cases against known answers
# ---------------------------------------------------------------------------


def test_independent_returns_near_zero_correlation_high_n_eff():
    """Case 1: N=30 independent standard-normal columns -- the shape a genuinely decorrelated
    down-cap cohort would produce.
    """
    returns = _make_independent_returns(n_symbols=30, n_obs=2000)
    result = correlation_structure(returns)
    assert abs(result["avg_pairwise_corr"]) < 0.05
    assert result["n_eff"] > 0.7 * 30
    assert result["pc1_variance_share"] < 0.15


def test_single_factor_known_loading_matches_population_correlation():
    """Case 2: b=0.6 loading -- population pairwise correlation is exactly b^2=0.36. Also
    asserts n_eff against its own formula definition so a transcription error cannot pass.
    """
    n_symbols = 25
    returns = _make_single_factor_returns(n_symbols=n_symbols, n_obs=3000, loading=0.6)
    result = correlation_structure(returns)
    assert abs(result["avg_pairwise_corr"] - 0.36) < 0.03

    measured_avg = result["avg_pairwise_corr"]
    expected_n_eff = n_symbols / (1 + (n_symbols - 1) * measured_avg)
    assert result["n_eff"] == pytest.approx(expected_n_eff, abs=1e-9)


def test_perfectly_correlated_cohort_degenerate_endpoint():
    """Case 3: identical return series across all symbols -- the degenerate endpoint of the
    shrinkage formula: avg corr -> 1.0, n_eff -> 1.0, PC1 share -> 1.0.
    """
    returns = _make_perfectly_correlated_returns(n_symbols=10, n_obs=500)
    result = correlation_structure(returns)
    assert result["avg_pairwise_corr"] == pytest.approx(1.0, abs=1e-6)
    assert result["n_eff"] == pytest.approx(1.0, abs=1e-6)
    assert result["pc1_variance_share"] == pytest.approx(1.0, abs=1e-6)


def test_two_block_structure_pc_decomposition_responds_to_structure():
    """Case 4: two 15-symbol blocks, each driven by its own factor, factors uncorrelated.
    PC1 alone should NOT capture as much as PC1-3, and n_eff should land strictly between the
    independent case and the single-factor case -- proving the PC decomposition responds to
    genuine structure, not just N.
    """
    two_block = correlation_structure(_make_two_block_returns(block_size=15, n_obs=1500))
    independent = correlation_structure(_make_independent_returns(n_symbols=30, n_obs=1500))
    single_factor = correlation_structure(
        _make_single_factor_returns(n_symbols=30, n_obs=1500, loading=0.7)
    )

    assert two_block["pc1_variance_share"] < two_block["pc1_3_variance_share"]
    assert independent["n_eff"] > two_block["n_eff"] > single_factor["n_eff"]


def test_n_eff_monotone_decreasing_in_avg_pairwise_corr():
    """Case 5: n_eff is monotone decreasing in avg_pairwise_corr across three constructed
    loadings (b=0.2, 0.5, 0.8) at fixed N.
    """
    n_symbols = 20
    n_obs = 2000
    results = [
        correlation_structure(
            _make_single_factor_returns(n_symbols=n_symbols, n_obs=n_obs, loading=b, seed=_SEED + i)
        )
        for i, b in enumerate((0.2, 0.5, 0.8))
    ]
    n_effs = [r["n_eff"] for r in results]
    assert n_effs[0] > n_effs[1] > n_effs[2]


# ---------------------------------------------------------------------------
# evaluate_d10_gate() -- boundary cases, input dicts constructed directly
# ---------------------------------------------------------------------------


def _gate_input(avg_pairwise_corr: float | None) -> dict[str, float] | None:
    if avg_pairwise_corr is None:
        return None
    return {"avg_pairwise_corr": avg_pairwise_corr}


def test_gate_both_clear_passes():
    """Case 6: both well within threshold -- passes, no failed conditions."""
    result = evaluate_d10_gate(_gate_input(0.08), _gate_input(0.25))
    assert result["passed"] is True
    assert result["failed_conditions"] == []


def test_gate_boundary_exactly_at_threshold_passes():
    """Case 7: unconditional exactly 0.10, high_bear exactly 0.30 -- D-10's wording is "<=", so
    the boundary value passes. Pins this reading explicitly rather than leaving it to a future
    reader of the comparison operator.
    """
    result = evaluate_d10_gate(
        _gate_input(_D10_GATE_UNCONDITIONAL_MAX), _gate_input(_D10_GATE_HIGH_BEAR_MAX)
    )
    assert result["passed"] is True
    assert result["failed_conditions"] == []


def test_gate_unconditional_just_over_fails_only_unconditional():
    """Case 8: unconditional just over (0.1001), high_bear clear -- fails, and only the
    unconditional condition is named.
    """
    result = evaluate_d10_gate(_gate_input(0.1001), _gate_input(0.25))
    assert result["passed"] is False
    assert len(result["failed_conditions"]) == 1
    assert "unconditional" in result["failed_conditions"][0]


def test_gate_high_bear_just_over_fails_only_high_bear():
    """Case 9: unconditional clear, high_bear just over (0.3001) -- fails, and only the
    high_bear condition is named.
    """
    result = evaluate_d10_gate(_gate_input(0.08), _gate_input(0.3001))
    assert result["passed"] is False
    assert len(result["failed_conditions"]) == 1
    assert "high_bear" in result["failed_conditions"][0]


def test_gate_both_over_fails_with_two_conditions():
    """Case 10: both thresholds missed -- fails with two named conditions."""
    result = evaluate_d10_gate(_gate_input(0.5), _gate_input(0.6))
    assert result["passed"] is False
    assert len(result["failed_conditions"]) == 2


def test_gate_missing_high_bear_fails_closed():
    """Case 11: high_bear result missing/None (regime produced too few days, or the join
    returned nothing) -- fails closed with a named reason, never a pass by omission.
    """
    result = evaluate_d10_gate(_gate_input(0.05), None)
    assert result["passed"] is False
    assert any("high_bear" in reason for reason in result["failed_conditions"])


def test_gate_missing_unconditional_fails_closed():
    """Symmetric case: unconditional missing/None also fails closed with a named reason."""
    result = evaluate_d10_gate(None, _gate_input(0.05))
    assert result["passed"] is False
    assert any("unconditional" in reason for reason in result["failed_conditions"])


def test_gate_threshold_constants_are_the_literals_d10_fixed():
    """Case 12: the threshold constants are the exact literals D-10 fixed. A future edit to
    either value fails this test -- the mechanism that makes the pre-registration enforceable
    rather than aspirational.
    """
    assert _D10_GATE_UNCONDITIONAL_MAX == 0.10
    assert _D10_GATE_HIGH_BEAR_MAX == 0.30


def test_gate_is_pure_no_mutation_same_inputs_equal_results():
    """evaluate_d10_gate() must not mutate its input dicts, and calling it twice with the same
    inputs must return equal results.
    """
    unconditional = _gate_input(0.08)
    high_bear = _gate_input(0.25)
    unconditional_copy = dict(unconditional)
    high_bear_copy = dict(high_bear)

    first = evaluate_d10_gate(unconditional, high_bear)
    second = evaluate_d10_gate(unconditional, high_bear)

    assert first == second
    assert unconditional == unconditional_copy
    assert high_bear == high_bear_copy


# ---------------------------------------------------------------------------
# residualize_against_factor() -- known single-factor construction + sparse-column handling
# ---------------------------------------------------------------------------


def test_residualize_recovers_known_betas_and_removes_factor():
    """Case 13: r_i = alpha_i + beta_i * factor + e_i with known, distinct alpha_i/beta_i per
    symbol and independent e_i. Asserts (a) fitted betas match construction within 0.05, (b)
    residual-vs-factor correlation is near zero for every symbol, (c) the residual frame's
    pairwise correlation structure resembles the independent case, not the single-factor case.
    """
    rng = np.random.default_rng(_SEED)
    n_obs = 3000
    n_symbols = 20
    index = pd.date_range("2010-01-01", periods=n_obs, freq="D")

    factor = pd.Series(rng.standard_normal(n_obs), index=index, name="factor")
    true_betas = {f"SYM{i:02d}": 0.3 + 0.1 * i for i in range(n_symbols)}
    true_alphas = {f"SYM{i:02d}": 0.0001 * i for i in range(n_symbols)}

    data = {}
    for symbol, beta in true_betas.items():
        alpha = true_alphas[symbol]
        idio = rng.standard_normal(n_obs) * 0.5
        data[symbol] = alpha + beta * factor.to_numpy() + idio
    returns = pd.DataFrame(data, index=index)

    residuals, fitted_betas = residualize_against_factor(returns, factor)

    for symbol, beta in true_betas.items():
        assert fitted_betas[symbol] == pytest.approx(beta, abs=0.05)

    for symbol in returns.columns:
        corr_with_factor = residuals[symbol].corr(factor)
        assert abs(corr_with_factor) < 0.05

    resid_structure = correlation_structure(residuals)
    independent_structure = correlation_structure(
        _make_independent_returns(n_symbols=n_symbols, n_obs=n_obs)
    )
    single_factor_structure = correlation_structure(
        _make_single_factor_returns(n_symbols=n_symbols, n_obs=n_obs, loading=0.6)
    )
    assert abs(
        resid_structure["avg_pairwise_corr"] - independent_structure["avg_pairwise_corr"]
    ) < abs(resid_structure["avg_pairwise_corr"] - single_factor_structure["avg_pairwise_corr"])


def test_residualize_sparse_column_left_nan_no_corruption():
    """Case 14: one symbol has only 10 non-null observations (below the 20-observation floor).
    Its output column must be entirely NaN, not a spuriously-fit regression on too little data,
    and this must not raise or corrupt the other columns' results.
    """
    rng = np.random.default_rng(_SEED)
    n_obs = 500
    index = pd.date_range("2010-01-01", periods=n_obs, freq="D")
    factor = pd.Series(rng.standard_normal(n_obs), index=index)

    full_symbol = 0.5 * factor.to_numpy() + rng.standard_normal(n_obs) * 0.5
    sparse_symbol = np.full(n_obs, np.nan)
    sparse_symbol[:10] = rng.standard_normal(10)

    returns = pd.DataFrame({"FULL": full_symbol, "SPARSE": sparse_symbol}, index=index)

    residuals, betas = residualize_against_factor(returns, factor)

    assert residuals["SPARSE"].isna().all()
    assert np.isnan(betas["SPARSE"])
    assert not residuals["FULL"].isna().all()
    assert not np.isnan(betas["FULL"])
    assert betas["FULL"] == pytest.approx(0.5, abs=0.1)


def test_residualize_against_factor_never_feeds_the_gate():
    """Case 15: static-analysis-style structural guard -- no `evaluate_d10_gate(...)` CALL SITE
    passes an argument whose name/prefix contains `resid` (case-insensitive), so a future edit
    cannot silently wire the residualized numbers into the pass/fail decision. Scoped to actual
    call sites (`evaluate_d10_gate(`) rather than a bare substring pairing anywhere in the
    module, which would false-positive on this module's own prose (e.g. the docstring line
    "...the only input `evaluate_d10_gate()` accepts. The SPY-residualized table is...").
    """
    import re

    import scripts.analysis.universe_expansion_correlation_structure_check as module

    source = inspect.getsource(module)
    call_sites = re.findall(r"evaluate_d10_gate\(([^)]*)\)", source, flags=re.DOTALL)
    assert call_sites, "expected at least one evaluate_d10_gate(...) call site in the module"
    for args in call_sites:
        assert (
            "resid" not in args.lower()
        ), f"call site wires a residualized value into the gate: {args}"
