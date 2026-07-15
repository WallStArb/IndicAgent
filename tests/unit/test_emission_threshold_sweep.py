"""Unit tests: EM-CAL emission threshold sweep (todo 065).

_passes_gate, _net_return_for_event, _sweep_stratum, _select_optimal, and
_granularity_earned are pure importable helpers in
scripts/ops/alpha/ops_emission_threshold_sweep.py. No live corpus data exists at time
of writing (ensemble_alpha is empty mid Phase 143.1-07 rebuild) -- these tests validate
the sweep mechanism against synthetic data so the harness is proven correct and ready
to run for real once the corpus lands, without treating any number here as a
calibration result.

No DB, no Kafka. Pure Python.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

_scripts_alpha_dir = _project_root / "scripts" / "ops" / "alpha"
if str(_scripts_alpha_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_alpha_dir))

from ops_emission_threshold_sweep import (
    _granularity_earned,
    _net_return_for_event,
    _passes_gate,
    _select_optimal,
    _sweep_stratum,
    _ThresholdResult,
)


class TestPassesGate:
    def test_effective_n_below_gate_rejected(self) -> None:
        assert not _passes_gate(2.0, 0.5, 3.5, 2.0, 1.0, 0.0, 3.0)

    def test_abs_score_at_or_below_threshold_rejected(self) -> None:
        assert not _passes_gate(1.0, 0.5, 3.5, 5.0, 1.0, 0.0, 3.0)

    def test_long_passes_when_ci_lower_above_hurdle(self) -> None:
        assert _passes_gate(2.0, 0.5, 3.5, 5.0, 1.0, 0.0, 3.0)

    def test_long_rejected_when_ci_lower_at_or_below_hurdle(self) -> None:
        assert not _passes_gate(2.0, 0.0, 3.5, 5.0, 1.0, 0.0, 3.0)

    def test_short_passes_when_ci_upper_below_negative_hurdle(self) -> None:
        assert _passes_gate(-2.0, -3.5, -0.5, 5.0, 1.0, 0.0, 3.0)

    def test_short_rejected_when_ci_upper_at_or_above_negative_hurdle(self) -> None:
        assert not _passes_gate(-2.0, -3.5, 0.0, 5.0, 1.0, 0.0, 3.0)

    def test_none_ci_lower_rejected_for_long(self) -> None:
        assert not _passes_gate(2.0, None, 3.5, 5.0, 1.0, 0.0, 3.0)

    def test_none_ci_upper_rejected_for_short(self) -> None:
        assert not _passes_gate(-2.0, -3.5, None, 5.0, 1.0, 0.0, 3.0)

    def test_cost_hurdle_raises_the_bar(self) -> None:
        # ci_lower=0.05 clears a zero hurdle but not a 0.1 hurdle
        assert _passes_gate(2.0, 0.05, 3.5, 5.0, 1.0, 0.0, 3.0)
        assert not _passes_gate(2.0, 0.05, 3.5, 5.0, 1.0, 0.1, 3.0)


class TestNetReturnForEvent:
    def test_long_direction_keeps_return_sign(self) -> None:
        assert _net_return_for_event(2.0, 0.01, 0.0) == 0.01

    def test_short_direction_flips_return_sign(self) -> None:
        assert _net_return_for_event(-2.0, 0.01, 0.0) == -0.01

    def test_cost_hurdle_subtracted(self) -> None:
        assert _net_return_for_event(2.0, 0.01, 0.002) == 0.008

    def test_short_cost_hurdle_still_subtracted_not_added(self) -> None:
        # direction flips the *return*, cost is a flat drag regardless of direction
        assert _net_return_for_event(-2.0, -0.01, 0.002) == 0.008


class TestSweepStratum:
    def _rows(self) -> list[dict]:
        return [
            {
                "alpha_score": 2.0,
                "alpha_ci_lower": 0.5,
                "alpha_ci_upper": 3.5,
                "effective_n": 5.0,
                "forward_return": 0.02,
            },
            {
                "alpha_score": 1.2,
                "alpha_ci_lower": 0.1,
                "alpha_ci_upper": 2.0,
                "effective_n": 5.0,
                "forward_return": 0.005,
            },
            {
                "alpha_score": -1.8,
                "alpha_ci_lower": -3.0,
                "alpha_ci_upper": -0.4,
                "effective_n": 5.0,
                "forward_return": -0.015,
            },
        ]

    def test_higher_threshold_yields_fewer_or_equal_events(self) -> None:
        results = _sweep_stratum(
            self._rows(), (1.0, 1.5, 2.5), cost_hurdle=0.0, effective_n_gate=3.0
        )
        n_by_threshold = {r.threshold: r.n_events for r in results}
        assert n_by_threshold[1.0] >= n_by_threshold[1.5] >= n_by_threshold[2.5]

    def test_threshold_above_all_scores_yields_zero_events(self) -> None:
        results = _sweep_stratum(self._rows(), (10.0,), cost_hurdle=0.0, effective_n_gate=3.0)
        assert results[0].n_events == 0
        assert results[0].mean_net_return is None
        assert results[0].se_net_return is None

    def test_single_event_has_no_standard_error(self) -> None:
        # 1.9 admits only the |score|=2.0 row (1.2 and 1.8 both fall at or below it)
        results = _sweep_stratum(self._rows(), (1.9,), cost_hurdle=0.0, effective_n_gate=3.0)
        assert results[0].n_events == 1
        assert results[0].mean_net_return is not None
        assert results[0].se_net_return is None

    def test_mean_net_return_matches_manual_computation(self) -> None:
        # threshold=1.0 admits all three rows (all |score| > 1.0); net returns are
        # long 0.02, long 0.005, short -(-0.015)=0.015 -> mean = 0.04/3
        results = _sweep_stratum(self._rows(), (1.0,), cost_hurdle=0.0, effective_n_gate=3.0)
        assert results[0].n_events == 3
        assert abs(results[0].mean_net_return - (0.02 + 0.005 + 0.015) / 3) < 1e-9


class TestSelectOptimal:
    def test_picks_highest_mean_return_among_eligible(self) -> None:
        results = [
            _ThresholdResult(1.0, 50, 0.001, 0.0002),
            _ThresholdResult(1.5, 40, 0.003, 0.0003),
            _ThresholdResult(2.0, 20, 0.010, 0.0010),
        ]
        optimal = _select_optimal(results, min_events=30)
        assert optimal is not None
        assert optimal.threshold == 1.5  # 2.0 has higher return but fails the N floor

    def test_none_when_nothing_clears_the_floor(self) -> None:
        results = [_ThresholdResult(1.0, 5, 0.05, 0.01)]
        assert _select_optimal(results, min_events=30) is None

    def test_skips_zero_event_thresholds(self) -> None:
        results = [_ThresholdResult(1.0, 0, None, None), _ThresholdResult(2.0, 40, 0.002, 0.0002)]
        optimal = _select_optimal(results, min_events=30)
        assert optimal is not None
        assert optimal.threshold == 2.0


class TestGranularityEarned:
    def test_non_overlapping_ci_above_is_earned(self) -> None:
        regime_optimal = _ThresholdResult(1.5, 50, 0.010, 0.001)  # CI ~[0.008, 0.012]
        assert _granularity_earned(regime_optimal, tf_optimal_ci=(0.001, 0.003))

    def test_overlapping_ci_is_not_earned(self) -> None:
        regime_optimal = _ThresholdResult(1.5, 50, 0.002, 0.001)  # CI ~[0.0, 0.004]
        assert not _granularity_earned(regime_optimal, tf_optimal_ci=(0.001, 0.003))

    def test_missing_ci_is_not_earned(self) -> None:
        regime_optimal = _ThresholdResult(1.5, 1, 0.010, None)
        assert not _granularity_earned(regime_optimal, tf_optimal_ci=(0.001, 0.003))
