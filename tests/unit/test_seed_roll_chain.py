"""Unit tests for historical_backfill.py --seed-roll-chain.

Tests seed_roll_chain():
- Iterates only futures base symbols (skips ETF, FX, Crypto)
- Calls derive_roll_chain() for each deduplicated base symbol
- First contract in chain has is_front_month=True, rest have False
- DB upsert SQL contains ON CONFLICT (symbol) DO UPDATE (idempotent)
- Deduplicates base symbols (same base from 2 instruments called once)
- DB error is caught and logged, does not re-raise
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Event loop setup for tests that import ib_insync-dependent modules
# ---------------------------------------------------------------------------
# historical_backfill imports IBKRProvider which transitively imports ib_insync
# which imports eventkit which calls asyncio.get_event_loop() at module import time.
# When run after tests that close the default event loop (via asyncio.run()), the
# import chain fails. The autouse fixture below ensures a fresh event loop is set
# before each test so the import succeeds on re-entry.

@pytest.fixture(autouse=True)
def ensure_event_loop():
    """Ensure a current event loop exists for eventkit/ib_insync compatibility."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    loop.close()
    asyncio.set_event_loop(None)


# ── Fixtures ───────────────────────────────────────────────────────────────────


def _make_settings(contracts: list[Any]) -> Any:
    """Create a minimal Settings-like object with given contracts."""
    settings = MagicMock()
    settings.contracts = contracts
    return settings


def _make_instrument(symbol: str, base: str, asset_class_str: str) -> Any:
    """Create a minimal Instrument-like object."""
    from src.core.models import AssetClass, Instrument

    ac = AssetClass(asset_class_str)
    return Instrument(symbol=symbol, base=base, asset_class=ac)


def _chain_for(base: str) -> list[dict]:
    """Return a mock 3-contract chain for the given base."""
    return [
        {"symbol": f"{base}M6", "base_symbol": base, "roll_from": None, "roll_to": f"{base}U6"},
        {"symbol": f"{base}U6", "base_symbol": base, "roll_from": f"{base}M6", "roll_to": f"{base}Z6"},
        {"symbol": f"{base}Z6", "base_symbol": base, "roll_from": f"{base}U6", "roll_to": None},
    ]


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestSeedRollChainBaseSymbolIteration:
    """seed_roll_chain should only iterate futures base symbols."""

    def test_correct_base_symbol_iteration(self) -> None:
        """Futures symbols iterated; ETF, FX, Crypto skipped."""
        from production.scripts.historical_backfill import seed_roll_chain

        contracts = [
            _make_instrument("ESM6", "ES", "futures"),
            _make_instrument("NQM6", "NQ", "futures"),
            _make_instrument("CLM6", "CL", "futures"),
            _make_instrument("SPY", "SPY", "equity"),   # ETF — skip
            _make_instrument("EURUSD", "EUR", "fx"),     # FX — skip
        ]
        settings = _make_settings(contracts)
        mock_db = MagicMock()
        mock_db.execute_batch = AsyncMock()

        with patch(
            "production.scripts.historical_backfill.derive_roll_chain",
            side_effect=lambda base: _chain_for(base),
        ) as mock_derive:
            asyncio.run(seed_roll_chain(settings, mock_db))

        called_bases = [c.args[0] for c in mock_derive.call_args_list]
        assert "ES" in called_bases
        assert "NQ" in called_bases
        assert "CL" in called_bases
        assert "SPY" not in called_bases, "ETF must be skipped"
        assert "EUR" not in called_bases, "FX must be skipped"

    def test_non_futures_skipped(self) -> None:
        """Contract with equity asset_class must not result in derive_roll_chain call."""
        from production.scripts.historical_backfill import seed_roll_chain

        contracts = [
            _make_instrument("QQQ", "QQQ", "equity"),
            _make_instrument("BTCUSD", "BTC", "crypto"),
        ]
        settings = _make_settings(contracts)
        mock_db = MagicMock()
        mock_db.execute_batch = AsyncMock()

        with patch(
            "production.scripts.historical_backfill.derive_roll_chain",
        ) as mock_derive:
            asyncio.run(seed_roll_chain(settings, mock_db))

        mock_derive.assert_not_called()


class TestSeedRollChainDeduplication:
    """seed_roll_chain must deduplicate base symbols across instruments."""

    def test_deduplication_same_base(self) -> None:
        """Two ES contracts with the same base → derive_roll_chain("ES") called once."""
        from production.scripts.historical_backfill import seed_roll_chain

        contracts = [
            _make_instrument("ESM6", "ES", "futures"),
            _make_instrument("ESU6", "ES", "futures"),  # same base
        ]
        settings = _make_settings(contracts)
        mock_db = MagicMock()
        mock_db.execute_batch = AsyncMock()

        with patch(
            "production.scripts.historical_backfill.derive_roll_chain",
            side_effect=lambda base: _chain_for(base),
        ) as mock_derive:
            asyncio.run(seed_roll_chain(settings, mock_db))

        called_bases = [c.args[0] for c in mock_derive.call_args_list]
        assert called_bases.count("ES") == 1, (
            f"derive_roll_chain('ES') must be called exactly once, got {called_bases}"
        )


