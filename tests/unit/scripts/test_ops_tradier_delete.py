"""Unit tests for the Tradier deletion script (phase 191 plan 20 task 2).

Covers the pure parts and the delete orchestration on fakes: the one exact predicate per value
table (held-back names excluded everywhere; ohlcv_load is lineage and is never deleted), CSV
record counting, the manifest check, the trial gate, the free-disk abort before a batch, the
per-batch content and count checks, the in-flight settlement, the state lock and the first-bar
TSV. No database anywhere in this file: every connection is a fake that records its statements.
The real SQL runs in tests/integration/test_ops_tradier_delete_scratch.py.
"""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from scripts.ops.bars import ops_old_store_backup
from scripts.ops.bars import ops_tradier_delete as mod

_HELD = "NOT (symbol = ANY(%(held)s::text[]))"
_BATCH = "symbol = ANY(%(batch)s::text[])"
_BAR_TABLES = {"ohlcv_raw", "market_data_ohlcv"}

# --- predicates ------------------------------------------------------------------------------


def test_tables_are_the_four_value_tables_in_delete_order():
    assert [spec.table for spec in mod.TABLES] == [
        "ohlcv_revision",
        "ohlcv_raw",
        "market_data_ohlcv",
        "ohlcv_coverage",
    ]


def test_ohlcv_load_is_lineage_and_never_deleted():
    source = Path(mod.__file__).read_text()
    assert not re.search(r"DELETE\s+FROM\s+ohlcv_load", source)
    assert "ohlcv_load" not in mod.SPECS


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("ohlcv_revision", "vendor"),
        ("ohlcv_raw", "vendor"),
        ("market_data_ohlcv", "vendor"),
        ("ohlcv_coverage", "provider"),
    ],
)
def test_each_table_has_one_exact_tradier_predicate(table: str, column: str):
    spec = mod.SPECS[table]
    scope = " AND timeframe = '1d'" if table in _BAR_TABLES else ""
    assert spec.predicate == f"{column} = 'tradier'{scope} AND {_HELD}"
    assert spec.delete_sql == f"DELETE FROM {table} WHERE {_BATCH} AND {spec.predicate}"
    assert spec.count_sql == (
        f"SELECT symbol, count(*) FROM {table} WHERE {spec.predicate} GROUP BY symbol"
    )
    assert spec.batch_count_sql == (
        f"SELECT symbol, count(*) FROM {table} WHERE {_BATCH} AND {spec.predicate} "
        "GROUP BY symbol"
    )
    assert spec.select_sql == f"SELECT * FROM {table} WHERE {spec.predicate}"


def test_the_two_bar_tables_share_one_1d_predicate():
    assert mod.SPECS["ohlcv_raw"].predicate == mod.SPECS["market_data_ohlcv"].predicate
    assert mod.SPECS["ohlcv_raw"].predicate == mod._BAR_1D_PREDICATE


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


def test_the_foreign_revision_count_reads_other_vendors_under_tradier_loads():
    sql = mod._FOREIGN_REVISIONS_SQL
    assert "l.source = 'tradier'" in sql and "v.vendor <> 'tradier'" in sql


def test_digest_sql_orders_whole_row_text_under_the_same_predicate():
    spec = mod.SPECS["ohlcv_raw"]
    assert spec.digest_sql == (
        "SELECT symbol, count(*), md5(string_agg(ohlcv_raw::text, E'\\n' ORDER BY "
        f"ohlcv_raw::text)) FROM ohlcv_raw WHERE {spec.predicate} GROUP BY symbol"
    )
    assert spec.batch_digest_sql.endswith(f"WHERE {_BATCH} AND {spec.predicate} GROUP BY symbol")


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


def test_the_file_hash_is_the_old_store_backup_helper():
    assert mod.sha256_of_file is ops_old_store_backup.sha256_of_file


def test_backup_file_name_is_per_table_and_utc_date():
    from datetime import date

    assert mod.backup_file_name("ohlcv_raw", date(2026, 10, 27)) == (
        "tradier_ohlcv_raw_2026-10-27.csv.gz"
    )


# --- manifest --------------------------------------------------------------------------------

