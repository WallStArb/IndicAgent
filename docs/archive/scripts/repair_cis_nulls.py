#!/usr/bin/env python3
"""
CIS Null Repair Script — Audit and repair NULL cis_score rows in signal_ledger.

1. Audit phase: Counts NULL cis_score rows, classifies as recoverable (has matching
   intelligence_features row) vs orphaned (no feature match).
2. Repair phase: Re-runs CISScorer on feature vectors for recoverable rows,
   batch-UPDATEs signal_ledger with computed CIS values.
3. Orphan logging: Logs orphaned signal_ids at WARNING level.
4. Verification: Prints before/after NULL counts for operator verification.

Idempotent: Running twice is safe (WHERE cis_score IS NULL guard on UPDATE).

Usage:
    INDICAGENT_ENV=development .venv/bin/python production/scripts/repair_cis_nulls.py --dry-run
    INDICAGENT_ENV=development .venv/bin/python production/scripts/repair_cis_nulls.py
    INDICAGENT_ENV=development .venv/bin/python production/scripts/repair_cis_nulls.py \\
        --symbols ES,NQ

Design rationale (Renaissance principles):
- Instrument everything: Exact counts printed at each stage (total, recoverable, orphaned)
- Never drop data: Orphaned rows are logged, not deleted — they may recover after a backfill
- Let the system run: CISScorer recomputes scores from historical features, no manual override
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.intelligence.trading.cis_scorer import CISScorer

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------


def connect_db(settings: Settings) -> Any:
    """Create a synchronous psycopg2 connection from Settings."""
    url = settings.database_url
    url = url.replace("postgresql://", "").replace("postgres://", "")
    userpass, rest = url.split("@", 1)
    user, password = userpass.split(":", 1)
    hostport_db = rest.split("/", 1)
    hostport = hostport_db[0]
    dbname = hostport_db[1] if len(hostport_db) > 1 else "indicagent"
    host, port = hostport.split(":", 1) if ":" in hostport else (hostport, "5432")

    return psycopg2.connect(
        host=host, port=int(port), database=dbname, user=user, password=password
    )


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def merge_feature_jsonb(
    i1: dict | None,
    i3: dict | None,
    i4: dict | None,
    i5: dict | None,
    smc: dict | None,
    i6: dict | None,
) -> dict:
    """Merge all tier JSONB dicts into one flat feature dict for CISScorer.

    Skips None/empty tier dicts gracefully.
    """
    merged: dict = {}
    for tier_dict in (i1, i3, i4, i5, smc, i6):
        if tier_dict and isinstance(tier_dict, dict):
            merged.update(tier_dict)
    return merged


def classify_rows(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Classify rows as recoverable (has feature data) vs orphaned (no match).

    Returns:
        (recoverable_rows, orphaned_signal_ids)
    """
    recoverable = []
    orphaned = []

    for row in rows:
        if row.get("feature_ts") and row.get("i1") is not None:
            recoverable.append(row)
        else:
            orphaned.append(row["signal_id"])

    return recoverable, orphaned


def build_cis_update_params(signal_id: str, cis_result: Any) -> tuple[float, str, int, str]:
    """Build parameters for UPDATE signal_ledger query.

    Returns:
        (cis_score, json_bucket_scores, weights_version, signal_id)
    """
    return (
        cis_result.cis_score,
        json.dumps(cis_result.bucket_scores),
        cis_result.weights_version,
        signal_id,
    )


# ---------------------------------------------------------------------------
# Audit functions
# ---------------------------------------------------------------------------


def audit_null_cis(
    conn: Any, symbols: list[str] | None = None
) -> tuple[int, list[dict], list[str]]:
    """Audit NULL cis_score rows in signal_ledger.

    Returns:
        (total_null_count, recoverable_rows, orphaned_signal_ids)

    Recoverable rows include: signal_id, symbol, feature_ts, feature_tf, and
    all tier JSONB columns (i1, i3, i4, i5, smc, i6).
    """
    with conn.cursor() as cur:
        # Total NULL count (use regular cursor, not RealDictCursor, for COUNT(*))
        if symbols:
            where_clause = "WHERE sl.cis_score IS NULL AND sl.symbol = ANY(%s)"
            cur.execute(
                f"SELECT COUNT(*) FROM signal_ledger sl {where_clause}",
                (symbols,),
            )
        else:
            where_clause = "WHERE sl.cis_score IS NULL"
            cur.execute(f"SELECT COUNT(*) FROM signal_ledger sl {where_clause}")

        total_null = cur.fetchone()[0]

        logger.info("Total NULL cis_score rows: %d", total_null)

    # Now use RealDictCursor for row fetching
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

        # Recoverable rows: JOIN with intelligence_features
        recoverable_query = f"""
            SELECT sl.signal_id, sl.symbol, sl.feature_ts, sl.feature_tf,
                   f.i1, f.i3, f.i4, f.i5, f.smc, f.i6
            FROM signal_ledger sl
            JOIN intelligence_features f
                ON f.ts = sl.feature_ts
                AND f.symbol = sl.symbol
                AND f.tf = sl.feature_tf
            {where_clause}
            AND sl.feature_ts IS NOT NULL
            LIMIT 10000
        """
        if symbols:
            cur.execute(recoverable_query, (symbols,))
        else:
            cur.execute(recoverable_query)

        # Fetch in batches to avoid memory pressure
        recoverable_rows = []
        while True:
            batch = cur.fetchmany(1000)
            if not batch:
                break
            recoverable_rows.extend(batch)

        logger.info("Recoverable rows (have feature match): %d", len(recoverable_rows))

        # Orphaned rows: LEFT JOIN where feature row is NULL
        orphaned_query = f"""
            SELECT sl.signal_id
            FROM signal_ledger sl
            LEFT JOIN intelligence_features f
                ON f.ts = sl.feature_ts
                AND f.symbol = sl.symbol
                AND f.tf = sl.feature_tf
            {where_clause}
            AND f.ts IS NULL
        """
        if symbols:
            cur.execute(orphaned_query, (symbols,))
        else:
            cur.execute(orphaned_query)

        orphaned_rows = cur.fetchall()
        orphaned_ids = [row["signal_id"] for row in orphaned_rows]

        logger.info("Orphaned rows (no feature match): %d", len(orphaned_ids))

    return total_null, recoverable_rows, orphaned_ids


