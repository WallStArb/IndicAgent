"""Unit tests: EIC-02 IC decay curve -> hold_max_bars selection.

_select_hold_bars_from_decay is a pure module-level function in
services/ensemble_ic_engine.py. Given a list of per-(scale) cell dicts for one
(symbol, tf, regime) group, it walks the canonical scale order
[fast, mid, slow, extended] and returns the lookahead_bars of the last scale
where the edge (ic_sharpe) is still above decay_threshold, subject to a
mandatory significance + sufficiency gate (review finding #6):

- passes_fdr=false cells are EXCLUDED even if ic_sharpe is high (statistically
  indistinguishable from noise -- must never set a load-bearing hold_bars).
- reliable=false cells are ALSO EXCLUDED even if passes_fdr=true (passed FDR
  on insufficient N; ic_sharpe is unstable at low N).
- walk_forward_stable=false cells are ALSO EXCLUDED even if passes_fdr=true and
  reliable=true (passed cross-sectional significance but did not reproduce
  out-of-sample across folds -- added 2026-07-09 to match EIC-04's own gate).
- If every cell in the group is unqualified (fails any of the three gates), the
  function returns None -- signal to the caller to skip calibration for this
  (symbol, tf, regime) and leave the prior APR value untouched.

No DB, no Kafka. Pure Python.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ensemble_ic_engine import _select_hold_bars_from_decay

_SCALE_TO_BARS = {"fast": 1, "mid": 5, "slow": 20, "extended": 60}


def _cell(
    lookahead: str,
    ic_sharpe,
    passes_fdr: bool = True,
    reliable: bool = True,
    walk_forward_stable: bool = True,
) -> dict:
    return {
        "lookahead": lookahead,
        "ic_sharpe": ic_sharpe,
        "passes_fdr": passes_fdr,
        "reliable": reliable,
        "walk_forward_stable": walk_forward_stable,
    }


def test_decay_at_mid_selects_mid_bars():
    """ic_sharpe = [0.5, 0.4, 0.05, -0.1] (fast/mid/slow/extended), threshold=0.1.

    slow (0.05) is the first scale below threshold -> return the PRECEDING
    scale's (mid) lookahead_bars = 5.
    """
    cells = [
        _cell("fast", 0.5),
        _cell("mid", 0.4),
        _cell("slow", 0.05),
        _cell("extended", -0.1),
    ]
    result = _select_hold_bars_from_decay(cells, decay_threshold=0.1, scale_to_bars=_SCALE_TO_BARS)
    assert result == (5, False)


def test_all_scales_above_threshold_selects_extended():
    """ic_sharpe = [0.5, 0.4, 0.3, 0.2], all above 0.1 -> edge persists to extended (60).

    No scale ever crossed decay_threshold, so this is right-censored (todo 088): we
    confirmed non-decay up to 60 bars but don't know if it persists beyond that.
    """
    cells = [
        _cell("fast", 0.5),
        _cell("mid", 0.4),
        _cell("slow", 0.3),
        _cell("extended", 0.2),
    ]
    result = _select_hold_bars_from_decay(cells, decay_threshold=0.1, scale_to_bars=_SCALE_TO_BARS)
    assert result == (60, True)


def test_decay_at_fast_selects_minimal_hold():
    """fast itself (0.05) is already below threshold -> minimal hold_bars = 1.

    A confirmed decay crossing at the very first scale -- not censored (todo 088).
    """
    cells = [
        _cell("fast", 0.05),
        _cell("mid", 0.03),
        _cell("slow", -0.02),
        _cell("extended", -0.1),
    ]
    result = _select_hold_bars_from_decay(cells, decay_threshold=0.1, scale_to_bars=_SCALE_TO_BARS)
    assert result == (1, False)


def test_unqualified_cell_excluded_despite_high_ic_sharpe_noise_case():
    """passes_fdr=false cell with ic_sharpe=0.9 is EXCLUDED -- treated as no data,
    never as 'edge alive'. Remaining qualifying cells still determine hold_bars.
    """
    cells = [
        _cell("fast", 0.9, passes_fdr=False, reliable=True),  # excluded -- noise
        _cell("mid", 0.4, passes_fdr=True, reliable=True),
        _cell("slow", 0.05, passes_fdr=True, reliable=True),
        _cell("extended", -0.1, passes_fdr=True, reliable=True),
    ]
    result = _select_hold_bars_from_decay(cells, decay_threshold=0.1, scale_to_bars=_SCALE_TO_BARS)
    # fast is excluded from the walk entirely; qualifying order starts at mid.
    # mid(0.4) above threshold, slow(0.05) below -> preceding qualifying scale is mid -> 5.
    assert result == (5, False)


def test_unreliable_cell_excluded_despite_passing_fdr_low_n_case():
    """reliable=false cell with ic_sharpe=0.9 and passes_fdr=true is ALSO EXCLUDED
    (review finding #6 -- FDR does not guarantee sufficient N).
    """
    cells = [
        _cell("fast", 0.9, passes_fdr=True, reliable=False),  # excluded -- low N
        _cell("mid", 0.4, passes_fdr=True, reliable=True),
        _cell("slow", 0.05, passes_fdr=True, reliable=True),
        _cell("extended", -0.1, passes_fdr=True, reliable=True),
    ]
    result = _select_hold_bars_from_decay(cells, decay_threshold=0.1, scale_to_bars=_SCALE_TO_BARS)
    assert result == (5, False)


def test_unstable_cell_excluded_despite_passing_fdr_and_reliable():
    """walk_forward_stable=false cell with ic_sharpe=0.9, passes_fdr=true, reliable=true
    is ALSO EXCLUDED (2026-07-09 extension of review finding #6 -- cross-sectional
    significance does not guarantee the effect reproduces out-of-sample across folds;
    this brings EIC-02's gate back in sync with EIC-04's own phase-gate query, which
    already required all three conditions).
    """
    cells = [
        _cell("fast", 0.9, passes_fdr=True, reliable=True, walk_forward_stable=False),  # excluded
        _cell("mid", 0.4, passes_fdr=True, reliable=True, walk_forward_stable=True),
        _cell("slow", 0.05, passes_fdr=True, reliable=True, walk_forward_stable=True),
        _cell("extended", -0.1, passes_fdr=True, reliable=True, walk_forward_stable=True),
    ]
    result = _select_hold_bars_from_decay(cells, decay_threshold=0.1, scale_to_bars=_SCALE_TO_BARS)
    assert result == (5, False)


def test_all_cells_unqualified_returns_none():
    """Every cell fails passes_fdr OR reliable -> no qualifying signal -> None.

    Caller interprets None as: skip this (symbol, tf, regime), leave the prior
    APR value in place -- do not write a noise-derived or low-N hold_bars.
    """
    cells = [
        _cell("fast", 0.9, passes_fdr=False, reliable=True),
        _cell("mid", 0.4, passes_fdr=True, reliable=False),
        _cell("slow", 0.05, passes_fdr=False, reliable=False),
        _cell("extended", -0.1, passes_fdr=False, reliable=True),
    ]
    result = _select_hold_bars_from_decay(cells, decay_threshold=0.1, scale_to_bars=_SCALE_TO_BARS)
    assert result is None


def test_none_ic_sharpe_skipped_not_treated_as_below_threshold():
    """A cell with ic_sharpe=None (no data) is skipped in the walk, not treated
    as a below-threshold crossing point.
    """
    cells = [
        _cell("fast", 0.5),
        _cell("mid", None),
        _cell("slow", 0.3),
        _cell("extended", 0.2),
    ]
    result = _select_hold_bars_from_decay(cells, decay_threshold=0.1, scale_to_bars=_SCALE_TO_BARS)
    # mid has no data (skipped); slow and extended both above threshold ->
    # edge persists to extended. No crossing observed -> right-censored (todo 088).
    assert result == (60, True)


def test_empty_cell_list_returns_none():
    """No cells at all for this group -> None (nothing to calibrate from)."""
    result = _select_hold_bars_from_decay([], decay_threshold=0.1, scale_to_bars=_SCALE_TO_BARS)
    assert result is None


def test_extended_never_qualifies_returns_last_measured_scale_not_ceiling():
    """extended is absent from cells entirely (never qualified) -- fast/mid/slow all
    above threshold. Must NOT default to the extended ceiling (60): that would claim
    "edge confirmed to persist to 60 bars" with zero data behind it. Correct answer is
    slow's bars (20) -- the longest scale actually measured and confirmed non-decaying.
    """
    cells = [
        _cell("fast", 0.5),
        _cell("mid", 0.4),
        _cell("slow", 0.3),
        # no "extended" cell at all
    ]
    result = _select_hold_bars_from_decay(cells, decay_threshold=0.1, scale_to_bars=_SCALE_TO_BARS)
    # No crossing observed within the measured scales -> right-censored (todo 088).
    assert result == (20, True)


def test_only_fast_qualifies_above_threshold_returns_fast_bars_not_ceiling():
    """Only fast ever qualifies and stays above threshold -- mid/slow/extended all
    absent/excluded. Must return fast's bars (1), not the extended ceiling (60).
    """
    cells = [_cell("fast", 0.5)]
    result = _select_hold_bars_from_decay(cells, decay_threshold=0.1, scale_to_bars=_SCALE_TO_BARS)
    # No crossing observed -> right-censored (todo 088).
    assert result == (1, True)