_COUNTS = {
    "ohlcv_revision": {"AAA": 2},
    "ohlcv_raw": {"AAA": 5, "BBB": 3},
    "market_data_ohlcv": {"AAA": 4, "BBB": 3},
    "ohlcv_coverage": {},
}


def _manifest() -> dict[str, Any]:
    return {
        "held": ["HLD"],
        "foreign_revisions": 3,
        "request_ledger": {"total": 100, "tradier": 10},
        "tables": [
            {
                "table": table,
                "per_symbol": {s: [n, f"md5-{table}-{s}"] for s, n in counts.items()},
                "file": f"tradier_{table}_2026-10-27.csv.gz",
                "sha256": f"sha-{table}",
            }
            for table, counts in _COUNTS.items()
        ],
    }


def test_rows_and_expected_counts_derive_from_per_symbol():
    manifest = _manifest()
    assert [mod.table_rows(t) for t in manifest["tables"]] == [2, 8, 7, 0]
    assert mod.expected_counts(manifest, ["AAA"]) == {
        "ohlcv_revision": 2,
        "ohlcv_raw": 5,
        "market_data_ohlcv": 4,
        "ohlcv_coverage": 0,
    }


def test_expected_content_holds_only_symbols_with_rows():
    content = mod.expected_content(_manifest(), ["AAA", "BBB"])
    assert content["ohlcv_revision"] == {"AAA": (2, "md5-ohlcv_revision-AAA")}
    assert content["ohlcv_coverage"] == {}
    assert content["ohlcv_raw"]["BBB"] == (3, "md5-ohlcv_raw-BBB")


def test_manifest_symbols_come_from_every_table():
    assert mod.manifest_symbols(_manifest()) == ["AAA", "BBB"]


# --- the manifest check ----------------------------------------------------------------------


def _agreeing(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "live": {t: dict(c) for t, c in _COUNTS.items()},
        "files": {t["table"]: mod.table_rows(t) for t in manifest["tables"]},
        "digests": {t["table"]: t["sha256"] for t in manifest["tables"]},
        "completed": set(),
        "foreign_revisions_live": 3,
        "ledger_live": {"total": 100, "tradier": 10},
    }


def test_verify_passes_when_live_files_and_ledger_agree():
    manifest = _manifest()
    assert mod.verify_problems(manifest, **_agreeing(manifest)) == []


def test_verify_names_a_live_count_mismatch_by_table_and_symbol():
    manifest = _manifest()
    observed = _agreeing(manifest)
    observed["live"]["ohlcv_raw"]["AAA"] = 6
    assert mod.verify_problems(manifest, **observed) == ["ohlcv_raw AAA: live 6 != expected 5"]


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
    observed["files"]["ohlcv_raw"] = 1
    observed["digests"]["ohlcv_raw"] = "other"
    del observed["files"]["ohlcv_coverage"]
    problems = mod.verify_problems(manifest, **observed)
    assert "ohlcv_raw: file rows 1 != manifest 8" in problems
    assert "ohlcv_raw: sha256 of tradier_ohlcv_raw_2026-10-27.csv.gz changed" in problems
    assert "ohlcv_coverage: file tradier_ohlcv_coverage_2026-10-27.csv.gz missing" in problems


def test_verify_expects_zero_live_rows_for_completed_symbols():
    manifest = _manifest()
    observed = _agreeing(manifest)
    observed["completed"] = {"AAA"}
    assert "ohlcv_raw AAA: live 5 != expected 0" in mod.verify_problems(manifest, **observed)
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


def test_verify_requires_the_other_vendor_revision_count_unchanged():
    # T-191-45: the IBKR revision rows under the Tradier loads must not move.
    manifest = _manifest()
    observed = _agreeing(manifest)
    observed["foreign_revisions_live"] = 2
    assert mod.verify_problems(manifest, **observed) == [
        "ohlcv_revision: other-vendor rows under Tradier loads 2 != manifest 3"
    ]


