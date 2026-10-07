"""CI guard: no first-write-wins write to a bar table (phase 185 plan 39, T-185-39-01).

`INSERT ... ON CONFLICT ... DO NOTHING` into market_data_ohlcv, ohlcv_intraday_raw_archive or
ohlcv_observation drops a later, differing answer without a trace. Data layer integrity design
section 4 replaces it with the write contract (compare, write new and changed rows, record the
old values in ohlcv_revision); this scan fails on any such statement outside a named allow-list,
and on a stale entry. The pattern is matched across a statement (no semicolon, no second INSERT
between the target and the conflict clause) so a Python string built from adjacent literals is
caught as well as a plain .sql file.

CI-clean: no DB, no network, pure filesystem grep.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

from tests.unit._source_grep_helpers import (
    assert_allow_list_has_no_stale_entries,
    assert_no_unlisted_references,
    find_pattern_references,
)

_REPO_ROOT = Path(__file__).parent.parent.parent
_SEARCH_DIRS = ("services", "src", "scripts")
_FILE_GLOBS = ("*.py", "*.sh", "*.sql")
_STATEMENT_BODY = r"(?:(?!INSERT\s+INTO)[^;])"
_FIRST_WRITE_WINS = re.compile(
    r"INSERT\s+INTO\s+(?:public\.)?(?:market_data_ohlcv|ohlcv_intraday_raw_archive|ohlcv_observation)"
    rf"\b{_STATEMENT_BODY}{{0,3000}}?ON\s+CONFLICT{_STATEMENT_BODY}{{0,300}}?DO\s+NOTHING",
    re.IGNORECASE | re.DOTALL,
)

# module -> reason. Every entry names why the write is out of this plan's scope and who retires it.
_ALLOW_LIST: dict[str, str] = {
    "services/bar_writer.py": (
        "PERMANENT while the streaming path is dormant: the Kafka-to-database bar writer is out "
        "of scope by the design's non-goals (section 10, 'the streaming path'). Revisit when "
        "live streaming resumes."
    ),
    "services/backfill_feature_factory.py": (
        "TEMPORARY, retire: 185-42. The phase 186 rebuild writer's --fetch-only stage; resolved "
        "in 185-42 under its no-live-rebuild check."
    ),
}


@functools.cache
def _hits() -> dict[str, int]:
    hits: dict[str, int] = {}
    for file_glob in _FILE_GLOBS:
        hits.update(
            find_pattern_references(
                _REPO_ROOT, _SEARCH_DIRS, _FIRST_WRITE_WINS, file_globs=(file_glob,)
            )
        )
    return hits


def test_no_first_write_wins_bar_write_outside_the_allow_list():
    assert_no_unlisted_references(
        _hits(),
        _ALLOW_LIST,
        what="`ON CONFLICT DO NOTHING` write(s) to a bar table",
        remedy=(
            "A later differing answer would be dropped silently. Write through the ingress "
            "contract (services/ohlcv_ingress_contract.py) or the grid stage's write contract; "
            "allow-list a path only with a reason and a retirement."
        ),
    )


def test_first_write_wins_allow_list_has_no_stale_entries():
    assert_allow_list_has_no_stale_entries(_hits(), _ALLOW_LIST)


def test_the_pattern_catches_each_statement_shape():
    assert _FIRST_WRITE_WINS.search(
        "INSERT INTO market_data_ohlcv (a) VALUES (1) ON CONFLICT (a) DO NOTHING"
    )
    assert _FIRST_WRITE_WINS.search(
        '"INSERT INTO ohlcv_intraday_raw_archive "\n"(a) VALUES "\n"{v} ON CONFLICT DO NOTHING"'
    )
    assert _FIRST_WRITE_WINS.search(
        "insert into ohlcv_observation (a) select 1 on conflict do nothing"
    )


def test_the_pattern_leaves_other_statements_alone():
    assert not _FIRST_WRITE_WINS.search(
        "INSERT INTO market_data_ohlcv (a) VALUES (1) ON CONFLICT (a) DO UPDATE SET a = 2"
    )
    assert not _FIRST_WRITE_WINS.search("INSERT INTO other (a) VALUES (1) ON CONFLICT DO NOTHING")
    # A conflict clause of a later statement does not belong to an earlier insert.
    assert not _FIRST_WRITE_WINS.search(
        "INSERT INTO market_data_ohlcv (a) VALUES (1);\nINSERT INTO other (a) VALUES (1) "
        "ON CONFLICT DO NOTHING"
    )
