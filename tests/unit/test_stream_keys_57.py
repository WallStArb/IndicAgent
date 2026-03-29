"""Tests for Phase 57 stream key additions.

Verifies:
  - topic_intelligence_pipeline_state() returns correct topic strings
  - topic_intelligence_shadow() returns correct topic strings
"""

from src.core.stream_keys import (
    topic_intelligence_pipeline_state,
    topic_intelligence_shadow,
)


def test_topic_intelligence_pipeline_state_with_env():
    """Pipeline state topic includes env prefix."""
    assert topic_intelligence_pipeline_state("development") == "development.intelligence.pipeline.state"


def test_topic_intelligence_pipeline_state_empty_env():
    """Pipeline state topic with no env prefix."""
    assert topic_intelligence_pipeline_state("") == "intelligence.pipeline.state"


def test_topic_intelligence_shadow_with_env():
    """Shadow topic includes env prefix."""
    assert topic_intelligence_shadow("development") == "development.intelligence.shadow"


def test_topic_intelligence_shadow_empty_env():
    """Shadow topic with no env prefix."""
    assert topic_intelligence_shadow("") == "intelligence.shadow"