def test_backup_file_reads_recount_only_a_file_whose_hash_changed(tmp_path: Path, monkeypatch):
    manifest = _manifest()
    for entry in manifest["tables"]:
        entry["sha256"] = _gz(tmp_path / entry["file"], b"x\n" * mod.table_rows(entry))
    raw = next(t for t in manifest["tables"] if t["table"] == "ohlcv_raw")
    _gz(tmp_path / raw["file"], b"x\n")  # changed after the dump
    recounted: list[str] = []
    real = mod.count_csv_records
    monkeypatch.setattr(mod, "count_csv_records", lambda p: recounted.append(p.name) or real(p))
    files, digests = mod.read_backup_files(manifest, tmp_path)
    assert recounted == [raw["file"]]
    assert files["ohlcv_raw"] == 1 and files["market_data_ohlcv"] == 7
    assert digests["ohlcv_raw"] != raw["sha256"]


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
        self.isolation_level: Any = None

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def rollback(self) -> None:
        return None

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


def _responder_for(
    manifest: dict[str, Any],
    *,
    skew: int = 0,
    tamper: str | None = None,
    on_delete: Callable[[], None] | None = None,
    live: dict[str, dict[str, int]] | None = None,
):
    """Answers each DELETE with the manifest count of the batch's symbols (plus `skew`), each
    batch digest with the manifest's content (the `tamper` table's md5 changed) and each batch
    count with `live` (default: the manifest's counts)."""
    per = {t["table"]: t["per_symbol"] for t in manifest["tables"]}
    digest_tables = {spec.batch_digest_sql: spec.table for spec in mod.TABLES}
    count_tables = {spec.batch_count_sql: spec.table for spec in mod.TABLES}

    def respond(sql: str, params: Any) -> Any:
        if sql in digest_tables:
            table = digest_tables[sql]
            return [
                (s, per[table][s][0], per[table][s][1] + ("x" if table == tamper else ""))
                for s in params["batch"]
                if s in per[table]
            ]
        if sql in count_tables:
            table = count_tables[sql]
            source = (
                live if live is not None else {t: {s: v[0] for s, v in per[t].items()} for t in per}
            )
            return [(s, source[table][s]) for s in params["batch"] if source[table].get(s)]
        if sql.startswith("DELETE"):
            if on_delete is not None:
                on_delete()
            table = sql.split()[2]
            return sum(per[table].get(s, [0])[0] for s in params["batch"]) + skew
        return 0

    return respond


def _clock() -> Callable[[], float]:
    ticks = iter(range(1000))
    return lambda: float(next(ticks))


# --- one batch -------------------------------------------------------------------------------


def test_delete_batch_checks_content_then_deletes_in_order_in_one_transaction():
    manifest = _manifest()
    conn = _FakeConn(_responder_for(manifest))
    timings = mod.delete_batch(
        conn,
        ["AAA", "BBB"],
        ["HLD"],
        mod.expected_content(manifest, ["AAA", "BBB"]),
        free_bytes=lambda: 10**12,
        clock=_clock(),
    )
    assert conn.statements[0] == mod.DECOMPRESSION_LIMIT_SQL
    assert conn.statements[1:5] == [spec.batch_digest_sql for spec in mod.TABLES]
    assert _deletes(conn) == [spec.delete_sql for spec in mod.TABLES]
    assert conn.commits == 1 and conn.rollbacks == 0
    assert {t: v["rows"] for t, v in timings.items()} == mod.expected_counts(
        manifest, ["AAA", "BBB"]
    )
    for params in conn.params[1:]:
        assert params == {"batch": ["AAA", "BBB"], "held": ["HLD"]}
    assert conn.isolation_level == mod.psycopg.IsolationLevel.READ_COMMITTED


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
    with pytest.raises(mod.DeleteRefused, match="ohlcv_revision deleted 3 rows, manifest 2"):
        mod.delete_batch(
            conn,
            ["AAA"],
            [],
            mod.expected_content(manifest, ["AAA"]),
            free_bytes=lambda: 1,
            clock=_clock(),
        )
    assert conn.commits == 0 and conn.rollbacks == 1


def test_delete_batch_refuses_content_that_differs_and_resets_isolation():
    manifest = _manifest()
    conn = _FakeConn(_responder_for(manifest, tamper="ohlcv_raw"))
    with pytest.raises(mod.DeleteRefused, match="ohlcv_raw content differs .*AAA"):
        mod.delete_batch(
            conn,
            ["AAA"],
            [],
            mod.expected_content(manifest, ["AAA"]),
            free_bytes=lambda: 1,
            clock=_clock(),
        )
    assert _deletes(conn) == [] and conn.rollbacks == 1
    assert conn.isolation_level == mod.psycopg.IsolationLevel.READ_COMMITTED


