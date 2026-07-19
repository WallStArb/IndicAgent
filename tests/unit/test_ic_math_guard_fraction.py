"""Unit tests: evaluate_guard_fraction (ic_decay guard stratified calibration, todo 144).

Pure Python -- no DB, no Kafka. Exercises the decision logic in isolation: cold-start
rails, empirical-band takeover at min_history, MAD-zero degeneracy guard, rail
intersection clamping, the min-cells floor, and both guard tails.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.intelligence.statistics.ic_math import GuardVerdict, evaluate_guard_fraction

_RAILS = dict(min_cells=100, min_history=8, band_z=3.0, rail_lo=0.85, rail_hi=0.995)


def test_below_min_cells_is_insufficient_cells():
    """A stratum with fewer active cells than the floor is never hold-authoritative."""
    verdict = evaluate_guard_fraction(0.99, n_cells=50, history=[], **_RAILS)
    assert verdict.status == "insufficient_cells"


def test_min_cells_boundary_is_inclusive():
    """Exactly min_cells active cells IS evaluated (>=, not >)."""
    verdict = evaluate_guard_fraction(0.50, n_cells=100, history=[], **_RAILS)
    assert verdict.status != "insufficient_cells"


def test_cold_start_within_seeded_rails_is_ok():
    """No history yet: the live-incident fraction (0.9618) sits inside the seeded
    rails [0.85, 0.995] -- this is the exact regression case for the original bug,
    where the old 0.60 threshold incorrectly held on ordinary variation."""
    verdict = evaluate_guard_fraction(0.9618, n_cells=57000, history=[], **_RAILS)
    assert verdict.status == "ok"
    assert verdict.band_source == "seeded"


def test_cold_start_above_rail_hi_holds():
    verdict = evaluate_guard_fraction(0.999, n_cells=57000, history=[], **_RAILS)
    assert verdict.status == "hold_high"
    assert verdict.band_source == "seeded"


def test_cold_start_below_rail_lo_alerts():
    verdict = evaluate_guard_fraction(0.50, n_cells=57000, history=[], **_RAILS)
    assert verdict.status == "alert_low"
    assert verdict.band_source == "seeded"


def test_history_below_min_history_still_uses_seeded_rails():
    """7 prior evaluations (one short of min_history=8) must not activate the
    empirical band yet."""
    history = [0.96] * 7
    verdict = evaluate_guard_fraction(0.9618, n_cells=57000, history=history, **_RAILS)
    assert verdict.band_source == "seeded"


def test_empirical_band_activates_at_min_history():
    """8 prior evaluations activates the empirical (median/MAD) band."""
    history = [0.96, 0.97, 0.96, 0.98, 0.95, 0.97, 0.96, 0.97]
    verdict = evaluate_guard_fraction(0.9618, n_cells=57000, history=history, **_RAILS)
    assert verdict.band_source == "empirical"
    assert verdict.status == "ok"


def test_empirical_band_can_tighten_but_never_widen_past_rails():
    """History clustered very tightly around 0.96 would (via median +/- 3*1.4826*MAD)
    produce a band narrower than the seeded rails -- confirm it's clamped INSIDE
    [rail_lo, rail_hi], never wider."""
    history = [0.960, 0.961, 0.960, 0.962, 0.959, 0.961, 0.960, 0.961]
    verdict = evaluate_guard_fraction(0.9618, n_cells=57000, history=history, **_RAILS)
    assert verdict.band_lo >= _RAILS["rail_lo"]
    assert verdict.band_hi <= _RAILS["rail_hi"]
    assert verdict.band_hi < _RAILS["rail_hi"]  # actually tightened, not just clamped to rail


def test_zero_mad_degenerate_history_falls_back_to_seeded_band():
    """All 8 history values identical -> MAD=0 -> a naive band would collapse to a
    single point and flag nearly anything. Must fall back to the seeded rails
    instead of a zero-width band."""
    history = [0.96] * 8
    verdict = evaluate_guard_fraction(0.9618, n_cells=57000, history=history, **_RAILS)
    assert verdict.status == "ok"
    assert verdict.band_lo <= 0.9618 <= verdict.band_hi
    assert verdict.band_hi - verdict.band_lo > 0.001  # not degenerate


def test_empirical_band_flags_genuine_excursion_above_recent_history():
    """History steady at ~0.96; a genuine spike to 0.999 must hold even though
    0.999 < rail_hi (0.995 is exceeded here, so this also trips the rail -- use a
    value between the tightened empirical band and the rail to isolate the
    empirical-band effect specifically)."""
    history = [0.960, 0.961, 0.960, 0.962, 0.959, 0.961, 0.960, 0.961]
    # Empirical hi from this history is well under 0.99; 0.994 is inside the rail
    # (0.995) but should still exceed the tightened empirical band.
    verdict = evaluate_guard_fraction(0.994, n_cells=57000, history=history, **_RAILS)
    assert verdict.status == "hold_high"
    assert verdict.band_source == "empirical"


def test_verdict_is_frozen_dataclass():
    verdict = evaluate_guard_fraction(0.90, n_cells=57000, history=[], **_RAILS)
    assert isinstance(verdict, GuardVerdict)
    import dataclasses

    assert dataclasses.is_dataclass(verdict)
    try:
        verdict.status = "ok"  # type: ignore[misc]
        raised = False
    except dataclasses.FrozenInstanceError:
        raised = True
    assert raised
