"""Integration test: market_data_ohlcv_tradeable view filters volume=0 bars correctly.

Requires a live DB (indicagent_test) -- belongs in tests/integration/, not tests/unit/.
"""

from __future__ import annotations

import asyncpg
import pytest

_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent_test"


@pytest.mark.asyncio
async def test_view_excludes_zero_volume_bars_and_includes_real_bars():
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        await conn.execute("""
            INSERT INTO market_data_ohlcv
                (timestamp, symbol, timeframe, open, high, low, close, volume, source)
            VALUES
                ('2024-01-02 09:30:00+00', 'ZZTEST', '5m', 100.0, 100.5, 99.5, 100.2, 500, 'ibkr_named'),
                ('2024-01-02 09:35:00+00', 'ZZTEST', '5m', 100.2, 100.2, 100.2, 100.2, 0, 'synthetic_fill'),
                ('2024-01-02 09:40:00+00', 'ZZTEST', '5m', 100.2, 100.2, 100.2, 100.2, 0, 'ibkr_named')
            """)
        rows = await conn.fetch(
            "SELECT timestamp, volume FROM market_data_ohlcv_tradeable "
            "WHERE symbol = 'ZZTEST' ORDER BY timestamp"
        )
        assert len(rows) == 1
        assert rows[0]["volume"] == 500
    finally:
        await conn.execute("DELETE FROM market_data_ohlcv WHERE symbol = 'ZZTEST'")
        await conn.close()
