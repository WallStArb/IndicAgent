"""Unit tests for infrastructure_nightly_backfill's candidate-selection and
collision-guard logic — the only two non-trivial pure-ish pieces; gap accounting itself
stays in infrastructure_run_historical_pipeline.py and isn't re-tested here."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts.infrastructure.backfill.infrastructure_nightly_backfill import (
    _is_another_backfill_running,
    _select_next_batch,
)


class TestIsAnotherBackfillRunning:
    def test_true_when_pgrep_finds_a_pid(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="123456\n")
            assert _is_another_backfill_running() is True

    def test_false_when_pgrep_finds_nothing(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="")
            assert _is_another_backfill_running() is False


class _FakeCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows
        self.executed_sql: str | None = None
        self.executed_params: tuple | None = None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple) -> None:
        self.executed_sql = sql
        self.executed_params = params

    def fetchall(self) -> list[tuple]:
        return self._rows


class TestSelectNextBatch:
    def test_returns_symbols_in_query_order(self):
        cursor = _FakeCursor([("ZZZ", 0), ("AAA", 100)])
        conn = MagicMock()
        conn.cursor.return_value = cursor

        result = _select_next_batch(conn, batch_size=20, completeness_threshold=150_000)

        assert result == ["ZZZ", "AAA"]

    def test_passes_ranking_tf_threshold_and_limit_as_params(self):
        cursor = _FakeCursor([])
        conn = MagicMock()
        conn.cursor.return_value = cursor

        _select_next_batch(conn, batch_size=7, completeness_threshold=42)

        assert cursor.executed_params == ("1h", 42, 7)

    def test_empty_result_when_nothing_below_threshold(self):
        cursor = _FakeCursor([])
        conn = MagicMock()
        conn.cursor.return_value = cursor

        result = _select_next_batch(conn, batch_size=20, completeness_threshold=150_000)

        assert result == []
