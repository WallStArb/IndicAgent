"""Todo 543: the FetcherLock's connection must survive idle_session_timeout.

The lock is a session-level advisory lock on a connection that sits idle for the whole run.
The server's idle_session_timeout (1h) killed it on 2026-10-26, releasing the lock under a live
run and letting the timer start a second fetcher beside it."""

from __future__ import annotations

from unittest.mock import MagicMock

from scripts.infrastructure.backfill import _fetcher_lock


def test_the_lock_connection_disables_idle_session_timeout(monkeypatch):
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = (True,)
    connect = MagicMock(return_value=conn)
    monkeypatch.setattr(_fetcher_lock.psycopg, "connect", connect)
    lock = _fetcher_lock.FetcherLock("postgresql://x", holder="test:1")
    assert lock.acquire()
    options = connect.call_args.kwargs.get("options", "")
    assert "idle_session_timeout=0" in options
