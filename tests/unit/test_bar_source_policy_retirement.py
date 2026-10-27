"""Migration 520 and D-191-P: a policy row can be retired; every reader reads the live view."""

from __future__ import annotations

import re
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
            "INSERT INTO bar_source_policy (timeframe, symbol, valid_from, ingress_mode,"
            " primary_source, reason) VALUES"
            " ('5m', NULL, DATE '1990-01-01', 'direct', 'ibkr', 'seed'),"
            " ('5m', 'SPY', DATE '2006-06-02', 'direct', 'ibkr', 'seed');"
            "INSERT INTO bar_source_policy (timeframe, symbol, valid_from, valid_to, ingress_mode,"
            " primary_source, fallback_source, reason) VALUES"
            " ('5m', 'EMR', DATE '2026-03-10', DATE '2026-07-31', 'direct', 'alpaca', 'ibkr', 'w');"
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
