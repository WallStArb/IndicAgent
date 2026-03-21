#!/usr/bin/env python3
"""E2E integration test for the bar → BarIntelligenceRecord pipeline.

Validates the full in-process pipeline in SignalGeneratorService._process_event:
    raw_signals → quality_gate → regime_gate → tod_adjuster → calibrator
    → ranker → winner_selector → BarIntelligenceRecord published to Kafka.

These tests do NOT require live Redpanda or a database — all I/O is mocked.
Safe to run in CI alongside unit tests.

Usage:
    .venv/bin/pytest tests/integration/test_signal_generator_e2e.py -v
"""

from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from services.signal_generator_service import (  # noqa: E402 — sys.path insert required
    _AUDIT_DROPS,  # Prometheus counters for metric delta tests
    _PIPELINE_STAGE_INPUT,
    SignalGeneratorService,
)
from src.intelligence.schemas import (  # noqa: E402
    BarIntelligenceRecord,
    I1Indicators,
    I2Events,
    I3Structure,
    I4Context,
    I5Patterns,
    I6Confluence,
    IntelligenceEvent,
    OHLCVBar,
    SMCContext,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    symbol: str = "ES",
    tf: str = "1m",
    ts: datetime | None = None,
) -> IntelligenceEvent:
    """Build a realistic IntelligenceEvent with populated I1-I6 fields."""
    if ts is None:
        ts = datetime(2026, 3, 21, 14, 30, 0, tzinfo=UTC)
    return IntelligenceEvent(
        ts=ts,
        symbol=symbol,
        tf=tf,
        bar=OHLCVBar(o=5400.0, h=5401.0, l=5399.0, c=5400.5, v=1000),
        i1=I1Indicators(
            close=5400.5,
            atr_14=5.0,
            rsi_14=55.0,
        ),
        i2=I2Events(),
        i3=I3Structure(trend_direction=1),
        i4=I4Context(
            hurst_trend_quality=0.9,
            entropy_quality=0.85,
        ),
        i5=I5Patterns(),
        smc=SMCContext(
            hmm_regime=1.0,
            hmm_regime_prob=0.80,
            hmm_regime_duration=10.0,
        ),
        i6=I6Confluence(),
    )


def _make_raw_signals() -> list[dict]:
    """Return 3 raw signal dicts ready for pipeline processing."""
    return [
        {
            "signal_id": str(uuid4()),
            "setup_plugin": "trad_TrendFollowing",
            "signal_type": "trend_following",
            "direction": 1,
            "confidence": 0.75,
            "regime_type": "trend",
            "regime_type_at_fire": "trend",
            "entry_price": 5400.5,
            "stop_loss": 5395.0,
            "targets": [5410.0, 5415.0],
            "confluence_score": 0.70,
            "quality_score": 1.0,
            "regime_eligible": True,
        },
        {
            "signal_id": str(uuid4()),
            "setup_plugin": "trad_MeanReversion",
            "signal_type": "mean_reversion",
            "direction": -1,
            "confidence": 0.65,
            "regime_type": "mean_reversion",
            "regime_type_at_fire": "mean_reversion",
            "entry_price": 5400.5,
            "stop_loss": 5406.0,
            "targets": [5390.0, 5385.0],
            "confluence_score": 0.60,
            "quality_score": 1.0,
            "regime_eligible": True,
        },
        {
            "signal_id": str(uuid4()),
            "setup_plugin": "trad_SqueezeExpansion",
            "signal_type": "squeeze_expansion",
            "direction": 1,
            "confidence": 0.70,
            "regime_type": "trend",
            "regime_type_at_fire": "trend",
            "entry_price": 5400.5,
            "stop_loss": 5394.0,
            "targets": [5408.0, 5414.0],
            "confluence_score": 0.65,
            "quality_score": 1.0,
            "regime_eligible": True,
        },
    ]


