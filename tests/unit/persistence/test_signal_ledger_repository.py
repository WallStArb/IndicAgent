"""Unit tests for SignalLedgerRepository — TDD RED phase."""

import re
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from src.persistence.repository.signal_ledger_repository import (
    _INSERT_SQL,
    LedgerEntry,
    SignalLedgerRepository,
)


def test_repository_exists():
    repo = SignalLedgerRepository.__new__(SignalLedgerRepository)
    assert repo is not None


def test_update_lifecycle_state_method_exists():
    assert hasattr(SignalLedgerRepository, "update_lifecycle_state")


def test_update_mae_mfe_method_exists():
    assert hasattr(SignalLedgerRepository, "update_mae_mfe")


def test_fetch_active_signals_method_exists():
    assert hasattr(SignalLedgerRepository, "fetch_active_signals")


def test_fetch_pending_signals_method_exists():
    assert hasattr(SignalLedgerRepository, "fetch_pending_signals")


def test_to_row_returns_correct_count():
    """_to_row() tuple length matches $N param count in _INSERT_SQL — self-maintaining."""
    entry = LedgerEntry(
        signal_id="00000000-0000-0000-0000-000000000001",
        timestamp=datetime.now(UTC),
        symbol="ES",
        timeframe="1m",
        setup_plugin="test_plugin",
        signal_type="long",
        direction=1,
        was_selected=True,
        entry_price=4500.0,
        stop_loss=4490.0,
        targets=[],
        cis_score=0.72,
        bucket_scores={"trend": 0.8},
        weights_version=3,
    )
    sql_param_count = len(re.findall(r"\$\d+", _INSERT_SQL))
    row = entry._to_row()
    assert isinstance(row, tuple)
    assert len(row) == sql_param_count


# ── New tests for Fix B (TDD RED phase) ──────────────────────────────────────
try:
    from src.persistence.repository.signal_ledger_repository import (
        _INSERT_OUTCOMES_SQL,
    )

    _OUTCOMES_SQL_AVAILABLE = True
except ImportError:
    _INSERT_OUTCOMES_SQL = ""
    _OUTCOMES_SQL_AVAILABLE = False


def _make_entry() -> LedgerEntry:
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


def test_insert_sql_contains_only_fire_time_columns():
    """_INSERT_SQL must NOT reference lifecycle columns (status, activated_at, exit_at, etc.)."""
    lifecycle_cols = {
        "status",
        "activated_at",
        "exit_at",
        "pnl_r",
        "outcome",
        "mae",
        "mfe",
        "signal_quality",
        "staleness_score",
    }
    for col in lifecycle_cols:
        assert col not in _INSERT_SQL, f"lifecycle column '{col}' must not appear in _INSERT_SQL"


def test_insert_outcomes_sql_exists_and_has_signal_id():
    """_INSERT_OUTCOMES_SQL must exist and insert into signal_outcomes with signal_id."""
    assert _OUTCOMES_SQL_AVAILABLE, "_INSERT_OUTCOMES_SQL not found in module — RED phase"
    assert "signal_outcomes" in _INSERT_OUTCOMES_SQL
    assert "signal_id" in _INSERT_OUTCOMES_SQL


def test_to_row_length_matches_insert_sql():
    """_to_row() param count must match $N placeholders in _INSERT_SQL."""
    entry = _make_entry()
    sql_param_count = len(re.findall(r"\$\d+", _INSERT_SQL))
    assert len(entry._to_row()) == sql_param_count


def test_update_methods_target_signal_outcomes():
    """All UPDATE SQL constants must reference signal_outcomes, not signal_ledger."""
    import inspect

    from src.persistence.repository import signal_ledger_repository as repo_mod

    src = inspect.getsource(repo_mod)
    updates = re.findall(r"UPDATE\s+(\w+)", src)
    bad = [t for t in updates if t == "signal_ledger"]
    assert bad == [], f"Found UPDATE signal_ledger — must be UPDATE signal_outcomes: {bad}"


@pytest.mark.asyncio
async def test_insert_writes_to_both_tables():
    """insert() must execute two INSERTs: one to signal_ledger, one to signal_outcomes."""
    repo = SignalLedgerRepository.__new__(SignalLedgerRepository)
    mock_db = MagicMock()
    calls = []

    async def fake_execute_batch(sql, params):
        calls.append(sql)

    mock_db.execute_batch = fake_execute_batch
    repo._db_manager = mock_db

    entry = _make_entry()
    await repo.insert([entry])

    assert len(calls) == 2
    assert any("signal_ledger" in c and "INSERT" in c for c in calls)
    assert any("signal_outcomes" in c for c in calls)
