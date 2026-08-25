"""Unit tests for ops_broadcast_feature_audit.py's pure classification logic
(2026-07-29, follow-up to todo 203; migrated 2026-08-25 to the three-way verdict
contract + persistence, Phase 173 / todo 270).

vix_z/yield_slope_z were confirmed bit-identical across every symbol at a given
bar_ts -- correctly, since they're legitimately single macro series broadcast to
every row. Any significance test that pools symbols together has the same
pseudo-replication exposure as the (buggy) canaries for any feature with this
structure. This script classifies which active features have it, empirically.

The classifier returns one of three verdicts -- 'broadcast', 'idiosyncratic',
'inconclusive' -- rather than a bool. The temporal-variance guard exists because a
never-fired event flag (e.g. sweep_detected, manip_strength) can be constant across
symbols AND constant across bar_ts within a narrow sample window, which the old
boolean contract misclassified 'broadcast' with zero real evidence of bar_ts-derived
structure. 'inconclusive' means "no evidence either way," not "assumed broadcast."

No DB, no asyncio -- pure function tests only, plus a SQL-shape assertion for the
--persist write path's JSONB merge idiom (never a live database).
"""

from __future__ import annotations

import numpy as np

from scripts.ops.alpha.ops_broadcast_feature_audit import (
    _PERSIST_UPDATE_SQL,
    _classify_broadcast,
    _count_finite_values_total,
)


class TestClassifyBroadcast:
    def test_identical_values_across_symbols_classified_broadcast(self) -> None:
        values_by_bar_ts = {
            "t1": np.array([1.5, 1.5, 1.5]),
            "t2": np.array([2.0, 2.0, 2.0]),
        }
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) == "broadcast"

    def test_varying_values_classified_idiosyncratic(self) -> None:
        values_by_bar_ts = {"t1": np.array([1.5, 1.6, 1.4])}
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) == "idiosyncratic"

    def test_single_bar_ts_with_variance_fails_even_if_others_pass(self) -> None:
        values_by_bar_ts = {
            "t1": np.array([1.5, 1.5, 1.5]),
            "t2": np.array([2.0, 2.1, 2.0]),
        }
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) == "idiosyncratic"

    def test_single_finite_value_in_only_group_is_inconclusive(self) -> None:
        """SEMANTIC CHANGE from the pre-2026-08-25 contract, where this fixture
        classified `True` (vacuously broadcast -- the loop never found a
        contradicting group). A single bar_ts group carries no temporal axis to
        compare against, so the classifier now correctly abstains: absence of
        cross-symbol variance in the ONE group sampled is not evidence the feature
        is bar_ts-derived broadcast structure rather than coincidentally constant
        in this narrow window."""
        values_by_bar_ts = {"t1": np.array([1.5])}
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) == "inconclusive"

    def test_nan_values_excluded_before_comparison(self) -> None:
        # Second group added so the single-group inconclusive rule (above) does not
        # mask what this test is actually named for -- NaN exclusion within a group.
        values_by_bar_ts = {
            "t1": np.array([1.5, 1.5, np.nan]),
            "t2": np.array([2.0, 2.0, np.nan]),
        }
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) == "broadcast"

    def test_epsilon_tolerance_allows_tiny_float_noise(self) -> None:
        # Second group added so the single-group inconclusive rule does not mask
        # what this test is actually named for -- epsilon tolerance within a group.
        values_by_bar_ts = {
            "t1": np.array([1.5, 1.5 + 1e-12]),
            "t2": np.array([2.5, 2.5 + 1e-12]),
        }
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) == "broadcast"

    def test_epsilon_tolerance_rejects_real_difference(self) -> None:
        values_by_bar_ts = {"t1": np.array([1.5, 1.5001])}
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) == "idiosyncratic"

    def test_empty_dict_is_inconclusive(self) -> None:
        """SEMANTIC CHANGE from the pre-2026-08-25 contract, where this fixture
        classified `True` ("nothing contradicts broadcast, matching the loop's
        natural behavior"). That rationale is now understood to be wrong: an empty
        input carries zero evidence in either direction, so vacuous truth is not a
        safe default for a classification that feeds a production significance-test
        gate. Absence of evidence now abstains rather than defaults to broadcast."""
        assert _classify_broadcast({}, epsilon=1e-9) == "inconclusive"

    def test_globally_constant_feature_is_inconclusive_not_broadcast(self) -> None:
        """The sweep_detected / manip_strength false-positive case: a rare,
        event-driven feature that never fired in the sampled window is constant
        across symbols (spread == 0 in every group) AND constant across bar_ts
        (every group's representative value is identical) -- zero real evidence
        of bar_ts-derived broadcast structure, so the verdict must be
        'inconclusive', never 'broadcast'."""
        values_by_bar_ts = {
            "t1": np.array([0.0, 0.0, 0.0]),
            "t2": np.array([0.0, 0.0, 0.0]),
        }
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) == "inconclusive"

    def test_idiosyncratic_check_runs_before_temporal_guard(self) -> None:
        """Ordering is pinned: the cross-symbol check runs FIRST. t1 fails the
        cross-symbol check (spread 0.1 > epsilon); t2's representative (2.0)
        differs from t1's would-be representative (~1.5), which is exactly the
        kind of evidence the temporal guard looks for -- but an idiosyncratic
        verdict must never be downgraded to 'inconclusive' or upgraded past
        'idiosyncratic' by that evidence."""
        values_by_bar_ts = {
            "t1": np.array([1.5, 1.6]),
            "t2": np.array([2.0, 2.0]),
        }
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) == "idiosyncratic"


class TestCountFiniteValuesTotal:
    def test_counts_finite_values_across_all_bar_ts(self) -> None:
        values_by_bar_ts = {
            "t1": np.array([1.5, 1.5, 1.5]),
            "t2": np.array([2.0, 2.0, np.nan]),
        }
        assert _count_finite_values_total(values_by_bar_ts) == 5

    def test_all_nan_returns_zero(self) -> None:
        values_by_bar_ts = {
            "t1": np.array([np.nan, np.nan]),
            "t2": np.array([np.nan, np.nan]),
        }
        assert _count_finite_values_total(values_by_bar_ts) == 0

    def test_empty_dict_returns_zero(self) -> None:
        assert _count_finite_values_total({}) == 0

    def test_single_bar_ts_counts_correctly(self) -> None:
        values_by_bar_ts = {"t1": np.array([1.5, 2.0, np.nan, 3.0])}
        assert _count_finite_values_total(values_by_bar_ts) == 3


class TestPersistUpdateSqlShape:
    """The --persist write path must merge into concept_registry.metadata, never
    replace it wholesale -- a bare `SET metadata = $n` would silently destroy the
    six pre-existing metadata keys every production row already carries (tier,
    apr_namespace, formula_short, normalization, migrated_from, migrated_by).
    Asserted on the SQL string shape, never against a live database."""

    def test_merge_idiom_present(self) -> None:
        assert "metadata || jsonb_build_object" in _PERSIST_UPDATE_SQL

    def test_no_bare_metadata_replacement(self) -> None:
        assert "SET metadata = $" not in _PERSIST_UPDATE_SQL

    def test_scoped_to_gate_joined_rows(self) -> None:
        assert "concept_gate" in _PERSIST_UPDATE_SQL

    def test_scoped_to_active_status(self) -> None:
        assert "cr.status = 'active'" in _PERSIST_UPDATE_SQL
