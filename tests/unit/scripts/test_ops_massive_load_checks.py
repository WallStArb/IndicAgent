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
