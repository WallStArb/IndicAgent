"""Unit tests for scripts/ops/alpha/ops_concept_registry_override.py (todo 117; Phase 170
Plan 07 repoint; todo 402 moved it onto the async ConceptRegistryService.record_transition).

No live DB: mocks connect_with_codecs and ConceptRegistryService.record_transition.
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.ops.alpha.ops_concept_registry_override import main
from src.intelligence.concept_registry_service import TransitionResult

_MODULE = "scripts.ops.alpha.ops_concept_registry_override"


def _conn(*fetchval_results):
    """asyncpg-shaped connection: fetchval returns the given values in order."""
    conn = MagicMock()
    conn.fetchval = AsyncMock(side_effect=list(fetchval_results))
    conn.close = AsyncMock()
    return conn


@pytest.fixture(autouse=True)
def _mock_settings():
    with patch(f"{_MODULE}.Settings") as mock_settings_cls:
        mock_settings_cls.return_value.database_url = "postgresql+asyncpg://x/y"
        yield


def _run(monkeypatch, conn, argv, record_result=TransitionResult.APPLIED):
    monkeypatch.setattr(f"{_MODULE}.connect_with_codecs", AsyncMock(return_value=conn))
    monkeypatch.setattr(sys, "argv", ["prog", *argv])
    record = AsyncMock(return_value=record_result)
    monkeypatch.setattr(f"{_MODULE}.ConceptRegistryService.record_transition", record)
    logger = MagicMock()
    monkeypatch.setattr(f"{_MODULE}._logger", logger)
    return main(), record, logger


_DEPRECATE = ["--feature-name", "days_to_month_end", "--to-status", "deprecated", "--reason", "x"]
_PROMOTE = ["--feature-name", "some_feature", "--to-status", "active", "--reason", "x"]


def test_not_found_returns_1(monkeypatch):
    conn = _conn(None)
    code, record, _ = _run(monkeypatch, conn, _DEPRECATE)
    assert code == 1
    record.assert_not_called()
    conn.close.assert_awaited_once()


def test_already_at_target_is_noop(monkeypatch):
    code, record, _ = _run(monkeypatch, _conn("deprecated"), _DEPRECATE)
    assert code == 0
    record.assert_not_called()


def test_successful_transition_threads_arguments(monkeypatch):
    conn = _conn("active")
    code, record, _ = _run(
        monkeypatch,
        conn,
        ["--domain", "feature", *_DEPRECATE[:-1], "redundant with month_position"],
    )
    assert code == 0
    record.assert_awaited_once()
    _, kwargs = record.call_args
    assert kwargs["domain"] == "feature"
    assert kwargs["name"] == "days_to_month_end"
    assert kwargs["from_status"] == "active"
    assert kwargs["to_status"] == "deprecated"
    assert kwargs["reason"] == "operator_override"
    assert kwargs["notes"] == "redundant with month_position"
    conn.close.assert_awaited_once()


def test_default_domain_is_feature(monkeypatch):
    _, record, _ = _run(monkeypatch, _conn("active"), _DEPRECATE)
    assert record.call_args.kwargs["domain"] == "feature"


def test_optimistic_lock_miss_returns_1(monkeypatch):
    code, _, logger = _run(
        monkeypatch, _conn("active"), _DEPRECATE, record_result=TransitionResult.LOCK_MISS
    )
    assert code == 1
    assert logger.error.call_args[0][0] == "ops_concept_registry_override.optimistic_lock_miss"


@pytest.mark.parametrize("flag,expected", [([], False), (["--fdr-passed"], True)])
def test_fdr_passed_flag_threads_through(monkeypatch, flag, expected):
    _, record, _ = _run(monkeypatch, _conn("candidate"), [*_PROMOTE, *flag])
    assert record.call_args.kwargs["fdr_passed"] is expected


def test_fdr_blocked_promotion_reports_distinct_event(monkeypatch):
    """Phase 170 CR-01: an FDR-blocked promotion must be reported as such, never as a
    rerun-hinted lock miss -- a rerun cannot fix it."""
    code, _, logger = _run(
        monkeypatch, _conn("candidate"), _PROMOTE, record_result=TransitionResult.FDR_BLOCKED
    )
    assert code == 1
    logger.error.assert_called_once()
    assert logger.error.call_args[0][0] == "ops_concept_registry_override.blocked_fdr_unverified"
