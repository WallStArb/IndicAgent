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
    """A vendor listing and a manifest; the production ``absent_from_manifest`` runs over them.

    ``absent`` dates are listed but not in the manifest even though older than its newest day;
    ``fail_once`` (dataset, date) pairs fail their first download; ``dl`` fails every download."""

    def __init__(
        self,
        listed,
        archived,
        raw,
        *,
        quiet=True,
        dl=0,
        load=0,
        bad=(),
        drift=(),
        quiet_after=None,
        absent=(),
        fail_once=(),
        load_fail=(),
    ):
        self.listed, self.raw = listed, dict(raw)
        self.manifest = {entry(day, ds).key: {"etag": "e"} for ds, day in _iso(archived).items()}
        self.manifest |= {
            e.key: {"etag": "e"}
            for e in listed
            if D(e.date) <= archived[e.dataset] and e.date not in absent
        }
        self.quiet, self.dl, self.load_code, self.bad = quiet, dl, load, list(bad)
        self.drift_rows, self.quiet_after, self.quiet_calls = list(drift), quiet_after, 0
        self.fail_once, self.load_fail = set(fail_once), set(load_fail)
        self.calls: list = []

    def archived_last(self, dataset):
        return max(D(k.rsplit("/", 1)[1][:10]) for k in self.manifest if f"/{dataset}/" in k)

    def steps(self) -> nightly.Steps:
        def download(dataset, window):
            self.calls.append(("download", dataset, window))
            day = window.first.isoformat()
            if self.dl or (dataset, day) in self.fail_once:
                self.fail_once.discard((dataset, day))
                return 1
            self.manifest[entry(day, dataset).key] = {"etag": "e"}  # a good download is recorded
            return 0

        def load(tf, year, month):
            self.calls.append(("load", tf, year, month))
            return 2 if (tf, year, month) in self.load_fail else self.load_code

        def require_quiet():
            self.calls.append(("quiet",))
            self.quiet_calls += 1
            if not self.quiet or (self.quiet_after and self.quiet_calls > self.quiet_after):
                raise InstallRefused("loader running")

        def write_report(name, rows):
            self.calls.append(("write_report", name, len(rows)))
            return "report.json"

        return nightly.Steps(
            vendor_entries=lambda: self.listed,
            archived_last=self.archived_last,
            to_download=lambda es: nightly.absent_from_manifest(es, self.manifest),
            drift=lambda es: self.drift_rows,
            write_report=write_report,
            unverified=lambda es: self.bad,
            raw_newest=lambda tf: self.raw[tf],
            require_quiet=require_quiet,
            download=download,
            load=load,
        )


def _iso(archived):
    return {ds: day.isoformat() for ds, day in archived.items()}


ARCHIVED = {"day_aggs_v1": D("2026-11-13"), "minute_aggs_v1": D("2026-11-13")}
RAW = {"1d": D("2026-11-13"), "5m": D("2026-11-13")}


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
    assert nightly.run_night(fake.steps(), apply=True) == (0, "success")
    assert fake.calls == []
    assert "nothing new" in capsys.readouterr().out


def test_a_new_day_downloads_each_dataset_then_loads_1d_before_5m():
    fake = Fake(both("2026-11-13") + both("2026-11-16"), ARCHIVED, RAW)
    assert nightly.run_night(fake.steps(), apply=True) == (0, "success")
    window = nightly.Window(D("2026-11-16"), D("2026-11-16"))
    assert fake.calls == [
        ("quiet",),
        ("download", "day_aggs_v1", window),
        ("download", "minute_aggs_v1", window),
        ("quiet",),
        ("load", "1d", 2026, 11),
        ("load", "5m", 2026, 11),
    ]


def test_dry_run_reports_the_fetch_and_writes_nothing(capsys):
    fake = Fake(both("2026-11-16"), ARCHIVED, RAW, drift=[{"key": "k"}])
    assert nightly.run_night(fake.steps(), apply=False) == (0, "drift")
    assert fake.calls == []
    out = capsys.readouterr().out
    assert "fetch: 2 files" in out and "dry run" in out


def test_a_failed_quiet_check_refuses_before_any_download_or_load():
    fake = Fake(both("2026-11-16"), ARCHIVED, RAW, quiet=False)
    assert nightly.run_night(fake.steps(), apply=True) == (1, "partial")
    assert fake.calls == [("quiet",)]


