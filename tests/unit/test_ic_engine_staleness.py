"""Unit tests: ic_engine post-run lifecycle hook staleness gauge + alert
(Phase 143 Plan 03, LIFECYCLE-05).

_evaluate_staleness is a pure function -- tested directly for precise (age_days, alert)
assertions. The integration-style tests below additionally exercise
_get_prior_ic_engine_completion's manifest-history + first-run-fallback behavior
through the full hook, reusing the fake psycopg2 connection/registry doubles from
test_ic_engine_lifecycle_hook. A real CorpusManifest is written to a tmp_path so the
manifest-history path reads back genuine behavior (no CorpusManifest monkeypatching).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from observability.corpus_manifest import CorpusManifest
from services.ic_engine import _evaluate_staleness, _run_lifecycle_hook
from tests.unit.test_ic_engine_lifecycle_hook import (
    _T1,
    _cell,
    _FakeLifecycleConn,
    _FakeManifest,
    _FakeRegistryService,
    _make_config,
)

# ---------------------------------------------------------------------------
# Pure function: _evaluate_staleness
# ---------------------------------------------------------------------------


def test_evaluate_staleness_fires_when_age_exceeds_threshold():
    now = datetime(2026, 7, 10, tzinfo=UTC)
    prior = now - timedelta(days=10)
    age_days, alert = _evaluate_staleness(prior, now, staleness_alert_days=5)
    assert age_days == 10
    assert alert is True


def test_evaluate_staleness_no_alert_when_within_threshold():
    now = datetime(2026, 7, 10, tzinfo=UTC)
    prior = now - timedelta(days=2)
    age_days, alert = _evaluate_staleness(prior, now, staleness_alert_days=5)
    assert age_days == 2
    assert alert is False


def test_evaluate_staleness_boundary_equal_to_threshold_no_alert():
    """age_days == threshold does not fire (strictly greater-than semantics)."""
    now = datetime(2026, 7, 10, tzinfo=UTC)
    prior = now - timedelta(days=5)
    age_days, alert = _evaluate_staleness(prior, now, staleness_alert_days=5)
    assert age_days == 5
    assert alert is False


def test_evaluate_staleness_first_run_fallback_age_zero_no_alert():
    now = datetime(2026, 7, 10, tzinfo=UTC)
    age_days, alert = _evaluate_staleness(None, now, staleness_alert_days=5)
    assert age_days == 0
    assert alert is False


def test_evaluate_staleness_naive_prior_completion_treated_as_utc():
    """A naive prior_completion (no tzinfo) must not raise -- treated as UTC."""
    now = datetime(2026, 7, 10, tzinfo=UTC)
    prior_naive = datetime(2026, 6, 30)  # 10 days prior, no tzinfo
    age_days, alert = _evaluate_staleness(prior_naive, now, staleness_alert_days=5)
    assert age_days == 10
    assert alert is True


# ---------------------------------------------------------------------------
# Integration: hook wires _get_prior_ic_engine_completion -> _evaluate_staleness
# ---------------------------------------------------------------------------


def _write_prior_manifest(manifest_dir: Path, completed_at: datetime) -> None:
    """Write a real ic_engine manifest file whose timestamp is `completed_at`,
    simulating a genuinely prior, already-completed run."""
    prior = CorpusManifest("ic_engine", manifest_dir)
    prior.data["timestamp"] = completed_at.isoformat()
    prior.mark_success()
    prior.write()


def _run_hook(tmp_path: Path, cells: list[dict]) -> None:
    config = _make_config()
    ew = [
        {
            "tf": c["tf"],
            "regime": c["regime"],
            "feature_name": c["feature_name"],
            "weight_version": "v1",
            "weight": 0.0,
        }
        for c in cells
    ]
    conn = _FakeLifecycleConn(cells, ensemble_weight_rows=ew)
    feature_names = {c["feature_name"] for c in cells}
    registry = _FakeRegistryService({name: {"status": "active"} for name in feature_names})
    _run_lifecycle_hook(conn, registry, config, _T1, _FakeManifest(tmp_path))


def test_hook_reads_prior_manifest_and_completes_without_error(tmp_path):
    """Prior run 10 days ago in the manifest history -- hook runs to completion
    (age computation + alert logging happen internally, no exception)."""
    _write_prior_manifest(tmp_path, datetime.now(UTC) - timedelta(days=10))
    cells = [
        _cell(
            "featA",
            "5m",
            "r0",
            ic_ci_lower=0.03,
            passes_fdr=True,
            n_independent=1000,
            status="active",
        )
    ]
    _run_hook(tmp_path, cells)


def test_hook_first_run_no_manifest_no_fallback_rows_completes_without_error(tmp_path):
    """No prior manifest AND no fallback feature_ic_scores rows (all corpus rows carry
    this run's own training_window_end) -- first-run fallback, no exception."""
    cells = [
        _cell(
            "featA",
            "5m",
            "r0",
            ic_ci_lower=0.03,
            passes_fdr=True,
            n_independent=1000,
            status="active",
        )
    ]
    _run_hook(tmp_path, cells)
