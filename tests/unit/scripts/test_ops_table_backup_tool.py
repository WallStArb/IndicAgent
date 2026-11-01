"""Unit tests for the generic pre-drop COPY backup tool (todo 578).

Covers the pure parts on in-memory fixtures: year-slice arithmetic, the slice SELECT (both
bound kinds plus the --where clause), gzip row counting, sha256, the disk-margin refusal, the
--verify mismatch path, and the --verify-files retention check. No database anywhere in this
file; the successor of test_ops_old_store_backup.py (todo 578).
"""

from __future__ import annotations

import gzip
import hashlib
from datetime import date
from pathlib import Path

import pytest

from scripts.ops.db import ops_table_backup as mod


def test_year_slices_are_half_open_and_consecutive():
    slices = mod.year_slices(1999, 2001)
    assert [(s.year, s.lo, s.hi) for s in slices] == [
        (1999, date(1999, 1, 1), date(2000, 1, 1)),
        (2000, date(2000, 1, 1), date(2001, 1, 1)),
        (2001, date(2001, 1, 1), date(2002, 1, 1)),
    ]


def test_slice_select_reads_one_table_within_bounds():
    sql = mod.slice_select_sql(
        mod.TableSpec("concept_gate", "recorded_at", "date"), date(2020, 1, 1), date(2021, 1, 1)
    )
    assert sql == (
        "SELECT * FROM concept_gate WHERE recorded_at >= '2020-01-01' "
        "AND recorded_at < '2021-01-01'"
    )


def test_slice_select_quotes_a_timestamptz_column_and_binds_an_instant():
    sql = mod.slice_select_sql(
        mod.TableSpec("market_data_ohlcv", '"timestamp"', "timestamptz"),
        date(2020, 1, 1),
        date(2021, 1, 1),
    )
    assert '"timestamp"' in sql and "2020-01-01T00:00:00+00:00" in sql


def test_slice_select_adds_the_where_clause():
    sql = mod.slice_select_sql(
        mod.TableSpec("ohlcv_raw", '"timestamp"', "timestamptz"),
        date(2020, 1, 1),
        date(2021, 1, 1),
        where="symbol = 'AAA'",
    )
    assert sql.endswith("AND (symbol = 'AAA')")


def test_count_rows_in_gzip_counts_csv_rows(tmp_path: Path):
    path = tmp_path / "slice.csv.gz"
    path.write_bytes(gzip.compress(b"a,b,c\n1,2,3\n4,5,6\n"))
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


def test_disk_refusal_scales_the_estimate_by_the_margin():
    assert mod.disk_refusal(100, 60, 2.0) is not None
    assert mod.disk_refusal(120, 60, 2.0) is None
    with pytest.raises(ValueError, match=">= 1.0"):
        mod.disk_refusal(100, 60, 0.5)


def test_manifest_totals_sum_the_file_rows():
    manifest = {
        "tables": [
            {"table": "t1", "files": [{"rows": 2}, {"rows": 3}]},
            {"table": "t2", "files": [{"rows": 7}]},
        ]
    }
    assert mod.manifest_table_totals(manifest) == {"t1": 5, "t2": 7}


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


def test_main_requires_a_table_for_dump_and_verify():
    with pytest.raises(SystemExit):
        mod.main(["--dump", "--retention-until", "2027-01-01"])
    with pytest.raises(SystemExit):
        mod.main(["--verify"])


def test_main_requires_retention_until_for_a_dump():
    with pytest.raises(SystemExit):
        mod.main(["--dump", "--table", "t1", "--backup-dir", "/tmp/x"])


def test_main_builds_the_table_specs():
    specs: list[mod.TableSpec] = []

    class _Recorder:
        def __init__(self, *args, **kwargs) -> None:
            return None

    original = mod.run_dump

    def _capture(specs_in, out_dir, manifest_path, retention_until, where):
        specs.extend(specs_in)
        return 0

    mod.run_dump = _capture
    try:
        mod.main(
            [
                "--dump",
                "--retention-until",
                "2027-06-01",
                "--table",
                "concept_gate:recorded_at",
                "--table",
                "ohlcv_raw::timestamptz",
                "--backup-dir",
                "/tmp/x",
            ]
        )
    finally:
        mod.run_dump = original
    assert specs == [
        mod.TableSpec("concept_gate", "recorded_at", "date"),
        mod.TableSpec("ohlcv_raw", "timestamp", "timestamptz"),
    ]
