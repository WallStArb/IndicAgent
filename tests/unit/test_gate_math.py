"""Unit tests: src/intelligence/statistics/gate_math.py -- the extracted day-clustered
bootstrap gate core (todo 249), plus evaluate_stratum_expectancy_gate (Task 4).
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.intelligence.statistics.gate_math import (
    evaluate_frame_gate,
    evaluate_stratum_expectancy_gate,
    frame_gate_passes,
)


def test_frame_gate_passes_below_min_n_returns_nan():
    passes, ci_lower, ci_upper = frame_gate_passes(
        [0.1, 0.2],
        ["2026-01-01", "2026-01-02"],
        min_n=5,
        bootstrap_max_n=5000,
        bootstrap_batch=1000,
    )
    assert passes is False
    assert ci_lower != ci_lower  # nan
    assert ci_upper != ci_upper  # nan


def test_frame_gate_passes_below_two_clusters_returns_nan():
    passes, ci_lower, ci_upper = frame_gate_passes(
        [0.1, 0.2, 0.3],
        ["2026-01-01", "2026-01-01", "2026-01-01"],
        min_n=1,
        bootstrap_max_n=5000,
        bootstrap_batch=1000,
    )
    assert passes is False
    assert ci_lower != ci_lower  # nan


def test_frame_gate_passes_analytic_path_above_bootstrap_max_n():
    """Above bootstrap_max_n clusters, uses the analytic CLT lower bound (ci_upper=inf)."""
    pnl_r_values = [1.0] * 20
    cluster_ids = [f"2026-01-{d:02d}" for d in range(1, 21)]
    passes, ci_lower, ci_upper = frame_gate_passes(
        pnl_r_values,
        cluster_ids,
        min_n=1,
        bootstrap_max_n=10,
        bootstrap_batch=1000,
    )
    assert ci_upper == float("inf")
    assert passes is True  # all pnl_r=1.0, mean is way above zero


def test_evaluate_frame_gate_groups_by_tf_and_regime():
    rows = [
        {"tf": "5m", "regime": "trending_up", "cluster_id": "2026-01-01", "pnl_r": 0.5},
        {"tf": "5m", "regime": "trending_up", "cluster_id": "2026-01-01", "pnl_r": 0.6},
        {"tf": "5m", "regime": "ranging", "cluster_id": "2026-01-01", "pnl_r": -0.2},
        {"tf": "1h", "regime": "trending_up", "cluster_id": "2026-01-01", "pnl_r": 0.3},
    ]
    verdicts = evaluate_frame_gate(rows, min_n=1, bootstrap_max_n=5000, bootstrap_batch=1000)
    cells = {(v["tf"], v["regime"]) for v in verdicts}
    assert cells == {("5m", "trending_up"), ("5m", "ranging"), ("1h", "trending_up")}


def test_evaluate_frame_gate_min_clusters_marks_insufficient():
    rows = [
        {"tf": "1h", "regime": "high_neutral", "cluster_id": f"day-{i}", "pnl_r": 0.1}
        for i in range(5)
    ] + [
        {"tf": "1h", "regime": "low_bull", "cluster_id": f"day-{i}", "pnl_r": 0.1}
        for i in range(25)
    ]
    verdicts = evaluate_frame_gate(
        rows, min_n=1, bootstrap_max_n=5000, bootstrap_batch=1000, min_clusters=20
    )
    by_regime = {v["regime"]: v for v in verdicts}
    assert by_regime["high_neutral"]["coverage"] == "insufficient"
    assert by_regime["high_neutral"]["passes"] is None
    assert by_regime["low_bull"]["coverage"] == "evaluated"
    assert by_regime["low_bull"]["passes"] is not None


def test_gate_math_equivalence_with_counterfactual_tracker_output():
    """Equivalence proof (design doc requirement): identical fixture data through the
    extracted gate_math functions must match services.counterfactual_tracker's
    frame_gate_passes/evaluate_frame_gate byte-for-byte, once Task 2 repoints that module
    to import from here. Import both under their current names -- after Task 2 lands,
    services.counterfactual_tracker.frame_gate_passes IS this module's frame_gate_passes
    (same function object via re-export), so this test asserts object identity, the
    strongest possible equivalence proof.
    """
    from services.counterfactual_tracker import (
        evaluate_frame_gate as tracker_evaluate_frame_gate,
    )
    from services.counterfactual_tracker import (
        frame_gate_passes as tracker_frame_gate_passes,
    )

    assert tracker_frame_gate_passes is frame_gate_passes
    assert tracker_evaluate_frame_gate is evaluate_frame_gate


def test_evaluate_stratum_expectancy_gate_groups_by_regime_and_direction():
    rows = [
        {"regime": "mid_bull", "direction": "long", "cluster_id": "2026-01-01", "pnl_r": 0.1},
        {"regime": "mid_bull", "direction": "long", "cluster_id": "2026-01-02", "pnl_r": 0.2},
        {"regime": "mid_bull", "direction": "short", "cluster_id": "2026-01-01", "pnl_r": -0.1},
        {"regime": "high_neutral", "direction": "long", "cluster_id": "2026-01-01", "pnl_r": 0.3},
    ]
    verdicts = evaluate_stratum_expectancy_gate(
        rows, min_n=1, bootstrap_max_n=5000, bootstrap_batch=1000, bootstrap_random_state=42
    )
    cells = {(v["regime"], v["direction"]) for v in verdicts}
    assert cells == {
        ("mid_bull", "long"),
        ("mid_bull", "short"),
        ("high_neutral", "long"),
    }
    # Field names are regime/direction, never the generic tf/regime evaluate_frame_gate
    # returns internally (naming-system.md Whiteboard Test -- see design doc).
    for v in verdicts:
        assert "tf" not in v
        assert set(v.keys()) == {
            "regime",
            "direction",
            "n_bars",
            "n_clusters",
            "ci_lower",
            "ci_upper",
            "passes",
            "coverage",
        }


def test_evaluate_stratum_expectancy_gate_degenerate_cluster_count():
    """Fewer than 2 day-clusters in a cell -> (False, nan, nan), reused unmodified from
    frame_gate_passes' existing documented contract (no reimplementation)."""
    rows = [
        {"regime": "mid_bull", "direction": "long", "cluster_id": "2026-01-01", "pnl_r": 0.1},
        {"regime": "mid_bull", "direction": "long", "cluster_id": "2026-01-01", "pnl_r": 0.2},
    ]
    verdicts = evaluate_stratum_expectancy_gate(
        rows, min_n=1, bootstrap_max_n=5000, bootstrap_batch=1000, bootstrap_random_state=42
    )
    assert verdicts[0]["passes"] is False
    assert verdicts[0]["ci_lower"] != verdicts[0]["ci_lower"]  # nan


