"""Migration 601 contract: the partial index the identity trigger's probe needs (todo 609).

Reads the .sql text only (no DB), SQL line comments stripped.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_FILE = "601_ticker_event_security_identifier_index.sql"
_CODE = re.sub(r"--[^\n]*", "", read_source("production", "migrations", _FILE))
_FLAT = re.sub(r"\s+", " ", _CODE)


def test_the_index_migration_runs_in_one_transaction():
    assert _CODE.strip().startswith("BEGIN;")
    assert _CODE.rstrip().endswith("COMMIT;")


def test_the_index_is_partial_on_the_triggers_own_predicate_and_rerun_safe():
    assert (
        "CREATE INDEX IF NOT EXISTS idx_ticker_event_security_identifier "
        "ON ticker_event (security_identifier_id) WHERE retired_at IS NULL;" in _FLAT
    )


def test_it_is_not_concurrent_because_it_runs_inside_a_transaction():
    assert "CONCURRENTLY" not in _CODE


def test_it_touches_no_row_and_owes_no_vacuum():
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|decompress_chunk|compress_chunk)\b", _CODE)
