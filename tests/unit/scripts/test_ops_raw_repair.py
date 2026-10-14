"""ops_raw_repair.py: the per-slot repair decision, the selection windows, the expected writes.

Fakes only: no database. The cases are the review's (191-07-REVIEW.md findings 2 and 4).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from scripts.ops.bars import ops_raw_repair as repair
from scripts.ops.bars import ops_selection_gate as gate
from src.intelligence.bars.selection import Candidate

IBKR = ("ibkr", "named")
ALPACA = ("alpaca", "sip_rth")
REFUSED_AT = datetime(2026, 10, 12, 12, 14, 31, tzinfo=UTC)


def _v(close=10.0, volume=100):
    return (9.0, 11.0, 8.5, close, volume)


def _load(
    outcome="refused", at=REFUSED_AT, first=date(2007, 1, 1), last=date(2026, 12, 31), lid="R"
):
    return gate.LoadFact(
        lid, "ibkr", first, last, outcome, at, "market_data_ohlcv", "ibkr-history-fetch"
    )


def _self(ts, canonical, raw, loads=()):
    key = (ts, *IBKR)
    refused = _load()
    evidence = gate.Evidence(raw={key: raw}, refused_serves={key: refused}, loads=[refused, *loads])
    return {ts: (IBKR, canonical)}, {ts: (IBKR, raw)}, evidence


def _plan(canonical, selected, evidence, ends=()):
    return repair.plan_series("KRE", "5m", canonical, selected, evidence, list(ends))


def test_a_request_end_strictly_inside_the_bar_marks_an_edge():
    ts = datetime(2007, 6, 25, 14, 0, tzinfo=UTC)
    inside = ts + timedelta(minutes=2, seconds=29)
    assert repair.at_edge(ts, 300, [inside])
    assert not repair.at_edge(ts, 300, [ts])  # an end on the bar start asks nothing of it
    assert not repair.at_edge(ts, 300, [ts + timedelta(minutes=5)])
    assert not repair.at_edge(ts, 300, [])


def test_the_whole_side_is_the_one_with_more_volume_and_unknown_otherwise():
    assert repair.whole_side(_v(volume=0), _v(volume=9500)) == "raw"
    assert repair.whole_side(_v(volume=44345), _v(volume=6399)) == "canonical"
    assert repair.whole_side(_v(volume=5), _v(volume=5)) is None
    assert repair.whole_side(_v(volume=None), _v()) is None


def test_a_refused_self_restatement_off_the_edge_is_restored_and_held_when_not_re_served():
    ts = datetime(2021, 11, 8, 14, 30, tzinfo=UTC)
    canonical, selected, evidence = _self(ts, _v(68.5514), _v(68.55))
    (slot,) = _plan(canonical, selected, evidence).actions
    assert (slot.action, slot.refused_load_id) == (repair.RESTORE_PENDING, "R")


def test_a_refused_value_the_vendor_answered_again_is_restored_without_a_hold():
    # GE 2021-09-01: refused at 12:14:31, an applied load re-served the slot at 12:15:17 (its
    # request window holds the bar)
    ts = datetime(2021, 9, 1, 16, 55, tzinfo=UTC)
    later = _load("applied", REFUSED_AT + timedelta(seconds=46), lid="A")
    canonical, selected, evidence = _self(ts, _v(64.7616), _v(64.76), loads=[later])
    evidence.windows = {"A": (datetime(2021, 6, 11, tzinfo=UTC), datetime(2021, 11, 7, tzinfo=UTC))}
    (slot,) = _plan(canonical, selected, evidence).actions
    assert slot.action == repair.RESTORE and "A" in slot.reason


def test_a_later_load_covering_the_date_but_not_the_slot_does_not_excuse_it():
    # ADM 2026-10-12 19:55: the later load's request asked 20:10 to 00:05 the same night
    ts = datetime(2026, 10, 12, 19, 55, tzinfo=UTC)
    later = _load("applied", REFUSED_AT + timedelta(hours=12), lid="F")
    canonical, selected, evidence = _self(ts, _v(81.0, 380459), _v(81.0, 380759), loads=[later])
    evidence.windows = {
        "F": (datetime(2026, 10, 12, 20, 10, tzinfo=UTC), datetime(2026, 10, 13, 0, 5, tzinfo=UTC))
    }
    (slot,) = _plan(canonical, selected, evidence).actions
    assert (slot.action, slot.refused_load_id) == (repair.RESTORE_PENDING, "R")


def test_at_an_edge_a_truncated_refused_serve_is_restored_and_a_whole_one_waits_for_a_re_serve():
    ts = datetime(2026, 5, 15, 15, 25, tzinfo=UTC)
    end = [ts + timedelta(minutes=2)]
    # HD: canonical truncated (11,238), the refused raw serve whole (24,428)
    canonical, selected, evidence = _self(ts, _v(299.29, 11238), _v(299.25, 24428))
    (slot,) = _plan(canonical, selected, evidence, end).actions
    assert slot.action == repair.RESERVE and slot.edge
    # the other way round the refused serve is the partial: put the whole bar back, hold nothing
    canonical, selected, evidence = _self(ts, _v(291.82, 12707), _v(291.65, 5903))
    (slot,) = _plan(canonical, selected, evidence, end).actions
    assert slot.action == repair.RESTORE


def test_restated_after_copy_at_an_edge_selects_a_whole_raw_bar_and_reserves_a_truncated_one():
    ts = datetime(2007, 6, 25, 14, 0, tzinfo=UTC)
    key = (ts, *IBKR)
    end = [ts + timedelta(minutes=2, seconds=29)]
    # KRE: canonical is the truncated later serve; raw keeps the whole bar
    whole_raw = gate.Evidence(revisions={key: [(REFUSED_AT, _v(45.65, 9500))]})
    plan = _plan({ts: (IBKR, _v(45.61, 0))}, {ts: (IBKR, _v(45.65, 9500))}, whole_raw, end)
    assert [a.action for a in plan.actions] == [repair.SELECT]
    # TMUS: raw copied the truncated serve, canonical is the whole bar again: never copy it
    truncated_raw = gate.Evidence(
        revisions={
            key: [(REFUSED_AT, _v(38.44, 44345)), (REFUSED_AT + timedelta(days=4), _v(38.51, 6399))]
        }
    )
    plan = _plan({ts: (IBKR, _v(38.44, 44345))}, {ts: (IBKR, _v(38.51, 6399))}, truncated_raw, end)
    assert [a.action for a in plan.actions] == [repair.RESERVE]
    assert plan.reserve_slots() == [ts]
    # off the edge raw is simply stale: restore the later serve
    plan = _plan({ts: (IBKR, _v(38.44, 44345))}, {ts: (IBKR, _v(38.51, 6399))}, truncated_raw)
    assert [a.action for a in plan.actions] == [repair.RESTORE]


def test_cross_vendor_slots_are_selected_and_real_differences_block():
    ts = datetime(2026, 9, 1, 14, 0, tzinfo=UTC)
    key = (ts, *IBKR)
    evidence = gate.Evidence(raw={key: _v()}, refused_serves={key: _load()}, loads=[_load()])
    plan = _plan({}, {ts: (IBKR, _v())}, evidence)
    assert [a.action for a in plan.actions] == [repair.SELECT] and not plan.blockers
    real = _plan({ts: (IBKR, _v(1.0))}, {ts: (IBKR, _v(2.0))}, gate.Evidence())
    assert real.blockers and not real.actions


def test_a_held_value_already_in_canonical_blocks_the_series():
    ts = datetime(2026, 9, 1, 14, 0, tzinfo=UTC)
    key = (ts, *IBKR)
    evidence = gate.Evidence(
        raw={key: _v(10.2)},
        refused_serves={key: _load()},
        revisions={key: [(REFUSED_AT, _v(10.0))]},
        loads=[_load()],
    )
    plan = _plan({ts: (IBKR, _v(10.2))}, {ts: (IBKR, _v(10.2))}, evidence)
    assert plan.blockers and "held refused value" in plan.blockers[0]


def test_reserve_slots_are_excluded_by_stamp_not_by_window():
    """Selection takes each session whole (second review, finding 3): a window that stops at a
    reserve slot would be widened to the whole session and re-select it, so the repair selects
    the series once and names the reserve slots in `exclude`."""
    assert not hasattr(repair, "selection_windows")
    body = Path(repair.__file__).read_text()
    assert "exclude=frozenset(reserve)" in body


def test_expected_canonical_changes_follow_the_repaired_raw_and_skip_reserve_dates():
    t1 = datetime(2026, 5, 14, 15, 0, tzinfo=UTC)
    t2 = datetime(2026, 5, 15, 15, 25, tzinfo=UTC)
    t3 = datetime(2026, 5, 18, 15, 0, tzinfo=UTC)
    cands = [
        Candidate(t1, "HD", "5m", "ibkr", "named", *_v(10.5)),
        Candidate(t2, "HD", "5m", "ibkr", "named", *_v(11.0)),
        Candidate(t3, "HD", "5m", "ibkr", "named", *_v(12.0)),
    ]
    restore = repair.SlotAction(
        t1, "ibkr", "named", gate.SELF_RESTATEMENT, repair.RESTORE, _v(10.0), _v(10.5), False
    )
    fixed = repair.repaired_candidates(cands, [restore])
    assert fixed[0].close == 10.0 and fixed[1] == cands[1]
    canonical = {t1: (IBKR, _v(10.0)), t2: (IBKR, _v(10.9))}
    selected = {c.timestamp: (IBKR, (c.open, c.high, c.low, c.close, c.volume)) for c in fixed}
    changes, n_new, n_replaced = repair.canonical_changes(canonical, selected, [t2])
    assert (n_new, n_replaced) == (1, 0) and changes[0]["timestamp"].startswith("2026-05-18")


def test_a_restore_reads_its_value_from_the_ledger_never_from_canonical():
    """Second review of 191-07, low item: the value put back must be a logged value of the same
    vendor and kind at the key; canonical only names which one. Without that row it blocks."""
    ts = datetime(2021, 11, 8, 14, 30, tzinfo=UTC)
    canonical, selected, evidence = _self(ts, _v(68.5514), _v(68.55))
    plan = _plan(canonical, selected, evidence)
    assert any("not in the ibkr/named ledger" in b for b in plan.blockers)
    evidence.revisions = {(ts, *IBKR): [(REFUSED_AT, _v(68.5514))]}
    assert _plan(canonical, selected, evidence).blockers == []
