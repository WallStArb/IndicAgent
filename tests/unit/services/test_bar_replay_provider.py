"""Tests for BarReplayProviderAgent (Phase 81 plan 07 task 4).

Tests: test_bar_replay_topic_routing, test_bar_replay_ordering, test_bar_replay_checkpoint_resume.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.bar_replay_provider_agent import BarReplayProviderAgent
from src.core.stream_keys import topic_market_bars, topic_market_bars_htf


def _make_agent() -> BarReplayProviderAgent:
    agent = BarReplayProviderAgent.__new__(BarReplayProviderAgent)
    agent._log = MagicMock()
    agent._settings = MagicMock()
    agent._settings.env_name = "test"
    agent._producer = AsyncMock()
    agent._pool = AsyncMock()
    agent._stop = asyncio.Event()
    agent._last_replayed_ts = None
    agent._rate_bps = 10.0
    return agent


def _row(timeframe: str) -> dict:
    return {
        "symbol": "ESM6",
        "timeframe": timeframe,
        "timestamp": datetime(2026, 1, 2, 10, 0, 0, tzinfo=UTC),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 1000.0,
    }


@pytest.mark.asyncio
async def test_bar_replay_topic_routing() -> None:
    """1m bars → topic_market_bars; HTF bars → topic_market_bars_htf."""
    agent = _make_agent()
    env = agent._settings.env_name  # "test"

    await agent._publish_bar(_row("1m"))
    first_call_topic = agent._producer.publish.call_args_list[-1][0][0]
    assert first_call_topic == topic_market_bars(
        env
    ), f"1m bar must publish to topic_market_bars({env!r}), got {first_call_topic!r}"

    await agent._publish_bar(_row("15m"))
    second_call_topic = agent._producer.publish.call_args_list[-1][0][0]
    assert second_call_topic == topic_market_bars_htf(
        env
    ), f"15m bar must publish to topic_market_bars_htf({env!r}), got {second_call_topic!r}"

    assert first_call_topic != second_call_topic


def test_bar_replay_ordering() -> None:
    """_fetch_batch SQL must ORDER BY timestamp ASC then CASE timeframe END ASC with correct mappings."""
    src = inspect.getsource(BarReplayProviderAgent._fetch_batch)

    assert re.search(
        r"ORDER\s+BY\s+timestamp\s+ASC", src, re.IGNORECASE
    ), "_fetch_batch must ORDER BY timestamp ASC"

    tf_mappings = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "1h": 60,
        "4h": 240,
        "1d": 1440,
    }
    for tf, expected_val in tf_mappings.items():
        pattern = rf"'{tf}'\s+THEN\s+{expected_val}"
        assert re.search(pattern, src), f"_fetch_batch CASE clause must map '{tf}' → {expected_val}"

    assert re.search(
        r"CASE\s+timeframe", src, re.IGNORECASE
    ), "_fetch_batch must have CASE timeframe clause for secondary ordering"


def test_bar_replay_checkpoint_resume(tmp_path, monkeypatch) -> None:
    """_save_checkpoint persists; _load_checkpoint reloads on new instance."""
    ckpt_file = tmp_path / "ckpt.json"
    monkeypatch.setattr("services.bar_replay_provider_agent.CHECKPOINT_PATH", ckpt_file)

    agent = _make_agent()

    assert agent._load_checkpoint() is None, "No checkpoint file → returns None"

    ts = datetime(2026, 3, 15, 12, 30, 0, tzinfo=UTC)
    agent._save_checkpoint(ts)

    assert ckpt_file.exists(), "_save_checkpoint must create the file"
    data = json.loads(ckpt_file.read_text())
    assert data["last_replayed_ts"] == ts.isoformat(), "File must contain ISO timestamp"

    agent2 = _make_agent()
    reloaded = agent2._load_checkpoint()
    assert reloaded is not None, "_load_checkpoint must return datetime after save"
    assert reloaded == ts, f"Reloaded ts {reloaded!r} must equal saved ts {ts!r}"
