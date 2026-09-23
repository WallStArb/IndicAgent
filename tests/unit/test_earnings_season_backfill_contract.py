"""Source-level contract test for migration 351 (earnings-season corpus backfill).

Asserts every clause of 176-07-PLAN.md Task 1's <behavior> block against the .sql
file read as text -- no DB, no network, CI-clean, mirroring
test_earnings_season_migration_contract.py's shape (which this plan's <interfaces>
block cites as the prior art).

The load-bearing assertion is the SET-list parse: the backfill's whole safety story
is "the statement names exactly two columns and therefore structurally cannot damage
any other column" (the T-176-07-03 mitigation that replaces pre/post checksums), so
the test parses the SET clause structurally rather than trusting a substring count.

SQL comment lines are stripped before matching so a header sentence merely describing
a clause cannot satisfy an assertion about the executable statement.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_SQL_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_DO_BLOCK_RE = re.compile(r"DO\s*\$\$.*?\$\$", re.DOTALL)
_BARE_VACUUM_RE = re.compile(r"(?m)^\s*VACUUM\s+feature_vectors\s*;")
_DECOMPRESS_CALL_RE = re.compile(r"\bdecompress_chunk\s*\(")
_COMPRESS_CALL_RE = re.compile(r"\bcompress_chunk\s*\(")


def _sql_no_comments() -> str:
    raw = read_source("production", "migrations", "351_earnings_season_backfill.sql")
    return _SQL_LINE_COMMENT_RE.sub("", raw)


def _update_set_clause(sql: str) -> str:
    """The text between the UPDATE's SET keyword and its top-level FROM/WHERE."""
    match = re.search(
        r"UPDATE\s+feature_vectors.*?\bSET\b(.*?)(?=\bFROM\b|\bWHERE\b)",
        sql,
        re.DOTALL | re.IGNORECASE,
    )
    assert match, "UPDATE feature_vectors ... SET clause not found in migration 351"
    return match.group(1)


def _split_set_items(set_clause: str) -> list[str]:
    """Split a SET clause on commas at paren-depth 0 (single-quote aware).

    A plain str.split(",") would shred the CASE expressions' function-call commas
    (date_trunc('quarter', d)); a depth-aware split keeps each assignment one item.
    """
    items: list[str] = []
    current: list[str] = []
    depth = 0
    in_quote = False
    for char in set_clause:
        if in_quote:
            current.append(char)
            if char == "'":
                in_quote = False
            continue
        if char == "'":
            in_quote = True
            current.append(char)
        elif char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            items.append("".join(current))
            current = []
        else:
            current.append(char)
    if current:
        items.append("".join(current))
    return [item.strip() for item in items if item.strip()]


def test_update_set_list_assigns_exactly_two_columns():
    """The T-176-07-03 structural proof: the statement's SET list names exactly
    earnings_season_flag and days_since_quarter_end and nothing else, so collateral
    damage to any other column is impossible from the statement's own shape.

    Each comma-separated SET item must START with `identifier =` (the assignment
    target). An `=` inside an expression (the days CASE's quarter-end comparison)
    sits mid-item and cannot produce a phantom assignment under this parse.
    """
    sql = _sql_no_comments()
    items = _split_set_items(_update_set_clause(sql))
    assert (
        len(items) == 2
    ), f"SET clause must have exactly 2 assignments, found {len(items)}: {items}"
    assigned: set[str] = set()
    for item in items:
        match = re.match(r"^(\w+)\s*=", item)
        assert match, f"SET item does not start with a column assignment: {item!r}"
        assigned.add(match.group(1))
    assert assigned == {"earnings_season_flag", "days_since_quarter_end"}


def test_window_bounds_come_from_config_state_not_literals():
    """T-176-07-05: no bare 14/42 literal may drift away from the APR values; both
    bounds must be read from config_state inside the statement itself."""
    sql = _sql_no_comments()
    for key in ("feature.earnings_season.start_days", "feature.earnings_season.end_days"):
        assert key in sql, f"window bound must be read from config_state key {key}"
    assert not re.search(
        r"\b14\b", sql
    ), "bare 14 literal in executable SQL -- bounds must be APR-sourced"
    assert not re.search(
        r"\b42\b", sql
    ), "bare 42 literal in executable SQL -- bounds must be APR-sourced"


def test_bare_top_level_vacuum_feature_vectors_present():
    """The mandatory step 4: exactly one bare `VACUUM feature_vectors;`, located
    outside any DO $$ block and after the final COMMIT (never inside BEGIN/COMMIT).
    Its omission is what turned migration 312 into the 768GB incident."""
    sql = _sql_no_comments()
    vacuums = _BARE_VACUUM_RE.findall(sql)
    assert (
        len(vacuums) == 1
    ), f"expected exactly 1 bare VACUUM feature_vectors; found {len(vacuums)}"
    no_do_blocks = _DO_BLOCK_RE.sub("", sql)
    assert _BARE_VACUUM_RE.search(no_do_blocks), "VACUUM is nested inside a DO $$ block"
    last_commit = no_do_blocks.rfind("COMMIT;")
    assert last_commit != -1, "no COMMIT found -- statement structure unexpected"
    vacuum_pos = no_do_blocks.find("VACUUM feature_vectors;")
    assert vacuum_pos > last_commit, "VACUUM must be a bare top-level statement after COMMIT"


def test_performs_the_decompress_recompress_round_trip():
    """Both calls present so the CI VACUUM guard
    (tests/unit/test_compressed_hypertable_migration_vacuum_check.py) sweeps this
    file -- filing the migration in production/migrations/ buys that guard."""
    sql = _sql_no_comments()
    assert _DECOMPRESS_CALL_RE.search(sql), "missing decompress_chunk( call"
    assert _COMPRESS_CALL_RE.search(sql), "missing compress_chunk( call"


def test_decompress_chunk_uses_if_compressed_flag():
    """decompress_chunk()'s keyword flag is `if_compressed => true`; `if_not_compressed`
    does not exist and raises `function ... does not exist` (migration-doc gotcha)."""
    sql = _sql_no_comments()
    assert "if_compressed => true" in sql
    assert "if_not_compressed" not in sql


def test_update_is_idempotent_via_distinct_from_scoping():
    """T-176-07-06: the WHERE must scope to rows whose stored value differs from the
    computed value (IS DISTINCT FROM per column), making a re-run a genuine no-op --
    what makes the file safe to re-run after a partial failure."""
    sql = _sql_no_comments()
    for column in ("earnings_season_flag", "days_since_quarter_end"):
        assert re.search(
            rf"{column}\s+IS\s+DISTINCT\s+FROM", sql
        ), f"UPDATE WHERE clause must scope {column} with IS DISTINCT FROM for idempotency"


def test_apr_guard_aborts_on_missing_bounds():
    """A NULL from either config_state subselect means the APR seed is missing -- the
    statement must RAISE EXCEPTION rather than silently write NULL flags."""
    sql = _sql_no_comments()
    assert "RAISE EXCEPTION" in sql, "missing RAISE EXCEPTION guard for missing APR bounds"


def test_utc_cast_is_explicit():
    """T-176-07-04: bar_ts is timestamptz and every project timestamp is UTC (DAG
    invariant 6), so the date must be taken in UTC explicitly, not in the server's
    TimeZone setting."""
    sql = _sql_no_comments()
    assert "AT TIME ZONE 'UTC'" in sql, "bar_ts must be converted to a date in UTC explicitly"
