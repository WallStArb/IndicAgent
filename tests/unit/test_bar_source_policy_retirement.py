"""Migration 520 and D-191-P: a policy row can be retired; every reader reads the live view."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from scripts.ops.bars.ops_source_policy import parse_plan

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (ROOT / "production/migrations/520_bar_source_policy_retirement.sql").read_text()

_PLAN = {
    "timeframe": "5m",
    "seam": "2016-01-04",
    "defaults": [{"valid_from": "2016-01-04", "primary": "alpaca", "fallback": "ibkr"}],
    "reason": "D-191-P",
    "evidence": {"decision": "D-191-P"},
}


def test_no_reader_queries_the_policy_table_directly():
    """Retired rows are out of force only if nobody reads around the view."""
    offenders = []
    for base in ("src", "services", "scripts"):
        for path in (ROOT / base).rglob("*.py"):
            text = path.read_text()
            for m in re.finditer(r"(?:FROM|JOIN)\s+bar_source_policy\b(?!_current|_changes)", text):
                offenders.append(f"{path.relative_to(ROOT)}:{text[: m.start()].count(chr(10)) + 1}")
    assert offenders == []


def test_migration_scopes_overlap_to_live_rows_and_adds_the_view():
    assert "WHERE (retired_at IS NULL)" in MIGRATION
    assert "CREATE OR REPLACE VIEW bar_source_policy_current" in MIGRATION
    assert "ck_bar_source_policy_retired" in MIGRATION
    assert "is retired and immutable" in MIGRATION
    assert "never inserted retired" in MIGRATION


def test_a_valid_plan_parses_with_defaults_meeting_at_the_seam():
    plan = parse_plan(_PLAN)
    assert plan.timeframe == "5m" and str(plan.seam) == "2016-01-04"
    assert [(r["primary_source"], r["fallback_source"]) for r in plan.defaults] == [
        ("alpaca", "ibkr")
    ]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"evidence": {}}, "evidence"),
        ({"timeframe": "2m"}, "unknown timeframe"),
        ({"seam": "2017-01-03"}, "seam"),
        (
            {
                "defaults": [
                    {"valid_from": "2016-01-04", "valid_to": "2018-01-02", "primary": "alpaca"},
                    {"valid_from": "2018-01-03", "primary": "ibkr"},
                ]
            },
            "gap or overlap",
        ),
        ({"defaults": [{"valid_from": "1990-01-01", "primary": "ibkr"}]}, "start at the seam"),
        (
            {"defaults": [{"valid_from": "2016-01-04", "valid_to": "2020-01-01", "primary": "x"}]},
            "open-ended",
        ),
    ],
)
def test_an_invalid_plan_is_refused(change, message):
    with pytest.raises(ValueError, match=message):
        parse_plan({**_PLAN, **change})


# --- apply_plan against the real trigger and constraints (TEMP copy, always rolled back) ---------

_LIVE_DB_DSN = "postgresql://postgres:postgres@localhost:5432/indicagent"


def _db_reachable() -> bool:
    import socket

    try:
        socket.create_connection(("localhost", 5432), timeout=1).close()
        return True
    except OSError:
        return False


@pytest.fixture
async def temp_policy():
    import asyncpg

    conn = await asyncpg.connect(_LIVE_DB_DSN)
    txn = conn.transaction()
    await txn.start()
    try:
        await conn.execute(
            "CREATE TEMP TABLE bar_source_policy"
            " (LIKE public.bar_source_policy INCLUDING ALL);"
            "CREATE TRIGGER trg_copy BEFORE INSERT OR UPDATE OR DELETE ON pg_temp.bar_source_policy"
            " FOR EACH ROW EXECUTE FUNCTION public.bar_source_policy_append_only();"
            "CREATE TEMP VIEW bar_source_policy_current AS"
            " SELECT * FROM pg_temp.bar_source_policy WHERE retired_at IS NULL;"
            "CREATE TEMP VIEW bar_source_policy_changes AS SELECT * FROM pg_temp.bar_source_policy;"
            "INSERT INTO bar_source_policy (timeframe, symbol, valid_from, ingress_mode,"
            " primary_source, reason, recorded_at) VALUES"
            " ('5m', NULL, DATE '1990-01-01', 'direct', 'ibkr', 'seed', '2026-01-01'),"
            " ('5m', 'SPY', DATE '2006-06-02', 'direct', 'ibkr', 'seed', '2026-01-01');"
            "INSERT INTO bar_source_policy (timeframe, symbol, valid_from, valid_to, ingress_mode,"
            " primary_source, fallback_source, reason, recorded_at) VALUES"
            " ('5m', 'EMR', DATE '2026-03-10', DATE '2026-07-31', 'direct', 'alpaca', 'ibkr', 'w',"
            " '2026-01-01');"
        )
        await conn.execute(
            "UPDATE bar_source_policy SET valid_to = DATE '2026-03-10'"
            " WHERE symbol = 'SPY' AND timeframe = '5m'"
        )
        yield conn
    finally:
        await txn.rollback()
        await conn.close()


@pytest.mark.skipif(not _db_reachable(), reason="needs the local database")
@pytest.mark.asyncio
async def test_apply_plan_retires_closes_and_inserts_in_one_transaction(temp_policy):
    from scripts.ops.bars.ops_source_policy import apply_plan

    counts = await apply_plan(temp_policy, parse_plan(_PLAN), apply=True)
    assert counts["retired"] == 2 and counts["default_closed"] == 1 and counts["inserted"] == 1
    rows = await temp_policy.fetch(
        "SELECT symbol, valid_from, valid_to, primary_source, fallback_source"
        " FROM bar_source_policy_current WHERE timeframe = '5m' ORDER BY valid_from"
    )
    assert [(r[0], str(r[1]), str(r[2]), r[3], r[4]) for r in rows] == [
        (None, "1990-01-01", "2016-01-04", "ibkr", None),
        (None, "2016-01-04", "None", "alpaca", "ibkr"),
    ]
    # a retired row is immutable: neither closed nor retired again
    with pytest.raises(Exception, match="retired and immutable"):
        await temp_policy.execute(
            "UPDATE bar_source_policy SET retired_at = now(), retired_reason = 'again'"
            " WHERE symbol = 'EMR'"
        )


@pytest.mark.skipif(not _db_reachable(), reason="needs the local database")
@pytest.mark.asyncio
async def test_a_dry_run_plan_leaves_the_policy_untouched(temp_policy):
    from scripts.ops.bars.ops_source_policy import apply_plan

    before = await temp_policy.fetchval("SELECT count(*) FROM bar_source_policy_current")
    await apply_plan(temp_policy, parse_plan(_PLAN), apply=False)
    assert await temp_policy.fetchval("SELECT count(*) FROM bar_source_policy_current") == before


@pytest.mark.skipif(not _db_reachable(), reason="needs the local database")
@pytest.mark.asyncio
async def test_a_retired_row_in_the_span_moves_the_snapshot_policy_as_of(temp_policy):
    """point_in_time: two snapshots that straddle a retirement must not pin the same as-of."""
    from src.intelligence.bars.label_inputs import _POLICY_AS_OF_SQL

    args = (["EMR"], "5m", date(2026, 4, 1), date(2026, 5, 1))
    before = await temp_policy.fetchval(_POLICY_AS_OF_SQL, *args)
    await temp_policy.execute(
        "UPDATE bar_source_policy SET retired_at = now(), retired_reason = 'test' WHERE symbol = 'EMR'"
    )
    retired_at = await temp_policy.fetchval(
        "SELECT retired_at FROM bar_source_policy WHERE symbol = 'EMR'"
    )
    after = await temp_policy.fetchval(_POLICY_AS_OF_SQL, *args)
    assert after == retired_at and after > before


# --- the 1d decision (D-191-Q, todo 545): retire both defaults, explicit symbol-row dispositions --

_ID_A = "00000000-0000-0000-0000-00000000000a"
_ID_B = "00000000-0000-0000-0000-00000000000b"
_ID_C = "00000000-0000-0000-0000-00000000000c"
_ID_DT = "00000000-0000-0000-0000-0000000000d1"
_ID_DI = "00000000-0000-0000-0000-0000000000d2"
_FINGERPRINT = {
    "through": "2026-10-06",
    "series": {"alpaca/sip_rth": {"rows": 10, "max_served_at": "2026-10-27T18:00:00+00:00"}},
}

_PLAN_1D = {
    "timeframe": "1d",
    "seam": "2016-01-04",
    "retire_defaults": True,
    "retire_default_ids": [_ID_DT, _ID_DI],
    "raw_fingerprint": _FINGERPRINT,
    "defaults": [
        {"valid_from": "1990-01-01", "valid_to": "2016-01-04", "primary": "ibkr"},
        {"valid_from": "2016-01-04", "primary": "alpaca", "fallback": "ibkr"},
    ],
    "symbol_rows": [
        {
            "symbol": "WDC",
            "valid_from": "2016-01-04",
            "valid_to": "2025-02-24",
            "primary": "ibkr",
            "fallback": None,
            "evidence": {"class": "alpaca_differs", "median_ibkr_over_alpaca": 0.7557},
        }
    ],
    "retire_symbol_rows": [
        {"policy_id": _ID_A, "symbol": "WDC", "disposition": "replaced", "evidence": {"n": 1}},
        {
            "policy_id": _ID_B,
            "symbol": "OKE",
            "disposition": "superseded_by_default",
            "evidence": {"n": 2},
        },
    ],
    "keep_symbol_rows": [
        {
            "policy_id": _ID_C,
            "symbol": "SSP",
            "valid_from": "2000-01-03",
            "valid_to": None,
            "reason": "no Alpaca 1d history to arbitrate",
        }
    ],
    "hold": [
        {"symbol": "WDC", "class": "three_way", "start": "2018-01-02", "end": "2019-01-02"},
        {"symbol": "SSP", "class": "two_vendor", "start": "2018-01-02", "end": "2019-01-02"},
    ],
    "quarantine": [],
    "quarantine_rule": "vendor_disagreement",
    "reason": "D-191-Q",
    "evidence": {"decision": "D-191-Q"},
}


def test_a_1d_plan_parses_with_retired_defaults_and_explicit_dispositions():
    plan = parse_plan(_PLAN_1D)
    assert plan.retire_defaults
    assert [(str(r["valid_from"]), r["primary_source"]) for r in plan.defaults] == [
        ("1990-01-01", "ibkr"),
        ("2016-01-04", "alpaca"),
    ]
    assert [r["symbol"] for r in plan.symbol_rows] == ["WDC"]
    assert {r["policy_id"] for r in plan.retire_symbol_rows} == {_ID_A, _ID_B}
    assert [r["policy_id"] for r in plan.keep_symbol_rows] == [_ID_C]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"retire_symbol_rows": None, "keep_symbol_rows": None}, "explicit"),
        ({"seam": "2017-01-03"}, "seam"),
        (
            {
                "retire_symbol_rows": [
                    {"policy_id": _ID_A, "symbol": "WDC", "disposition": "maybe", "evidence": {}}
                ]
            },
            "disposition",
        ),
        (
            {
                "retire_symbol_rows": [
                    {"policy_id": _ID_B, "symbol": "OKE", "disposition": "replaced", "evidence": {}}
                ]
            },
            "no new symbol row",
        ),
        (
            {"keep_symbol_rows": [{"policy_id": _ID_A, "symbol": "WDC", "reason": "x"}]},
            "listed twice",
        ),
        (
            {"keep_symbol_rows": [{"policy_id": _ID_C, "symbol": "WDC", "reason": "hold"}]},
            "kept",
        ),
        ({"symbol_rows": [{**_PLAN_1D["symbol_rows"][0], "evidence": {}}]}, "evidence"),
        ({"retire_default_ids": [_ID_DT]}, "default"),
        ({"raw_fingerprint": None}, "fingerprint"),
        (
            {
                "hold": [
                    {
                        "symbol": "OKE",
                        "class": "three_way",
                        "start": "2018-01-02",
                        "end": "2019-01-02",
                    }
                ]
            },
            "not covered",
        ),
        (
            {
                "retire_symbol_rows": [
                    {
                        "policy_id": _ID_B,
                        "symbol": "OKE",
                        "disposition": "confirmed",
                        "evidence": {},
                    }
                ]
            },
            "disposition",
        ),
    ],
)
def test_an_invalid_1d_plan_is_refused(change, message):
    raw = {k: v for k, v in {**_PLAN_1D, **change}.items() if v is not None}
    with pytest.raises(ValueError, match=message):
        parse_plan(raw)


@pytest.fixture
async def temp_policy_1d():
    import asyncpg

    conn = await asyncpg.connect(_LIVE_DB_DSN)
    txn = conn.transaction()
    await txn.start()
    try:
        await conn.execute(
            "CREATE TEMP TABLE bar_source_policy"
            " (LIKE public.bar_source_policy INCLUDING ALL);"
            "CREATE TRIGGER trg_copy BEFORE INSERT OR UPDATE OR DELETE ON pg_temp.bar_source_policy"
            " FOR EACH ROW EXECUTE FUNCTION public.bar_source_policy_append_only();"
            "CREATE TEMP VIEW bar_source_policy_current AS"
            " SELECT * FROM pg_temp.bar_source_policy WHERE retired_at IS NULL;"
            "CREATE TEMP VIEW bar_source_policy_changes AS SELECT * FROM pg_temp.bar_source_policy;"
        )
        await conn.execute(
            "INSERT INTO bar_source_policy (policy_id, timeframe, symbol, valid_from, ingress_mode,"
            " primary_source, fallback_source, reason, recorded_at) VALUES"
            f" ('{_ID_DT}', '1d', NULL, DATE '1990-01-01', 'observed', 'tradier', 'ibkr',"
            " 'seed', '2026-01-01'),"
            f" ('{_ID_A}', '1d', 'WDC', DATE '1990-01-01', 'observed', 'ibkr', NULL, 's', '2026-01-01'),"
            f" ('{_ID_B}', '1d', 'OKE', DATE '1990-01-01', 'observed', 'ibkr', NULL, 's', '2026-01-01'),"
            f" ('{_ID_C}', '1d', 'SSP', DATE '2000-01-03', 'observed', 'tradier', 'ibkr', 's',"
            " '2026-01-01');"
        )
        # The live shape: the Tradier default closed at D, IBKR open from D.
        await conn.execute(
            "UPDATE bar_source_policy SET valid_to = DATE '2026-10-07'"
            " WHERE timeframe = '1d' AND symbol IS NULL"
        )
        await conn.execute(
            "UPDATE bar_source_policy SET valid_to = DATE '2026-10-07'"
            " WHERE timeframe = '1d' AND symbol IN ('WDC', 'OKE')"
        )
        await conn.execute(
            "INSERT INTO bar_source_policy (policy_id, timeframe, symbol, valid_from,"
            " ingress_mode, primary_source, reason, recorded_at) VALUES"
            f" ('{_ID_DI}', '1d', NULL, DATE '2026-10-07', 'observed', 'ibkr', 'seed',"
            " '2026-01-01')"
        )
        yield conn
    finally:
        await txn.rollback()
        await conn.close()


@pytest.fixture(autouse=True)
def _plan_fingerprint(monkeypatch):
    """The apply re-reads the raw fingerprint; these tests stub it to the plan's own."""

    async def same(conn, through):
        return _FINGERPRINT

    monkeypatch.setattr("scripts.ops.bars.ops_source_policy.read_raw_fingerprint", same)


