from datetime import date
from types import SimpleNamespace

import pytest

from scripts.infrastructure.massive import massive_tape_slice as mod
from scripts.infrastructure.massive.massive_tape_slice import local_path, pick_last_listed, tape_key


def test_pick_last_listed_takes_the_newest_published_sessions_oldest_first():
    sessions = [date(2026, 11, d) for d in (16, 17, 18, 19, 20)]
    listed = {date(2026, 11, d) for d in (16, 17, 18, 19)}  # the 20th is not published yet
    assert pick_last_listed(sessions, listed, 2) == [date(2026, 11, 18), date(2026, 11, 19)]


def test_pick_last_listed_returns_fewer_when_few_are_published():
    assert pick_last_listed([date(2026, 11, 16)], {date(2026, 11, 16)}, 5) == [date(2026, 11, 16)]


def test_key_and_path_follow_the_bucket_layout():
    key = tape_key("quotes_v1", date(2026, 3, 9))
    assert key == "us_stocks_sip/quotes_v1/2026/03/2026-03-09.csv.gz"
    assert local_path(key).parts[-5:] == ("tapes", "quotes_v1", "2026", "03", "2026-03-09.csv.gz")


def _cfg():
    return SimpleNamespace()


def test_list_file_parses_both_etag_quote_styles(monkeypatch):
    for quoted in ("&quot;abc-12&quot;", '"abc-12"'):
        body = (
            "<ListBucketResult><Contents><Key>us_stocks_sip/trades_v1/2026/03/2026-03-09.csv.gz</Key>"
            f"<LastModified>2026-04-06T23:59:45.287Z</LastModified><ETag>{quoted}</ETag><Size>42</Size>"
            "</Contents></ListBucketResult>"
        )
        monkeypatch.setattr(
            mod, "_s3", lambda *a, _body=body.encode(), **k: SimpleNamespace(stdout=_body)
        )
        item = mod.list_file(_cfg(), "trades_v1", date(2026, 3, 9))
        assert (item.size, item.etag) == (42, "abc-12")


def test_list_file_returns_none_for_an_unpublished_day_but_raises_on_a_failed_listing(monkeypatch):
    monkeypatch.setattr(
        mod, "_s3", lambda *a, **k: SimpleNamespace(stdout=b"<ListBucketResult></ListBucketResult>")
    )
    assert mod.list_file(_cfg(), "trades_v1", date(2026, 3, 9)) is None
    monkeypatch.setattr(
        mod, "_s3", lambda *a, **k: SimpleNamespace(stdout=b"<Error><Code>403</Code></Error>")
    )
    with pytest.raises(RuntimeError):
        mod.list_file(_cfg(), "trades_v1", date(2026, 3, 9))


def test_download_retries_then_renames_a_complete_part_file(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "TAPES", tmp_path)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    item = mod.TapeFile(
        tape_key("trades_v1", date(2026, 3, 9)), date(2026, 3, 9), "trades_v1", 5, "e", "t"
    )
    calls = []

    def fake_s3(cfg, suffix, extra=(), *, fail):
        assert fail  # a transfer never drops --fail
        calls.append(1)
        if len(calls) == 1:
            return SimpleNamespace(stdout=b"429")
        mod.local_path(item.key).with_suffix(".gz.part").write_bytes(b"12345")
        return SimpleNamespace(stdout=b"200")

    monkeypatch.setattr(mod, "_s3", fake_s3)
    assert mod.download(_cfg(), item, 0) == "downloaded"
    assert mod.local_path(item.key).read_bytes() == b"12345"
    assert mod.download(_cfg(), item, 0) == "present"
