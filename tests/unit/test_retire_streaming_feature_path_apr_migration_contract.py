"""Source-level contract for migration 599: retire the streaming feature path's APR keys.

The keys' only consumers (services/feature_vector_pipeline.py and feature_vector_writer.py) are
deleted in the same commit. The migration deletes each key from config_history, then config_state,
then config_schema, by literal key, inside one transaction. CI-clean: reads the file only.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_KEYS = (
    "alert.lag.feature-vector-writer",
    "feature.cross_asset.role_symbols",
    "infra.instruments_listener.heartbeat_s",
    "infra.instruments_listener.reconnect_backoff_s",
    "threshold.ofi_continuation.magnitude_floors",
)


def _statements() -> list[str]:
    sql = re.sub(
        r"--[^\n]*",
        "",
        read_source("production", "migrations", "599_retire_streaming_feature_path_apr.sql"),
    )
    return [" ".join(part.split()) for part in sql.split(";") if part.strip()]


def test_deletes_history_then_state_then_schema_by_literal_key_in_one_transaction():
    statements = _statements()
    assert statements[0] == "BEGIN" and statements[-1] == "COMMIT"
    body = statements[1:-1]
    assert [s.split()[2] for s in body] == ["config_history", "config_state", "config_schema"]
    for statement in body:
        assert statement.startswith("DELETE FROM ")
        for key in _KEYS:
            assert f"'{key}'" in statement
        assert "LIKE" not in statement.upper()
