"""The Massive source of the dividend writer: capture validation, load planning, the dry run
and the per-symbol write (fake connection, no database)."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

import services.dividend_event_writer as w
from src.intelligence.bars import massive_dividends as md

CAP = date(2026, 11, 10)
MANIFEST = "data/massive/reference/manifest/20261110.jsonl"
PAGE_IDS = {1: uuid.UUID(int=1), 2: uuid.UUID(int=2)}


def _page_row(page, status=200, manifest=MANIFEST):
    return {
        "reference_raw_id": PAGE_IDS.get(page, uuid.UUID(int=page)),
        "page": page,
        "manifest_path": manifest,
        "served_at": datetime(2026, 11, 10, 15, 49, tzinfo=UTC),
        "http_status": status,
    }


def test_the_capture_is_one_manifest_of_contiguous_http_200_pages():
    capture = w.massive_capture([_page_row(1), _page_row(2)])
    assert capture.manifest_path == MANIFEST and capture.capture_date == CAP
    assert capture.page_ids == PAGE_IDS


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [_page_row(1), _page_row(3)],
        [_page_row(1), _page_row(2, status=500)],
        [_page_row(1), _page_row(2, manifest="other.jsonl")],
    ],
)
def test_a_partial_or_mixed_capture_is_refused(rows):
    with pytest.raises(RuntimeError):
        w.massive_capture(rows)


def _quarterly(start, n):
    return [start + timedelta(days=91 * i) for i in range(n)]


DAYS = _quarterly(date(2010, 1, 4), 8)
SPANS = [md.TickerSpan("te", "ACME", "ACME", date(2003, 9, 10), None)]


def _records(days=DAYS, ticker="ACME"):
    return [
        md.DividendRecord(f"E{i}", ticker, d, 0.5, "USD", "recurring", None, 1 + i % 2)
        for i, d in enumerate(days)
    ]


def _collapsed(records=None, spans=SPANS):
    index = md.SpanIndex(spans)
    return md.collapse_events(records or _records(), index, CAP), index


def test_an_event_without_a_prior_close_is_dropped_and_becomes_a_hole():
    collapsed, index = _collapsed()
    prev = {"ACME": {d: 50.0 for d in DAYS if d != DAYS[3]}}
    (load,), drops = w.plan_massive_loads(collapsed, index, prev, {"ACME"}, CAP)
    assert drops == {md.DROP_NO_PREV_CLOSE: 1}
    assert [e.ex_date for e, _ in load.events] == [d for d in DAYS if d != DAYS[3]]
    assert not load.claim.covers(DAYS[3]) and load.claim.covers(DAYS[3] + timedelta(days=1))


def test_a_symbol_missing_from_instruments_is_dropped_whole():
    collapsed, index = _collapsed()
    prev = {"ACME": {d: 50.0 for d in DAYS}}
    loads, drops = w.plan_massive_loads(collapsed, index, prev, set(), CAP)
    assert loads == [] and drops == {"no_instrument": len(DAYS)}


def test_the_prior_close_is_the_last_bar_strictly_before_the_ex_date_and_not_too_old():
    bars = [(date(2010, 1, 4), 10.0), (date(2010, 1, 5), 11.0), (date(2010, 1, 20), 12.0)]
    out = w.prior_closes(
        bars, [date(2010, 1, 5), date(2010, 1, 8), date(2010, 1, 13), date(2010, 1, 4)], 7
    )
    # Jan 5: the Jan 4 bar (its own bar never counts); Jan 8: Jan 5 (3 days); Jan 13: Jan 5
    # is 8 days old; Jan 4: nothing before it
    assert out == {date(2010, 1, 5): 10.0, date(2010, 1, 8): 11.0}


def test_covered_member_months_reads_the_claim():
    collapsed, index = _collapsed()
    loads, _ = w.plan_massive_loads(
        collapsed, index, {"ACME": {d: 50.0 for d in DAYS}}, {"ACME"}, CAP
    )
    months = [
        {"symbol": "ACME", "as_of": date(2009, 12, 31)},  # before the first event
        {"symbol": "ACME", "as_of": date(2010, 6, 30)},
        {"symbol": "OTHER", "as_of": date(2010, 6, 30)},
    ]
    assert w.covered_member_months(loads, months) == [("ACME", date(2010, 6, 30))]


def test_only_symbols_keeps_the_whole_capture_drop_counts():
    collapsed, _ = _collapsed(_records() + _records(ticker="NOPE"))
    only = w._only_symbols(collapsed, {"ACME"})
    assert set(only.events) == {"ACME"} and only.drops == collapsed.drops


def test_the_default_cli_run_is_unchanged_and_massive_runs_alone(monkeypatch):
    assert w._DEFAULT_CLI_SOURCES == ["ibkr", "yahoo"]
    for argv in (["--sources", "massive", "yahoo"], ["--sources", "yahoo", "--dry-run"]):
        monkeypatch.setattr("sys.argv", ["dividend_event_writer.py", *argv])
        with pytest.raises(SystemExit):
            w.main()


class _Conn:
    """Enough of asyncpg for MassiveDividendWriter: canned reads, recorded writes."""

    def __init__(self, stored=None, claims=("ACME",)):
        self.stored = dict(stored or {})  # ex_date -> yield
        self.claims = list(claims)  # symbols holding a stored massive claim
        self.writes: list[tuple[str, object]] = []
        body = {
            "status": "OK",
            "results": [
                {
                    "id": r.record_id,
                    "ticker": r.ticker,
                    "ex_dividend_date": r.ex_date.isoformat(),
                    "cash_amount": r.cash_amount,
                    "currency": r.currency,
                    "distribution_type": r.distribution_type,
                }
                for r in _records()
            ],
        }
        self.body = json.dumps(body)

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def fetch(self, sql, *args):
        if "FROM config_state" in sql:
            return []
        if "FROM reference_raw_current" in sql:
            return [_page_row(1)]
        if "FROM ticker_event_current" in sql:
            return [
                {
                    "ticker_event_id": "te",
                    "symbol": "ACME",
                    "ticker": "ACME",
                    "valid_from": date(2003, 9, 10),
                    "valid_to": None,
                }
            ]
        if "FROM instruments" in sql:
            return [{"symbol": "ACME"}]
        if "FROM ohlcv_raw" in sql:
            assert args[0] == ["ACME"]
            # the Friday before each Monday ex-date
            return [
                {"symbol": "ACME", "bar_date": d - timedelta(days=3), "close": 50.0} for d in DAYS
            ]
        if "FROM universe_membership" in sql:
            return [{"symbol": "ACME", "as_of": date(2010, 6, 30)}]
        if "FROM dividend_event_coverage WHERE source = 'massive'" in sql:
            return [{"symbol": s} for s in self.claims]
        if "FROM dividend_events" in sql:
            return [{"ex_date": d, "dividend_yield": y} for d, y in self.stored.items()]
        raise AssertionError(f"unexpected fetch: {sql}")

    async def fetchval(self, sql, *args):
        assert "FROM reference_raw" in sql
        return self.body

    async def execute(self, sql, *args):
        self.writes.append((sql, args))
        return "OK"

    async def executemany(self, sql, rows):
        self.writes.append((sql, list(rows)))
        return "OK"


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return self.conn


def _writer(dry_run):
    return w.MassiveDividendWriter("postgresql://unused", [], dry_run)


def test_a_stored_claim_whose_symbol_left_the_capture_fails_loud():
    conn = _Conn(claims=("ACME", "GONE"))
    with pytest.raises(RuntimeError, match="1/2 symbols failed"):
        asyncio.run(_writer(dry_run=False).execute(_Pool(conn)))


def test_the_dry_run_reads_everything_and_writes_nothing(capsys):
    conn = _Conn()
    writer = _writer(dry_run=True)
    asyncio.run(writer.execute(_Pool(conn)))
    assert conn.writes == [] and writer.completion_status == "dry_run"
    summary = json.loads(capsys.readouterr().out)
    assert summary["events"] == len(DAYS) and summary["names"] == 1
    assert summary["member_years_covered"] == 1 and summary["manifest"] == MANIFEST


def test_the_write_stores_lineage_replaces_the_claim_and_its_holes():
    conn = _Conn()
    asyncio.run(_writer(dry_run=False).execute(_Pool(conn)))
    sqls = [sql for sql, _ in conn.writes]
    events = next(rows for sql, rows in conn.writes if "INSERT INTO dividend_events" in sql)
    assert len(events) == len(DAYS)
    symbol, ex, source, amount, close, _version, declared, record_ids, raw_ids = events[0]
    assert (symbol, ex, source, amount, close, declared) == (
        "ACME",
        DAYS[0],
        "massive",
        0.5,
        50.0,
        None,
    )
    assert record_ids == ["E0"] and raw_ids == [PAGE_IDS[1]]
    cov = next(args for sql, args in conn.writes if "INSERT INTO dividend_event_coverage " in sql)
    assert cov[0:4] == ("ACME", "massive", DAYS[0], DAYS[-1] + timedelta(days=68))
    assert cov[5:] == (MANIFEST, md.RULE_ID)
    delete = sqls.index(
        next(s for s in sqls if s.startswith("DELETE FROM dividend_event_coverage_gap"))
    )
    insert = sqls.index(
        next(s for s in sqls if s.startswith("INSERT INTO dividend_event_coverage_gap"))
    )
    assert delete < insert


def test_a_rerun_inserts_nothing_new():
    stored = {d: 0.5 / 50.0 for d in DAYS}
    conn = _Conn(stored)
    asyncio.run(_writer(dry_run=False).execute(_Pool(conn)))
    events = next(rows for sql, rows in conn.writes if "INSERT INTO dividend_events" in sql)
    assert events == []


def test_a_stored_event_the_capture_no_longer_has_fails_the_symbol():
    stored = {d: 0.01 for d in DAYS} | {date(2009, 6, 1): 0.01}
    conn = _Conn(stored)
    writer = _writer(dry_run=False)
    with pytest.raises(RuntimeError, match="1/1 symbols failed"):
        asyncio.run(writer.execute(_Pool(conn)))
    assert not any("INSERT" in sql for sql, _ in conn.writes)


class _ReconcileConn:
    """Stored rows of every source the query names (all of them when it names none)."""

    rows = [
        {"source": "yahoo", "ex_date": DAYS[0], "y": 0.01, "prev_close": 50.0},
        {"source": "massive", "ex_date": DAYS[1], "y": 0.01, "prev_close": 50.0},
    ]

    async def fetch(self, sql, *args):
        named = self.rows
        if "source IN" in sql:
            named = [r for r in self.rows if f"'{r['source']}'" in sql]
        if "dividend_event_coverage" in sql:
            return [
                {"source": r["source"], "covered_from": DAYS[0], "covered_to": DAYS[-1]}
                for r in named
            ]
        return named


def test_the_yahoo_reconciliation_ignores_massive_rows():
    rule = w.DisputeRule(rel_tolerance=0.1, noise_margin=1.25)
    rec = asyncio.run(w.DividendEventWriter._reconcile(_ReconcileConn(), "ACME", 5, rule))
    assert rec.near_misses == [] and rec.yield_disagreements == []
