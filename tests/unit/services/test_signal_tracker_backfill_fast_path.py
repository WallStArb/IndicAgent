"""Tests for SignalTracker._ingest_signal backfill fast-path.

Covers:
1. test_backfill_routed_to_replay — backfill signal past TTL → dedup-only (no EXIT), counter incremented (1-H)
2. test_backfill_fast_path_non_backfill_expired — non-backfill past TTL → TTL-expired published (existing path)
3. test_backfill_fast_path_publish_failure — non-backfill publish failure → signal_id NOT deduped (allows retry)
4. test_backfill_carried_forward — backfill signal within TTL → added to active index normally
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.signal_tracker import SignalTracker


def _make_agent() -> SignalTracker:
    """Create a SignalTracker bypassing __init__."""
    agent = SignalTracker.__new__(SignalTracker)
    agent.logger = MagicMock()
    agent._active_index: dict = defaultdict(list)
    agent._active_symbols: set = set()
    agent._signal_ids: set = set()
    agent._signal_states: dict = {}
    agent._point_values: dict = {}
    agent._regime_cache: dict = {}
    agent._producer = AsyncMock()
    agent._transitions_total = MagicMock()
    agent._active_signals_gauge = MagicMock()
    agent.settings = MagicMock(env_name="test")
    return agent


def _make_backfill_canonical(
    signal_id: str, timestamp: datetime, ttl_bars: int = 10, *, expires_at=None
) -> dict:
    """Build a canonical backfill signal dict.

    expires_at should be provided for correct D-17 TTL evaluation.
    If not provided, the signal will be skipped by the NULL-guard (no fast-path taken).
    """
    if expires_at is None:
        expires_at = timestamp + timedelta(seconds=ttl_bars * 60)
    return {
        "signal_id": signal_id,
        "symbol": "ES",
        "timeframe": "1m",
        "timestamp": timestamp,
        "entry_price": 5000.0,
        "stop_loss": 4990.0,
        "is_backfill": True,
        "ttl_bars": ttl_bars,
        "expires_at": expires_at,
        "status": "pending",
        "direction": 1,
        "targets": [5015.0],
        "entry_zone_low": 4998.0,
        "entry_zone_high": 5002.0,
        "market_entry_price": None,
        "activated_at": None,
        "garch_sigma_at_fire": None,
        "hmm_regime_at_fire": None,
    }


class TestBackfillFastPathExpired:
    """Backfill signals with elapsed TTL → routed to dedup-only (1-H / D-09)."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_backfill_routed_to_replay(self):
        """Backfill signal with elapsed TTL routes to dedup-only — no EXIT published.

        SignalReplayAuditor owns evaluation for these signals. Publishing a false EXIT
        here would contaminate the ledger (1-H fix).
        """
        agent = _make_agent()

        signal_ts = datetime.now(UTC) - timedelta(minutes=20)
        canonical = _make_backfill_canonical("fast-path-expired-001", signal_ts, ttl_bars=10)

        mock_replay_counter = MagicMock()
        with (
            patch(
                "services.signal_tracker.SIGNAL_TRACKER_BACKFILL_ROUTED_TO_REPLAY_TOTAL",
                mock_replay_counter,
            ),
            patch.object(
                agent, "_publish_ttl_expired_transition", new_callable=AsyncMock, return_value=True
            ) as mock_ttl,
            patch.object(agent, "_add_to_active_index", wraps=MagicMock()) as mock_add,
        ):
            await agent._ingest_signal(canonical)

            # No EXIT published for backfill signals
            mock_ttl.assert_not_called()
            # Not added to active index
            mock_add.assert_not_called()
            # Counter incremented
            mock_replay_counter.add.assert_called_once()

        # Signal is deduped so re-ingestion is a no-op
        assert "fast-path-expired-001" in agent._signal_ids

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_non_backfill_fast_path_still_publishes_exit(self):
        """Non-backfill signals with elapsed TTL still publish TTL-expired EXIT (existing path)."""
        agent = _make_agent()

        signal_ts = datetime.now(UTC) - timedelta(minutes=20)
        # is_backfill=False: uses original fast path
        canonical = _make_backfill_canonical("fast-path-non-backfill-004", signal_ts, ttl_bars=10)
        canonical["is_backfill"] = False

        mock_fastpath = MagicMock()
        with (
            patch(
                "services.signal_tracker.SIGNAL_TRACKER_BACKFILL_FAST_PATH_TOTAL",
                mock_fastpath,
            ),
            patch.object(
                agent, "_publish_ttl_expired_transition", new_callable=AsyncMock, return_value=True
            ) as mock_ttl,
            patch.object(agent, "_add_to_active_index", wraps=MagicMock()) as mock_add,
        ):
            await agent._ingest_signal(canonical)

            mock_ttl.assert_called_once()
            mock_add.assert_not_called()

        assert "fast-path-non-backfill-004" in agent._signal_ids
        mock_fastpath.add.assert_called()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_backfill_fast_path_publish_failure_does_not_dedup(self):
        """If non-backfill publish fails, signal_id must NOT be deduped so retry is possible."""
        agent = _make_agent()

        signal_ts = datetime.now(UTC) - timedelta(minutes=20)
        canonical = _make_backfill_canonical("fast-path-fail-003", signal_ts, ttl_bars=10)
        # is_backfill=False uses old path where publish failure matters
        canonical["is_backfill"] = False

        with patch.object(
            agent, "_publish_ttl_expired_transition", new_callable=AsyncMock, return_value=False
        ):
            await agent._ingest_signal(canonical)

        assert "fast-path-fail-003" not in agent._signal_ids


