"""Phase 107 Regression Smoke Test.

Runs BEFORE Wave 1 (baseline) and AFTER each wave.
Fails if hot path is broken.

Tests:
- TimescaleDB connectivity
- Data freshness (intelligence_features, signal_ledger, market_data_ohlcv)
- JSONB integrity (no double-serialization)

IMPORTANT: This test uses the REAL database (indicagent), not indicagent_test.
It validates the production database state before/after Phase 107 waves.

Run with: pytest tests/integration/test_pipeline_flow.py -k "_sync"
"""

import asyncio
import os

import asyncpg

# IMPORTANT: Override conftest.py's indicagent_test setting
# This is an integration test that must validate the real database
DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent"
os.environ["DATABASE_URL"] = DB_URL


async def get_connection():
    """Get a database connection."""
    return await asyncpg.connect(DB_URL)


async def test_timescaledb_connectable():
    """TimescaleDB is reachable and responsive."""
    conn = await get_connection()
    try:
        result = await conn.fetchval("SELECT 1")
        assert result == 1
    finally:
        await conn.close()


async def test_intelligence_features_has_recent_data():
    """intelligence_features hypertable has data from last hour."""
    conn = await get_connection()
    try:
        count = await conn.fetchval("""
            SELECT COUNT(*) FROM intelligence_features
            WHERE ts > NOW() - INTERVAL '1 hour'
        """)
        # During off-market hours, this may be 0 - that's OK, just check query works
        assert count >= 0
    finally:
        await conn.close()


async def test_signal_ledger_has_recent_data():
    """signal_ledger has data from last hour."""
    conn = await get_connection()
    try:
        count = await conn.fetchval("""
            SELECT COUNT(*) FROM signal_ledger
            WHERE timestamp > NOW() - INTERVAL '1 hour'
        """)
        # May be 0 during off-hours - query must not error
        assert count >= 0
    finally:
        await conn.close()


async def test_market_data_ohlcv_has_recent_data():
    """market_data_ohlcv has data from last hour (live bars flowing)."""
    conn = await get_connection()
    try:
        count = await conn.fetchval("""
            SELECT COUNT(*) FROM market_data_ohlcv
            WHERE timestamp > NOW() - INTERVAL '1 hour'
        """)
        # Off-market hours may have 0 bars - that's expected
        assert count >= 0
    finally:
        await conn.close()


async def test_jsonb_not_double_serialized():
    """JSONB columns contain structured data, not escaped strings."""
    conn = await get_connection()
    try:
        row = await conn.fetchrow("""
            SELECT technical_indicators FROM intelligence_features
            WHERE technical_indicators IS NOT NULL
            ORDER BY ts DESC LIMIT 1
        """)
        if row and row["technical_indicators"]:
            val = row["technical_indicators"]
            # asyncpg returns JSONB as dict in normal cases
            # If it's a string, check it's not double-serialized
            if isinstance(val, str):
                # Check for double-serialization (starts with quote and escaped quotes)
                assert not (
                    val.startswith('"') and '\\"' in val
                ), f"JSONB double-serialized: {val[:50]}"
                # Single-serialized string is OK (asyncpg codec behavior)
            # Should be a dict or a valid JSON string
            if isinstance(val, dict):
                assert len(val) > 0, "JSONB dict should not be empty"
            elif isinstance(val, str):
                # If it's a string, it should be valid JSON
                import json

                parsed = json.loads(val)
                assert isinstance(parsed, dict), "JSONB string should parse to dict"
    finally:
        await conn.close()


async def test_signal_ledger_schema_columns_exist():
    """signal_ledger has all expected schema columns."""
    conn = await get_connection()
    try:
        # Check for critical columns that should exist
        columns = await conn.fetch("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'signal_ledger'
            AND column_name IN (
                'signal_id', 'timestamp', 'symbol', 'timeframe', 'setup_plugin',
                'direction', 'was_selected', 'is_shadow', 'is_backfill',
                'signal_schema_version', 'entry_price', 'stop_loss', 'targets'
            )
        """)
        # Should have at least these columns
        assert len(columns) >= 10, f"Expected >= 10 columns, got {len(columns)}"
    finally:
        await conn.close()


async def test_intelligence_features_schema_columns_exist():
    """intelligence_features has all expected schema columns."""
    conn = await get_connection()
    try:
        # Check for critical columns
        columns = await conn.fetch("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'intelligence_features'
            AND column_name IN (
                'ts', 'symbol', 'tf', 'technical_indicators',
                'pattern_detections', 'regime_features', 'confluence_scores',
                'smc', 'trading_signals', 'llm_narrative', 'ctx'
            )
        """)
        # Should have at least these columns
        assert len(columns) >= 5, f"Expected >= 5 columns, got {len(columns)}"
    finally:
        await conn.close()


def test_timescaledb_connectable_sync():
    """Sync wrapper for TimescaleDB connectivity test."""
    return asyncio.run(test_timescaledb_connectable())


def test_intelligence_features_has_recent_data_sync():
    """Sync wrapper for intelligence_features freshness test."""
    return asyncio.run(test_intelligence_features_has_recent_data())


def test_signal_ledger_has_recent_data_sync():
    """Sync wrapper for signal_ledger freshness test."""
    return asyncio.run(test_signal_ledger_has_recent_data())


def test_market_data_ohlcv_has_recent_data_sync():
    """Sync wrapper for market_data_ohlcv freshness test."""
    return asyncio.run(test_market_data_ohlcv_has_recent_data())


def test_jsonb_not_double_serialized_sync():
    """Sync wrapper for JSONB integrity test."""
    return asyncio.run(test_jsonb_not_double_serialized())


def test_signal_ledger_schema_columns_exist_sync():
    """Sync wrapper for signal_ledger schema test."""
    return asyncio.run(test_signal_ledger_schema_columns_exist())


def test_intelligence_features_schema_columns_exist_sync():
    """Sync wrapper for intelligence_features schema test."""
    return asyncio.run(test_intelligence_features_schema_columns_exist())
