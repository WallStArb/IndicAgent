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
    bars_to_scale_map,
    cfg,
    connect_db_from_url,
    load_apr_dict_async,
    resolve_per_tf,
)


class TestBarsToScaleMap:
    def test_inverts_scale_to_bars(self) -> None:
        result = bars_to_scale_map({"fast": 1, "mid": 6, "slow": 12, "extended": 39})
        assert result == {1: "fast", 6: "mid", 12: "slow", 39: "extended"}

    def test_raises_on_collision(self) -> None:
        """Todo 211 part 2: this collision check was missing from two prior
        independent reimplementations of this reverse-map (ops_ic_shrinkage.py,
        ops_ic_null_calibration.py), which would silently drop a cell (last write
        wins) instead of failing loudly -- CLAUDE.md: silent wrong answers are worse
        than loud crashes."""
        with pytest.raises(ValueError, match="collides"):
            bars_to_scale_map({"fast": 5, "mid": 5})

    def test_collision_error_includes_context_label(self) -> None:
        with pytest.raises(ValueError, match="tf='1h'"):
            bars_to_scale_map({"fast": 5, "mid": 5}, context="1h")


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

    def test_bool_false_string_parses_to_false(self) -> None:
        """Regression: bool("false") is True in Python (non-empty string is truthy).
        A naive type(default)(val) cast would silently invert every falsy bool APR
        flag -- found live in alpha.ensemble.sign_symmetric (stored 'false', read as
        True) while wiring alpha.publisher.is_shadow (todo 011)."""
        cfg_dict = {"alpha.ensemble.sign_symmetric": "false"}
        result = cfg(cfg_dict, "alpha.ensemble.sign_symmetric", False)
        assert result is False

    def test_bool_true_string_parses_to_true(self) -> None:
        cfg_dict = {"alpha.publisher.is_shadow": "true"}
        result = cfg(cfg_dict, "alpha.publisher.is_shadow", True)
        assert result is True

    def test_bool_default_used_when_key_absent(self) -> None:
        assert cfg({}, "alpha.publisher.is_shadow", True) is True
        assert cfg({}, "alpha.ensemble.sign_symmetric", False) is False

    def test_bool_case_and_whitespace_insensitive(self) -> None:
        assert cfg({"k": " True "}, "k", False) is True
        assert cfg({"k": "FALSE"}, "k", True) is False

    def test_list_default_json_loads_raw_string(self) -> None:
        """Regression (todo 187): a naive type(default)(val) cast against a list default
        splits a raw JSON-array string into individual characters --
        list("[1,3,5,10]") != [1, 3, 5, 10] -- found live in
        alpha.construction.cost_hurdle_bps_round_trip, worked around locally in
        cross_sectional_spread_tracker.py before being fixed here at the shared layer."""
        cfg_dict = {"alpha.construction.cost_hurdle_bps_round_trip": "[1,3,5,10]"}
        result = cfg(cfg_dict, "alpha.construction.cost_hurdle_bps_round_trip", [1, 3, 5, 10])
        assert result == [1, 3, 5, 10]

    def test_list_default_used_when_key_absent(self) -> None:
        assert cfg({}, "alpha.construction.cost_hurdle_bps_round_trip", [1, 3, 5, 10]) == [
            1,
            3,
            5,
            10,
        ]

    def test_dict_default_json_loads_raw_string(self) -> None:
        cfg_dict = {"alpha.regime.groups": '{"equity": true}'}
        result = cfg(cfg_dict, "alpha.regime.groups", {})
        assert result == {"equity": True}

    def test_dict_default_passthrough_when_already_parsed(self) -> None:
        """ConfigService's json.loads() may already have parsed the value before it
        reaches cfg() in some call paths -- must not double-decode a dict that's no
        longer a raw string."""
        cfg_dict = {"alpha.regime.groups": {"equity": True}}
        result = cfg(cfg_dict, "alpha.regime.groups", {})
        assert result == {"equity": True}


class TestResolvePerTf:
    """Relocated from services/ensemble_trainer.py (todo 009 Part D Item 4) -- direct
    test at the new canonical home, in addition to the coverage that already runs
    through ensemble_trainer.py's re-exported _resolve_per_tf alias
    (test_ensemble_trainer.py)."""

    def test_uses_global_default_when_no_per_tf_override(self) -> None:
        assert resolve_per_tf({}, "alpha.ensemble.min_passing_features", "1h", 5) == 5

    def test_uses_per_tf_override_when_present(self) -> None:
        cfg_dict = {"alpha.ensemble.min_passing_features.1h": "3"}
        assert resolve_per_tf(cfg_dict, "alpha.ensemble.min_passing_features", "1h", 5) == 3

    def test_per_tf_override_scoped_to_its_own_tf(self) -> None:
        cfg_dict = {"alpha.ensemble.min_passing_features.1h": "3"}
        assert resolve_per_tf(cfg_dict, "alpha.ensemble.min_passing_features", "15m", 5) == 5


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
