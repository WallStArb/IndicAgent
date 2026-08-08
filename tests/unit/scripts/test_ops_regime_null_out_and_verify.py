"""Unit tests for scripts/ops/corpus/ops_regime_null_out_and_verify.py (Phase 171 Plan 03).

No live DB: a small scripted fake connection/cursor plays back a fixed sequence of
fetchone()/rowcount responses in the exact order the implementation issues execute()
calls, mirroring tests/unit/services/test_regime_writer.py's `_make_mock_conn` mocking
style but with per-call response control (needed here because a single cell issues
multiple distinct queries in sequence, not one).
"""

from __future__ import annotations

import json

import pytest

from scripts.ops.corpus.ops_regime_null_out_and_verify import (
    _NULL_OUT_SQL,
    _STATUS_FAILED,
    _STATUS_VERIFIED_NULL,
    REGIME_WRITER_OWNED_COLUMN_NAMES,
    _manifest_key,
    _parse_args,
    _run_null_out,
)

_MODULE = "scripts.ops.corpus.ops_regime_null_out_and_verify"


# ---------------------------------------------------------------------------
# Scripted fake connection -- replays responses in call order
# ---------------------------------------------------------------------------


class _ScriptedCursor:
    def __init__(self, conn: _ScriptedConn) -> None:
        self._conn = conn
        self._response: dict = {}

    def __enter__(self) -> _ScriptedCursor:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self._conn.calls.append((sql, params))
        self._response = self._conn.pop_response()

    def fetchone(self):
        return self._response.get("fetchone")

    @property
    def rowcount(self) -> int:
        return self._response.get("rowcount", 0)


class _ScriptedConn:
    def __init__(self, responses: list[dict] | None = None) -> None:
        self.calls: list[tuple[str, tuple | None]] = []
        self.commits = 0
        self.closed = False
        self._responses = list(responses or [])
        self._idx = 0

    def cursor(self) -> _ScriptedCursor:
        return _ScriptedCursor(self)

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True

    def pop_response(self) -> dict:
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
        else:
            resp = {}
        self._idx += 1
        return resp


def _update_calls(conn: _ScriptedConn) -> list[tuple[str, tuple | None]]:
    return [c for c in conn.calls if "UPDATE feature_vectors" in c[0]]


# ---------------------------------------------------------------------------
# Task 1 -- null-out mode
# ---------------------------------------------------------------------------


class TestNullOutSetClause:
    def test_set_clause_contains_all_8_owned_columns_and_no_others(self):
        for name in REGIME_WRITER_OWNED_COLUMN_NAMES:
            assert f"{name} = NULL" in _NULL_OUT_SQL
        assert _NULL_OUT_SQL.count(" = NULL") == len(REGIME_WRITER_OWNED_COLUMN_NAMES)


class TestNullOutPerCellUpdates:
    def test_n_symbols_x_m_tfs_issue_exactly_nxm_updates_no_batched_scope(self, tmp_path):
        # 2 symbols x 2 tfs = 4 cells, each a clean pass: pre-count, update, verify.
        # First response is the once-per-run chunk-compression-state log.
        responses = [{"fetchone": (80, 83)}]
        for _ in range(4):
            responses += [
                {"fetchone": (5,)},  # pre_null_labeled
                {"rowcount": 5},  # UPDATE rowcount
                {"fetchone": (0,)},  # post-condition: zero remaining
            ]
        conn = _ScriptedConn(responses)
        manifest_path = tmp_path / "manifest.json"

        n_failed = _run_null_out(conn, ["SPY", "QQQ"], ["1h", "1d"], manifest_path, dry_run=False)

        assert n_failed == 0
        updates = _update_calls(conn)
        assert len(updates) == 4
        seen_pairs = {params for _, params in updates}
        assert seen_pairs == {("SPY", "1h"), ("SPY", "1d"), ("QQQ", "1h"), ("QQQ", "1d")}
        for sql, _ in conn.calls:
            assert "IN (" not in sql
            assert "= ANY(" not in sql


class TestNullOutRequiresSymbols:
    def test_missing_symbols_exits_nonzero(self):
        with pytest.raises(SystemExit) as excinfo:
            _parse_args(["--tf", "1h"])
        assert excinfo.value.code != 0


class TestNullOutDryRun:
    def test_dry_run_issues_zero_update_calls(self, tmp_path):
        conn = _ScriptedConn([{"fetchone": (42,)}])
        manifest_path = tmp_path / "manifest.json"

        n_failed = _run_null_out(conn, ["SPY"], ["1d"], manifest_path, dry_run=True)

        assert n_failed == 0
        assert _update_calls(conn) == []
        assert conn.commits == 0
        assert not manifest_path.exists()


class TestNullOutManifestResumability:
    def test_verified_null_cell_is_skipped_on_rerun(self, tmp_path):
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    _manifest_key("SPY", "1h"): {
                        "status": _STATUS_VERIFIED_NULL,
                        "pre_null_labeled": 5,
                        "rows_affected": 5,
                        "elapsed_s": 0.1,
                    }
                }
            )
        )
        # Only QQQ/1h should actually run: compression-state log, then pre-count, update, verify.
        conn = _ScriptedConn(
            [
                {"fetchone": (80, 83)},
                {"fetchone": (3,)},
                {"rowcount": 3},
                {"fetchone": (0,)},
            ]
        )

        n_failed = _run_null_out(conn, ["SPY", "QQQ"], ["1h"], manifest_path, dry_run=False)

        assert n_failed == 0
        assert len(conn.calls) == 4
        for sql, params in conn.calls[1:]:
            assert params == ("QQQ", "1h")


class TestNullOutFailedCellContinues:
    def test_postcondition_failure_marks_cell_failed_and_continues(self, tmp_path):
        manifest_path = tmp_path / "manifest.json"
        # Cell 1 (SPY/1h): post-condition fails (remaining_nonnull=3).
        # Cell 2 (QQQ/1h): post-condition passes.
        conn = _ScriptedConn(
            [
                {"fetchone": (80, 83)},  # once-per-run compression-state log
                {"fetchone": (5,)},
                {"rowcount": 5},
                {"fetchone": (3,)},  # FAIL
                {"fetchone": (2,)},
                {"rowcount": 2},
                {"fetchone": (0,)},  # PASS
            ]
        )

        n_failed = _run_null_out(conn, ["SPY", "QQQ"], ["1h"], manifest_path, dry_run=False)

        assert n_failed == 1
        assert len(_update_calls(conn)) == 2  # both cells attempted, run did not abort
        manifest = json.loads(manifest_path.read_text())
        assert manifest[_manifest_key("SPY", "1h")]["status"] == _STATUS_FAILED
        assert manifest[_manifest_key("QQQ", "1h")]["status"] == _STATUS_VERIFIED_NULL
