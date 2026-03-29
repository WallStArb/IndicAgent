import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from unittest.mock import MagicMock


def test_preflight_shows_row_counts():
    """Preflight prints table name and row count for each target table."""
    from production.scripts.pipeline_reset import build_preflight_summary

    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: s
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.fetchone.return_value = (42,)

    summary = build_preflight_summary(conn, keep_ohlcv=False, clear_llm=False)

    assert "signal_ledger" in summary
    assert "intelligence_features" in summary
    assert "market_data_ohlcv" in summary
    assert "42" in summary


def test_preflight_omits_ohlcv_when_keep_ohlcv():
    """With --keep-ohlcv, market_data_ohlcv should not appear in summary."""
    from production.scripts.pipeline_reset import build_preflight_summary

    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: s
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.fetchone.return_value = (0,)

    summary = build_preflight_summary(conn, keep_ohlcv=True, clear_llm=False)

    assert "market_data_ohlcv" not in summary


def test_preflight_includes_llm_when_flag_set():
    """With --clear-llm, llm_calls should appear in summary."""
    from production.scripts.pipeline_reset import build_preflight_summary

    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: s
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.fetchone.return_value = (7,)

    summary = build_preflight_summary(conn, keep_ohlcv=False, clear_llm=True)

    assert "llm_calls" in summary


def test_truncate_tables_always_clears_core_tables():
    """truncate_tables always clears signal_ledger and intelligence_features."""
    from production.scripts.pipeline_reset import truncate_tables

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: cur
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    truncate_tables(conn, keep_ohlcv=True, clear_llm=False)

    executed = [call.args[0] for call in cur.execute.call_args_list]
    assert any("signal_ledger" in sql for sql in executed)
    assert any("intelligence_features" in sql for sql in executed)
    assert not any("market_data_ohlcv" in sql for sql in executed)


def test_truncate_tables_includes_ohlcv_when_not_keep():
    """truncate_tables includes market_data_ohlcv when keep_ohlcv=False."""
    from production.scripts.pipeline_reset import truncate_tables

    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = (100,)  # _row_count needs a real tuple for > comparison
    conn.cursor.return_value.__enter__ = lambda s: cur
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    truncate_tables(conn, keep_ohlcv=False, clear_llm=False)

    executed = [call.args[0] for call in cur.execute.call_args_list]
    assert any("market_data_ohlcv" in sql for sql in executed)


def test_truncate_tables_includes_llm_when_flag_set():
    """truncate_tables includes llm_calls when clear_llm=True."""
    from production.scripts.pipeline_reset import truncate_tables

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: cur
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    truncate_tables(conn, keep_ohlcv=True, clear_llm=True)

    executed = [call.args[0] for call in cur.execute.call_args_list]
    assert any("llm_calls" in sql for sql in executed)


def test_verify_dataset_passes_when_rows_exist():
    """verify_dataset returns True when all tables have rows."""
    from production.scripts.pipeline_reset import verify_dataset

    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: s
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    # Returns different counts per call: signal_ledger=1000, intelligence_features=5000
    conn.cursor.return_value.fetchone.side_effect = [(1000,), (5000,), (10,)]
    conn.cursor.return_value.fetchall.return_value = [
        ("ESH6", "1m", 500, "2026-03-01", "2026-03-06"),
    ]

    ok, report = verify_dataset(conn)

    assert ok is True
    assert "ESH6" in report


def test_verify_dataset_fails_when_signal_ledger_empty():
    """verify_dataset returns False when signal_ledger has 0 rows."""
    from production.scripts.pipeline_reset import verify_dataset

    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: s
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.fetchone.side_effect = [(0,), (0,), (0,)]
    conn.cursor.return_value.fetchall.return_value = []

    ok, report = verify_dataset(conn)

    assert ok is False
    assert "EMPTY" in report or "0" in report


# ---------------------------------------------------------------------------
# drift tables + Kafka topic clearing
# ---------------------------------------------------------------------------


def test_always_clear_includes_drift_tables():
    """drift_state and drift_monitor must be in _ALWAYS_CLEAR so a full reset wipes them."""
    from production.scripts.pipeline_reset import _ALWAYS_CLEAR

    assert "drift_state" in _ALWAYS_CLEAR
    assert "drift_monitor" in _ALWAYS_CLEAR


def test_clear_kafka_topics_deletes_all_env_prefixed_topics():
    """clear_kafka_topics deletes all pipeline topics under the given env prefix."""
    from unittest.mock import AsyncMock, patch

    from production.scripts.pipeline_reset import clear_kafka_topics

    mock_client = MagicMock()
    mock_client.start = AsyncMock()
    mock_client.close = AsyncMock()
    mock_client.delete_topics = AsyncMock()
    mock_client.create_topics = AsyncMock()

    with patch("production.scripts.pipeline_reset.AIOKafkaAdminClient", return_value=mock_client):
        import asyncio
        count = asyncio.run(
            clear_kafka_topics("localhost:19092", env_prefix="development", providers=["ibkr"])
        )

    mock_client.delete_topics.assert_called_once()
    topics_deleted = mock_client.delete_topics.call_args.args[0]
    assert all(t.startswith("development.") for t in topics_deleted)
    assert count == len(topics_deleted)


