"""Unit tests: itr_materiality_shadow_diagnostic.py's pure membership-delta and
gate-attribution logic (Phase 175, Plan 04, Task 1).

No DB, no Kafka, no network. Pure Python -- every fixture row is a plain dict shaped
like an `instrument_tags_active` row.
"""

from __future__ import annotations

import math
from typing import Any

from scripts.analysis.itr_materiality_shadow_diagnostic import (
    attribute_gate_failures,
    build_tag_arms,
    gate_value_distributions,
    membership_delta,
    sign_stability_near_miss,
)

_THRESHOLDS = {
    "min_sample_n": 756,
    "min_partial_loading": 0.35,
    "min_partial_loading_ci_low": 0.20,
    "min_incremental_r2": 0.05,
    "min_sign_stable_windows": 3,
    "null_arm_alpha": 0.05,
}


def _row(
    symbol: str,
    tag: str,
    source: str,
    *,
    valid_to: str | None = None,
    passes_materiality: bool | None = None,
    discovery_state: str | None = None,
    partial_loading: float | None = None,
    partial_loading_ci_low: float | None = None,
    incremental_r2: float | None = None,
    sign_stable_windows: int | None = None,
    sign_stable_windows_total: int | None = None,
    null_arm_bh_p: float | None = None,
    materiality_sample_n: int | None = None,
) -> dict[str, Any]:
    """Build a plain dict shaped like an instrument_tags_active row."""
    return {
        "symbol": symbol,
        "tag": tag,
        "source": source,
        "valid_to": valid_to,
        "passes_materiality": passes_materiality,
        "discovery_state": discovery_state,
        "partial_loading": partial_loading,
        "partial_loading_ci_low": partial_loading_ci_low,
        "incremental_r2": incremental_r2,
        "sign_stable_windows": sign_stable_windows,
        "sign_stable_windows_total": sign_stable_windows_total,
        "null_arm_bh_p": null_arm_bh_p,
        "materiality_sample_n": materiality_sample_n,
    }


def _eligible_row(symbol: str, tag: str) -> dict[str, Any]:
    """A fully materiality-eligible empirical row -- clears all six gates plus the
    temporal and expiry gates."""
    return _row(
        symbol,
        tag,
        "empirical",
        valid_to=None,
        passes_materiality=True,
        discovery_state="confirmed",
        partial_loading=0.50,
        partial_loading_ci_low=0.30,
        incremental_r2=0.10,
        sign_stable_windows=3,
        sign_stable_windows_total=4,
        null_arm_bh_p=0.01,
        materiality_sample_n=900,
    )


# ---------------------------------------------------------------------------
# build_tag_arms
# ---------------------------------------------------------------------------


def test_build_tag_arms_human_row_in_both_arms() -> None:
    rows = [_row("SPY", "eq_factor", "human")]
    baseline, candidate = build_tag_arms(rows)
    assert baseline == {"SPY": {"eq_factor"}}
    assert candidate == {"SPY": {"eq_factor"}}


def test_build_tag_arms_eligible_empirical_row_in_candidate_only() -> None:
    rows = [_eligible_row("XLE", "eq_energy")]
    baseline, candidate = build_tag_arms(rows)
    assert baseline == {}
    assert candidate == {"XLE": {"eq_energy"}}


def test_build_tag_arms_pending_oos_row_in_neither_arm() -> None:
    """Todo 125 temporal gate: passes_materiality=True, discovery_state='pending_oos'."""
    row = _eligible_row("XLE", "eq_energy")
    row["discovery_state"] = "pending_oos"
    baseline, candidate = build_tag_arms([row])
    assert baseline == {}
    assert candidate == {}


def test_build_tag_arms_expired_row_in_neither_arm() -> None:
    """Todo 126 expiry gate: confirmed + passing but valid_to is set. Asserted even
    though the view already filters this out, so the contract holds in code too."""
    row = _eligible_row("XLE", "eq_energy")
    row["valid_to"] = "2026-01-01T00:00:00+00:00"
    baseline, candidate = build_tag_arms([row])
    assert baseline == {}
    assert candidate == {}


def test_build_tag_arms_ai_source_never_appears() -> None:
    rows = [_row("SPY", "eq_factor", "ai")]
    baseline, candidate = build_tag_arms(rows)
    assert baseline == {}
    assert candidate == {}


def test_build_tag_arms_non_eligible_empirical_excluded_from_candidate() -> None:
    row = _eligible_row("XLE", "eq_energy")
    row["passes_materiality"] = False
    baseline, candidate = build_tag_arms([row])
    assert baseline == {}
    assert candidate == {}


# ---------------------------------------------------------------------------
# membership_delta
# ---------------------------------------------------------------------------


