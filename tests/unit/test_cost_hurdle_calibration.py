"""Unit tests for cost-hurdle calibration pure functions (todo 030 Steps 1-3).

Pure-function tests only — no DB, no ConfigService, no asyncpg. The calibration
script's DB-touching code path (Steps 0-3 orchestration, ConfigService writes) is
exercised only when run against a live corpus; these tests cover the three
decision helpers that drive it: percentile selection, threshold verdict, and gap
verdict.
"""

from __future__ import annotations

from scripts.ops.corpus.ops_cost_hurdle_calibration import (
    _gap_verdict,
    _select_cost_hurdle,
    _threshold_verdict,
)


class TestSelectCostHurdle:
    def test_selects_p25_by_default(self) -> None:
        percentiles = {"p10": 0.01, "p25": 0.03, "p50": 0.05}
        assert _select_cost_hurdle(percentiles) == 0.03

    def test_selects_p10_when_requested(self) -> None:
        percentiles = {"p10": 0.01, "p25": 0.03, "p50": 0.05}
        assert _select_cost_hurdle(percentiles, percentile="p10") == 0.01

    def test_selects_p50_when_requested(self) -> None:
        percentiles = {"p10": 0.01, "p25": 0.03, "p50": 0.05}
        assert _select_cost_hurdle(percentiles, percentile="p50") == 0.05


class TestThresholdVerdict:
    def test_not_binding_when_current_below_p10(self) -> None:
        assert _threshold_verdict(current=0.5, p10=1.0, p50=2.0) == "not_binding"

    def test_over_filtering_when_current_above_p50(self) -> None:
        assert _threshold_verdict(current=3.0, p10=1.0, p50=2.0) == "over_filtering"

    def test_ok_when_current_between_p10_and_p50(self) -> None:
        assert _threshold_verdict(current=1.5, p10=1.0, p50=2.0) == "ok"

    def test_boundary_current_equals_p10_is_ok(self) -> None:
        # current < p10 is the not_binding trigger; current == p10 is not "below".
        assert _threshold_verdict(current=1.0, p10=1.0, p50=2.0) == "ok"

    def test_boundary_current_equals_p50_is_ok(self) -> None:
        # current > p50 is the over_filtering trigger; current == p50 is not "above".
        assert _threshold_verdict(current=2.0, p10=1.0, p50=2.0) == "ok"


class TestGapVerdict:
    def test_not_supported_when_gap_fraction_below_five_percent(self) -> None:
        result = _gap_verdict(mean_gap=0.01, mean_nogap=0.001, gap_fraction=0.02)
        assert result == "not_supported"

    def test_not_supported_when_returns_within_tolerance(self) -> None:
        # Gap fraction material but return means nearly identical (< 1% relative
        # difference) -> not supported.
        result = _gap_verdict(mean_gap=0.0010, mean_nogap=0.001005, gap_fraction=0.30)
        assert result == "not_supported"

    def test_material_when_gap_fraction_sufficient_and_returns_differ(self) -> None:
        result = _gap_verdict(mean_gap=0.05, mean_nogap=0.001, gap_fraction=0.30)
        assert result == "material"

    def test_boundary_gap_fraction_exactly_five_percent_with_material_diff(self) -> None:
        # gap_fraction < 0.05 is the not_supported trigger; == 0.05 should proceed
        # to the return-mean comparison.
        result = _gap_verdict(mean_gap=0.05, mean_nogap=0.001, gap_fraction=0.05)
        assert result == "material"
