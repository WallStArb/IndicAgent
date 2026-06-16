"""Canonical dict immutability test for SignalTracker._evaluate_bar.

Verifies that canonical signal dicts in _active_index are read-only after
_add_to_active_index ingestion. Specifically:
  - No direct top-level key mutations (sig["key"] = val)
  - No nested dict mutations (sig["nested"]["key"] = val)

Gate 1-G from Plan 112-03.
"""

import copy
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.signal_tracker import SignalState, SignalTracker


def _make_agent() -> SignalTracker:
    """Create a SignalTracker bypassing __init__."""
    agent = SignalTracker.__new__(SignalTracker)
    agent.logger = MagicMock()
    agent._stop_event = MagicMock()
    agent._stop_event.is_set.return_value = False

    # In-memory state
    agent._active_index: dict[tuple[str, str], list[dict]] = defaultdict(list)
    agent._active_symbols: set[str] = set()
    agent._signal_ids: set[str] = set()
    agent._signal_states: dict[str, SignalState] = {}
    agent._point_values: dict[str, float] = {}
    agent._regime_cache: dict[tuple[str, str], dict] = {}

    # Kafka producer mock
    agent._producer = AsyncMock()

    # Metrics mocks
    agent._transitions_total = MagicMock()
    agent._active_signals_gauge = MagicMock()

    # Settings
    agent.settings = MagicMock(env_name="dev")

    # APR-backed config (defaults from migration 142)
    agent._staleness_score_threshold = 0.5

    return agent


def _make_canonical(status: str = "pending") -> dict:
    """Return a canonical signal dict with nested sub-dicts to catch nested mutations."""
    ts = datetime.now(UTC) - timedelta(seconds=30)
    expires_at = datetime.now(UTC) + timedelta(minutes=5)
    return {
        "signal_id": "canon-001",
        "symbol": "ESM6",
        "timeframe": "1m",
        "timestamp": ts,
        "entry_price": 5100.0,
        "stop_loss": 5090.0,
        "status": status,
        "direction": 1,
        "targets": [5120.0, 5140.0],
        "entry_zone_low": 5095.0,
        "entry_zone_high": 5105.0,
        "market_entry_price": 0.0,
        "activated_at": None,
        "garch_sigma_at_fire": 0.015,
        "hmm_regime_at_fire": 1,
        "expires_at": expires_at,
        "is_backfill": False,
        "ttl_bars": 10,
        # Nested dict — must not be mutated
        "trailing_stop_price": {
            "trailing_stop": None,
            "highest_high": 5105.0,
            "lowest_low": 5095.0,
            "vol": 0.015,
            "vol_source": "garch_sigma",
        },
    }