class TestBackfillCarriedForward:
    """TTL not elapsed → signal enters active index."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_backfill_carried_forward(self):
        """Backfill signal only 5 bars old (< ttl_bars=10) is carried forward to active index."""
        agent = _make_agent()

        signal_ts = datetime.now(UTC) - timedelta(minutes=5)
        canonical = _make_backfill_canonical("backfill-carried-002", signal_ts, ttl_bars=10)

        mock_fastpath = MagicMock()
        with (
            patch(
                "services.signal_tracker.SIGNAL_TRACKER_BACKFILL_FAST_PATH_TOTAL",
                mock_fastpath,
            ),
            patch.object(
                agent, "_publish_ttl_expired_transition", new_callable=AsyncMock, return_value=True
            ) as mock_ttl,
            patch.object(agent, "_add_to_active_index", wraps=MagicMock()) as mock_add,
        ):
            await agent._ingest_signal(canonical)

            mock_ttl.assert_not_called()
            mock_add.assert_called_once()

        assert "backfill-carried-002" in agent._signal_ids
        mock_fastpath.add.assert_not_called()


class TestBootstrapTTLFastPath:
    """Bootstrap loads signals from DB; signals with elapsed TTL must be fast-pathed,
    not loaded into the active index."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_expired_non_backfill_publishes_ttl_and_skips_index(self):
        """Non-backfill signal with elapsed TTL at bootstrap: TTL transition published,
        signal NOT added to active index."""
        agent = _make_agent()

        signal_ts = datetime.now(UTC) - timedelta(minutes=20)
        canonical = _make_backfill_canonical("bootstrap-expired-live-001", signal_ts, ttl_bars=10)
        canonical["is_backfill"] = False

        with (
            patch.object(
                agent, "_publish_ttl_expired_transition", new_callable=AsyncMock, return_value=True
            ) as mock_ttl,
            patch.object(agent, "_add_to_active_index") as mock_add,
        ):
            await agent._bootstrap_apply_signal(canonical)

            mock_ttl.assert_called_once()
            mock_add.assert_not_called()
        assert "bootstrap-expired-live-001" in agent._signal_ids

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_expired_backfill_dedup_only_skips_index(self):
        """Backfill signal with elapsed TTL at bootstrap: dedup-only, no EXIT published,
        NOT added to active index."""
        agent = _make_agent()

        signal_ts = datetime.now(UTC) - timedelta(minutes=20)
        canonical = _make_backfill_canonical(
            "bootstrap-expired-backfill-001", signal_ts, ttl_bars=10
        )

        with (
            patch.object(
                agent, "_publish_ttl_expired_transition", new_callable=AsyncMock
            ) as mock_ttl,
            patch.object(agent, "_add_to_active_index") as mock_add,
        ):
            await agent._bootstrap_apply_signal(canonical)

            mock_ttl.assert_not_called()
            mock_add.assert_not_called()
        assert "bootstrap-expired-backfill-001" in agent._signal_ids

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_valid_signal_enters_active_index(self):
        """Signal with future expires_at enters active index normally."""
        agent = _make_agent()

        signal_ts = datetime.now(UTC) - timedelta(minutes=2)
        canonical = _make_backfill_canonical("bootstrap-valid-001", signal_ts, ttl_bars=10)
        canonical["is_backfill"] = False
        canonical["expires_at"] = datetime.now(UTC) + timedelta(minutes=8)

        with (
            patch.object(
                agent, "_publish_ttl_expired_transition", new_callable=AsyncMock
            ) as mock_ttl,
            patch.object(agent, "_add_to_active_index") as mock_add,
        ):
            await agent._bootstrap_apply_signal(canonical)

            mock_ttl.assert_not_called()
            mock_add.assert_called_once_with(canonical)