def test_membership_delta_added_and_removed_sorted() -> None:
    baseline = {"AGG": {"fi_bond"}}
    candidate = {"AGG": {"fi_bond"}, "TLT": {"fi_bond"}, "IEF": {"fi_bond"}}
    baseline_symbols, candidate_symbols, added, removed = membership_delta(
        baseline, candidate, ["fi_*"], set()
    )
    assert baseline_symbols == ["AGG"]
    assert candidate_symbols == ["AGG", "IEF", "TLT"]
    assert added == ["IEF", "TLT"]
    assert removed == []


def test_membership_delta_removed_always_empty() -> None:
    """The candidate arm is a strict superset of the baseline arm by construction --
    removed must be empty for any input."""
    baseline = {"A": {"eq_x"}, "B": {"eq_y"}}
    candidate = {"A": {"eq_x"}, "B": {"eq_y"}, "C": {"eq_z"}}
    _, _, _, removed = membership_delta(baseline, candidate, ["eq_*"], set())
    assert removed == []


def test_membership_delta_delegates_prefix_matching_to_resolve_group_symbols() -> None:
    """eq_factor matches filter ["eq_*"] via prefix stripping -- proves symbol
    resolution goes through _resolve_group_symbols, not a reimplementation."""
    baseline: dict[str, set[str]] = {}
    candidate = {"XLF": {"eq_factor"}}
    _, candidate_symbols, added, _ = membership_delta(baseline, candidate, ["eq_*"], set())
    assert candidate_symbols == ["XLF"]
    assert added == ["XLF"]


def test_membership_delta_applies_exclude_symbols_after_resolution() -> None:
    baseline: dict[str, set[str]] = {}
    candidate = {"XLF": {"eq_factor"}, "XLE": {"eq_factor"}}
    _, candidate_symbols, added, _ = membership_delta(baseline, candidate, ["eq_*"], {"XLE"})
    assert candidate_symbols == ["XLF"]
    assert added == ["XLF"]


# ---------------------------------------------------------------------------
# attribute_gate_failures
# ---------------------------------------------------------------------------


def test_attribute_gate_failures_counts_every_failing_gate() -> None:
    """A row failing two gates at once counts under BOTH gates, and neither gate's
    sole_failure count increments for it."""
    row = _eligible_row("XLE", "eq_energy")
    row["passes_materiality"] = False  # a real non-eligible row (calibrator's own verdict)
    row["partial_loading"] = 0.10  # fails min_partial_loading (0.35)
    row["incremental_r2"] = 0.01  # fails min_incremental_r2 (0.05)
    result = attribute_gate_failures([row], _THRESHOLDS)
    assert result["partial_loading"]["count"] == 1
    assert result["incremental_r2"]["count"] == 1
    assert result["partial_loading"]["sole_failure"] == 0
    assert result["incremental_r2"]["sole_failure"] == 0


def test_attribute_gate_failures_sole_failure_distinct_from_count() -> None:
    row = _eligible_row("XLE", "eq_energy")
    row["passes_materiality"] = False
    row["materiality_sample_n"] = 100  # fails min_sample_n (756) only
    result = attribute_gate_failures([row], _THRESHOLDS)
    assert result["sample_n"]["count"] == 1
    assert result["sample_n"]["sole_failure"] == 1
    for gate in ("partial_loading", "ci_low", "incremental_r2", "sign_stability", "null_arm"):
        assert result[gate]["count"] == 0
        assert result[gate]["sole_failure"] == 0


def test_attribute_gate_failures_nan_statistic_counted_as_unmeasured() -> None:
    row = _eligible_row("XLE", "eq_energy")
    row["passes_materiality"] = False
    row["partial_loading"] = float("nan")
    result = attribute_gate_failures([row], _THRESHOLDS)
    assert result["unmeasured"] == 1
    for gate in ("sample_n", "partial_loading", "ci_low", "incremental_r2", "sign_stability"):
        assert result[gate]["count"] == 0


def test_attribute_gate_failures_null_statistic_counted_as_unmeasured() -> None:
    row = _eligible_row("XLE", "eq_energy")
    row["passes_materiality"] = False
    row["sign_stable_windows"] = None
    result = attribute_gate_failures([row], _THRESHOLDS)
    assert result["unmeasured"] == 1


def test_attribute_gate_failures_skips_already_eligible_rows() -> None:
    row = _eligible_row("XLE", "eq_energy")
    result = attribute_gate_failures([row], _THRESHOLDS)
    for gate in (
        "sample_n",
        "partial_loading",
        "ci_low",
        "incremental_r2",
        "sign_stability",
        "null_arm",
    ):
        assert result[gate]["count"] == 0
    assert result["unmeasured"] == 0


def test_attribute_gate_failures_null_arm_gate() -> None:
    row = _eligible_row("XLE", "eq_energy")
    row["passes_materiality"] = False
    row["null_arm_bh_p"] = 0.20  # fails null_arm_alpha (0.05)
    result = attribute_gate_failures([row], _THRESHOLDS)
    assert result["null_arm"]["count"] == 1
    assert result["null_arm"]["sole_failure"] == 1