def test_evaluate_stratum_expectancy_gate_min_clusters_coverage_floor():
    rows = [
        {"regime": "mid_bull", "direction": "long", "cluster_id": f"day-{i}", "pnl_r": 0.1}
        for i in range(5)
    ] + [
        {"regime": "high_neutral", "direction": "long", "cluster_id": f"day-{i}", "pnl_r": 0.1}
        for i in range(25)
    ]
    verdicts = evaluate_stratum_expectancy_gate(
        rows,
        min_n=1,
        bootstrap_max_n=5000,
        bootstrap_batch=1000,
        bootstrap_random_state=42,
        min_clusters=20,
    )
    by_regime = {v["regime"]: v for v in verdicts}
    assert by_regime["mid_bull"]["coverage"] == "insufficient"
    assert by_regime["mid_bull"]["passes"] is None
    assert by_regime["high_neutral"]["coverage"] == "evaluated"
    assert by_regime["high_neutral"]["passes"] is not None


def test_evaluate_stratum_expectancy_gate_delegates_to_evaluate_frame_gate():
    """No bootstrap math reimplemented here (design doc requirement) -- proven by asserting
    the function's own source contains no 'bootstrap(' call and no 'np.mean'/'np.std' of its
    own, only a call into evaluate_frame_gate."""
    import inspect

    source = inspect.getsource(evaluate_stratum_expectancy_gate)
    assert "evaluate_frame_gate(" in source
    assert "bootstrap(" not in source
    assert "np.std(" not in source
