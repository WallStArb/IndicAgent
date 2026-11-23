"""Integration test for the instrument registry's schema (Phase 091.1 hardening).

The pg_notify trigger was installed by migration 220. The data checks that lived here (the active
contract list is non-empty, SPY is present) asserted the content of the instruments seed, not code,
and were removed under todo 656 (docs/plans/2026-11-23-integration-harness-plan.md).

Run: pytest tests/integration/ -m integration
"""

import asyncpg
import pytest

from src.config.settings import get_settings

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_trigger_installed():
    """The trg_instruments_notify trigger is installed on the instruments table.

    This verifies migration 220 was applied. FeatureVectorPipeline checks this at
    startup (DatabaseManager.instruments_trigger_exists()) and fails loudly if missing
    rather than installing it itself (DAG Invariants 2/3 — compute never owns schema
    mutation). Query information_schema.triggers directly rather than relying on
    service state.
    """
    settings = get_settings()
    conn = await asyncpg.connect(settings.database_url)
    try:
        trigger_names = await conn.fetch(
            "SELECT trigger_name FROM information_schema.triggers "
            "WHERE event_object_table = 'instruments'"
        )
        names = {row["trigger_name"] for row in trigger_names}
        assert "trg_instruments_notify" in names, (
            f"trg_instruments_notify trigger not found. Installed triggers: {names}. "
            "Apply production/migrations/213_instruments_notify_trigger.sql."
        )
    finally:
        await conn.close()
