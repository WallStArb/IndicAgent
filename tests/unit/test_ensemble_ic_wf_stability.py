"""Unit tests: EIC-03 walk_forward_stable computation (fold IC-MAGNITUDE ratio).

D-142A-R1 (LOCKED decision, see 142A-CONTEXT.md): walk_forward_stable is the
max/min ratio of per-fold IC MAGNITUDE, NOT per-fold IC Sharpe. ROADMAP EIC-03
wording says "IC Sharpe max/min fold ratio < 3x", but a reliable per-fold IC
Sharpe would need sharpe_min_windows(30) * sharpe_window_size(2000) = 60,000
bars inside ONE fold's test slice -- orders of magnitude above per-cell
per-fold N (each fold test slice is gated at min_reliable_n=100).
ic_engine.py's own walk-forward gate (lines 969-973) likewise uses fold IC
scalars, not fold Sharpe -- this proxy matches existing codebase methodology.

This test file is intentionally documented as testing the MAGNITUDE proxy by
design, not a stand-in for a future fold-Sharpe implementation.

No DB, no Kafka. Pure numpy.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ensemble_ic_engine import compute_walk_forward_stable


def test_stable_fold_ics_below_ratio_threshold():
    """[0.3, 0.4, 0.5]: max/min = 0.5/0.3 = 1.67 < 3.0 -> stable."""
    fold_ics = [0.3, 0.4, 0.5]
    assert compute_walk_forward_stable(fold_ics, wf_stability_ratio=3.0) is True


def test_unstable_fold_ics_above_ratio_threshold():
    """[0.1, 0.9]: ratio = 9 >= 3.0 -> unstable."""
    fold_ics = [0.1, 0.9]
    assert compute_walk_forward_stable(fold_ics, wf_stability_ratio=3.0) is False


def test_fewer_than_two_folds_is_unstable():
    """Folds with < 2 entries cannot compute a max/min ratio -> false."""
    assert compute_walk_forward_stable([], wf_stability_ratio=3.0) is False
    assert compute_walk_forward_stable([0.3], wf_stability_ratio=3.0) is False


def test_mixed_sign_fold_ics_use_magnitude_not_raw_value():
    """[-0.3, 0.5]: magnitude ratio = 0.5/0.3 = 1.67 < 3.0 -> stable.

    A naive (non-magnitude) max/min on the raw signed values would produce a
    nonsensical or sign-flipped ratio; the D-142A-R1 proxy takes abs() first.
    """
    fold_ics = [-0.3, 0.5]
    assert compute_walk_forward_stable(fold_ics, wf_stability_ratio=3.0) is True


def test_zero_min_magnitude_is_unstable():
    """A fold IC of exactly 0.0 makes the ratio undefined -> treat as unstable."""
    fold_ics = [0.0, 0.5]
    assert compute_walk_forward_stable(fold_ics, wf_stability_ratio=3.0) is False


def test_boundary_ratio_exactly_at_threshold_is_unstable():
    """Ratio strictly < threshold required; ratio == threshold does not pass."""
    # 0.25/0.05 == 5.0 exactly (exact binary fractions -- avoids floating-point
    # representation drift that 0.3/0.1 would introduce).
    fold_ics = [0.05, 0.25]
    assert compute_walk_forward_stable(fold_ics, wf_stability_ratio=5.0) is False
