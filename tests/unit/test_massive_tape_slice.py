from datetime import date

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
