"""Unit tests: Phase 166 fresh validation gate (gate166_frame_recalibration_eval).

Analog: tests/unit/test_score03_gate2_execution_eval.py -- these tests exercise the pure
evidence-assembly core (assemble_gate166_evidence and its helpers) on synthetic rows: the
frozen five criteria, the mandatory regime companion, gate_id derivation (D-04), and the new
population-footprint disclosure (Codex concern 2).

No DB, no Kafka. (The atomic write path + dry-run sentinel are tested in a follow-on commit,
Task 2.)
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from scripts.analysis.gate166_frame_recalibration_eval import (
    _GATE_IDS,
    _build_snapshot,
    _compute_population_footprint,
    _json_safe,
    assemble_gate166_evidence,
)


def _synthetic_rows(n_days: int = 8, tf: str = "5m", regime: str = "mid_bull") -> list[dict]:
    """Synthetic rows spanning 2 directions, a single (regime, tf) cell by default -- reused
    across tests that just need "some" OOS-shaped rows with a tf field (score03's fixture
    predates the tf column this plan's population footprint requires)."""
    rows = []
    base_day = datetime(2026, 1, 1, tzinfo=UTC)
    directions = ["long", "short"]
    day_offset = 0
    for direction in directions:
        for _ in range(n_days // 2):
            ts = base_day + timedelta(days=day_offset)
            rows.append(
                {
                    "bar_ts": ts,
                    "direction": direction,
                    "regime": regime,
                    "tf": tf,
                    "cluster_id": ts.date(),
                    "pnl_r": 0.1 if direction == "long" else -0.1,
                }
            )
            day_offset += 1
    return rows


def _apr_kwargs() -> dict:
    return {
        "min_n": 1,
        "bootstrap_max_n": 100,
        "bootstrap_batch": 50,
        "bootstrap_random_state": 42,
        "min_sharpe": 0.5,
        "max_drawdown_ratio": 0.25,
        "regime_gate_min_clusters": 2,
    }


def _snapshot(candidate: str = "scalar") -> dict:
    return _build_snapshot(
        oos_start=datetime(2026, 1, 1, tzinfo=UTC),
        candidate=candidate,
        weight_epoch="166-scalar-candidate",
        apr_values_used={"min_sharpe": 0.5, "max_drawdown_ratio": 0.25},
        input_population_row_count=8,
        fetch_sql_sha256="deadbeef",
    )


# ---------------------------------------------------------------------------
# Test 1: full evidence dict -- pooled criteria + regime companion + candidate + result
# ---------------------------------------------------------------------------


def test_assemble_gate166_evidence_returns_full_dict():
    """assemble_gate166_evidence(rows, candidate) returns a dict with the pooled frozen-five
    criteria + a regime companion list + the candidate label + a result of 'pass'/'fail' -- a
    statistical FAIL is a normal value, never an exception."""
    rows = _synthetic_rows()
    evidence = assemble_gate166_evidence(rows, "scalar", **_apr_kwargs(), snapshot=_snapshot())

    assert evidence["candidate"] == "scalar"
    assert evidence["result"] in ("pass", "fail")
    assert "pooled" in evidence
    for key in (
        "c1_min_60_days",
        "c2_ci_lower",
        "c2_ci_upper",
        "c2_passes",
        "c3_sharpe",
        "c3_passes",
        "c4_max_dd",
        "c4_passes",
        "c5_confident_loss",
        "c5_passes",
    ):
        assert key in evidence["pooled"], f"missing pooled criterion key: {key}"
    assert "regime_cells" in evidence
    assert len(evidence["regime_cells"]) > 0

    # A hostile min_sharpe (statistical FAIL) must never raise.
    hostile_kwargs = _apr_kwargs()
    hostile_kwargs["min_sharpe"] = 1000.0
    evidence_fail = assemble_gate166_evidence(
        rows, "scalar", **hostile_kwargs, snapshot=_snapshot()
    )
    assert evidence_fail["result"] == "fail"
    assert evidence_fail["pooled"]["c3_passes"] is False


# ---------------------------------------------------------------------------
# Test 2: same-bar_ts aggregation before cumulative walk (172 guard)
# ---------------------------------------------------------------------------


def test_same_bar_ts_rows_aggregated_before_cumulative_stat():
    """A fixture with 20+ tied bar_ts asserts aggregation fires: c4_max_dd is computed from
    the SUMMED per-bar_ts series, not a naive per-row cumulative walk. With 22 rows sharing
    exactly ONE bar_ts (11 long +0.1, 11 short -0.1 -- net zero at that instant), the
    aggregated series collapses to a single ~0.0 value and the drawdown must reflect that
    single aggregated point, not a 22-step naive walk that would show interim swings."""
    tied_ts = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for _i in range(11):
        rows.append(
            {
                "bar_ts": tied_ts,
                "direction": "long",
                "regime": "mid_bull",
                "tf": "5m",
                "cluster_id": tied_ts.date(),
                "pnl_r": 0.1,
            }
        )
        rows.append(
            {
                "bar_ts": tied_ts,
                "direction": "short",
                "regime": "mid_bull",
                "tf": "5m",
                "cluster_id": tied_ts.date(),
                "pnl_r": -0.1,
            }
        )
    assert len(rows) == 22

    from scripts.analysis.gate166_frame_recalibration_eval import _aggregate_pnl_by_bar_ts

    aggregated = _aggregate_pnl_by_bar_ts(rows)
    # All 22 rows share one bar_ts -- aggregation must collapse them to exactly 1 point.
    assert len(aggregated) == 1
    assert aggregated[0] == pytest.approx(0.0, abs=1e-9)

    # c1 fails (single day) but assembly must not raise, and n_days reflects 1 cluster.
    evidence = assemble_gate166_evidence(rows, "scalar", **_apr_kwargs(), snapshot=_snapshot())
    assert evidence["n_days"] == 1
    assert evidence["pooled"]["c1_min_60_days"] is False


# ---------------------------------------------------------------------------
# Test 3: regime companion always present; insufficient coverage excluded not failed (D-05)
# ---------------------------------------------------------------------------


def test_regime_companion_always_present_insufficient_excluded_not_failed():
    """The regime companion is ALWAYS present. A cell below min_clusters is marked
    coverage="insufficient" and its passes is None (excluded from, not counted as failing,
    the aggregate) -- disclose, don't gate (D-05)."""
    # mid_bull has 4 distinct days (>= min_clusters=2); low_bear has only 1 day (< 2).
    rows = _synthetic_rows(n_days=8, tf="5m", regime="mid_bull")
    sparse_rows = [
        {
            "bar_ts": datetime(2026, 6, 1, tzinfo=UTC),
            "direction": "long",
            "regime": "low_bear",
            "tf": "15m",
            "cluster_id": datetime(2026, 6, 1, tzinfo=UTC).date(),
            "pnl_r": 0.05,
        }
    ]
    all_rows = rows + sparse_rows

    evidence = assemble_gate166_evidence(all_rows, "scalar", **_apr_kwargs(), snapshot=_snapshot())
    assert "regime_cells" in evidence
    assert len(evidence["regime_cells"]) > 0

    insufficient_cells = [c for c in evidence["regime_cells"] if c["regime"] == "low_bear"]
    assert len(insufficient_cells) == 1
    assert insufficient_cells[0]["coverage"] == "insufficient"
    assert insufficient_cells[0]["passes"] is None

    evaluated_cells = [c for c in evidence["regime_cells"] if c["coverage"] == "evaluated"]
    assert all(c["regime"] != "low_bear" for c in evaluated_cells)


# ---------------------------------------------------------------------------
# Test 4: gate_id derivation -- never gate2_execution (D-04)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("candidate", ["scalar", "structural", "baseline"])
def test_gate_id_never_gate2_execution(candidate: str):
    """evidence["gate_id"] is derived from candidate and is one of
    gate166_scalar/gate166_structural/gate166_baseline -- never "gate2_execution" (D-04)."""
    rows = _synthetic_rows()
    evidence = assemble_gate166_evidence(
        rows, candidate, **_apr_kwargs(), snapshot=_snapshot(candidate)
    )
    assert evidence["gate_id"] != "gate2_execution"
    assert evidence["gate_id"] in {"gate166_scalar", "gate166_structural", "gate166_baseline"}
    assert evidence["gate_id"] == _GATE_IDS[candidate]


def test_unknown_candidate_raises():
    rows = _synthetic_rows()
    with pytest.raises(ValueError, match="unknown candidate"):
        assemble_gate166_evidence(rows, "not_a_candidate", **_apr_kwargs(), snapshot=_snapshot())


# ---------------------------------------------------------------------------
# Test 5: _json_safe converts non-finite floats
# ---------------------------------------------------------------------------


def test_json_safe_converts_non_finite_floats():
    payload = {
        "a": float("inf"),
        "b": float("-inf"),
        "c": float("nan"),
        "d": 1.5,
        "e": [float("inf"), 2.0],
        "f": "ok",
    }
    safe = _json_safe(payload)
    assert safe["a"] == "Infinity"
    assert safe["b"] == "-Infinity"
    assert safe["c"] == "NaN"
    assert safe["d"] == 1.5
    assert safe["e"] == ["Infinity", 2.0]
    assert safe["f"] == "ok"
    # Must be JSON-serializable after sanitization.
    json.dumps(safe)


# ---------------------------------------------------------------------------
# Test 6: population footprint reports counts; sparse cell visible (Codex concern 2)
# ---------------------------------------------------------------------------


def test_population_footprint_reports_counts_and_sparse_cell_visible():
    """evidence["population"] reports total frame_count, eligible-cell count, and a
    per-(regime,tf) frame counts map; a fixture with a deliberately sparse cell asserts that
    cell's low count is present and visible (Codex concern 2) -- a smaller/sparser candidate
    population cannot look artificially favorable without the disparity being visible."""
    dense_rows = _synthetic_rows(n_days=8, tf="5m", regime="mid_bull")  # 8 rows
    sparse_rows = [
        {
            "bar_ts": datetime(2026, 6, 1, tzinfo=UTC),
            "direction": "long",
            "regime": "high_bear",
            "tf": "1h",
            "cluster_id": datetime(2026, 6, 1, tzinfo=UTC).date(),
            "pnl_r": 0.05,
        }
    ]  # 1 row, deliberately sparse
    all_rows = dense_rows + sparse_rows

    population = _compute_population_footprint(all_rows)
    assert population["frame_count"] == len(all_rows) == 9
    assert population["eligible_cell_count"] == 2  # mid_bull.5m + high_bear.1h
    assert population["cell_frame_counts"]["mid_bull.5m"] == 8
    assert population["cell_frame_counts"]["high_bear.1h"] == 1  # sparse cell visible

    evidence = assemble_gate166_evidence(
        all_rows, "structural", **_apr_kwargs(), snapshot=_snapshot("structural")
    )
    assert evidence["population"] == population
    # Population counts are descriptive-only -- do not appear in the pass/fail computation
    # (result depends only on pooled c1-c5, asserted structurally: population dict has no
    # "passes"/"result" key of its own).
    assert "passes" not in evidence["population"]
    assert "result" not in evidence["population"]
