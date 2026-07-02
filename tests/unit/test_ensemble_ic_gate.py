"""Unit tests: EIC-04 phase-gate fraction evaluation.

_evaluate_gate is a pure importable helper in
scripts/ops/alpha/ops_ensemble_ic_gate.py. Given n_qualifying, n_total, and the
APR-sourced min_qualifying_fraction threshold, it returns (passed, fraction)
without ever hardcoding the threshold and without crashing on n_total=0.

No DB, no Kafka. Pure Python.
"""

from __future__ import annotations

import sys
from pathlib import Path

_scripts_alpha_dir = Path(__file__).parent.parent.parent / "scripts" / "ops" / "alpha"
if str(_scripts_alpha_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_alpha_dir))

from ops_ensemble_ic_gate import _evaluate_gate


def test_gate_passes_when_fraction_meets_threshold():
    """75/100 = 0.75 >= 0.60 -> PASS."""
    passed, fraction = _evaluate_gate(n_qualifying=75, n_total=100, min_qualifying_fraction=0.60)
    assert passed is True
    assert fraction == 0.75


def test_gate_fails_when_fraction_below_threshold():
    """40/100 = 0.40 < 0.60 -> FAIL."""
    passed, fraction = _evaluate_gate(n_qualifying=40, n_total=100, min_qualifying_fraction=0.60)
    assert passed is False
    assert fraction == 0.40


def test_gate_fails_with_zero_qualifying():
    """0/100 = 0.0 < 0.60 -> FAIL."""
    passed, fraction = _evaluate_gate(n_qualifying=0, n_total=100, min_qualifying_fraction=0.60)
    assert passed is False
    assert fraction == 0.0


def test_gate_handles_zero_total_without_zero_division_error():
    """n_total=0 (empty table / no cells) -> (False, 0.0), no ZeroDivisionError."""
    passed, fraction = _evaluate_gate(n_qualifying=0, n_total=0, min_qualifying_fraction=0.60)
    assert passed is False
    assert fraction == 0.0
