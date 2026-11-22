"""The one integration test allowed a production DSN (todo 656 task 1): it reads the catalog only,
on a read-only connection that fails fast instead of waiting behind a busy production database,
and runs only under --live-catalog."""

from __future__ import annotations

import re

from tests.integration import test_migration_schema_sync as sync

_CATALOG_SCHEMAS = ("information_schema.", "pg_catalog.")
_CATALOG_RELATIONS = {"pg_constraint"}  # pg_catalog relations named without their schema


def test_the_production_connection_is_read_only_and_fails_fast():
    assert sync.LIVE_CATALOG_SETTINGS == {
        "default_transaction_read_only": "on",
        "statement_timeout": "30000",
        "lock_timeout": "1000",
        "application_name": "indicagent-test-live-catalog",
    }


def test_every_query_reads_the_catalog_only():
    queries = [sync._COLUMNS_SQL, sync._CONSTRAINTS_SQL, sync._TABLES_SQL]
    for sql in queries:
        relations = re.findall(r"\b(?:FROM|JOIN)\s+([\w.]+)", sql, flags=re.IGNORECASE)
        assert relations, sql
        for relation in relations:
            assert relation.startswith(_CATALOG_SCHEMAS) or relation in _CATALOG_RELATIONS, relation


def test_the_schema_sync_runs_only_under_the_live_catalog_marker():
    marks = sync.pytestmark if isinstance(sync.pytestmark, list) else [sync.pytestmark]
    assert {"integration", "live_catalog"} <= {mark.name for mark in marks}
