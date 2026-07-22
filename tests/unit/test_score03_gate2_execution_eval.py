"""Unit tests: Gate 2 execution-proof evaluation (SCORE-03).

Wave 0 stub -- scripts/analysis/score03_gate2_execution_eval.py does not exist yet.
These are RED-by-construction placeholders naming the concrete targets Wave 2's
SCORE-03 build plan (148-04) fills in. Do NOT import
scripts.analysis.score03_gate2_execution_eval at module scope: the module doesn't
exist yet, and a module-scope import would break `pytest --collect-only` with an
ImportError instead of a clean RED failure.

Analog: scripts/analysis/phase143_1_08_shadow_validation.py (this function minus
challenger/c6, plus a gate_evaluations INSERT, per CONTEXT.md D-08).
"""

from __future__ import annotations

import pytest


def test_cites_champion_143_1_08_numbers():
    """Gate 2 script cites the known-in-advance champion 143.1-08 pooled numbers
    (c2_ci_lower, c3_sharpe, c4_max_dd) verbatim from 143.1-08-SHADOW-VALIDATION.md
    section 6/7, rather than recomputing them from a different population (D-06).

    Wave 2 (148-04) implements scripts/analysis/score03_gate2_execution_eval.py's
    reproduction-tolerance assertion (fresh recompute matches baseline within 1e-6).
    """
    pytest.fail("Wave 0 stub - implemented in Wave 2 SCORE build plan")


def test_regime_stratified_companion_required():
    """A pooled Gate 2 verdict is never reported alone -- the regime-stratified
    companion (evaluate_frame_gate with group_key=(direction, regime),
    min_clusters=alpha.validation.regime_gate_min_clusters) must accompany every
    pooled FAIL/PASS in the same output/row (D-07).

    Wave 2 (148-04) wires evaluate_frame_gate's exact call shape into
    scripts/analysis/score03_gate2_execution_eval.py.
    """
    pytest.fail("Wave 0 stub - implemented in Wave 2 SCORE build plan")


def test_gate2_dry_run_writes_nothing():
    """--dry-run escape hatch: Gate 2 script computes and reports the verdict but
    writes zero rows to gate_evaluations, enabling dev-time testing of an otherwise
    irreversible, run-once-per-milestone gate (D-04).

    Wave 2 (148-04) adds the --dry-run flag per the cross-AI review fix.
    """
    pytest.fail("Wave 0 stub - implemented in Wave 2 SCORE build plan")


def test_gate2_evidence_payload_shape():
    """gate_evaluations row written by Gate 2 has the expected shape: gate_id
    ('gate2_execution', also serving as FRAME-04's formal re-run per D-08 -- never
    a second FRAME-04 gate_id), result, and an evidence jsonb payload containing
    both the pooled and regime-stratified verdict detail.

    Wave 2 (148-04) implements the actual INSERT INTO gate_evaluations statement.
    """
    pytest.fail("Wave 0 stub - implemented in Wave 2 SCORE build plan")