# ---------------------------------------------------------------------------
# sign_stability_near_miss
# ---------------------------------------------------------------------------


def test_sign_stability_near_miss_passing_row_absent() -> None:
    """A row at (3, 3) passes (min_sign_stable_windows=3) and must not appear."""
    row = _eligible_row("XLE", "eq_energy")
    row["sign_stable_windows"] = 3
    row["sign_stable_windows_total"] = 3
    all_hist, sole_hist = sign_stability_near_miss([row], _THRESHOLDS)
    assert all_hist == {}
    assert sole_hist == {}


def test_sign_stability_near_miss_sole_failing_row_in_both_histograms() -> None:
    """A row at (2, 4) fails by one window and, when no other gate also fails,
    must appear in both histograms."""
    row = _eligible_row("XLE", "eq_energy")
    row["passes_materiality"] = False
    row["sign_stable_windows"] = 2
    row["sign_stable_windows_total"] = 4
    all_hist, sole_hist = sign_stability_near_miss([row], _THRESHOLDS)
    assert all_hist == {(2, 4): 1}
    assert sole_hist == {(2, 4): 1}


def test_sign_stability_near_miss_multi_failing_row_only_in_all_histogram() -> None:
    """A row failing sign-stability AND another gate appears in the all-failing
    histogram but not the sole-failing one."""
    row = _eligible_row("XLE", "eq_energy")
    row["passes_materiality"] = False
    row["sign_stable_windows"] = 2
    row["sign_stable_windows_total"] = 4
    row["partial_loading"] = 0.10  # also fails min_partial_loading
    all_hist, sole_hist = sign_stability_near_miss([row], _THRESHOLDS)
    assert all_hist == {(2, 4): 1}
    assert sole_hist == {}


def test_sign_stability_near_miss_empty_when_no_failures() -> None:
    row = _eligible_row("XLE", "eq_energy")
    all_hist, sole_hist = sign_stability_near_miss([row], _THRESHOLDS)
    assert all_hist == {}
    assert sole_hist == {}


def test_sign_stability_near_miss_unmeasured_row_excluded() -> None:
    row = _eligible_row("XLE", "eq_energy")
    row["passes_materiality"] = False
    row["sign_stable_windows"] = None
    all_hist, sole_hist = sign_stability_near_miss([row], _THRESHOLDS)
    assert all_hist == {}
    assert sole_hist == {}


# ---------------------------------------------------------------------------
# gate_value_distributions
# ---------------------------------------------------------------------------


def test_gate_value_distributions_order_statistics_over_failing_rows() -> None:
    rows = []
    for pl in (0.05, 0.10, 0.20):
        row = _eligible_row("SYM", "eq_x")
        row["partial_loading"] = pl
        rows.append(row)
    result = gate_value_distributions(rows, _THRESHOLDS)
    dist = result["partial_loading"]
    assert dist["n"] == 3
    assert dist["n_unmeasured"] == 0
    assert dist["min"] == 0.05
    assert dist["median"] == 0.10
    assert dist["max"] == 0.20


def test_gate_value_distributions_excludes_passing_rows() -> None:
    row = _eligible_row("SYM", "eq_x")  # partial_loading=0.50, passes
    result = gate_value_distributions([row], _THRESHOLDS)
    assert result["partial_loading"]["n"] == 0


def test_gate_value_distributions_nan_excluded_and_counted_separately() -> None:
    row = _eligible_row("SYM", "eq_x")
    row["partial_loading"] = float("nan")
    result = gate_value_distributions([row], _THRESHOLDS)
    dist = result["partial_loading"]
    assert dist["n"] == 0
    assert dist["n_unmeasured"] == 1
    assert dist["min"] is None


def test_gate_value_distributions_covers_four_scalar_gates() -> None:
    row = _eligible_row("SYM", "eq_x")
    row["materiality_sample_n"] = 100
    row["partial_loading_ci_low"] = 0.05
    result = gate_value_distributions([row], _THRESHOLDS)
    assert set(result.keys()) == {"sample_n", "partial_loading", "ci_low", "incremental_r2"}
    assert result["sample_n"]["n"] == 1
    assert result["ci_low"]["n"] == 1
    assert result["partial_loading"]["n"] == 0
    assert result["incremental_r2"]["n"] == 0


def test_gate_value_distributions_never_coerces_nan_to_zero() -> None:
    row = _eligible_row("SYM", "eq_x")
    row["materiality_sample_n"] = float("nan")
    result = gate_value_distributions([row], _THRESHOLDS)
    assert result["sample_n"]["n"] == 0
    assert result["sample_n"]["n_unmeasured"] == 1
    assert result["sample_n"]["min"] is None
    assert math.isnan(row["materiality_sample_n"])  # sanity: input untouched
