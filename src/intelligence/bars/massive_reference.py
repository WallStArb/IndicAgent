"""Massive reference capture: one manifest line in, one ``reference_raw`` row out.

Pure parsing plus the one file read that proves a line's bytes (admission design section 6,
step 3). Nothing is skipped and nothing is transformed: the body is the file's exact text, the
HTTP status is as served, and a NOT_FOUND answer (HTTP 404, ``{"status": "NOT_FOUND", ...}``)
is a row like any other, judged by its body downstream.

Two capture layouts exist, told apart by the manifest's name:

- ``capture_log.jsonl`` (``LEGACY``): the first, undated capture. Lines carry ``endpoint`` as a
  URL path, ``captured_at``, ``note`` and ``file`` (a plain ``pageNNNN.json``, hash over the file
  bytes). No ``key``, no ``page``, no HTTP Date header: ``request_key`` is the note with its
  trailing page token removed (the page is its own column), ``page`` is the file's page number
  plus one (``page0000`` is page 1; a single-file capture is page 1), ``served_at`` is
  ``captured_at``, which is at or after the true answer.
- ``manifest/YYYYMMDD.jsonl`` (``DATED``): the canonical layout. Lines carry ``endpoint`` as the
  capture's label, ``key``, ``page``, ``date`` (the HTTP Date header), ``fetched_at`` and ``path``
  (gzip; the hash is over the decompressed bytes, which are the bytes served).

``as_of`` is the ``date`` query parameter of the URL (an overview of a delisted ticker is asked
as of a date); NULL means the vendor's state at ``served_at``.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

VENDOR = "massive"
LEGACY = "legacy"
DATED = "dated"
LEGACY_MANIFEST_NAME = "capture_log.jsonl"
_DATED_MANIFEST = re.compile(r"^\d{8}\.jsonl$")
_LEGACY_PAGE_TOKEN = re.compile(r"\s*page\s*\d+$")
_LEGACY_FILE_PAGE = re.compile(r"page(\d+)\.json$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ReferenceCaptureError(ValueError):
    """A manifest line or its file is not what the capture claims; the load refuses."""


@dataclass(frozen=True)
class ReferenceCapture:
    """One manifest line, parsed and not yet backed by its file."""

    layout: str
    endpoint: str
    request_key: str
    page: int
    as_of: date | None
    url: str
    http_status: int
    served_at: datetime
    manifest_path: str  # repo-relative
    manifest_line: int  # 1-based physical line
    file_path: str  # repo-relative
    file_sha256: str
    file_bytes: int


def manifest_layout(manifest: Path) -> str:
    """The layout a manifest file belongs to; anything else is refused, never guessed."""
    if manifest.name == LEGACY_MANIFEST_NAME:
        return LEGACY
    if manifest.parent.name == "manifest" and _DATED_MANIFEST.match(manifest.name):
        return DATED
    raise ReferenceCaptureError(f"{manifest}: not a known reference manifest name")


def discover_manifests(reference_root: Path) -> list[Path]:
    """Every manifest under a reference root, legacy first, then dated by date."""
    found = [p for p in (reference_root / LEGACY_MANIFEST_NAME,) if p.is_file()]
    found += sorted(
        p for p in (reference_root / "manifest").glob("*.jsonl") if _DATED_MANIFEST.match(p.name)
    )
    return found


def _as_of(url: str) -> date | None:
    values = parse_qs(urlsplit(url).query).get("date", [])
    if not values:
        return None
    if len(values) > 1:
        raise ReferenceCaptureError(f"{url}: more than one date parameter")
    return date.fromisoformat(values[0])


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ReferenceCaptureError(f"timestamp without a zone: {value!r}")
    return value.astimezone(UTC)


def _served_at(entry: dict, layout: str) -> datetime:
    """The vendor's HTTP Date where the capture recorded one, else the capture time."""
    if layout == DATED:
        header = entry.get("date")
        if header:
            return _utc(parsedate_to_datetime(header))
        return _utc(datetime.fromisoformat(entry["fetched_at"]))
    return _utc(datetime.fromisoformat(entry["captured_at"]))


def parse_manifest_line(
    text: str, manifest: Path, line_number: int, *, repo_root: Path
) -> ReferenceCapture:
    """One manifest line to its capture. Raises ReferenceCaptureError on anything malformed."""
    layout = manifest_layout(manifest)
    try:
        entry = json.loads(text)
        url = entry["url"]
        sha = entry["sha256"]
        if not isinstance(sha, str) or not _SHA256.match(sha):
            raise ReferenceCaptureError(f"{manifest}:{line_number}: sha256 is not 64 hex digits")
        root = manifest.parent.parent if layout == DATED else manifest.parent
        if layout == DATED:
            relative, page, key = entry["path"], int(entry["page"]), entry["key"]
        else:
            relative = entry["file"]
            matched = _LEGACY_FILE_PAGE.search(relative)
            page = int(matched.group(1)) + 1 if matched else 1
            key = _LEGACY_PAGE_TOKEN.sub("", entry["note"])
        return ReferenceCapture(
            layout=layout,
            endpoint=entry["endpoint"],
            request_key=key,
            page=page,
            as_of=_as_of(url),
            url=url,
            http_status=int(entry["status"]),
            served_at=_served_at(entry, layout),
            manifest_path=manifest.relative_to(repo_root).as_posix(),
            manifest_line=line_number,
            file_path=(root / relative).relative_to(repo_root).as_posix(),
            file_sha256=sha,
            file_bytes=int(entry["bytes"]),
        )
    except ReferenceCaptureError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise ReferenceCaptureError(f"{manifest}:{line_number}: {error!r}") from error


def read_body(capture: ReferenceCapture, *, repo_root: Path) -> str:
    """The captured body text, after proving the file holds the bytes the manifest hashed.

    A ``.gz`` file is decompressed first: the manifest's hash and byte count are over the bytes
    served. Returns the exact text (UTF-8), for jsonb to parse in the database.
    """
    raw = (repo_root / capture.file_path).read_bytes()
    served = gzip.decompress(raw) if capture.file_path.endswith(".gz") else raw
    digest = hashlib.sha256(served).hexdigest()
    if digest != capture.file_sha256 or len(served) != capture.file_bytes:
        raise ReferenceCaptureError(
            f"{capture.file_path}: sha256 {digest} ({len(served)} bytes) differs from the "
            f"manifest's {capture.file_sha256} ({capture.file_bytes} bytes)"
        )
    return served.decode("utf-8")
