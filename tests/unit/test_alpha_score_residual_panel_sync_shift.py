"""RED-first regression test for todo 372: Panel's synchronous-shift null must apply
the SAME real calendar-date offset to every symbol in the family, not a per-symbol
modular offset (the bug -- `k % (that symbol's own active-date count)` -- silently
degrades the null from a shared panel-wide shift into independent per-symbol shifts
whenever active-date counts vary across symbols, understating the true false-positive
rate whenever returns are correlated across symbols on the same date).

Tests `_panel_synchronous_shift_indices`, the pure helper this fix extracts so the
shift/pairing logic is directly testable without threading or RNG plumbing.
"""

import numpy as np

from scripts.analysis.alpha_score_residual_single_security_15m import (
    Panel,
    _panel_synchronous_shift_indices,
)


def test_shift_uses_same_calendar_offset_for_every_symbol():
    """6-date shared calendar. Symbol A trades every day (dense). Symbol B is
    absent on the last 3 dates (started late). For shift k=1, the SAME real
    calendar-date offset (one day back) must be used for both symbols: a
    target date's return pairs with the score from the date one calendar
    position earlier, whenever the symbol has equal-count data on both.

    Encoding: `scores[row] = calendar position of that row` for every row, for
    both symbols -- so the correct shifted score at target position `pos` is
    exactly `(pos - k) % n_cal`, independent of which symbol is being read,
    as long as that symbol has data at both the target and source position.
    """
    n_cal = 6
    k = 1

    # Symbol A: active on all 6 calendar positions, one row each, absolute
    # rows 0..5. scores[row] = calendar position of that row (0..5).
    cal_start_a = np.array([0, 1, 2, 3, 4, 5], dtype=np.int64)
    cal_len_a = np.array([1, 1, 1, 1, 1, 1], dtype=np.int64)

    # Symbol B: active only on calendar positions 0, 1, 2 (started late),
    # absolute rows 6, 7, 8. Positions 3, 4, 5 have cal_len=0 (inactive).
    cal_start_b = np.array([6, 7, 8, 0, 0, 0], dtype=np.int64)
    cal_len_b = np.array([1, 1, 1, 0, 0, 0], dtype=np.int64)

    scores = np.array([0, 1, 2, 3, 4, 5, 0, 1, 2], dtype=np.float64)

    ret_idx_a, score_idx_a = _panel_synchronous_shift_indices(cal_start_a, cal_len_a, n_cal, k)
    ret_idx_b, score_idx_b = _panel_synchronous_shift_indices(cal_start_b, cal_len_b, n_cal, k)

    # Symbol A: active everywhere, so every one of the 6 calendar positions is
    # usable. Target position pos pairs with shifted position (pos - 1) % 6.
    # Expected (target_position, source_position) pairs: (0,5),(1,0),(2,1),
    # (3,2),(4,3),(5,4) -- i.e. scores read at source position == shifted
    # value, always (pos - 1) % 6.
    expected_scores_a = [(p - k) % n_cal for p in range(n_cal)]
    assert sorted(scores[score_idx_a].tolist()) == sorted(expected_scores_a)

    # Symbol B: only positions 0,1,2 are active (cal_len > 0). A position is
    # usable only when BOTH it and its shifted source position are active
    # for B. shifted = [(pos-1)%6 for pos in 0..5] = [5,0,1,2,3,4].
    #   pos=0 -> shifted=5 -> B inactive at 5 -> excluded
    #   pos=1 -> shifted=0 -> B active at both 1 and 0 -> USABLE, score=scores at B's row for position 0 = 0
    #   pos=2 -> shifted=1 -> B active at both 2 and 1 -> USABLE, score=scores at B's row for position 1 = 1
    #   pos=3,4,5 -> B inactive at the true position itself -> excluded
    # So exactly 2 usable positions for B, with paired scores [0, 1] (order
    # not asserted -- only the multiset of what B contributes).
    assert sorted(scores[score_idx_b].tolist()) == [0, 1]
    assert len(ret_idx_b) == 2

    # THE core panel-synchronicity property this bug violates: A and B must
    # be shifted by the SAME real calendar-date offset (k=1 calendar
    # position back), not by their own independent active-date-count moduli
    # (old bug: A's m=6 -> k%6=1; B's m=3 -> k%3=1 -- coincidentally equal
    # here, so this specific k wouldn't distinguish old vs new code; the
    # point of this test is the CORRECT positive-control behavior, verified
    # by direct index arithmetic above, not a differential vs. the old bug).
    # A stronger differential check follows in the next test.


