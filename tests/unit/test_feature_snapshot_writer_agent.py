"""Tests for FeatureSnapshotWriterAgent — shadow writer for parity validation."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock


def test_feature_snapshot_writer_agent_class_exists():
    """Agent must exist and inherit BaseAgent."""
    from services.feature_snapshot_writer_agent import FeatureSnapshotWriterAgent
    from src.core.agent.base import BaseAgent

    agent = FeatureSnapshotWriterAgent.__new__(FeatureSnapshotWriterAgent)
    assert isinstance(agent, BaseAgent)


def test_uses_snapshot_writer_consumer_group():
    """Consumer group must differ from primary feature_writer_group."""
    import pathlib

    src = pathlib.Path("services/feature_snapshot_writer_agent.py").read_text()
    assert "feature_snapshot_writer_group" in src


def test_subscribes_to_intelligence_journal():
    """Must subscribe to intelligence.journal, never topic_feature_processed."""
    import pathlib

    src = pathlib.Path("services/feature_snapshot_writer_agent.py").read_text()
    assert "topic_intelligence_journal" in src
    assert "topic_feature_processed" not in src


def test_consumer_group_constant():
    """CONSUMER_GROUP module constant must be the distinct snapshot group."""
    from services.feature_snapshot_writer_agent import CONSUMER_GROUP

    assert CONSUMER_GROUP == "feature_snapshot_writer_group"
    # Sanity: different from primary writer
    from services.feature_writer_agent import CONSUMER_GROUP as PRIMARY_GROUP

    assert CONSUMER_GROUP != PRIMARY_GROUP


def test_shadow_table_constant():
    """SHADOW_TABLE must reference the shadow table, not the primary."""
    from services.feature_snapshot_writer_agent import SHADOW_TABLE

    assert SHADOW_TABLE == "feature_snapshots_shadow"


def test_parse_valid_bar_intelligence_record():
    """_parse_record() must deserialize a valid BarIntelligenceRecord JSON."""
    from services.feature_snapshot_writer_agent import FeatureSnapshotWriterAgent
    from src.intelligence.schemas import (
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

    agent = FeatureSnapshotWriterAgent.__new__(FeatureSnapshotWriterAgent)
    # Manually set attributes used by _parse_record (bypassing __init__)
    agent.logger = MagicMock()
    agent._parse_errors = MagicMock()
    agent._parse_errors.inc = MagicMock()

    event = IntelligenceEvent(
        ts=datetime(2026, 3, 26, 10, 0, tzinfo=UTC),
        symbol="ES",
        tf="1m",
        source="live",
        bar=OHLCVBar(o=5100, h=5110, l=5095, c=5105, v=1000),
        i1=I1Indicators(),
        i2=I2Events(),
        i3=I3Structure(),
        i4=I4Context(),
        i5=I5Patterns(),
        smc=SMCContext(),
        i6=I6Confluence(),
    )
    record = BarIntelligenceRecord(
        intelligence=event,
        ranked_signals=[],
        winner_plugin=None,
        winner_confidence=None,
        winner_direction=None,
        signals_evaluated=0,
        signals_after_quality=0,
        signals_after_regime=0,
        signals_after_tod=0,
        signals_after_calibration=0,
        ledger_written=False,
        session_type="rth",
        i7_computed_at=datetime(2026, 3, 26, 10, 0, tzinfo=UTC),
        pipeline_latency_ms=12.5,
    )
    raw = record.model_dump_json()
    result = agent._parse_record(raw)
    assert result is not None
    assert result.intelligence.symbol == "ES"


def test_parse_invalid_json_returns_none():
    """_parse_record() must return None and increment parse error counter on bad JSON."""
    from services.feature_snapshot_writer_agent import FeatureSnapshotWriterAgent

    agent = FeatureSnapshotWriterAgent.__new__(FeatureSnapshotWriterAgent)
    agent.logger = MagicMock()
    agent._parse_errors = MagicMock()
    agent._parse_errors.inc = MagicMock()

    result = agent._parse_record(b"not_json")
    assert result is None
    agent._parse_errors.inc.assert_called_once()
