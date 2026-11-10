"""Manifest and resume logic for the Massive flat-file downloader (todo 600).

No network: listings come from canned XML, transfers from a fake fetch that writes
bytes to the .part path, free space from an injected callable.
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import io
import json
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

    def runner(args: list[str], stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
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
    return entry_for(etag="")


def gz_bytes(rows: list[str], header: bool = True) -> bytes:
    lines = (
        ["ticker,volume,open,close,high,low,window_start,transactions"] if header else []
    ) + rows
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as fh:
        fh.write(("\n".join(lines) + "\n").encode())
    return buf.getvalue()


def make_csv_gz(path: Path, rows: list[str], header: bool = True) -> int:
    """Write a realistic csv.gz payload, return its compressed byte size."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gz_bytes(rows, header))
    return path.stat().st_size


def entry_for(
    date: str = "2003-09-10", dataset: str = "minute_aggs_v1", size: int = 0, etag: str = "e1"
):
    year, month, _ = date.split("-")
    key = f"us_stocks_sip/{dataset}/{year}/{month}/{date}.csv.gz"
    return md.KeyEntry(key=key, dataset=dataset, date=date, size=size, etag=etag)


LAST_MODIFIED = "2026-03-30T15:50:44.799Z"


def writing_fetch(payloads: dict[str, bytes], etag: str | None = None, last_modified=LAST_MODIFIED):
    """A fake transfer: writes the payload and returns the response labels (the entry's
    ETag unless ``etag`` overrides it)."""

    def fetch(cfg, entry, part):  # noqa: ANN001
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(payloads[entry.key])
        return md.Served(etag=entry.etag if etag is None else etag, last_modified=last_modified)

    return fetch


def fresh_free(_root):  # noqa: ANN001
    return 1 << 40


def download(entry, files_root, cfg, payload, previous=None, **fetch_kwargs):
    return md.download_one(
        entry,
        files_root,
        cfg,
        0,
        fetch_fn=writing_fetch({entry.key: payload}, **fetch_kwargs),
        disk_free_fn=fresh_free,
        previous=previous,
    )