def test_shift_offset_differs_from_buggy_per_symbol_modulus():
    """Direct differential test: pick k and per-symbol active-date counts
    such that the OLD bug's `k % m` (m = that symbol's own active-date
    count) would select a DIFFERENT calendar offset than the correct
    shared-calendar shift -- proving the fix's arithmetic is not just
    "close enough" to the bug but genuinely different where it matters.

    9-date calendar. Symbol A active on all 9 (m_bug_a = 9). Symbol B
    active on only 4 of them, positions 0,1,2,3 (m_bug_b = 4). k=5.

    Old bug for B: k % m_bug_b = 5 % 4 = 1 (a 1-BLOCK shift within B's own
    4-block list -- NOT a 5-calendar-position shift).
    Correct behavior for B: shifted = (pos - 5) % 9 -- a genuine 5-real-day
    shift, wrapping around the FULL 9-date calendar, not B's own 4-date
    sublist.
    These are different operations; assert the fix performs the LATTER by
    checking a target position whose two candidate results disagree.
    """
    n_cal = 9
    k = 5

    cal_start_b = np.array([10, 11, 12, 13, 0, 0, 0, 0, 0], dtype=np.int64)
    cal_len_b = np.array([1, 1, 1, 1, 0, 0, 0, 0, 0], dtype=np.int64)
    scores = np.zeros(20, dtype=np.float64)
    scores[10:14] = [100, 101, 102, 103]  # position-tagged scores for B's 4 rows

    # Correct (fixed) behavior: shifted = (pos - 5) % 9.
    # For target pos=2 (B is active there): shifted = (2-5)%9 = 6 -> B is
    # INACTIVE at position 6 -> pos=2 must be EXCLUDED under correct logic.
    # The old per-symbol-modulus bug, applied to B's OWN 4-block list
    # (m=4): treats "pos=2" as the 3rd of B's own 4 active blocks (index 2),
    # shifts by k%m = 5%4 = 1 -> selects B's own block at index (2+1)%4 = 3
    # -> that IS a valid (bugged) result (B's own 4th block, score=103) --
    # i.e. the bug would silently produce a result for exactly the case the
    # correct fix must exclude.
    ret_idx, score_idx = _panel_synchronous_shift_indices(cal_start_b, cal_len_b, n_cal, k)

    # Correct fix: position 2's TRUE row (absolute index 12) must NOT appear
    # in ret_idx, because position 2 has no valid shifted-source pairing.
    assert 12 not in ret_idx, (
        "position 2 (B's 3rd active date) was paired despite its shifted "
        "source position (6) being inactive for B -- this is the old "
        "per-symbol-modulus bug's signature, not the fixed shared-calendar shift"
    )


def test_sync_shift_null_p_runs_via_real_panel_with_uneven_symbol_coverage():
    """End-to-end: build a real Panel (via its actual constructor, not a hand-
    built helper call) with symbols whose active-date counts differ sharply
    -- exactly todo 372's reported real-world trigger condition -- and
    confirm sync_shift_null_p runs through the rewired helper and returns a
    valid empirical p-value in [0, 1]. Regression guard for the rewiring
    (self.cal_start[s]/self.cal_len[s] indexing), not a statistical power
    test.
    """
    rng = np.random.default_rng(0)
    n_dates_dense = 300
    n_dates_sparse = 105  # sharply fewer active dates (still >= _MIN_BARS_PER_SYMBOL=100)
    # -- old bug's failure trigger is uneven active-date counts across symbols

    dates_dense = np.arange(20260101, 20260101 + n_dates_dense)
    # symbol 1 ("dense"): one row per day for 40 days
    sym_dense = np.zeros(n_dates_dense, dtype=np.int64)
    # symbol 2 ("sparse"): only the first 6 of those same calendar dates
    dates_sparse = dates_dense[:n_dates_sparse]
    sym_sparse = np.ones(n_dates_sparse, dtype=np.int64)

    symbol_ids = np.concatenate([sym_dense, sym_sparse])
    dates = np.concatenate([dates_dense, dates_sparse])
    scores = rng.normal(size=len(dates))
    returns = rng.normal(size=len(dates))

    panel = Panel(symbol_ids, dates, scores, returns)
    assert set(panel.family) == {0, 1}, "both symbols should qualify for the family"

    observed = panel.family_stat()
    p = panel.sync_shift_null_p(observed, rng, n_null=50)
    assert 0.0 <= p <= 1.0
