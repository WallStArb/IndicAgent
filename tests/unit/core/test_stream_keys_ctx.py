"""Tests for the ctx.snapshot Kafka topic stream key helper."""

from src.core.stream_keys import topic_ctx_snapshot


def test_topic_ctx_snapshot_dev():
    assert topic_ctx_snapshot("dev") == "dev.ctx.snapshot"


def test_topic_ctx_snapshot_prod():
    assert topic_ctx_snapshot("production") == "production.ctx.snapshot"


def test_topic_ctx_snapshot_uses_dots_not_colons():
    assert ":" not in topic_ctx_snapshot("dev")
