"""ops_massive_split_audit: identity preparation and the read-only contract (todo 600 step 4)."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np

from scripts.ops.bars import ops_massive_split_audit as audit
from src.intelligence.bars.corporate_actions import SplitRatioRule
from src.intelligence.bars.level_seams import RecordedFactor
from src.intelligence.bars.split_reconciliation import (
    IdentityIndex,
    ReconciledSplit,
    RecordedSplit,
    StringSpan,
    VendorSplit,
    ticker_key,
)

SESSIONS = [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6)]


def test_the_chain_head_reaches_back_to_the_list_date():
    # OKE's only event is dated 2026-09-11 although the string traded for decades.
    ident = audit.build_identity("OKE", [(date(2026, 9, 11), "OKE")], date(1954, 5, 24))
    assert ident.chain == "consistent"
    assert [(s.string, s.valid_from, s.valid_to) for s in ident.spans] == [
        ("OKE", date(1954, 5, 24), None)
    ]


def test_a_rename_opens_a_span_and_an_inconsistent_chain_falls_back():
    chain = [(date(2012, 5, 18), "FB"), (date(2022, 6, 9), "META")]
    ident = audit.build_identity("META", chain, date(2012, 5, 18))
    assert [(s.string, s.valid_from, s.valid_to) for s in ident.spans] == [
        ("FB", date(2012, 5, 18), date(2022, 6, 9)),
        ("META", date(2022, 6, 9), None),
    ]
    # Agilent's chain ends on AWD, not A: the instrument keeps its own string only.
    odd = audit.build_identity("A", [(date(2003, 9, 10), "A"), (date(2005, 11, 23), "AWD")], None)
    assert odd.chain == "inconsistent"
    assert [(s.string, s.valid_from) for s in odd.spans] == [("A", date.min)]


def test_span_ordinals_are_half_open_over_the_sessions():
    ident = audit.build_identity(
        "META", [(date(2020, 1, 1), "FB"), (date(2020, 1, 3), "META")], None
    )
    assert ident.ordinals(SESSIONS) == [("FB", 0, 2), ("META", 2, 4)]


def test_massive_on_todays_scale_divides_every_later_split():
    series = audit.Series("X", np.array([0, 1, 2, 3]), np.array([40.0, 40.0, 10.0, 5.0]), None)
    factors = [RecordedFactor(2, 4.0, "massive", "a"), RecordedFactor(3, 2.0, "massive", "b")]
    assert audit.adjusted_close(series, factors, SESSIONS).tolist() == [5.0, 5.0, 5.0, 5.0]
    # A split whose new scale starts at the archive's first session divides no archived bar.
    first = [RecordedFactor(0, 2.0, "massive", "c")]
    assert audit.adjusted_close(series, first, SESSIONS).tolist() == [40.0, 40.0, 10.0, 5.0]


def test_the_audit_never_writes_the_database():
    source = Path(audit.__file__).read_text()
    assert not re.search(r"\b(INSERT INTO|UPDATE|DELETE FROM|TRUNCATE|commit\()", source)


_RULE = SplitRatioRule(max_numerator=50, max_denominator=4, rel_tol=0.002)
_PAGE = "170b3385-022a-462f-a29e-e101adae3a74"


def _offset_pair(*, by="nightly_overlap", correction=False, outcome="date_offset", factor=3.0):
    vendor = VendorSplit(
        "E1",
        date(2026, 11, 5),
        factor,
        "ITA",
        "ITA",
        "forward_split",
        frozenset({"bulk"}),
        (_PAGE,),
    )
    ours = RecordedSplit("a1", "ITA", date(2026, 11, 3), 3.0, by, correction)
    return ReconciledSplit("ITA", outcome, vendor, "span", ours, date(2026, 11, 4), -1)


def test_a_tape_confirmed_date_offset_is_a_redate_line_that_replaces_the_recorded_row():
    pair = _offset_pair()
    assert audit.redate_ok(pair, "tape_step", _RULE)
    served = {_PAGE: datetime(2026, 11, 10, 16, 43, tzinfo=UTC)}
    line = audit.redate_line(pair, served, {"tape": "tape_step", "tape_level_step": -1.1})
    assert (line["effective_date"], line["supersedes"], line["status"]) == (
        "2026-11-04",
        "a1",
        "proposed",
    )
    assert line["factor"] == 3.0 and line["recorded_at"] == served[_PAGE].isoformat()
    assert set(audit.REDATE_COLUMNS) - set(line) == {"guard_skip"}


def test_only_a_tape_confirmed_restatement_row_is_redated():
    assert not audit.redate_ok(_offset_pair(), "tape_flat", _RULE)
    assert not audit.redate_ok(_offset_pair(by="massive_reference"), "tape_step", _RULE)
    assert not audit.redate_ok(
        _offset_pair(by="calendar_audit", correction=True), "tape_step", _RULE
    )
    assert not audit.redate_ok(_offset_pair(outcome="ratio_disagree"), "tape_step", _RULE)
    assert not audit.redate_ok(_offset_pair(factor=1.391), "tape_step", _RULE)


def test_group_counts_split_tier_non_tier_and_active():
    from types import SimpleNamespace

    ref = SimpleNamespace(tier=frozenset({"T"}), members=frozenset({"T", "N"}))

    def vs(i):
        return VendorSplit(i, date(2020, 1, 2), 2.0, "X", "X", None, frozenset({"bulk"}), ())

    own = [(vs("1"), "T", "span"), (vs("2"), "N", "span"), (vs("3"), "A", "span")]
    proposed = [{"symbol": "T"}, {"symbol": "A"}]
    review = [{"symbol": "N", "status": "tape_flat"}]
    out = audit.group_counts(ref, own, proposed, review)
    assert out["tier_5m_ever"]["proposed_rows"] == 1
    assert out["non_tier_member"]["review_by_status"] == {"tape_flat": 1}
    assert out["active"]["events_attributed"] == 1 and out["active"]["proposed_names"] == 1


def _split(day, ticker="DEAD", event_id="e1"):
    return VendorSplit(event_id, day, 2.0, ticker, ticker, None, frozenset({"bulk"}), ("r",))


class _ReferenceConn:
    """load_reference's queries answered from canned rows keyed by the SQL text."""

    def __init__(self, rows):
        page = {"status": "OK", "results": []}
        self.rows = {
            audit._MEMBERS_SQL: [("DEAD", True)],
            audit._SPLITS_SQL: [
                (f"p{i}", ep, None, page) for i, ep in enumerate(audit._FAMILY_OF_ENDPOINT)
            ],
        } | rows

    def execute(self, sql, params=None):
        return _Rows(self.rows.get(sql, []))