def test_a_failed_download_exits_1_and_loads_nothing():
    fake = Fake(both("2026-11-16"), ARCHIVED, RAW, dl=1)
    assert nightly.run_night(fake.steps(), apply=True).code == 1
    assert not [c for c in fake.calls if c[0] == "load"]


def test_an_unverified_file_is_never_loaded_even_when_the_download_exits_0():
    fake = Fake(both("2026-11-16"), ARCHIVED, RAW, bad=["some/key"])
    assert nightly.run_night(fake.steps(), apply=True).code == 1
    assert not [c for c in fake.calls if c[0] == "load"]


def test_a_failed_load_exits_1_but_still_tries_the_other_timeframe():
    fake = Fake(both("2026-11-16"), ARCHIVED, RAW, load=2)
    assert nightly.run_night(fake.steps(), apply=True).code == 1
    assert [c[1] for c in fake.calls if c[0] == "load"] == ["1d", "5m"]


def test_a_load_left_by_an_earlier_night_heals_without_a_download():
    archived = {"day_aggs_v1": D("2026-11-16"), "minute_aggs_v1": D("2026-11-16")}
    fake = Fake(both("2026-11-16"), archived, RAW)
    assert nightly.run_night(fake.steps(), apply=True).code == 0
    assert fake.calls == [
        ("quiet",),
        ("quiet",),
        ("load", "1d", 2026, 11),
        ("load", "5m", 2026, 11),
    ]


def test_an_empty_raw_refuses():
    fake = Fake(both("2026-11-16"), ARCHIVED, {"1d": None, "5m": RAW["5m"]})
    assert nightly.run_night(fake.steps(), apply=True).code == 1
    assert fake.calls == []


def test_datasets_with_different_archived_days_each_fetch_their_own_gap():
    archived = {"day_aggs_v1": D("2026-11-16"), "minute_aggs_v1": D("2026-11-13")}
    fake = Fake(both("2026-11-16") + both("2026-11-13"), archived, RAW)
    assert nightly.run_night(fake.steps(), apply=True).code == 0
    downloads = [c for c in fake.calls if c[0] == "download"]
    assert [d[1] for d in downloads] == ["minute_aggs_v1"]


def test_a_download_crossing_a_month_loads_both_months_per_timeframe():
    archived = {"day_aggs_v1": D("2026-10-30"), "minute_aggs_v1": D("2026-10-30")}
    raw = {"1d": D("2026-10-30"), "5m": D("2026-10-30")}
    fake = Fake(both("2026-10-30") + both("2026-11-02"), archived, raw)
    assert nightly.run_night(fake.steps(), apply=True).code == 0
    assert [c for c in fake.calls if c[0] == "load"] == [
        ("load", "1d", 2026, 10),
        ("load", "1d", 2026, 11),
        ("load", "5m", 2026, 10),
        ("load", "5m", 2026, 11),
    ]


def test_drift_writes_the_report_triggers_no_download_or_load_and_exits_0():
    fake = Fake(both("2026-11-13"), ARCHIVED, RAW, drift=[{"key": "a"}, {"key": "b"}])
    assert nightly.run_night(fake.steps(), apply=True) == (0, "drift")
    assert fake.calls == [("write_report", "etag_drift", 2)]


def test_drift_does_not_stop_a_new_day_from_loading_and_stays_status_drift():
    fake = Fake(both("2026-11-16"), ARCHIVED, RAW, drift=[{"key": "a"}])
    assert nightly.run_night(fake.steps(), apply=True) == (0, "drift")
    assert ("load", "1d", 2026, 11) in fake.calls and (
        "write_report",
        "etag_drift",
        1,
    ) in fake.calls


def test_a_blank_etag_exits_1_without_a_crash(capsys):
    fake = Fake(both("2026-11-16"), ARCHIVED, RAW)
    steps = fake.steps()

    def blank():
        raise nightly.md.MissingServeFieldsError("listing entry some/key has no ETag")

    steps = nightly.Steps(**{**steps.__dict__, "vendor_entries": blank})
    assert nightly.run_night(steps, apply=True) == (1, "partial")
    assert "some/key" in capsys.readouterr().out
    assert fake.calls == []


