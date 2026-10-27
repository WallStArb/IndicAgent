"""Unit tests for the Tradier deletion script (phase 191 plan 20 task 2).

Covers the pure parts and the delete orchestration on fakes: the one exact predicate per table
(held-back names excluded everywhere), CSV record counting, the manifest check (live, files,
ledger, retained loads), the refusal without a verified manifest, the trial gate, the free-disk
abort before a batch, the per-batch count equality and cascade checks, and the first-bar TSV.
No database anywhere in this file: every connection is a fake that records its statements.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from scripts.ops.bars import ops_tradier_delete as mod

# --- predicates ------------------------------------------------------------------------------

_HELD = "NOT (symbol = ANY(%(held)s::text[]))"
_BATCH = "symbol = ANY(%(batch)s::text[])"
_BAR_TABLES = {"ohlcv_raw", "market_data_ohlcv"}


def test_tables_are_the_five_in_delete_order():
    assert [spec.table for spec in mod.TABLES] == [
        "ohlcv_revision",
        "ohlcv_load",
        "ohlcv_raw",
        "market_data_ohlcv",
        "ohlcv_coverage",
    ]


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("ohlcv_revision", "vendor"),
        ("ohlcv_load", "source"),
        ("ohlcv_raw", "vendor"),
        ("market_data_ohlcv", "vendor"),
        ("ohlcv_coverage", "provider"),
    ],
)
def test_each_table_has_one_exact_tradier_predicate(table: str, column: str):
    spec = mod.SPECS[table]
    scope = " AND timeframe = '1d'" if table in _BAR_TABLES else ""
    assert spec.predicate.startswith(f"{column} = 'tradier'{scope} AND {_HELD}")
    assert spec.delete_sql == f"DELETE FROM {table} WHERE {_BATCH} AND {spec.predicate}"
    assert spec.count_sql == (
        f"SELECT symbol, count(*) FROM {table} WHERE {spec.predicate} GROUP BY symbol"
    )
    assert spec.select_sql == f"SELECT * FROM {table} WHERE {spec.predicate}"


def test_only_the_load_predicate_carries_an_extra_clause():
    for spec in mod.TABLES:
        column = spec.predicate.split(" ", 1)[0]
        scope = " AND timeframe = '1d'" if spec.table in _BAR_TABLES else ""
        bare = f"{column} = 'tradier'{scope} AND {_HELD}"
        if spec.table == "ohlcv_load":
            assert spec.predicate == bare + mod.LOAD_KEEPS_FOREIGN_REVISIONS
        else:
            assert spec.predicate == bare


def test_a_tradier_load_owning_another_vendors_revision_is_kept():
    # A Tradier load that displaced IBKR canonical values owns ohlcv_revision rows of vendor
    # ibkr; deleting the load would cascade-delete IBKR evidence, so the predicate keeps it.
    clause = mod.LOAD_KEEPS_FOREIGN_REVISIONS
    assert "NOT EXISTS" in clause
    assert "v.load_id = ohlcv_load.load_id" in clause
    assert "v.vendor <> 'tradier'" in clause


def test_the_vendor_literal_is_the_only_one_in_every_predicate():
    for spec in mod.TABLES:
        literals = set(re.findall(r"'([^']*)'", spec.predicate))
        want = {"tradier", "1d"} if spec.table in _BAR_TABLES else {"tradier"}
        assert literals == want, spec.table


def test_bar_deletes_are_scoped_to_the_1d_segments_and_the_dump_guards_the_scope():
    # timeframe is segmentby on both bar hypertables; vendor is not on market_data_ohlcv, so
    # without the 1d scope a batch delete decompresses every timeframe of each name.
    for table in _BAR_TABLES:
        assert "timeframe = '1d'" in mod.SPECS[table].delete_sql
    guard = mod._OFF_TIMEFRAME_SQL
    assert "FROM ohlcv_raw WHERE vendor = 'tradier' AND timeframe <> '1d'" in guard
    assert "FROM market_data_ohlcv WHERE vendor = 'tradier' AND timeframe <> '1d'" in guard


# --- files -----------------------------------------------------------------------------------


def _gz(path: Path, body: bytes) -> str:
    path.write_bytes(gzip.compress(body))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_count_csv_records_counts_quoted_embedded_newlines_once(tmp_path: Path):
    path = tmp_path / "t.csv.gz"
    _gz(path, b'a,"line one\nline two",c\n1,2,3\n')
    assert mod.count_csv_records(path) == 2


def test_count_csv_records_empty_file_is_zero(tmp_path: Path):
    path = tmp_path / "t.csv.gz"
    _gz(path, b"")
    assert mod.count_csv_records(path) == 0


def test_tradier_backup_sha256_matches_hashlib(tmp_path: Path):
    path = tmp_path / "t.csv.gz"
    digest = _gz(path, b"x\n")
    assert mod.sha256_of_file(path) == digest


def test_backup_file_name_is_per_table_and_utc_date():
    from datetime import date

    assert mod.backup_file_name("ohlcv_raw", date(2026, 10, 27)) == (
        "tradier_ohlcv_raw_2026-10-27.csv.gz"
    )


# --- manifest check --------------------------------------------------------------------------


def _manifest() -> dict[str, Any]:
    per_symbol = {
        "ohlcv_revision": {"AAA": 2},
        "ohlcv_load": {"AAA": 1, "BBB": 1},
        "ohlcv_raw": {"AAA": 5, "BBB": 3},
        "market_data_ohlcv": {"AAA": 4, "BBB": 3},
        "ohlcv_coverage": {},
    }
    return {
        "held": ["HLD"],
        "retained_loads": 7,
        "request_ledger": {"total": 100, "tradier": 10},
        "tables": [
            {
                "table": table,
                "rows": sum(counts.values()),
                "per_symbol": counts,
                "file": f"tradier_{table}_2026-10-27.csv.gz",
                "sha256": f"sha-{table}",
            }
            for table, counts in per_symbol.items()
        ],
    }


def _agreeing(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "live": {t["table"]: dict(t["per_symbol"]) for t in manifest["tables"]},
        "files": {t["table"]: t["rows"] for t in manifest["tables"]},
        "digests": {t["table"]: t["sha256"] for t in manifest["tables"]},
        "completed": set(),
        "retained_live": 7,
        "ledger_live": {"total": 100, "tradier": 10},
    }


def test_verify_passes_when_live_files_ledger_and_retained_agree():
    manifest = _manifest()
    assert mod.verify_problems(manifest, **_agreeing(manifest)) == []


def test_verify_names_a_live_count_mismatch_by_table_and_symbol():
    manifest = _manifest()
    observed = _agreeing(manifest)
    observed["live"]["ohlcv_raw"]["AAA"] = 6
    problems = mod.verify_problems(manifest, **observed)
    assert problems == ["ohlcv_raw AAA: live 6 != expected 5"]


def test_verify_flags_a_live_symbol_the_manifest_lacks():
    manifest = _manifest()
    observed = _agreeing(manifest)
    observed["live"]["market_data_ohlcv"]["NEW"] = 1
    assert mod.verify_problems(manifest, **observed) == [
        "market_data_ohlcv NEW: live 1 != expected 0"
    ]


def test_verify_names_file_row_and_digest_mismatches():
    manifest = _manifest()
    observed = _agreeing(manifest)
    observed["files"]["ohlcv_load"] = 1
    observed["digests"]["ohlcv_raw"] = "other"
    del observed["files"]["ohlcv_coverage"]
    problems = mod.verify_problems(manifest, **observed)
    assert "ohlcv_load: file rows 1 != manifest 2" in problems
    assert "ohlcv_raw: sha256 of tradier_ohlcv_raw_2026-10-27.csv.gz changed" in problems
    assert "ohlcv_coverage: file tradier_ohlcv_coverage_2026-10-27.csv.gz missing" in problems


def test_verify_expects_zero_live_rows_for_completed_symbols():
    manifest = _manifest()
    observed = _agreeing(manifest)
    observed["completed"] = {"AAA"}
    problems = mod.verify_problems(manifest, **observed)
    assert "ohlcv_raw AAA: live 5 != expected 0" in problems
    for table in observed["live"]:
        observed["live"][table].pop("AAA", None)
    assert mod.verify_problems(manifest, **observed) == []


def test_verify_requires_the_ledger_tradier_count_unchanged_and_total_not_shrunk():
    manifest = _manifest()
    observed = _agreeing(manifest)
    observed["ledger_live"] = {"total": 120, "tradier": 10}
    assert mod.verify_problems(manifest, **observed) == []
    observed["ledger_live"] = {"total": 99, "tradier": 9}
    problems = mod.verify_problems(manifest, **observed)
    assert "ohlcv_request: tradier rows 9 != manifest 10" in problems
    assert "ohlcv_request: total rows 99 < manifest 100" in problems


def test_verify_requires_the_retained_load_count_unchanged():
    manifest = _manifest()
    observed = _agreeing(manifest)
    observed["retained_live"] = 6
    assert mod.verify_problems(manifest, **observed) == [
        "ohlcv_load: retained Tradier loads 6 != manifest 7"
    ]


# --- fakes -----------------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn
        self.rowcount = -1
        self._result: list[tuple[Any, ...]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self._conn.statements.append(sql)
        self._conn.params.append(params)
        result = self._conn.responder(sql, params)
        if isinstance(result, int):
            self.rowcount = result
            self._result = []
        else:
            self._result = list(result)
            self.rowcount = len(self._result)

    def fetchone(self) -> tuple[Any, ...]:
        return self._result[0]

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._result


class _FakeConn:
    def __init__(self, responder: Callable[[str, Any], Any]) -> None:
        self.responder = responder
        self.statements: list[str] = []
        self.params: list[Any] = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            yield
        except BaseException:
            self.rollbacks += 1
            raise
        self.commits += 1


def _deletes(conn: _FakeConn) -> list[str]:
    return [s for s in conn.statements if s.startswith("DELETE")]


def _responder_for(manifest: dict[str, Any], *, cascade: int = 0, skew: int = 0):
    """Answers each DELETE with the manifest count of the batch's symbols (plus `skew`)."""
    per = {t["table"]: t["per_symbol"] for t in manifest["tables"]}

    def respond(sql: str, params: Any) -> Any:
        if sql.startswith("DELETE"):
            table = sql.split()[2]
            return sum(per[table].get(s, 0) for s in params["batch"]) + skew
        if sql == mod.CASCADE_CHECK_SQL:
            return [(cascade,)]
        return 0

    return respond


