"""Massive reference capture parser: manifest lines of both layouts (real sample lines)."""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.intelligence.bars.massive_reference import (
    ReferenceCaptureError,
    discover_manifests,
    manifest_layout,
    parse_manifest_line,
    read_body,
    vendor_of_root,
)

LEGACY_LINE = (
    '{"endpoint": "/v3/reference/splits", "url": "https://api.massive.com/v3/reference/splits'
    '?cursor=YXA9", "params": null, "status": 200, "sha256": "' + "a" * 64 + '", '
    '"captured_at": "2026-11-10T16:43:40.310597+00:00", "note": "splits full page28", '
    '"file": "splits/page0028.json", "bytes": 12}'
)
LEGACY_SINGLE = LEGACY_LINE.replace("splits full page28", "types full").replace(
    "splits/page0028.json", "ticker_types/all.json"
)
DATED_404 = (
    '{"endpoint": "events", "key": "AAB.WS@2008-02-11", "page": 1, "url": '
    '"https://api.massive.com/vX/reference/tickers/AAB.WS/events", "status": 404, "date": '
    '"Tue, 10 Nov 2026 15:49:53 GMT", "bytes": 111, "sha256": "' + "b" * 64 + '", "path": '
    '"events/20261110/AAB.WS%402008-02-11__p0001.json.gz", "fetched_at": '
    '"2026-11-10T15:49:53.533201Z"}'
)
DATED_AS_OF = (
    DATED_404.replace('"events"', '"overview"')
    .replace("/events", "?date=2008-02-11")
    .replace("404", "200")
)


def _parse(text: str, manifest: str, root: Path):
    return parse_manifest_line(text, root / manifest, 7, repo_root=root)


ROOT = Path("/repo")
LEGACY = "data/massive/reference/capture_log.jsonl"
DATED = "data/massive/reference/manifest/20261110.jsonl"


def test_legacy_paged_line():
    c = _parse(LEGACY_LINE, LEGACY, ROOT)
    assert (c.layout, c.endpoint, c.request_key, c.page) == (
        "legacy",
        "/v3/reference/splits",
        "splits full",
        29,
    )
    assert c.served_at == datetime(2026, 11, 10, 16, 43, 40, 310597, tzinfo=UTC)
    assert c.as_of is None
    assert c.manifest_path == LEGACY and c.manifest_line == 7
    assert c.file_path == "data/massive/reference/splits/page0028.json"


def test_legacy_single_file_is_page_one():
    c = _parse(LEGACY_SINGLE, LEGACY, ROOT)
    assert (c.request_key, c.page) == ("types full", 1)


def test_dated_not_found_keeps_status_key_and_date_header():
    c = _parse(DATED_404, DATED, ROOT)
    assert (c.layout, c.endpoint, c.request_key, c.page, c.http_status) == (
        "dated",
        "events",
        "AAB.WS@2008-02-11",
        1,
        404,
    )
    assert c.served_at == datetime(2026, 11, 10, 15, 49, 53, tzinfo=UTC)
    assert c.as_of is None
    assert (
        c.file_path == "data/massive/reference/events/20261110/AAB.WS%402008-02-11__p0001.json.gz"
    )


def test_as_of_comes_from_the_url_date_parameter():
    assert _parse(DATED_AS_OF, DATED, ROOT).as_of == date(2008, 2, 11)


def test_dated_without_date_header_falls_back_to_fetched_at():
    text = json.dumps({**json.loads(DATED_404), "date": ""})
    assert _parse(text, DATED, ROOT).served_at == datetime(
        2026, 11, 10, 15, 49, 53, 533201, tzinfo=UTC
    )


@pytest.mark.parametrize(
    "text",
    [
        "{not json",
        json.dumps({**json.loads(DATED_404), "sha256": "xyz"}),
        json.dumps({k: v for k, v in json.loads(DATED_404).items() if k != "key"}),
    ],
)
def test_malformed_line_raises(text):
    with pytest.raises(ReferenceCaptureError):
        _parse(text, DATED, ROOT)


def test_unknown_manifest_name_refused():
    with pytest.raises(ReferenceCaptureError):
        manifest_layout(Path("data/massive/reference/other.jsonl"))


def test_read_body_verifies_sha_and_decompresses(tmp_path):
    body = b'{"status":"NOT_FOUND"}'
    rel = "data/massive/reference/events/20261110/x.json.gz"
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_bytes(gzip.compress(body))
    line = json.dumps(
        {
            **json.loads(DATED_404),
            "path": "events/20261110/x.json.gz",
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
        }
    )
    capture = _parse(line, DATED, tmp_path)
    assert read_body(capture, repo_root=tmp_path) == body.decode()
    bad = _parse(line.replace(hashlib.sha256(body).hexdigest(), "c" * 64), DATED, tmp_path)
    with pytest.raises(ReferenceCaptureError, match="differs"):
        read_body(bad, repo_root=tmp_path)


def test_discover_manifests_orders_legacy_then_dated(tmp_path):
    (tmp_path / "manifest").mkdir()
    for name in ("capture_log.jsonl", "manifest/20261111.jsonl", "manifest/20261110.jsonl"):
        (tmp_path / name).write_text("")
    (tmp_path / "manifest" / "20261110.lock").write_text("")
    assert [p.name for p in discover_manifests(tmp_path)] == [
        "capture_log.jsonl",
        "20261110.jsonl",
        "20261111.jsonl",
    ]


def test_vendor_comes_from_the_root_directory():
    assert vendor_of_root(Path("data/massive/reference")) == "massive"
    assert vendor_of_root(Path("/x/data/ibkr/reference")) == "ibkr"
    for bad in ("data/massive/manifest", "data/Massive/reference", "reference"):
        with pytest.raises(ReferenceCaptureError):
            vendor_of_root(Path(bad))


def test_non_http_answer_has_no_status(tmp_path):
    manifest = tmp_path / "data" / "ibkr" / "reference" / "manifest" / "20261110.jsonl"
    manifest.parent.mkdir(parents=True)
    line = (
        '{"endpoint": "contract_details", "key": "BRK.B", "page": 1, "url": '
        '"ibkr://reqContractDetails?symbol=BRK%20B", "status": null, "date": null, "bytes": 2, '
        '"sha256": "' + "b" * 64 + '", "path": "contract_details/20261110/BRK.B.json.gz", '
        '"fetched_at": "2026-11-10T18:37:39.205738Z"}'
    )
    capture = parse_manifest_line(line, manifest, 1, repo_root=tmp_path)
    assert capture.http_status is None
    assert capture.request_key == "BRK.B"
    assert capture.served_at.isoformat() == "2026-11-10T18:37:39.205738+00:00"