def test_the_quiet_check_is_asked_again_before_the_load_and_refuses_it():
    fake = Fake(both("2026-11-16"), ARCHIVED, RAW, quiet_after=1)  # quiet at start, not after
    assert nightly.run_night(fake.steps(), apply=True).code == 1
    assert [c[0] for c in fake.calls] == ["quiet", "download", "download", "quiet"]


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


def _args(tmp_path):
    import argparse

    return argparse.Namespace(
        apply=True,
        data_root=tmp_path,
        manifest_dir=tmp_path / "manifest",
        env_file=tmp_path / ".env",
        concurrency=3,
        min_free_gb=7,
    )


def test_build_steps_passes_the_download_and_load_arguments(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(nightly.md, "S3Config", lambda **_: "cfg")
    monkeypatch.setattr(
        nightly.md,
        "run",
        lambda args, cfg, **kw: seen.update(dl=args, cfg=cfg, kw=kw) or 0,
    )
    monkeypatch.setattr(nightly.loader, "run", lambda args: seen.update(load=args) or 0)
    steps = nightly.build_steps(_args(tmp_path))

    assert steps.download("day_aggs_v1", nightly.Window(D("2026-11-14"), D("2026-11-16"))) == 0
    dl = seen["dl"]
    assert (dl.date_from, dl.date_to) == ("2026-11-14", "2026-11-16")
    assert dl.refresh_inventory is False and (dl.concurrency, dl.min_free_gb) == (3, 7)
    assert dl.datasets == ["day_aggs_v1"]
    assert seen["cfg"] == "cfg" and seen["kw"] == {"emit_metrics": False}

    assert steps.load("5m", 2026, 11) == 0
    load = seen["load"]
    assert (load.timeframe, load.years, load.month, load.apply) == ("5m", [2026], 11, True)
    assert load.gap_list is None and load.all_tickers is False  # the newest installed map


def test_build_steps_calls_a_missing_or_stale_etag_unverified(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(nightly.md, "S3Config", lambda **_: "cfg")
    manifest_dir = tmp_path / "manifest"
    manifest_dir.mkdir()
    good, stale, absent = (
        entry(d, "day_aggs_v1") for d in ("2026-11-13", "2026-11-14", "2026-11-15")
    )
    records = [{"key": good.key, "etag": "e"}, {"key": stale.key, "etag": "old"}]
    (manifest_dir / "manifest.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")
    steps = nightly.build_steps(_args(tmp_path))
    assert steps.unverified([good, stale, absent]) == [stale.key, absent.key]


def test_build_steps_to_download_is_absent_keys_and_never_a_changed_etag(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(nightly.md, "S3Config", lambda **_: "cfg")
    (tmp_path / "manifest").mkdir()
    old, new = entry("2026-11-13", "day_aggs_v1"), entry("2026-11-16", "day_aggs_v1")
    mrows = [entry(d, ds) for ds in nightly._TIMEFRAME_DATASET.values() for d in ("2026-11-13",)]
    (tmp_path / "manifest" / "manifest.jsonl").write_text(
        "\n".join(json.dumps({"key": e.key, "etag": "e", "bytes": 10}) for e in mrows) + "\n"
    )
    steps = nightly.build_steps(_args(tmp_path))
    reposted = KeyEntry(old.key, old.dataset, old.date, 10, "other-etag")  # drift, not a fetch
    assert steps.to_download([reposted, new]) == [new]
    assert [r["key"] for r in steps.drift([reposted, new])] == [old.key] + [
        e.key for e in mrows if e.key != old.key
    ]


def test_a_partial_multi_day_download_is_finished_the_next_night_and_its_month_loaded():
    archived = {"day_aggs_v1": D("2026-10-30"), "minute_aggs_v1": D("2026-10-30")}
    raw = {"1d": D("2026-10-30"), "5m": D("2026-10-30")}
    listed = both("2026-10-30") + both("2026-11-02") + both("2026-11-03") + both("2026-11-04")
    fake = Fake(listed, archived, raw, fail_once={("day_aggs_v1", "2026-11-03")})
    assert nightly.run_night(fake.steps(), apply=True) == (1, "partial")  # 11-02 landed, 11-03 not
    assert not [c for c in fake.calls if c[0] == "load"]
    assert fake.archived_last("day_aggs_v1") == D("2026-11-02")

    fake.calls.clear()
    assert nightly.run_night(fake.steps(), apply=True) == (0, "success")
    assert (
        "download",
        "day_aggs_v1",
        nightly.Window(D("2026-11-03"), D("2026-11-03")),
    ) in fake.calls
    assert [c for c in fake.calls if c[0] == "load"] == [
        ("load", "1d", 2026, 10),
        ("load", "1d", 2026, 11),
        ("load", "5m", 2026, 10),
        ("load", "5m", 2026, 11),
    ]


def test_a_late_old_key_is_fetched_not_loaded_reported_and_exits_1_while_recent_days_load():
    archived = {"day_aggs_v1": D("2026-11-13"), "minute_aggs_v1": D("2026-11-13")}
    raw = {"1d": D("2026-10-30"), "5m": D("2026-10-30")}
    # 09-15 is a hole before October (late, not loaded); 10-29 is inside the first loadable month
    listed = both("2026-09-15") + both("2026-10-29") + both("2026-11-13")
    fake = Fake(listed, archived, raw, absent={"2026-09-15", "2026-10-29"})
    assert nightly.run_night(fake.steps(), apply=True) == (1, "manual_load")
    fetched = [(c[1], c[2].first.isoformat()) for c in fake.calls if c[0] == "download"]
    assert ("day_aggs_v1", "2026-09-15") in fetched and ("minute_aggs_v1", "2026-10-29") in fetched
    assert [c for c in fake.calls if c[0] == "load"] == [
        ("load", "1d", 2026, 10),
        ("load", "1d", 2026, 11),
        ("load", "5m", 2026, 10),
        ("load", "5m", 2026, 11),
    ]
    assert ("write_report", "late_keys", 2) in fake.calls  # both datasets of 09-15, not 10-29


def test_a_late_key_is_reported_even_when_a_load_fails_and_the_night_stays_partial():
    archived = {"day_aggs_v1": D("2026-11-13"), "minute_aggs_v1": D("2026-11-13")}
    raw = {"1d": D("2026-10-30"), "5m": D("2026-10-30")}
    listed = both("2026-09-15") + both("2026-11-13")
    fake = Fake(listed, archived, raw, absent={"2026-09-15"}, load_fail={("1d", 2026, 10)})
    assert nightly.run_night(fake.steps(), apply=True) == (1, "partial")
    assert ("write_report", "late_keys", 2) in fake.calls


def test_a_late_key_is_reported_when_a_later_download_fails_after_it_landed():
    archived = {"day_aggs_v1": D("2026-11-13"), "minute_aggs_v1": D("2026-11-13")}
    raw = {"1d": D("2026-10-30"), "5m": D("2026-10-30")}
    listed = both("2026-09-15") + both("2026-11-16")
    fake = Fake(
        listed, archived, raw, absent={"2026-09-15"}, fail_once={("day_aggs_v1", "2026-11-16")}
    )
    assert nightly.run_night(fake.steps(), apply=True) == (1, "partial")
    # day_aggs 09-15 landed before day_aggs 11-16 failed: the report names it; the night stopped
    assert ("write_report", "late_keys", 1) in fake.calls


def test_a_failed_month_stops_that_timeframe_so_raw_never_advances_past_it():
    archived = {"day_aggs_v1": D("2026-10-30"), "minute_aggs_v1": D("2026-10-30")}
    raw = {"1d": D("2026-10-30"), "5m": D("2026-10-30")}
    fake = Fake(
        both("2026-10-30") + both("2026-11-02"), archived, raw, load_fail={("1d", 2026, 10)}
    )
    assert nightly.run_night(fake.steps(), apply=True) == (1, "partial")
    assert [c for c in fake.calls if c[0] == "load"] == [
        ("load", "1d", 2026, 10),
        ("load", "5m", 2026, 10),
        ("load", "5m", 2026, 11),
    ]


def test_a_changed_etag_on_a_recorded_key_is_never_refetched():
    listed = both("2026-11-13")
    fake = Fake(listed, ARCHIVED, RAW, drift=[{"key": listed[0].key}])
    reposted = [nightly.md.KeyEntry(e.key, e.dataset, e.date, 99, "new") for e in listed]
    assert nightly.absent_from_manifest(reposted, fake.manifest) == []
