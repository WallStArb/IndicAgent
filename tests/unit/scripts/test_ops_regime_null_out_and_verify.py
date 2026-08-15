"""Unit tests for scripts/ops/corpus/ops_regime_null_out_and_verify.py (Phase 171 Plan 03).

No live DB: a small scripted fake connection/cursor plays back a fixed sequence of
fetchone()/rowcount responses in the exact order the implementation issues execute()
calls, mirroring tests/unit/services/test_regime_writer.py's `_make_mock_conn` mocking
style but with per-call response control (needed here because a single cell issues
multiple distinct queries in sequence, not one).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from scripts.ops.corpus.ops_regime_null_out_and_verify import (
    _COLUMN_FAMILIES,
    _DEFAULT_COLUMN_FAMILY_OBJ,
    _STATUS_FAILED,
    _STATUS_VERIFIED_NULL,
    _WALK_FORWARD_DEFAULT_PARAMS,
    REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES,
    REGIME_WRITER_OWNED_COLUMN_NAMES,
    _build_any_owned_nonnull_sql,
    _build_null_out_sql,
    _load_initial_warmup_bars,
    _manifest_key,
    _parse_args,
    _run_null_out,
    _run_verify_post_null,
    _run_verify_post_relabel,
)

_REGIME_VOLATILITY_FAMILY = _COLUMN_FAMILIES["regime_volatility"]

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

    def fetchall(self):
        # todo 318: compressed_hypertable_write_session's combined statement_timeout +
        # idle_session_timeout APR lookup reads via fetchall(), not fetchone() -- default
        # empty (no APR rows scripted) so the session falls back to its own defaults,
        # same shape as _mock_sync_conn in tests/unit/test_batch_utils.py.
        return self._response.get("fetchall", [])

    @property
    def rowcount(self) -> int:
        return self._response.get("rowcount", 0)


class _ScriptedConn:
    def __init__(self, responses: list[dict] | None = None) -> None:
        self.calls: list[tuple[str, tuple | None]] = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.autocommit = False
        self._responses = list(responses or [])
        self._idx = 0

    def cursor(self) -> _ScriptedCursor:
        return _ScriptedCursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

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


# compressed_hypertable_write_session's fixed call sequence (services/_batch_utils.py) --
# every test that runs a real (non-empty) write session prepends/appends these, so the
# session's own internals only need updating in one place if its call shape changes again
# (as it did 2026-08-14, twice in the same session: the statement_timeout override was
# added, then the config lookup it added was rescoped from a full-table load to a single
# key; and again 2026-08-15, todo 318: idle_session_timeout/idle_in_transaction_session_
# timeout overrides added, then the whole 3-GUC set (statement_timeout included) collapsed
# from 3 separate SHOW/SET pairs into one combined current_setting()/set_config() round
# trip per direction -- see _SESSION_GUC_OVERRIDES and compressed_hypertable_write_
# session's docstring for what each call is).
_WRITE_SESSION_ENTRY_RESPONSES: list[dict] = [
    {"fetchall": []},  # combined _SESSION_GUC_OVERRIDES APR key lookup (no rows -> defaults)
    {"fetchone": ("30min", "1h", "1h")},  # combined current_setting() read, all 3 GUCs
    {},  # combined set_config() override, all 3 GUCs
    {"rowcount": 0},  # decompress-all (0 chunks)
]
_WRITE_SESSION_EXIT_RESPONSES: list[dict] = [
    {"rowcount": 0},  # compress-all
    {},  # VACUUM
    {},  # combined set_config() restore, all 3 GUCs
]


# ---------------------------------------------------------------------------
# Task 1 -- null-out mode
# ---------------------------------------------------------------------------


class TestNullOutSetClause:
    def test_set_clause_contains_all_8_owned_columns_and_no_others(self):
        null_out_sql = _build_null_out_sql(REGIME_WRITER_OWNED_COLUMN_NAMES)
        for name in REGIME_WRITER_OWNED_COLUMN_NAMES:
            assert f"{name} = NULL" in null_out_sql
        assert null_out_sql.count(" = NULL") == len(REGIME_WRITER_OWNED_COLUMN_NAMES)

    def test_regime_family_is_the_default_column_family(self):
        assert _DEFAULT_COLUMN_FAMILY_OBJ.name == "regime"
        assert _DEFAULT_COLUMN_FAMILY_OBJ.owned_columns == REGIME_WRITER_OWNED_COLUMN_NAMES
        assert _DEFAULT_COLUMN_FAMILY_OBJ.label_column == "regime"


class TestColumnFamilyRegistry:
    def test_regime_volatility_family_covers_exactly_its_own_8_columns(self):
        sql = _build_null_out_sql(REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES)
        for name in REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES:
            assert f"{name} = NULL" in sql
        for name in REGIME_WRITER_OWNED_COLUMN_NAMES:
            assert f"{name} = NULL" not in sql
        assert sql.count(" = NULL") == len(REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES)

    def test_any_owned_nonnull_sql_filters_on_the_right_family_only(self):
        sql = _build_any_owned_nonnull_sql(REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES)
        assert "regime_volatility IS NOT NULL" in sql
        assert "regime IS NOT NULL" not in sql.replace("regime_volatility IS NOT NULL", "")

    def test_two_families_default_manifest_paths_differ(self):
        regime_path = _COLUMN_FAMILIES["regime"].default_manifest_path
        vol_path = _COLUMN_FAMILIES["regime_volatility"].default_manifest_path
        assert regime_path != vol_path

    def test_two_families_default_provenance_report_paths_differ(self):
        regime_path = _COLUMN_FAMILIES["regime"].default_provenance_report_path
        vol_path = _COLUMN_FAMILIES["regime_volatility"].default_provenance_report_path
        assert regime_path != vol_path


class TestNullOutPerCellUpdates:
    def test_n_symbols_x_m_tfs_issue_exactly_nxm_updates_no_batched_scope(self, tmp_path):
        # 2 symbols x 2 tfs = 4 cells, each a clean pass: pre-count, update, verify.
        # Wrapped in compressed_hypertable_write_session's fixed entry/exit sequence
        # (empty chunk lists -> no actual decompress/compress work, just the bracket).
        responses = list(_WRITE_SESSION_ENTRY_RESPONSES)
        for _ in range(4):
            responses += [
                {"fetchone": (5,)},  # pre_null_labeled
                {"rowcount": 5},  # UPDATE rowcount
                {"fetchone": (0,)},  # post-condition: zero remaining
            ]
        responses += _WRITE_SESSION_EXIT_RESPONSES
        conn = _ScriptedConn(responses)
        manifest_path = tmp_path / "manifest.json"

        n_failed = _run_null_out(conn, ["SPY", "QQQ"], ["1h", "1d"], manifest_path, dry_run=False)

        assert n_failed == 0
        updates = _update_calls(conn)
        assert len(updates) == 4
        seen_pairs = {params for _, params in updates}
        assert seen_pairs == {("SPY", "1h"), ("SPY", "1d"), ("QQQ", "1h"), ("QQQ", "1d")}
        # Scoped to _run_null_out's OWN per-cell queries, excluding the write-session
        # bracket's calls (known count from the same fixture used to build `responses`
        # above) -- compressed_hypertable_write_session's own APR config lookup legitimately
        # uses `= ANY(%s)` to fetch 2 keys in one round trip (unrelated to per-cell
        # symbol/tf batching, already covered by test_batch_utils.py), which is not the
        # "no batched scope" invariant this test actually verifies.
        cell_calls = conn.calls[
            len(_WRITE_SESSION_ENTRY_RESPONSES) : len(conn.calls)
            - len(_WRITE_SESSION_EXIT_RESPONSES)
        ]
        for sql, _ in cell_calls:
            assert "IN (" not in sql
            assert "= ANY(" not in sql


class TestNullOutRequiresSymbols:
    def test_missing_symbols_exits_nonzero(self):
        with pytest.raises(SystemExit) as excinfo:
            _parse_args(["--tf", "1h"])
        assert excinfo.value.code != 0

    def test_missing_symbols_exits_nonzero_for_regime_volatility_family(self):
        # --symbols required=True must hold for both families, not just the default.
        with pytest.raises(SystemExit) as excinfo:
            _parse_args(["--tf", "1d", "--column-family", "regime_volatility"])
        assert excinfo.value.code != 0


class TestColumnFamilyArg:
    def test_default_column_family_is_regime(self):
        args = _parse_args(["--symbols", "SPY", "--tf", "1d"])
        assert args.column_family == "regime"

    def test_column_family_accepts_regime_volatility(self):
        args = _parse_args(
            ["--symbols", "SPY", "--tf", "1d", "--column-family", "regime_volatility"]
        )
        assert args.column_family == "regime_volatility"

    def test_invalid_column_family_exits_nonzero(self):
        with pytest.raises(SystemExit) as excinfo:
            _parse_args(["--symbols", "SPY", "--tf", "1d", "--column-family", "bogus"])
        assert excinfo.value.code != 0


class TestNullOutRegimeVolatilityFamily:
    def test_dry_run_reports_regime_volatility_owned_columns_not_regime(self, tmp_path, capsys):
        conn = _ScriptedConn([{"fetchone": (7,)}])
        manifest_path = tmp_path / "manifest.json"

        n_failed = _run_null_out(
            conn, ["SPY"], ["1d"], manifest_path, dry_run=True, family=_REGIME_VOLATILITY_FAMILY
        )

        assert n_failed == 0
        out = capsys.readouterr().out
        assert "regime_volatility-owned columns" in out
        assert str(len(REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES)) in out


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
        # Only QQQ/1h should actually run: write-session entry, then pre-count, update,
        # verify, then write-session exit.
        conn = _ScriptedConn(
            [
                *_WRITE_SESSION_ENTRY_RESPONSES,
                {"fetchone": (3,)},
                {"rowcount": 3},
                {"fetchone": (0,)},
                *_WRITE_SESSION_EXIT_RESPONSES,
            ]
        )

        n_failed = _run_null_out(conn, ["SPY", "QQQ"], ["1h"], manifest_path, dry_run=False)

        assert n_failed == 0
        assert len(conn.calls) == len(_WRITE_SESSION_ENTRY_RESPONSES) + 3 + len(
            _WRITE_SESSION_EXIT_RESPONSES
        )
        # The 3 cell-level calls (pre-count, update, verify) sit between the write-session
        # entry and exit brackets -- sliced by the same centralized fixture lengths used to
        # build `conn`'s scripted responses above, not a hardcoded index.
        cell_calls = conn.calls[
            len(_WRITE_SESSION_ENTRY_RESPONSES) : len(_WRITE_SESSION_ENTRY_RESPONSES) + 3
        ]
        for sql, params in cell_calls:
            assert params == ("QQQ", "1h")

    def test_all_cells_already_verified_skips_the_write_session_entirely(self, tmp_path):
        """Efficiency fix (2026-08-14): when the whole requested scope is already a
        verified-null resume no-op, _run_null_out must not pay for a decompress/
        recompress+VACUUM session it will issue zero UPDATEs inside -- asserted by an empty
        scripted-response list: any unscripted call would return {} and silently succeed
        with wrong values, so a real session entry (which reads cur.rowcount) would show up
        as a spurious call rather than fail outright. len(conn.calls) == 0 is the real
        assertion."""
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    _manifest_key("SPY", "1h"): {"status": _STATUS_VERIFIED_NULL},
                    _manifest_key("QQQ", "1h"): {"status": _STATUS_VERIFIED_NULL},
                }
            )
        )
        conn = _ScriptedConn([])

        n_failed = _run_null_out(conn, ["SPY", "QQQ"], ["1h"], manifest_path, dry_run=False)

        assert n_failed == 0
        assert len(conn.calls) == 0


class TestNullOutFailedCellContinues:
    def test_postcondition_failure_marks_cell_failed_and_continues(self, tmp_path):
        manifest_path = tmp_path / "manifest.json"
        # Cell 1 (SPY/1h): post-condition fails (remaining_nonnull=3).
        # Cell 2 (QQQ/1h): post-condition passes.
        conn = _ScriptedConn(
            [
                *_WRITE_SESSION_ENTRY_RESPONSES,
                {"fetchone": (5,)},
                {"rowcount": 5},
                {"fetchone": (3,)},  # FAIL
                {"fetchone": (2,)},
                {"rowcount": 2},
                {"fetchone": (0,)},  # PASS
                *_WRITE_SESSION_EXIT_RESPONSES,
            ]
        )

        n_failed = _run_null_out(conn, ["SPY", "QQQ"], ["1h"], manifest_path, dry_run=False)

        assert n_failed == 1
        assert len(_update_calls(conn)) == 2  # both cells attempted, run did not abort
        manifest = json.loads(manifest_path.read_text())
        assert manifest[_manifest_key("SPY", "1h")]["status"] == _STATUS_FAILED
        assert manifest[_manifest_key("QQQ", "1h")]["status"] == _STATUS_VERIFIED_NULL


# ---------------------------------------------------------------------------
# Task 2 -- verify-post-null / verify-post-relabel modes
# ---------------------------------------------------------------------------


class TestVerifyPostNull:
    def test_issues_zero_update_calls(self):
        conn = _ScriptedConn([{"fetchone": (0,)}])
        n_failed = _run_verify_post_null(conn, ["SPY"], ["1h"])
        assert n_failed == 0
        assert _update_calls(conn) == []


class TestVerifyPostRelabel:
    def test_passes_when_rows_before_first_label_meets_warmup_floor(self, tmp_path, capsys):
        first_ts = datetime(2020, 1, 1, tzinfo=UTC)
        conn = _ScriptedConn(
            [
                {"fetchone": (100,)},  # initial_warmup_bars from config_state
                {"fetchone": (500, first_ts)},  # labeled_rows, first_labeled_bar_ts
                {"fetchone": (150,)},  # rows_before_first_label >= 100
            ]
        )

        n_failed = _run_verify_post_relabel(
            conn, ["SPY"], ["1h"], provenance_report_path=tmp_path / "report.json"
        )

        assert n_failed == 0
        assert _update_calls(conn) == []
        out = capsys.readouterr().out
        assert "REQ-3 PROVENANCE: PASS" in out
        assert "column_family=regime" in out
        report = json.loads((tmp_path / "report.json").read_text())
        assert report[0]["verdict"] == "pass"

    def test_fails_when_rows_before_first_label_is_one_short(self, tmp_path):
        first_ts = datetime(2020, 1, 1, tzinfo=UTC)
        conn = _ScriptedConn(
            [
                {"fetchone": (100,)},
                {"fetchone": (500, first_ts)},
                {"fetchone": (99,)},  # one short of 100
            ]
        )

        n_failed = _run_verify_post_relabel(
            conn, ["SPY"], ["1h"], provenance_report_path=tmp_path / "report.json"
        )

        assert n_failed == 1
        report = json.loads((tmp_path / "report.json").read_text())
        assert report[0]["verdict"] == "fail"

    def test_zero_labeled_rows_yields_no_labels_and_does_not_fail(self, tmp_path):
        conn = _ScriptedConn(
            [
                {"fetchone": (100,)},
                {"fetchone": (0, None)},  # zero labeled rows
            ]
        )

        n_failed = _run_verify_post_relabel(
            conn, ["SPY"], ["1h"], provenance_report_path=tmp_path / "report.json"
        )

        assert n_failed == 0
        assert len(conn.calls) == 2  # no third (rows-before) query issued
        report = json.loads((tmp_path / "report.json").read_text())
        assert report[0]["verdict"] == "no_labels"

    def test_issues_zero_update_calls(self, tmp_path):
        conn = _ScriptedConn([{"fetchone": (100,)}, {"fetchone": (0, None)}])
        _run_verify_post_relabel(
            conn, ["SPY"], ["1h"], provenance_report_path=tmp_path / "report.json"
        )
        assert _update_calls(conn) == []

    def test_regime_volatility_family_filters_on_regime_volatility_column_and_own_report_path(
        self, tmp_path, capsys
    ):
        first_ts = datetime(2020, 1, 1, tzinfo=UTC)
        conn = _ScriptedConn(
            [
                {"fetchone": (100,)},
                {"fetchone": (500, first_ts)},
                {"fetchone": (150,)},
            ]
        )
        report_path = tmp_path / "vol_report.json"

        n_failed = _run_verify_post_relabel(
            conn,
            ["SPY"],
            ["1h"],
            family=_REGIME_VOLATILITY_FAMILY,
            provenance_report_path=report_path,
        )

        assert n_failed == 0
        out = capsys.readouterr().out
        assert "column_family=regime_volatility" in out
        assert report_path.exists()
        labeled_count_call = conn.calls[1]
        assert "regime_volatility IS NOT NULL" in labeled_count_call[0]


class TestLoadInitialWarmupBars:
    def test_reads_from_config_state_row_not_module_constant_when_present(self):
        mocked_value = 999
        assert mocked_value != _WALK_FORWARD_DEFAULT_PARAMS["1h"][1]
        conn = _ScriptedConn([{"fetchone": (mocked_value,)}])

        result = _load_initial_warmup_bars(conn, "1h")

        assert result == mocked_value

    def test_falls_back_to_module_constant_when_key_missing(self):
        conn = _ScriptedConn([{"fetchone": None}])

        result = _load_initial_warmup_bars(conn, "1h")

        assert result == _WALK_FORWARD_DEFAULT_PARAMS["1h"][1]
