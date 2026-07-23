"""Unit tests for services/_batch_utils.py's short_lived_conn(dsn) context manager
(todo 129, 162-01 Task 1).

Worker-side sibling of ic_engine.py's Settings-based `_short_lived_conn` -- takes a
dsn string (picklable, crosses a ProcessPoolExecutor boundary) instead of a Settings
object. DB-free: connect_db_from_url is monkeypatched to return a Mock() connection,
no live database or fixtures required.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import services._batch_utils as batch_utils
from services._batch_utils import short_lived_conn


def test_short_lived_conn_closes_on_normal_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """conn.close() is called exactly once when the `with` body completes normally."""
    mock_conn = Mock()
    monkeypatch.setattr(batch_utils, "connect_db_from_url", lambda dsn: mock_conn)

    with short_lived_conn("postgresql://fake-dsn") as conn:
        assert conn is mock_conn
        mock_conn.close.assert_not_called()

    mock_conn.close.assert_called_once()


def test_short_lived_conn_closes_when_body_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """conn.close() is STILL called exactly once when the `with` body raises mid-fetch.

    This is the exact defect the 3 hand-rolled dsn call sites in ic_engine.py had
    before this extraction (todo 129): no try/finally, so any exception between
    open and the nearest explicit conn.close() call leaked a connection.
    """
    mock_conn = Mock()
    monkeypatch.setattr(batch_utils, "connect_db_from_url", lambda dsn: mock_conn)

    with pytest.raises(ValueError, match="boom"):
        with short_lived_conn("postgresql://fake-dsn") as conn:
            assert conn is mock_conn
            raise ValueError("boom")

    mock_conn.close.assert_called_once()


def test_short_lived_conn_passes_dsn_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """The dsn string is forwarded to connect_db_from_url unmodified."""
    seen_dsns = []

    def _fake_connect(dsn: str):
        seen_dsns.append(dsn)
        return Mock()

    monkeypatch.setattr(batch_utils, "connect_db_from_url", _fake_connect)

    with short_lived_conn("postgresql://example/db") as conn:
        assert conn is not None

    assert seen_dsns == ["postgresql://example/db"]
