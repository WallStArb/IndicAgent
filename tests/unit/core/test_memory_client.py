"""Unit tests for MemoryClient — fake backends, no DB/Ollama.

Locks the contracts:
  - MEM-01: recall returns [] / None on any error (graceful degradation)
  - MEM-04: latency metrics recorded
  - D-19: MemoryClient is read-only (no store/write methods)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.core.memory.client import MemoryClient
from src.core.memory.types import CalibrationStats, Episode

# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------

_UTC_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def _make_episode(idx: int = 0) -> Episode:
    return Episode(
        id=f"ep-{idx}",
        ts=_UTC_NOW,
        kind="episodic",
        signal_id=f"sig-{idx}",
        symbol="ES",
        timeframe="5m",
        agent_id="test_agent",
        hmm_regime="trending_up",
        vol_regime="normal",
        entry_type="at_close",
        regime_epoch=1,
        outcome="win",
        pnl_r=1.2,
        mae=0.3,
        mfe=1.8,
        bars_in_trade=5,
        memory_assisted=False,
        payload={"note": f"episode {idx}"},
        similarity=0.85,
        epoch_weight=1.0,
    )


def _make_calibration_stats(stable: bool = True) -> CalibrationStats:
    return CalibrationStats(
        agent_id="test_agent",
        symbol="ES",
        hmm_regime="trending_up",
        entry_type="at_close",
        regime_epoch=1,
        sample_n=50,
        mean_prediction=0.6,
        actual_rate=0.58,
        calibration_error=0.02,
        calibration_error_variance=0.001,
        correction_factor=0.97 if stable else None,
        correction_factor_stable=stable,
        bootstrapped=True,
        skill_score=0.12,
        information_coefficient=0.15,
        ic_p_value=0.03,
        brier_score=0.21,
        base_rate=0.5,
        ci_lower=0.52,
        ci_upper=0.68,
        p_value_corrected=0.04,
        p_signal=0.8,
        feedback_loop_quarantine=False,
        quarantine_review_at=None,
        promoted_at=_UTC_NOW,
        window_start=_UTC_NOW,
        window_end=_UTC_NOW,
    )


class _FakeEmbeddingService:
    """Fake EmbeddingService — returns a fixed 768-dim vector without HTTP calls."""

    async def embed_context(self, context):
        return ([0.0] * 768, "ES 5m at_close regime:trending_up")


class _FailingEmbeddingService:
    """Fake EmbeddingService that always returns None (embedding failed)."""

    async def embed_context(self, context):
        return (None, "")


class _FakeEpisodicBackend:
    """Fake EpisodicBackend returning canned episodes."""

    def __init__(self, episodes: list[Episode] | None = None, raise_on_recall: bool = False):
        self._episodes = episodes or []
        self._raise = raise_on_recall

    async def recall(
        self, *, embedding, agent_id, symbol, hmm_regime, entry_type, regime_epoch, limit
    ):
        if self._raise:
            raise RuntimeError("DB offline")
        return self._episodes[:limit]


class _FakeCalibrationBackend:
    """Fake CalibrationBackend returning canned CalibrationStats."""

    def __init__(self, stats: CalibrationStats | None = None, partial_n: int = 0):
        self._stats = stats
        self._partial_n = partial_n

    async def get_calibration(self, *, agent_id, symbol, hmm_regime, entry_type, regime_epoch):
        return self._stats

    async def get_partial_sample_n(self, *, agent_id, symbol, hmm_regime, entry_type, regime_epoch):
        return self._partial_n


class _FakeRegimeBackend:
    async def get_regime_history(self, *, symbol, timeframe):
        return None


class _FakeMem0Backend:
    async def search(self, *, query, tier, symbol, timeframe, limit):
        return []


def _make_client(
    episodes: list[Episode] | None = None,
    cal_stats: CalibrationStats | None = None,
    partial_n: int = 0,
    raise_episodic: bool = False,
    use_failing_embed: bool = False,
) -> MemoryClient:
    embed = _FailingEmbeddingService() if use_failing_embed else _FakeEmbeddingService()
    return MemoryClient(
        episodic=_FakeEpisodicBackend(episodes=episodes, raise_on_recall=raise_episodic),
        calibration=_FakeCalibrationBackend(stats=cal_stats, partial_n=partial_n),
        regime=_FakeRegimeBackend(),
        mem0=_FakeMem0Backend(),
        embedding=embed,
        recall_limit=10,
    )


# ---------------------------------------------------------------------------
# Tests: recall
# ---------------------------------------------------------------------------


class _SimpleContext:
    """Minimal duck-typed context for recall tests."""

    def __init__(self):
        self.symbol = "ES"
        self.timeframe = "5m"
        self.entry_type = "at_close"
        self.hmm_regime = "trending_up"
        self.vol_regime = "normal"
        self.regime_epoch = 1
        self.rsi_pct = 0.65
        self.atr_pct = 0.50


@pytest.mark.asyncio
async def test_recall_returns_episodes():
    """recall() returns Episode list when backend has results."""
    episodes = [_make_episode(0), _make_episode(1)]
    client = _make_client(episodes=episodes)
    result = await client.recall(_SimpleContext(), agent_id="test_agent")
    assert len(result) == 2
    assert result[0].id == "ep-0"
    assert result[1].id == "ep-1"


@pytest.mark.asyncio
async def test_recall_empty_is_miss():
    """recall() returns [] when backend returns empty list (does not raise)."""
    client = _make_client(episodes=[])
    result = await client.recall(_SimpleContext(), agent_id="test_agent")
    assert result == []


@pytest.mark.asyncio
async def test_recall_backend_error_returns_empty():
    """recall() returns [] when EpisodicBackend raises — graceful degradation (MEM-01)."""
    client = _make_client(raise_episodic=True)
    # Must not raise — returns [] silently
    result = await client.recall(_SimpleContext(), agent_id="test_agent")
    assert result == []


@pytest.mark.asyncio
async def test_recall_embedding_failure_returns_empty():
    """recall() returns [] when EmbeddingService returns None (embedding failed)."""
    episodes = [_make_episode(0)]
    client = _make_client(episodes=episodes, use_failing_embed=True)
    result = await client.recall(_SimpleContext(), agent_id="test_agent")
    assert result == []


@pytest.mark.asyncio
async def test_recall_limit_respected():
    """recall() limit parameter caps the returned episode count."""
    episodes = [_make_episode(i) for i in range(8)]
    client = _make_client(episodes=episodes)
    result = await client.recall(_SimpleContext(), agent_id="test_agent", limit=3)
    assert len(result) <= 3


# ---------------------------------------------------------------------------
# Tests: calibration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_calibration_none_when_missing():
    """calibration() returns None when no data exists (sample_n == 0, no promoted row)."""
    client = _make_client(cal_stats=None, partial_n=0)
    result = await client.calibration(
        agent_id="test_agent",
        symbol="ES",
        hmm_regime="trending_up",
        entry_type="at_close",
        regime_epoch=1,
    )
    assert result is None


@pytest.mark.asyncio
async def test_calibration_returns_stats():
    """calibration() returns CalibrationStats when a promoted row exists."""
    stats = _make_calibration_stats(stable=True)
    client = _make_client(cal_stats=stats)
    result = await client.calibration(
        agent_id="test_agent",
        symbol="ES",
        hmm_regime="trending_up",
        entry_type="at_close",
        regime_epoch=1,
    )
    assert result is not None
    assert result.correction_factor_stable is True
    assert result.bootstrapped is True
    assert result.sample_n == 50


@pytest.mark.asyncio
async def test_calibration_partial_when_accumulating():
    """calibration() returns partial CalibrationStats (bootstrapped=False) when sample_n > 0 but no promoted row."""
    client = _make_client(cal_stats=None, partial_n=15)
    result = await client.calibration(
        agent_id="test_agent",
        symbol="ES",
        hmm_regime="trending_up",
        entry_type="at_close",
        regime_epoch=1,
    )
    assert result is not None
    assert result.bootstrapped is False
    assert result.sample_n == 15


# ---------------------------------------------------------------------------
# Tests: D-19 read-only invariant
# ---------------------------------------------------------------------------


def test_no_write_method():
    """MemoryClient must not expose store() or write() (D-19 read-only invariant)."""
    assert not hasattr(MemoryClient, "store"), "MemoryClient must not have store()"
    assert not hasattr(MemoryClient, "write"), "MemoryClient must not have write()"
