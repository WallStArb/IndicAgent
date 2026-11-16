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
    ReconciledSplit,
    RecordedSplit,
    VendorSplit,
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
