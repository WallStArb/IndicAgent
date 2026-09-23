"""Unit test for ops_vol_normalized_target_ab.py's active-scale resolution (todo 209).

_load_active_scales replaces this script's former flat _SCALES import with the
same per-tf active-scale resolution ic_engine.py's ICEngineConfig.from_apr() uses --
this script talks to config_state directly (no ConfigService wrapper), so the
helper is tested standalone rather than via the full production config path.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest

from scripts.ops.alpha.ops_vol_normalized_target_ab import (
    _BASELINE_SQL,
    _LATEST_VINTAGE_SQL,
    _REGIMES_SQL,
    _load_active_scales,
)
from services._batch_utils import ACTIVE_SCALES_FALLBACKS_BY_TF


@pytest.mark.asyncio
async def test_load_active_scales_falls_back_when_key_absent():
    pool = AsyncMock()
    pool.fetchval.return_value = None

    scales = await _load_active_scales(pool, "1h")

    assert scales == ACTIVE_SCALES_FALLBACKS_BY_TF["1h"]


@pytest.mark.asyncio
async def test_load_active_scales_parses_configured_json_array():
    pool = AsyncMock()
    pool.fetchval.return_value = '["mid","fast"]'

    scales = await _load_active_scales(pool, "1h")

    # canonicalize_active_scales reorders to (fast, mid, slow, extended) order --
    # the configured array's write order is never semantically meaningful.
    assert scales == ("fast", "mid")


@pytest.mark.asyncio
async def test_load_active_scales_queries_the_correct_per_tf_key():
    pool = AsyncMock()
    pool.fetchval.return_value = None

    await _load_active_scales(pool, "15m")

    args = pool.fetchval.call_args.args
    assert "alpha.ic.active_scales.15m" in args


class TestEarningsSeasonScopeExclusion:
    """Phase 176 (todo 353) scope-consumer audit: Component F's regime-conditional
    raw-vs-vol-normalized target A/B could change the production return target
    definition (see module docstring), so this script is decision-driving. Without
    this exclusion, _REGIMES_SQL would also discover earnings-season's season-
    qualified regime labels and test vol-normalization against a fundamentally
    different (calendar-conditioned, not volatility/trend-conditioned) stratification
    -- not the comparison this A/B is designed to make."""

    def test_regimes_sql_excludes_earnings_season(self) -> None:
        assert "regime_scope <> 'earnings_season'" in _REGIMES_SQL

    def test_baseline_sql_excludes_earnings_season(self) -> None:
        assert "regime_scope <> 'earnings_season'" in _BASELINE_SQL

    def test_latest_vintage_excludes_earnings_season(self) -> None:
        assert "regime_scope <> 'earnings_season'" in _LATEST_VINTAGE_SQL
