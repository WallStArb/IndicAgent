"""Unit tests for split_feed_auditor (todo 649). CI-clean: no DB, no network."""

from __future__ import annotations

import csv
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from services.split_feed_auditor import (
    _CANDIDATE_COLUMNS,
    FeedError,
    FeedSplit,
    Flagged,
    Judgement,
    Recorded,
    candidate_rows,
    feed_window,
    fetch_feed,
    judge_splits,
    parse_feed_splits,
    write_candidates,
)
from src.config.settings import Settings

TODAY = date(2026, 11, 23)
_SETTINGS = Settings(alpaca_key_id="key", alpaca_secret_key="secret")
KW = {"record_lookback_days": 7, "row_grace_days": 2, "rel_tol": 0.02}


def _dt(day: str, hour: int = 4) -> datetime:
    return datetime.fromisoformat(day).replace(hour=hour, tzinfo=UTC)


def _fwd(symbol="SNDK", ex="2026-11-23", old=1, new=8, kind="split") -> FeedSplit:
    return FeedSplit(symbol, date.fromisoformat(ex), kind, float(old), float(new))


def _judge(splits, active=("SNDK",), recorded=(), flagged=()):
    return judge_splits(splits, set(active), list(recorded), list(flagged), TODAY, **KW)


def _page(forward=(), reverse=(), token=None):
    page = {"corporate_actions": {"forward_splits": list(forward), "reverse_splits": list(reverse)}}
    if token:
        page["next_page_token"] = token
    return page


def _entry(symbol="SNDK", ex="2026-11-20", old=1, new=8):
    return {"symbol": symbol, "ex_date": ex, "old_rate": old, "new_rate": new}


# parse


def test_parse_reverse_split_factor_is_new_over_old():
    (split,) = parse_feed_splits(_page(reverse=[_entry("VIXM", "2026-11-19", 2, 1)]))
    assert split.action_type == "reverse_split"
    assert split.factor == 0.5


def test_parse_drops_duplicate_rows_across_pages():
    pages = [_page(forward=[_entry()]), _page(forward=[_entry()])]
    assert len(parse_feed_splits(pages)) == 1


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"corporate_actions": None},
        _page(forward=[{"symbol": "X", "ex_date": "2026-11-20", "old_rate": 0, "new_rate": 2}]),
        _page(forward=[{"symbol": "X", "ex_date": "not-a-date", "old_rate": 1, "new_rate": 2}]),
        _page(forward=[{"ex_date": "2026-11-20", "old_rate": 1, "new_rate": 2}]),
    ],
)
def test_parse_rejects_malformed_payload_loudly(bad):
    with pytest.raises(FeedError):
        parse_feed_splits(bad)


# fetch: the feed being down must raise, never read as "no splits"


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_feed_server_error_raises():
    client = _client(lambda request: httpx.Response(503, text="down"))
    with pytest.raises(FeedError, match="503"):
        fetch_feed(_SETTINGS, date(2026, 11, 9), TODAY, client)


def test_feed_transport_error_raises():
    def boom(request):
        raise httpx.ConnectError("no route")

    with pytest.raises(FeedError, match="feed request failed"):
        fetch_feed(_SETTINGS, date(2026, 11, 9), TODAY, _client(boom))


def test_feed_non_json_body_raises():
    client = _client(lambda request: httpx.Response(200, text="<html>"))
    with pytest.raises(FeedError, match="not JSON"):
        fetch_feed(_SETTINGS, date(2026, 11, 9), TODAY, client)


def test_feed_follows_pages_and_returns_all_splits():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page_token") == "p2":
            return httpx.Response(200, json=_page(reverse=[_entry("VIXM", "2026-11-19", 2, 1)]))
        return httpx.Response(200, json=_page(forward=[_entry()], token="p2"))

    splits = fetch_feed(_SETTINGS, date(2026, 11, 9), TODAY, _client(handler))
    assert [s.symbol for s in splits] == ["VIXM", "SNDK"]


# judge


def test_inactive_name_is_ignored():
    judgement = _judge([_fwd("DEAD")], active=("SNDK",))
    assert [s.symbol for s in judgement.inactive] == ["DEAD"]
    assert not judgement.failed and not judgement.candidates


def test_recorded_split_does_not_realert():
    row = Recorded("SNDK", "split", 8.0, _dt("2026-11-21"))
    judgement = _judge([_fwd(ex="2026-11-20")], recorded=[row])
    assert judgement.recorded and not judgement.failed and not judgement.candidates


def test_recorded_reverse_split_matches_its_own_factor():
    split = _fwd("VIXM", "2026-11-19", 2, 1, "reverse_split")
    row = Recorded("VIXM", "reverse_split", 0.5, _dt("2026-11-20"))
    assert _judge([split], active=("VIXM",), recorded=[row]).recorded == [split]


