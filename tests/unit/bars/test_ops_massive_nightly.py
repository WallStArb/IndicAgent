"""The Massive nightly leaf: window arithmetic, the no-op night, the quiet refusal, exit codes."""

from datetime import date

import pytest

from scripts.infrastructure.massive.massive_download import KeyEntry
from scripts.ops.bars import ops_massive_nightly as nightly
from services.ticker_entity_map_writer import InstallRefused

D = date.fromisoformat


def entry(day: str, dataset: str) -> KeyEntry:
    y, m, _ = day.split("-")
    return KeyEntry(f"us_stocks_sip/{dataset}/{y}/{m}/{day}.csv.gz", dataset, day, 10, "e")


def both(day: str) -> list[KeyEntry]:
    return [entry(day, "day_aggs_v1"), entry(day, "minute_aggs_v1")]


class Fake:
    """Records calls; every knob a test turns is a constructor argument."""

    def __init__(self, listed, archived, raw, *, quiet=True, dl=0, load=0, bad=()):
        self.listed, self.archived, self.raw = listed, dict(archived), dict(raw)
        self.quiet, self.dl, self.load_code, self.bad = quiet, dl, load, list(bad)
        self.calls: list = []

    def steps(self) -> nightly.Steps:
        def download(window):
            self.calls.append(("download", window))
            if self.dl == 0:  # a good download advances the manifest
                for e in self.listed:
                    self.archived[e.dataset] = max(self.archived[e.dataset], D(e.date))
            return self.dl

        def load(tf, year, month):
            self.calls.append(("load", tf, year, month))
            return self.load_code

        def require_quiet():
            self.calls.append(("quiet",))
            if not self.quiet:
                raise InstallRefused("loader running")

        return nightly.Steps(
            vendor_entries=lambda: self.listed,
            archived_last=lambda ds: self.archived[ds],
            to_download=lambda es: [e for e in es if D(e.date) > self.archived[e.dataset]],
            unverified=lambda es: self.bad,
            raw_newest=lambda tf: self.raw[tf],
            require_quiet=require_quiet,
            download=download,
            load=load,
        )


ARCHIVED = {"day_aggs_v1": D("2026-11-13"), "minute_aggs_v1": D("2026-11-13")}
RAW = {"1d": D("2026-11-13"), "5m": D("2026-11-13")}


def test_window_starts_after_the_oldest_dataset_and_ends_at_the_vendor_newest():
    window = nightly.fetch_window([D("2026-11-13"), D("2026-11-11")], D("2026-11-16"))
    assert window == nightly.Window(D("2026-11-12"), D("2026-11-16"))


def test_window_is_empty_when_the_archive_reaches_the_vendor_newest():
    assert nightly.fetch_window([D("2026-11-13")], D("2026-11-13")) is None
    assert nightly.fetch_window([D("2026-11-13")], None) is None


def test_months_touched_span_the_year_end_and_skip_a_current_raw():
    assert nightly.months_to_load(D("2026-12-30"), D("2027-02-02")) == [
        (2026, 12),
        (2027, 1),
        (2027, 2),
    ]
    assert nightly.months_to_load(D("2026-11-13"), D("2026-11-13")) == []
    assert nightly.months_to_load(None, D("2026-11-13")) == []


def test_a_current_night_is_a_loud_no_op_with_no_quiet_check(capsys):
    fake = Fake(both("2026-11-13"), ARCHIVED, RAW)
    assert nightly.run_night(fake.steps(), apply=True) == 0
    assert fake.calls == []
    assert "nothing new" in capsys.readouterr().out


def test_weekend_with_no_new_key_is_not_an_error():
    fake = Fake(both("2026-11-13"), ARCHIVED, RAW)  # Saturday: vendor has nothing past Friday
    assert nightly.run_night(fake.steps(), apply=True) == 0


def test_a_new_day_downloads_then_loads_1d_before_5m():
    fake = Fake(both("2026-11-13") + both("2026-11-16"), ARCHIVED, RAW)
    assert nightly.run_night(fake.steps(), apply=True) == 0
    assert fake.calls == [
        ("quiet",),
        ("download", nightly.Window(D("2026-11-14"), D("2026-11-16"))),
        ("load", "1d", 2026, 11),
        ("load", "5m", 2026, 11),
    ]


def test_dry_run_reports_the_window_and_writes_nothing(capsys):
    fake = Fake(both("2026-11-16"), ARCHIVED, RAW)
    assert nightly.run_night(fake.steps(), apply=False) == 0
    assert fake.calls == []
    out = capsys.readouterr().out
    assert "2026-11-14..2026-11-16" in out and "dry run" in out


def test_a_failed_quiet_check_refuses_before_any_download_or_load():
    fake = Fake(both("2026-11-16"), ARCHIVED, RAW, quiet=False)
    assert nightly.run_night(fake.steps(), apply=True) == 1
    assert fake.calls == [("quiet",)]


def test_a_failed_download_exits_1_and_loads_nothing():
    fake = Fake(both("2026-11-16"), ARCHIVED, RAW, dl=1)
    assert nightly.run_night(fake.steps(), apply=True) == 1
    assert not [c for c in fake.calls if c[0] == "load"]


def test_an_unverified_file_is_never_loaded_even_when_the_download_exits_0():
    fake = Fake(both("2026-11-16"), ARCHIVED, RAW, bad=["some/key"])
    assert nightly.run_night(fake.steps(), apply=True) == 1
    assert not [c for c in fake.calls if c[0] == "load"]


def test_a_failed_load_exits_1_but_still_tries_the_other_timeframe():
    fake = Fake(both("2026-11-16"), ARCHIVED, RAW, load=2)
    assert nightly.run_night(fake.steps(), apply=True) == 1
    assert [c[1] for c in fake.calls if c[0] == "load"] == ["1d", "5m"]


def test_a_load_left_by_an_earlier_night_heals_without_a_download():
    archived = {"day_aggs_v1": D("2026-11-16"), "minute_aggs_v1": D("2026-11-16")}
    fake = Fake(both("2026-11-16"), archived, RAW)
    assert nightly.run_night(fake.steps(), apply=True) == 0
    assert fake.calls == [("quiet",), ("load", "1d", 2026, 11), ("load", "5m", 2026, 11)]


def test_an_empty_raw_refuses():
    fake = Fake(both("2026-11-16"), ARCHIVED, {"1d": None, "5m": RAW["5m"]})
    assert nightly.run_night(fake.steps(), apply=True) == 1
    assert fake.calls == []


def test_last_file_day_is_per_dataset():
    from scripts.ops.bars.ops_massive_policy_plan import archive_end_of, last_file_day

    manifest = (
        b'{"key": "us_stocks_sip/day_aggs_v1/2026/11/2026-11-13.csv.gz"}\n'
        b'{"key": "us_stocks_sip/minute_aggs_v1/2026/11/2026-11-12.csv.gz"}\n'
    )
    assert last_file_day(manifest, "minute_aggs_v1") == D("2026-11-12")
    assert last_file_day(manifest) == D("2026-11-13")
    assert archive_end_of(manifest) == D("2026-11-16")  # the next session after Friday
    with pytest.raises(ValueError):
        last_file_day(b"", None)
