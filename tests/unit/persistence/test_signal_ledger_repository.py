"""Unit tests for SignalEventsRepository (formerly SignalLedgerRepository).

Updated in Phase 130 (130-02): signal_ledger_repository is now a backward-compat shim
re-exporting from signal_events_repository. Tests updated to target the new 3-table schema.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.persistence.repository.signal_events_repository import (
    WIN_OUTCOMES,
    LedgerEntry,
    SignalEventsRepository,
    SignalStatus,
)
from src.persistence.repository.signal_ledger_repository import (
    SignalEventsRepository as _ShimEventsRepo,
)
from src.persistence.repository.signal_ledger_repository import (
    SignalLedgerRepository,
)


def test_repository_exists():
    repo = SignalEventsRepository.__new__(SignalEventsRepository)
    assert repo is not None


def test_shim_alias_identity():
    """SignalLedgerRepository from shim module is the same class as SignalEventsRepository."""
    assert SignalLedgerRepository is SignalEventsRepository
    assert _ShimEventsRepo is SignalEventsRepository


def test_update_lifecycle_state_method_exists():
    assert hasattr(SignalEventsRepository, "update_lifecycle_state")


def test_update_mae_mfe_method_exists():
    assert hasattr(SignalEventsRepository, "update_mae_mfe")


def test_fetch_active_signals_method_exists():
    assert hasattr(SignalEventsRepository, "fetch_active_signals")


def test_fetch_pending_signals_method_exists():
    assert hasattr(SignalEventsRepository, "fetch_pending_signals")


def test_insert_signal_with_frames_method_exists():
    assert hasattr(SignalEventsRepository, "insert_signal_with_frames")


def test_get_active_signals_for_bootstrap_method_exists():
    assert hasattr(SignalEventsRepository, "get_active_signals_for_bootstrap")


def test_update_signal_status_method_exists():
    assert hasattr(SignalEventsRepository, "update_signal_status")


def test_update_frame_details_method_exists():
    assert hasattr(SignalEventsRepository, "update_frame_details")


def _make_ledger_entry() -> LedgerEntry:
    return LedgerEntry(
        signal_id="00000000-0000-0000-0000-000000000001",
        timestamp=datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC),
        symbol="ESM6",
        timeframe="5m",
        setup_plugin="breakout_v2",
        signal_type="long",
        direction=1,
        was_selected=True,
        entry_price=5200.0,
        stop_loss=5190.0,
        targets=[5215.0, 5225.0],
        cis_score=0.78,
        bucket_scores={"trend": 0.85},
        weights_version=4,
    )


def test_ledger_entry_compat_fields():
    """LedgerEntry backward-compat shim has required fields for legacy callers."""
    entry = _make_ledger_entry()
    assert entry.signal_id == "00000000-0000-0000-0000-000000000001"
    assert entry.symbol == "ESM6"
    assert entry.timeframe == "5m"
    assert entry.setup_plugin == "breakout_v2"
    assert entry.was_selected is True
    assert entry.status == SignalStatus.PENDING


def test_win_outcomes_non_empty():
    """WIN_OUTCOMES frozenset contains expected values."""
    assert "target_1" in WIN_OUTCOMES
    assert "target_full" in WIN_OUTCOMES


def test_insert_sql_targets_signal_events():
    """INSERT SQL in signal_events_repository targets signal_events, not signal_ledger."""
    import inspect

    from src.persistence.repository import signal_events_repository as repo_mod

    src = inspect.getsource(repo_mod)
    assert "INSERT INTO signal_events" in src
    assert "INSERT INTO trade_frames" in src
    # Must NOT reference legacy tables
    assert "INSERT INTO signal_ledger " not in src
    assert "INSERT INTO signal_outcomes" not in src


def test_update_sql_targets_signal_events():
    """UPDATE SQL in signal_events_repository targets signal_events.status, not signal_outcomes."""
    import inspect

    from src.persistence.repository import signal_events_repository as repo_mod

    src = inspect.getsource(repo_mod)
    assert "UPDATE signal_events" in src
    # No UPDATE on legacy tables
    assert "UPDATE signal_outcomes" not in src
    assert "UPDATE signal_ledger" not in src


@pytest.mark.asyncio
async def test_update_signal_status_calls_execute_command():
    """update_signal_status calls execute_command with correct SQL."""
    mock_db = MagicMock()
    mock_db.execute_command = AsyncMock()
    repo = SignalEventsRepository(mock_db)

    await repo.update_signal_status("test-uuid", "active")

    mock_db.execute_command.assert_awaited_once()
    call_args = mock_db.execute_command.call_args
    sql = call_args[0][0]
    assert "UPDATE signal_events" in sql
    assert "status" in sql