def test_delete_batch_refuses_a_row_count_change_seen_by_the_digest_read():
    manifest = _manifest()
    conn = _FakeConn(_responder_for(manifest))
    expected = mod.expected_content(manifest, ["AAA"])
    expected["market_data_ohlcv"]["AAA"] = (5, expected["market_data_ohlcv"]["AAA"][1])
    with pytest.raises(mod.DeleteRefused, match="market_data_ohlcv content differs"):
        mod.delete_batch(conn, ["AAA"], [], expected, free_bytes=lambda: 1, clock=_clock())
    assert _deletes(conn) == []


def test_repeatable_read_sets_and_resets_the_isolation_level():
    conn = _FakeConn(lambda sql, params: 0)
    with pytest.raises(RuntimeError):
        with mod.repeatable_read(conn):
            assert conn.isolation_level == mod.psycopg.IsolationLevel.REPEATABLE_READ
            raise RuntimeError("boom")
    assert conn.isolation_level == mod.psycopg.IsolationLevel.READ_COMMITTED
    assert conn.rollbacks == 1


# --- batch run and the disk guard ------------------------------------------------------------


def _state() -> dict[str, Any]:
    return mod.new_state("msha")


def _run(conn: _FakeConn, state: dict[str, Any], path: Path, **kw: Any) -> int:
    args: dict[str, Any] = {
        "batch_symbols": 20,
        "floor_bytes": 1,
        "free_bytes": lambda: 2,
        "clock": _clock(),
    }
    args.update(kw)
    return mod.run_batches(conn, _manifest(), state, path, **args)


def test_the_state_carries_no_unread_fields():
    assert set(_state()) == {
        "manifest_sha256",
        "completed",
        "in_flight",
        "batches",
        "tsv_written",
        "aborted",
    }


def test_run_batches_aborts_before_any_delete_when_disk_is_below_the_floor(tmp_path: Path):
    conn = _FakeConn(_responder_for(_manifest()))
    path = tmp_path / "state.json"
    code = _run(
        conn,
        _state(),
        path,
        batch_symbols=1,
        floor_bytes=200 * 2**30,
        free_bytes=lambda: 199 * 2**30,
    )
    assert code == mod.EXIT_DISK_ABORT
    assert _deletes(conn) == []
    saved = json.loads(path.read_text())
    assert saved["aborted"]["reason"] == "free disk below floor"
    assert saved["aborted"]["free_bytes"] == 199 * 2**30
    assert saved["completed"] == []


def test_run_batches_checks_disk_before_every_batch_and_stops_mid_run(tmp_path: Path):
    conn = _FakeConn(_responder_for(_manifest()))
    path = tmp_path / "state.json"
    # batch 1's guard reads 500 GB, its per-table reads (two per table) see plenty; batch 2's
    # guard reads 100 GB and aborts.
    readings = iter([500 * 2**30] + [400 * 2**30] * 8 + [100 * 2**30])
    code = _run(
        conn,
        _state(),
        path,
        batch_symbols=1,
        floor_bytes=200 * 2**30,
        free_bytes=lambda: next(readings),
    )
    assert code == mod.EXIT_DISK_ABORT
    saved = json.loads(path.read_text())
    assert saved["completed"] == ["AAA"]
    assert saved["aborted"]["next_batch"] == ["BBB"]
    assert all("BBB" not in p["batch"] for p in conn.params if p and "batch" in p)


def test_run_batches_completes_and_skips_completed_symbols(tmp_path: Path):
    conn = _FakeConn(_responder_for(_manifest()))
    state = _state()
    state["completed"] = ["AAA"]
    assert _run(conn, state, tmp_path / "state.json") == 0
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["completed"] == ["AAA", "BBB"]
    assert {p["batch"][0] for p in conn.params if p and "batch" in p} == {"BBB"}


