"""The ticker-entity map's --install, --rollback and pit install against a throwaway Postgres database.

The schema is migrations 586 and 598 themselves (ticker_event, its retire-only trigger and the
exclusion constraints, the cik_ticker scheme), on minimal stand-ins for the tables they reference. Each test creates the database
``ticker_install_test``, seeds a small fixture and drops the database afterwards; the live
``indicagent`` database is never opened. Skips when no local Postgres answers (CI has none).

    .venv/bin/pytest tests/integration/test_ticker_entity_map_install_db.py -m integration --noconftest -q
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date
from pathlib import Path

import asyncpg
import psycopg
import pytest

import services.ticker_entity_map_writer as writer
from services.ticker_entity_map_writer import (
    _DOC_SPANS_SQL,
    _LIVE_SQL,
    _LOCK_SQL,
    _PIT_LOCK_IDENTIFIERS_SQL,
    PIT_KIND,
    DocPlacement,
    InstallRefused,
    PitBuild,
    ReconcileInputs,
    TickerEntityMapInstaller,
    WitnessRegion,
    content_sha256,
    install_pit_plan,
    live_old_spans,
    plan_documentary_map,
    reconcile_coverage,
    render_documentary_map,
    rollback_in_transaction,
    write_map_files,
)
from src.core.database_manager import connect_with_codecs, create_pool
from src.intelligence.bars import ticker_entity_map_pit as pit

pytestmark = pytest.mark.integration

DB_NAME = f"ticker_install_test_{os.getpid()}"
MAINTENANCE_URL = "postgresql://postgres:postgres@localhost:5432/postgres"
DSN = f"postgresql://postgres:postgres@localhost:5432/{DB_NAME}"
_MIGRATIONS = Path(__file__).resolve().parents[2] / "production/migrations"
MIGRATIONS = (
    _MIGRATIONS / "586_massive_admission_schema.sql",
    _MIGRATIONS / "598_security_identifier_cik_ticker_scheme.sql",
)
D = date.fromisoformat

# stand-ins for what migration 586 references and the installer's load-row checks read
PREREQUISITES = """
CREATE TABLE instruments (
    symbol text PRIMARY KEY, base text, contract_details jsonb, is_active boolean,
    compute_eligible boolean, compute_eligible_1d boolean, live_tradeable boolean,
    universe_entry_date date, universe_cohort text);
CREATE TABLE controlled_vocabulary (
    namespace text, code text, label text, description text, sort_order int,
    UNIQUE (namespace, code));
CREATE TABLE corporate_action (inferred_by text);
CREATE TABLE ohlcv_load (
    load_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), symbol text NOT NULL,
    caller text NOT NULL, loaded_at timestamptz NOT NULL DEFAULT now(), detail text);