class TestCredentialHandling:
    def test_secret_in_neither_argv_nor_a_file(self, cfg):
        args = md.curl_base_args(cfg)
        assert "sk" not in " ".join(args)
        assert args[-2:] == ["-K", "-"]
        assert md.curl_auth_stdin(cfg) == b'user = "ak:sk"\n'

    def test_curl_run_passes_stdin_explicitly(self, cfg, monkeypatch):
        seen: dict = {}

        def fake_run(args, **kwargs):
            seen["input"] = kwargs.get("input")
            return subprocess.CompletedProcess(args, 0, b"", b"")

        monkeypatch.setattr(md.subprocess, "run", fake_run)
        md.curl_run(md.curl_base_args(cfg), md.curl_auth_stdin(cfg))
        assert seen["input"] == b'user = "ak:sk"\n'

    def test_quotes_and_backslashes_are_escaped_in_the_config_line(self):
        cfg = md.S3Config(access_key_id='a"b', secret_access_key="c\\d")
        assert md.curl_auth_stdin(cfg) == b'user = "a\\"b:c\\\\d"\n'

    def test_line_break_in_a_credential_is_refused(self):
        cfg = md.S3Config(access_key_id="a\nb", secret_access_key="c")
        with pytest.raises(ValueError, match="line break"):
            md.curl_auth_stdin(cfg)

    def test_repr_hides_the_secret(self, cfg):
        assert "sk" not in repr(cfg) and "ak" not in repr(cfg)

    def test_missing_credentials_error_names_fields_not_values(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MASSIVE_S3_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("MASSIVE_S3_SECRET_ACCESS_KEY", raising=False)
        env = tmp_path / "x.env"
        env.write_text("MASSIVE_S3_ACCESS_KEY_ID=topsecretvalue\n")
        args = run_args(tmp_path)
        args.env_file = env
        with pytest.raises(SystemExit) as raised:
            md.run(args)
        assert "MASSIVE_S3_SECRET_ACCESS_KEY" in str(raised.value)
        assert "topsecretvalue" not in str(raised.value)


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
        def runner(args, stdin=None):  # noqa: ANN001
            return subprocess.CompletedProcess(args, 1, b"", b"403")

        with pytest.raises(RuntimeError, match="403"):
            md.list_prefix(cfg, "minute_aggs_v1", runner=runner)

    def test_inventory_roundtrip(self, tmp_path, entry):
        entry = md.KeyEntry(
            entry.key,
            entry.dataset,
            entry.date,
            size=777,
            etag="abc",
            last_modified="2026-03-30T15:50:44.799Z",
        )
        path = tmp_path / "inventory.jsonl"
        md.write_inventory(path, [entry])
        assert md.load_inventory(path) == [entry]
        assert not list(tmp_path.glob("*.tmp"))  # atomic: temp renamed away

    def test_truncated_without_token_fails(self, cfg):
        xml = LIST_XML_TEMPLATE.format(
            contents="", count=0, token="<IsTruncated>true</IsTruncated>"
        ).encode()

        def runner(args, stdin=None):  # noqa: ANN001
            return subprocess.CompletedProcess(args, 0, xml, b"")

        with pytest.raises(RuntimeError, match="truncated without a continuation token"):
            md.list_prefix(cfg, "minute_aggs_v1", runner=runner)

    def test_rejected_key_fails_the_listing(self, cfg):
        runner = make_listing_runner(
            {None: ([("us_stocks_sip/minute_aggs_v1/2003/09/readme.txt", 1)], None)}
        )
        with pytest.raises(RuntimeError, match="1 keys the parser rejects"):
            md.list_prefix(cfg, "minute_aggs_v1", runner=runner)

    def test_key_outside_the_requested_dataset_fails(self, cfg):
        runner = make_listing_runner(
            {None: ([("us_stocks_sip/day_aggs_v1/2003/09/2003-09-10.csv.gz", 1)], None)}
        )
        with pytest.raises(RuntimeError, match="rejects"):
            md.list_prefix(cfg, "minute_aggs_v1", runner=runner)


def per_dataset_runner(pages: dict[str, list[tuple[str, int]]]):
    """Serves one canned page per dataset prefix; a dataset not in ``pages`` must not be
    listed."""

    def runner(args, stdin=None):  # noqa: ANN001
        dataset = args[-1].split("%2F")[1]
        xml = LIST_XML_TEMPLATE.format(
            contents=contents_xml(pages[dataset]), count=len(pages[dataset]), token=""
        )
        return subprocess.CompletedProcess(args, 0, xml.encode(), b"")

    return runner


class TestEnsureInventory:
    def seed(self, path):
        old = [
            entry_for(size=1, etag="m1"),
            entry_for(dataset="day_aggs_v1", size=2, etag="d1"),
        ]
        md.write_inventory(path, old)
        return old

    def test_refresh_subset_merges_other_datasets_from_the_existing_inventory(self, tmp_path, cfg):
        path = tmp_path / "inventory.jsonl"
        old = self.seed(path)
        day_key = "us_stocks_sip/day_aggs_v1/2003/09/2003-09-10.csv.gz"
        runner = per_dataset_runner({"day_aggs_v1": [(day_key, 99)]})
        merged = md.ensure_inventory(path, cfg, ["day_aggs_v1"], True, runner=runner)
        assert [(e.dataset, e.size) for e in merged] == [("day_aggs_v1", 99), ("minute_aggs_v1", 1)]
        assert md.load_inventory(path) == merged
        assert old[0] in merged  # the minute entry survived untouched

    def test_subset_with_no_inventory_to_merge_is_refused(self, tmp_path, cfg):
        runner = per_dataset_runner({"day_aggs_v1": []})
        with pytest.raises(md.InventoryScopeError):
            md.ensure_inventory(tmp_path / "inv.jsonl", cfg, ["day_aggs_v1"], False, runner=runner)
        assert not (tmp_path / "inv.jsonl").exists()

    def test_existing_inventory_loads_without_listing(self, tmp_path, cfg):
        path = tmp_path / "inventory.jsonl"
        old = self.seed(path)

        def boom(args, stdin=None):  # noqa: ANN001
            raise AssertionError("must not list")

        assert md.ensure_inventory(path, cfg, list(md.DATASETS), False, runner=boom) == old


class TestServeFields:
    def test_listing_captures_normalized_etag_and_last_modified(self, cfg):
        runner = make_listing_runner(
            {None: ([("us_stocks_sip/minute_aggs_v1/2003/09/2003-09-10.csv.gz", 100)], None)}
        )
        (listed,) = md.list_prefix(cfg, "minute_aggs_v1", runner=runner)
        assert listed.etag == "x"
        assert listed.last_modified == "2026-03-30T15:50:44.799Z"

    def test_old_inventory_loads_with_empty_etag(self, tmp_path, entry):
        path = tmp_path / "inventory.jsonl"
        path.write_text(
            json.dumps({"key": entry.key, "dataset": entry.dataset, "date": entry.date, "size": 5})
            + "\n"
        )
        assert md.load_inventory(path)[0].etag == ""

    def test_normalize_etag_handles_escaped_and_plain_quotes(self):
        assert md.normalize_etag("&quot;abc&quot;") == "abc"
        assert md.normalize_etag('"abc"') == "abc"
        assert md.normalize_etag("abc") == "abc"

    def test_weak_etag_is_rejected(self):
        with pytest.raises(ValueError, match="weak"):
            md.normalize_etag('W/"abc"')


# One real line of data/massive/manifest/servetimes_minute_aggs_v1.jsonl (captured 2026-11-10):
# columns are key, LastModified, ETag (HTML-escaped quotes), size, tab separated.
REAL_SERVETIMES_LINE = (
    "us_stocks_sip/minute_aggs_v1/2003/09/2003-09-10.csv.gz\t"
    "2026-03-30T15:50:44.799Z\t"
    "&quot;577342683416e5452eec25d36c4a4e56&quot;\t"
    "7726388\n"
)


def servetimes_line(key: str, etag: str, size: int) -> str:
    return f"{key}\t{LAST_MODIFIED}\t&quot;{etag}&quot;\t{size}\n"


def record_for(entry, size=10, **extra):
    return {
        "key": entry.key,
        "bytes": size,
        "sha256": "s" * 64,
        "downloaded_at": "2026-11-10T12:51:55.550538+00:00",
        **extra,
    }


class TestServetimesGolden:
    def test_real_line_column_order(self, tmp_path):
        (tmp_path / "servetimes_minute_aggs_v1.jsonl").write_text(REAL_SERVETIMES_LINE)
        served = md.load_servetimes(tmp_path)
        assert served == {
            "us_stocks_sip/minute_aggs_v1/2003/09/2003-09-10.csv.gz": {
                "etag": "577342683416e5452eec25d36c4a4e56",
                "last_modified": "2026-03-30T15:50:44.799Z",
                "size": 7726388,
            }
        }


class TestMigration:
    def record(self, entry, size=10, **extra):
        return record_for(entry, size, **extra)

    def test_join_enriches_and_skips_records_that_have_an_etag(self, entry):
        served = {entry.key: {"etag": "e1", "last_modified": LAST_MODIFIED, "size": 10}}
        (done,) = md.join_servetimes([self.record(entry)], served)
        assert (done["etag"], done["last_modified"]) == ("e1", LAST_MODIFIED)
        assert done["sha256"] == "s" * 64
        assert md.join_servetimes([self.record(entry, etag="e0")], served) == []

    def test_join_fails_loudly(self, entry):
        ok = {"etag": "e1", "last_modified": LAST_MODIFIED, "size": 10}
        with pytest.raises(md.ManifestJoinError, match="not in servetimes"):
            md.join_servetimes([self.record(entry)], {})
        with pytest.raises(md.ManifestJoinError, match="size"):
            md.join_servetimes([self.record(entry)], {entry.key: {**ok, "size": 11}})
        with pytest.raises(md.ManifestJoinError, match="ETag is empty"):
            md.join_servetimes([self.record(entry)], {entry.key: {**ok, "etag": ""}})
        with pytest.raises(md.ManifestJoinError, match="LastModified is empty"):
            md.join_servetimes([self.record(entry)], {entry.key: {**ok, "last_modified": ""}})

    def test_join_fails_when_served_after_the_download(self, entry):
        late = {"etag": "e1", "last_modified": "2026-11-11T00:00:00.000Z", "size": 10}
        with pytest.raises(md.ManifestJoinError, match="later than downloaded_at"):
            md.join_servetimes([self.record(entry)], {entry.key: late})

    def test_join_md5_pass_through_checks_single_part_etags_only(self, entry):
        good = hashlib.md5(b"bytes").hexdigest()
        served = {"last_modified": LAST_MODIFIED, "size": 10}
        md5_of = lambda _record: good  # noqa: E731
        (done,) = md.join_servetimes(
            [self.record(entry)], {entry.key: {**served, "etag": good}}, md5_of
        )
        assert done["etag"] == good
        with pytest.raises(md.ManifestJoinError, match="md5"):
            md.join_servetimes(
                [self.record(entry)], {entry.key: {**served, "etag": "0" * 32}}, md5_of
            )
        multipart = {**served, "etag": "0" * 32 + "-3"}  # a dash: not an md5, not checked
        assert md.join_servetimes([self.record(entry)], {entry.key: multipart}, md5_of)

    def test_migrate_appends_and_is_idempotent(self, tmp_path, entry):
        manifest = tmp_path / md.MANIFEST_NAME
        md.append_manifest(manifest, self.record(entry))
        (tmp_path / "servetimes_minute_aggs_v1.jsonl").write_text(
            servetimes_line(entry.key, "e1", 10)
        )
        assert md.migrate_manifest(manifest, tmp_path) == 1
        assert md.load_manifest(manifest)[entry.key]["etag"] == "e1"
        assert len(manifest.read_text().splitlines()) == 2  # original kept, enriched appended
        assert md.migrate_manifest(manifest, tmp_path) == 0

    def test_duplicate_servetimes_key_raises(self, tmp_path, entry):
        for name in ("servetimes_a.jsonl", "servetimes_b.jsonl"):
            (tmp_path / name).write_text(servetimes_line(entry.key, "e1", 10))
        with pytest.raises(md.ManifestJoinError, match="twice"):
            md.load_servetimes(tmp_path)


class TestManifestResume:
    def test_skip_when_manifest_size_matches(self, tmp_path, entry):
        files_root = tmp_path / "files"
        dest = entry.local_path(files_root)
        size = make_csv_gz(dest, ["SPY,1,2,3,4,1,0,1"])
        listed = md.KeyEntry(entry.key, entry.dataset, entry.date, size=size, etag="e1")
        index = {listed.key: {"key": listed.key, "etag": "e1"}}
        todo, skipped = md.plan_downloads([listed], index, files_root)
        assert todo == []
        assert skipped == 1

    def test_redownload_on_etag_change_with_equal_size(self, tmp_path, entry):
        files_root = tmp_path / "files"
        size = make_csv_gz(entry.local_path(files_root), ["SPY,1,2,3,4,1,0,1"])
        listed = md.KeyEntry(entry.key, entry.dataset, entry.date, size=size, etag="e2")
        index = {listed.key: {"key": listed.key, "etag": "e1"}}
        todo, skipped = md.plan_downloads([listed], index, files_root)
        assert todo == [listed]
        assert skipped == 0

    def test_missing_etag_raises_on_either_side(self, tmp_path, entry):
        with_etag = md.KeyEntry(entry.key, entry.dataset, entry.date, size=1, etag="e1")
        with pytest.raises(md.MissingServeFieldsError, match="refresh-inventory"):
            md.plan_downloads([entry], {}, tmp_path)
        with pytest.raises(md.MissingServeFieldsError, match="migrate-manifest"):
            md.plan_downloads([with_etag], {entry.key: {"key": entry.key}}, tmp_path)

    def test_redownload_on_size_mismatch(self, tmp_path, entry):
        files_root = tmp_path / "files"
        dest = entry.local_path(files_root)
        make_csv_gz(dest, ["SPY,1,2,3,4,1,0,1"])
        listed = md.KeyEntry(entry.key, entry.dataset, entry.date, size=999999, etag="e1")
        index = {entry.key: {"key": entry.key, "etag": "e1"}}
        todo, skipped = md.plan_downloads([listed], index, files_root)
        assert todo == [listed]
        assert skipped == 0

    def test_redownload_when_file_missing(self, tmp_path, entry):
        listed = md.KeyEntry(entry.key, entry.dataset, entry.date, size=1, etag="e1")
        todo, skipped = md.plan_downloads(
            [listed], {entry.key: {"key": entry.key, "etag": "e1"}}, tmp_path / "files"
        )
        assert todo == [listed]
        assert skipped == 0

    def test_redownload_without_manifest_record(self, tmp_path, entry):
        # Interrupted before the manifest record: the file on disk is not trusted.
        listed = md.KeyEntry(entry.key, entry.dataset, entry.date, size=1, etag="e1")
        todo, skipped = md.plan_downloads([listed], {}, tmp_path / "files")
        assert todo == [listed]
        assert skipped == 0

    def test_manifest_roundtrip_last_wins(self, tmp_path):
        path = tmp_path / "manifest.jsonl"
        md.append_manifest(path, {"key": "a", "rows": 1})
        md.append_manifest(path, {"key": "a", "rows": 2})
        md.append_manifest(path, {"key": "b", "rows": 3})
        index = md.load_manifest(path)
        assert index["a"]["rows"] == 2
        assert index["b"]["rows"] == 3


class TestManifestAppend:
    def test_torn_fragment_is_truncated_before_the_next_append(self, tmp_path):
        path = tmp_path / "manifest.jsonl"
        md.append_manifest(path, {"key": "a", "rows": 1})
        with path.open("a") as fh:
            fh.write('{"key": "b", "ro')  # a kill mid-append
        assert md.load_manifest(path) == {"a": {"key": "a", "rows": 1}}  # ignored on load
        md.append_manifest(path, {"key": "c", "rows": 3})
        assert md.load_manifest(path) == {
            "a": {"key": "a", "rows": 1},
            "c": {"key": "c", "rows": 3},
        }
        assert len(path.read_text().splitlines()) == 2  # fragment gone, not buried mid-file

    def test_complete_record_missing_its_newline_is_kept(self, tmp_path):
        path = tmp_path / "manifest.jsonl"
        path.write_text(json.dumps({"key": "a", "rows": 1}))  # no trailing newline
        md.append_manifest(path, {"key": "b", "rows": 2})
        assert sorted(md.load_manifest(path)) == ["a", "b"]

    def test_damage_mid_file_still_raises(self, tmp_path):
        path = tmp_path / "manifest.jsonl"
        path.write_text('{"key": "a"}\nnot json\n{"key": "b"}\n')
        with pytest.raises(json.JSONDecodeError):
            md.load_manifest(path)


class TestManifestLock:
    def test_second_writer_is_refused(self, tmp_path):
        with md.manifest_lock(tmp_path), pytest.raises(md.ManifestLockedError):
            with md.manifest_lock(tmp_path):
                pass
        with md.manifest_lock(tmp_path):  # released on exit
            pass

    def test_run_refuses_a_writing_mode_while_locked(self, tmp_path, cfg):
        (tmp_path / "m").mkdir()
        with (tmp_path / "m" / md.LOCK_NAME).open("a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            assert md.run(run_args(tmp_path), cfg=cfg) == 2

    def test_read_only_modes_do_not_take_the_lock(self, tmp_path, cfg):
        (tmp_path / "m").mkdir()
        args = run_args(tmp_path)
        args.verify = True
        with (tmp_path / "m" / md.LOCK_NAME).open("a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            assert md.run(args, cfg=cfg) == 0


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
    def test_success_records_and_moves(self, tmp_path, cfg):
        rows = ["SPY,1,2,3,4,1,0,1"] * 5
        payload = gz_bytes(rows)
        entry = entry_for(size=len(payload))
        files_root = tmp_path / "files"
        record = download(entry, files_root, cfg, payload)
        assert entry.local_path(files_root).read_bytes() == payload
        assert record["bytes"] == len(payload)
        assert record["rows"] == len(rows)
        assert record["sha256"] == hashlib.sha256(payload).hexdigest()
        assert not list(files_root.rglob("*.part"))
        assert record["path"] == "minute_aggs_v1/2003/09/2003-09-10.csv.gz"

    def test_record_labels_come_from_the_response(self, tmp_path, cfg):
        payload = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        entry = entry_for(size=len(payload))
        record = download(entry, tmp_path / "files", cfg, payload, last_modified="served-at")
        assert record["last_modified"] == "served-at"  # not the inventory's (empty) value
        assert record["etag"] == "e1"

    def test_response_etag_differing_from_inventory_fails(self, tmp_path, cfg):
        payload = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        entry = entry_for(size=len(payload), etag="old")
        files_root = tmp_path / "files"
        with pytest.raises(md.ServeLabelError, match="differs from inventory"):
            download(entry, files_root, cfg, payload, etag="new")
        assert not list(files_root.rglob("*.csv.gz*"))

    def test_empty_response_labels_refuse(self, tmp_path, cfg):
        payload = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        entry = entry_for(size=len(payload))
        with pytest.raises(md.ServeLabelError, match="lacks"):
            download(entry, tmp_path / "files", cfg, payload, last_modified="")
        with pytest.raises(md.ServeLabelError, match="lacks"):
            download(entry, tmp_path / "files", cfg, payload, etag='""')

    def test_single_part_etag_must_equal_md5_of_the_bytes(self, tmp_path, cfg):
        payload = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        good = hashlib.md5(payload).hexdigest()
        files_root = tmp_path / "files"
        record = download(entry_for(size=len(payload), etag=good), files_root, cfg, payload)
        assert record["etag_md5_verified"] is True
        bad = entry_for(date="2003-09-11", size=len(payload), etag="0" * 32)
        with pytest.raises(md.ServeLabelError, match="md5"):
            download(bad, files_root, cfg, payload)
        assert not bad.local_path(files_root).exists()

    def test_multipart_etag_skips_the_md5_check(self, tmp_path, cfg):
        payload = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        record = download(
            entry_for(size=len(payload), etag="0" * 32 + "-2"), tmp_path / "files", cfg, payload
        )
        assert record["etag_md5_verified"] is False

    def test_size_mismatch_removes_part(self, tmp_path, cfg):
        payload = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        files_root = tmp_path / "files"
        with pytest.raises(RuntimeError, match="size mismatch"):
            download(entry_for(size=999), files_root, cfg, payload)
        assert not list(files_root.rglob("*.part"))
        assert not list(files_root.rglob("*.csv.gz"))

    def test_corrupt_payload_rejected(self, tmp_path, cfg):
        files_root = tmp_path / "files"
        with pytest.raises(OSError):
            download(entry_for(size=32), files_root, cfg, b"x" * 32)
        assert not list(files_root.rglob("*.csv.gz"))

    def test_disk_floor_refuses_before_fetch(self, tmp_path, cfg):
        calls: list[str] = []

        def fetch(cfg, entry, part):  # noqa: ANN001
            calls.append(entry.key)

        with pytest.raises(md.DiskFloorError):
            md.download_one(
                entry_for(size=100),
                tmp_path / "files",
                cfg,
                min_free_bytes=(1 << 40),
                fetch_fn=fetch,
                disk_free_fn=lambda _root: (1 << 40) + 50,
            )
        assert calls == []


class TestCurlFetchParsing:
    def test_write_out_block_is_parsed_and_the_last_retry_block_wins(self):
        out = b'"aaa"\nMon, 01 Jan 2026 00:00:00 GMT\n"bbb"\nTue, 02 Jan 2026 00:00:00 GMT\n'
        served = md.parse_write_out(out)
        assert served == md.Served("bbb", "Tue, 02 Jan 2026 00:00:00 GMT")

    def test_missing_headers_come_back_empty(self):
        assert md.parse_write_out(b"") == md.Served("", "")

    def test_curl_fetch_asks_for_the_headers_and_returns_them(self, cfg, tmp_path, monkeypatch):
        seen: dict = {}

        def fake_run(args, **kwargs):
            seen["args"] = args
            return subprocess.CompletedProcess(args, 0, b'"abc"\n2026-03-30T15:50:44.799Z\n', b"")

        monkeypatch.setattr(md.subprocess, "run", fake_run)
        served = md.curl_fetch(cfg, entry_for(), tmp_path / "x.part")
        assert served == md.Served("abc", "2026-03-30T15:50:44.799Z")
        assert "--write-out" in seen["args"]
        assert "%header{etag}" in seen["args"][seen["args"].index("--write-out") + 1]


class TestSupersession:
    def restate(
        self, tmp_path, cfg, old_payload, new_payload, old_etag="aaaaaaaa11", new_etag="bbbbbbbb22"
    ):
        files_root = tmp_path / "data" / "files"
        old = entry_for(size=len(old_payload), etag=old_etag)
        previous = download(old, files_root, cfg, old_payload)
        new = entry_for(size=len(new_payload), etag=new_etag)
        record = download(new, files_root, cfg, new_payload, previous=previous)
        return files_root, new, previous, record

    def test_etag_change_archives_old_bytes_and_records_supersession(self, tmp_path, cfg):
        old = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        new = gz_bytes(["SPY,9,9,9,9,9,0,9"])
        files_root, entry, previous, record = self.restate(tmp_path, cfg, old, new)
        assert entry.local_path(files_root).read_bytes() == new
        block = record["supersedes"]
        archive = files_root.parent / block["path"]
        assert archive.read_bytes() == old
        assert archive.name.endswith(".csv.gz.superseded-aaaaaaaa")
        assert archive.parent.parts[-3:] == ("minute_aggs_v1", "2003", "09")
        assert files_root not in archive.parents  # outside files/, a loader never sees it
        assert block["etag"] == "aaaaaaaa11"
        assert block["sha256"] == previous["sha256"] != record["sha256"]
        assert record["etag"] == "bbbbbbbb22"

    def test_same_etag_redownload_is_repair_not_supersession(self, tmp_path, cfg):
        payload = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        files_root, _entry, _prev, record = self.restate(
            tmp_path, cfg, payload, payload, old_etag="same", new_etag="same"
        )
        assert "supersedes" not in record
        assert not (files_root.parent / md.SUPERSEDED_DIR).exists()

    def test_new_etag_over_identical_bytes_is_a_repair(self, tmp_path, cfg):
        payload = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        files_root, _entry, _prev, record = self.restate(tmp_path, cfg, payload, payload)
        assert "supersedes" not in record
        assert not (files_root.parent / md.SUPERSEDED_DIR).exists()

    def test_same_etag_different_bytes_is_logged_loudly(self, tmp_path, cfg, monkeypatch):
        events: list[str] = []
        old = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        new = gz_bytes(["SPY,9,9,9,9,9,0,9"])
        files_root = tmp_path / "data" / "files"
        prev = download(entry_for(size=len(old), etag="same"), files_root, cfg, old)
        e_new = entry_for(size=len(new), etag="same")
        monkeypatch.setattr(md.log, "error", lambda event, **kw: events.append(event))
        record = download(e_new, files_root, cfg, new, previous=prev)
        assert "download.same_etag_different_bytes" in events
        assert "supersedes" not in record

    def test_existing_archive_is_never_overwritten(self, tmp_path, cfg):
        old = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        new = gz_bytes(["SPY,9,9,9,9,9,0,9"])
        files_root = tmp_path / "data" / "files"
        e_old = entry_for(size=len(old), etag="aaaaaaaa11")
        prev = download(e_old, files_root, cfg, old)
        e_new = entry_for(size=len(new), etag="bbbbbbbb22")
        block = md.supersession(
            prev, "bbbbbbbb22", hashlib.sha256(new).hexdigest(), e_new, files_root
        )
        archive = files_root.parent / block["path"]
        archive.parent.mkdir(parents=True)
        archive.write_bytes(b"precious")
        with pytest.raises(md.SupersessionRefusedError, match="refusing to overwrite"):
            download(e_new, files_root, cfg, new, previous=prev)
        assert archive.read_bytes() == b"precious"
        assert e_old.local_path(files_root).read_bytes() == old

    def test_missing_destination_refuses(self, tmp_path, cfg):
        old = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        new = gz_bytes(["SPY,9,9,9,9,9,0,9"])
        files_root = tmp_path / "data" / "files"
        e_old = entry_for(size=len(old), etag="aaaaaaaa11")
        prev = download(e_old, files_root, cfg, old)
        e_old.local_path(files_root).unlink()
        with pytest.raises(md.SupersessionRefusedError, match="absent"):
            download(
                entry_for(size=len(new), etag="bbbbbbbb22"), files_root, cfg, new, previous=prev
            )
        assert not list((tmp_path / "data").rglob("*.superseded-*"))

    def test_destination_with_other_bytes_refuses_and_is_left_alone(self, tmp_path, cfg):
        old = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        new = gz_bytes(["SPY,9,9,9,9,9,0,9"])
        other = gz_bytes(["QQQ,5,5,5,5,5,0,5"])
        files_root = tmp_path / "data" / "files"
        e_old = entry_for(size=len(old), etag="aaaaaaaa11")
        prev = download(e_old, files_root, cfg, old)
        e_old.local_path(files_root).write_bytes(other)
        with pytest.raises(md.SupersessionRefusedError, match="unproven"):
            download(
                entry_for(size=len(new), etag="bbbbbbbb22"), files_root, cfg, new, previous=prev
            )
        assert e_old.local_path(files_root).read_bytes() == other
        assert not list((tmp_path / "data").rglob("*.superseded-*"))


class TestSupersessionResume:
    def test_rerun_after_kill_between_archive_and_manifest_append(self, tmp_path, cfg):
        old = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        new = gz_bytes(["SPY,9,9,9,9,9,0,9"])
        files_root = tmp_path / "data" / "files"
        e_old = entry_for(size=len(old), etag="aaaaaaaa11")
        prev = download(e_old, files_root, cfg, old)
        e_new = entry_for(size=len(new), etag="bbbbbbbb22")
        first = download(e_new, files_root, cfg, new, previous=prev)
        # the kill: new file and archive are on disk, the manifest still holds `prev`
        again = download(e_new, files_root, cfg, new, previous=prev)
        assert again["supersedes"] == first["supersedes"]
        assert e_new.local_path(files_root).read_bytes() == new
        archive = files_root.parent / again["supersedes"]["path"]
        assert archive.read_bytes() == old


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
        restat=False,
        drift_report=None,
        migrate_manifest=False,
        verify_etag=False,
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

    def test_etag_change_redownloads_supersedes_and_resumes(self, tmp_path, cfg):
        old = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        new = gz_bytes(["SPY,9,9,9,9,9,0,9"])
        inventory = tmp_path / "m" / md.INVENTORY_NAME
        e_old = entry_for(size=len(old), etag="aaaaaaaa11")
        md.write_inventory(inventory, [e_old])
        args = run_args(tmp_path)
        assert md.run(args, cfg=cfg, fetch_fn=writing_fetch({e_old.key: old})) == 0
        e_new = entry_for(size=len(new), etag="bbbbbbbb22")
        md.write_inventory(inventory, [e_new])
        assert md.run(args, cfg=cfg, fetch_fn=writing_fetch({e_new.key: new})) == 0
        record = md.load_manifest(tmp_path / "m" / md.MANIFEST_NAME)[e_new.key]
        assert record["etag"] == "bbbbbbbb22"
        assert record["supersedes"]["etag"] == "aaaaaaaa11"
        assert (tmp_path / "data" / record["supersedes"]["path"]).read_bytes() == old
        assert md.run(args, cfg=cfg, fetch_fn=writing_fetch({})) == 0  # now idle

    def test_verify_covers_superseded_archives(self, tmp_path, cfg):
        old = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        new = gz_bytes(["SPY,9,9,9,9,9,0,9"])
        inventory = tmp_path / "m" / md.INVENTORY_NAME
        args = run_args(tmp_path)
        md.write_inventory(inventory, [entry_for(size=len(old), etag="aaaaaaaa11")])
        assert md.run(args, cfg=cfg, fetch_fn=writing_fetch({entry_for().key: old})) == 0
        md.write_inventory(inventory, [entry_for(size=len(new), etag="bbbbbbbb22")])
        assert md.run(args, cfg=cfg, fetch_fn=writing_fetch({entry_for().key: new})) == 0
        verify_args = run_args(tmp_path)
        verify_args.verify = True
        assert md.run(verify_args, cfg=cfg) == 0
        (archive,) = (tmp_path / "data" / md.SUPERSEDED_DIR).rglob("*.superseded-*")
        archive.write_bytes(b"rotted")
        assert md.run(verify_args, cfg=cfg) == 1

    def test_unprovable_supersession_stops_the_run_without_retry(self, tmp_path, cfg):
        old = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        new = gz_bytes(["SPY,9,9,9,9,9,0,9"])
        inventory = tmp_path / "m" / md.INVENTORY_NAME
        args = run_args(tmp_path)
        e_old = entry_for(size=len(old), etag="aaaaaaaa11")
        md.write_inventory(inventory, [e_old])
        assert md.run(args, cfg=cfg, fetch_fn=writing_fetch({e_old.key: old})) == 0
        e_old.local_path(tmp_path / "data" / "files").unlink()
        fetches: list[str] = []
        inner = writing_fetch({e_old.key: new})

        def counting_fetch(cfg, entry, part):  # noqa: ANN001
            fetches.append(entry.key)
            return inner(cfg, entry, part)

        md.write_inventory(inventory, [entry_for(size=len(new), etag="bbbbbbbb22")])
        assert md.run(args, cfg=cfg, fetch_fn=counting_fetch) == 2
        assert len(fetches) == 1  # no retry pass
        assert (
            md.load_manifest(tmp_path / "m" / md.MANIFEST_NAME)[e_old.key]["etag"] == "aaaaaaaa11"
        )

    def test_verify_etag_mode_flags_a_bad_md5(self, tmp_path, cfg):
        payload = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        e1 = entry_for(size=len(payload), etag=hashlib.md5(payload).hexdigest())
        md.write_inventory(tmp_path / "m" / md.INVENTORY_NAME, [e1])
        assert md.run(run_args(tmp_path), cfg=cfg, fetch_fn=writing_fetch({e1.key: payload})) == 0
        args = run_args(tmp_path)
        args.verify_etag = True
        assert md.run(args, cfg=cfg) == 0
        dest = e1.local_path(tmp_path / "data" / "files")
        flipped = bytearray(payload)
        flipped[len(flipped) // 2] ^= 0xFF
        dest.write_bytes(bytes(flipped))
        assert md.run(args, cfg=cfg) == 1

    def test_stale_inventory_refuses_without_downloading(self, tmp_path, cfg):
        payload = gz_bytes(["SPY,1,2,3,4,1,0,1"])
        e1 = entry_for(size=len(payload), etag="")
        md.write_inventory(tmp_path / "m" / md.INVENTORY_NAME, [e1])
        assert md.run(run_args(tmp_path), cfg=cfg, fetch_fn=writing_fetch({})) == 2

    def test_migrate_manifest_mode(self, tmp_path, cfg):
        e1 = entry_for(size=10)
        manifest_dir = tmp_path / "m"
        md.append_manifest(manifest_dir / md.MANIFEST_NAME, record_for(e1))
        args = run_args(tmp_path)
        args.migrate_manifest = True
        (manifest_dir / "servetimes_x.jsonl").write_text(servetimes_line(e1.key, "e1", 11))
        assert md.run(args, cfg=cfg) == 1  # size mismatch fails loudly, nothing appended
        assert "etag" not in md.load_manifest(manifest_dir / md.MANIFEST_NAME)[e1.key]
        (manifest_dir / "servetimes_x.jsonl").write_text(servetimes_line(e1.key, "e1", 10))
        assert md.run(args, cfg=cfg) == 0
        assert md.load_manifest(manifest_dir / md.MANIFEST_NAME)[e1.key]["etag"] == "e1"


class TestRestat:
    def seed(self, tmp_path, etag="e1", size=10):
        e1 = entry_for(size=size, etag=etag)
        manifest = tmp_path / "m" / md.MANIFEST_NAME
        md.append_manifest(manifest, {"key": e1.key, "bytes": 10, "etag": "e1"})
        return e1

    def seed_second_day(self, tmp_path):
        later = entry_for(date="2003-10-01", size=10, etag="e1")
        md.append_manifest(
            tmp_path / "m" / md.MANIFEST_NAME, {"key": later.key, "bytes": 10, "etag": "e1"}
        )
        return later

    def listing(self, key, size, etag):
        # the shared fake serves etag "x"; build a one-off runner with the etag asked for
        xml = LIST_XML_TEMPLATE.format(
            contents=contents_xml([(key, size)]).replace("&quot;x&quot;", f"&quot;{etag}&quot;"),
            count=1,
            token="",
        )

        def runner(args, stdin=None):  # noqa: ANN001
            body = (
                xml
                if "day_aggs_v1" not in args[-1]
                else LIST_XML_TEMPLATE.format(contents="", count=0, token="")
            )
            return subprocess.CompletedProcess(args, 0, body.encode(), b"")

        return runner

    def restat_args(self, tmp_path):
        args = run_args(tmp_path)
        args.restat = True
        args.drift_report = tmp_path / "drift.json"
        return args

    def test_clean_restat_writes_empty_report_exit_0(self, tmp_path, cfg):
        e1 = self.seed(tmp_path)
        runner = self.listing(e1.key, 10, "e1")
        assert md.run(self.restat_args(tmp_path), cfg=cfg, list_runner=runner) == 0
        assert json.loads((tmp_path / "drift.json").read_text()) == []

    def test_etag_drift_with_equal_size_exits_1(self, tmp_path, cfg):
        e1 = self.seed(tmp_path)
        runner = self.listing(e1.key, 10, "e2")
        assert md.run(self.restat_args(tmp_path), cfg=cfg, list_runner=runner) == 1
        (row,) = json.loads((tmp_path / "drift.json").read_text())
        assert row["key"] == e1.key
        assert row["changed"] == ["etag"]
        assert row["manifest"]["etag"] == "e1"
        assert row["listed"]["etag"] == "e2"

    def test_size_drift_and_vanished_key(self, tmp_path, cfg):
        e1 = self.seed(tmp_path)
        drift = md.restat_drift(
            md.load_manifest(tmp_path / "m" / md.MANIFEST_NAME),
            [md.KeyEntry(e1.key, e1.dataset, e1.date, size=11, etag="e1")],
        )
        assert drift[0]["changed"] == ["size"]
        gone = md.restat_drift(md.load_manifest(tmp_path / "m" / md.MANIFEST_NAME), [])
        assert gone[0]["changed"] == ["missing"]
        assert gone[0]["listed"] is None

    def test_new_vendor_key_is_not_drift(self, tmp_path):
        e1 = self.seed(tmp_path)
        newer = entry_for(date="2003-09-11", size=5, etag="n1")
        listed = [e1, newer]
        assert md.restat_drift(md.load_manifest(tmp_path / "m" / md.MANIFEST_NAME), listed) == []

    def test_restat_refuses_etagless_manifest(self, tmp_path, cfg):
        e1 = entry_for(size=10)
        md.append_manifest(tmp_path / "m" / md.MANIFEST_NAME, {"key": e1.key, "bytes": 10})
        runner = self.listing(e1.key, 10, "e1")
        assert md.run(self.restat_args(tmp_path), cfg=cfg, list_runner=runner) == 2
        assert not (tmp_path / "drift.json").exists()

    def test_date_filter_scopes_the_drift_check(self, tmp_path, cfg):
        e1 = self.seed(tmp_path)
        later = self.seed_second_day(tmp_path)
        # both keys drifted on the vendor, but only the first is inside the date range
        xml = LIST_XML_TEMPLATE.format(
            contents=contents_xml([(e1.key, 10), (later.key, 10)]).replace("x&quot;", "z&quot;"),
            count=2,
            token="",
        )

        def runner(args, stdin=None):  # noqa: ANN001
            body = (
                xml
                if "day_aggs_v1" not in args[-1]
                else LIST_XML_TEMPLATE.format(contents="", count=0, token="")
            )
            return subprocess.CompletedProcess(args, 0, body.encode(), b"")

        args = self.restat_args(tmp_path)
        args.date_to = "2003-09-30"
        assert md.run(args, cfg=cfg, list_runner=runner) == 1
        (row,) = json.loads((tmp_path / "drift.json").read_text())
        assert row["key"] == e1.key  # the October key is out of scope, not reported

    def test_new_keys_counted_within_the_date_scope(self, tmp_path, cfg, capsys):
        e1 = self.seed(tmp_path)
        runner = self.listing(e1.key, 10, "e1")
        assert md.run(self.restat_args(tmp_path), cfg=cfg, list_runner=runner) == 0
        assert "0 new to the vendor" in capsys.readouterr().out
        xml = LIST_XML_TEMPLATE.format(
            contents=contents_xml([(e1.key, 10), (entry_for(date="2003-09-12").key, 5)]).replace(
                "x&quot;", "e1&quot;"
            ),
            count=2,
            token="",
        )
        empty = LIST_XML_TEMPLATE.format(contents="", count=0, token="")

        def two(args, stdin=None):  # noqa: ANN001
            body = empty if "day_aggs_v1" in args[-1] else xml
            return subprocess.CompletedProcess(args, 0, body.encode(), b"")

        md.run(self.restat_args(tmp_path), cfg=cfg, list_runner=two)
        assert "1 new to the vendor" in capsys.readouterr().out
