"""Unit tests for scripts/ops/alpha/ops_concept_registry_override.py (todo 117;
Phase 170 Plan 07 repoint + rename from this script's predecessor).

No live DB: mocks connect_db_from_url and ConceptRegistryService.record_transition_sync.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from scripts.ops.alpha.ops_concept_registry_override import main

_MODULE = "scripts.ops.alpha.ops_concept_registry_override"


def _mock_conn_with_status(status: str | None):
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = (status,) if status is not None else None
    conn.cursor.return_value.__enter__.return_value = cur
    return conn


@pytest.fixture(autouse=True)
def _mock_settings():
    with patch(f"{_MODULE}.Settings") as mock_settings_cls:
        mock_settings_cls.return_value.database_url = "postgresql+asyncpg://x/y"
        yield


class TestOpsConceptRegistryOverride:
    def test_feature_not_found_returns_1(self, monkeypatch):
        conn = _mock_conn_with_status(None)
        monkeypatch.setattr(f"{_MODULE}.connect_db_from_url", lambda dsn: conn)
        monkeypatch.setattr(
            sys,
            "argv",
            ["prog", "--feature-name", "nope", "--to-status", "deprecated", "--reason", "x"],
        )

        assert main() == 1
        conn.close.assert_called_once()
        conn.commit.assert_not_called()

    def test_already_at_target_status_is_noop(self, monkeypatch):
        conn = _mock_conn_with_status("deprecated")
        monkeypatch.setattr(f"{_MODULE}.connect_db_from_url", lambda dsn: conn)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "prog",
                "--feature-name",
                "days_to_month_end",
                "--to-status",
                "deprecated",
                "--reason",
                "x",
            ],
        )

        assert main() == 0
        conn.commit.assert_not_called()

    def test_default_domain_is_feature(self, monkeypatch):
        """--domain defaults to 'feature' when not passed (the actuator sits on a
        cross-domain registry; the CLI must never silently assume a domain)."""
        conn = _mock_conn_with_status("active")
        monkeypatch.setattr(f"{_MODULE}.connect_db_from_url", lambda dsn: conn)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "prog",
                "--feature-name",
                "days_to_month_end",
                "--to-status",
                "deprecated",
                "--reason",
                "redundant with month_position",
            ],
        )
        mock_record = MagicMock(return_value=True)
        monkeypatch.setattr(f"{_MODULE}.ConceptRegistryService.record_transition_sync", mock_record)

        assert main() == 0
        _, kwargs = mock_record.call_args
        assert kwargs["domain"] == "feature"

    def test_successful_transition_calls_record_transition_sync(self, monkeypatch):
        conn = _mock_conn_with_status("active")
        monkeypatch.setattr(f"{_MODULE}.connect_db_from_url", lambda dsn: conn)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "prog",
                "--domain",
                "feature",
                "--feature-name",
                "days_to_month_end",
                "--to-status",
                "deprecated",
                "--reason",
                "redundant with month_position",
            ],
        )
        mock_record = MagicMock(return_value=True)
        monkeypatch.setattr(f"{_MODULE}.ConceptRegistryService.record_transition_sync", mock_record)

        assert main() == 0
        mock_record.assert_called_once()
        _, kwargs = mock_record.call_args
        assert kwargs["domain"] == "feature"
        assert kwargs["name"] == "days_to_month_end"
        assert kwargs["from_status"] == "active"
        assert kwargs["to_status"] == "deprecated"
        assert kwargs["reason"] == "operator_override"
        assert kwargs["notes"] == "redundant with month_position"
        # Phase 170 Plan 07 fix: the status-check SELECT above already opened the
        # connection's implicit transaction, so record_transition_sync's own
        # conn.transaction() runs as a nested savepoint and never commits the
        # connection by itself -- main() must commit explicitly on success, or the
        # transition silently never lands (found live dry-running this script).
        conn.commit.assert_called_once()

    def test_optimistic_lock_miss_returns_1(self, monkeypatch):
        conn = _mock_conn_with_status("active")
        monkeypatch.setattr(f"{_MODULE}.connect_db_from_url", lambda dsn: conn)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "prog",
                "--feature-name",
                "days_to_month_end",
                "--to-status",
                "deprecated",
                "--reason",
                "x",
            ],
        )
        monkeypatch.setattr(
            f"{_MODULE}.ConceptRegistryService.record_transition_sync",
            MagicMock(return_value=False),
        )

        assert main() == 1
        conn.commit.assert_not_called()