# ---------------------------------------------------------------------------
# Repair functions
# ---------------------------------------------------------------------------


def repair_recoverable(conn: Any, rows: list[dict], batch_size: int = 500) -> int:
    """Repair recoverable rows by recomputing CIS scores and UPDATEing.

    Returns:
        Number of rows updated.

    Batch-commits every `batch_size` rows to avoid holding large transactions.
    """
    if not rows:
        return 0

    scorer = CISScorer()
    updated_count = 0

    # Process in batches
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        update_params = []

        for row in batch:
            # Merge feature JSONB tiers
            features = merge_feature_jsonb(
                row["i1"], row["i3"], row["i4"], row["i5"], row["smc"], row["i6"]
            )

            # Compute CIS score (plugin_outputs={} for historical rows)
            cis_result = scorer.score(features, plugin_outputs={})

            # Build UPDATE parameters
            params = build_cis_update_params(row["signal_id"], cis_result)
            update_params.append(params)

        # Batch UPDATE
        with conn.cursor() as cur:
            update_query = """
                UPDATE signal_ledger
                SET cis_score = %s,
                    bucket_scores = %s::jsonb,
                    weights_version = %s
                WHERE signal_id = %s::uuid
                  AND cis_score IS NULL
            """
            psycopg2.extras.execute_batch(cur, update_query, update_params)

        conn.commit()
        updated_count += len(batch)
        batch_num = (i // batch_size) + 1
        total_batches = (len(rows) + batch_size - 1) // batch_size
        logger.info("Updated %d rows (batch %d/%d)", updated_count, batch_num, total_batches)

    return updated_count


def log_orphans(orphaned_ids: list[str]) -> None:
    """Log orphaned signal_ids at WARNING level."""
    logger.warning("=== Orphaned Signals (no feature match) ===")
    for signal_id in orphaned_ids:
        logger.warning("Orphaned signal (no feature match): %s", signal_id)
    logger.warning("Total orphaned signals: %d", len(orphaned_ids))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit and repair NULL cis_score rows in signal_ledger"
    )
    parser.add_argument("--dry-run", action="store_true", help="Audit only, no UPDATE")
    parser.add_argument(
        "--symbols",
        help="Limit repair to specific symbols (comma-separated, e.g. ES,NQ)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Rows per UPDATE commit (default: 500)",
    )

    args = parser.parse_args()

    # Parse symbols if provided
    symbols = None
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
        logger.info("Limiting repair to symbols: %s", ", ".join(symbols))

    # Load settings and connect
    settings = Settings()
    conn = connect_db(settings)

    try:
        print("\n=== CIS Null Audit ===")

        # Audit phase
        total_null, recoverable_rows, orphaned_ids = audit_null_cis(conn, symbols)

        if args.dry_run:
            print("\n=== Dry Run Complete (no UPDATE performed) ===")
            return

        # Repair phase
        if recoverable_rows:
            print("\n=== Repairing Recoverable Rows ===")
            updated = repair_recoverable(conn, recoverable_rows, args.batch_size)
            print(f"Updated {updated} rows with CIS scores")

        # Log orphans
        if orphaned_ids:
            log_orphans(orphaned_ids)

        # Verification phase: re-run audit
        print("\n=== Post-Repair Verification ===")
        total_null_after, recoverable_after, orphaned_after = audit_null_cis(conn, symbols)

        recoverable_remaining = len(recoverable_after)
        if recoverable_remaining > 0:
            print(
                f"\n[FAIL] Completeness gate: {recoverable_remaining} recoverable rows "
                f"still have NULL cis_score. Exit 1."
            )
            sys.exit(1)

        print(
            f"\n[PASS] Completeness gate: 0 recoverable nulls remain. "
            f"Orphaned (unrecoverable): {len(orphaned_after)}"
        )

        print("\n=== Repair Complete ===")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