def _clock() -> Callable[[], float]:
    ticks = iter(range(1000))
    return lambda: float(next(ticks))


# --- one batch -------------------------------------------------------------------------------


def test_delete_batch_runs_every_delete_in_order_in_one_transaction():
    manifest = _manifest()
    conn = _FakeConn(_responder_for(manifest))
    expected = mod.expected_counts(manifest, ["AAA", "BBB"])
    timings = mod.delete_batch(
        conn, ["AAA", "BBB"], ["HLD"], expected, free_bytes=lambda: 10**12, clock=_clock()
    )
    assert conn.statements[0] == mod.DECOMPRESSION_LIMIT_SQL
    assert _deletes(conn) == [spec.delete_sql for spec in mod.TABLES]
    # the cascade check sits between the revision delete and the load delete
    order = conn.statements
    assert (
        order.index(mod.SPECS["ohlcv_revision"].delete_sql)
        < order.index(mod.CASCADE_CHECK_SQL)
        < order.index(mod.SPECS["ohlcv_load"].delete_sql)
    )
    assert conn.commits == 1 and conn.rollbacks == 0
    assert {t: v["rows"] for t, v in timings.items()} == expected
    for params in conn.params[1:]:
        assert params == {"batch": ["AAA", "BBB"], "held": ["HLD"]}


