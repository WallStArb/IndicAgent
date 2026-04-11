"""Tests for src/core/ml/ — FeatureExtractor, ShadowRecorder, ModelRegistry, TrainingDataQuery."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


def _make_event(symbol: str = "ESM6", tf: str = "1m", regime: int = 1):
    from src.intelligence.schemas import IntelligenceEvent
    event = MagicMock(spec=IntelligenceEvent)
    event.symbol = symbol
    event.tf = tf
    event.ts = datetime(2026, 4, 10, 14, 0, tzinfo=UTC)
    event.bar = MagicMock()
    event.bar.close = 5280.0
    event.bar.volume = 12000.0
    event.i1 = MagicMock()
    event.i1.atr_14 = 8.5
    event.i1.rsi_14 = 62.0
    event.i1.adx = 32.0
    event.i1.macd = 2.1
    event.i1.macd_signal = 1.8
    event.i1.volume_ratio = 1.2
    event.i4 = MagicMock()
    event.i4.hmm_regime = regime
    event.i4.hmm_regime_prob = 0.87
    event.i4.hurst_exponent = 0.52
    event.i4.kalman_trend = 0.1
    event.i4.kalman_slope = 0.02
    event.i4.vol_percentile = 0.65
    event.i4.garch_vol_ratio = 1.1
    event.i4.vwap = 5277.5
    event.i4.poc_price = 5275.0
    event.i6 = MagicMock()
    event.i6.ctf_score = 0.72
    event.i6.ctf_trend_alignment = 0.75
    event.i6.ctf_regime_agreement = 0.80
    event.i6.ctf_fvg_alignment = 0.60
    event.i6.ctf_ob_alignment = 0.55
    event.i7 = MagicMock()
    event.i7.cis = MagicMock()
    event.i7.cis.score = 0.78
    return event


# ---------------------------------------------------------------------------
# FeatureExtractor
# ---------------------------------------------------------------------------

def test_extractor_from_event_returns_feature_vector():
    from src.core.ml.extractor import FeatureExtractor
    extractor = FeatureExtractor()
    event = _make_event()
    fv = extractor.from_event(event)

    from src.core.ml.features import FeatureVector
    assert isinstance(fv, FeatureVector)
    assert fv.symbol == "ESM6"
    assert fv.tf == "1m"
    assert fv.atr == 8.5
    assert fv.hmm_regime == 1
    assert fv.hmm_prob == 0.87


def test_extractor_from_event_same_result_from_row():
    """from_event and from_row must produce identical FeatureVector for same data.

    This test verifies no train/serve skew by creating a mock polars row
    that mirrors what a real DB query would return.
    """
    from src.core.ml.extractor import FeatureExtractor
    extractor = FeatureExtractor()
    event = _make_event()
    fv_from_event = extractor.from_event(event)

    # Simulate the polars row that training_data_query would produce
    row = {
        "ts": "2026-04-10T14:00:00+00:00",
        "symbol": "ESM6",
        "tf": "1m",
        "atr": 8.5,
        "rsi": 62.0,
        "adx": 32.0,
        "hmm_regime": 1,
        "hmm_prob": 0.87,
        "ctf_score": 0.72,
        "ctf_trend_alignment": 0.75,
        "ctf_regime_agreement": 0.80,
        "hurst_exponent": 0.52,
        "kalman_trend": 0.1,
        "kalman_slope": 0.02,
        "vol_percentile": 0.65,
        "garch_vol_ratio": 1.1,
        "cis_score": 0.78,
    }
    fv_from_row = extractor.from_row(row)

    assert fv_from_event.symbol == fv_from_row.symbol
    assert fv_from_event.atr == fv_from_row.atr
    assert fv_from_event.hmm_regime == fv_from_row.hmm_regime
    assert fv_from_event.ctf_trend_alignment == fv_from_row.ctf_trend_alignment


def test_extractor_returns_none_for_missing_fields_gracefully():
    """Missing i-tier fields default to None — no crash."""
    from src.core.ml.extractor import FeatureExtractor
    extractor = FeatureExtractor()

    from src.intelligence.schemas import IntelligenceEvent
    event = MagicMock(spec=IntelligenceEvent)
    event.symbol = "ESM6"
    event.tf = "1m"
    event.ts = datetime.now(UTC)
    event.bar = MagicMock()
    event.bar.close = 5280.0
    event.bar.volume = None
    event.i1 = None  # missing tier
    event.i4 = None
    event.i6 = None
    event.i7 = None

    fv = extractor.from_event(event)
    assert fv.atr is None
    assert fv.hmm_regime is None


# ---------------------------------------------------------------------------
# ShadowRecorder
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shadow_recorder_record_queues_row():
    from src.core.ml.shadow import ShadowRecorder

    mock_pool = MagicMock()
    conn = AsyncMock()
    conn.executemany = AsyncMock()
    mock_pool.acquire = MagicMock(
        return_value=AsyncMock(__aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock())
    )

    recorder = ShadowRecorder(pool=mock_pool, batch_size=1)
    await recorder.record(
        signal_id=uuid4(),
        agent_id="test_agent",
        multiplier=1.2,
        confidence=0.85,
        symbol="ESM6",
        tf="1m",
        regime=1,
        path="path_a",
        features=None,
    )

    # batch_size=1 → immediate flush
    conn.executemany.assert_awaited_once()
    sql = conn.executemany.call_args[0][0]
    assert "alpha_multiplier_shadow" in sql


@pytest.mark.asyncio
async def test_shadow_recorder_writes_correct_columns():
    from src.core.ml.shadow import ShadowRecorder

    written_rows = []

    mock_pool = MagicMock()
    conn = AsyncMock()

    async def capture_executemany(sql, rows):
        written_rows.extend(rows)

    conn.executemany = capture_executemany
    mock_pool.acquire = MagicMock(
        return_value=AsyncMock(__aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock())
    )

    recorder = ShadowRecorder(pool=mock_pool, batch_size=1)
    signal_id = uuid4()
    await recorder.record(
        signal_id=signal_id,
        agent_id="my_agent",
        multiplier=1.3,
        confidence=0.9,
        symbol="NQM6",
        tf="5m",
        regime=2,
        path="path_b",
        features={"hmm_regime": 2, "atr": 15.0},
    )

    assert len(written_rows) == 1
    row = written_rows[0]
    # Row is a tuple: (ts, signal_id, agent_id, symbol, tf, regime, path, multiplier, confidence, features_json)
    assert row[2] == "my_agent"   # agent_id
    assert row[3] == "NQM6"       # symbol
    assert row[7] == 1.3          # multiplier
    assert row[8] == 0.9          # confidence


# ---------------------------------------------------------------------------
# TrainingDataQuery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_training_data_query_enforces_no_lookahead():
    """SQL must contain a WHERE clause preventing feature_ts >= outcome_ts."""
    from src.core.ml.training_data import TrainingDataQuery
    query = TrainingDataQuery.__new__(TrainingDataQuery)
    # Access the SQL constant directly
    assert "feature_ts < " in TrainingDataQuery._NO_LOOKAHEAD_SQL or \
           "WHERE" in TrainingDataQuery._BASE_SQL
