"""Tests for DLQ stream keys."""

from src.core.stream_keys import (
    topic_bar_aggregator_dlq,
    topic_bar_audit_dlq,
    topic_bar_writer_dlq,
    topic_cross_asset_dlq,
    topic_feature_writer_dlq,
    topic_intelligence_pipeline_dlq,
    topic_lifecycle_writer_dlq,
    topic_llm_writer_dlq,
    topic_signal_audit_dlq,
    topic_signal_tracker_dlq,
    topic_signal_writer_dlq,
    topic_swarm_writer_dlq,
)


def test_writer_agent_dlq_topics():
    """Verify writer agent DLQ topic names follow convention."""
    assert topic_bar_writer_dlq("dev") == "dev.bar.writer.dlq"
    assert topic_feature_writer_dlq("dev") == "dev.feature.writer.dlq"
    assert topic_signal_writer_dlq("dev") == "dev.signal.writer.dlq"
    assert topic_lifecycle_writer_dlq("dev") == "dev.lifecycle.writer.dlq"
    assert topic_swarm_writer_dlq("dev") == "dev.swarm.writer.dlq"


def test_auditor_agent_dlq_topics():
    """Verify auditor agent DLQ topic names follow convention."""
    assert topic_bar_audit_dlq("dev") == "dev.bar.audit.dlq"
    assert topic_signal_audit_dlq("dev") == "dev.signal.audit.dlq"


def test_compute_agent_dlq_topics():
    """Verify compute agent DLQ topic names follow convention."""
    assert topic_intelligence_pipeline_dlq("dev") == "dev.intelligence.pipeline.dlq"
    assert topic_signal_tracker_dlq("dev") == "dev.signal.tracker.dlq"
    assert topic_cross_asset_dlq("dev") == "dev.cross.asset.dlq"


def test_llm_writer_dlq_topic():
    """Verify LLM writer DLQ topic name follows convention."""
    assert topic_llm_writer_dlq("dev") == "dev.llm.writer.dlq"


def test_dlq_topics_no_env_prefix():
    """Verify DLQ topics with empty env prefix (production)."""
    assert topic_bar_writer_dlq("") == "bar.writer.dlq"
    assert topic_feature_writer_dlq("") == "feature.writer.dlq"
    assert topic_signal_audit_dlq("") == "signal.audit.dlq"
    assert topic_intelligence_pipeline_dlq("") == "intelligence.pipeline.dlq"


def test_bar_aggregator_dlq_topic():
    """Verify bar_aggregator DLQ topic follows naming convention."""
    assert topic_bar_aggregator_dlq("dev") == "dev.bar.aggregator.dlq"
    assert topic_bar_aggregator_dlq("") == "bar.aggregator.dlq"
    assert topic_bar_aggregator_dlq("prod") == "prod.bar.aggregator.dlq"
