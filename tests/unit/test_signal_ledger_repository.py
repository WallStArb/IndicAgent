"""Unit tests for SignalLedgerRepository — TDD RED phase."""

import pytest
from src.persistence.repository.signal_ledger_repository import SignalLedgerRepository


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