class _Rows(list):
    def fetchall(self):
        return list(self)


def test_a_dead_names_open_span_ends_at_its_last_session_and_a_reused_ticker_is_nobodys():
    # ticker_event leaves the last span open; the same string is reused after the death.
    conn = _ReferenceConn(
        {
            audit._MEMBER_SPANS_SQL: [("DEAD", "DEAD", date(2010, 1, 4), None)],
            audit._MEMBER_LAST_SESSION_SQL: [("DEAD", date(2015, 6, 30))],
        }
    )
    ref = audit.load_reference(conn)
    (span,) = ref.member_spans["DEAD"]
    assert span.valid_to == date(2015, 7, 1)  # exclusive: the last session is still held
    index = IdentityIndex.build(
        span and ref.member_spans["DEAD"], {"DEAD": span.valid_from}, label_symbols=()
    )
    on_last = _split(date(2015, 6, 30), event_id="a")
    after = _split(date(2019, 3, 1), event_id="b")  # a new holder of the string splits
    own, excluded, outside = audit.attribute_all([on_last, after], index, {ticker_key("DEAD")})
    assert [(s.event_id, sym) for s, sym, _ in own + excluded] == [("a", "DEAD")]
    assert [s.event_id for s in outside] == ["b"]


def test_a_string_only_an_active_name_holds_is_not_outside_span():
    active = StringSpan("ACT", "ACT", date(2010, 1, 4), date(2012, 1, 1))
    index = IdentityIndex.build([active], {"ACT": active.valid_from}, label_symbols=())
    after = _split(date(2019, 3, 1), event_id="late", ticker="ACT")  # outside the active span
    own, excluded, outside = audit.attribute_all([after], index, member_keys=set())
    assert (own, excluded, outside) == ([], [], [])


def test_member_keys_match_across_share_class_spellings():
    span = StringSpan("BRKB", "BRKB", date(2010, 1, 4), date(2012, 1, 1))
    index = IdentityIndex.build([span], {"BRKB": span.valid_from}, label_symbols=())
    late = _split(
        date(2019, 3, 1), event_id="late", ticker="BRK.B"
    )  # dotted spelling, after the span
    _, _, outside = audit.attribute_all([late], index, {ticker_key("BRKB")})
    assert [s.event_id for s in outside] == ["late"]


def test_a_member_with_no_bars_holds_nothing_and_a_closed_span_keeps_its_own_end():
    open_span = StringSpan("X", "X", date(2010, 1, 4), None)
    assert audit.clip_span(open_span, {}).valid_to == date(2010, 1, 4)
    closed = StringSpan("X", "X", date(2010, 1, 4), date(2012, 1, 1))
    assert audit.clip_span(closed, {"X": date(2020, 1, 1)}).valid_to == date(2012, 1, 1)