def test_a_batch_is_recorded_in_flight_before_its_transaction(tmp_path: Path):
    path = tmp_path / "state.json"
    seen: list[Any] = []
    conn = _FakeConn(
        _responder_for(
            _manifest(), on_delete=lambda: seen.append(json.loads(path.read_text())["in_flight"])
        )
    )
    assert _run(conn, _state(), path) == 0
    assert seen and all(f["symbols"] == ["AAA", "BBB"] and f["trial"] is False for f in seen)
    assert json.loads(path.read_text())["in_flight"] is None


def test_a_refused_batch_clears_in_flight_and_exits_refused(tmp_path: Path):
    conn = _FakeConn(_responder_for(_manifest(), tamper="ohlcv_raw"))
    path = tmp_path / "state.json"
    assert _run(conn, _state(), path) == mod.EXIT_REFUSED
    saved = json.loads(path.read_text())
    assert saved["in_flight"] is None and saved["completed"] == []
    assert "content differs" in saved["aborted"]["reason"]


def test_run_batches_refuses_an_unsettled_in_flight_batch(tmp_path: Path):
    state = _state()
    state["in_flight"] = {"symbols": ["AAA"], "trial": False}
    with pytest.raises(ValueError, match="in-flight"):
        _run(_FakeConn(lambda sql, params: 0), state, tmp_path / "state.json")


# --- in-flight settlement --------------------------------------------------------------------


def test_settle_reads_committed_rolled_back_and_partial():
    manifest = _manifest()
    live = {t: {} for t in _COUNTS}
    for table, counts in _COUNTS.items():
        if "BBB" in counts:
            live[table]["BBB"] = counts["BBB"]  # BBB untouched: rolled back; AAA gone: committed
    settlement = mod.settle(manifest, ["AAA", "BBB"], live)
    assert settlement.committed == ["AAA"] and settlement.rolled_back == ["BBB"]
    partial = {"ohlcv_revision": {}, "ohlcv_raw": {"AAA": 5}, "market_data_ohlcv": {"AAA": 4}}
    assert mod.settle(manifest, ["AAA"], partial).partial == ["AAA"]


def _flight(symbols: list[str], *, trial: bool) -> dict[str, Any]:
    return {
        "symbols": symbols,
        "trial": trial,
        "free_bytes_before": 1000,
        "started": "2026-10-27T00:00:00+00:00",
    }


def test_settle_in_flight_marks_committed_done_and_saves(tmp_path: Path):
    manifest = _manifest()
    state = _state()
    state["in_flight"] = _flight(["AAA", "BBB"], trial=False)
    live = {t: {"BBB": c["BBB"]} if "BBB" in c else {} for t, c in _COUNTS.items()}
    conn = _FakeConn(_responder_for(manifest, live=live))
    path = tmp_path / "state.json"
    refusal = mod._settle_in_flight(conn, manifest, state, path, tmp_path, lambda: 900, "msha")
    assert refusal is None
    saved = json.loads(path.read_text())
    assert saved["completed"] == ["AAA"] and saved["in_flight"] is None
    assert list(tmp_path.glob("tradier_delete_trial_*.json")) == []


def test_settle_in_flight_refuses_a_partial_symbol_and_keeps_the_flight(tmp_path: Path):
    manifest = _manifest()
    state = _state()
    state["in_flight"] = _flight(["AAA"], trial=False)
    live = {t: {} for t in _COUNTS}
    live["ohlcv_raw"]["AAA"] = 5  # raw still there, the rest gone
    conn = _FakeConn(_responder_for(manifest, live=live))
    refusal = mod._settle_in_flight(
        conn, manifest, state, tmp_path / "state.json", tmp_path, lambda: 900, "msha"
    )
    assert refusal is not None and "AAA" in refusal
    assert state["in_flight"]["symbols"] == ["AAA"] and state["completed"] == []


def test_a_settled_committed_trial_gets_a_recovered_report(tmp_path: Path):
    manifest = _manifest()
    state = _state()
    state["in_flight"] = _flight(["AAA"], trial=True)
    conn = _FakeConn(_responder_for(manifest, live={t: {} for t in _COUNTS}))
    assert (
        mod._settle_in_flight(
            conn, manifest, state, tmp_path / "state.json", tmp_path, lambda: 900, "msha"
        )
        is None
    )
    (report_path,) = tmp_path.glob("tradier_delete_trial_AAA_*.json")
    report = json.loads(report_path.read_text())
    assert report["recovered"] is True and report["rows_total"] == 11
    assert report["disk_delta_bytes"] == 100 and report["tables"] is None


