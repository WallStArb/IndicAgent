"""Unit tests for the old-store COPY backup script (phase 191 plan 16).

Covers the pure parts on in-memory fixtures: year-slice arithmetic, gzip row counting,
sha256, the disk-margin refusal, the --verify mismatch path (a slice that disagrees
with the manifest is named in the failure) and the --verify-files retention check (the
same file half with no database anywhere). No database anywhere in this file.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from scripts.ops.bars import ops_old_store_backup as mod


def test_year_slices_are_half_open_and_consecutive():
    slices = mod.year_slices(1999, 2001)
    assert [(s.year, s.lo, s.hi) for s in slices] == [
        (1999, date(1999, 1, 1), date(2000, 1, 1)),
        (2000, date(2000, 1, 1), date(2001, 1, 1)),
        (2001, date(2001, 1, 1), date(2002, 1, 1)),
    ]


def test_slice_select_reads_one_table_within_bounds():
    sql = mod.slice_select_sql(mod.TABLES[0], date(2020, 1, 1), date(2021, 1, 1))
    assert sql == (
        "SELECT * FROM ohlcv_observation WHERE bar_date >= '2020-01-01' "
        "AND bar_date < '2021-01-01'"
    )


def test_slice_select_quotes_the_archive_timestamp_column():
    sql = mod.slice_select_sql(mod.TABLES[1], date(2020, 1, 1), date(2021, 1, 1))
    assert '"timestamp"' in sql and "ohlcv_intraday_raw_archive" in sql


def test_count_rows_in_gzip_counts_csv_rows(tmp_path: Path):
    path = tmp_path / "slice.csv.gz"
    body = b"a,b,c\n1,2,3\n4,5,6\n"
    path.write_bytes(gzip.compress(body))
    assert mod.count_rows_in_file(path) == 3


def test_count_rows_in_gzip_empty_file_is_zero_rows(tmp_path: Path):
    path = tmp_path / "empty.csv.gz"
    path.write_bytes(gzip.compress(b""))
    assert mod.count_rows_in_file(path) == 0


def test_count_rows_in_gzip_refuses_a_file_without_final_newline(tmp_path: Path):
    path = tmp_path / "partial.csv.gz"
    path.write_bytes(gzip.compress(b"a,b\n1,2"))
    with pytest.raises(ValueError, match="final newline"):
        mod.count_rows_in_file(path)


def test_sha256_of_file_matches_hashlib(tmp_path: Path):
    path = tmp_path / "x.bin"
    path.write_bytes(b"backup bytes")
    assert mod.sha256_of_file(path) == hashlib.sha256(b"backup bytes").hexdigest()


def test_manifest_totals_sum_the_file_rows():
    manifest = {
        "tables": [
            {
                "table": "t1",
                "files": [{"rows": 2}, {"rows": 3}],
            },
            {
                "table": "t2",
                "files": [{"rows": 7}],
            },
        ]
    }
    assert mod.manifest_table_totals(manifest) == {"t1": 5, "t2": 7}


def test_verify_slices_passes_when_live_and_files_agree():
    manifest = {
        "tables": [
            {
                "table": "t1",
                "files": [
                    {"year": 2020, "file": "t1_2020.csv.gz", "rows": 4, "sha256": "x"},
                    {"year": 2021, "file": "t1_2021.csv.gz", "rows": 0, "sha256": "y"},
                ],
            }
        ]
    }
    live = {("t1", 2020): 4, ("t1", 2021): 0}
    files = {("t1", 2020): 4, ("t1", 2021): 0}
    digests = {("t1", 2020): "x", ("t1", 2021): "y"}
    assert mod.verify_slices(manifest, live, files, digests) == []


def test_verify_slices_names_every_mismatching_slice():
    manifest = {
        "tables": [
            {
                "table": "t1",
                "files": [
                    {"year": 2020, "file": "t1_2020.csv.gz", "rows": 4, "sha256": "x"},
                    {"year": 2021, "file": "t1_2021.csv.gz", "rows": 2, "sha256": "y"},
                    {"year": 2022, "file": "t1_2022.csv.gz", "rows": 9, "sha256": "z"},
                ],
            }
        ]
    }
    live = {("t1", 2020): 5, ("t1", 2021): 2, ("t1", 2022): 9}  # 2020 differs live
    files = {("t1", 2020): 4, ("t1", 2021): 3, ("t1", 2022): 9}  # 2021 differs on disk
    digests = {("t1", 2020): "x", ("t1", 2021): "y", ("t1", 2022): "w"}  # 2022 digest moved
    problems = mod.verify_slices(manifest, live, files, digests)
    assert "t1 2020" in problems[0] and "live count" in problems[0]
    assert "t1 2021" in problems[1] and "file rows" in problems[1]
    assert "t1 2022" in problems[2] and "sha256" in problems[2]
    assert len(problems) == 3


def test_verify_slices_flags_a_live_slice_the_manifest_lacks():
    manifest = {
        "tables": [
            {"table": "t1", "files": [{"year": 2020, "file": "f", "rows": 1, "sha256": "x"}]}
        ]
    }
    live = {("t1", 2020): 1, ("t1", 2021): 3}
    files = {("t1", 2020): 1}
    digests = {("t1", 2020): "x"}
    problems = mod.verify_slices(manifest, live, files, digests)
    assert any("t1 2021" in p and "not in the manifest" in p for p in problems)


def test_verify_files_passes_when_files_agree():
    manifest = {
        "tables": [
            {
                "table": "t1",
                "files": [
                    {"year": 2020, "file": "t1_2020.csv.gz", "rows": 4, "sha256": "x"},
                    {"year": 2021, "file": "t1_2021.csv.gz", "rows": 0, "sha256": "y"},
                ],
            }
        ]
    }
    files = {("t1", 2020): 4, ("t1", 2021): 0}
    digests = {("t1", 2020): "x", ("t1", 2021): "y"}
    assert mod.verify_files(manifest, files, digests) == []


def test_verify_files_names_every_mismatching_slice():
    manifest = {
        "tables": [
            {
                "table": "t1",
                "files": [
                    {"year": 2020, "file": "t1_2020.csv.gz", "rows": 4, "sha256": "x"},
                    {"year": 2021, "file": "t1_2021.csv.gz", "rows": 2, "sha256": "y"},
                    {"year": 2022, "file": "t1_2022.csv.gz", "rows": 9, "sha256": "z"},
                ],
            }
        ]
    }
    files = {("t1", 2020): 4, ("t1", 2021): 3}  # 2021 differs on disk, 2022 deleted
    digests = {("t1", 2020): "w", ("t1", 2021): "y", ("t1", 2022): "z"}  # 2020 digest moved
    problems = mod.verify_files(manifest, files, digests)
    assert "t1 2020" in problems[0] and "sha256" in problems[0]
    assert "t1 2021" in problems[1] and "file rows" in problems[1]
    assert "t1 2022" in problems[2] and "missing" in problems[2]
    assert len(problems) == 3


def _write_backup_file(path: Path, rows: int) -> str:
    """One gzip CSV of `rows` data lines plus a header, as the dump writes; its sha256."""
    body = b"col\n" + b"1\n" * rows
    compressed = gzip.compress(body, mtime=0)
    path.write_bytes(compressed)
    return hashlib.sha256(compressed).hexdigest()


def _write_manifest(tmp_path: Path) -> Path:
    sha_2020 = _write_backup_file(tmp_path / "t1_2020.csv.gz", rows=2)
    sha_2021 = _write_backup_file(tmp_path / "t1_2021.csv.gz", rows=3)
    manifest = {
        "tables": [
            {
                "table": "t1",
                "date_column": "bar_date",
                "total_rows": 5,
                "files": [
                    {"year": 2020, "file": "t1_2020.csv.gz", "rows": 2, "sha256": sha_2020},
                    {"year": 2021, "file": "t1_2021.csv.gz", "rows": 3, "sha256": sha_2021},
                ],
            }
        ]
    }
    manifest_path = tmp_path / "old_store_backup_manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    return manifest_path


def test_run_verify_files_agrees_on_disk_without_any_database(tmp_path, capsys, monkeypatch):
    manifest_path = _write_manifest(tmp_path)

    def _no_db(*args, **kwargs):
        raise AssertionError("the file-only verify must not open a database connection")

    monkeypatch.setattr(mod, "_connect", _no_db)
    assert mod.run_verify_files(manifest_path) == 0
    out = capsys.readouterr().out
    assert "verify ok" in out and '"t1": 5' in out


def test_run_verify_files_fails_naming_the_slice_when_a_file_changed(tmp_path, capsys):
    manifest_path = _write_manifest(tmp_path)
    _write_backup_file(tmp_path / "t1_2021.csv.gz", rows=6)  # bit rot after the manifest
    assert mod.run_verify_files(manifest_path) == 1
    captured = capsys.readouterr()
    assert "VERIFY FAILED" in captured.err
    assert "t1 2021" in captured.out and "file rows" in captured.out


def test_run_verify_files_reports_a_deleted_slice_file(tmp_path, capsys):
    manifest_path = _write_manifest(tmp_path)
    (tmp_path / "t1_2021.csv.gz").unlink()
    assert mod.run_verify_files(manifest_path) == 1
    out = capsys.readouterr().out
    assert "t1 2021" in out and "missing" in out


def test_disk_check_refuses_below_estimate_times_margin():
    refusal = mod.disk_refusal(free_bytes=90, estimated_bytes=50, margin=2)
    assert refusal is not None and "90" in refusal and "100" in refusal


def test_disk_check_passes_at_or_above_the_margin():
    assert mod.disk_refusal(free_bytes=100, estimated_bytes=50, margin=2) is None
    assert mod.disk_refusal(free_bytes=150, estimated_bytes=50, margin=2) is None


def test_disk_check_refuses_a_margin_below_one():
    with pytest.raises(ValueError, match="margin"):
        mod.disk_refusal(free_bytes=10_000, estimated_bytes=1, margin=0.5)


def test_source_carries_no_write_or_ddl_tokens():
    """The script must stay read-only: no row-writing or schema-changing SQL token appears
    outside comments (the plan's done check, enforced here)."""
    import re

    source = Path(mod.__file__).read_text()
    stripped = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    assert not re.search(
        r"\b(DELETE|DROP|UPDATE|INSERT|TRUNCATE|MERGE)\b", stripped
    ), "the backup script must never carry a write or DDL token"


def test_tables_name_both_old_stores_with_their_date_columns():
    assert [(t.table, t.date_column) for t in mod.TABLES] == [
        ("ohlcv_observation", "bar_date"),
        ("ohlcv_intraday_raw_archive", '"timestamp"'),
    ]