"""
FIGI = {"LUMN": "BBG000000011", "ZZZ": "BBG000000022", "RGA": "BBG000000033"}
SCLASS_NOF = "BBG000000055"
SPANS = [  # symbol, ticker, valid_from, valid_to
    ("LUMN", "LUMN", "2003-09-10", "2021-01-22"),
    ("LUMN", "LUMN", "2021-01-22", None),
    ("ZZZ", "ZZZ", "2010-01-04", None),
    ("RGA", "RGA", "2003-09-10", "2008-11-26"),
    ("NOF", "NOF", "2012-01-03", None),  # resolves to a share-class FIGI only: no composite_figi
]
REGIONS = [WitnessRegion("LUMN", D("2003-09-10"), D("2020-09-18"), "placed", 4286)]
PLACEMENTS = [
    DocPlacement("LUMN", "CTL", D("2003-09-10"), D("2020-09-18"), 4286, "before_first_event",
                 "cik_and_share_class_figi_same", "agrees", "")  # fmt: skip
]
LOST_1D = b"symbol,session,file_ticker,class\nLUMN,2010-01-04,CTL,map_gap\n"
LOST_5M = b"symbol,session,alt_ticker,class\n"
EXPECTED = {"1d": {"map_gap_rows": 1, "covered": 1}, "5m": {"map_gap_rows": 0, "covered": 0}}


@pytest.fixture
def db():
    try:
        admin = psycopg.connect(MAINTENANCE_URL, autocommit=True)
    except psycopg.OperationalError as error:
        pytest.skip(f"no local Postgres: {error}")
    with admin:
        admin.execute(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {DB_NAME}")
        try:
            with psycopg.connect(DSN, autocommit=True) as conn:
                conn.execute(PREREQUISITES)
                for migration in MIGRATIONS:
                    conn.execute(migration.read_text())
                _seed(conn)
            yield DSN
        finally:
            admin.execute(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)")


def _seed(conn: psycopg.Connection) -> None:
    symbols = [*FIGI, "NOF"]
    raw, ident = {}, {}
    for line, symbol in enumerate(symbols, 1):
        conn.execute("INSERT INTO instruments VALUES (%s)", (symbol,))
        raw[symbol] = conn.execute(
            """INSERT INTO reference_raw (vendor, endpoint, request_key, page, url, http_status,
                   body, served_at, manifest_path, manifest_line, file_path, file_sha256)
               VALUES ('massive', 'overview', %s, 1, 'u', 200, '{"status": "OK"}', now(), 'm', %s,
                       'f', %s) RETURNING reference_raw_id""",
            (f"{symbol}@active", line, "0" * 64),
        ).fetchone()[0]
        scheme, value = ("share_class_figi", SCLASS_NOF) if symbol == "NOF" else (
            "composite_figi", FIGI[symbol]
        )  # fmt: skip
        ident[symbol] = conn.execute(
            """INSERT INTO security_identifier (symbol, scheme, value, valid_from, reference_raw_id)
               VALUES (%s, %s, %s, '2003-09-10', %s) RETURNING security_identifier_id""",
            (symbol, scheme, value, raw[symbol]),
        ).fetchone()[0]
    for symbol, ticker, start, end in SPANS:
        conn.execute(
            """INSERT INTO ticker_event (security_identifier_id, symbol, vendor, ticker,
                   valid_from, valid_to, reference_raw_id, evidence)
               VALUES (%s, %s, 'massive', %s, %s, %s, %s, '{"seed": 1}')""",
            (ident[symbol], symbol, ticker, start, end, raw[symbol]),
        )


async def _fetch(sql: str):
    conn = await connect_with_codecs(DSN)
    try:
        return await conn.fetch(sql)
    finally:
        await conn.close()


async def _live_hash() -> str:
    return content_sha256(await _fetch(_LIVE_SQL))


def _exec(sql: str) -> None:
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(sql)


def _count(sql: str) -> int:
    with psycopg.connect(DSN, autocommit=True) as conn:
        return conn.execute(sql).fetchone()[0]


async def _build_map(scratch: Path) -> tuple[Path, str, ReconcileInputs]:
    """The documentary map over the live spans that carry a composite FIGI, as the --documentary run builds it."""
    old = live_old_spans(await _fetch(_DOC_SPANS_SQL))
    result = plan_documentary_map(old, [], REGIONS, PLACEMENTS, "p" * 8)
    reconcile = ReconcileInputs(LOST_1D, LOST_5M, json.dumps(EXPECTED).encode(), ())
    reconciliation = reconcile_coverage(result.spans, reconcile.rows(), EXPECTED)
    name, files = render_documentary_map(
        old, result, {"x": 1, **reconcile.pins()}, reconciliation, "20261114"
    )
    write_map_files(scratch / name, files)
    return scratch / name, writer.manifest_sha256(files), reconcile


class Run:
    """One map built from the seeded database, the installer pointed at scratch roots."""

    def __init__(self, tmp: Path, map_dir: Path, pin: str, reconcile: ReconcileInputs):
        self.tmp, self.map_dir, self.pin, self.reconcile = tmp, map_dir, pin, reconcile
        for name, data in (("lost_1d", reconcile.lost_1d), ("lost_5m", reconcile.lost_5m),
                           ("cov", reconcile.coverage_summary)):  # fmt: skip
            (tmp / name).write_bytes(data)

    def args(self, **extra) -> argparse.Namespace:
        base = dict(
            install=self.map_dir, install_digest=self.map_dir.name.split("_")[1],
            install_spans_sha256=self.pin, untouched="RGA", lost_1d=self.tmp / "lost_1d",
            lost_5m=self.tmp / "lost_5m", coverage_summary=self.tmp / "cov", hidden_1d=[],
            apply=True, rollback=None, accept_loaded_rows=False,
        )  # fmt: skip
        return argparse.Namespace(**(base | extra))

    async def install(self, **extra) -> dict:
        return await self._run(self.args(**extra), "_install")

    async def rollback(self, install_id: str, **extra) -> dict:
        return await self._run(self.args(install=None, rollback=install_id, **extra), "_rollback")

    async def _run(self, args: argparse.Namespace, method: str) -> dict:
        installer = TickerEntityMapInstaller(
            DSN, args, out_root=self.tmp / "out", rolled_back_root=self.tmp / "rolled_back"
        )
        pool = await create_pool(DSN, pool_name="ticker-install-test", min_size=1, max_size=2)
        try:
            return await getattr(installer, method)(pool)
        finally:
            await pool.close()


@pytest.fixture
async def run(db, tmp_path, monkeypatch):
    monkeypatch.setattr(writer, "massive_load_pids", lambda: [])
    return Run(tmp_path, *await _build_map(tmp_path / "scratch"))


async def test_install_apply_then_a_second_install_is_a_no_op(run, tmp_path):
    first = await run.install()
    assert first["outcome"] == "installed"
    assert first["balance"] == {
        "live_before": 4,
        "retire": 1,
        "insert": 2,
        "live_after_expected": 5,
    }
    assert (tmp_path / "out" / run.map_dir.name / "spans.csv").exists()
    # the figi-less NOF span rides along untouched: 5 live before, 1 retired, 2 inserted
    assert _count("SELECT count(*) FROM ticker_event_current") == 6
    again = await run.install()
    assert (again["outcome"], again["status"]) == ("no_op", "already_installed")
    assert _count("SELECT count(*) FROM ticker_event_current") == 6


async def test_a_rehearsal_writes_nothing(run):
    before = _count("SELECT count(*) FROM ticker_event")
    report = await run.install(apply=False)
    assert report["outcome"] == "rolled_back"
    assert _count("SELECT count(*) FROM ticker_event") == before


async def test_drifted_live_spans_are_refused(run):
    _exec("""UPDATE ticker_event SET retired_reason = 'drift'
            WHERE symbol = 'ZZZ' AND retired_at IS NULL""")
    with pytest.raises(InstallRefused, match="table moved since the map was built"):
        await run.install()
    assert _count("SELECT count(*) FROM ticker_event WHERE evidence ? 'map_install'") == 0


async def test_rollback_restores_the_content_hash_and_a_second_rollback_is_refused(run, tmp_path):
    pre = await _live_hash()
    installed = await run.install()
    assert await _live_hash() != pre
    rolled = await run.rollback(installed["install_id"])
    assert rolled["outcome"] == "rolled_back_install"
    assert (rolled["rows_retired"], rolled["rows_restored"]) == (2, 1)
    # the figi-less span is in both hashes: pre-install and post-rollback read the same rows
    assert await _live_hash() == pre
    assert pre == rolled["post_rollback_sha256"] == installed["pre_install_sha256"]
    assert not (tmp_path / "out" / run.map_dir.name).exists()
    assert (tmp_path / "rolled_back" / f"{run.map_dir.name}__{installed['install_id']}").exists()
    with pytest.raises(InstallRefused, match="already rolled back"):
        await run.rollback(installed["install_id"])


async def test_retiring_before_inserting_is_what_satisfies_the_exclusion_constraints(run):
    # the clipped LUMN span [2020-09-18, 2021-01-22) overlaps the old span it replaces
    with psycopg.connect(DSN, autocommit=True) as conn:
        row = conn.execute("""SELECT security_identifier_id, reference_raw_id FROM ticker_event
                WHERE symbol = 'LUMN' AND valid_to = '2021-01-22'""").fetchone()
        with pytest.raises(psycopg.errors.ExclusionViolation):
            conn.execute(
                """INSERT INTO ticker_event (security_identifier_id, symbol, vendor, ticker,
                       valid_from, valid_to, reference_raw_id, evidence)
                   VALUES (%s, 'LUMN', 'massive', 'LUMN', '2020-09-18', '2021-01-22', %s,
                           '{"x": 1}')""",
                row,
            )
    assert (await run.install())["outcome"] == "installed"


async def test_loads_under_the_retired_spans_are_reported_by_name(run):
    _exec("""INSERT INTO ohlcv_load (symbol, caller, loaded_at, detail)
           SELECT symbol, 'massive-5m-load', now() - interval '3 days',
                  'lineage: {"ticker_events": {"' || ticker_event_id || '": "LUMN"}}'
             FROM ticker_event WHERE symbol = 'LUMN' AND valid_to = '2021-01-22'""")
    report = await run.install(apply=False)
    assert report["loaded_under_retired_spans"] == {"LUMN": 1}


async def test_rollback_is_refused_over_loaded_rows_unless_accepted(run):
    installed = await run.install()
    _exec("""INSERT INTO ohlcv_load (symbol, caller, loaded_at, detail)
           SELECT symbol, 'massive-5m-load', now() - interval '2 hours',
                  'lineage: {"ticker_events": {"' || ticker_event_id || '": "CTL"}}'
             FROM ticker_event WHERE ticker = 'CTL'""")
    with pytest.raises(InstallRefused, match=r"cite spans this install inserted: \{'LUMN': 1\}"):
        await run.rollback(installed["install_id"])
    with pytest.raises(InstallRefused, match="cite spans"):
        await run.rollback(installed["install_id"], apply=False)
    assert (
        _count("SELECT count(*) FROM ticker_event WHERE retired_reason LIKE 'ticker_map_roll%'")
        == 0
    )
    rolled = await run.rollback(installed["install_id"], accept_loaded_rows=True)
    assert rolled["loaded_rows_citing_inserted"] == {"LUMN": 1}
    assert rolled["accepted_loaded_rows"] is True


async def test_the_flag_without_loaded_rows_changes_nothing(run):
    installed = await run.install()
    rolled = await run.rollback(installed["install_id"], accept_loaded_rows=True)
    assert (rolled["loaded_rows_citing_inserted"], rolled["accepted_loaded_rows"]) == ({}, False)


async def test_a_massive_load_in_the_last_half_hour_or_a_visible_loader_refuses(run, monkeypatch):
    _exec("INSERT INTO ohlcv_load (symbol, caller, detail) VALUES ('ZZZ', 'massive-1d-load', 'x')")
    with pytest.raises(InstallRefused, match="last 30 minutes"):
        await run.install()
    _exec("UPDATE ohlcv_load SET loaded_at = now() - interval '31 minutes'")
    monkeypatch.setattr(writer, "massive_load_pids", lambda: [4242])
    with pytest.raises(InstallRefused, match=r"ops_massive_load is running \(pids \[4242\]\)"):
        await run.install()
    monkeypatch.setattr(writer, "massive_load_pids", lambda: [])
    assert (await run.install())["outcome"] == "installed"


async def test_the_map_pin_is_enforced_before_the_database_is_touched(run):
    with pytest.raises(InstallRefused, match="--install-spans-sha256"):
        await run.install(install_spans_sha256=hashlib.sha256(b"other").hexdigest())
    assert _count("SELECT count(*) FROM ticker_event WHERE evidence ? 'map_install'") == 0


def test_the_database_is_dropped_after_the_tests():
    try:
        admin = psycopg.connect(MAINTENANCE_URL, autocommit=True)
    except psycopg.OperationalError as error:
        pytest.skip(f"no local Postgres: {error}")
    with admin:
        left = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,)).fetchone()
    assert left is None


# ---------------------------------------------------------------------------------------------
# The pit install and its rollback (retire_install_identifiers), on the real schema
# ---------------------------------------------------------------------------------------------

PIT_FIRST, PIT_LAST = D("2015-01-30"), D("2019-06-28")
PIT_EVIDENCE = '{"pit": 1}'


def _pit_plan(raw: str) -> pit.PitPlan:
    """Two new securities, one keyed by composite FIGI and one by (CIK, ticker), one span each."""
    figi, cik_key = "BBG000000101", "0000000002:PITB"
    securities = tuple(
        pit.PitSecurity(symbol, kind, key, cik, composite, None, symbol, "XNYS", ("CS",),
                        PIT_FIRST, PIT_LAST, (symbol,))
        for symbol, kind, key, cik, composite in (
            ("PITA", pit.COMPOSITE_FIGI, figi, None, figi),
            ("PITB", pit.CIK_TICKER, cik_key, "0000000002", None),
        )
    )  # fmt: skip
    return pit.PitPlan(
        securities,
        tuple(
            pit.PitIdentifier(s.symbol, s.key_kind, s.key_value, PIT_FIRST, None, raw)
            for s in securities
        ),
        tuple(
            pit.PitSpan(s.symbol, s.symbol, PIT_FIRST, D("2019-07-01"), raw, PIT_EVIDENCE)
            for s in securities
        ),
        (), {}, {}, 1, PIT_FIRST, PIT_LAST,
    )  # fmt: skip


async def _state(conn: asyncpg.Connection) -> dict:
    """The live-span hash and the row counts of the four tables an install writes."""
    counts = {
        table: await conn.fetchval(f"SELECT count(*) FROM {table}")
        for table in ("instruments", "security_identifier", "ticker_event")
    }
    counts["identifiers_live"] = await conn.fetchval(
        "SELECT count(*) FROM security_identifier_current"
    )
    return {"live": content_sha256(await conn.fetch(_LIVE_SQL)), **counts}


def _lineage(plan: pit.PitPlan, install_id: str, pre_install_sha256: str) -> dict:
    return {
        "install_id": install_id, "map_digest": "d", "map_dir": "20261116_d",
        "pre_install_sha256": pre_install_sha256, "rows_retired": 0,
        "rows_inserted": len(plan.spans), "kind": PIT_KIND,
    }  # fmt: skip


async def _install(conn: asyncpg.Connection, plan: pit.PitPlan, install_id: str, pre: str) -> dict:
    async with conn.transaction():
        await conn.execute(_LOCK_SQL)
        await conn.execute(_PIT_LOCK_IDENTIFIERS_SQL)
        return await install_pit_plan(
            conn, PitBuild("20261116_d", {}, plan, ()), _lineage(plan, install_id, pre)
        )


@pytest.fixture
async def pit_conn(db, monkeypatch):
    monkeypatch.setattr(writer, "massive_load_pids", lambda: [])
    conn = await connect_with_codecs(DSN)
    try:
        yield conn, _pit_plan(
            str(await conn.fetchval("SELECT reference_raw_id FROM reference_raw"))
        )
    finally:
        await conn.close()


async def test_a_pit_rollback_retires_the_identifiers_the_install_inserted_and_restores_the_rows(
    pit_conn,
):
    conn, plan = pit_conn
    before = await _state(conn)
    written = await _install(conn, plan, "pit-1", before["live"])
    assert written["identifiers_inserted"] == 2 and written["spans_inserted"] == 2
    installed = await _state(conn)
    assert (
        installed["live"] != before["live"]
        and installed["identifiers_live"] == before["identifiers_live"] + 2
    )
    async with conn.transaction():
        report = await rollback_in_transaction(conn, "pit-1", False)
    assert report["identifiers_retired"] == 2 and report["rows_retired"] == 2
    assert report["post_rollback_sha256"] == report["pre_install_sha256"] == before["live"]
    after = await _state(conn)
    assert (
        after["live"] == before["live"] and after["identifiers_live"] == before["identifiers_live"]
    )
    # the inactive instrument rows, the identifiers and the spans stay as retired history
    assert after["instruments"] == before["instruments"] + 2
    assert after["security_identifier"] == before["security_identifier"] + 2
    assert after["ticker_event"] == before["ticker_event"] + 2


async def test_a_rehearsal_that_installs_and_rolls_back_leaves_every_table_as_it_was(pit_conn):
    conn, plan = pit_conn
    before = await _state(conn)

    class Rehearsal(Exception):
        pass

    with pytest.raises(Rehearsal):
        async with conn.transaction():
            await install_pit_plan(
                conn, PitBuild("20261116_d", {}, plan, ()), _lineage(plan, "pit-2", before["live"])
            )
            await rollback_in_transaction(conn, "pit-2", False)
            raise Rehearsal
    assert await _state(conn) == before


@pytest.mark.parametrize(
    ("foreign_span_retired", "error", "message"),
    [
        (True, InstallRefused, "outside the install"),
        (False, asyncpg.exceptions.CheckViolationError, "retire them first"),
    ],
)
async def test_a_pit_rollback_refuses_and_writes_nothing_when_a_retired_identifier_has_a_foreign_span(
    pit_conn, foreign_span_retired, error, message
):
    """The identifier retire matches by symbol. An older identifier of an install symbol (the
    instrument row is a stage 2 row an earlier install left) that a span outside the install
    resolves to must stop the rollback: by the assertion when that span is retired, by the
    identity trigger when it is live. Either way the transaction leaves every table as it was."""
    conn, plan = pit_conn
    raw = plan.identifiers[0].reference_raw_id
    details = {"provider_meta": {"key_kind": pit.CIK_TICKER, "key": "0000000002:PITB"}}
    await conn.execute(
        "INSERT INTO instruments (symbol, universe_cohort, contract_details) "
        "VALUES ('PITB', 'stage2_pit', $1::jsonb)", details,
    )  # fmt: skip
    older = await conn.fetchval(
        "INSERT INTO security_identifier (symbol, scheme, value, valid_from, reference_raw_id) "
        "VALUES ('PITB', 'isin', 'US0000000002', '2010-01-04', $1::uuid) "
        "RETURNING security_identifier_id", raw,
    )  # fmt: skip
    await conn.execute(
        "INSERT INTO ticker_event (security_identifier_id, symbol, vendor, ticker, valid_from, "
        "valid_to, reference_raw_id, evidence) VALUES ($1, 'PITB', 'massive', 'PITBOLD', "
        "'2010-01-04', '2011-01-03', $2::uuid, '{\"foreign\": 1}')", older, raw,
    )  # fmt: skip
    if foreign_span_retired:
        await conn.execute(
            "UPDATE ticker_event SET retired_reason = 'test' WHERE ticker = 'PITBOLD'"
        )
    before = await _state(conn)
    await _install(conn, plan, "pit-3", before["live"])
    installed = await _state(conn)
    with pytest.raises(error, match=message):
        async with conn.transaction():
            await rollback_in_transaction(conn, "pit-3", False)
    assert await _state(conn) == installed
    assert await conn.fetchval(
        "SELECT retired_at IS NULL FROM security_identifier WHERE security_identifier_id = $1",
        older,
    )  # fmt: skip
