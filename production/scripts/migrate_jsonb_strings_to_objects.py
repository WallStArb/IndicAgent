#!/usr/bin/env python3
"""
One-time migration: Convert jsonb string values to proper jsonb objects.

Run AFTER deploying the jsonb write fixes (feature_writer_service, signal_ledger).
This converts existing string-stored jsonb to native objects so the entire
dataset is consistent.

Safe to run multiple times — idempotent (checks jsonb_typeof before converting).
"""

from datetime import UTC, datetime
from pathlib import Path

import asyncio
import sys

sys.path.insert(0, str(Path(__file__).parents[2]))

from src.core.database_manager import DatabaseManager
from src.config.settings import Settings


async def migrate_table(db: DatabaseManager, table: str, jsonb_columns: list[str]) -> int:
    """Convert string-stored jsonb columns to proper jsonb objects.

    Returns number of rows updated.
    """
    if not jsonb_columns:
        return 0

    # Build SET clause for each column: col_name = col_name::jsonb
    # The ::jsonb cast parses the string and returns a proper jsonb object
    set_clauses = ", ".join([f"{col} = {col}::jsonb" for col in jsonb_columns])
    where_clause = " OR ".join([f"jsonb_typeof({col}) = 'string'::text" for col in jsonb_columns])

    sql = f"""
        UPDATE {table}
        SET {set_clauses}
        WHERE {where_clause}
    """

    result = await db.execute_command(sql)
    # extract number of rows from result like "UPDATE 12345"
    rows_updated = int(result.split()[-1]) if result and result.split()[-1].isdigit() else 0
    return rows_updated


async def main() -> None:
    settings = Settings()
    db = DatabaseManager(settings.database_url)
    await db.initialize()

    print("Jsonb Migration: String → Object")
    print("=" * 50)
    print(f"Started: {datetime.now(tz=UTC).isoformat()}")
    print()

    total_updated = 0

    # intelligence_features: bar, i1-i7
    print("Migrating intelligence_features...")
    cols = ["bar", "i1", "i2", "i3", "i4", "i5", "smc", "i6", "i7"]
    n = await migrate_table(db, "intelligence_features", cols)
    print(f"  Updated {n:,} rows")
    total_updated += n

    # signal_ledger: targets, supporting_factors, market_context, bucket_scores,
    #                cis_attribution, trailing_stop_price
    print("Migrating signal_ledger...")
    cols = ["targets", "supporting_factors", "market_context", "bucket_scores",
             "cis_attribution", "trailing_stop_price"]
    n = await migrate_table(db, "signal_ledger", cols)
    print(f"  Updated {n:,} rows")
    total_updated += n

    # instruments: contract_details
    print("Migrating instruments...")
    cols = ["contract_details"]
    n = await migrate_table(db, "instruments", cols)
    print(f"  Updated {n:,} rows")
    total_updated += n

    print()
    print(f"Total rows updated: {total_updated:,}")
    print(f"Finished: {datetime.now(tz=UTC).isoformat()}")

    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
