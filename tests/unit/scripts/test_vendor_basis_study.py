"""vendor_basis_study.py: the pre-registered boundary rule, decomposition and actions (185-37).

Pure functions on synthetic series; no database (todo 494).
"""

from __future__ import annotations

import inspect
import math
import re
from datetime import date, timedelta

import pytest

from scripts.research import vendor_basis_study as study
from src.intelligence.bars.vendor_basis import BasisRun, find_basis_runs, ratio_pairs


def _days(n: int) -> list[date]:
    return [date(2010, 1, 1) + timedelta(days=i) for i in range(n)]


def _walk(n: int, step: float = 0.01) -> list[float]:
    # A deterministic zig-zag: ordinary moves of about 1%, none large.
    price, out = 100.0, []
    for i in range(n):
        price *= math.exp(step * (1 if i % 3 else -1) * (1 + (i % 5) / 10))
        out.append(price)
    return out


def _pair(n: int, run: range, scale: float, stepping: str):
    """IBKR and Tradier closes equal except over `run`, where the stepping vendor is scaled."""
    days, base = _days(n), _walk(n)
    ibkr = dict(zip(days, base, strict=True))
    tradier = dict(zip(days, base, strict=True))
    target = tradier if stepping == "tradier" else ibkr
    for i in run:
        target[days[i]] = base[i] * scale
    return days, ibkr, tradier


def _only_run(ibkr, tradier):
    (run,) = find_basis_runs(ratio_pairs(ibkr, tradier), tolerance_bp=10.0, min_sessions=5)
    return run


def test_tradier_stepping_in_and_out_is_judged_ibkr_continuous():
    days, ibkr, tradier = _pair(600, range(300, 340), 1.5, stepping="tradier")
    run = _only_run(ibkr, tradier)
    boundaries, verdict = study.judge_run(run, ibkr, tradier, {})
    assert verdict == study.VENDOR_IBKR
    assert [b.side for b in boundaries] == ["before", "after"]
    assert all(b.vote == study.VENDOR_IBKR for b in boundaries)
    assert boundaries[0].prev == days[299] and boundaries[0].cur == days[300]


def test_ibkr_stepping_is_judged_tradier_continuous():
    _days_, ibkr, tradier = _pair(600, range(300, 340), 0.6, stepping="ibkr")
    run = _only_run(ibkr, tradier)
    assert study.judge_run(run, ibkr, tradier, {})[1] == study.VENDOR_TRADIER


def test_a_run_at_the_history_start_has_one_boundary():
    _d, ibkr, tradier = _pair(400, range(0, 50), 1.05, stepping="tradier")
    run = _only_run(ibkr, tradier)
    boundaries, _verdict = study.judge_run(run, ibkr, tradier, {})
    assert [b.side for b in boundaries] == ["after"]


def test_a_gradual_drift_casts_no_vote_and_stays_undecided():
    days, base = _days(600), _walk(600)
    ibkr = dict(zip(days, base, strict=True))
    # Tradier drifts 1 bp a day away from IBKR and back: no boundary step on either side.
    tradier = {
        d: p * (1 + 0.0001 * min(max(i - 300, 0), max(500 - i, 0)))
        for i, (d, p) in enumerate(zip(days, base, strict=True))
    }
    runs = find_basis_runs(ratio_pairs(ibkr, tradier), tolerance_bp=10.0, min_sessions=5)
    assert runs
    for run in runs:
        boundaries, verdict = study.judge_run(run, ibkr, tradier, {})
        assert verdict is None
        assert all(b.vote is None for b in boundaries)


def test_a_corporate_action_on_the_boundary_explains_the_step():
    days, ibkr, tradier = _pair(600, range(300, 340), 1.5, stepping="tradier")
    run = _only_run(ibkr, tradier)
    boundaries, verdict = study.judge_run(run, ibkr, tradier, {days[300]: "split"})
    assert boundaries[0].vote is None and boundaries[0].explained_by
    # The after boundary still votes, so the run is decided by it alone.
    assert verdict == study.VENDOR_IBKR


