"""The Massive archive end: the first session canonical takes Alpaca instead of Massive.

One recorded, versioned pin (``config/bars/massive_archive_end.json``), never a function of the
downloader manifest: a file added to the manifest must not move the seam (the 2026-11-20 catch-up
did, in the old derivation, from 2026-11-16 to 2026-11-19). A pre-registered pin, not an APR key:
an operator-tunable seam invites tuning. Every script that needs the date reads it here; a missing
or malformed pin raises, and a rehearsal names its own date explicitly.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from src.intelligence.bars.sessions import nyse_sessions

ARCHIVE_END_PIN = (
    Path(__file__).resolve().parents[3] / "config" / "bars" / "massive_archive_end.json"
)
_REQUIRED = (
    "archive_end",
    "pinned_on",
    "ruling",
    "last_file_day_when_ruled",
    "manifest_sha256_at_record",
)


class ArchiveEndPinError(ValueError):
    """The archive end pin is missing or malformed."""


@dataclass(frozen=True)
class ArchiveEndPin:
    archive_end: date
    pinned_on: date
    ruling: str
    manifest_sha256_at_record: str


def read_archive_end_pin(path: Path = ARCHIVE_END_PIN) -> ArchiveEndPin:
    """The recorded pin; raises ArchiveEndPinError on a missing file, a missing field or a date
    that does not parse, so a script never runs on a guessed seam."""
    try:
        record = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ArchiveEndPinError(f"archive end pin {path} unreadable: {error}") from error
    missing = [key for key in _REQUIRED if not isinstance(record.get(key), str) or not record[key]]
    if missing:
        raise ArchiveEndPinError(f"archive end pin {path} lacks {missing}")
    try:
        pin = ArchiveEndPin(
            date.fromisoformat(record["archive_end"]),
            date.fromisoformat(record["pinned_on"]),
            record["ruling"],
            record["manifest_sha256_at_record"],
        )
        last_ruled = date.fromisoformat(record["last_file_day_when_ruled"])
    except ValueError as error:
        raise ArchiveEndPinError(f"archive end pin {path} holds a bad date: {error}") from error
    # The pin is the first NYSE session after the last file day when it was ruled; a hand edit to
    # a date that is no session, or one that does not follow that day, is refused.
    first_after = min(
        nyse_sessions(last_ruled + timedelta(days=1), last_ruled + timedelta(days=15))
    )
    if pin.archive_end != first_after or pin.pinned_on > pin.archive_end:
        raise ArchiveEndPinError(
            f"archive end pin {path}: archive_end {pin.archive_end} is not the first session "
            f"after the last file day when ruled ({first_after}), or pinned_on follows it"
        )
    return pin


def add_archive_end_argument(parser: argparse.ArgumentParser) -> None:
    """The one `--archive-end` option every consumer offers: a rehearsal's explicit date."""
    parser.add_argument(
        "--archive-end",
        type=date.fromisoformat,
        default=None,
        help="rehearsal only: an explicit archive end replacing the recorded pin "
        "(config/bars/massive_archive_end.json); a pinned run never passes it",
    )


def resolve_archive_end(override: date | None = None, path: Path = ARCHIVE_END_PIN) -> date:
    """The archive end a script runs with: the recorded pin, or `override` when a rehearsal names
    its own date explicitly (said on stderr; a pinned run never passes one)."""
    if override is None:
        return read_archive_end_pin(path).archive_end
    print(f"archive end {override} (rehearsal override, not the pin)", file=sys.stderr)
    return override