@pytest.mark.skipif(not _db_reachable(), reason="needs the local database")
@pytest.mark.asyncio
async def test_the_1d_plan_retires_both_defaults_and_writes_the_arbitrated_rows(temp_policy_1d):
    from scripts.ops.bars.ops_source_policy import apply_plan

    conn = temp_policy_1d
    counts = await apply_plan(conn, parse_plan(_PLAN_1D), apply=True)
    assert counts["defaults_retired"] == 2 and counts["retired"] == 2 and counts["kept"] == 1
    assert counts["inserted"] == 2 and counts["symbol_rows_inserted"] == 1
    rows = await conn.fetch(
        "SELECT symbol, valid_from, valid_to, primary_source, fallback_source"
        " FROM bar_source_policy_current WHERE timeframe = '1d'"
        " ORDER BY symbol NULLS FIRST, valid_from"
    )
    assert [(r[0], str(r[1]), str(r[2]), r[3], r[4]) for r in rows] == [
        (None, "1990-01-01", "2016-01-04", "ibkr", None),
        (None, "2016-01-04", "None", "alpaca", "ibkr"),
        ("SSP", "2000-01-03", "None", "tradier", "ibkr"),
        ("WDC", "2016-01-04", "2025-02-24", "ibkr", None),
    ]
    reasons = dict(
        await conn.fetch(
            "SELECT policy_id::text, retired_reason FROM bar_source_policy"
            " WHERE retired_at IS NOT NULL AND symbol IS NOT NULL"
        )
    )
    assert reasons == {_ID_A: "D-191-Q: replaced", _ID_B: "D-191-Q: superseded_by_default"}


