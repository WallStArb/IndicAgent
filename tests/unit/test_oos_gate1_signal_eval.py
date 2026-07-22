"""Unit tests: OOS Gate 1 signal-proof evaluation (SCORE-02).

Wave 0 stub -- scripts/ops/corpus/ops_oos_gate1_signal_eval.py does not exist yet.
These are RED-by-construction placeholders naming the concrete targets Wave 2's
SCORE-02 build plan (148-03) fills in. Do NOT import
scripts.ops.corpus.ops_oos_gate1_signal_eval at module scope: the module doesn't exist
yet, and a module-scope import would break `pytest --collect-only` with an ImportError
instead of a clean RED failure.

Analog: tests/unit/test_oos_holdout_eval.py (request-response test shape).
"""

from __future__ import annotations

import pytest


def test_fails_loud_when_oos_start_unset():
    """Gate 1 script raises loud (never falls back to MAX(bar_ts)) when
    alpha.validation.oos_start is unset in config_state.

    Wave 2 (148-03) implements the fail-loud OOS-boundary read pattern, mirroring
    services/ensemble_ic_engine.py lines 952-967 / scripts/ops/corpus/
    ops_oos_holdout_eval.py lines 114-130.
    """
    pytest.fail("Wave 0 stub - implemented in Wave 2 SCORE build plan")


def test_uses_fisher_z_ci_methodology():
    """Gate 1 script measures IC(alpha_score, forward_return_*) using
    _fisher_z_ci (src/intelligence/statistics/ic_math.py), not
    ic_engine.py's newer circular_block_bootstrap_ic_serial (RESEARCH.md Pitfall 1).

    Wave 2 (148-03) wires this methodology into
    scripts/ops/corpus/ops_oos_gate1_signal_eval.py.
    """
    pytest.fail("Wave 0 stub - implemented in Wave 2 SCORE build plan")


def test_gate1_dry_run_writes_nothing():
    """--dry-run escape hatch: Gate 1 script computes and reports the verdict but
    writes zero rows to gate_evaluations, enabling dev-time testing of an otherwise
    irreversible, run-once-per-milestone gate (D-04).

    Wave 2 (148-03) adds the --dry-run flag per the cross-AI review fix.
    """
    pytest.fail("Wave 0 stub - implemented in Wave 2 SCORE build plan")


def test_gate1_evidence_payload_shape():
    """gate_evaluations row written by Gate 1 has the expected shape: gate_id
    ('gate1_signal'), result, and an evidence jsonb payload containing the
    Fisher-z CI + BH-FDR corpus-level verdict detail.

    Wave 2 (148-03) implements the actual INSERT INTO gate_evaluations statement.
    """
    pytest.fail("Wave 0 stub - implemented in Wave 2 SCORE build plan")
