"""Mathematical invariant tests for GARCHVolatilityPlugin.

Enforces these algebraic preconditions in code (not docs):
  - sigma2 > 0 always (the GARCH recurrence preserves positivity when omega > 0).
  - No overflow or unbounded growth on long sequences.
  - No underflow (sigma2 stays above a small positive floor on flat data).
  - Convergence on flat-return data to the correct fixed point derived from
    the actual recurrence in garch_volatility.py (NOT assumed from textbook).
  - Shock formula uses prior sigma2 (not posterior).
  - Incremental state updates equal full recomputation on the same input window.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src.intelligence.context.garch_volatility import GARCHVolatilityPlugin
from tests.unit.intelligence.correctness.conftest import frames_from_ohlcv


def _run_incremental(
    plugin: GARCHVolatilityPlugin,
    df: pd.DataFrame,
    *,
    bootstrap_bars: int = 30,
) -> list[dict]:
    """Bootstrap with compute_full on first `bootstrap_bars`, then iterate compute_next.

    Returns list of result dicts for each step (bootstrap result + incremental).
    """
    result = plugin.compute_full(frames_from_ohlcv(df.iloc[:bootstrap_bars]))
    if not result:
        return []
    results = [result]
    state = dict(result["_state"])

    for i in range(bootstrap_bars, len(df)):
        r = plugin.compute_next(frames_from_ohlcv(df.iloc[i : i + 1]), state=state)
        if not r:
            break
        results.append(r)
        state = dict(r["_state"])

    return results


class TestGARCHInvariants:
    """Invariant tests for GARCHVolatilityPlugin's GARCH(1,1) recurrence."""

    def test_garch_sigma2_strictly_positive(self, synthetic_ohlcv_trending: pd.DataFrame) -> None:
        """prev_sigma2 (posterior conditional variance) must be > 0 after every bar.

        GARCH(1,1) recurrence: sigma2 = omega + alpha * epsilon^2 + beta * sigma2_prior
        With omega > 0 and alpha, beta >= 0, the right-hand side is >= omega > 0
        regardless of epsilon and sigma2_prior. Therefore sigma2 > 0 is maintained
        inductively for all bars.
        """
        plugin = GARCHVolatilityPlugin()
        df = synthetic_ohlcv_trending
        results = _run_incremental(plugin, df)
        assert len(results) >= 100, "Expected at least 100 results"
        for idx, r in enumerate(results):
            state = r["_state"]
            sigma2 = state["prev_sigma2"]
            assert sigma2 > 0.0, f"Bar {idx}: prev_sigma2={sigma2} is not positive"
            assert math.isfinite(sigma2), f"Bar {idx}: prev_sigma2={sigma2} is not finite"

    @pytest.mark.parametrize(
        "fixture_name",
        ["synthetic_ohlcv_trending", "synthetic_ohlcv_ranging"],
    )
    def test_garch_no_overflow_on_long_run(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        """garch_sigma output must remain finite and below a sane upper bound of 1e6.

        Unbounded growth would indicate a stationarity violation (alpha+beta >= 1)
        or a numerical blow-up. The default parameters (alpha=0.10, beta=0.85,
        alpha+beta=0.95 < 1) are stationary, so sigma should remain bounded.
        """
        df: pd.DataFrame = request.getfixturevalue(fixture_name)
        plugin = GARCHVolatilityPlugin()
        results = _run_incremental(plugin, df)
        assert len(results) > 0
        for idx, r in enumerate(results):
            sigma = r.get("garch_sigma")
            assert sigma is not None, f"{fixture_name} bar {idx}: garch_sigma key missing"
            assert math.isfinite(
                sigma
            ), f"{fixture_name} bar {idx}: garch_sigma={sigma} is not finite"
            assert (
                sigma < 1e6
            ), f"{fixture_name} bar {idx}: garch_sigma={sigma} exceeds upper bound 1e6"

    def test_garch_no_underflow_on_flat_data(self, synthetic_ohlcv_flat: pd.DataFrame) -> None:
        """sigma2 must stay strictly above a small positive floor on flat-price data.

        On flat data all log returns are 0, so the GARCH recurrence becomes:
          sigma2_t = omega + beta * sigma2_{t-1}   (alpha * 0^2 = 0)
        This is a linear contraction (beta=0.85 < 1) toward omega/(1-beta).
        sigma2 can never reach zero because the recurrence always adds omega > 0.
        """
        plugin = GARCHVolatilityPlugin()
        df = synthetic_ohlcv_flat
        results = _run_incremental(plugin, df)
        assert len(results) > 0
        for idx, r in enumerate(results):
            state = r["_state"]
            sigma2 = state["prev_sigma2"]
            # sigma2 must stay above a small positive floor — never zero or negative
            assert (
                sigma2 >= 1e-12
            ), f"Bar {idx}: prev_sigma2={sigma2} is below the positive floor 1e-12"
            assert sigma2 > 0.0, f"Bar {idx}: prev_sigma2={sigma2} is not positive"

    def test_garch_converges_to_long_run_variance(self, synthetic_ohlcv_flat: pd.DataFrame) -> None:
        """GARCH sigma2 must converge to the correct fixed point on flat-return data.

        Fixed-point derivation (derived from the actual recurrence in garch_volatility.py):
        -----------------------------------------------------------------------------------
        Recurrence (from garch_volatility.py line 62):
            sigma2 = self.omega + self.alpha * epsilon**2 + self.beta * sigma2
        where epsilon = log(c / prev_close) (raw log return, from compute_next line 126).

        On perfectly flat data (all close prices equal), every log return is:
            epsilon = log(price / price) = log(1) = 0
        Therefore the alpha term vanishes:
            sigma2_t = omega + alpha * 0^2 + beta * sigma2_{t-1}
                     = omega + beta * sigma2_{t-1}

        Fixed point: set sigma2* = sigma2 in the recurrence:
            sigma2* = omega + beta * sigma2*
            sigma2* * (1 - beta) = omega
            sigma2* = omega / (1 - beta)

        NOTE: This is NOT the unconditional variance formula omega / (1 - alpha - beta).
        That formula applies when epsilon^2 is replaced by its expectation sigma2 (i.e.,
        the unconditional mean under the stationary distribution). On ZERO-RETURN data,
        epsilon=0 strictly, so the alpha term is exactly zero and the fixed point is
        omega / (1 - beta), not omega / (1 - alpha - beta).

        With the default parameters omega=0.00001, alpha=0.10, beta=0.85:
            long_run_var = 0.00001 / (1 - 0.85) = 0.00001 / 0.15 ≈ 6.667e-5
        -----------------------------------------------------------------------------------
        """
        plugin = GARCHVolatilityPlugin()

        # Extract actual parameters from the plugin (do not hard-code them)
        omega = plugin.omega  # 0.00001
        beta = plugin.beta  # 0.85

        # Fixed point on zero-return data: omega / (1 - beta)
        # See derivation in the docstring above.
        long_run_var = omega / (1 - beta)

        df = synthetic_ohlcv_flat
        results = _run_incremental(plugin, df)
        assert len(results) >= 200, "Need sufficient bars for convergence"

        # After 500 bars on flat data, sigma2 should be within 5% of the fixed point
        final_state = results[-1]["_state"]
        sigma2_final = final_state["prev_sigma2"]

        rel_error = abs(sigma2_final - long_run_var) / long_run_var
        assert rel_error < 0.05, (
            f"sigma2 did not converge to fixed point: "
            f"sigma2_final={sigma2_final:.6e}, "
            f"long_run_var(omega/(1-beta))={long_run_var:.6e}, "
            f"rel_error={rel_error:.4f} (max 0.05)"
        )

    def test_garch_shock_uses_prior_sigma2(self, synthetic_ohlcv_trending: pd.DataFrame) -> None:
        """Shock = epsilon^2 / sigma2_prior must match the garch_shock output.

        The implementation (garch_volatility.py line 152 in compute_next) computes:
            shock = epsilon^2 / s["prev_sigma2"]   (prior, not posterior)
        This test re-derives shock from two consecutive bars' state and verifies the
        garch_shock output matches to atol=1e-9.
        """
        plugin = GARCHVolatilityPlugin()
        df = synthetic_ohlcv_trending

        # Bootstrap: get state after first 30 bars
        result = plugin.compute_full(frames_from_ohlcv(df.iloc[:30]))
        assert result, "Bootstrap returned empty"
        state = dict(result["_state"])

        # Capture sigma2_prior BEFORE compute_next mutates the state dict in place
        sigma2_prior = float(state["prev_sigma2"])
        prev_close = float(state["prev_close"])

        # Advance one bar to get bar 30's result
        r1 = plugin.compute_next(frames_from_ohlcv(df.iloc[30:31]), state=state)
        assert r1, "compute_next at bar 30 returned empty"
        # NOTE: state is mutated by compute_next via state.update(...); read prior
        # values from the copies captured above, not from state after the call.

        # The epsilon for bar 30 = log(close[30] / close[29])
        close_30 = float(df.iloc[30]["close"])
        epsilon = math.log(close_30 / prev_close) if prev_close > 0 else 0.0

        # Re-derive shock using the prior (pre-update) sigma2
        if sigma2_prior > 1e-15:
            expected_shock = epsilon**2 / sigma2_prior
        else:
            expected_shock = 0.0

        reported_shock = float(r1["garch_shock"])

        assert math.isclose(reported_shock, expected_shock, abs_tol=1e-9), (
            f"garch_shock mismatch: reported={reported_shock:.6e}, "
            f"re-derived={expected_shock:.6e} "
            f"(epsilon={epsilon:.6e}, sigma2_prior={sigma2_prior:.6e})"
        )

    def test_garch_incremental_equals_full(self, synthetic_ohlcv_trending: pd.DataFrame) -> None:
        """compute_next must produce identical garch_sigma to compute_full on same window.

        Protocol:
          1. compute_full on bars[0:100] to get bootstrap state.
          2. compute_next bar-by-bar for bars[100:200] threading state forward.
          3. compute_full on bars[0:200] independently.
          4. Assert final garch_sigma values match within atol=1e-6.
        """
        plugin = GARCHVolatilityPlugin()
        df = synthetic_ohlcv_trending

        # Step 1: bootstrap on first 100 bars
        result_bootstrap = plugin.compute_full(frames_from_ohlcv(df.iloc[:100]))
        assert result_bootstrap, "Bootstrap compute_full returned empty"
        state = dict(result_bootstrap["_state"])

        # Step 2: incremental for bars 100..199
        last_incremental: dict = {}
        for i in range(100, 200):
            r = plugin.compute_next(frames_from_ohlcv(df.iloc[i : i + 1]), state=state)
            assert r, f"compute_next returned empty at bar {i}"
            last_incremental = r
            state = dict(r["_state"])

        # Step 3: full recomputation on bars[0:200]
        result_full = plugin.compute_full(frames_from_ohlcv(df.iloc[:200]))
        assert result_full, "Full compute_full on 200 bars returned empty"

        # Step 4: compare garch_sigma final value
        inc_sigma = float(last_incremental["garch_sigma"])
        full_sigma = float(result_full["garch_sigma"])

        assert math.isclose(inc_sigma, full_sigma, abs_tol=1e-6), (
            f"garch_sigma mismatch: incremental={inc_sigma:.8e} vs full={full_sigma:.8e} "
            f"(diff={abs(inc_sigma - full_sigma):.2e})"
        )

        # Also verify sigma2 state matches
        inc_sigma2 = last_incremental["_state"]["prev_sigma2"]
        full_sigma2 = result_full["_state"]["prev_sigma2"]
        assert math.isclose(
            float(inc_sigma2), float(full_sigma2), abs_tol=1e-6
        ), f"prev_sigma2 state mismatch: incremental={inc_sigma2:.8e} vs full={full_sigma2:.8e}"