@pytest.mark.skipif(not _db_reachable(), reason="needs the local database")
@pytest.mark.asyncio
async def test_a_live_symbol_row_the_plan_does_not_name_refuses_the_whole_plan(temp_policy_1d):
    from scripts.ops.bars.ops_source_policy import apply_plan

    conn = temp_policy_1d
    before = await conn.fetchval("SELECT count(*) FROM bar_source_policy_current")
    unnamed = {**_PLAN_1D, "keep_symbol_rows": [], "hold": _PLAN_1D["hold"][:1]}
    with pytest.raises(ValueError, match="not named"):
        await apply_plan(conn, parse_plan(unnamed), apply=True)
    assert await conn.fetchval("SELECT count(*) FROM bar_source_policy_current") == before


@pytest.mark.skipif(not _db_reachable(), reason="needs the local database")
@pytest.mark.asyncio
async def test_a_1d_dry_run_leaves_the_policy_untouched(temp_policy_1d):
    from scripts.ops.bars.ops_source_policy import apply_plan

    conn = temp_policy_1d
    before = await conn.fetch("SELECT * FROM bar_source_policy_current ORDER BY policy_id")
    counts = await apply_plan(conn, parse_plan(_PLAN_1D), apply=False)
    assert counts["defaults_retired"] == 2
    assert await conn.fetch("SELECT * FROM bar_source_policy_current ORDER BY policy_id") == before


