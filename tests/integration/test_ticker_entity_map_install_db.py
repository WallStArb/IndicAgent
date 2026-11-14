"""The ticker-entity map's --install and --rollback against a throwaway Postgres database.

The schema is migration 586 itself (ticker_event, its retire-only trigger and the exclusion
constraints), on minimal stand-ins for the tables it references. Each test creates the database
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

import psycopg
import pytest

import services.ticker_entity_map_writer as writer
from services.ticker_entity_map_writer import (
    _DOC_SPANS_SQL,
    _LIVE_SQL,
    DocPlacement,
    InstallRefused,
    ReconcileInputs,
    TickerEntityMapInstaller,
    WitnessRegion,
    content_sha256,
    live_old_spans,
    plan_documentary_map,
    reconcile_coverage,
    render_documentary_map,
    write_map_files,
)
from src.core.database_manager import connect_with_codecs, create_pool

pytestmark = pytest.mark.integration

DB_NAME = f"ticker_install_test_{os.getpid()}"
MAINTENANCE_URL = "postgresql://postgres:postgres@localhost:5432/postgres"
DSN = f"postgresql://postgres:postgres@localhost:5432/{DB_NAME}"
MIGRATION = (
    Path(__file__).resolve().parents[2] / "production/migrations/586_massive_admission_schema.sql"
)
D = date.fromisoformat

# stand-ins for what migration 586 references and the installer's load-row checks read
PREREQUISITES = """
CREATE TABLE instruments (symbol text PRIMARY KEY);
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
                conn.execute(MIGRATION.read_text())
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