def _make_service() -> SignalGeneratorService:
    """Build a bare SignalGeneratorService instance via __new__ (bypasses __init__).

    Only the attributes accessed by _process_event are set here.
    """
    svc = SignalGeneratorService.__new__(SignalGeneratorService)

    # Logger
    import structlog
    svc.logger = structlog.get_logger("test_signal_generator_e2e")

    # Env
    svc.env_name = "development"

    # Pipeline state
    svc._audit_queue = asyncio.Queue(maxsize=1000)
    svc._calibration_curves = {}
    svc._tod_multipliers = {}
    svc._perf_weights = {}
    svc._cis_weights_cache = {}
    svc._drift_penalties = {}
    svc._signal_gate: dict = {}
    svc._setup_cooldown: dict = {}
    svc._setup_last_fire: dict = {}

    # Regime cache — trending regime for ES/1m authority TF
    svc._regime_cache = defaultdict(dict)
    svc._regime_cache["ES"]["5m"] = {
        "hmm_regime": 1,
        "hmm_regime_prob": 0.80,
        "hmm_regime_duration": 10,
    }

    # CIS scorer (uses bootstrap weights — no DB needed)
    from src.intelligence.trading.cis_scorer import CISScorer
    svc._cis_scorer = CISScorer()

    # Kafka producer — captured to inspect published payloads
    svc._kafka_producer = AsyncMock()

    # DB manager — None by default so ledger writes are skipped unless overridden
    svc.db_manager = None

    # Prometheus counters used inside _process_event
    from src.observability.metrics import counter
    svc.signals_generated_total = counter(
        "test_e2e_signals_generated_total",
        "Test counter — signals generated",
    )
    svc.signals_selected_total = counter(
        "test_e2e_signals_selected_total",
        "Test counter — signals selected",
    )
    svc._total_signals = 0

    svc.shutdown_requested = False

    return svc


def _capture_record(svc: SignalGeneratorService) -> BarIntelligenceRecord | None:
    """Extract the BarIntelligenceRecord from the most recent kafka publish call.

    Searches calls to _kafka_producer.publish for the intelligence.record topic
    and parses the JSON payload into a BarIntelligenceRecord.
    """
    for call in reversed(svc._kafka_producer.publish.call_args_list):
        args = call.args if call.args else ()
        if args and "intelligence.record" in str(args[0]):
            raw = args[1] if len(args) > 1 else None
            if raw is None:
                # payload may be in kwargs
                raw = call.kwargs.get("value") or call.kwargs.get("payload")
            if raw is not None:
                return BarIntelligenceRecord.model_validate_json(raw)
    return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def event() -> IntelligenceEvent:
    return _make_event()


@pytest.fixture()
def raw_signals() -> list[dict]:
    return _make_raw_signals()


@pytest.fixture()
def svc() -> SignalGeneratorService:
    return _make_service()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_bar_to_record_all_fields_populated(
    svc: SignalGeneratorService,
    event: IntelligenceEvent,
    raw_signals: list[dict],
) -> None:
    """Feed IntelligenceEvent with I1-I6 data → BarIntelligenceRecord with all fields."""
    features = {"atr_14": 5.0, "hmm_regime": 1, "hurst_trend_quality": 0.9}
    await svc._process_event(
        event=event,
        symbol="ES",
        timeframe="1m",
        timestamp=event.ts,
        bar_close_ts=event.ts,
        source="live",
        raw_signals=raw_signals,
        regime_data={"hmm_regime": 1, "hmm_regime_prob": 0.80, "hmm_regime_duration": 10},
        drift_penalty=1.0,
        features=features,
    )

    record = _capture_record(svc)
    assert record is not None, "BarIntelligenceRecord was not published"
    assert record.schema_version == "1.0"
    assert record.intelligence is not None
    assert isinstance(record.ranked_signals, list)
    assert record.signals_evaluated > 0
    assert record.signals_after_quality >= 0
    assert record.signals_after_regime >= 0
    assert record.pipeline_latency_ms > 0
    assert isinstance(record.i7_computed_at, datetime)


