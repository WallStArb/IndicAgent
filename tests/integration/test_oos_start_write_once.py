"""Migration 506 against a migrated database: alpha.validation.oos_start is write-once.

Everything runs in one transaction that is rolled back, so the test database is unchanged.
"""

from __future__ import annotations

import asyncpg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent_test"
_KEY = "alpha.validation.oos_start"
_REFUSED = [
    f"UPDATE config_state SET config_value = '2026-10-01T00:00:00Z' WHERE config_key = '{_KEY}'",
    f"DELETE FROM config_state WHERE config_key = '{_KEY}'",
    "INSERT INTO config_state (config_key, config_value, version) "
    f"VALUES ('{_KEY}', '2026-10-01T00:00:00Z', 99) "
    "ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value",
]


async def test_oos_start_refuses_every_change_and_other_keys_still_update():
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        outer = conn.transaction()
        await outer.start()
        try:
            await conn.execute(
                "INSERT INTO config_state (config_key, config_value, version) "
                "VALUES ($1, '2025-12-24T05:15:00Z', 1) ON CONFLICT (config_key) DO NOTHING",
                _KEY,
            )
            for sql in _REFUSED:
                with pytest.raises(asyncpg.RaiseError, match="write-once"):
                    async with conn.transaction():
                        await conn.execute(sql)
            with pytest.raises(asyncpg.RaiseError, match="cannot be truncated"):
                async with conn.transaction():
                    await conn.execute("TRUNCATE config_state")
            await conn.execute(
                "INSERT INTO config_state (config_key, config_value, version) "
                "VALUES ('test.oos_guard.other', '1', 1)"
            )
            await conn.execute(
                "UPDATE config_state SET config_value = '2' "
                "WHERE config_key = 'test.oos_guard.other'"
            )
            with pytest.raises(asyncpg.RaiseError, match="write-once"):
                async with conn.transaction():
                    await conn.execute(
                        f"UPDATE config_state SET config_key = '{_KEY}' "
                        "WHERE config_key = 'test.oos_guard.other'"
                    )
        finally:
            await outer.rollback()
    finally:
        await conn.close()
