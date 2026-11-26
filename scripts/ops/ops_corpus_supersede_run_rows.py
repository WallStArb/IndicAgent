"""ops_corpus_supersede_run_rows.py - clear one corpus run's stored feature_vectors units so a new run can load them.

A unit completed under another run and not adopted (a new pin gives every unit a new batch key) blocks the
new run: its COPY fails on the primary key after minutes of compute (2026-11-26: nine units, 438,171 rows,
then eca9e854's 63 units when the pin moved again). The runbook's recovery (docs/operations/corpus-rerun-runbook.md,
Recovery) is the sanctioned `completed -> superseded` transition (migration 416), then the unit's
replace_where delete: rows of (symbols, tf, range). The runner never does it itself; this tool does, per unit.

    .venv/bin/python scripts/ops/ops_corpus_supersede_run_rows.py <run_id>           # dry run: list, count, check
    .venv/bin/python scripts/ops/ops_corpus_supersede_run_rows.py <run_id> --apply   # flip and delete, per unit

Dry run is the default and writes nothing. Each unit is one transaction on one serial connection: flip the
provenance row, delete its rows, assert the deleted count equals the row_count its load recorded; a mismatch
(another unit's rows in the same replace_where, a partial load) rolls that unit back and stops the run of
the tool, so nothing the provenance cannot account for is ever deleted. Refused while a corpus run,
ic_measure or rebuild process is live. Exit 0 clean, 1 a mismatch, a live run or an unknown run.
"""

from __future__ import annotations

import argparse
import dataclasses
import re
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

TARGET_TABLE = "feature_vectors"
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

_UNITS_SQL = """
SELECT batch_key, generation, tf, range_start, range_end, symbols, row_count
  FROM provenance_batch
 WHERE run_id = %s::uuid AND target_table = %s AND status = 'completed'
 ORDER BY tf, range_start, batch_key
"""
_COUNT_SQL = f"""
SELECT count(*) FROM {TARGET_TABLE}
 WHERE symbol = ANY(%s) AND tf = %s AND bar_ts >= %s AND bar_ts < %s
"""
_DELETE_SQL = f"""
DELETE FROM {TARGET_TABLE}
 WHERE symbol = ANY(%s) AND tf = %s AND bar_ts >= %s AND bar_ts < %s
"""
# the provenance row by its primary key, under the named run: exactly one row flips or the unit stops
_FLIP_SQL = (
    "UPDATE provenance_batch SET status = 'superseded' "
    "WHERE batch_key = %s AND generation = %s AND run_id = %s::uuid AND status = 'completed'"
)


@dataclasses.dataclass(frozen=True)
class Unit:
    batch_key: str
    generation: int
    run_id: str
    tf: str
    range_start: datetime
    range_end: datetime
    symbols: tuple[str, ...]
    row_count: int

    @property
    def where(self) -> tuple[Any, ...]:
        return (list(self.symbols), self.tf, self.range_start, self.range_end)


@dataclasses.dataclass(frozen=True)
class Plan:
    unit: Unit
    stored: int

    @property
    def ok(self) -> bool:
        """The rows in the unit's replace_where are exactly the rows its load recorded."""
        return self.stored == self.unit.row_count


def fetch_units(conn: Any, run_id: str) -> list[Unit]:
    rows = conn.execute(_UNITS_SQL, (run_id, TARGET_TABLE)).fetchall()
    return [
        Unit(key, int(generation), run_id, tf, start, end, tuple(symbols), int(count))
        for key, generation, tf, start, end, symbols, count in rows
    ]


def plan(conn: Any, units: Sequence[Unit]) -> list[Plan]:
    return [Plan(unit, int(conn.execute(_COUNT_SQL, unit.where).fetchone()[0])) for unit in units]


def render(plans: Sequence[Plan], apply: bool) -> tuple[list[str], bool]:
    """The report lines and whether every unit is clean (stored rows equal the recorded row_count)."""
    lines = [
        f"{'ok  ' if p.ok else 'FAIL'} {p.unit.batch_key[:12]} {p.unit.tf} {len(p.unit.symbols)} names "
        f"{p.unit.range_start:%Y-%m-%d}..{p.unit.range_end:%Y-%m-%d} recorded {p.unit.row_count} stored {p.stored}"
        for p in plans
    ]
    total = sum(p.stored for p in plans)
    bad = [p for p in plans if not p.ok]
    lines.append(f"{len(plans)} units, {total} stored rows, {len(bad)} mismatched")
    if bad:
        lines.append(
            "refused: a unit's stored rows differ from its recorded row_count; nothing is deleted"
        )
    elif not apply:
        lines.append("dry run: nothing written; add --apply to supersede and delete")
    return lines, not bad


def supersede_and_delete(conn: Any, plans: Sequence[Plan]) -> list[str]:
    """Per unit, one transaction: flip, delete, assert the count. Raises on a mismatch after the rollback."""
    done = []
    for p in plans:
        with conn.transaction():
            flipped = conn.execute(
                _FLIP_SQL, (p.unit.batch_key, p.unit.generation, p.unit.run_id)
            ).rowcount
            if flipped != 1:
                raise RuntimeError(
                    f"{p.unit.batch_key[:12]}: the provenance flip touched {flipped} rows, not 1 "
                    "(the unit is no longer completed under this run); rolled back"
                )
            deleted = conn.execute(_DELETE_SQL, p.unit.where).rowcount
            if deleted != p.unit.row_count:
                raise RuntimeError(
                    f"{p.unit.batch_key[:12]}: deleted {deleted}, recorded row_count {p.unit.row_count}; rolled back"
                )
        done.append(f"{p.unit.batch_key[:12]} {p.unit.tf} superseded, deleted {p.unit.row_count}")
    done.append(f"deleted {sum(p.unit.row_count for p in plans)} rows in {len(plans)} units")
    return done


def _live_run_refusal() -> str | None:
    from services import rebuild_preconditions as rp

    result = rp.check_no_live_run(rp.fetch_process_lines(), "")
    return None if result.ok else result.detail


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_id", help="the corpus_run whose feature_vectors units to clear")
    parser.add_argument(
        "--apply", action="store_true", help="flip and delete; the default is a dry run"
    )
    args = parser.parse_args(argv)
    if not _UUID.match(args.run_id):
        parser.error(f"{args.run_id!r} is not a run id (a lowercase uuid)")
    refusal = _live_run_refusal()
    if refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 1

    import psycopg

    from src.config.settings import Settings

    with psycopg.connect(Settings().database_url, autocommit=True) as conn:
        if not conn.execute(
            "SELECT 1 FROM corpus_run WHERE run_id = %s::uuid", (args.run_id,)
        ).fetchone():
            print(f"refused: no corpus_run row for {args.run_id}", file=sys.stderr)
            return 1
        plans = plan(conn, fetch_units(conn, args.run_id))
        lines, clean = render(plans, args.apply)
        print("\n".join(lines))
        if not clean or not args.apply:
            return 0 if clean else 1
        try:
            print("\n".join(supersede_and_delete(conn, plans)))
        except RuntimeError as error:
            print(f"STOPPED: {error}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