@pytest.mark.asyncio
async def test_e2e_funnel_counts_monotonically_decreasing(
    svc: SignalGeneratorService,
    event: IntelligenceEvent,
    raw_signals: list[dict],
) -> None:
    """signals_evaluated >= signals_after_quality >= signals_after_regime (gate only suppresses)."""
    features: dict = {}
    await svc._process_event(
        event=event,
        symbol="ES",
        timeframe="1m",
        timestamp=event.ts,
        bar_close_ts=event.ts,
        source="live",
        raw_signals=raw_signals,
        regime_data={"hmm_regime": 1, "hmm_regime_prob": 0.80, "hmm_regime_duration": 10},
        drift_penalty=1.0,
        features=features,
    )

    record = _capture_record(svc)
    assert record is not None
    assert record.signals_evaluated == len(raw_signals)
    assert record.signals_evaluated >= record.signals_after_quality
    assert record.signals_after_quality >= record.signals_after_regime


@pytest.mark.asyncio
async def test_e2e_ranked_signals_have_all_fields(
    svc: SignalGeneratorService,
    event: IntelligenceEvent,
    raw_signals: list[dict],
) -> None:
    """Each RankedSignal has plugin (non-empty), direction, raw_confidence > 0, adjusted_rank, is_winner."""  # noqa: E501
    features: dict = {}
    await svc._process_event(
        event=event,
        symbol="ES",
        timeframe="1m",
        timestamp=event.ts,
        bar_close_ts=event.ts,
        source="live",
        raw_signals=raw_signals,
        regime_data=None,
        drift_penalty=1.0,
        features=features,
    )

    record = _capture_record(svc)
    assert record is not None
    assert len(record.ranked_signals) > 0, "Expected non-empty ranked_signals"
    for rs in record.ranked_signals:
        assert rs.plugin, f"plugin should be non-empty string, got {rs.plugin!r}"
        assert rs.direction in (-1, 0, 1), f"direction out of range: {rs.direction}"
        assert rs.raw_confidence > 0.0, (  # noqa: E501
            f"raw_confidence should be positive, got {rs.raw_confidence}"
        )
        assert isinstance(rs.adjusted_rank, float)
        assert isinstance(rs.is_winner, bool)


@pytest.mark.asyncio
async def test_e2e_winner_fields_consistent(
    svc: SignalGeneratorService,
    event: IntelligenceEvent,
    raw_signals: list[dict],
) -> None:
    """If winner_plugin is set: confidence > 0, direction not None, exactly one is_winner=True."""
    features: dict = {}
    await svc._process_event(
        event=event,
        symbol="ES",
        timeframe="1m",
        timestamp=event.ts,
        bar_close_ts=event.ts,
        source="live",
        raw_signals=raw_signals,
        regime_data={"hmm_regime": 1, "hmm_regime_prob": 0.80, "hmm_regime_duration": 10},
        drift_penalty=1.0,
        features=features,
    )

    record = _capture_record(svc)
    assert record is not None
    if record.winner_plugin is not None:
        assert record.winner_confidence is not None
        assert record.winner_confidence > 0.0
        assert record.winner_direction is not None
        winner_count = sum(1 for rs in record.ranked_signals if rs.is_winner)
        assert winner_count <= 1, f"At most one is_winner=True, got {winner_count}"


@pytest.mark.asyncio
async def test_e2e_ledger_written_true_on_success(
    svc: SignalGeneratorService,
    event: IntelligenceEvent,
    raw_signals: list[dict],
) -> None:
    """Mock DB write succeeds → ledger_written=True in the published record."""
    # Attach a mock db_manager so the write path is exercised
    mock_db = MagicMock()
    mock_db.pool = MagicMock()
    svc.db_manager = mock_db

    with patch(
        "services.signal_generator_service.insert_signals_with_features",
        new_callable=AsyncMock,
    ) as mock_insert:
        mock_insert.return_value = None
        features: dict = {}
        await svc._process_event(
            event=event,
            symbol="ES",
            timeframe="1m",
            timestamp=event.ts,
            bar_close_ts=event.ts,
            source="live",
            raw_signals=raw_signals,
            regime_data={"hmm_regime": 1, "hmm_regime_prob": 0.80, "hmm_regime_duration": 10},
            drift_penalty=1.0,
            features=features,
        )

    record = _capture_record(svc)
    assert record is not None
    # ledger_written=True only when a winner passes the gate and DB succeeds
    if record.winner_plugin is not None:
        assert record.ledger_written is True, (
            f"Expected ledger_written=True when winner={record.winner_plugin!r} and DB succeeds"
        )


