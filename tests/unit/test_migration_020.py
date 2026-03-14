"""Unit tests for migration 020: llm_calls hypertable fix."""

import re
from pathlib import Path

MIGRATIONS = Path(__file__).parent.parent.parent / "production" / "migrations"


def _read(name: str) -> str:
    return (MIGRATIONS / name).read_text()


def test_drop_constraint_present():
    sql = _read("020_llm_calls_hypertable_fix.sql")
    assert "DROP CONSTRAINT IF EXISTS llm_calls_pkey" in sql


def test_composite_pk_present():
    sql = _read("020_llm_calls_hypertable_fix.sql")
    assert re.search(r"ADD PRIMARY KEY\s*\(\s*call_id\s*,\s*called_at\s*\)", sql)


def test_create_hypertable_no_if_not_exists():
    sql = _read("020_llm_calls_hypertable_fix.sql")
    # if_not_exists must not appear on the create_hypertable line in 020
    ht_lines = [line for line in sql.splitlines() if "create_hypertable" in line.lower()]
    assert ht_lines, "create_hypertable call must be present"
    assert not any(
        "if_not_exists" in line for line in ht_lines
    ), "020 must NOT use if_not_exists — errors must surface"


def test_migrate_data_flag():
    sql = _read("020_llm_calls_hypertable_fix.sql")
    assert "migrate_data => TRUE" in sql or "migrate_data=>TRUE" in sql


def test_idempotency_guard():
    sql = _read("020_llm_calls_hypertable_fix.sql")
    # Guard: DO $$ block that checks hypertables before attempting create
    assert "timescaledb_information.hypertables" in sql


def test_019_pk_corrected():
    sql = _read("019_llm_intelligence_layer.sql")
    # Old UUID PRIMARY KEY must be gone
    assert "UUID PRIMARY KEY" not in sql
    # Composite PK table constraint must be present
    assert re.search(r"PRIMARY KEY\s*\(\s*call_id\s*,\s*called_at\s*\)", sql)


def test_019_no_silent_if_not_exists():
    sql = _read("019_llm_intelligence_layer.sql")
    # if_not_exists must not appear on the create_hypertable line in 019 either
    ht_lines = [line for line in sql.splitlines() if "create_hypertable" in line.lower()]
    assert ht_lines, "create_hypertable must still be in 019"
    assert not any(
        "if_not_exists" in line for line in ht_lines
    ), "019 must NOT use if_not_exists after the fix"
