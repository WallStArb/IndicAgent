"""Migration 605 contract: reset of the stage 2 membership for the placement amendment (no database).

Reads the .sql text only, SQL line comments stripped.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_RAW = read_source("production", "migrations", "605_universe_membership_reset_for_rebuild.sql")
_CODE = re.sub(r"--[^\n]*", "", _RAW)
_FLAT = re.sub(r"\s+", " ", _CODE)


def test_the_reset_is_one_transaction():
    assert _CODE.strip().startswith("BEGIN;")
    assert _CODE.rstrip().endswith("COMMIT;")
    assert _FLAT.count("BEGIN;") == 1 and _FLAT.count("COMMIT;") == 1


def test_it_refuses_unless_the_live_build_is_the_measured_one_and_no_run_exists():
    assert "n_rows <> 858454 OR n_months <> 278" in _FLAT
    assert "FROM research_run" in _FLAT and "n_runs <> 0" in _FLAT


def test_the_old_build_is_copied_and_checked_before_anything_is_truncated():
    copy = _FLAT.index("CREATE TABLE universe_membership_pre605 AS TABLE universe_membership;")
    build_copy = _FLAT.index(
        "CREATE TABLE universe_membership_build_pre605 AS TABLE universe_membership_build;"
    )
    check = _FLAT.index("the pre-reset copy does not hold the live rows")
    truncate = _FLAT.index("TRUNCATE universe_membership, universe_membership_build;")
    assert max(copy, build_copy) < check < truncate


def test_only_the_truncate_triggers_are_disabled_and_both_are_enabled_again_before_commit():
    disable = _FLAT.index("DISABLE TRIGGER trg_universe_membership_no_truncate")
    truncate = _FLAT.index("TRUNCATE universe_membership, universe_membership_build;")
    enable = _FLAT.index("ENABLE TRIGGER trg_universe_membership_no_truncate")
    assert disable < truncate < enable < _FLAT.index("COMMIT;")
    assert _FLAT.count("DISABLE TRIGGER") == 2 and _FLAT.count(" ENABLE TRIGGER") == 2
    assert "trg_universe_membership_insert_only" not in _FLAT  # the row triggers stay in force
    assert "tgenabled = 'O') <> 4" in _FLAT  # all four triggers verified on before commit


def test_the_kept_copies_get_the_insert_only_triggers_and_nothing_else_is_touched():
    created = re.findall(r"CREATE TRIGGER (\w+) BEFORE \w+(?: OR \w+)? ON (\w+)", _FLAT)
    assert {t for _, t in created} == {
        "universe_membership_pre605",
        "universe_membership_build_pre605",
    }
    assert len(created) == 4 and all("pre605" in name for name, _ in created)
    body = re.sub(r"CREATE TRIGGER .*?EXECUTE FUNCTION \w+\(\);", "", _FLAT)
    statements = re.findall(r"\b(DELETE FROM|UPDATE|DROP|ALTER TABLE) (\w+)", body)
    assert {t for s, t in statements if s != "ALTER TABLE"} == set()
    assert {t for s, t in statements} <= {"universe_membership", "universe_membership_build"}