def test_conflicting_votes_leave_the_run_undecided():
    days, base = _days(600), _walk(600)
    ibkr = dict(zip(days, base, strict=True))
    tradier = dict(zip(days, base, strict=True))
    for i in range(300, 340):
        tradier[days[i]] = base[i] * 1.5  # Tradier steps up at the start
    for i in range(340, 600):
        ibkr[days[i]] = base[i] * 1.5  # IBKR steps up at the end, Tradier steps back down
        tradier[days[i]] = base[i] * 1.5
    # At 340 Tradier does not move abnormally (stays 1.5x), IBKR jumps: a tradier vote; at 300
    # Tradier jumps: an ibkr vote.
    run = _only_run(ibkr, tradier)
    boundaries, verdict = study.judge_run(run, ibkr, tradier, {})
    assert {b.vote for b in boundaries} == {study.VENDOR_IBKR, study.VENDOR_TRADIER}
    assert verdict is None


def test_ordinary_ceiling_excludes_the_boundaries_and_respects_the_window():
    moves = [0.01] * 300
    moves[149] = 0.5  # the move ending at session 150, a boundary
    cap = study.ordinary_ceiling(moves, 150, {150}, half_window=125, percentile=99.0)
    assert cap == pytest.approx(0.01)
    assert study.ordinary_ceiling([], 1, {1}) is None


def test_isolated_dates_are_short_out_of_tolerance_stretches():
    days = _days(20)
    pairs = [(d, 1.0, 1.0) for d in days]
    for i in (3, 4):  # stretch of 2
        pairs[i] = (days[i], 1.05, 1.0)
    for i in range(10, 16):  # stretch of 6: a run
        pairs[i] = (days[i], 1.05, 1.0)
    assert study.isolated_dates(pairs, tolerance_bp=10.0, min_sessions=5) == {days[3], days[4]}


def test_decompose_splits_raw_disagreement_into_run_isolated_and_other():
    days = _days(30)
    cur_i = {d: 100.0 for d in days}
    cur_t = {d: 100.0 for d in days}
    for i in range(5, 12):
        cur_i[days[i]] = 103.0  # a 7-session run, 3%
    cur_i[days[20]] = 102.0  # an isolated 2% day
    raw_i, raw_t = dict(cur_i), dict(cur_t)
    raw_i[days[25]] = 50.0  # a pre-split raw answer, current scale agrees
    runs = find_basis_runs(ratio_pairs(cur_i, cur_t), tolerance_bp=10.0, min_sessions=5)
    out = study.decompose("X", raw_i, raw_t, cur_i, cur_t, runs, tolerance_bp=10.0, min_sessions=5)
    assert (out.raw_disagree, out.raw_in_run, out.raw_isolated, out.raw_other) == (9, 7, 1, 1)
    assert (out.current_disagree, out.current_in_run, out.current_isolated) == (8, 7, 1)
    assert out.names_raw_disagree == {"X"}


def test_proposed_action_follows_rule_3():
    a = study.proposed_action
    assert a(None, {"tradier"}, False) == study.ACTION_UNDECIDED
    assert a("ibkr", {"tradier"}, False) == study.ACTION_ROW
    assert a("ibkr", {"tradier", "ibkr"}, False) == study.ACTION_ROW
    assert a("ibkr", {"ibkr"}, False) == study.ACTION_ALREADY_IBKR
    assert a("ibkr", {"tradier"}, True) == study.ACTION_ALREADY_IBKR
    assert a("tradier", {"tradier"}, False) == study.ACTION_TRADIER_OK
    assert a("tradier", {"ibkr"}, True) == study.ACTION_LIST_IBKR_STORED