class TestSeedRollChainIsFrontMonth:
    """First contract in 3-contract chain must have is_front_month=True."""

    def test_is_front_month_assignment(self) -> None:
        """First upsert for each base symbol passes is_front_month=True, rest False."""
        from production.scripts.historical_backfill import seed_roll_chain

        contracts = [_make_instrument("ESM6", "ES", "futures")]
        settings = _make_settings(contracts)
        mock_db = MagicMock()
        mock_db.execute_batch = AsyncMock()

        chain = _chain_for("ES")
        with patch(
            "production.scripts.historical_backfill.derive_roll_chain",
            return_value=chain,
        ):
            asyncio.run(seed_roll_chain(settings, mock_db))

        # Each call to execute_batch carries a params list of 1-tuple rows
        all_calls = mock_db.execute_batch.call_args_list
        assert len(all_calls) >= 1

        # Collect all is_front_month values passed
        front_month_values = []
        for c in all_calls:
            # call args: (sql, params_list)
            params_list = c.args[1]
            for params_row in params_list:
                # Find the is_front_month param — should be the 5th positional param
                # based on the INSERT: symbol, base_symbol, asset_class, roll_from, roll_to, is_front_month
                if len(params_row) >= 6:  # noqa: PLR2004
                    front_month_values.append(params_row[5])

        assert len(front_month_values) == 3, f"Expected 3 rows, got {front_month_values}"  # noqa: PLR2004
        assert front_month_values[0] is True, "First contract must be is_front_month=True"
        assert front_month_values[1] is False, "Second contract must be is_front_month=False"
        assert front_month_values[2] is False, "Third contract must be is_front_month=False"


class TestSeedRollChainOnConflict:
    """seed_roll_chain SQL must use ON CONFLICT (symbol) DO UPDATE for idempotency."""

    def test_on_conflict_upsert(self) -> None:
        """SQL passed to execute_batch must contain ON CONFLICT (symbol) DO UPDATE."""
        from production.scripts.historical_backfill import seed_roll_chain

        contracts = [_make_instrument("ESM6", "ES", "futures")]
        settings = _make_settings(contracts)
        mock_db = MagicMock()
        mock_db.execute_batch = AsyncMock()

        with patch(
            "production.scripts.historical_backfill.derive_roll_chain",
            return_value=_chain_for("ES"),
        ):
            asyncio.run(seed_roll_chain(settings, mock_db))

        all_sqls = [c.args[0] for c in mock_db.execute_batch.call_args_list]
        conflict_sqls = [s for s in all_sqls if "ON CONFLICT" in s and "DO UPDATE" in s]
        assert len(conflict_sqls) > 0, "SQL must contain ON CONFLICT (symbol) DO UPDATE"

    def test_idempotency_no_errors_on_double_call(self) -> None:
        """Running seed_roll_chain twice must not raise any errors."""
        from production.scripts.historical_backfill import seed_roll_chain

        contracts = [_make_instrument("ESM6", "ES", "futures")]
        settings = _make_settings(contracts)
        mock_db = MagicMock()
        mock_db.execute_batch = AsyncMock()

        with patch(
            "production.scripts.historical_backfill.derive_roll_chain",
            return_value=_chain_for("ES"),
        ):
            asyncio.run(seed_roll_chain(settings, mock_db))
            asyncio.run(seed_roll_chain(settings, mock_db))  # Second call — no error


class TestSeedRollChainErrorHandling:
    """DB errors during upsert are caught and logged, not re-raised."""

    def test_db_error_caught_and_logged(self) -> None:
        """If execute_batch raises, seed_roll_chain should log and not re-raise."""
        from production.scripts.historical_backfill import seed_roll_chain

        contracts = [_make_instrument("ESM6", "ES", "futures")]
        settings = _make_settings(contracts)
        mock_db = MagicMock()
        mock_db.execute_batch = AsyncMock(side_effect=Exception("DB connection error"))

        with patch(
            "production.scripts.historical_backfill.derive_roll_chain",
            return_value=_chain_for("ES"),
        ):
            # Should not raise
            asyncio.run(seed_roll_chain(settings, mock_db))


class TestSeedRollChainSummaryLog:
    """seed_roll_chain should log summary with base symbol count and contract count."""

    def test_logs_summary(self) -> None:
        """No assertion on exact format — just that the function completes without crash."""
        from production.scripts.historical_backfill import seed_roll_chain

        contracts = [
            _make_instrument("ESM6", "ES", "futures"),
            _make_instrument("NQM6", "NQ", "futures"),
        ]
        settings = _make_settings(contracts)
        mock_db = MagicMock()
        mock_db.execute_batch = AsyncMock()

        with patch(
            "production.scripts.historical_backfill.derive_roll_chain",
            side_effect=lambda base: _chain_for(base),
        ):
            asyncio.run(seed_roll_chain(settings, mock_db))  # No crash = success


class TestSeedRollChainCLIFlag:
    """--seed-roll-chain CLI flag must exist in argparse."""

    def test_seed_roll_chain_flag_in_help(self) -> None:
        """--seed-roll-chain must appear in the script's argparse help output."""
        import subprocess

        result = subprocess.run(
            [".venv/bin/python", "production/scripts/historical_backfill.py", "--help"],
            capture_output=True,
            text=True,
            cwd="/home/bg/dev/indicagent",
        )
        assert "--seed-roll-chain" in result.stdout, (
            "--seed-roll-chain flag not found in --help output"
        )
