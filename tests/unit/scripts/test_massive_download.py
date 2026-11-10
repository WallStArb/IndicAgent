"""Manifest and resume logic for the Massive flat-file downloader (todo 600).

No network: listings come from canned XML, transfers from a fake fetch that writes
bytes to the .part path, free space from an injected callable.
"""

from __future__ import annotations

import argparse
import gzip
import io
import subprocess
from pathlib import Path

import pytest

from scripts.infrastructure.massive import massive_download as md

LIST_XML_TEMPLATE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
    "<Name>production-flatfiles</Name>"
    "<Prefix>us_stocks_sip/minute_aggs_v1/</Prefix>"
    "{contents}"
    "<KeyCount>{count}</KeyCount>"
    "{token}"
    "</ListBucketResult>"
)


def contents_xml(pairs: list[tuple[str, int]]) -> str:
    parts = []
    for key, size in pairs:
        parts.append(
            "<Contents>"
            f"<Key>{key}</Key>"
            "<LastModified>2026-03-30T15:50:44.799Z</LastModified>"
            "<ETag>&quot;x&quot;</ETag>"
            f"<Size>{size}</Size>"
            "<StorageClass>STANDARD</StorageClass>"
            "<Type>Normal</Type>"
            "</Contents>"
        )
    return "".join(parts)


def make_listing_runner(pages: dict[str | None, tuple[list[tuple[str, int]], str | None]]):
    """A fake curl runner serving one canned page per request token (None = first).

    Each page is (key/size pairs, next continuation token or None), emitted
    verbatim: no token minting, no URL grammar beyond the one split.
    """

    def runner(args: list[str]) -> subprocess.CompletedProcess[bytes]:
        url = args[-1]
        token = None
        if "continuation-token=" in url:
            token = url.split("continuation-token=")[1]
        pairs, next_token = pages[token]
        token_xml = (
            f"<NextContinuationToken>{next_token}</NextContinuationToken>" if next_token else ""
        )
        xml = LIST_XML_TEMPLATE.format(
            contents=contents_xml(pairs), count=len(pairs), token=token_xml
        )
        return subprocess.CompletedProcess(args, 0, xml.encode(), b"")

    return runner


@pytest.fixture
def cfg() -> md.S3Config:
    return md.S3Config(
        endpoint="https://files.example.com",
        bucket="flatfiles",
        access_key_id="ak",
        secret_access_key="sk",
    )


@pytest.fixture
def entry() -> md.KeyEntry:
    return md.KeyEntry(
        key="us_stocks_sip/minute_aggs_v1/2003/09/2003-09-10.csv.gz",
        dataset="minute_aggs_v1",
        date="2003-09-10",
        size=0,
    )


