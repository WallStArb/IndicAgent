"""Restore the 2026-10-28 Tradier delete backups into ohlcv_raw (todo 574, owner decision
2026-11-01: the Tradier-era history is KEEP, Option A).

The delete's COPY backups are the only copy of the Tradier-era daily history (for some names
materially deeper than IBKR's; the vendor no longer serves it). This script loads them back
through the raw-capture law (528): `persist_chunk_atomically` writes the rows last-wins under
the bar_derivation_writer role, moves the 1d coverage ledger bounds for the restored symbols
and logs revisions wherever a restored row would displace a newer answer (none expected:
nothing else writes vendor='tradier'). Rows are grouped by their original (served_at,
request_id), so served time and lineage survive the round trip exactly. The 1d coverage
ledger is refreshed once for all symbols at the end state, not per chunk: per-chunk refreshes
rescan each symbol's growing raw rows thousands of times (measured 89k rows in 8 minutes).

Restore order is the delete order reversed per ops_tradier_delete.py TABLES: revision rows
first (their recorded load ids are lineage, inserted as-is, no conflict), then ohlcv_raw. The
market_data_ohlcv backup is NOT restored: canonical is a rebuildable selection and
bar_source_policy does not select tradier (`ops_selection_gate.py --compare` proves it after).
The ohlcv_coverage backup is empty; the ledger rows are recomputed by the refresh instead.

Run: .venv/bin/python scripts/ops/bars/ops_tradier_restore.py --apply
Without --apply: report the groups and rows only.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from scripts.infrastructure.backfill._intraday_persist import persist_chunk_atomically
from services.ohlcv_ingress_contract import read_raw_params
from services.ohlcv_raw_writer import RawRow

BACKUP = Path("data/backups/191/tradier_ohlcv_raw_2026-10-28.csv.gz")
REVISION_BACKUP = Path("data/backups/191/tradier_ohlcv_revision_2026-10-28.csv.gz")
MANIFEST = Path("data/backups/191/tradier_delete_manifest.json")
DSN = "postgresql://postgres:postgres@localhost:5432/indicagent"
BATCH_GROUPS = 40  # persist calls per transaction batch (each call commits its own chunk)


def _groups():
    """(served_at, request_id) -> [RawRow, ...], preserving the backup's lineage."""
    groups: dict[tuple[datetime, str], list[RawRow]] = defaultdict(list)
    with gzip.open(BACKUP, "rt", newline="") as f:
        for row in csv.reader(f):
            (
                timestamp,
                symbol,
                timeframe,
                vendor,
                kind,
                o,
                h,
                lo,
                c,
                v,
                served_at,
                request_id,
                _load_id,
            ) = row
            groups[(datetime.fromisoformat(served_at), request_id)].append(
                RawRow(
                    timestamp=datetime.fromisoformat(timestamp),
                    symbol=symbol,
                    timeframe=timeframe,
                    vendor=vendor,
                    kind=kind,
                    open=float(o),
                    high=float(h),
                    low=float(lo),
                    close=float(c),
                    volume=int(v) if v else None,
                )
            )
    return groups


def _restore_revision(conn) -> int:
    """The recorded revision rows back into ohlcv_revision as lineage (no conflict expected:
    the 191-20 delete removed them; a re-fetch could have re-displaced, hence ON CONFLICT)."""

    # one explicit transaction: autocommit would make each of the 155k inserts its own
    count = 0
    with conn.transaction():
        with conn.cursor() as cur:
            with gzip.open(REVISION_BACKUP, "rt", newline="") as f:
                for r in csv.reader(f):
                    cur.execute(
                        """
                        INSERT INTO ohlcv_revision (load_id, symbol, timeframe, "timestamp",
                                                    old_open, old_high, old_low, old_close,
                                                    old_volume, old_source, origin, vendor,
                                                    kind, request_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        tuple(None if v == "" else v for v in r),
                    )
                    count += cur.rowcount
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write; without it, report only")
    args = parser.parse_args(argv)

    import psycopg

    manifest = json.loads(MANIFEST.read_text())
    (raw_table,) = (t for t in manifest["tables"] if t["table"] == "ohlcv_raw")
    manifest_rows = sum(v[0] for v in raw_table["per_symbol"].values())
    groups = _groups()
    total = sum(len(rows) for rows in groups.values())
    print(
        f"backup: {total} raw rows in {len(groups)} (served_at, request_id) groups; "
        f"manifest says {manifest_rows}"
    )
    if total != manifest_rows:
        print(f"PROBLEM: file rows {total} != manifest {manifest_rows}")
        return 1
    if not args.apply:
        print("dry run: nothing written")
        return 0

    conn = psycopg.connect(DSN, autocommit=True)
    params = read_raw_params(conn.cursor().__enter__())
    restored = 0
    batch: list[tuple[datetime, str, list[RawRow]]] = []
    for (served_at, request_id), rows in groups.items():
        batch.append((served_at, request_id, rows))
        if len(batch) >= BATCH_GROUPS:
            restored += _persist_batch(conn, batch, params)
            batch = []
    restored += _persist_batch(conn, batch, params)
    print(f"raw rows restored: {restored}")

    revisions = _restore_revision(conn)
    print(f"revision rows restored: {revisions}")

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM ohlcv_raw WHERE vendor = 'tradier'")
        live = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM ohlcv_raw WHERE vendor = 'tradier' AND symbol = 'H'")
        h_rows = cur.fetchone()[0]
        cur.execute(
            'SELECT min("timestamp"), max("timestamp") FROM ohlcv_raw '
            "WHERE vendor = 'tradier' AND symbol = 'H'"
        )
        span = cur.fetchone()
    print(f"live tradier raw rows: {live} (expected {total})")
    print(f"H spot check: {h_rows} daily rows, {span[0]} .. {span[1]} (191-20 deleted 4,435)")
    conn.close()
    return 0 if live == total else 1


def _persist_batch(conn, batch, params) -> int:
    """One persist call per (served_at, request_id) group: served time and lineage survive."""
    restored = 0
    for served_at, request_id, rows in batch:
        result = persist_chunk_atomically(
            conn,
            request_rows=[],
            raw_rows=rows,
            caller="tradier_restore",
            request_id=uuid.UUID(request_id) if request_id else None,
            answered_at=served_at,
            params=params,
        )
        restored += result.n_rows
    return restored


if __name__ == "__main__":
    raise SystemExit(main())
