"""Integration tests for the instrument registry (Phase 091.1 hardening).

Verifies:
1. get_active_contracts() returns instruments from a live DB
2. Required equity symbols (SPY) are present
3. The pg_notify trigger was installed by migration 220

Run: pytest tests/integration/ -m integration
"""

import asyncpg
import pytest

from src.config.settings import get_active_contracts, get_settings

pytestmark = pytest.mark.integration


def test_get_active_contracts_returns_nonzero():
    """get_active_contracts() returns at least one instrument from the live DB."""
    settings = get_settings()
    result = get_active_contracts(settings)
    assert (
        len(result) > 0
    ), "No active contracts returned — DB unreachable or instruments table empty"


def test_all_required_symbols_present():
    """Required equity symbols are present in active contracts.

    FX pairs (EURUSD/GBPUSD/USDCHF/USDJPY) are intentionally is_active=false in
    production - FX is not currently traded - so they are not asserted here.
    """
    settings = get_settings()
    symbols = {c.symbol for c in get_active_contracts(settings)}
    assert "SPY" in symbols, f"SPY not found in active contracts: {symbols}"


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
            "Apply production/migrations/220_instruments_notify_trigger.sql."
        )
    finally:
        await conn.close()
