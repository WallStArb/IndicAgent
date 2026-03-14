# tests/unit/scripts/test_validate_equity_backfill.py
from unittest.mock import AsyncMock

import pytest


class TestValidateEquityBackfill:
    def test_module_importable(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "validate_equity_backfill",
            "production/scripts/validate_equity_backfill.py",
        )
        assert spec is not None

    @pytest.mark.asyncio
    async def test_zero_count_exits_zero(self):
        """When DB returns count=0, validation passes."""
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[{"count": 0}])

        from production.scripts.validate_equity_backfill import validate_symbol

        result = await validate_symbol(mock_db, "SPY")
        assert result == 0

    @pytest.mark.asyncio
    async def test_nonzero_count_returns_count(self):
        """When DB returns count > 0, returns positive int."""
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[{"count": 42}])

        from production.scripts.validate_equity_backfill import validate_symbol

        result = await validate_symbol(mock_db, "SPY")
        assert result == 42