def test_row_with_the_wrong_factor_or_type_does_not_cover_the_split():
    split = _fwd("VIXM", "2026-11-23", 2, 1, "reverse_split")
    wrong_factor = Recorded("VIXM", "reverse_split", 2.0, _dt("2026-11-23"))
    wrong_type = Recorded("VIXM", "split", 0.5, _dt("2026-11-23"))
    judgement = _judge([split], active=("VIXM",), recorded=[wrong_factor, wrong_type])
    assert not judgement.recorded and judgement.unseen == [split]


def test_row_recorded_long_before_the_ex_date_does_not_cover_it():
    old = Recorded("SNDK", "split", 8.0, _dt("2026-06-01"))
    assert _judge([_fwd()], recorded=[old]).unseen


def test_flagged_split_inside_grace_is_a_candidate_not_a_failure():
    flag = Flagged("SNDK", 0.125, _dt("2026-11-23"))
    judgement = _judge([_fwd()], flagged=[flag])
    assert len(judgement.candidates) == 1 and not judgement.failed


def test_reverse_split_flag_ratio_matches_in_either_direction():
    split = _fwd("VIXM", "2026-11-23", 2, 1, "reverse_split")
    flag = Flagged("VIXM", 2.0, _dt("2026-11-23"))  # VIXM: price ratio 2.0 for factor 0.5
    assert _judge([split], active=("VIXM",), flagged=[flag]).candidates == [split]


def test_split_with_no_flag_and_no_row_fails_unseen():
    judgement = _judge([_fwd()])
    assert judgement.unseen and judgement.failed


def test_flag_for_another_ratio_does_not_count():
    flag = Flagged("SNDK", 0.5, _dt("2026-11-23"))
    assert _judge([_fwd()], flagged=[flag]).unseen


def test_flagged_split_without_a_row_past_grace_fails_overdue():
    flag = Flagged("SNDK", 0.125, _dt("2026-11-20"))
    judgement = _judge([_fwd(ex="2026-11-20")], flagged=[flag])
    assert judgement.overdue and judgement.failed


# candidate file


def test_candidate_rows_use_the_calendar_market_columns(tmp_path):
    rows = candidate_rows([_fwd(ex="2026-11-20")], {"SNDK": date(2026, 11, 13)})
    path = tmp_path / "split_candidates.csv"
    write_candidates(path, rows)
    with path.open() as handle:
        (row,) = list(csv.DictReader(handle))
    assert row["symbol"] == "SNDK"
    assert row["effective_date"] == "2026-11-13"
    assert float(row["factor"]) == 8.0
    assert row["unadjusted_routes"] == "massive/sip_flat"
    assert tuple(row) == _CANDIDATE_COLUMNS


def test_candidate_without_a_massive_session_leaves_the_route_blank():
    (row,) = candidate_rows([_fwd()], {"SNDK": None})
    assert row["effective_date"] == "" and row["unadjusted_routes"] == ""


def test_feed_with_empty_credentials_raises_before_any_request():
    def never(request):
        raise AssertionError("no request expected")

    settings = Settings(alpaca_key_id="", alpaca_secret_key="")
    with pytest.raises(FeedError, match="empty"):
        fetch_feed(settings, date(2026, 11, 9), TODAY, _client(never))


def test_feed_window_ends_yesterday_and_never_precedes_the_seam():
    seam = date(2026, 11, 16)
    assert feed_window(date(2026, 11, 24), 14, seam) == (seam, date(2026, 11, 23))
    assert feed_window(date(2027, 1, 10), 14, seam) == (date(2026, 12, 27), date(2027, 1, 9))


def test_counts_name_every_class_once():
    judgement = Judgement(
        recorded=[_fwd("A")],
        inactive=[_fwd("B"), _fwd("C")],
        candidates=[_fwd("D")] * 3,
        unseen=[_fwd("E")] * 4,
        overdue=[_fwd("F")] * 5,
    )
    assert judgement.counts() == {
        "inactive_ignored": 2,
        "recorded": 1,
        "candidates": 3,
        "unseen": 4,
        "overdue": 5,
    }


def test_report_counts_sets_one_gauge_point_per_class(monkeypatch):
    import services.split_feed_auditor as auditor

    calls = []
    monkeypatch.setattr(
        auditor, "SPLIT_FEED_SPLITS", SimpleNamespace(set=lambda v, a: calls.append((a, v)))
    )
    judgement = Judgement([_fwd("A")], [], [_fwd("B")] * 2, [], [])
    auditor.report_counts(judgement)
    assert dict((a["class"], v) for a, v in calls) == judgement.counts()