def _deep_snapshot(d: dict) -> str:
    """JSON-serializable snapshot of a dict (handles datetime, list, nested dict)."""

    def _convert(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {k: _convert(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_convert(v) for v in obj]
        return obj

    return json.dumps(_convert(d), sort_keys=True)


class TestCanonicalDictImmutability:
    """Verify that _evaluate_bar does not mutate canonical dicts in _active_index."""

    @pytest.mark.asyncio
    async def test_pending_signal_canonical_unchanged_after_evaluate_bar(self):
        """Canonical dict with status=pending must be identical after _evaluate_bar."""
        agent = _make_agent()
        canonical = _make_canonical(status="pending")
        agent._add_to_active_index(canonical)
        agent._signal_ids.add("canon-001")

        # Deep snapshot before evaluation
        snapshot_before = _deep_snapshot(canonical)
        canonical_id_before = id(canonical)

        bar = {"high": 5102.0, "low": 5098.0, "close": 5100.0}
        bar_time = datetime.now(UTC)

        await agent._evaluate_bar("ESM6", "1m", bar, bar_time)

        # Deep snapshot after evaluation
        snapshot_after = _deep_snapshot(canonical)

        # 1. Object identity — same dict object
        assert id(canonical) == canonical_id_before, "canonical dict object was replaced"

        # 2. Deep equality — no mutations including nested keys
        assert snapshot_before == snapshot_after, (
            "canonical dict was mutated during _evaluate_bar:\n"
            f"BEFORE: {snapshot_before}\n"
            f"AFTER:  {snapshot_after}"
        )

    @pytest.mark.asyncio
    async def test_nested_dict_not_mutated(self):
        """Nested sub-dicts (e.g. trailing_stop_price) must not be mutated."""
        agent = _make_agent()
        canonical = _make_canonical(status="active")
        # Pre-seed an active state so chandelier path is triggered
        agent._add_to_active_index(canonical)
        sid = "canon-001"
        agent._signal_ids.add(sid)

        # Force ACTIVE status in state
        state = agent._signal_states[sid]
        state.status = "active"
        state.activated_at = datetime.now(UTC) - timedelta(minutes=2)

        # Snapshot nested dict separately
        nested_before = copy.deepcopy(canonical.get("trailing_stop_price"))
        snapshot_before = _deep_snapshot(canonical)

        bar = {"high": 5110.0, "low": 5100.0, "close": 5105.0}
        bar_time = datetime.now(UTC)

        await agent._evaluate_bar("ESM6", "1m", bar, bar_time)

        snapshot_after = _deep_snapshot(canonical)
        nested_after = canonical.get("trailing_stop_price")

        assert snapshot_before == snapshot_after, (
            "Canonical dict (including nested keys) was mutated during _evaluate_bar:\n"
            f"BEFORE: {snapshot_before}\n"
            f"AFTER:  {snapshot_after}"
        )
        # Verify nested dict specifically
        assert nested_after == nested_before, (
            f"Nested trailing_stop_price was mutated:\n"
            f"BEFORE: {nested_before}\n"
            f"AFTER:  {nested_after}"
        )

    @pytest.mark.asyncio
    async def test_market_entry_price_mutation_goes_to_state_not_canonical(self):
        """market_entry_price=5100 → after resolution, canonical still has 5100, state has 0."""
        agent = _make_agent()
        canonical = _make_canonical(status="active")
        canonical["market_entry_price"] = 5100.0

        agent._add_to_active_index(canonical)
        sid = "canon-001"
        agent._signal_ids.add(sid)
        # Force ACTIVE + market entry price in state
        state = agent._signal_states[sid]
        state.status = "active"
        state.market_entry_price = 5100.0
        state.activated_at = datetime.now(UTC) - timedelta(minutes=2)

        canonical_market_entry_before = canonical["market_entry_price"]

        # Bar that triggers stop-loss (close far below stop_loss at 5090)
        bar = {"high": 5060.0, "low": 5050.0, "close": 5055.0}
        bar_time = datetime.now(UTC)

        await agent._evaluate_bar("ESM6", "1m", bar, bar_time)

        # Canonical must be unchanged
        assert canonical["market_entry_price"] == canonical_market_entry_before, (
            f"Canonical market_entry_price was mutated from "
            f"{canonical_market_entry_before} to {canonical['market_entry_price']}"
        )

    @pytest.mark.asyncio
    async def test_status_mutation_goes_to_state_not_canonical(self):
        """status='pending' in canonical must remain 'pending' after activation."""
        agent = _make_agent()
        canonical = _make_canonical(status="pending")
        agent._add_to_active_index(canonical)
        sid = "canon-001"
        agent._signal_ids.add(sid)

        canonical_status_before = canonical["status"]

        # Bar that hits entry zone (between 5095 and 5105) → activates pending signal
        bar = {"high": 5102.0, "low": 5098.0, "close": 5100.0}
        bar_time = datetime.now(UTC)

        await agent._evaluate_bar("ESM6", "1m", bar, bar_time)

        # Canonical status must remain "pending" — state.status may have changed
        assert canonical["status"] == canonical_status_before, (
            f"Canonical status was mutated from "
            f"'{canonical_status_before}' to '{canonical['status']}'"
        )