def test_the_session_never_uses_the_hardened_decompress_all_helper():
    # Amendment 2026-10-13: compressed_hypertable_write_session is not available for these
    # tables (and commits the caller's transaction); plain DELETE batches with native DML
    # decompression, the per-batch disk guard and the mandatory trial replace it.
    source = Path(mod.__file__).read_text()
    assert "compressed_hypertable_write_session(" not in source
    assert mod.DECOMPRESSION_LIMIT_SQL == (
        "SET LOCAL timescaledb.max_tuples_decompressed_per_dml_transaction = 0"
    )


def test_delete_batch_rolls_back_on_a_count_mismatch():
    manifest = _manifest()
    conn = _FakeConn(_responder_for(manifest, skew=1))
    expected = mod.expected_counts(manifest, ["AAA"])
    with pytest.raises(mod.DeleteRefused, match="ohlcv_revision deleted 3 rows, manifest 2"):
        mod.delete_batch(conn, ["AAA"], [], expected, free_bytes=lambda: 1, clock=_clock())
    assert conn.commits == 0 and conn.rollbacks == 1


def test_delete_batch_refuses_a_load_delete_that_would_cascade():
    manifest = _manifest()
    conn = _FakeConn(_responder_for(manifest, cascade=4))
    expected = mod.expected_counts(manifest, ["AAA"])
    with pytest.raises(mod.DeleteRefused, match="cascade"):
        mod.delete_batch(conn, ["AAA"], [], expected, free_bytes=lambda: 1, clock=_clock())
    assert mod.SPECS["ohlcv_load"].delete_sql not in conn.statements
    assert conn.rollbacks == 1


