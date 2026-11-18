"""Integration: every legacy battery waiver names a spec hash with a recorded real run.

A waiver (battery_pass.LEGACY_WAIVERS) covers only a spec that already ran for real under the E17
battery of its day, whose pass is ledger prose. Strictly read-only against the live indicagent DB:
one small SELECT on research_run. On 2026-11-18 research_run was empty, so the table is empty and no
recorded family exists: every family needs a true pass record before a real run (todo 637).
"""

from __future__ import annotations

import psycopg
import pytest

from src.intelligence.research import battery_pass

_LIVE_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent"

pytestmark = pytest.mark.integration


def test_every_waiver_row_has_a_recorded_real_run():
    if not battery_pass.LEGACY_WAIVERS:
        pytest.skip("no waivers: nothing to check")
    with psycopg.connect(_LIVE_DB_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT spec_hash FROM research_run "
            "WHERE mode IN ('real', 'exploration') AND spec_hash = ANY(%s)",
            ([h for _, h in battery_pass.LEGACY_WAIVERS],),
        )
        recorded = {row[0] for row in cur.fetchall()}
    missing = {key for key in battery_pass.LEGACY_WAIVERS if key[1] not in recorded}
    assert not missing, f"waivers with no recorded real run: {sorted(missing)}"
