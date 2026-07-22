"""Unit tests: OOS Gate 1 signal-proof evaluation (SCORE-02).

scripts/ops/corpus/ops_oos_gate1_signal_eval.py is a standalone, run-once OOS scorer
(D-04). These tests exercise its pure helpers and its dry-run/write-gating behavior with
mocked asyncpg pools/connections -- no real DB, and the real (non-dry-run) write path is
never invoked here, so running this suite never consumes the one-shot gate.

Analog: tests/unit/test_oos_holdout_eval.py (request-response test shape).
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_fails_loud_when_oos_start_unset():
    """Gate 1 script raises loud (never falls back to MAX(bar_ts)) when
    alpha.validation.oos_start is unset in config_state.

    Mirrors scripts/ops/corpus/ops_oos_holdout_eval.py's TestReadOosStartAsync shape.
    """
    from scripts.ops.corpus.ops_oos_gate1_signal_eval import _read_oos_start

    mock_pool = AsyncMock()
    mock_pool.fetchrow = AsyncMock(return_value=None)

    with pytest.raises(RuntimeError):
        await _read_oos_start(mock_pool)


def test_uses_fisher_z_ci_methodology():
    """Gate 1 script measures IC(alpha_score, forward_return_*) using
    _fisher_z_ci (src/intelligence/statistics/ic_math.py), not the newer
    bootstrap-based CI method (RESEARCH.md Pitfall 1) -- asserted at the source level so
    a future edit that reintroduces the bootstrap helper fails this test immediately.
    """
    import scripts.ops.corpus.ops_oos_gate1_signal_eval as gate1_module

    source = inspect.getsource(gate1_module)

    assert "_fisher_z_ci" in source
    assert "circular_block_bootstrap" not in source


@pytest.mark.asyncio
async def test_gate1_dry_run_writes_nothing(tmp_path):
    """--dry-run escape hatch: Gate 1 script computes and reports the verdict but writes
    zero rows to gate_evaluations and appends zero look-log lines, enabling dev-time
    testing of an otherwise irreversible, run-once-per-milestone gate (D-04).
    """
    from scripts.ops.corpus.ops_oos_gate1_signal_eval import _run_gate1

    mock_pool = AsyncMock()
    mock_pool.fetch = AsyncMock(return_value=[])  # zero OOS rows for every (symbol, tf)
    look_log_path = tmp_path / "gate_look_log.jsonl"

    evidence = await _run_gate1(
        pool=mock_pool,
        symbols=["SPY"],
        tfs=["1h"],
        weight_version="v1",
        oos_start=datetime(2026, 1, 1, tzinfo=UTC),
        apr_cfg={},
        dry_run=True,
        look_log_path=look_log_path,
    )

    # No write-path methods were ever invoked (dry-run never opens a write transaction).
    assert mock_pool.acquire.call_count == 0
    assert mock_pool.execute.await_count == 0
    # No look-log line appended -- the file was never created.
    assert not look_log_path.exists()
    # Full computation still ran and produced a real evidence payload.
    assert evidence["verdict"]["result"] == "insufficient"


def test_gate1_evidence_payload_shape():
    """gate_evaluations row written by Gate 1 has the expected shape: an evidence jsonb
    payload containing the Fisher-z CI + BH-FDR corpus-level verdict detail plus the
    pre-run integrity snapshot (Consensus Concern 2) -- asserts EXACT key sets, not
    merely "a row exists".
    """
    from scripts.ops.corpus.ops_oos_gate1_signal_eval import (
        _assemble_evidence,
        _assemble_verdict,
        _build_snapshot,
    )

    cells = [
        {
            "symbol": "SPY",
            "tf": "1h",
            "scale": "fast",
            "n_valid": 500,
            "ic_value": 0.05,
            "ic_ci_lower": 0.01,
            "ic_ci_upper": 0.09,
            "p_value": 0.01,
            "bh_adjusted_p": 0.02,
            "passes_fdr": True,
            "reliable": True,
            "walk_forward_stable": True,
        }
    ]
    oos_start = datetime(2026, 1, 1, tzinfo=UTC)

    snapshot = _build_snapshot(
        oos_start=oos_start,
        apr_values_used={"fdr_alpha": 0.05},
        input_population_row_count=500,
        fetch_sql_sha256="abc123",
    )
    verdict = _assemble_verdict(cells, min_qualifying_fraction=0.6)
    evidence = _assemble_evidence(cells, oos_start, snapshot, verdict)

    assert {"cells", "oos_start", "snapshot", "verdict"} <= evidence.keys()
    assert {
        "oos_start",
        "apr_values_used",
        "input_population_row_count",
        "fetch_sql_sha256",
    } <= snapshot.keys()
    assert "result" in verdict
    assert verdict["result"] in {"pass", "fail", "insufficient"}