# --- batch run and the disk guard ------------------------------------------------------------


def _state() -> dict[str, Any]:
    return mod.new_state("msha")


def test_run_batches_aborts_before_any_delete_when_disk_is_below_the_floor(tmp_path: Path):
    manifest = _manifest()
    conn = _FakeConn(_responder_for(manifest))
    state = _state()
    code = mod.run_batches(
        conn,
        manifest,
        state,
        tmp_path / "state.json",
        batch_symbols=1,
        floor_bytes=200 * 2**30,
        free_bytes=lambda: 199 * 2**30,
        clock=_clock(),
    )
    assert code == mod.EXIT_DISK_ABORT
    assert _deletes(conn) == []
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["aborted"]["reason"] == "free disk below floor"
    assert saved["aborted"]["free_bytes"] == 199 * 2**30
    assert saved["completed"] == []


def test_run_batches_checks_disk_before_every_batch_and_stops_mid_run(tmp_path: Path):
    manifest = _manifest()
    conn = _FakeConn(_responder_for(manifest))
    state = _state()
    # batch 1's guard reads 500 GB; the batch's own per-table reads see plenty; batch 2's
    # guard reads 100 GB and aborts.
    readings = iter([500 * 2**30] + [400 * 2**30] * 10 + [100 * 2**30])
    code = mod.run_batches(
        conn,
        manifest,
        state,
        tmp_path / "state.json",
        batch_symbols=1,
        floor_bytes=200 * 2**30,
        free_bytes=lambda: next(readings),
        clock=_clock(),
    )
    assert code == mod.EXIT_DISK_ABORT
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["completed"] == ["AAA"]
    assert saved["aborted"]["next_batch"] == ["BBB"]
    assert all("BBB" not in p["batch"] for p in conn.params if p and "batch" in p)


