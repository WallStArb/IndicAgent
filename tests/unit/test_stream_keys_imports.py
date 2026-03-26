"""Tests for stream_keys topic presence — guards against stale/missing topic functions."""


def test_topic_feature_processed_does_not_exist():
    import src.core.stream_keys as sk

    assert not hasattr(sk, "topic_feature_processed")


def test_topic_intelligence_journal_exists():
    from src.core.stream_keys import topic_intelligence_journal

    assert topic_intelligence_journal("development") == "development.intelligence.journal"


def test_topic_audit_exists():
    from src.core.stream_keys import topic_audit

    assert topic_audit("development") == "development.audit"