def test_ibkr_policy_overlap_uses_the_half_open_range():
    run = BasisRun(date(2010, 1, 10), date(2010, 1, 20), 8, 1.1, None)
    span = study.PolicySpan
    assert study.ibkr_policy_overlaps(run, [span(date(2000, 1, 1), None, "ibkr")])
    assert not study.ibkr_policy_overlaps(run, [span(date(2000, 1, 1), date(2010, 1, 10), "ibkr")])
    assert study.ibkr_policy_overlaps(run, [span(date(2000, 1, 1), date(2010, 1, 11), "ibkr")])
    assert not study.ibkr_policy_overlaps(run, [span(date(2000, 1, 1), None, "tradier")])


def test_evidence_record_is_json_safe_and_complete():
    import json
    from datetime import UTC, datetime

    days, ibkr, tradier = _pair(600, range(300, 340), 1.5, stepping="tradier")
    run = _only_run(ibkr, tradier)
    boundaries, verdict = study.judge_run(run, ibkr, tradier, {})
    rv = study.RunVerdict(run, boundaries, verdict, "ibkr")
    record = study.evidence_record(
        "X", rv, tolerance_bp=10.0, min_sessions=5, measured_at=datetime(2026, 10, 7, tzinfo=UTC)
    )
    assert record["run"]["start"] == days[300].isoformat()
    assert len(record["boundaries"]) == 2 and record["continuous_vendor"] == "ibkr"
    json.dumps(record)


def test_the_study_holds_no_write_statement():
    source = inspect.getsource(study)
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|TRUNCATE|ALTER|DROP|CREATE)\b", source)
    assert "default_transaction_read_only" in source


def test_a_run_inside_common_history_has_measured_ends():
    _d, ibkr, tradier = _pair(600, range(300, 340), 1.5, stepping="tradier")
    ends = study.range_ends(_only_run(ibkr, tradier), ibkr, tradier, tolerance_bp=10.0)
    assert ends.measured and ends.entry_ratio == pytest.approx(1.0)
    assert ends.exit_ratio == pytest.approx(1.0) and ends.tradier_head == 0


def test_a_run_at_ibkr_start_with_a_tradier_head_is_not_measured():
    days, ibkr, tradier = _pair(600, range(0, 600), 1.0, stepping="tradier")
    # IBKR starts at day 100; Tradier holds a 100-day head on the stale basis.
    for i in range(100):
        del ibkr[days[i]]
    for i in range(100, 300):
        tradier[days[i]] *= 2.0
    for i in range(100):
        tradier[days[i]] *= 2.0
    run = _only_run(ibkr, tradier)
    ends = study.range_ends(run, ibkr, tradier, tolerance_bp=10.0)
    assert ends.entry_ratio is None and ends.tradier_head == 100 and not ends.measured


def test_a_run_at_the_start_of_both_histories_is_measured():
    _d, ibkr, tradier = _pair(400, range(0, 50), 2.0, stepping="tradier")
    ends = study.range_ends(_only_run(ibkr, tradier), ibkr, tradier, tolerance_bp=10.0)
    assert ends.tradier_head == 0 and ends.measured


def test_a_run_reaching_the_last_common_session_with_a_tradier_tail_is_not_measured():
    days, ibkr, tradier = _pair(400, range(350, 400), 2.0, stepping="tradier")
    for i in range(380, 400):
        del ibkr[days[i]]
    ends = study.range_ends(_only_run(ibkr, tradier), ibkr, tradier, tolerance_bp=10.0)
    assert ends.exit_ratio is None and ends.tradier_tail == 20 and not ends.measured


def test_zero_volume_share_counts_only_the_run_sessions():
    run = BasisRun(date(2016, 3, 1), date(2016, 3, 4), 4, 1.01, None)
    volumes = {
        date(2016, 2, 29): 0.0,
        date(2016, 3, 1): 0.0,
        date(2016, 3, 2): None,
        date(2016, 3, 3): 300.0,
        date(2016, 3, 4): 0.0,
    }
    assert study.zero_volume_share(volumes, run) == pytest.approx(0.75)
    assert study.zero_volume_share({}, run) is None