def test_run_batches_completes_and_skips_completed_symbols(tmp_path: Path):
    manifest = _manifest()
    conn = _FakeConn(_responder_for(manifest))
    state = _state()
    state["completed"] = ["AAA"]
    code = mod.run_batches(
        conn,
        manifest,
        state,
        tmp_path / "state.json",
        batch_symbols=20,
        floor_bytes=1,
        free_bytes=lambda: 2,
        clock=_clock(),
    )
    assert code == 0
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["completed"] == ["AAA", "BBB"]
    assert saved["complete"] is True
    assert {p["batch"][0] for p in conn.params if p and "batch" in p} == {"BBB"}


def test_manifest_symbols_exclude_nothing_but_come_from_every_table():
    assert mod.manifest_symbols(_manifest()) == ["AAA", "BBB"]


# --- the trial gate --------------------------------------------------------------------------


def test_trial_gate_refuses_without_a_trial_report():
    assert "trial" in mod.trial_refusal(None, 10, 10**12, 1)


def test_trial_gate_extrapolates_disk_per_row_over_the_remaining_rows():
    report = {"rows_total": 100, "disk_delta_bytes": 1000}
    # 10 bytes per row, 1000 rows left: 10 000 bytes needed
    assert mod.trial_refusal(report, 1000, free_bytes=20_000, floor_bytes=5_000) is None
    refusal = mod.trial_refusal(report, 1000, free_bytes=14_000, floor_bytes=5_000)
    assert refusal is not None and "10000" in refusal


def test_trial_gate_treats_a_freed_disk_as_zero_growth():
    report = {"rows_total": 100, "disk_delta_bytes": -5000}
    assert mod.trial_refusal(report, 10**9, free_bytes=6, floor_bytes=5) is None


def test_trial_gate_refuses_a_trial_that_deleted_nothing():
    assert "deleted no rows" in mod.trial_refusal(
        {"rows_total": 0, "disk_delta_bytes": 0}, 10, 10**12, 1
    )


# --- the apply path refuses without a verified manifest --------------------------------------


def _apply(tmp_path: Path, **overrides: Any) -> tuple[int, _FakeConn]:
    manifest = _manifest()
    conn = _FakeConn(_responder_for(manifest))
    kwargs: dict[str, Any] = {
        "conn": conn,
        "manifest": manifest,
        "state": _state(),
        "manifest_sha256": "msha",
        "state_path": tmp_path / "state.json",
        "verify": lambda: [],
        "trial_report": {"rows_total": 10, "disk_delta_bytes": 10},
        "restatement_flags": 0,
        "write_tsv": lambda: None,
        "batch_symbols": 20,
        "floor_bytes": 1,
        "free_bytes": lambda: 10**12,
        "clock": _clock(),
    }
    kwargs.update(overrides)
    return mod.apply_delete(**kwargs), conn


def test_apply_refuses_without_a_manifest(tmp_path: Path):
    code, conn = _apply(tmp_path, manifest=None)
    assert code == mod.EXIT_REFUSED and _deletes(conn) == []


def test_apply_refuses_when_the_manifest_does_not_verify(tmp_path: Path):
    code, conn = _apply(tmp_path, verify=lambda: ["ohlcv_raw AAA: live 6 != expected 5"])
    assert code == mod.EXIT_REFUSED and _deletes(conn) == []


def test_apply_refuses_without_a_trial(tmp_path: Path):
    code, conn = _apply(tmp_path, trial_report=None)
    assert code == mod.EXIT_REFUSED and _deletes(conn) == []


def test_apply_refuses_when_a_restatement_flag_holds_a_load(tmp_path: Path):
    code, conn = _apply(tmp_path, restatement_flags=1)
    assert code == mod.EXIT_REFUSED and _deletes(conn) == []


def test_apply_writes_the_first_bar_tsv_before_the_first_delete(tmp_path: Path):
    seen: list[int] = []
    holder: dict[str, _FakeConn] = {}

    def write_tsv() -> None:
        seen.append(len(_deletes(holder["conn"])))

    manifest = _manifest()
    conn = _FakeConn(_responder_for(manifest))
    holder["conn"] = conn
    code, _ = _apply(tmp_path, conn=conn, write_tsv=write_tsv)
    assert code == 0
    assert seen == [0]
    assert len(_deletes(conn)) == len(mod.TABLES)  # one batch of both symbols


