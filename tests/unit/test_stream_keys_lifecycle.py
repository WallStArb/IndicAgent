"""Tests for the lifecycle transitions Kafka topic key."""

from src.core.stream_keys import topic_lifecycle_transitions


def test_topic_lifecycle_transitions_development():
    assert topic_lifecycle_transitions("development") == "development.lifecycle.transitions"


def test_topic_lifecycle_transitions_production():
    assert topic_lifecycle_transitions("production") == "production.lifecycle.transitions"


def test_topic_lifecycle_transitions_empty():
    assert topic_lifecycle_transitions("") == "lifecycle.transitions"


def test_topic_lifecycle_transitions_dev():
    assert topic_lifecycle_transitions("dev") == "dev.lifecycle.transitions"