@pytest.mark.skipif(not _db_reachable(), reason="needs the local database")
@pytest.mark.asyncio
async def test_the_1d_apply_holds_a_share_row_exclusive_lock(temp_policy_1d):
    from scripts.ops.bars.ops_source_policy import apply_plan

    conn = temp_policy_1d
    await apply_plan(conn, parse_plan(_PLAN_1D), apply=True)
    modes = {
        r["mode"]
        for r in await conn.fetch(
            "SELECT mode FROM pg_locks WHERE relation = 'pg_temp.bar_source_policy'::regclass"
            " AND pid = pg_backend_pid()"
        )
    }
    assert "ShareRowExclusiveLock" in modes


@pytest.mark.skipif(not _db_reachable(), reason="needs the local database")
@pytest.mark.asyncio
async def test_a_changed_raw_fingerprint_refuses_the_plan(temp_policy_1d, monkeypatch):
    from scripts.ops.bars.ops_source_policy import apply_plan

    async def moved(conn, through):
        return {**_FINGERPRINT, "series": {"alpaca/sip_rth": {"rows": 11, "max_served_at": "x"}}}

    monkeypatch.setattr("scripts.ops.bars.ops_source_policy.read_raw_fingerprint", moved)
    conn = temp_policy_1d
    before = await conn.fetchval("SELECT count(*) FROM bar_source_policy_current")
    with pytest.raises(ValueError, match="fingerprint"):
        await apply_plan(conn, parse_plan(_PLAN_1D), apply=True)
    assert await conn.fetchval("SELECT count(*) FROM bar_source_policy_current") == before


