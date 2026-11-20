import argparse
import json
import re
from datetime import date
from pathlib import Path

import pytest

from src.intelligence.bars.archive_end import (
    ARCHIVE_END_PIN,
    ArchiveEndPinError,
    add_archive_end_argument,
    read_archive_end_pin,
    resolve_archive_end,
)


def _pin(tmp_path, **over):
    record = {
        "archive_end": "2026-11-16",
        "pinned_on": "2026-11-16",
        "ruling": "runbook",
        "last_file_day_when_ruled": "2026-11-13",
        "manifest_sha256_at_record": "ab" * 32,
    } | over
    path = tmp_path / "pin.json"
    path.write_text(json.dumps({k: v for k, v in record.items() if v is not None}))
    return path


def test_the_recorded_pin_is_2026_11_16_and_names_its_manifest_hash():
    pin = read_archive_end_pin()
    assert pin.archive_end == date(2026, 11, 16)
    assert len(pin.manifest_sha256_at_record) == 64 and pin.ruling
    assert resolve_archive_end() == date(2026, 11, 16)
    assert ARCHIVE_END_PIN.name == "massive_archive_end.json"


def test_a_missing_or_unparseable_pin_raises(tmp_path):
    with pytest.raises(ArchiveEndPinError, match="unreadable"):
        read_archive_end_pin(tmp_path / "absent.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(ArchiveEndPinError, match="unreadable"):
        read_archive_end_pin(bad)


@pytest.mark.parametrize("field", ["archive_end", "ruling", "manifest_sha256_at_record"])
def test_a_missing_field_raises(tmp_path, field):
    with pytest.raises(ArchiveEndPinError, match=field):
        read_archive_end_pin(_pin(tmp_path, **{field: None}))


def test_a_bad_date_raises(tmp_path):
    with pytest.raises(ArchiveEndPinError, match="bad date"):
        read_archive_end_pin(_pin(tmp_path, archive_end="2026-13-40"))


def test_the_pin_is_not_a_function_of_a_manifest_file(tmp_path):
    # a manifest growing past the pin changes nothing: the pin file is the only input
    path = _pin(tmp_path, archive_end="2026-11-16")
    assert resolve_archive_end(path=path) == date(2026, 11, 16)


def test_an_override_is_explicit_and_loud(tmp_path, capsys):
    parser = argparse.ArgumentParser()
    add_archive_end_argument(parser)
    assert parser.parse_args([]).archive_end is None
    given = parser.parse_args(["--archive-end", "2026-12-01"]).archive_end
    assert resolve_archive_end(given, path=tmp_path / "absent.json") == date(2026, 12, 1)
    assert "rehearsal override" in capsys.readouterr().err


def test_a_pin_that_is_not_the_first_session_after_the_ruled_last_file_day_is_refused(tmp_path):
    for bad in ("2026-11-19", "2026-11-14"):  # a later session, a Saturday
        with pytest.raises(ArchiveEndPinError, match="first session"):
            read_archive_end_pin(_pin(tmp_path, archive_end=bad))
    with pytest.raises(ArchiveEndPinError, match="first session"):
        read_archive_end_pin(_pin(tmp_path, pinned_on="2026-11-17"))  # pinned after its own date


def test_the_runbook_seam_equals_the_recorded_pin():
    runbook = Path(__file__).resolve().parents[2] / "docs/operations/massive-step7-runbook.md"
    seam = re.search(r"^SEAM=(\d{4}-\d{2}-\d{2})", runbook.read_text(), flags=re.M).group(1)
    assert date.fromisoformat(seam) == read_archive_end_pin().archive_end
