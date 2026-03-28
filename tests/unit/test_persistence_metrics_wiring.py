"""Tests verifying persistence metrics are wired in writer services."""

import pathlib


def test_feature_writer_records_batch_latency():
    src = pathlib.Path("services/feature_writer_agent.py").read_text()
    assert "persistence_batch_latency" in src.lower() or "PERSISTENCE_BATCH_LATENCY" in src
    assert "PERSISTENCE_BATCH_LATENCY" in src


def test_feature_writer_records_consumer_lag():
    src = pathlib.Path("services/feature_writer_agent.py").read_text()
    assert "PERSISTENCE_CONSUMER_LAG" in src


def test_llm_writer_records_batch_latency():
    src = pathlib.Path("services/llm_writer_service.py").read_text()
    assert "PERSISTENCE_BATCH_LATENCY" in src


def test_llm_writer_records_consumer_lag():
    src = pathlib.Path("services/llm_writer_service.py").read_text()
    assert "PERSISTENCE_CONSUMER_LAG" in src
