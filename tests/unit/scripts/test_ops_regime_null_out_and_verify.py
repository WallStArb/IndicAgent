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
    _STATUS_VERIFIED_NULL,
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
from tests.unit._compressed_hypertable_write_session_fakes import (
    WRITE_SESSION_ENTRY_RESPONSES as _WRITE_SESSION_ENTRY_RESPONSES,
)
from tests.unit._compressed_hypertable_write_session_fakes import (
    ScriptedConn as _ScriptedConn,
)

_REGIME_VOLATILITY_FAMILY = _COLUMN_FAMILIES["regime_volatility"]

_MODULE = "scripts.ops.corpus.ops_regime_null_out_and_verify"


# ---------------------------------------------------------------------------
# Scripted fake connection -- replays responses in call order. _ScriptedConn/
# _WRITE_SESSION_*_RESPONSES imported above (todo 307: extracted to
# tests/unit/_compressed_hypertable_write_session_fakes.py once a second caller needed
# this exact fake). _ScriptedCursor itself is never referenced directly here -- only
# via _ScriptedConn.cursor() -- so it isn't imported.
# ---------------------------------------------------------------------------


def _update_calls(conn: _ScriptedConn) -> list[tuple[str, tuple | None]]:
    return [c for c in conn.calls if "UPDATE feature_vectors" in c[0]]


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


class TestNullOutRefusesTheKernelTable:
    def test_a_real_run_refuses_to_open_a_write_session_on_feature_vectors(self, tmp_path):
        """Migration 570: feature_vectors is the rebuild's table (one writer, bulk_load) and left
        the write-session allow-list, so this v1 repair pass refuses before any UPDATE."""
        conn = _ScriptedConn(list(_WRITE_SESSION_ENTRY_RESPONSES))
        with pytest.raises(ValueError, match="feature_vectors"):
            _run_null_out(conn, ["SPY"], ["1h"], tmp_path / "manifest.json", dry_run=False)
        assert _update_calls(conn) == []


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
    def test_reads_from_config_state_row_when_present(self):
        mocked_value = 999
        conn = _ScriptedConn([{"fetchone": (mocked_value,)}])

        result = _load_initial_warmup_bars(conn, "1h")

        assert result == mocked_value

    def test_raises_naming_the_key_when_it_is_missing(self):
        conn = _ScriptedConn([{"fetchone": None}])

        with pytest.raises(KeyError, match="initial_warmup_bars.1h"):
            _load_initial_warmup_bars(conn, "1h")


# ---------------------------------------------------------------------------
# todo 290 item 4 (186-13): SQL text is computed once per family, not per cell
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("family_name", ["regime", "regime_volatility"])
def test_column_family_sql_is_precomputed_and_matches_the_builders(family_name):
    family = _COLUMN_FAMILIES[family_name]
    assert family.null_out_sql == _build_null_out_sql(family.owned_columns)
    assert family.any_owned_nonnull_sql == _build_any_owned_nonnull_sql(family.owned_columns)
    assert f"{family.label_column} IS NOT NULL" in family.pre_null_labeled_sql
    assert f"min(bar_ts) FILTER (WHERE {family.label_column} IS NOT NULL)" in (
        family.labeled_count_and_min_ts_sql
    )


def test_per_cell_helpers_never_rebuild_the_sql(monkeypatch):
    import scripts.ops.corpus.ops_regime_null_out_and_verify as module

    def _boom(*args, **kwargs):
        raise AssertionError("SQL rebuilt per cell")

    for name in (
        "_build_null_out_sql",
        "_build_any_owned_nonnull_sql",
        "_pre_null_labeled_sql_text",
        "_labeled_count_and_min_ts_sql_text",
    ):
        monkeypatch.setattr(module, name, _boom)

    class _Cursor:
        rowcount = 3

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            self.sql = sql

        def fetchone(self):
            return (1, None) if "min(bar_ts)" in self.sql else (1,)

    class _Conn:
        def cursor(self):
            return _Cursor()

    family = _COLUMN_FAMILIES["regime_volatility"]
    for _ in range(2):
        assert module._pre_null_labeled_count(_Conn(), "SPY", "1d", family) == 1
        assert module._issue_null_out_update(_Conn(), "SPY", "1d", family) == 3
        assert module._count_any_owned_nonnull(_Conn(), "SPY", "1d", family) == 1
        assert module._labeled_count_and_min_ts(_Conn(), "SPY", "1d", family) == (1, None)
