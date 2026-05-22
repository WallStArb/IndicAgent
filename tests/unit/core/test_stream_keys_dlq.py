"""Tests for DLQ stream keys."""

from src.core.stream_keys import (
    topic_bar_aggregator_dlq,
    topic_bar_writer_dlq,
    topic_feature_writer_dlq,
    topic_intelligence_pipeline_dlq,
    topic_lifecycle_writer_dlq,
    topic_llm_writer_dlq,
    topic_signal_tracker_dlq,
    topic_signal_writer_dlq,
)


def test_writer_agent_dlq_topics():
    """Verify writer agent DLQ topic names follow convention."""
    assert topic_bar_writer_dlq("dev") == "dev.bar.writer.dlq"
    assert topic_feature_writer_dlq("dev") == "dev.feature.writer.dlq"
    assert topic_signal_writer_dlq("dev") == "dev.intelligence.signal.writer.dlq"
    assert topic_lifecycle_writer_dlq("dev") == "dev.lifecycle.writer.dlq"


def test_compute_agent_dlq_topics():
    """Verify compute agent DLQ topic names follow convention."""
    assert topic_intelligence_pipeline_dlq("dev") == "dev.intelligence.pipeline.dlq"
    assert topic_signal_tracker_dlq("dev") == "dev.signal.tracker.dlq"


def test_llm_writer_dlq_topic():
    """Verify LLM writer DLQ topic name follows convention."""
    assert topic_llm_writer_dlq("dev") == "dev.llm.writer.dlq"


def test_dlq_topics_no_env_prefix():
    """Verify DLQ topics with empty env prefix (production)."""
    assert topic_bar_writer_dlq("") == "bar.writer.dlq"
    assert topic_feature_writer_dlq("") == "feature.writer.dlq"
    assert topic_intelligence_pipeline_dlq("") == "intelligence.pipeline.dlq"


def test_bar_aggregator_dlq_topic():
    """Verify bar_aggregator DLQ topic follows naming convention."""
    assert topic_bar_aggregator_dlq("dev") == "dev.bar.aggregator.dlq"
    assert topic_bar_aggregator_dlq("") == "bar.aggregator.dlq"
    assert topic_bar_aggregator_dlq("prod") == "prod.bar.aggregator.dlq"