@pytest.mark.skipif(not _db_reachable(), reason="needs the local database")
@pytest.mark.asyncio
async def test_unpinned_live_defaults_refuse_the_plan(temp_policy_1d):
    from scripts.ops.bars.ops_source_policy import apply_plan

    other = {**_PLAN_1D, "retire_default_ids": [_ID_DT, _ID_A]}
    with pytest.raises(ValueError, match="default"):
        await apply_plan(temp_policy_1d, parse_plan(other), apply=True)


_QUARANTINE = [
    {"symbol": "GDX", "session": "2020-03-16", "alpaca": 18.0, "ibkr": 19.0, "tradier": 19.0},
    {"symbol": "GDX", "session": "2020-03-17", "alpaca": 18.5, "ibkr": 19.5, "tradier": 19.5},
]


@pytest.mark.skipif(not _db_reachable(), reason="needs the local database")
@pytest.mark.asyncio
async def test_quarantine_sessions_go_through_the_flag_writer(temp_policy_1d, monkeypatch):
    import scripts.ops.bars.ops_source_policy as osp

    calls: dict = {"flags": [], "batches": []}

    async def rules(conn):
        return frozenset({"vendor_disagreement", "price_sanity"})

    async def open_batch(conn, **kwargs):
        calls["batches"].append(kwargs)
        return "batch-1"

    async def write_flags(conn, **kwargs):
        calls["flags"].append(kwargs)
        return len(kwargs["flags"])

    async def close_batch(conn, batch_id, **kwargs):
        calls["closed"] = (batch_id, kwargs["status"])

    monkeypatch.setattr(osp, "read_quarantine_rules", rules)
    monkeypatch.setattr(osp, "open_batch", open_batch)
    monkeypatch.setattr(osp, "write_flags", write_flags)
    monkeypatch.setattr(osp, "close_batch", close_batch)
    counts = await osp.apply_plan(
        temp_policy_1d, parse_plan({**_PLAN_1D, "quarantine": _QUARANTINE}), apply=True
    )
    assert counts["quarantined"] == 2 and calls["closed"] == ("batch-1", "completed")
    (call,) = calls["flags"]
    assert call["symbol"] == "GDX" and call["tf"] == "1d"
    assert call["rules_evaluated"] == frozenset({"vendor_disagreement"})
    assert [(f.timestamp.isoformat(), f.rule, f.quarantine) for f in call["flags"]] == [
        ("2020-03-16T00:00:00+00:00", "vendor_disagreement", True),
        ("2020-03-17T00:00:00+00:00", "vendor_disagreement", True),
    ]


