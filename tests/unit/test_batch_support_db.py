"""Unit tests for services/batch_support/db.py (APR loading, connect, column types)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.batch_support.db import connect_db_from_url, load_apr_dict_async


class TestLoadAprDictAsync:
    @pytest.mark.asyncio
    async def test_default_pattern_is_alpha_only(self) -> None:
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])

        await load_apr_dict_async(conn)

        args, _ = conn.fetch.call_args
        sql, params = args[0], args[1:]
        assert "config_key LIKE ANY($1::text[])" in sql
        assert params == (["alpha.%"],)

    @pytest.mark.asyncio
    async def test_extra_patterns_are_bound_as_one_array_param(self) -> None:
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])

        await load_apr_dict_async(conn, extra_like_patterns=["infra.ic_measure.%"])

        args, _ = conn.fetch.call_args
        sql, params = args[0], args[1:]
        assert "config_key LIKE ANY($1::text[])" in sql
        assert params == (["alpha.%", "infra.ic_measure.%"],)

    @pytest.mark.asyncio
    async def test_returns_key_value_dict_from_fetched_rows(self) -> None:
        conn = MagicMock()
        conn.fetch = AsyncMock(
            return_value=[
                {"config_key": "alpha.ic.fdr_alpha", "config_value": "0.05"},
                {"config_key": "alpha.ensemble.weight_version", "config_value": "v1"},
            ]
        )

        result = await load_apr_dict_async(conn)

        assert result == {
            "alpha.ic.fdr_alpha": "0.05",
            "alpha.ensemble.weight_version": "v1",
        }


class TestConnectDbFromUrl:
    def test_disables_autocommit(self) -> None:
        with patch("services.batch_support.db.psycopg.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value = mock_conn

            result = connect_db_from_url("postgresql://fake")

            mock_connect.assert_called_once_with("postgresql://fake")
            assert result is mock_conn
            assert mock_conn.autocommit is False


@pytest.mark.asyncio
async def test_fetch_table_columns_reads_public_schema_names_and_types():
    from unittest.mock import AsyncMock, MagicMock

    from services.batch_support.db import _TABLE_COLUMNS_SQL, fetch_table_columns

    conn = MagicMock()
    conn.fetch = AsyncMock(
        return_value=[
            {"column_name": "symbol", "data_type": "text"},
            {"column_name": "momentum_z_fast", "data_type": "real"},
        ]
    )
    assert await fetch_table_columns(conn, "feature_vectors") == {
        "symbol": "text",
        "momentum_z_fast": "real",
    }
    conn.fetch.assert_awaited_once_with(_TABLE_COLUMNS_SQL, "feature_vectors")
    assert "table_schema = 'public'" in _TABLE_COLUMNS_SQL  # same-named internal tables excluded
