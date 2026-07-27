"""Integration test: construction_spreads schema, APR seeds, and truncation order
(Phase 167 Plan 01).

Verifies production/migrations/260_construction_spreads_schema.sql landed correctly:
the construction_spreads hypertable (partition-column-containing PK per migration 205's
review-H1 constraint), the six alpha.construction.*/infra.cross_sectional_spread_tracker.*
APR keys (each provenance-tagged per CLAUDE.md's APR mandate), the json-typed cost-hurdle
key's json.loads round-trip (design decision 5, addressing Codex review concern REVIEW-M1),
and the corpus-rebuild truncation order (construction_spreads before alpha_frames,
addressing Codex review concern REVIEW-S1).

IMPORTANT: This test asserts against indicagent_test (the conftest-rebuilt database that
replays every migration numbered above tests/integration/conftest.py's
_BASELINE_MIGRATION_CUTOFF), not production indicagent. Migration 260 is above that
cutoff, so it is replayed into indicagent_test by the session-scoped autouse
migrated_test_database fixture before this module's tests run.

Run: pytest tests/integration/test_construction_spreads_schema.py -m integration
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import asyncpg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent_test"

_TRUNCATE_SCRIPT = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts"
    / "infrastructure"
    / "backfill"
    / "infrastructure_truncate_derived_tables.sh"
)

_PROVENANCE_TAG_RE = re.compile(r"\[(initial_estimate|conventional|rca_analysis|user_preference)\]")

# The fourteen columns named in 167-01-PLAN.md's <interfaces> block.
_EXPECTED_COLUMNS: dict[str, tuple[str, str]] = {
    # column_name: (udt_name, is_nullable)
    "construction_name": ("text", "NO"),
    "tf": ("text", "NO"),
    "bar_ts": ("timestamptz", "NO"),
    "n_universe": ("int4", "NO"),
    "n_leg": ("int4", "NO"),
    "long_leg_symbols": ("_text", "NO"),
    "short_leg_symbols": ("_text", "NO"),
    "gross_spread_fast": ("float8", "YES"),
    "gross_spread_slow": ("float8", "YES"),
    "one_way_turnover": ("float8", "YES"),
    "net_spread_fast_by_cost_bps": ("jsonb", "YES"),
    "net_spread_slow_by_cost_bps": ("jsonb", "YES"),
    "compute_version": ("text", "NO"),
    "created_at": ("timestamptz", "NO"),
}

_EXPECTED_APR_KEYS: dict[str, tuple[str, str]] = {
    # config_key: (value_type, default config_value)
    "alpha.construction.decile_fraction": ("float", "0.10"),
    "alpha.construction.cost_hurdle_bps_round_trip": ("json", "[1, 3, 5, 10]"),
    "alpha.construction.null_shuffles": ("int", "40"),
    "alpha.construction.attribution_max_static_r2": ("float", "0.50"),
    "infra.cross_sectional_spread_tracker.itersize": ("int", "5000"),
    "infra.cross_sectional_spread_tracker.chunk_size": ("int", "5000"),
}


@pytest.mark.asyncio
async def test_construction_spreads_is_a_hypertable() -> None:
    """construction_spreads must exist and be registered as exactly one hypertable."""
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        regclass = await conn.fetchval("SELECT to_regclass('construction_spreads')")
        assert regclass is not None, "construction_spreads table does not exist"

        hypertable_count = await conn.fetchval(
            "SELECT count(*) FROM timescaledb_information.hypertables "
            "WHERE hypertable_name = 'construction_spreads'"
        )
        assert hypertable_count == 1, (
            f"Expected exactly 1 hypertable registration for construction_spreads, "
            f"got {hypertable_count}"
        )
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_construction_spreads_columns() -> None:
    """All fourteen expected columns must exist with the correct type and nullability."""
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        rows = await conn.fetch(
            "SELECT column_name, udt_name, is_nullable FROM information_schema.columns "
            "WHERE table_name = $1",
            "construction_spreads",
        )
    finally:
        await conn.close()

    actual = {row["column_name"]: (row["udt_name"], row["is_nullable"]) for row in rows}

    missing = set(_EXPECTED_COLUMNS) - set(actual)
    assert not missing, f"construction_spreads missing expected column(s): {sorted(missing)}"

    for col, expected in _EXPECTED_COLUMNS.items():
        assert actual[col] == expected, (
            f"construction_spreads.{col}: expected (udt_name, is_nullable)={expected}, "
            f"got {actual[col]}"
        )

    # Pitfall-4 design decision: these three must be nullable (NULL means "no
    # predecessor bar existed", never a faked 0.0).
    for nullable_col in (
        "one_way_turnover",
        "net_spread_fast_by_cost_bps",
        "net_spread_slow_by_cost_bps",
    ):
        assert actual[nullable_col][1] == "YES", (
            f"construction_spreads.{nullable_col} must be nullable (Pitfall 4 design "
            f"decision), got is_nullable={actual[nullable_col][1]}"
        )

    # Postgres array-of-text columns.
    for array_col in ("long_leg_symbols", "short_leg_symbols"):
        assert actual[array_col][0] == "_text", (
            f"construction_spreads.{array_col} must be udt_name='_text' (array of text), "
            f"got {actual[array_col][0]}"
        )

    # Both net_spread_*_by_cost_bps columns are jsonb.
    for jsonb_col in ("net_spread_fast_by_cost_bps", "net_spread_slow_by_cost_bps"):
        assert (
            actual[jsonb_col][0] == "jsonb"
        ), f"construction_spreads.{jsonb_col} must be udt_name='jsonb', got {actual[jsonb_col][0]}"


@pytest.mark.asyncio
async def test_construction_spreads_pk_contains_partition_column() -> None:
    """The PK must contain construction_name, tf, AND bar_ts (migration 205 review-H1)."""
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        pk_def = await conn.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'construction_spreads'::regclass AND contype = 'p'"
        )
    finally:
        await conn.close()

    assert pk_def is not None, "construction_spreads has no primary key"

    msg = (
        "construction_spreads PK must contain construction_name, tf, AND bar_ts "
        "(migration 205's review-H1 constraint: TimescaleDB requires every unique "
        f"index, including the PK, to contain the partitioning column). Got: {pk_def}"
    )
    assert "construction_name" in pk_def, msg
    assert "tf" in pk_def, msg
    assert "bar_ts" in pk_def, msg


@pytest.mark.asyncio
async def test_construction_apr_keys_seeded() -> None:
    """All six APR keys must exist across config_schema/config_state/config_history,
    each provenance-tagged, and none may touch the alpha.quant.cost_hurdle namespace
    (Pitfall 5)."""
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        schema_rows = await conn.fetch(
            "SELECT config_key, value_type, description FROM config_schema "
            "WHERE config_key = ANY($1::text[])",
            list(_EXPECTED_APR_KEYS),
        )
        state_rows = await conn.fetch(
            "SELECT config_key, config_value FROM config_state "
            "WHERE config_key = ANY($1::text[])",
            list(_EXPECTED_APR_KEYS),
        )
        history_counts = await conn.fetch(
            "SELECT config_key, count(*) AS n FROM config_history "
            "WHERE config_key = ANY($1::text[]) GROUP BY config_key",
            list(_EXPECTED_APR_KEYS),
        )
    finally:
        await conn.close()

    schema_by_key = {r["config_key"]: r for r in schema_rows}
    state_by_key = {r["config_key"]: r for r in state_rows}
    history_by_key = {r["config_key"]: r["n"] for r in history_counts}

    assert set(schema_by_key) == set(
        _EXPECTED_APR_KEYS
    ), f"config_schema missing key(s): {set(_EXPECTED_APR_KEYS) - set(schema_by_key)}"
    assert set(state_by_key) == set(
        _EXPECTED_APR_KEYS
    ), f"config_state missing key(s): {set(_EXPECTED_APR_KEYS) - set(state_by_key)}"

    for key, (expected_type, expected_value) in _EXPECTED_APR_KEYS.items():
        assert schema_by_key[key]["value_type"] == expected_type, (
            f"{key}: expected config_schema.value_type={expected_type!r}, "
            f"got {schema_by_key[key]['value_type']!r}"
        )
        assert state_by_key[key]["config_value"] == expected_value, (
            f"{key}: expected config_state.config_value={expected_value!r}, "
            f"got {state_by_key[key]['config_value']!r}"
        )
        assert history_by_key.get(key, 0) >= 1, f"{key}: no config_history row found"

        description = schema_by_key[key]["description"]
        assert _PROVENANCE_TAG_RE.search(description), (
            f"{key}: config_schema.description must carry a provenance tag "
            f"([initial_estimate]/[conventional]/[rca_analysis]/[user_preference]) "
            f"per CLAUDE.md's APR mandate. Got: {description!r}"
        )

    # Pitfall 5: this construction must never touch the existing flat per-tf key.
    for key in _EXPECTED_APR_KEYS:
        assert not key.startswith("alpha.quant.cost_hurdle"), (
            f"{key} must not start with alpha.quant.cost_hurdle (Pitfall 5 -- this "
            "construction's cost mechanism is deliberately distinct from the flat, "
            "single-value alpha.quant.cost_hurdle.<tf> key)"
        )


@pytest.mark.asyncio
async def test_construction_json_apr_key_round_trips() -> None:
    """alpha.construction.cost_hurdle_bps_round_trip must be seeded as value_type='json'
    and round-trip through json.loads to exactly [1, 3, 5, 10] (design decision 5,
    REVIEW-M1). A key mistakenly seeded as 'str' would be consumed as the literal text
    "[1, 3, 5, 10]" and the cost sweep would iterate its characters -- a wrong answer
    that raises nothing anywhere in the pipeline."""
    key = "alpha.construction.cost_hurdle_bps_round_trip"
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        value_type = await conn.fetchval(
            "SELECT value_type FROM config_schema WHERE config_key = $1", key
        )
        config_value = await conn.fetchval(
            "SELECT config_value FROM config_state WHERE config_key = $1", key
        )
    finally:
        await conn.close()

    assert value_type == "json", (
        f"{key}: config_schema.value_type must be the literal string 'json', got "
        f"{value_type!r}. A key seeded as 'str' would be consumed as the literal text "
        '"[1, 3, 5, 10]" and the cost sweep would iterate its characters -- a wrong '
        "answer that raises nothing anywhere in the pipeline."
    )

    parsed = json.loads(config_value)
    assert parsed == [
        1,
        3,
        5,
        10,
    ], f"{key}: json.loads(config_value) expected [1, 3, 5, 10], got {parsed}"
    assert all(isinstance(v, int) for v in parsed), (
        f"{key}: every element of the parsed list must be an int, got types "
        f"{[type(v).__name__ for v in parsed]}"
    )


def test_truncate_script_orders_construction_spreads_before_alpha_frames() -> None:
    """infrastructure_truncate_derived_tables.sh must TRUNCATE construction_spreads
    strictly before it TRUNCATEs alpha_frames (REVIEW-S1: dedicated test for the corpus
    truncation order, making the contract mechanical rather than reviewer-enforced).
    No database access needed -- reads the script as text."""
    text = _TRUNCATE_SCRIPT.read_text()
    lines = text.splitlines()

    construction_idx = next(
        (i for i, line in enumerate(lines) if "TRUNCATE construction_spreads" in line), None
    )
    alpha_frames_idx = next(
        (i for i, line in enumerate(lines) if "TRUNCATE alpha_frames" in line), None
    )

    assert construction_idx is not None, "TRUNCATE construction_spreads not found in script"
    assert alpha_frames_idx is not None, "TRUNCATE alpha_frames not found in script"
    assert construction_idx < alpha_frames_idx, (
        f"TRUNCATE construction_spreads (line {construction_idx + 1}) must appear before "
        f"TRUNCATE alpha_frames (line {alpha_frames_idx + 1}) so a corpus rebuild never "
        "leaves stale spread rows computed from deleted inputs"
    )
