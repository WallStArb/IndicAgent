"""Split reconciliation (admission step 4): Massive's splits families against corporate_action."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.intelligence.bars.corporate_actions import SplitRatioRule
from src.intelligence.bars.split_reconciliation import (
    BULK,
    OUTCOMES,
    V3,
    IdentityIndex,
    ReconciledSplit,
    ReconcileParams,
    RecordedSplit,
    StringSpan,
    VendorSplit,
    attribute,
    collapse_vendor_duplicates,
    merge_split_families,
    partition_counts,
    proposal_status,
    reconcile,
    split_factor,
    vendor_effective_date,
)

RULE = SplitRatioRule(max_numerator=50, max_denominator=4, rel_tol=0.002)


def _weekdays(start: date, end: date) -> list[date]:
    days, d = [], start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


SESSIONS = _weekdays(date(1985, 1, 2), date(2027, 2, 1))
PARAMS = ReconcileParams(
    ratio_rel_tol=0.002,
    same_event_days=7,
    served_on={"p1": date(2026, 11, 10)},
    archive_start=date(2003, 9, 10),
    sessions=SESSIONS,
)


def _result(event_id, ticker, execution, to, frm, **extra):
    return {
        "id": event_id,
        "ticker": ticker,
        "execution_date": execution,
        "split_to": to,
        "split_from": frm,
        **extra,
    }


def _split(event_id, execution, factor, bulk=None, v3=None):
    return VendorSplit(event_id, execution, factor, bulk, v3, None, frozenset({BULK}), ("p1",))


def test_factor_orientation_is_old_over_new_price():
    assert split_factor(10, 1) == 10.0  # NVDA 2024-06-10: ten new shares per old
    assert split_factor(1, 10) == 0.1  # a 1-for-10 reverse split
    with pytest.raises(ValueError):
        split_factor(0, 1)


def test_the_families_merge_by_id_and_a_disagreement_is_a_conflict():
    rows = [
        (V3, "a", _result("E1", "NVDA", "2024-06-10", 10, 1)),
        (
            BULK,
            "b",
            _result("E1", "NVDA", "2024-06-10", 10.0, 1.0, adjustment_type="forward_split"),
        ),
        (V3, "a", _result("E1", "NVDA", "2024-06-10", 10, 1)),  # served twice: collapses
        (V3, "a", _result("E2", "AAPL", "2020-08-31", 4, 1)),
        (BULK, "b", _result("E2", "AAPL", "2020-08-28", 4.0, 1.0)),  # date disagrees
        (BULK, "b", _result("E3", "X", "2020-01-02", 2.0, 1.0, adjustment_type="forward_split")),
        (BULK, "c", _result("E3", "X", "2020-01-02", 2.0, 1.0, adjustment_type="stock_dividend")),
    ]
    merged, conflicts = merge_split_families(rows)
    assert [s.event_id for s in merged] == ["E1"]
    nvda = merged[0]
    assert (nvda.factor, nvda.bulk_ticker, nvda.v3_ticker) == (10.0, "NVDA", "NVDA")
    assert nvda.families == frozenset({V3, BULK}) and nvda.evidence == ("a", "b")
    assert nvda.adjustment_type == "forward_split"
    assert [c.event_id for c in conflicts] == ["E2", "E3"]


def _index():
    spans = [
        StringSpan("NVDA", "NVDA", date(1999, 1, 22), None),
        StringSpan("META", "FB", date(2012, 5, 18), date(2022, 6, 9)),
        StringSpan("META", "META", date(2022, 6, 9), None),
        StringSpan("HEI.A", "HEI.A", date(1990, 1, 1), None),
        StringSpan("BR", "BR", date(2007, 3, 22), None),
    ]
    return IdentityIndex.build(
        spans,
        {
            "NVDA": date(1999, 1, 22),
            "META": date(2012, 5, 18),
            "HEI.A": date(1990, 1, 1),
            "BR": date(2007, 3, 22),
        },
    )


def test_attribution_goes_through_identity_never_a_label_alone():
    index = _index()
    nvda = _split("E1", date(2024, 6, 10), 10.0, bulk="NVDA", v3="NVDA")
    assert attribute(nvda, index) == ("NVDA", "span")
    # A rename: the event traded under FB, the instrument is META.
    fb = _split("E2", date(2015, 1, 5), 2.0, bulk="FB")
    assert attribute(fb, index) == ("META", "span")
    # v3 drops share-class dots.
    hei = _split("E3", date(2018, 1, 2), 1.25, v3="HEIA")
    assert attribute(hei, index) == ("HEI.A", "span_v3")
    # The vendor relabels an old event with today's string after the security listed.
    relabel = _split("E4", date(2016, 1, 5), 2.0, bulk="META")
    assert attribute(relabel, index) == ("META", "current_label")
    # A reused ticker: Burlington Resources' BR split of 2004 is not Broadridge's (listed 2007).
    reused = _split("E5", date(2004, 6, 2), 2.0, bulk="BR", v3="BR")
    assert attribute(reused, index) == ("BR", "predates_entity")
    # Labels that resolve to two instruments decide nothing.
    both = _split("E6", date(2015, 1, 5), 2.0, bulk="FB", v3="NVDA")
    assert attribute(both, index)[1] == "ambiguous"
    assert attribute(_split("E7", date(2015, 1, 5), 2.0, bulk="ZZZZ"), index) is None
    # No list date: no evidence dates the instrument's hold on its string, so nothing is its own.
    bare = IdentityIndex.build([StringSpan("OLD", "OLD", date.min, None)], {"OLD": None})
    assert attribute(_split("E8", date(2004, 6, 2), 2.0, bulk="OLD"), bare) == (
        "OLD",
        "unanchored",
    )


def test_duplicate_ids_of_one_split_collapse_and_contradicting_ones_drop():
    # Measured: CMI 2007-04-10 is served under two ids; two rows would rescale twice.
    a = _split("Ea", date(2007, 4, 10), 2.0, bulk="CMI", v3="CUM")
    b = _split("Eb", date(2007, 4, 10), 2.0, bulk="CMI", v3="CMI")
    c = _split("Ec", date(2008, 1, 3), 2.0, bulk="CMI")
    d = _split("Ed", date(2008, 1, 7), 3.0, bulk="CMI")
    kept, groups = collapse_vendor_duplicates(
        [(a, "CMI", "span"), (b, "CMI", "span_v3"), (c, "CMI", "span"), (d, "CMI", "span")], 7
    )
    assert [(k.event_id, how) for k, _s, how in kept] == [("Ea", "span")]
    assert [(g.kept, g.ids) for g in groups] == [("Ea", ("Ea", "Eb")), (None, ("Ec", "Ed"))]


def _ours(symbol, effective, factor, *, correction=False, aid="o1"):
    return RecordedSplit(aid, symbol, effective, factor, "calendar_audit", correction)


def test_the_partition_names_every_member_once():
    own = [
        (_split("E1", date(2024, 6, 10), 10.0), "NVDA", "span"),  # massive_only
        (_split("E2", date(2020, 8, 31), 4.0), "AAPL", "span"),  # agree with ours
        (_split("E3", date(2014, 6, 9), 7.0), "AAPL", "span"),  # date_offset (ours a day late)
        (_split("E4", date(2005, 2, 28), 2.0), "AAPL", "span"),  # ratio_disagree
        (_split("E5", date(2000, 6, 21), 2.0), "AAPL", "span"),  # pre-archive, paired: agree
        (_split("E6", date(1987, 6, 16), 2.0), "AAPL", "span"),  # pre-archive, unpaired
        (_split("E7", date(2027, 1, 13), 2.0), "IBDS", "span"),  # announced
    ]
    recorded = [
        _ours("AAPL", date(2020, 8, 28), 4.0, aid="a"),
        _ours("AAPL", date(2014, 6, 9), 7.0, aid="b"),
        _ours("AAPL", date(2005, 2, 25), 3.0, aid="c"),
        _ours("AAPL", date(2000, 6, 20), 2.0, aid="d"),
        _ours("AAPL", date(2010, 3, 1), 2.0, aid="e"),  # ours_only
        _ours("PATK", date(2015, 12, 31), 0.4, correction=True, aid="f"),
    ]
    members = reconcile(own, recorded, PARAMS)
    by_event = {m.vendor.event_id: m for m in members if m.vendor is not None}
    assert by_event["E1"].outcome == "massive_only"
    assert by_event["E1"].vendor_effective_date == date(2024, 6, 7)
    assert by_event["E2"].outcome == "agree"
    assert (by_event["E3"].outcome, by_event["E3"].session_offset) == ("date_offset", 1)
    assert by_event["E4"].outcome == "ratio_disagree"
    assert by_event["E5"].outcome == "agree"  # AAPL 2000-06-20 is one event, never two
    assert by_event["E6"].outcome == "before_archive"
    assert by_event["E7"].outcome == "announced"
    counts = partition_counts(members)
    assert set(counts) == set(OUTCOMES)
    assert counts["ours_only"] == 1 and counts["vendor_correction"] == 1
    assert sum(counts.values()) == len(members) == 9


def test_only_own_attributions_reconcile_and_the_effective_date_is_the_prior_session():
    with pytest.raises(ValueError, match="not the instrument's own"):
        reconcile([(_split("E", date(2010, 1, 4), 2.0), "BR", "predates_entity")], [], PARAMS)
    assert vendor_effective_date(date(2024, 6, 10), SESSIONS) == date(2024, 6, 7)


def test_a_proposal_needs_a_split_ratio_and_the_tape():
    member = ReconciledSplit(
        "NVDA",
        "massive_only",
        _split("E1", date(2024, 6, 10), 10.0),
        "span",
        None,
        date(2024, 6, 7),
    )
    assert proposal_status(member, "tape_step", RULE) == "proposed"
    assert proposal_status(member, "tape_flat", RULE) == "tape_flat"
    # The vendor serves spin-off adjustments as forward splits (YUM 2016-11-01 x1.391).
    spin = ReconciledSplit(
        "YUM",
        "massive_only",
        _split("E2", date(2016, 11, 1), 1.391),
        "span",
        None,
        date(2016, 10, 31),
    )
    assert proposal_status(spin, "tape_step", RULE) == "not_a_split_ratio"
    with pytest.raises(ValueError):
        proposal_status(ReconciledSplit("X", "agree"), "tape_step", RULE)


def test_an_operator_row_is_never_the_markets_split_even_at_its_ratio():
    # UHAL 2022-11-09 x10 rescales IBKR's route at the split's own ratio; selection never rescales
    # Massive by it, so the vendor's event stays massive_only and needs its own row.
    own = [(_split("E1", date(2022, 11, 10), 10.0), "UHAL", "span")]
    recorded = [_ours("UHAL", date(2022, 11, 9), 10.0, correction=True, aid="u")]
    out = {(m.symbol, m.outcome) for m in reconcile(own, recorded, PARAMS)}
    assert out == {("UHAL", "massive_only"), ("UHAL", "vendor_correction")}


def test_an_announcement_is_judged_against_its_own_pages_serve_date():
    early = VendorSplit("E", date(2026, 11, 10), 2.0, "X", None, None, frozenset({BULK}), ("p0",))
    params = ReconcileParams(
        0.002, 7, {"p0": date(2026, 11, 9), "p1": date(2026, 11, 10)}, date(2003, 9, 10), SESSIONS
    )
    (member,) = reconcile([(early, "X", "span")], [], params)
    assert member.outcome == "announced"
