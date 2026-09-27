"""Known-answer fixtures for phase 185 exist and carry their documented counts.

These assertions pin the D-10 known-answer set: the 45/27/1864 dry-run section counts,
the 26 Flash Crash rows plus EWW 2006-11-07 among the MARKET_EVENT rows, and the
bar-count shapes of the exported CSV fixtures. If a regeneration of the CSVs changes
a count here, that is a deliberate re-pin and belongs in the same commit as the
regeneration, with the reason in tests/fixtures/bars/README.md.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from tests.unit.bars._builders import load_dry_run_report

_FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "bars"

_CSV_FIXTURES = (
    "price_sanity_status_rows.csv",
    "seam_candidates_mrna_alms.csv",
    "spy_5m_2025_11_28_half_day.csv",
    "spy_5m_dst_2025_03_10_2025_11_03.csv",
    "spy_1d_2024.csv",
)


def test_dry_run_report_section_counts():
    assert len(load_dry_run_report("CONFIRMED_CORRUPT")) == 45
    assert len(load_dry_run_report("MARKET_EVENT")) == 27
    assert len(load_dry_run_report("AMBIGUOUS")) == 1864


def test_market_event_rows_are_flash_crash_plus_eww():
    rows = load_dry_run_report("MARKET_EVENT")
    dates = Counter(r["timestamp"] for r in rows)
    flash_crash = sum(n for ts, n in dates.items() if ts.startswith("2010-05-06"))
    assert flash_crash == 26
    eww = [r for r in rows if r["symbol"] == "EWW"]
    assert len(eww) == 1
    assert eww[0]["timestamp"].startswith("2006-11-07")
    assert sum(dates.values()) == 27


def test_confirmed_corrupt_includes_known_extremes():
    rows = {(r["symbol"], r["timestamp"]): r for r in load_dry_run_report("CONFIRMED_CORRUPT")}
    assert ("IWO", "2009-05-26T00:00:00Z") in rows
    assert rows[("IWO", "2009-05-26T00:00:00Z")]["high"] == 1_000_000.0
    assert ("TRST", "2007-07-26T00:00:00Z") in rows
    assert ("ARE", "2007-02-27T00:00:00Z") in rows
    assert ("UHAL", "2022-11-09T00:00:00Z") in rows


def test_every_csv_fixture_exists_and_is_non_empty():
    for name in _CSV_FIXTURES:
        path = _FIXTURE_DIR / name
        assert path.is_file(), f"missing fixture: {name}"
        with path.open() as handle:
            rows = list(csv.reader(handle))
        assert len(rows) > 1, f"{name} has no data rows"


def test_spy_half_day_csv_has_42_bars():
    with (_FIXTURE_DIR / "spy_5m_2025_11_28_half_day.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 42
    assert rows[0]["timestamp"].startswith("2025-11-28T14:30")
    assert rows[-1]["timestamp"].startswith("2025-11-28T17:55")


def test_spy_dst_csv_has_78_bars_per_day():
    with (_FIXTURE_DIR / "spy_5m_dst_2025_03_10_2025_11_03.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    per_day: dict[str, int] = {}
    for r in rows:
        per_day[r["timestamp"][:10]] = per_day.get(r["timestamp"][:10], 0) + 1
    assert per_day == {"2025-03-10": 78, "2025-11-03": 78}
    # 2025-03-10 is EDT (13:30 UTC open); 2025-11-03 is EST (14:30 UTC open).
    first_by_day: dict[str, str] = {}
    for r in rows:
        day = r["timestamp"][:10]
        if day not in first_by_day:
            first_by_day[day] = r["timestamp"]
    assert first_by_day["2025-03-10"].startswith("2025-03-10T13:30")
    assert first_by_day["2025-11-03"].startswith("2025-11-03T14:30")


def test_status_rows_csv_covers_every_status_value():
    with (_FIXTURE_DIR / "price_sanity_status_rows.csv").open() as handle:
        statuses = Counter(r["price_sanity_status"] for r in csv.DictReader(handle))
    assert set(statuses) == {"confirmed_corrupt", "ambiguous", "plausible"}
    assert statuses == {
        "confirmed_corrupt": 67,  # 1d 15, 15m 19, 5m 20, 1h 13
        "ambiguous": 16,
        "plausible": 484,
    }
    assert sum(statuses.values()) == 567
