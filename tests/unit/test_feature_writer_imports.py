"""Tests for feature_writer_agent import correctness — guards against stale topic imports."""

import sys


def test_feature_writer_imports_cleanly():
    sys.path.insert(0, ".")
    from services import feature_writer_agent

    assert hasattr(feature_writer_agent, "FeatureWriterAgent")


def test_feature_writer_subscribes_to_intelligence_journal():
    """feature_writer must use topic_intelligence_journal, not topic_feature_processed."""
    import pathlib

    src = pathlib.Path("services/feature_writer_agent.py").read_text()
    assert (
        "topic_feature_processed" not in src
    ), "feature_writer_agent.py must not reference the removed topic_feature_processed"
    assert (
        "topic_intelligence_journal" in src
    ), "feature_writer_agent.py must subscribe to topic_intelligence_journal"
