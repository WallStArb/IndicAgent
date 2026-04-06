"""Tests for Phase 61 stream key additions — signal DLQ and audit topics."""
from src.core.stream_keys import topic_signal_dlq, topic_signal_audit


def test_topic_signal_dlq_no_env():
    assert topic_signal_dlq("") == "intelligence.signal.dlq"


def test_topic_signal_dlq_with_env():
    assert topic_signal_dlq("dev") == "dev.intelligence.signal.dlq"


def test_topic_signal_audit_no_env():
    assert topic_signal_audit("") == "intelligence.signal.audit"


def test_topic_signal_audit_with_env():
    assert topic_signal_audit("dev") == "dev.intelligence.signal.audit"
