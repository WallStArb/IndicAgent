"""Migrate instruments from settings.py defaults to the instruments DB table.

Run: python production/scripts/migrate_instruments.py

Idempotent: safe to re-run. ON CONFLICT (symbol) DO UPDATE means subsequent runs
produce 0 inserts (all rows already exist) and only update timestamps.

Purpose:
    Capture the legacy Settings.contracts list into the instruments table before
    Settings.contracts is removed in Plan 091-04. After this migration, the DB
    is the authoritative source of truth for all instrument configuration.

Legacy cleanup:
    The old upsert_instruments() used c.base as the DB primary key, which caused
    FX pairs sharing base='USD' to collide (USDJPY and USDCHF both have base=USD).
    This script deletes the legacy base-keyed rows (EUR, GBP, USD) before upserting
    the correct symbol-keyed rows (EURUSD, GBPUSD, USDJPY, USDCHF).

Safety guard:
    After all upserts, the script queries COUNT(*) FROM instruments WHERE is_active=true.
    If the count is 0, it prints a FATAL message and exits with code 1.
"""

import asyncio
import json

# Add project root to path so src.config.settings can be imported
import os
import sys

import asyncpg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.config.settings import Settings  # noqa: E402


async def main() -> None:
    settings = Settings()
    contracts = settings.contracts

    if not contracts:
        print("ERROR: settings.contracts is empty - nothing to migrate.")
        sys.exit(1)

    print(f"Connecting to {settings.database_url} ...")
    conn = await asyncpg.connect(settings.database_url)

    try:
        # ------------------------------------------------------------------
        # Step 1: Remove legacy base-keyed FX rows.
        # The old upsert_instruments() used c.base as symbol PK. For FX pairs
        # EURUSD (base=EUR), GBPUSD (base=GBP), USDJPY (base=USD), USDCHF (base=USD)
        # this stored rows as symbol=EUR, symbol=GBP, symbol=USD. The collision
        # meant USDJPY was never stored.
        #
        # Delete any row whose symbol is a bare base currency code (EUR, GBP, USD)
        # and whose contract_details->>'symbol' is a full FX pair (EURUSD etc).
        # This is a targeted delete that only removes the wrongly-keyed FX rows.
        # ------------------------------------------------------------------
        deleted = await conn.fetchval("""
            WITH deleted AS (
                DELETE FROM instruments
                WHERE symbol IN ('EUR', 'GBP', 'USD')
                  AND contract_details->>'asset_class' = 'fx'
                RETURNING symbol
            )
            SELECT COUNT(*) FROM deleted
            """)
        if deleted and deleted > 0:
            print(f"Cleaned up {deleted} legacy base-keyed FX row(s) (EUR/GBP/USD).")
        else:
            print("No legacy base-keyed FX rows found (already clean).")

        # ------------------------------------------------------------------
        # Step 2: Upsert all instruments using c.symbol as the primary key.
        # ON CONFLICT (symbol) DO UPDATE ensures idempotency.
        # ------------------------------------------------------------------
        inserted_count = 0
        updated_count = 0

        for c in contracts:
            # Use c.model_dump() for the contract_details JSONB column.
            # asyncpg accepts dict directly - do NOT json.dumps().
            cd = c.model_dump()

            result = await conn.fetchrow(
                """
                INSERT INTO instruments (symbol, base, contract_details, is_active, updated_at)
                VALUES ($1, $2, $3::jsonb, $4, NOW())
                ON CONFLICT (symbol) DO UPDATE
                    SET contract_details = EXCLUDED.contract_details,
                        is_active        = EXCLUDED.is_active,
                        updated_at       = NOW()
                RETURNING (xmax = 0) AS inserted
                """,
                c.symbol,
                c.base,
                json.dumps(cd),
                True,
            )

            if result and result["inserted"]:
                inserted_count += 1
            else:
                updated_count += 1

        # ------------------------------------------------------------------
        # Step 3: Safety guard - abort if migration produced zero active rows.
        # ------------------------------------------------------------------
        active_count = await conn.fetchval(
            "SELECT COUNT(*) FROM instruments WHERE is_active = true"
        )

        if active_count == 0:
            print("FATAL: migration produced zero active instruments - aborting.")
            sys.exit(1)

        # ------------------------------------------------------------------
        # Step 4: Verify USDJPY is present.
        # ------------------------------------------------------------------
        usdjpy_present = await conn.fetchval(
            "SELECT COUNT(*) FROM instruments WHERE symbol = 'USDJPY'"
        )

        fx_symbols = await conn.fetch(
            "SELECT symbol FROM instruments WHERE contract_details->>'asset_class' = 'fx' ORDER BY symbol"
        )
        fx_symbol_list = [r["symbol"] for r in fx_symbols]

        print("\nMigration complete:")
        print(f"  Processed : {len(contracts)}")
        print(f"  Inserted  : {inserted_count}")
        print(f"  Updated   : {updated_count}")
        print(f"  Active    : {active_count}")
        print(f"  USDJPY    : {'PRESENT' if usdjpy_present else 'MISSING - check FX rows'}")
        print(f"  FX symbols: {fx_symbol_list}")

        if not usdjpy_present:
            print("\nWARNING: USDJPY is missing from instruments table.")
            sys.exit(1)

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
