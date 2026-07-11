"""Unit tests: anytime-valid e-values on IC sign (Component C, todo 079, Phase 143.1
Plan 06).

Task 1: the e-value kernel in src/intelligence/statistics/ic_math.py --
ic_sign_e_value_factor() (per-run e-value factor, likelihood-ratio variant) and
update_cumulative_e_value() (multiplicative anytime-valid update across corpus
reruns). Covers the anytime-valid null-boundedness property, promotion-threshold
growth under a consistent signal, and determinism.

Task 2: the tf=5m pilot-scope gate (services/ic_engine.py's _e_value_pilot_active())
and the canary-decay self-verification (scripts/ops/alpha/ops_canary_integrity_assert.py's
evaluate_e_value_decay()) -- the noise/dead canaries' cumulative e-value must decay
toward zero across reruns and must not cross the promotion threshold.

No DB, no Kafka. Pure numpy / synthetic rows.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.intelligence.statistics.ic_math import (
    _E_VALUE_P_ALT,
    ic_sign_e_value_factor,
    update_cumulative_e_value,
)

_ALPHA = 0.05
_PROMOTION_THRESHOLD = 1.0 / _ALPHA  # 20.0
_DEMOTION_THRESHOLD = _ALPHA  # 0.05


# ---------------------------------------------------------------------------
# Task 1: ic_sign_e_value_factor -- per-run e-value factor
# ---------------------------------------------------------------------------


class TestICSignEValueFactor:
    def test_matching_sign_grows_evidence(self):
        """Sign matching the tested (positive) direction -> factor > 1 (p_alt/0.5)."""
        factor = ic_sign_e_value_factor(1)
        assert factor == pytest.approx(_E_VALUE_P_ALT / 0.5)
        assert factor > 1.0

    def test_opposing_sign_shrinks_evidence(self):
        """Sign opposing the tested direction -> factor < 1 ((1-p_alt)/0.5)."""
        factor = ic_sign_e_value_factor(-1)
        assert factor == pytest.approx((1.0 - _E_VALUE_P_ALT) / 0.5)
        assert factor < 1.0

    def test_valid_e_value_nonnegative(self):
        """An e-value factor must be non-negative by definition."""
        assert ic_sign_e_value_factor(1) >= 0.0
        assert ic_sign_e_value_factor(-1) >= 0.0

    def test_deterministic_given_fixed_inputs(self):
        assert ic_sign_e_value_factor(1) == ic_sign_e_value_factor(1)
        assert ic_sign_e_value_factor(-1) == ic_sign_e_value_factor(-1)

    def test_custom_p_alt_respected(self):
        factor = ic_sign_e_value_factor(1, p_alt=0.6)
        assert factor == pytest.approx(0.6 / 0.5)


# ---------------------------------------------------------------------------
# Task 1: update_cumulative_e_value -- multiplicative anytime-valid update
# ---------------------------------------------------------------------------


class TestUpdateCumulativeEValue:
    def test_deterministic_given_fixed_inputs(self):
        a = update_cumulative_e_value(2.0, ic_sign=1)
        b = update_cumulative_e_value(2.0, ic_sign=1)
        assert a == b

    def test_none_sign_leaves_cumulative_unchanged(self):
        """A degenerate/unmeasurable cell this run contributes no evidence -- the
        cumulative e-value is neither inflated nor deflated by a non-observation."""
        assert update_cumulative_e_value(3.0, ic_sign=None) == 3.0

    def test_first_look_defaults_to_neutral_prior(self):
        """prior_cumulative=1.0 (no evidence yet) times this run's factor == the
        factor itself -- the process starts at the neutral e-value of 1.0."""
        result = update_cumulative_e_value(1.0, ic_sign=1)
        assert result == pytest.approx(ic_sign_e_value_factor(1))

    def test_consistent_positive_sign_compounds_and_crosses_promotion_threshold(self):
        """A cell with consistent positive IC sign across reruns -> cumulative
        e-value grows above 1/alpha (promotion threshold) within a bounded number
        of reruns -- evidence compounds, not resets."""
        cumulative = 1.0
        n_runs = 0
        while cumulative <= _PROMOTION_THRESHOLD and n_runs < 100:
            cumulative = update_cumulative_e_value(cumulative, ic_sign=1)
            n_runs += 1
        assert cumulative > _PROMOTION_THRESHOLD
        assert n_runs < 100, "did not converge within a reasonable number of reruns"

    def test_consistent_negative_sign_decays_toward_demotion_threshold(self):
        """A cell testing the positive direction that instead sees a consistently
        NEGATIVE sign decays below the symmetric demotion threshold (alpha) --
        evidence against the tested direction also compounds."""
        cumulative = 1.0
        n_runs = 0
        while cumulative >= _DEMOTION_THRESHOLD and n_runs < 100:
            cumulative = update_cumulative_e_value(cumulative, ic_sign=-1)
            n_runs += 1
        assert cumulative < _DEMOTION_THRESHOLD
        assert n_runs < 100

    def test_random_sign_null_cell_rarely_crosses_promotion_threshold(self):
        """Ville's inequality: P(cumulative e-value ever exceeds 1/alpha under H0)
        <= alpha. Empirically verified over many simulated null (fair-coin) IC-sign
        sequences with a fixed seed -- 'no free re-roll' means a random-sign cell
        should almost never accumulate enough evidence to promote."""
        rng = np.random.default_rng(42)
        n_runs = 200
        n_sims = 500
        n_crossed = 0
        final_cumulatives = []
        for _ in range(n_sims):
            cumulative = 1.0
            crossed = False
            for _ in range(n_runs):
                sign = 1 if rng.random() < 0.5 else -1
                cumulative = update_cumulative_e_value(cumulative, ic_sign=sign)
                if cumulative > _PROMOTION_THRESHOLD:
                    crossed = True
            final_cumulatives.append(cumulative)
            if crossed:
                n_crossed += 1
        # Ville's bound is <= alpha (0.05); allow generous empirical margin.
        assert n_crossed / n_sims <= 0.15
        # The e-process is a martingale under H0 with negative log-drift -- it
        # decays toward zero a.s., so the median final cumulative should be small.
        assert np.median(final_cumulatives) < 1.0

    def test_e_value_expectation_le_one_under_null_exact(self):
        """The defining property of a valid e-value: E_H0[e] <= 1 under the null
        (fair coin, i.e. no genuine directional signal -- reruns are noise).
        Verified exactly (closed-form): a likelihood ratio against a fixed
        alternative has E_H0[LR]=1 by construction (0.5*(p_alt/0.5) +
        0.5*((1-p_alt)/0.5) = p_alt + (1-p_alt) = 1), not merely bounded above
        by 1. Deterministic, not Monte Carlo -- the multiplicative cumulative
        process is heavy-tailed (variance grows geometrically with n_runs), so a
        sample-mean check over compounded reruns would need an infeasible
        number of simulations to converge tightly; the single-step expectation
        is exact and requires none.
        """
        pos_factor = ic_sign_e_value_factor(1)
        neg_factor = ic_sign_e_value_factor(-1)
        expected_under_fair_coin = 0.5 * pos_factor + 0.5 * neg_factor
        assert expected_under_fair_coin == pytest.approx(1.0)
        assert expected_under_fair_coin <= 1.0 + 1e-9

    def test_e_value_single_step_mean_matches_theory_under_synthetic_null(self):
        """Empirical corroboration of the exact result above on a synthetic null
        (fair-coin IC-sign draws): the single-step (not compounded) sample mean
        of the e-value factor converges tightly to 1.0 -- bounded variance
        (0.25) makes this check statistically sound at a modest sample size,
        unlike compounding across many reruns."""
        rng = np.random.default_rng(7)
        n_sims = 20000
        pos_factor = ic_sign_e_value_factor(1)
        neg_factor = ic_sign_e_value_factor(-1)
        signs = rng.random(n_sims) < 0.5
        factors = np.where(signs, pos_factor, neg_factor)
        assert factors.mean() == pytest.approx(1.0, abs=0.02)
        assert np.all(factors >= 0.0)


# ---------------------------------------------------------------------------
# Task 2: pilot-scope gate (services/ic_engine.py's _e_value_pilot_active)
# ---------------------------------------------------------------------------


class TestEValuePilotScopeGate:
    def test_5m_is_pilot_active(self):
        from services.ic_engine import _e_value_pilot_active

        assert _e_value_pilot_active("5m") is True

    def test_other_timeframes_are_not_pilot_active(self):
        from services.ic_engine import _e_value_pilot_active

        for tf in ("15m", "1h", "1d"):
            assert _e_value_pilot_active(tf) is False


# ---------------------------------------------------------------------------
# Task 2: canary-decay self-verification
# (scripts/ops/alpha/ops_canary_integrity_assert.py's evaluate_e_value_decay)
# ---------------------------------------------------------------------------


def _e_row(
    feature_name: str,
    control_expectation: str,
    cumulative_e_value: float | None,
    tf: str = "5m",
    symbol: str = "POOLED",
    regime: str = "trending_up",
) -> dict:
    return {
        "feature_name": feature_name,
        "symbol": symbol,
        "tf": tf,
        "regime": regime,
        "control_expectation": control_expectation,
        "cumulative_e_value": cumulative_e_value,
    }


class TestEValueDecaySelfVerification:
    def test_negative_control_decaying_toward_zero_passes(self):
        from scripts.ops.alpha.ops_canary_integrity_assert import evaluate_e_value_decay

        rows = [
            _e_row("canary_noise_gaussian", "negative_control", 0.02),
            _e_row("canary_noise_uniform", "negative_control", 0.15),
            _e_row("canary_constant", "negative_control", 0.5),
            _e_row("canary_near_constant", "negative_control", 0.9),
            _e_row("canary_acausal_placebo", "positive_control", 1.2),
        ]
        report = evaluate_e_value_decay(rows)
        assert report["negative_control_violations"] == []

    def test_negative_control_crossing_promotion_threshold_is_flagged(self):
        from scripts.ops.alpha.ops_canary_integrity_assert import (
            EValueDecayViolation,
            evaluate_e_value_decay,
        )

        rows = [
            _e_row("canary_noise_gaussian", "negative_control", 0.02),
            # A dead/noise canary that has somehow accumulated enough evidence to
            # cross the promotion threshold -- this must never happen for a
            # genuine negative control; a mis-specified e-value kernel would.
            _e_row("canary_constant", "negative_control", 25.0),
        ]
        with pytest.raises(EValueDecayViolation, match="canary_constant"):
            evaluate_e_value_decay(rows)

    def test_rows_outside_5m_pilot_scope_are_ignored(self):
        from scripts.ops.alpha.ops_canary_integrity_assert import evaluate_e_value_decay

        rows = [
            _e_row("canary_constant", "negative_control", 25.0, tf="15m"),
        ]
        report = evaluate_e_value_decay(rows)
        assert report["n_rows_evaluated"] == 0
        assert report["negative_control_violations"] == []

    def test_rows_with_no_cumulative_e_value_yet_are_ignored(self):
        """Before any corpus rerun has populated the column, rows carry NULL --
        this must not be treated as a violation (pilot not yet exercised)."""
        from scripts.ops.alpha.ops_canary_integrity_assert import evaluate_e_value_decay

        rows = [_e_row("canary_noise_gaussian", "negative_control", None)]
        report = evaluate_e_value_decay(rows)
        assert report["n_rows_evaluated"] == 0

    def test_no_rows_at_all_does_not_raise(self):
        """Unlike the base canary integrity check, absence of e-value coverage is
        expected before Plan 07's corpus rerun -- not a hard-halt condition."""
        from scripts.ops.alpha.ops_canary_integrity_assert import evaluate_e_value_decay

        report = evaluate_e_value_decay([])
        assert report["n_rows_evaluated"] == 0
        assert report["negative_control_violations"] == []

    def test_positive_control_growing_is_reported_not_flagged(self):
        """The acausal placebo's e-value growing is the EXPECTED, healthy positive-
        control behavior (interfaces note) -- must not be flagged as a violation."""
        from scripts.ops.alpha.ops_canary_integrity_assert import evaluate_e_value_decay

        rows = [_e_row("canary_acausal_placebo", "positive_control", 50.0)]
        report = evaluate_e_value_decay(rows)
        assert report["negative_control_violations"] == []
        assert report["positive_control_crossed_promotion"] is True
