"""Unit tests for SignalLedgerRepository — TDD RED phase."""

import re
from datetime import UTC, datetime

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
        entry_price=4500.0,
        stop_loss=4490.0,
        targets=[],
        confidence=0.75,
        confluence_score=0.7,
        regime_context="trending",
        supporting_factors=[],
        was_selected=True,
        num_signals_bar=1,
        num_agreeing=1,
        num_conflicting=0,
        resolution_method="in_process",
        composite_rank=1,
    )
    sql_param_count = len(re.findall(r"\$\d+", _INSERT_SQL))
    assert isinstance(entry._to_row(), tuple)
    assert len(entry._to_row()) == sql_param_count