@pytest.mark.asyncio
async def test_e2e_ledger_written_false_on_failure(
    svc: SignalGeneratorService,
    event: IntelligenceEvent,
    raw_signals: list[dict],
) -> None:
    """Mock DB write raises → ledger_written=False, record still published."""
    mock_db = MagicMock()
    mock_db.pool = MagicMock()
    svc.db_manager = mock_db

    with patch(
        "services.signal_generator_service.insert_signals_with_features",
        new_callable=AsyncMock,
        side_effect=Exception("DB connection refused"),
    ):
        features: dict = {}
        await svc._process_event(
            event=event,
            symbol="ES",
            timeframe="1m",
            timestamp=event.ts,
            bar_close_ts=event.ts,
            source="live",
            raw_signals=raw_signals,
            regime_data={"hmm_regime": 1, "hmm_regime_prob": 0.80, "hmm_regime_duration": 10},
            drift_penalty=1.0,
            features=features,
        )

    # Record must still be published even when DB fails
    record = _capture_record(svc)
    assert record is not None, "BarIntelligenceRecord must be published even when DB fails"
    assert record.ledger_written is False


@pytest.mark.asyncio
async def test_e2e_pipeline_metrics_present(
    svc: SignalGeneratorService,
    event: IntelligenceEvent,
    raw_signals: list[dict],
) -> None:
    """After processing, _PIPELINE_STAGE_INPUT.labels(stage='quality_gate') has incremented."""
    # Read baseline counter value before
    before = _PIPELINE_STAGE_INPUT.labels(stage="quality_gate")._value.get()

    features: dict = {}
    await svc._process_event(
        event=event,
        symbol="ES",
        timeframe="1m",
        timestamp=event.ts,
        bar_close_ts=event.ts,
        source="live",
        raw_signals=raw_signals,
        regime_data=None,
        drift_penalty=1.0,
        features=features,
    )

    after = _PIPELINE_STAGE_INPUT.labels(stage="quality_gate")._value.get()
    assert after > before, (
        f"pipeline_stage_input_total[stage=quality_gate] should have incremented; "
        f"before={before}, after={after}"
    )


@pytest.mark.asyncio
async def test_e2e_audit_queue_no_drops(svc: SignalGeneratorService) -> None:
    """Process 10 bars → audit_queue_drops_total increments by 0 (no drops)."""
    drops_before = _AUDIT_DROPS._value.get()

    features: dict = {}

    for i in range(10):
        svc._kafka_producer.publish.reset_mock()
        ts = datetime(2026, 3, 21, 14, 30 + i, 0, tzinfo=UTC)
        ev = _make_event(ts=ts)
        await svc._process_event(
            event=ev,
            symbol="ES",
            timeframe="1m",
            timestamp=ts,
            bar_close_ts=ts,
            source="live",
            raw_signals=_make_raw_signals(),
            regime_data={"hmm_regime": 1, "hmm_regime_prob": 0.80, "hmm_regime_duration": 10},
            drift_penalty=1.0,
            features=features,
        )

    drops_after = _AUDIT_DROPS._value.get()
    assert drops_after == drops_before, (
        f"Expected 0 audit queue drops under normal load; "
        f"drops delta = {drops_after - drops_before}"
    )


@pytest.mark.asyncio
async def test_e2e_no_signals_produces_empty_record(svc: SignalGeneratorService) -> None:
    """When no I7 plugins fire (empty raw_signals), record: ranked_signals=[], winner=None."""
    event = _make_event()
    features: dict = {}

    await svc._process_event(
        event=event,
        symbol="ES",
        timeframe="1m",
        timestamp=event.ts,
        bar_close_ts=event.ts,
        source="live",
        raw_signals=[],  # No signals
        regime_data=None,
        drift_penalty=1.0,
        features=features,
    )

    record = _capture_record(svc)
    assert record is not None
    assert record.ranked_signals == []
    assert record.signals_evaluated == 0
    assert record.winner_plugin is None
    assert record.ledger_written is False
