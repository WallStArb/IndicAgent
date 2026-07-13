"""Unit tests for services/_batch_utils.py's async APR-loading helpers (todo 048).

cfg() and load_apr_dict_async() consolidate a pattern previously copy-pasted verbatim
across ensemble_trainer.py, alpha_publisher.py, and ensemble_ic_engine.py: load
alpha.* (+ each service's own infra.<name>.* keys) into a raw dict, then cast with a
small type-inferring helper.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services._batch_utils import (
    Float32ChunkAccumulator,
    cfg,
    connect_db_from_url,
    load_apr_dict_async,
)


class TestCfg:
    def test_returns_float_when_present(self) -> None:
        cfg_dict = {"alpha.ensemble.max_feature_weight": "0.20"}
        result = cfg(cfg_dict, "alpha.ensemble.max_feature_weight", 0.5)
        assert result == 0.20
        assert isinstance(result, float)

    def test_returns_float_default_when_missing(self) -> None:
        result = cfg({}, "alpha.ensemble.max_feature_weight", 0.25)
        assert result == 0.25

    def test_returns_int_when_present(self) -> None:
        cfg_dict = {"alpha.ensemble.min_passing_features": "5"}
        result = cfg(cfg_dict, "alpha.ensemble.min_passing_features", 3)
        assert result == 5
        assert isinstance(result, int)

    def test_returns_str_when_present(self) -> None:
        cfg_dict = {"alpha.ensemble.weight_version": "v2"}
        result = cfg(cfg_dict, "alpha.ensemble.weight_version", "v1")
        assert result == "v2"
        assert isinstance(result, str)

    def test_type_inferred_from_default_not_from_raw_value(self) -> None:
        """config_state values are always text; cfg() must cast via type(default),
        not assume the raw string is already the right type."""
        cfg_dict = {"infra.workers": "12"}
        result = cfg(cfg_dict, "infra.workers", 1)
        assert result == 12
        assert isinstance(result, int)


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

        await load_apr_dict_async(conn, extra_like_patterns=["infra.ensemble_ic_engine.%"])

        args, _ = conn.fetch.call_args
        sql, params = args[0], args[1:]
        assert "config_key LIKE ANY($1::text[])" in sql
        assert params == (["alpha.%", "infra.ensemble_ic_engine.%"],)

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
        with patch("services._batch_utils.psycopg2.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value = mock_conn

            result = connect_db_from_url("postgresql://fake")

            mock_connect.assert_called_once_with("postgresql://fake")
            assert result is mock_conn
            assert mock_conn.autocommit is False


class TestFloat32ChunkAccumulator:
    """todo 087: shared 'buffer rows -> float32 chunk -> vstack once' idiom behind
    ic_engine.py's per-symbol (row-by-row, threshold-flushed) and cross-sectional
    (whole-batch-per-query-chunk) OOM-mitigation fetch loops."""

    def test_finalize_with_no_rows_returns_none(self) -> None:
        acc = Float32ChunkAccumulator(flush_at=2)
        assert acc.finalize() is None

    def test_append_row_flushes_at_threshold(self) -> None:
        acc = Float32ChunkAccumulator(flush_at=2)
        acc.append_row([1.0, 2.0])
        acc.append_row([3.0, 4.0])
        acc.append_row([5.0, 6.0])

        result = acc.finalize()

        assert result.dtype == np.float32
        np.testing.assert_array_equal(result, [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])

    def test_append_row_flushes_remainder_on_finalize(self) -> None:
        acc = Float32ChunkAccumulator(flush_at=10)
        acc.append_row([1.0, 2.0])

        result = acc.finalize()

        np.testing.assert_array_equal(result, [[1.0, 2.0]])

    def test_append_chunk_appends_whole_batch_immediately(self) -> None:
        acc = Float32ChunkAccumulator()
        acc.append_chunk([[1.0, 2.0], [3.0, 4.0]])
        acc.append_chunk([[5.0, 6.0]])

        result = acc.finalize()

        assert result.dtype == np.float32
        np.testing.assert_array_equal(result, [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])

    def test_append_chunk_ignores_empty_batch(self) -> None:
        acc = Float32ChunkAccumulator()
        acc.append_chunk([])
        assert acc.finalize() is None

    def test_finalize_frees_internal_chunk_list(self) -> None:
        acc = Float32ChunkAccumulator()
        acc.append_chunk([[1.0, 2.0]])
        acc.finalize()
        assert acc._chunks == []