def make_csv_gz(path: Path, rows: list[str], header: bool = True) -> int:
    """Write a realistic csv.gz payload, return its compressed byte size."""
    lines = (
        ["ticker,volume,open,close,high,low,window_start,transactions"] if header else []
    ) + rows
    payload = ("\n".join(lines) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as fh:
        fh.write(payload)
    return path.stat().st_size


def fake_fetch_factory(content: bytes):
    def fetch(cfg, entry, part):  # noqa: ANN001
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(content)

    return fetch


class TestParseKey:
    def test_accepts_real_layout(self):
        entry = md.parse_key("us_stocks_sip/minute_aggs_v1/2003/09/2003-09-10.csv.gz")
        assert entry is not None
        assert entry.dataset == "minute_aggs_v1"
        assert entry.date == "2003-09-10"

    def test_rejects_other_prefixes_and_names(self):
        assert md.parse_key("us_stocks_sip/day_aggs_v1/2010/01/2010-01-04.csv.gz") is not None
        assert md.parse_key("other/minute_aggs_v1/2010/01/2010-01-04.csv.gz") is None
        assert md.parse_key("us_stocks_sip/minute_aggs_v1/2010/01/junk.csv") is None
        assert md.parse_key("us_stocks_sip/minute_aggs_v1/2010/01/2010-13-99.csv.gz") is None


class TestListAndInventory:
    def test_paginated_listing(self, cfg):
        runner = make_listing_runner(
            {
                None: ([("us_stocks_sip/minute_aggs_v1/2003/09/2003-09-10.csv.gz", 100)], "t1"),
                "t1": ([("us_stocks_sip/minute_aggs_v1/2003/09/2003-09-11.csv.gz", 200)], None),
            }
        )
        entries = md.list_prefix(cfg, "minute_aggs_v1", runner=runner)
        assert [entry.size for entry in entries] == [100, 200]
        assert all(entry.dataset == "minute_aggs_v1" for entry in entries)

    def test_listing_failure_raises(self, cfg):
        def runner(args: list[str]) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(args, 1, b"", b"403")

        with pytest.raises(RuntimeError, match="403"):
            md.list_prefix(cfg, "minute_aggs_v1", runner=runner)

    def test_inventory_roundtrip(self, tmp_path, entry):
        entry = md.KeyEntry(entry.key, entry.dataset, entry.date, size=777)
        path = tmp_path / "inventory.jsonl"
        md.write_inventory(path, [entry])
        assert md.load_inventory(path) == [entry]


class TestManifestResume:
    def test_skip_when_manifest_size_matches(self, tmp_path, entry):
        files_root = tmp_path / "files"
        dest = entry.local_path(files_root)
        size = make_csv_gz(dest, ["SPY,1,2,3,4,1,0,1"])
        listed = md.KeyEntry(entry.key, entry.dataset, entry.date, size=size)
        index = {listed.key: {"key": listed.key}}
        todo, skipped = md.plan_downloads([listed], index, files_root)
        assert todo == []
        assert skipped == 1

    def test_redownload_on_size_mismatch(self, tmp_path, entry):
        files_root = tmp_path / "files"
        dest = entry.local_path(files_root)
        make_csv_gz(dest, ["SPY,1,2,3,4,1,0,1"])
        listed = md.KeyEntry(entry.key, entry.dataset, entry.date, size=999999)
        index = {entry.key: {"key": entry.key}}
        todo, skipped = md.plan_downloads([listed], index, files_root)
        assert todo == [listed]
        assert skipped == 0

    def test_redownload_when_file_missing(self, tmp_path, entry):
        todo, skipped = md.plan_downloads(
            [entry], {entry.key: {"key": entry.key}}, tmp_path / "files"
        )
        assert todo == [entry]
        assert skipped == 0

    def test_redownload_without_manifest_record(self, tmp_path, entry):
        # Interrupted before the manifest record: the file on disk is not trusted.
        todo, skipped = md.plan_downloads([entry], {}, tmp_path / "files")
        assert todo == [entry]
        assert skipped == 0

    def test_manifest_roundtrip_last_wins(self, tmp_path):
        path = tmp_path / "manifest.jsonl"
        md.append_manifest(path, {"key": "a", "rows": 1})
        md.append_manifest(path, {"key": "a", "rows": 2})
        md.append_manifest(path, {"key": "b", "rows": 3})
        index = md.load_manifest(path)
        assert index["a"]["rows"] == 2
        assert index["b"]["rows"] == 3


class TestGzipRows:
    def test_counts_rows_excluding_header(self, tmp_path):
        path = tmp_path / "f.csv.gz"
        make_csv_gz(path, ["SPY,1,2,3,4,1,0,1", "QQQ,2,3,4,5,2,0,2"])
        assert md.gzip_rows(path) == 2

    def test_empty_payload_is_zero_rows(self, tmp_path):
        path = tmp_path / "f.csv.gz"
        make_csv_gz(path, [], header=False)
        assert md.gzip_rows(path) == 0

    def test_corrupt_gzip_raises(self, tmp_path):
        path = tmp_path / "f.csv.gz"
        path.write_bytes(b"\x1f\x8b" + b"garbage" * 10)
        with pytest.raises(OSError):
            md.gzip_rows(path)


class TestDownloadOne:
    def test_success_records_and_moves(self, tmp_path, entry, cfg):
        rows = ["SPY,1,2,3,4,1,0,1"] * 5
        staging = tmp_path / "staging.csv.gz"
        size = make_csv_gz(staging, rows)
        payload = staging.read_bytes()
        entry = md.KeyEntry(entry.key, entry.dataset, entry.date, size=size)
        files_root = tmp_path / "files"
        record = md.download_one(
            entry,
            files_root,
            cfg,
            min_free_bytes=0,
            fetch_fn=fake_fetch_factory(payload),
            disk_free_fn=lambda _root: 1 << 40,
        )
        dest = entry.local_path(files_root)
        assert dest.read_bytes() == payload
        assert record["bytes"] == size
        assert record["rows"] == len(rows)
        assert record["gzip_ok"] is True
        assert len(record["sha256"]) == 64
        assert not list(files_root.rglob("*.part"))
        assert record["path"] == "minute_aggs_v1/2003/09/2003-09-10.csv.gz"

    def test_size_mismatch_removes_part(self, tmp_path, entry, cfg):
        staging = tmp_path / "staging.csv.gz"
        make_csv_gz(staging, ["SPY,1,2,3,4,1,0,1"])
        entry = md.KeyEntry(entry.key, entry.dataset, entry.date, size=999)
        files_root = tmp_path / "files"
        with pytest.raises(RuntimeError, match="size mismatch"):
            md.download_one(
                entry,
                files_root,
                cfg,
                0,
                fetch_fn=fake_fetch_factory(staging.read_bytes()),
                disk_free_fn=lambda _root: 1 << 40,
            )
        assert not list(files_root.rglob("*.part"))
        assert not list(files_root.rglob("*.csv.gz"))

    def test_corrupt_payload_rejected(self, tmp_path, entry, cfg):
        entry = md.KeyEntry(entry.key, entry.dataset, entry.date, size=32)
        files_root = tmp_path / "files"
        with pytest.raises(OSError):
            md.download_one(
                entry,
                files_root,
                cfg,
                0,
                fetch_fn=fake_fetch_factory(b"x" * 32),
                disk_free_fn=lambda _root: 1 << 40,
            )
        assert not list(files_root.rglob("*.csv.gz"))

    def test_disk_floor_refuses_before_fetch(self, tmp_path, entry, cfg):
        entry = md.KeyEntry(entry.key, entry.dataset, entry.date, size=100)
        calls: list[str] = []

        def fetch(cfg, entry, part):  # noqa: ANN001
            calls.append(entry.key)

        with pytest.raises(md.DiskFloorError):
            md.download_one(
                entry,
                tmp_path / "files",
                cfg,
                min_free_bytes=(1 << 40),
                fetch_fn=fetch,
                disk_free_fn=lambda _root: (1 << 40) + 50,
            )
        assert calls == []


class TestFloorLaw:
    def test_one_predicate_serves_preflight_and_per_file(self):
        floor = 100
        assert md.floor_breached(free=150, incoming=60, floor=floor) is True
        assert md.floor_breached(free=160, incoming=60, floor=floor) is False


class TestFilterEntries:
    def test_filters_dataset_and_dates(self, entry):
        day = md.KeyEntry(
            key="us_stocks_sip/day_aggs_v1/2003/09/2003-09-10.csv.gz",
            dataset="day_aggs_v1",
            date="2003-09-10",
            size=1,
        )
        later = md.KeyEntry(entry.key, entry.dataset, "2003-10-01", size=1)
        selected = md.filter_entries([entry, day, later], {"minute_aggs_v1"}, None, "2003-09-30")
        assert selected == [entry]


def gz_bytes(rows: list[str]) -> bytes:
    header = "ticker,volume,open,close,high,low,window_start,transactions"
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as fh:
        fh.write(("\n".join([header] + rows) + "\n").encode())
    return buf.getvalue()


def entry_for(date: str = "2003-09-10", dataset: str = "minute_aggs_v1", size: int = 0):
    year, month, _ = date.split("-")
    key = f"us_stocks_sip/{dataset}/{year}/{month}/{date}.csv.gz"
    return md.KeyEntry(key=key, dataset=dataset, date=date, size=size)


def writing_fetch(payloads: dict[str, bytes]):
    def fetch(cfg, entry, part):  # noqa: ANN001
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(payloads[entry.key])

    return fetch


def run_args(tmp_path: Path, min_free_gb: int = 1) -> argparse.Namespace:
    return argparse.Namespace(
        data_root=tmp_path / "data",
        manifest_dir=tmp_path / "m",
        env_file=tmp_path / "absent.env",
        datasets=["minute_aggs_v1", "day_aggs_v1"],
        date_from=None,
        date_to=None,
        inventory_only=False,
        refresh_inventory=False,
        verify=False,
        concurrency=2,
        min_free_gb=min_free_gb,
    )


class TestRun:
    """The orchestration layer: exit codes, manifest writes, resume."""

    def test_download_then_resume(self, tmp_path, cfg):
        p1 = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        p2 = gz_bytes(["A,2,3,4,5,2,0,2"])
        e1 = entry_for(size=len(p1))
        e2 = entry_for(date="2003-09-11", dataset="day_aggs_v1", size=len(p2))
        md.write_inventory(tmp_path / "m" / md.INVENTORY_NAME, [e1, e2])
        args = run_args(tmp_path)
        fetch = writing_fetch({e1.key: p1, e2.key: p2})
        assert md.run(args, cfg=cfg, fetch_fn=fetch) == 0
        manifest = md.load_manifest(tmp_path / "m" / md.MANIFEST_NAME)
        assert sorted(manifest) == sorted([e1.key, e2.key])
        files_root = tmp_path / "data" / "files"
        assert e1.local_path(files_root).read_bytes() == p1
        assert e2.local_path(files_root).read_bytes() == p2
        # resume: everything already in the manifest with matching sizes
        assert md.run(args, cfg=cfg, fetch_fn=writing_fetch({})) == 0

    def test_floor_preflight_exit_2(self, tmp_path, cfg):
        payload = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        e1 = entry_for(size=len(payload))
        md.write_inventory(tmp_path / "m" / md.INVENTORY_NAME, [e1])
        args = run_args(tmp_path, min_free_gb=10**6)
        assert md.run(args, cfg=cfg, fetch_fn=writing_fetch({e1.key: payload})) == 2
        assert not md.load_manifest(tmp_path / "m" / md.MANIFEST_NAME)

    def test_size_mismatch_fails_after_retries(self, tmp_path, cfg):
        payload = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        e1 = entry_for(size=len(payload) + 5)  # listed size disagrees with served bytes
        md.write_inventory(tmp_path / "m" / md.INVENTORY_NAME, [e1])
        args = run_args(tmp_path)
        assert md.run(args, cfg=cfg, fetch_fn=writing_fetch({e1.key: payload})) == 1
        assert not md.load_manifest(tmp_path / "m" / md.MANIFEST_NAME)

    def test_verify_flags_corruption(self, tmp_path, cfg):
        payload = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        e1 = entry_for(size=len(payload))
        md.write_inventory(tmp_path / "m" / md.INVENTORY_NAME, [e1])
        args = run_args(tmp_path)
        assert md.run(args, cfg=cfg, fetch_fn=writing_fetch({e1.key: payload})) == 0
        files_root = tmp_path / "data" / "files"
        # corrupt the file at rest, keeping its size, then verify must exit 1
        dest = e1.local_path(files_root)
        corrupted = bytearray(dest.read_bytes())
        corrupted[len(corrupted) // 2] ^= 0xFF
        dest.write_bytes(bytes(corrupted))
        verify_args = run_args(tmp_path)
        verify_args.verify = True
        assert md.run(verify_args, cfg=cfg) == 1
