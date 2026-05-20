"""Integration tests for the instrument registry (Phase 091.1 hardening).

Verifies:
1. get_active_contracts() returns instruments from a live DB
2. Required symbols (SPY, USDJPY, EURUSD) are present
3. The pg_notify trigger was auto-installed by ensure_instruments_trigger()

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
    """Required equity and FX symbols are present in active contracts."""
    settings = get_settings()
    symbols = {c.symbol for c in get_active_contracts(settings)}
    assert "SPY" in symbols, f"SPY not found in active contracts: {symbols}"
    assert "USDJPY" in symbols, f"USDJPY not found in active contracts: {symbols}"
    assert "EURUSD" in symbols, f"EURUSD not found in active contracts: {symbols}"


@pytest.mark.asyncio
async def test_trigger_installed():
    """The trg_instruments_notify trigger is installed on the instruments table.

    This verifies ensure_instruments_trigger() ran successfully at service startup.
    Query information_schema.triggers directly rather than relying on service state.
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
            "Run ensure_instruments_trigger() or restart the intelligence-pipeline service."
        )
    finally:
        await conn.close()
