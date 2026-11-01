"""ops_tradier_restore's parsing and manifest cross-check (todo 574 restore, 2026-11-01).

No database: the restore's DB writes go through persist_chunk_atomically, which has its own
tests; what is tested here is what the restore script itself owns — grouping the backup rows
by (served_at, request_id) with types intact, and the manifest cross-check that refuses a
file whose row count drifted."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

from scripts.ops.bars import ops_tradier_restore as restore

_ROWS = [
    (
        "2023-12-19 00:00:00+00",
        "A",
        "1d",
        "tradier",
        "consolidated",
        "138.51",
        "139.89",
        "137.32",
        "139.79",
        "1523339",
        "2026-10-03 20:08:57.686633+00",
        "6bd29049-6138-4fa2-9b01-a9155327cf7c",
        "",
    ),
    (
        "2023-12-20 00:00:00+00",
        "A",
        "1d",
        "tradier",
        "consolidated",
        "139.79",
        "141.24",
        "138.14",
        "138.18",
        "2121066",
        "2026-10-03 20:08:57.686633+00",
        "6bd29049-6138-4fa2-9b01-a9155327cf7c",
        "",
    ),
    (
        "2020-01-02 00:00:00+00",
        "H",
        "1d",
        "tradier",
        "consolidated",
        "1",
        "2",
        "0.5",
        "1.5",
        "10",
        "2026-10-02 21:00:00+00",
        "0bb0fb0be2081ac9dc4abd98ae4d89de".ljust(36, "0"),
        "",
    ),
]


def _write_backup(tmp_path: Path, rows) -> Path:
    path = tmp_path / "tradier_ohlcv_raw.csv.gz"
    with gzip.open(path, "wt", newline="") as f:
        for row in rows:
            f.write(",".join(row) + "\n")
    return path


def test_groups_key_on_served_at_and_request_id_with_types(tmp_path, monkeypatch):
    path = _write_backup(tmp_path, _ROWS)
    monkeypatch.setattr(restore, "BACKUP", path)
    groups = restore._groups()
    # two groups: the two A rows share served_at and request_id; the H row is its own
    assert len(groups) == 2
    rows = groups[(datetime(2026, 10, 3, 20, 8, 57, 686633, tzinfo=UTC), _ROWS[0][11])]
    assert [r.symbol for r in rows] == ["A", "A"]
    assert rows[0].close == 139.79 and rows[0].volume == 1523339
    assert rows[0].timestamp == datetime(2023, 12, 19, tzinfo=UTC)
    other = next(
        k
        for k in groups
        if k != (datetime(2026, 10, 3, 20, 8, 57, 686633, tzinfo=UTC), _ROWS[0][11])
    )
    assert groups[other][0].symbol == "H" and groups[other][0].volume == 10


def test_a_missing_volume_restores_as_none(tmp_path, monkeypatch):
    row = (*_ROWS[0][:9], "", *_ROWS[0][10:])  # volume empty, served_at and id intact
    path = _write_backup(tmp_path, [row])
    monkeypatch.setattr(restore, "BACKUP", path)
    groups = restore._groups()
    (records,) = groups.values()
    assert records[0].volume is None


def test_the_manifest_cross_check_refuses_a_drifted_file(tmp_path, monkeypatch, capsys):
    path = _write_backup(tmp_path, _ROWS)  # 3 rows in the file
    manifest = {
        "tables": [
            {
                "table": "ohlcv_raw",
                "per_symbol": {"A": [2, "sha"], "H": [2, "sha"]},  # 4 rows: one is missing
            }
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(restore, "BACKUP", path)
    monkeypatch.setattr(restore, "MANIFEST", manifest_path)
    assert restore.main([]) == 1  # the file's 3 rows drift from the manifest's 4
    assert "PROBLEM" in capsys.readouterr().out
