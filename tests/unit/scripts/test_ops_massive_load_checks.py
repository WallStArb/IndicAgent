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
    (frozen / "frozen_at.txt").write_text("2026-11-12T12:00:00+00:00\n")
    (frozen / "corporate_actions.csv").write_text(
        "symbol,effective_date,factor,recorded_at,inferred_by,rows_file,market_fact\n"
        "AAPL,2014-06-06,7.0,2026-10-01T00:00:00+00:00,massive_reference,False,True\n"
        "AAPL,2020-08-28,4.0,2026-10-01T00:00:00+00:00,calendar_audit,True,False\n"
        "AAPL,2030-01-01,2.0,2026-10-01T00:00:00+00:00,massive_reference,False,True\n"
    )
    splits = runner.load_frozen_splits(cfg)
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
            "ca": [("AAPL", date(2014, 6, 6), 7.0, recorded, "massive_reference", False)],
            "span": [("AAPL", "AAPL", date(2003, 9, 10), None)],
        }

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.tables)


def test_freeze_is_byte_identical_across_runs_and_keeps_the_timestamp_beside(
    tmp_path: Path,
) -> None:
    """R5: the freeze time lives beside the hashed content, so two freezes of one state agree."""
    first, second = tmp_path / "a", tmp_path / "b"
    for out in (first, second):
        runner.freeze_inputs(_cfg(out), _FakeConn())
    names = ("frozen.json", "corporate_actions.csv", "ticker_spans.csv")
    for name in names:
        assert (first / "frozen" / name).read_bytes() == (second / "frozen" / name).read_bytes()
    assert "frozen_at" not in (first / "frozen" / "frozen.json").read_text()
    assert (first / "frozen" / "frozen_at.txt").exists()
    # a reload verifies the recorded hashes and never touches the database again
    again = runner.freeze_inputs(_cfg(first), None)  # type: ignore[arg-type]
    assert again["n_corporate_actions"] == 1
    (first / "frozen" / "corporate_actions.csv").write_text("tampered")
    with pytest.raises(RuntimeError):
        runner.freeze_inputs(_cfg(first), None)  # type: ignore[arg-type]


def test_non_split_csv_reads_symbol_with_optional_era(tmp_path: Path) -> None:
    path = tmp_path / "ns.csv"
    path.write_text("symbol,era\nBDX,2010\nEXC,\n")
    assert runner.read_non_split_csv(path) == {("BDX", 2010), ("EXC", None)}
    assert runner.read_non_split_csv(None) == set()