def test_apply_does_not_rewrite_the_tsv_on_a_resume(tmp_path: Path):
    calls: list[int] = []
    state = _state()
    state["tsv_written"] = True
    code, _ = _apply(tmp_path, state=state, write_tsv=lambda: calls.append(1))
    assert code == 0 and calls == []


def test_apply_refuses_a_state_bound_to_another_manifest(tmp_path: Path):
    code, conn = _apply(tmp_path, state=mod.new_state("other"), manifest_sha256="msha")
    assert code == mod.EXIT_REFUSED and _deletes(conn) == []


# --- first-bar change record ----------------------------------------------------------------


def test_first_bar_tsv_lists_every_name_and_marks_the_changes():
    measures = [
        {
            "symbol": "BBB",
            "n_tradier": 5,
            "n_residue": 0,
            "first_bar_current": "2010-01-04",
            "first_bar_after": "2010-01-04",
        },
        {
            "symbol": "AAA",
            "n_tradier": 9,
            "n_residue": 3,
            "first_bar_current": "2005-01-03",
            "first_bar_after": "2007-06-01",
        },
        {
            "symbol": "CCC",
            "n_tradier": 2,
            "n_residue": 2,
            "first_bar_current": "2020-01-02",
            "first_bar_after": None,
        },
        {
            "symbol": "HLD",
            "n_tradier": 2,
            "n_residue": 2,
            "first_bar_current": "2020-01-02",
            "first_bar_after": None,
        },
    ]
    lines = mod.render_first_bar_tsv(measures, held=["HLD"]).splitlines()
    assert lines[0] == (
        "symbol\tn_tradier_sessions\tn_residue_sessions\tfirst_bar_current\t"
        "first_bar_after\tfirst_bar_changed"
    )
    assert lines[1:] == [
        "AAA\t9\t3\t2005-01-03\t2007-06-01\ttrue",
        "BBB\t5\t0\t2010-01-04\t2010-01-04\tfalse",
        "CCC\t2\t2\t2020-01-02\tnone\ttrue",
    ]


# --- dry run -------------------------------------------------------------------------------


def test_dry_run_counts_issue_selects_only():
    conn = _FakeConn(lambda sql, params: [("AAA", 3), ("BBB", 1)])
    counts = mod.plan_counts(conn, held=["HLD"])
    assert counts == {spec.table: {"AAA": 3, "BBB": 1} for spec in mod.TABLES}
    assert all(s.startswith("SELECT") for s in conn.statements)
    assert all(p == {"held": ["HLD"]} for p in conn.params)


def test_parse_held_normalizes_and_rejects_empty_items():
    assert mod.parse_held(None) == []
    assert mod.parse_held("bbb, AAA") == ["AAA", "BBB"]
    with pytest.raises(SystemExit):
        mod.parse_held("AAA,,BBB")


# --- APR keys ------------------------------------------------------------------------------


def test_apr_keys_are_the_two_seeded_infra_keys():
    assert mod.MIN_FREE_DISK_KEY == "infra.tradier_delete.min_free_disk_gb"
    assert mod.BATCH_SYMBOLS_KEY == "infra.tradier_delete.batch_symbols"


def test_the_migration_seeds_both_keys():
    migrations = Path(mod.project_root) / "production" / "migrations"
    matches = sorted(migrations.glob("*_tradier_delete_apr.sql"))
    assert len(matches) == 1
    body = matches[0].read_text()
    for key, default in (
        ("infra.tradier_delete.min_free_disk_gb", "200"),
        ("infra.tradier_delete.batch_symbols", "20"),
    ):
        assert body.count(f"'{key}'") == 3, key  # schema, state, history
        assert f"'{default}'" in body
    assert "Not an ML learning target." in body
