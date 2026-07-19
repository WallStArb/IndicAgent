"""Unit tests for scripts/ops/alpha/ops_feature_registry_override.py (todo 117).

No live DB: mocks connect_db_from_url and FeatureRegistryService.record_transition_sync.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

_scripts_alpha_dir = _project_root / "scripts" / "ops" / "alpha"
if str(_scripts_alpha_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_alpha_dir))

from ops_feature_registry_override import main  # noqa: E402


def _mock_conn_with_status(status: str | None):
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = (status,) if status is not None else None
    conn.cursor.return_value.__enter__.return_value = cur
    return conn


@pytest.fixture(autouse=True)
def _mock_settings():
    with patch("ops_feature_registry_override.Settings") as mock_settings_cls:
        mock_settings_cls.return_value.database_url = "postgresql+asyncpg://x/y"
        yield


class TestOpsFeatureRegistryOverride:
    def test_feature_not_found_returns_1(self, monkeypatch):
        conn = _mock_conn_with_status(None)
        monkeypatch.setattr("ops_feature_registry_override.connect_db_from_url", lambda dsn: conn)
        monkeypatch.setattr(
            sys,
            "argv",
            ["prog", "--feature-name", "nope", "--to-status", "deprecated", "--reason", "x"],
        )

        assert main() == 1
        conn.close.assert_called_once()

    def test_already_at_target_status_is_noop(self, monkeypatch):
        conn = _mock_conn_with_status("deprecated")
        monkeypatch.setattr("ops_feature_registry_override.connect_db_from_url", lambda dsn: conn)
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

    def test_successful_transition_calls_record_transition_sync(self, monkeypatch):
        conn = _mock_conn_with_status("active")
        monkeypatch.setattr("ops_feature_registry_override.connect_db_from_url", lambda dsn: conn)
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
        monkeypatch.setattr(
            "ops_feature_registry_override.FeatureRegistryService.record_transition_sync",
            mock_record,
        )

        assert main() == 0
        mock_record.assert_called_once()
        _, kwargs = mock_record.call_args
        assert kwargs["feature_name"] == "days_to_month_end"
        assert kwargs["from_status"] == "active"
        assert kwargs["to_status"] == "deprecated"
        assert kwargs["reason"] == "operator_override"

    def test_optimistic_lock_miss_returns_1(self, monkeypatch):
        conn = _mock_conn_with_status("active")
        monkeypatch.setattr("ops_feature_registry_override.connect_db_from_url", lambda dsn: conn)
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
            "ops_feature_registry_override.FeatureRegistryService.record_transition_sync",
            MagicMock(return_value=False),
        )

        assert main() == 1
