"""Tests for SignalTracker._ingest_signal backfill fast-path.

Covers:
1. test_backfill_fast_path_expired — backfill signal past TTL → TTL-expired published, NOT added to active index
2. test_backfill_carried_forward — backfill signal within TTL → added to active index normally
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from services.signal_tracker_compute_agent import SignalTracker


def _make_agent() -> SignalTracker:
    """Create a SignalTracker bypassing __init__."""
    agent = SignalTracker.__new__(SignalTracker)
    agent.logger = MagicMock()
    agent._active_index: dict = defaultdict(list)
    agent._active_symbols: set = set()
    agent._signal_ids: set = set()
    agent._signal_states: dict = {}
    agent._point_values: dict = {}
    agent._producer = MagicMock()
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
    # Default: compute expires_at from timestamp + ttl_bars * 60s (1m timeframe)
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
        "signal_schema_version": "v1",
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
    """test_backfill_fast_path_expired — TTL elapsed → TTL transition published, skip active index."""

    @pytest.mark.unit
    def test_backfill_fast_path_expired(self):
        """Backfill signal with 20 bars elapsed (> ttl_bars=10) takes fast-path."""
        agent = _make_agent()

        # 20 minutes ago → 20 bars elapsed for "1m" timeframe (> ttl_bars=10)
        signal_ts = datetime.now(UTC) - timedelta(minutes=20)
        canonical = _make_backfill_canonical("fast-path-expired-001", signal_ts, ttl_bars=10)

        mock_fastpath = MagicMock()
        with (
            patch(
                "services.signal_tracker_compute_agent.SIGNAL_TRACKER_BACKFILL_FAST_PATH_TOTAL",
                mock_fastpath,
            ),
            patch.object(
                agent, "_publish_ttl_expired_transition_sync", wraps=MagicMock()
            ) as mock_ttl,
            patch.object(agent, "_add_to_active_index", wraps=MagicMock()) as mock_add,
        ):
            agent._ingest_signal(canonical)

            # Fast-path MUST have published TTL-expired transition
            mock_ttl.assert_called_once()
            # Fast-path MUST NOT add to active index
            mock_add.assert_not_called()

        # signal_id must be tracked in dedup set
        assert "fast-path-expired-001" in agent._signal_ids

        # OTel counter: .add(1, ...) must have been called
        mock_fastpath.add.assert_called()


class TestBackfillCarriedForward:
    """test_backfill_carried_forward — TTL not elapsed → signal enters active index."""

    @pytest.mark.unit
    def test_backfill_carried_forward(self):
        """Backfill signal only 5 bars old (< ttl_bars=10) is carried forward to active index."""
        agent = _make_agent()

        # 5 minutes ago → 5 bars elapsed for "1m" timeframe (< ttl_bars=10)
        signal_ts = datetime.now(UTC) - timedelta(minutes=5)
        canonical = _make_backfill_canonical("backfill-carried-002", signal_ts, ttl_bars=10)

        mock_fastpath = MagicMock()
        with (
            patch(
                "services.signal_tracker_compute_agent.SIGNAL_TRACKER_BACKFILL_FAST_PATH_TOTAL",
                mock_fastpath,
            ),
            patch.object(
                agent, "_publish_ttl_expired_transition_sync", wraps=MagicMock()
            ) as mock_ttl,
            patch.object(agent, "_add_to_active_index", wraps=MagicMock()) as mock_add,
        ):
            agent._ingest_signal(canonical)

            # Must NOT take fast-path
            mock_ttl.assert_not_called()
            # Must enter active index
            mock_add.assert_called_once()

        # signal_id must be tracked in dedup set
        assert "backfill-carried-002" in agent._signal_ids

        # Fast-path counter must NOT have been incremented for carried-forward signal
        mock_fastpath.add.assert_not_called()