@pytest.mark.skipif(not _db_reachable(), reason="needs the local database")
@pytest.mark.asyncio
async def test_a_quarantine_rule_outside_the_apr_list_refuses_the_plan(temp_policy_1d, monkeypatch):
    import scripts.ops.bars.ops_source_policy as osp

    async def rules(conn):
        return frozenset({"price_sanity"})

    monkeypatch.setattr(osp, "read_quarantine_rules", rules)
    with pytest.raises(ValueError, match="quarantine_rules"):
        await osp.apply_plan(
            temp_policy_1d, parse_plan({**_PLAN_1D, "quarantine": _QUARANTINE}), apply=True
        )


@pytest.mark.skipif(not _db_reachable(), reason="needs the local database")
@pytest.mark.asyncio
async def test_the_quarantine_write_clears_the_rule_on_names_the_plan_dropped(
    temp_policy_1d, monkeypatch
):
    import scripts.ops.bars.ops_source_policy as osp

    written: dict = {}

    async def rules(conn):
        return frozenset({"vendor_disagreement"})

    async def flagged(conn, rule):
        assert rule == "vendor_disagreement"
        return ["GDX", "OLD"]

    async def open_batch(conn, **kwargs):
        return "batch-1"

    async def write_flags(conn, **kwargs):
        written[kwargs["symbol"]] = [f.timestamp.date().isoformat() for f in kwargs["flags"]]
        assert kwargs["start"] is None and kwargs["end"] is None
        return len(kwargs["flags"])

    async def close_batch(conn, batch_id, **kwargs):
        return None

    for name, fn in {
        "read_quarantine_rules": rules,
        "read_flagged_symbols": flagged,
        "open_batch": open_batch,
        "write_flags": write_flags,
        "close_batch": close_batch,
    }.items():
        monkeypatch.setattr(osp, name, fn)
    await osp.apply_plan(
        temp_policy_1d, parse_plan({**_PLAN_1D, "quarantine": _QUARANTINE}), apply=True
    )
    assert written == {"GDX": ["2020-03-16", "2020-03-17"], "OLD": []}


def test_a_plan_listing_window_end_spans_is_refused():
    """A window-end span has no row; applying would let Alpaca serve it (2026-10-28 review)."""
    with pytest.raises(ValueError, match="window-end"):
        parse_plan({**_PLAN, "window_end_spans": [{"symbol": "X", "start": "2026-09-01"}]})