def test_the_trial_report_builder_sums_rows_and_disk():
    report = mod._trial_report(
        "AAA",
        "msha",
        recovered=False,
        started="s",
        tables={"ohlcv_raw": {"rows": 3, "seconds": 1.5, "disk_delta_bytes": 7}},
        rows_total=3,
        free_before=100,
        free_after=40,
    )
    assert report["disk_delta_bytes"] == 60 and report["seconds_total"] == 1.5
    assert report["manifest_sha256"] == "msha" and report["recovered"] is False


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


def test_trial_gate_refuses_a_recovered_trial_report():
    report = {"rows_total": 100, "disk_delta_bytes": 10, "recovered": True}
    refusal = mod.trial_refusal(report, 10, free_bytes=10**12, floor_bytes=1)
    assert refusal is not None and "fresh trial" in refusal


# --- the apply path --------------------------------------------------------------------------


def _apply(tmp_path: Path, **overrides: Any) -> tuple[int, _FakeConn]:
    manifest = _manifest()
    conn = _FakeConn(_responder_for(manifest))
    kwargs: dict[str, Any] = {
        "conn": conn,
        "manifest": manifest,
        "state": _state(),
        "state_path": tmp_path / "state.json",
        "verify": lambda: [],
        "trial_report": {"rows_total": 10, "disk_delta_bytes": 10},
        "write_tsv": lambda: None,
        "batch_symbols": 20,
        "floor_bytes": 1,
        "free_bytes": lambda: 10**12,
        "clock": _clock(),
    }
    kwargs.update(overrides)
    return mod.apply_delete(**kwargs), conn


def test_apply_refuses_when_the_manifest_does_not_verify(tmp_path: Path):
    code, conn = _apply(tmp_path, verify=lambda: ["ohlcv_raw AAA: live 6 != expected 5"])
    assert code == mod.EXIT_REFUSED and _deletes(conn) == []


def test_apply_refuses_without_a_trial(tmp_path: Path):
    code, conn = _apply(tmp_path, trial_report=None)
    assert code == mod.EXIT_REFUSED and _deletes(conn) == []


def test_apply_writes_the_first_bar_tsv_before_the_first_delete(tmp_path: Path):
    seen: list[int] = []
    holder: dict[str, _FakeConn] = {}
    conn = _FakeConn(_responder_for(_manifest()))
    holder["conn"] = conn
    code, _ = _apply(
        tmp_path, conn=conn, write_tsv=lambda: seen.append(len(_deletes(holder["conn"])))
    )
    assert code == 0 and seen == [0]
    assert len(_deletes(conn)) == len(mod.TABLES)  # one batch of both symbols


def test_apply_does_not_rewrite_the_tsv_on_a_resume(tmp_path: Path):
    calls: list[int] = []
    state = _state()
    state["tsv_written"] = True
    code, _ = _apply(tmp_path, state=state, write_tsv=lambda: calls.append(1))
    assert code == 0 and calls == []


def test_ensure_tsv_writes_once_across_trial_and_batch(tmp_path: Path):
    calls: list[int] = []
    state = _state()
    mod.ensure_tsv(state, tmp_path / "state.json", lambda: calls.append(1))
    mod.ensure_tsv(state, tmp_path / "state.json", lambda: calls.append(1))
    assert calls == [1]
    assert json.loads((tmp_path / "state.json").read_text())["tsv_written"] is True


def test_the_trial_writes_the_tsv_before_its_delete():
    source = Path(mod.__file__).read_text()
    trial = source[source.index("def run_trial(") : source.index("def run_delete(")]
    assert trial.index("ensure_tsv(") < trial.index("_run_one_batch(")


# --- the mode entry points -------------------------------------------------------------------


def _no_runtime(tmp_path: Path) -> Any:
    def _no_db() -> Any:
        raise AssertionError("refused before any database access")

    return mod.Runtime(connect=_no_db, read_apr=_no_db, measure=_no_db, tsv_path=tmp_path / "t")


