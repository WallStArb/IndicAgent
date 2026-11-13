"""The ticker-entity map writer's --amend mode (design 8c identity witness): pure tests."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import hashlib
import io
from datetime import date
from pathlib import Path

import pytest

from services.ticker_entity_map_writer import (
    PlacedSpan,
    TickerEntityMapAmender,
    plan_amendment,
    read_placed,
    single_figi,
)

START, END = date(2003, 9, 10), date(2026, 11, 10)
SPANS_CSV = (
    b"symbol,reason,span_start,span_end,list_date,ibkr_sessions,decision,placing_ticker\n"
    b"APA,before_first_event,2003-09-10,2021-03-02,1969-05-27,4397,placed,APA\n"
    b"CAL,before_first_event,2003-09-10,2015-05-29,1913-01-01,1777,returns_disagree,\n"
)
CANDIDATES_CSV = (
    b"symbol,span_start,span_end,candidate,matched,pairs,agreeing,return_share,correlation,"
    b"level_median,level_iqr,n_splits,decision\n"
    b"APA,2003-09-10,2021-03-02,APA,4397,4395,3750,0.85,0.9998,0.0,0.0,1,placed\n"
)
GAPS = [
    {"symbol": "APA", "scope": "span", "reason": "before_first_event",
     "valid_from": "2003-09-10", "valid_to": "2021-03-02", "detail": "{}"},
    {"symbol": "CAL", "scope": "span", "reason": "before_first_event",
     "valid_from": "2003-09-10", "valid_to": "2015-05-29", "detail": "{}"},
]  # fmt: skip
IDS = {"APA": {"composite_figi": "C1", "isin": "I1"}}


def _placed(symbol="APA", ticker="APA", start=date(2003, 9, 10), end=date(2021, 3, 2)):
    return PlacedSpan(symbol, "before_first_event", start, end, ticker, {"witness_rule": "r"})


def test_read_placed_keeps_only_placed_rows_with_their_evidence():
    rows = read_placed(SPANS_CSV, CANDIDATES_CSV, hashlib.sha256(SPANS_CSV).hexdigest())
    assert [(r.symbol, r.ticker, r.start, r.end) for r in rows] == [
        ("APA", "APA", date(2003, 9, 10), date(2021, 3, 2))
    ]
    assert rows[0].evidence["correlation"] == "0.9998"


def test_a_wrong_sha256_refuses():
    with pytest.raises(ValueError, match="not the pinned"):
        read_placed(SPANS_CSV, CANDIDATES_CSV, "0" * 64)


def test_an_overlap_with_a_live_span_of_the_name_or_the_ticker_refuses():
    live_name = [("APA", "APA", date(2021, 3, 1), None)]  # one day of overlap
    with pytest.raises(ValueError, match="overlap"):
        plan_amendment([_placed()], IDS, {}, live_name, GAPS, START, END)
    live_ticker = [("OTHER", "APA", date(2010, 1, 4), date(2011, 1, 3))]
    with pytest.raises(ValueError, match="overlap"):
        plan_amendment([_placed()], IDS, {}, live_ticker, GAPS, START, END)
    adjacent = [("APA", "APA", date(2021, 3, 2), None)]  # the first event: adjacent, no overlap
    plan = plan_amendment([_placed()], IDS, {}, adjacent, GAPS, START, END)
    assert [p.symbol for p in plan.spans] == ["APA"] and plan.removed_gaps == [GAPS[0]]


def test_a_name_without_a_figi_mints_from_one_captured_answer_and_an_ambiguous_one_stays_a_gap():
    one = [{"data": [{"ticker": "NAD", "exchCode": "US", "compositeFIGI": "C9",
                      "shareClassFIGI": "S9"},
                     {"ticker": "XNADX", "exchCode": "US", "compositeFIGI": "C8",
                      "shareClassFIGI": "S9"}]}]  # fmt: skip
    assert single_figi(one, "NAD") == ("C9", "S9")
    two = [{"data": [{"ticker": "NAD", "exchCode": "US", "compositeFIGI": "C9",
                      "shareClassFIGI": "S9"},
                     {"ticker": "NAD", "exchCode": "US", "compositeFIGI": "C7",
                      "shareClassFIGI": "S7"}]}]  # fmt: skip
    assert single_figi(two, "NAD") is None
    ids = {"NAD": {"isin": "INAD"}}
    gaps = [{"symbol": "NAD", "scope": "instrument", "reason": "openfigi_ambiguous",
             "valid_from": "", "valid_to": "", "detail": "{}"}]  # fmt: skip
    nad = PlacedSpan("NAD", "openfigi_ambiguous", START, END, "NAD", {"witness_rule": "r"})
    plan = plan_amendment([nad], ids, {"INAD": ("ref", one)}, [], gaps, START, END)
    assert plan.mint == [
        ("NAD", "composite_figi", "C9", "ref"),
        ("NAD", "share_class_figi", "S9", "ref"),
    ]
    assert plan.removed_gaps == gaps
    left = plan_amendment([nad], ids, {"INAD": ("ref", two)}, [], gaps, START, END)
    assert left.spans == [] and left.mint == [] and left.removed_gaps == []
    assert left.kept_as_gap == [("NAD", "no single captured OpenFIGI answer")]


class _FakeConn:
    def __init__(self):
        self.executed = 0
        self.committed = False

    async def fetch(self, sql, *args):
        if "security_identifier_current" in sql:
            return [{"security_identifier_id": "id-apa", "symbol": "APA",
                     "scheme": "composite_figi", "value": "C1"}]  # fmt: skip
        if "endpoint = 'overview'" in sql:
            return [{"symbol": "APA", "id": "ov-apa"}]
        return []

    async def execute(self, sql, *args):
        self.executed += 1

    @contextlib.asynccontextmanager
    async def transaction(self):
        yield
        self.committed = True


class _FakePool:
    def __init__(self, conn):
        self.conn = conn

    @contextlib.asynccontextmanager
    async def acquire(self):
        yield self.conn


def test_a_rehearsal_rolls_back_and_writes_no_map_directory(tmp_path):
    spans, cands = tmp_path / "spans.csv", tmp_path / "cands.csv"
    spans.write_bytes(SPANS_CSV)
    cands.write_bytes(CANDIDATES_CSV)
    gap = tmp_path / "gap_list.csv"
    buf = io.StringIO()
    writer = csv.DictWriter(buf, list(GAPS[0]))
    writer.writeheader()
    writer.writerows(GAPS)
    gap.write_text(buf.getvalue())
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text('{"dataset": "day", "key": "x/2026-11-09.csv.gz"}\n')
    args = argparse.Namespace(
        amend=spans,
        amend_sha256=hashlib.sha256(SPANS_CSV).hexdigest(),
        amend_candidates=cands,
        gap_list=gap,
        manifest=manifest,
    )
    out_root = tmp_path / "maps"
    amender = TickerEntityMapAmender("postgresql://unused", False, args, out_root=out_root)
    conn = _FakeConn()
    asyncio.run(amender.execute(_FakePool(conn)))
    assert conn.executed == 1  # the span insert ran inside the transaction ...
    assert not conn.committed  # ... which the rehearsal rolled back
    assert not Path(out_root).exists()  # and no map directory was written
