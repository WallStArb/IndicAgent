"""ops_massive_load_checks: runner plumbing (era parsing, nightly windows, part reuse, archive read)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from scripts.ops.bars import ops_massive_load_checks as runner
from src.intelligence.bars import massive_load_checks as lc


def test_parse_eras() -> None:
    assert runner.parse_eras("2010") == (2010,)
    assert runner.parse_eras("2003-2005,2010") == (2003, 2004, 2005, 2010)


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [(4, 30, False), (4, 40, True), (4, 55, False), (5, 20, True), (6, 29, True), (6, 30, False)],
)
def test_nightly_window(hour: int, minute: int, expected: bool) -> None:
    assert runner.in_nightly_window(datetime(2026, 11, 12, hour, minute, tzinfo=UTC)) is expected


def _cfg(tmp_path: Path, **over: object) -> runner.Config:
    base = {
        "out": tmp_path,
        "data_dir": tmp_path,
        "seed": 1,
        "days_per_era": 2,
        "eras": (2010,),
        "force": False,
        "throttle_s": 0.0,
    }
    return runner.Config(**{**base, **over})  # type: ignore[arg-type]


def test_part_reuse_requires_same_sample_key(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    runner.write_json(runner.part_path(cfg, "session", 2010), {"key": runner.sample_key(cfg)})
    assert runner.load_part(cfg, "session", 2010, runner.sample_key(cfg)) is not None
    other = _cfg(tmp_path, days_per_era=3)
    assert runner.load_part(other, "session", 2010, runner.sample_key(other)) is None
    forced = _cfg(tmp_path, force=True)
    assert runner.load_part(forced, "session", 2010, runner.sample_key(forced)) is None


def test_load_archive_last_manifest_row_wins_and_hashes_inputs(tmp_path: Path) -> None:
    mdir = tmp_path / "manifest"
    mdir.mkdir()
    old = {
        "dataset": runner.DAY,
        "key": "x/day_aggs_v1/2024/01/2024-01-02.csv.gz",
        "sha256": "a" * 64,
    }
    new = {**old, "sha256": "b" * 64}
    (mdir / "manifest.jsonl").write_text(json.dumps(old) + "\n" + json.dumps(new) + "\n")
    line = "x/day_aggs_v1/2024/01/2024-01-02.csv.gz\t2024-01-02T22:00:00.000Z\t&quot;e&quot;\t10\n"
    (mdir / "servetimes_day_aggs_v1.jsonl").write_text(line)
    (mdir / "servetimes_minute_aggs_v1.jsonl").write_text("")
    archive = runner.load_archive(tmp_path)
    assert archive.manifest[runner.DAY][date(2024, 1, 2)]["sha256"] == "b" * 64
    assert len(archive.inputs) == 3 and all(len(h) == 64 for h in archive.inputs.values())


def test_draw_days_without_held_sessions_is_vacuous(tmp_path: Path) -> None:
    archive = runner.Archive(
        {runner.MINUTE: {}, runner.DAY: {}}, {runner.MINUTE: {}, runner.DAY: {}}, {}
    )
    with pytest.raises(lc.VacuousCheckError):
        runner.draw_days(_cfg(tmp_path), archive, [date(2010, 1, 4)])


def test_frozen_splits_load_from_the_frozen_file_only(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    (frozen / "frozen.json").write_text(
        json.dumps(
            {
                "freeze_version": runner.FREEZE_VERSION,
                "sha256": {},
                "horizon": "2026-11-12T12:00:00+00:00",
            }
        )
    )
    (frozen / "corporate_actions.csv").write_text(
        "symbol,effective_date,factor,recorded_at,inferred_by,rows_file,market_fact,"
        "unadjusted_routes\n"
        "AAPL,2014-06-06,7.0,2026-10-01T00:00:00+00:00,massive_reference,False,True,\n"
        "AAPL,2020-08-28,4.0,2026-10-01T00:00:00+00:00,calendar_audit,True,False,\n"
        "AAPL,2030-01-01,2.0,2026-10-01T00:00:00+00:00,massive_reference,False,True,\n"
    )
    (frozen / "ticker_spans.csv").write_text(
        "symbol,ticker,valid_from,valid_to\nAAPL,AAPL,2003-09-10,\n"
    )
    splits = runner.load_frozen(cfg).splits
    # the operator route correction and the not-yet-executed split never rescale
    assert [(s.effective_date, s.factor) for s in splits["AAPL"]] == [(date(2014, 6, 6), 7.0)]


class _FakeCursor:
    def __init__(self, tables: dict[str, list[tuple]]) -> None:
        self._tables = tables
        self._rows: list[tuple] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: object = None) -> None:
        self._rows = self._tables["ca" if "corporate_action_current" in sql else "span"]

    def fetchall(self) -> list[tuple]:
        return self._rows


class _FakeConn:
    def __init__(self) -> None:
        recorded = datetime(2026, 10, 1, tzinfo=UTC)
        self.tables = {
            "ca": [("AAPL", date(2014, 6, 6), 7.0, recorded, "massive_reference", False, None)],
            "span": [("AAPL", "AAPL", date(2003, 9, 10), None)],
        }

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.tables)


def test_freeze_writes_identical_inputs_and_hashes_the_horizon_in_the_record(
    tmp_path: Path,
) -> None:
    """Round 5 finding 7: two freezes of one state write identical CSVs and hashes; the splits
    horizon (the freeze time) lives inside the frozen record that part keys carry, with the
    unhashed frozen_at.txt as a note only."""
    first, second = tmp_path / "a", tmp_path / "b"
    for out in (first, second):
        runner.freeze_inputs(_cfg(out), _FakeConn())
    for name in ("corporate_actions.csv", "ticker_spans.csv"):
        assert (first / "frozen" / name).read_bytes() == (second / "frozen" / name).read_bytes()
    record = json.loads((first / "frozen" / "frozen.json").read_text())
    assert record["sha256"] == json.loads((second / "frozen" / "frozen.json").read_text())["sha256"]
    assert (first / "frozen" / "frozen_at.txt").read_text().strip() == record["horizon"]
    assert runner.frozen_hashes(_cfg(first))["horizon"] == record["horizon"]
    # a reload verifies the recorded hashes and never touches the database again
    again = runner.freeze_inputs(_cfg(first), None)  # type: ignore[arg-type]
    assert again["n_corporate_actions"] == 1
    # the horizon read for the splits is the recorded one, never the unhashed note
    (first / "frozen" / "frozen_at.txt").write_text("1999-01-01T00:00:00+00:00\n")
    assert runner.frozen_hashes(_cfg(first))["horizon"] == record["horizon"]
    (first / "frozen" / "corporate_actions.csv").write_text("tampered")
    with pytest.raises(RuntimeError):
        runner.freeze_inputs(_cfg(first), None)  # type: ignore[arg-type]


def test_the_runner_session_is_read_only_on_the_server() -> None:
    """Round 5 finding 6: psycopg ignores conn.read_only in autocommit mode, so the runner sets
    the server-side default; a write must be refused by the database itself."""
    try:
        conn = runner.connect_read_only()
    except Exception as error:  # no database in this environment
        pytest.skip(f"database unavailable: {error}")
    with conn:
        assert conn.execute("SHOW transaction_read_only").fetchone() == ("on",)
        with pytest.raises(Exception, match="read-only"):
            conn.execute("CREATE TEMP TABLE load_check_write_probe (i int)")


def test_the_runner_source_issues_no_write_statement() -> None:
    import re

    source = Path(runner.__file__).read_text()
    assert not re.search(
        r"\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|TRUNCATE|DROP\s)", source
    )


def test_part_keys_carry_the_inputs_and_the_raw_fingerprint(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    base = runner.sample_key(cfg, {"manifest.jsonl": "aa"}, {"massive|sip_flat|1d": 10})
    assert runner.LOGIC_VERSION.endswith("r5f")  # no round 4 part is ever reused
    assert base["archive_inputs"] == {"manifest.jsonl": "aa"}
    runner.write_json(runner.part_path(cfg, "volume_bands", 2010), {"key": base})
    assert runner.load_part(cfg, "volume_bands", 2010, base) is not None
    reloaded = runner.sample_key(cfg, {"manifest.jsonl": "aa"}, {"massive|sip_flat|1d": 11})
    assert runner.load_part(cfg, "volume_bands", 2010, reloaded) is None  # raw rows changed
    changed = runner.sample_key(cfg, {"manifest.jsonl": "bb"}, {"massive|sip_flat|1d": 10})
    assert runner.load_part(cfg, "volume_bands", 2010, changed) is None  # archive changed


def test_malformed_disputed_rows_fail_the_run(tmp_path: Path) -> None:
    path = tmp_path / "disputed.csv"
    path.write_text("symbol,date\nAAPL,2010-03-01\nMSFT,not-a-date\n,\n")
    with pytest.raises(ValueError, match="2 malformed"):
        runner.run_disputed_windows(_cfg(tmp_path), None, path, {})  # type: ignore[arg-type]


def test_a_ledger_row_without_a_median_writes_no_witness_and_no_fabricated_zero() -> None:
    row = runner.ledger_row("A", 2010, "1d", "price_agreement_1d", None, [], {}, "s")
    assert row["verdict"] == "unresolved" and row["witnesses"] == "none available"


def _live_url() -> str | None:
    """The database the SQL probe runs against: LOAD_CHECKS_SQL_PROBE_URL (the real database), else
    the pytest database."""
    import os

    return os.environ.get("LOAD_CHECKS_SQL_PROBE_URL")


def test_every_sql_statement_the_runner_issues_executes_against_the_database() -> None:
    """Round 5 second review, finding 1: a FakeConn hid `text ->> unknown` in the freeze SQL. Every
    statement is EXPLAINed (parsed, analysed and planned) through connect_read_only(), and every
    ``execute`` call in the runner names a statement of the registry."""
    import re

    source = Path(runner.__file__).read_text()
    called = set(re.findall(r"execute\(\s*(_[A-Z_]+SQL)\b", source))
    assert called and called <= set(runner.SQL_STATEMENTS), called - set(runner.SQL_STATEMENTS)
    try:
        conn = runner.connect_read_only(_live_url())
    except Exception as error:
        pytest.skip(f"database unavailable: {error}")
    with conn:
        for name, (sql, params) in runner.SQL_STATEMENTS.items():
            try:
                conn.execute("EXPLAIN " + sql, params or None)
            except Exception as error:
                if "does not exist" in str(error) and _live_url() is None:
                    pytest.skip(f"{name}: the pytest database lacks the table ({error})")
                raise AssertionError(f"{name} does not execute: {error}") from error


def test_a_frozen_record_of_another_version_is_refused(tmp_path: Path) -> None:
    runner.freeze_inputs(_cfg(tmp_path), _FakeConn())
    path = tmp_path / "frozen" / "frozen.json"
    record = json.loads(path.read_text())
    assert record["freeze_version"] == runner.FREEZE_VERSION
    record["freeze_version"] = runner.FREEZE_VERSION - 1
    path.write_text(json.dumps(record))
    with pytest.raises(RuntimeError, match="freeze version"):
        runner.freeze_inputs(_cfg(tmp_path), None)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="freeze version"):
        runner.frozen_hashes(_cfg(tmp_path))


def test_stage_c_refuses_stage_a_and_b_files_without_the_current_provenance(
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    inputs = {"manifest.jsonl": "aa"}
    runner.freeze_inputs(cfg, _FakeConn())
    for name, with_frozen in (("stageA_systemic.json", False), ("stageB_systemic.json", True)):
        runner.write_json(
            tmp_path / name,
            {
                "provenance": runner.provenance(cfg, inputs, frozen=with_frozen),
                "stop_eras": {"2010": ["session"]},
            },
        )
    assert runner.systemic_stop_eras(cfg, inputs) == {2010: "session"}
    with pytest.raises(RuntimeError, match="archive_inputs"):  # the archive changed
        runner.systemic_stop_eras(cfg, {"manifest.jsonl": "bb"})
    wider = runner.Config(tmp_path, tmp_path, cfg.seed, cfg.days_per_era, (2010, 2011), False, 0.0)
    with pytest.raises(RuntimeError, match="eras"):  # an era the file does not cover
        runner.systemic_stop_eras(wider, inputs)
    path = tmp_path / "stageB_systemic.json"
    record = json.loads(path.read_text())
    record["provenance"]["logic"] = "old"
    path.write_text(json.dumps(record))
    with pytest.raises(RuntimeError, match="logic"):
        runner.systemic_stop_eras(cfg, inputs)


def test_the_session_id_is_required() -> None:
    with pytest.raises(SystemExit):
        runner.main(["--stages", "A"])


def test_split_tapes_come_from_one_batch_query() -> None:
    from datetime import UTC, datetime

    calls: list[tuple] = []

    class Cursor:
        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def execute(self, sql: str, params: object = None) -> None:
            calls.append((sql, params))

        def fetchall(self) -> list[tuple]:
            eff = date(2020, 8, 28)
            return [
                ("AAPL", eff, datetime(2020, 8, 28, 4, tzinfo=UTC), 500.0),
                ("AAPL", eff, datetime(2020, 8, 31, 4, tzinfo=UTC), 129.0),
                ("MSFT", date(2020, 1, 2), datetime(2020, 1, 3, 5, tzinfo=UTC), 10.0),
            ]

    class Conn:
        def cursor(self) -> Cursor:
            return Cursor()

    out = runner.fetch_split_tapes(
        Conn(), [("AAPL", date(2020, 8, 28)), ("MSFT", date(2020, 1, 2))]  # type: ignore[arg-type]
    )
    assert len(calls) == 1  # one query for every (name, split) of the batch
    assert out == {("AAPL", date(2020, 8, 28)): [500.0, 129.0]}  # MSFT has no 'before' side