def test_clear_kafka_topics_recreates_topics_after_delete():
    """After deleting, clear_kafka_topics calls create_topics to restore topic config."""
    from unittest.mock import AsyncMock, patch

    from production.scripts.pipeline_reset import clear_kafka_topics

    mock_client = MagicMock()
    mock_client.start = AsyncMock()
    mock_client.close = AsyncMock()
    mock_client.delete_topics = AsyncMock()
    mock_client.create_topics = AsyncMock()

    with patch("production.scripts.pipeline_reset.AIOKafkaAdminClient", return_value=mock_client):
        import asyncio
        asyncio.run(
            clear_kafka_topics("localhost:19092", env_prefix="development", providers=["ibkr"])
        )

    mock_client.create_topics.assert_called_once()


# ---------------------------------------------------------------------------
# Service lists (Phase 54 provider refactor)
# ---------------------------------------------------------------------------


def test_stop_services_includes_new_provider_services():
    """_STOP_SERVICES must include ibkr-provider and provider-merger (new DAG services)."""
    from production.scripts.pipeline_reset import _STOP_SERVICES

    assert "indicagent-ibkr-provider" in _STOP_SERVICES
    assert "indicagent-provider-merger" in _STOP_SERVICES


def test_stop_services_includes_bar_pipeline():
    """_STOP_SERVICES must include bar-aggregator, bar-writer, bar-auditor."""
    from production.scripts.pipeline_reset import _STOP_SERVICES

    assert "indicagent-bar-aggregator-compute" in _STOP_SERVICES
    assert "indicagent-bar-writer" in _STOP_SERVICES
    assert "indicagent-bar-auditor" in _STOP_SERVICES


def test_stop_services_excludes_old_data_provider():
    """indicagent-data-provider is retired — must NOT appear in _STOP_SERVICES."""
    from production.scripts.pipeline_reset import _STOP_SERVICES

    assert "indicagent-data-provider" not in _STOP_SERVICES


def test_start_services_includes_bar_pipeline():
    """_START_SERVICES must include bar-aggregator, bar-writer, bar-auditor after reset."""
    from production.scripts.pipeline_reset import _START_SERVICES

    assert "indicagent-bar-aggregator-compute" in _START_SERVICES
    assert "indicagent-bar-writer" in _START_SERVICES
    assert "indicagent-bar-auditor" in _START_SERVICES


def test_start_services_includes_new_provider_services():
    """_START_SERVICES must include ibkr-provider and provider-merger."""
    from production.scripts.pipeline_reset import _START_SERVICES

    assert "indicagent-ibkr-provider" in _START_SERVICES
    assert "indicagent-provider-merger" in _START_SERVICES


# ---------------------------------------------------------------------------
# kafka_init_topics — topic spec completeness
# ---------------------------------------------------------------------------


def test_kafka_init_topics_importable():
    """kafka_init_topics module must exist and export _TOPIC_SPECS."""
    from production.scripts.kafka_init_topics import _TOPIC_SPECS

    assert isinstance(_TOPIC_SPECS, list)
    assert len(_TOPIC_SPECS) > 0


def test_kafka_init_topics_spec_shape():
    """Each entry in _TOPIC_SPECS must be a (suffix, partitions, retention_ms) tuple."""
    from production.scripts.kafka_init_topics import _TOPIC_SPECS

    for entry in _TOPIC_SPECS:
        assert len(entry) == 3, f"Expected 3-tuple, got {entry}"
        suffix, partitions, retention_ms = entry
        assert isinstance(suffix, str)
        assert isinstance(partitions, int)
        assert isinstance(retention_ms, int)


def test_kafka_init_topics_includes_core_topics():
    """Core market data topics must be present in _TOPIC_SPECS."""
    from production.scripts.kafka_init_topics import _TOPIC_SPECS

    suffixes = {s for s, _, _ in _TOPIC_SPECS}
    assert "market.bars" in suffixes
    assert "market.bars.htf" in suffixes
    assert "market.ticks" in suffixes
    assert "market.events.gap_requests" in suffixes


def test_kafka_init_topics_includes_provider_raw_topic():
    """get_topic_specs must include a raw topic for each provider."""
    from production.scripts.kafka_init_topics import get_topic_specs

    specs = get_topic_specs(["ibkr"])
    suffixes = {s for s, _, _ in specs}
    assert "market.bars.raw.ibkr" in suffixes

    specs_multi = get_topic_specs(["ibkr", "polygon"])
    suffixes_multi = {s for s, _, _ in specs_multi}
    assert "market.bars.raw.ibkr" in suffixes_multi
    assert "market.bars.raw.polygon" in suffixes_multi


def test_kafka_init_topics_includes_quality_topic():
    """market.data.quality must be in _TOPIC_SPECS (Phase 54 new topic)."""
    from production.scripts.kafka_init_topics import _TOPIC_SPECS

    suffixes = {s for s, _, _ in _TOPIC_SPECS}
    assert "market.data.quality" in suffixes


def test_kafka_init_topics_all_use_dots_not_colons():
    """All topic suffixes must use dots as separators, never colons (CLAUDE.md rule)."""
    from production.scripts.kafka_init_topics import _TOPIC_SPECS

    for suffix, _, _ in _TOPIC_SPECS:
        assert ":" not in suffix, f"Colon found in topic suffix: {suffix}"
