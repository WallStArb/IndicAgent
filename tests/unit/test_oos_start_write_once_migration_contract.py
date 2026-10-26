"""Migration 506 contract: alpha.validation.oos_start is write-once (todo 439 part 1).

Reads the .sql text only (no DB), SQL line comments stripped. The behaviour against a real
database is tests/integration/test_oos_start_write_once.py.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_RAW = read_source("production", "migrations", "506_oos_start_write_once.sql")
_CODE = re.sub(r"--[^\n]*", "", _RAW)
_FLAT = re.sub(r"\s+", " ", _CODE)


def test_migration_506_runs_in_one_transaction():
    assert _CODE.strip().startswith("BEGIN;")
    assert _CODE.rstrip().endswith("COMMIT;")


def test_trigger_guards_update_and_delete_of_the_key_on_config_state():
    assert (
        "CREATE TRIGGER trg_config_state_oos_start_write_once "
        "BEFORE UPDATE OR DELETE ON config_state FOR EACH ROW "
        "EXECUTE FUNCTION refuse_oos_start_change();"
    ) in _FLAT
    assert "OLD.config_key = 'alpha.validation.oos_start'" in _FLAT
    assert "NEW.config_key = 'alpha.validation.oos_start'" in _FLAT
    assert _FLAT.count("RAISE EXCEPTION") == 3


def test_truncate_of_config_state_is_refused():
    assert (
        "CREATE TRIGGER trg_config_state_no_truncate BEFORE TRUNCATE ON config_state "
        "FOR EACH STATEMENT EXECUTE FUNCTION refuse_config_state_truncate();"
    ) in _FLAT


def test_insert_is_not_guarded_so_a_fresh_database_can_seed_the_key():
    assert "INSERT" not in _FLAT.split("CREATE TRIGGER", 1)[1].split(";", 1)[0]