def _argv(tmp_path: Path, *mode: str) -> list[str]:
    return [*mode, "--backup-dir", str(tmp_path), "--log-dir", str(tmp_path)]


@pytest.mark.parametrize(
    "mode", [["--dump", "--apply"], ["--trial", "AAA", "--apply"], ["--delete", "--apply"]]
)
def test_every_write_mode_refuses_while_the_state_lock_is_held(tmp_path: Path, mode: list[str]):
    lock_path = tmp_path / "tradier_delete_state.json.lock"
    with lock_path.open("a") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert mod.main(_argv(tmp_path, *mode), _no_runtime(tmp_path)) == mod.EXIT_REFUSED


def test_the_state_lock_is_released_after_a_mode(tmp_path: Path):
    with mod.state_lock(tmp_path) as acquired:
        assert acquired
        with mod.state_lock(tmp_path) as second:
            assert not second
    with mod.state_lock(tmp_path) as again:
        assert again


def test_delete_refuses_without_a_manifest_before_any_database_access(tmp_path: Path):
    assert mod.main(_argv(tmp_path, "--delete", "--apply"), _no_runtime(tmp_path)) == 2


def test_delete_refuses_a_state_bound_to_another_manifest(tmp_path: Path):
    (tmp_path / "tradier_delete_manifest.json").write_text(json.dumps(_manifest()))
    mod.save_state(mod.new_state("other"), tmp_path / "tradier_delete_state.json")
    assert mod.main(_argv(tmp_path, "--delete", "--apply"), _no_runtime(tmp_path)) == 2


def test_dump_refuses_when_any_backup_file_exists(tmp_path: Path):
    (tmp_path / "tradier_ohlcv_raw_2026-10-01.csv.gz").write_bytes(b"")
    assert mod.main(_argv(tmp_path, "--dump", "--apply"), _no_runtime(tmp_path)) == 2


def test_the_disk_path_defaults_to_the_apr_value(tmp_path: Path):
    args = mod.build_parser().parse_args(_argv(tmp_path, "--verify"))
    assert args.disk_path is None
    assert mod.DISK_PATH_KEY == "infra.compressed_hypertable_write_session.disk_path"
    assert mod.disk_path_for(args, "/apr/path") == Path("/apr/path")
    args.disk_path = tmp_path
    assert mod.disk_path_for(args, "/apr/path") == tmp_path


def test_sessions_lift_the_statement_timeout():
    source = Path(mod.__file__).read_text()
    connect = source[source.index("def _connect(") : source.index("async def _read_apr_async(")]
    assert "statement_timeout=0" in connect and "timezone=UTC" in connect


class _SchemaConn:
    def __init__(self, schemas: list[str]) -> None:
        self.schemas = schemas
        self.closed = False

    def execute(self, sql: str) -> Any:
        assert sql == "SELECT current_schemas(false)"
        return self

    def fetchone(self) -> tuple[list[str]]:
        return (self.schemas,)

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def test_the_production_connection_refuses_a_non_public_schema_list(monkeypatch):
    conn = _SchemaConn(["zz_scratch"])
    monkeypatch.setattr(mod.psycopg, "connect", lambda *a, **k: conn)
    with pytest.raises(SystemExit, match="public"):
        mod._connect()
    assert conn.closed
    ok = _SchemaConn(["public"])
    monkeypatch.setattr(mod.psycopg, "connect", lambda *a, **k: ok)
    assert mod._connect() is ok


def test_verify_success_message_says_counts_not_content():
    source = Path(mod.__file__).read_text()
    assert "backup matches live" not in source
    assert "counts match" in source


# --- first-bar change record ----------------------------------------------------------------


def test_first_bar_tsv_lists_every_name_and_marks_the_changes():
    def m(symbol: str, n: int, r: int, cur: str, after: str | None) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "n_tradier": n,
            "n_residue": r,
            "first_bar_current": cur,
            "first_bar_after": after,
        }

    measures = [
        m("BBB", 5, 0, "2010-01-04", "2010-01-04"),
        m("AAA", 9, 3, "2005-01-03", "2007-06-01"),
        m("CCC", 2, 2, "2020-01-02", None),
        m("HLD", 2, 2, "2020-01-02", None),
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


# --- dry run and held names ----------------------------------------------------------------


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
