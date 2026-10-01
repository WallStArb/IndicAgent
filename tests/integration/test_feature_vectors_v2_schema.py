"""Integration test: feature_vectors_v2 schema on indicagent_test (phase 186-24, D-34, D-37).

Migration 425 is replayed into indicagent_test by tests/integration/conftest.py. Catalog
introspection uses timescaledb_information.hypertables and
_timescaledb_catalog.compression_settings, because TimescaleDB 2.27.1 has no
_timescaledb_catalog.hypertable_compression or hypertable.compressed_enabled.

Run: pytest tests/integration/test_feature_vectors_v2_schema.py -m integration
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.integration.conftest import connect
from tests.unit.intelligence.test_feature_vectors_v2_schema import (
    DROPPED_COLUMNS,
    METADATA_DROPPED,
    expected_columns,
)

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

_TABLE = "feature_vectors_v2"


def _scalar(query: str, params: tuple = ()):
    with connect() as conn:
        return conn.execute(query, params).fetchone()[0]


def test_table_is_empty() -> None:
    assert _scalar(f"SELECT count(*) FROM {_TABLE}") == 0


def test_primary_key_columns() -> None:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT a.attname FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = %s::regclass AND i.indisprimary
            """,
            (_TABLE,),
        ).fetchall()
    assert {r[0] for r in rows} == {"symbol", "tf", "bar_ts"}


def test_one_year_time_dimension() -> None:
    interval = _scalar(
        """
        SELECT time_interval FROM timescaledb_information.dimensions
        WHERE hypertable_name = %s AND dimension_type = 'Time'
        """,
        (_TABLE,),
    )
    # psycopg maps INTERVAL '1 year' to 360 days (Postgres month arithmetic) in the interval type.
    assert interval == timedelta(days=360)


def test_compression_attributes_and_no_policy() -> None:
    assert _scalar(
        "SELECT compression_enabled FROM timescaledb_information.hypertables "
        "WHERE hypertable_name = %s",
        (_TABLE,),
    )
    with connect() as conn:
        segmentby, orderby = conn.execute(
            "SELECT segmentby, orderby FROM _timescaledb_catalog.compression_settings "
            "WHERE relid = %s::regclass",
            (_TABLE,),
        ).fetchone()
    assert segmentby == ["symbol", "tf"]
    assert orderby[0] == "bar_ts"
    assert (
        _scalar(
            "SELECT count(*) FROM timescaledb_information.jobs "
            "WHERE hypertable_name = %s AND proc_name = 'policy_compression'",
            (_TABLE,),
        )
        == 0
    )


def test_columns_equal_registry_derivation_and_dropped_absent() -> None:
    with connect() as conn:
        columns = {
            r[0]
            for r in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                (_TABLE,),
            ).fetchall()
        }
    assert columns == expected_columns()
    assert not columns & (set(DROPPED_COLUMNS) | set(METADATA_DROPPED))
