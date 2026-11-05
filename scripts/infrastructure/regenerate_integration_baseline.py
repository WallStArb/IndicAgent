#!/usr/bin/env python3
"""Regenerate the integration-test baseline from production (todo 591).

tests/integration/conftest.py rebuilds indicagent_test from a pinned schema-only dump plus seed
data, then replays every migration numbered above _BASELINE_MIGRATION_CUTOFF. This writes the six
fixture files for one date in one command, so the baseline can be bumped whenever the replay
drifts:

- schema_baseline_<date>.sql: `pg_dump --schema-only` of the database;
- schema_baseline_<date>_hypertables.sql: the chunk and compressed-storage stub cleanup (the
  schema-only restore leaves both as plain tables), then create_hypertable and the compression
  attributes for every public hypertable, read from the TimescaleDB catalog (no policies);
- seed_{config,controlled_vocabulary,instruments,tag_vocabulary}_<date>.sql: data dumps of the
  tables pre-cutoff migrations seed as data, which a schema-only dump leaves empty.

After running it, point conftest.py at the new date and set the cutoff (and its not-in-baseline
set) by hand: which migrations are applied is an operator fact, not something this reads.

Usage: .venv/bin/python scripts/infrastructure/regenerate_integration_baseline.py [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import psycopg

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = _ROOT / "tests" / "integration" / "fixtures"
_DB = "indicagent"
_DSN = "postgresql://postgres:postgres@localhost:5432/indicagent"

_SEEDS: dict[str, tuple[str, ...]] = {
    "config": ("public.config_schema", "public.config_state"),
    "controlled_vocabulary": (
        "public.controlled_vocabulary",
        "public.vocabulary_group",
        "public.vocabulary_group_member",
    ),
    "instruments": ("public.instruments",),
    "tag_vocabulary": ("public.tag_vocabulary",),
}

_STUB_CLEANUP = """\
-- Chunk stubs: the schema-only dump restores _timescaledb_internal chunk tables as plain
-- inheritance children of public hypertables, which makes create_hypertable refuse ("already
-- partitioned"). Drop every inheritance child of a public table first (empty after a
-- schema-only restore), then re-register each hypertable with production's chunk interval
-- and compression attributes. Policies are intentionally not re-added.
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT c.oid::regclass::text AS child
           FROM pg_inherits i
           JOIN pg_class c ON c.oid = i.inhrelid
           JOIN pg_class p ON p.oid = i.inhparent
           WHERE p.relnamespace = 'public'::regnamespace
  LOOP EXECUTE format('DROP TABLE IF EXISTS %s', r.child); END LOOP;
END $$;

-- Compressed-hypertable storage stubs: the dump also restores every
-- _timescaledb_internal._compressed_hypertable_N as an empty heap table, which collides with
-- the N that SET (timescaledb.compress) picks. Drop them first.
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT c.oid::regclass::text AS tbl
           FROM pg_class c
           WHERE c.relnamespace = '_timescaledb_internal'::regnamespace
             AND c.relname LIKE '\\_compressed\\_hypertable\\_%'
  LOOP EXECUTE format('DROP TABLE IF EXISTS %s', r.tbl); END LOOP;
END $$;
"""

_DIMENSIONS_SQL = """
SELECT h.table_name, d.column_name, d.interval_length
FROM _timescaledb_catalog.hypertable h
JOIN _timescaledb_catalog.dimension d ON d.hypertable_id = h.id
WHERE h.schema_name = 'public' AND d.interval_length IS NOT NULL
  AND h.compression_state <> 2
ORDER BY h.table_name
"""

_COMPRESSION_SQL = """
SELECT c.relname, s.segmentby, s.orderby, s.orderby_desc
FROM _timescaledb_catalog.compression_settings s
JOIN pg_class c ON c.oid = s.relid
WHERE c.relnamespace = 'public'::regnamespace
ORDER BY c.relname
"""


def _pg_dump(args: list[str], out: Path) -> None:
    env = {**os.environ, "PGPASSWORD": "postgres"}
    with out.open("w") as handle:
        subprocess.run(
            ["pg_dump", "-U", "postgres", "-h", "localhost", *args, _DB],
            env=env,
            stdout=handle,
            check=True,
        )


def hypertables_sql(conn: psycopg.Connection) -> str:
    lines = [_STUB_CLEANUP]
    for table, column, interval in conn.execute(_DIMENSIONS_SQL).fetchall():
        lines.append(
            f"SELECT create_hypertable('public.{table}'::regclass, '{column}'::name, "
            f"chunk_time_interval => {interval});"
        )
    lines.append("")
    for table, segmentby, orderby, orderby_desc in conn.execute(_COMPRESSION_SQL).fetchall():
        options = ["timescaledb.compress"]
        if segmentby:
            options.append(f"timescaledb.compress_segmentby = '{','.join(segmentby)}'")
        if orderby:
            terms = [
                f"{name} DESC" if desc else name
                for name, desc in zip(orderby, orderby_desc or [False] * len(orderby), strict=True)
            ]
            options.append(f"timescaledb.compress_orderby = '{','.join(terms)}'")
        lines.append(f"ALTER TABLE public.{table} SET ({', '.join(options)});")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--date", default=datetime.now(UTC).date().isoformat())
    args = parser.parse_args()
    date = args.date

    _pg_dump(["--schema-only"], _FIXTURES / f"schema_baseline_{date}.sql")
    for name, tables in _SEEDS.items():
        table_args = [arg for table in tables for arg in ("-t", table)]
        _pg_dump(["--data-only", "--inserts", *table_args], _FIXTURES / f"seed_{name}_{date}.sql")
    with psycopg.connect(_DSN) as conn:
        (_FIXTURES / f"schema_baseline_{date}_hypertables.sql").write_text(hypertables_sql(conn))
    print(f"wrote 6 fixture files for {date} under {_FIXTURES}")


if __name__ == "__main__":
    main()
