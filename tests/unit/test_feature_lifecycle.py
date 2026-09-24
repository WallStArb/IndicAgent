"""Unit tests for services/feature_lifecycle.py (todo 402).

The decision rules are the ones ic_engine's retired post-run hook applied (material-fail
predicate, sign awareness, guard scoping); these tests port its invariants onto the pure
functions. The ledger tests pin what changed: evidence counts once per window.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest

import services.feature_lifecycle as fl
from services.feature_lifecycle import (
    Evaluation,
    LifecycleConfig,
    LifecycleGate,
    derive_feature_transition,
    evidence_key,
    feature_verdict,
    flag_cell,
    guard_cells,
    latest_per_window,
    staleness,
    stratum_guard,
    window_guard_status,
)

_W1 = datetime(2025, 6, 24, 5, 15, tzinfo=UTC)
_W2 = datetime(2025, 12, 24, 5, 15, tzinfo=UTC)
_W3 = datetime(2026, 6, 24, 5, 15, tzinfo=UTC)
_T0 = datetime(2026, 9, 1, tzinfo=UTC)


def _config(**overrides) -> LifecycleConfig:
    base = dict(
        lookahead_mid={"5m": 6, "15m": 2, "1h": 2, "1d": 2},
        materiality_threshold=0.005,
        guard_band_z=3.0,
        guard_min_cells=100,
        guard_min_history=8,
        guard_history_window=20,
        recovery_min_observations=2000,
        recovery_min_passes=2,
        demotion_min_consecutive=2,
        meta_fdr_min_fraction=0.5,
        staleness_alert_days=5,
        weight_version="v1",
        sign_symmetric=False,
    )
    base.update(overrides)
    return LifecycleConfig(**base)


def _cell(**overrides) -> dict:
    base = dict(
        feature_name="f",
        tf="1d",
        regime="high_bull",
        regime_scope="cross_sectional",
        lookahead_bars=2,
        ic_ci_lower=0.01,
        ic_ci_upper=0.05,
        ic_sign=1,
        passes_fdr=True,
        n_independent=500,
        ic_sharpe_hac=0.3,
        standing_weight=0.2,
    )
    base.update(overrides)
    return base


def _flagged(config: LifecycleConfig, **overrides) -> dict:
    cell = _cell(**overrides)
    flag_cell(cell, config)
    return cell


def _eval(window, passed, *, status="active", at=None, guard="ok", n_obs=1000) -> Evaluation:
    return Evaluation(
        window_end=window,
        evaluated_status=status,
        passed=passed,
        n_observations=n_obs,
        guard_status=guard,
        evaluated_at=at or _T0,
    )


_GATE = LifecycleGate(
    demotion_min_consecutive=2, recovery_min_passes=2, recovery_min_observations=2000
)


# ---------------------------------------------------------------------------
# Material-fail predicate
# ---------------------------------------------------------------------------


class TestFlagCell:
    def test_failing_weighted_cell_is_material(self):
        cell = _flagged(_config(), ic_ci_lower=-0.05, standing_weight=0.2)
        assert cell["_failed"] and cell["_material_fail"]

    def test_materiality_boundary_is_strict(self):
        # weight x |bound| == threshold is not material (strict >), just above is.
        at = _flagged(_config(), ic_ci_lower=-0.01, standing_weight=0.5)
        above = _flagged(_config(), ic_ci_lower=-0.011, standing_weight=0.5)
        assert at["_failed"] and not at["_material_fail"]
        assert above["_material_fail"]

    def test_zero_standing_weight_never_material(self):
        cell = _flagged(_config(), ic_ci_lower=-0.5, passes_fdr=False, standing_weight=0.0)
        assert cell["_failed"] and not cell["_material_fail"]

    def test_fdr_failure_alone_fails(self):
        cell = _flagged(_config(), passes_fdr=False)
        assert cell["_failed"]

    def test_sign_symmetric_significant_contrarian_not_failed(self):
        cell = _flagged(
            _config(sign_symmetric=True), ic_sign=-1, ic_ci_lower=-0.05, ic_ci_upper=-0.01
        )
        assert not cell["_failed"]
        assert cell["_signed_margin"] == pytest.approx(0.01)

    def test_sign_symmetric_straddling_contrarian_fails(self):
        cell = _flagged(
            _config(sign_symmetric=True),
            ic_sign=-1,
            ic_ci_lower=-0.05,
            ic_ci_upper=0.01,
            standing_weight=1.0,
        )
        # Material on the bound nearest zero on its own side (ic_ci_upper), not ic_ci_lower.
        assert cell["_failed"] and cell["_material_fail"]

    def test_flag_off_matches_long_only_predicate(self):
        # Off: a significant contrarian still fails on ic_ci_lower <= 0 (pre-Component-E).
        cell = _flagged(_config(), ic_sign=-1, ic_ci_lower=-0.05, ic_ci_upper=-0.01)
        assert cell["_failed"]
        assert cell["_signed_margin"] == -0.05


# ---------------------------------------------------------------------------
# Per-feature verdicts and guard scoping
# ---------------------------------------------------------------------------


class TestFeatureVerdict:
    def test_active_passes_below_floor(self):
        config = _config()
        cells = [_flagged(config), _flagged(config, ic_ci_lower=-0.05)]  # 1 of 2 material
        verdict = feature_verdict("active", cells, config)
        # demote_fraction 0.5 is not < floor 0.5 -> fails
        assert verdict.statistic == 0.5 and not verdict.passed

    def test_active_with_no_material_cells_passes(self):
        config = _config()
        verdict = feature_verdict("active", [_flagged(config), _flagged(config)], config)
        assert verdict.passed and verdict.n_observations == 1000

    def test_active_detail_reports_worst_cell(self):
        config = _config()
        cells = [_flagged(config, regime="a"), _flagged(config, regime="b", ic_ci_lower=-0.2)]
        verdict = feature_verdict("active", cells, config)
        assert verdict.detail["worst_regime"] == "b"
        assert verdict.detail["worst_ci_bound"] == -0.2

    def test_shadow_uses_fdr_pass_fraction(self):
        config = _config()
        cells = [_flagged(config), _flagged(config, passes_fdr=False)]
        verdict = feature_verdict("shadow_only", cells, config)
        assert verdict.statistic == 0.5 and verdict.passed

    @pytest.mark.parametrize("status", ["candidate", "deprecated"])
    def test_ungoverned_status_has_no_verdict(self, status):
        config = _config()
        assert feature_verdict(status, [_flagged(config)], config) is None


def test_guard_cells_keep_preexisting_scopes_and_drop_season_labels():
    """Moved from ic_engine's _lifecycle_guard_cells tests (Phase 176 plan 04,
    T-176-04-03): the three routed scopes pass; earnings-season cells, which have no
    market_regimes row by construction, never reach the regime-label mapping."""
    rows = [
        _cell(regime="trending_up", regime_scope="cross_sectional"),
        _cell(regime="calm", regime_scope="symbol_hmm"),
        _cell(regime="in_season", regime_scope="earnings_season"),
        _cell(regime="breadth_vol_high__in_season", regime_scope="earnings_season"),
    ]
    kept = guard_cells(rows, {"f": "active"})
    assert [c["regime"] for c in kept] == ["trending_up", "calm"]


def test_guard_cells_filter_by_scope_value_not_label_string():
    source = inspect.getsource(guard_cells)
    assert "earnings_season" in source
    assert "in_season" not in source and "off_season" not in source


def test_guard_cells_keep_active_non_earnings_only():
    cells = [
        _cell(feature_name="a"),
        _cell(feature_name="a", regime_scope="earnings_season"),
        _cell(feature_name="s"),
    ]
    kept = guard_cells(cells, {"a": "active", "s": "shadow_only"})
    assert kept == [cells[0]]


@pytest.mark.parametrize(
    "statuses,expected",
    [
        ([], "insufficient_cells"),
        (["insufficient_cells", "insufficient_cells"], "insufficient_cells"),
        (["uncalibrated", "insufficient_cells"], "uncalibrated"),
        (["ok", "uncalibrated"], "ok"),
        (["ok", "alert_low"], "alert_low"),
        (["alert_low", "hold_high", "uncalibrated"], "hold_high"),
    ],
)
def test_window_guard_status(statuses, expected):
    assert window_guard_status(statuses) == expected


class TestStratumGuard:
    """Todo 407: a stratum holds only on change against its own calibrated history."""

    def test_no_history_never_holds_even_at_total_failure(self):
        # The 176-08 cross-asset case: ~100% failing, no history -> no claim.
        assert stratum_guard(1.0, 500, [], _config()).status == "uncalibrated"

    def test_short_history_is_uncalibrated(self):
        assert stratum_guard(0.999, 500, [0.99] * 7, _config()).status == "uncalibrated"

    def test_small_stratum_is_insufficient(self):
        assert stratum_guard(1.0, 50, [0.9] * 10, _config()).status == "insufficient_cells"

    def test_calibrated_stratum_judged_against_own_band_not_a_global_rail(self):
        # A structurally ~99.8% slice is normal against its own history...
        hist = [0.997, 0.998, 0.999, 0.998, 0.997, 0.999, 0.998, 0.998]
        assert stratum_guard(0.998, 500, hist, _config()).status == "ok"
        # ...and an equity-like slice jumping far above its own band holds.
        eq = [0.95, 0.96, 0.955, 0.96, 0.95, 0.958, 0.952, 0.957]
        assert stratum_guard(0.999, 500, eq, _config()).status == "hold_high"

    def test_zero_spread_history_makes_no_claim(self):
        assert stratum_guard(1.0, 500, [0.9] * 8, _config()).status == "ok"


# ---------------------------------------------------------------------------
# Evidence key
# ---------------------------------------------------------------------------


class TestEvidenceKey:
    rule = _config().rule_fingerprint()

    def test_independent_of_cell_order(self):
        cells = [_cell(regime="a"), _cell(regime="b")]
        assert evidence_key("active", "ok", cells, self.rule) == evidence_key(
            "active", "ok", cells[::-1], self.rule
        )

    @pytest.mark.parametrize(
        "change",
        [
            {"status": "shadow_only"},
            {"guard_status": "hold_high"},
            {"rule": {**_config(materiality_threshold=0.01).rule_fingerprint()}},
            {"cells": [_cell(ic_ci_lower=0.011)]},
        ],
    )
    def test_moves_with_any_input(self, change):
        base = dict(status="active", guard_status="ok", cells=[_cell()], rule=self.rule)
        changed = {**base, **change}
        assert evidence_key(**base) != evidence_key(**changed)


# ---------------------------------------------------------------------------
# Ledger derivation -- the point of todo 402
# ---------------------------------------------------------------------------


class TestDerivation:
    def test_single_failing_window_does_not_demote(self):
        assert derive_feature_transition("active", None, [_eval(_W1, False)], _GATE) is None

    def test_two_failing_windows_demote(self):
        t = derive_feature_transition("active", None, [_eval(_W1, False), _eval(_W2, False)], _GATE)
        assert t.to_status == "shadow_only" and t.reason == "demotion_performance"
        assert t.n_windows == 2 and t.evidence.window_end == _W2

    def test_recomputing_one_window_never_counts_as_new_evidence(self):
        # The bug todo 402's original fix would have introduced: same window, re-evaluated
        # after a code change, must not reach demotion_min_consecutive on its own.
        evals = [_eval(_W1, False, at=_T0 + timedelta(days=d)) for d in range(5)]
        assert derive_feature_transition("active", None, evals, _GATE) is None

    def test_latest_evaluation_of_a_window_supersedes(self):
        evals = [
            _eval(_W1, False),
            _eval(_W2, False, at=_T0),
            _eval(_W2, True, at=_T0 + timedelta(days=1)),
        ]
        assert derive_feature_transition("active", None, evals, _GATE) is None

    def test_intervening_pass_resets_streak(self):
        evals = [_eval(_W1, False), _eval(_W2, True), _eval(_W3, False)]
        assert derive_feature_transition("active", None, evals, _GATE) is None

    def test_streak_orders_by_window_not_evaluation_time(self):
        # W3 evaluated first, W1/W2 replayed later: trailing run by window_end is W2, W3.
        evals = [
            _eval(_W3, False, at=_T0),
            _eval(_W1, True, at=_T0 + timedelta(days=1)),
            _eval(_W2, False, at=_T0 + timedelta(days=2)),
        ]
        assert derive_feature_transition("active", None, evals, _GATE).n_windows == 2

    def test_held_windows_are_not_evidence(self):
        evals = [_eval(_W1, False), _eval(_W2, False, guard="hold_high")]
        assert derive_feature_transition("active", None, evals, _GATE) is None

    def test_evidence_before_entering_status_is_ignored(self):
        since = _T0 + timedelta(days=10)
        evals = [_eval(_W1, False, at=_T0), _eval(_W2, False, at=since + timedelta(days=1))]
        assert derive_feature_transition("active", since, evals, _GATE) is None

    def test_evidence_under_another_status_is_ignored(self):
        evals = [_eval(_W1, False, status="shadow_only"), _eval(_W2, False)]
        assert derive_feature_transition("active", None, evals, _GATE) is None

    def test_per_concept_override_threshold(self):
        gate = LifecycleGate(3, 2, 2000)
        evals = [_eval(_W1, False), _eval(_W2, False)]
        assert derive_feature_transition("active", None, evals, gate) is None

    def test_promotion_needs_passes_and_observations(self):
        passes = [_eval(_W1, True, status="shadow_only"), _eval(_W2, True, status="shadow_only")]
        t = derive_feature_transition("shadow_only", None, passes, _GATE)
        assert t.to_status == "active" and t.reason == "promotion"
        thin = [
            _eval(_W1, True, status="shadow_only", n_obs=500),
            _eval(_W2, True, status="shadow_only", n_obs=500),
        ]
        assert derive_feature_transition("shadow_only", None, thin, _GATE) is None

    def test_observations_sum_once_per_window(self):
        evals = [
            _eval(_W1, True, status="shadow_only", n_obs=1500, at=_T0 + timedelta(days=d))
            for d in range(4)
        ] + [_eval(_W2, True, status="shadow_only", n_obs=400)]
        assert derive_feature_transition("shadow_only", None, evals, _GATE) is None

    @pytest.mark.parametrize("status", ["candidate", "deprecated"])
    def test_ungoverned_status_never_transitions(self, status):
        evals = [_eval(_W1, False, status=status), _eval(_W2, False, status=status)]
        assert derive_feature_transition(status, None, evals, _GATE) is None


def test_latest_per_window_orders_by_window():
    evals = [_eval(_W2, True), _eval(_W1, False), _eval(_W1, True, at=_T0 + timedelta(days=1))]
    out = latest_per_window(evals)
    assert [e.window_end for e in out] == [_W1, _W2]
    assert out[0].passed is True


# ---------------------------------------------------------------------------
# Staleness gauge (LIFECYCLE-05, alert-only)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("gap_days,alert", [(6, True), (5, False), (3, False)])
def test_staleness_threshold(gap_days, alert):
    this_run = datetime(2026, 9, 24, tzinfo=UTC)
    assert staleness(this_run - timedelta(days=gap_days), this_run, 5) == (gap_days, alert)


@pytest.mark.parametrize("prior,this", [(None, _T0), (_T0, None)])
def test_staleness_unknown_end_never_alerts(prior, this):
    assert staleness(prior, this, 5) == (0, False)


# ---------------------------------------------------------------------------
# Source contracts
# ---------------------------------------------------------------------------


def test_node_never_writes_ensemble_weights():
    source = inspect.getsource(fl)
    assert "INSERT INTO ensemble_weights" not in source
    assert "UPDATE ensemble_weights" not in source


def test_cells_query_pins_weight_version_and_never_orders_by_computed_at():
    assert "ew.weight_version = $1" in fl._CELLS_SQL
    assert "mid.lookahead_bars = fis.lookahead_bars" in fl._CELLS_SQL
    assert "fis.regime_scope <> 'earnings_season'" in fl._CELLS_SQL
    assert "computed_at" not in fl._CELLS_SQL


def test_guard_history_reads_only_earlier_windows_once_each():
    assert "training_window_end < $2" in fl._GUARD_HISTORY_SQL
    assert "DISTINCT ON (subject, training_window_end)" in fl._GUARD_HISTORY_SQL


def test_ledger_upsert_refreshes_recency_on_identical_evidence():
    sql = fl._UPSERT_EVALUATION_SQL
    assert "ON CONFLICT (concept_id, window_end, evidence_key)" in sql
    assert "evaluated_at = EXCLUDED.evaluated_at" in sql


def test_promotion_attests_fdr():
    source = inspect.getsource(fl.FeatureLifecycle._apply)
    assert 'fdr_passed=True if t.to_status == "active" else None' in source
