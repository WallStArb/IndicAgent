"""Live-DB coverage, provenance, depth and read-layer checks for indicagent_v1 (Phase 182).

Covers D-05 (depth), D-06 (source_ref), D-07 (no history before the build date), D-08 (service
round trip), D-09 (coverage) and D-10 (Instrument.sector comes from the classification).

These tests query the live `indicagent` DB, not the scratch `indicagent_test` DB. They are
marked `integration` and are NOT GitHub-CI-enforced (CI runs `tests/unit/` only, with no DB).
The enforcement that runs automatically is the seed migration's guards, the onboarding gate
and the nightly coverage audit. Run these locally with `--noconftest` until todo 413 fixes the
conftest's scratch-DB rebuild:

    .venv/bin/pytest tests/integration/test_instrument_classification_coverage.py -m integration --noconftest -q

All tests are read-only.
"""

from __future__ import annotations

from datetime import date

import asyncpg
import pytest

from src.config.classification_service import (
    ALLOWED_SOURCE_REFS,
    DEFAULT_SCHEME,
    SECTOR_LEVEL,
    SOURCE_REF_IBKR_REVIEWED,
    ClassificationService,
    unclassified_code,
)
from src.config.settings import get_active_contracts, get_settings

pytestmark = pytest.mark.integration

BUILD_DATE = date(2026, 9, 25)


def _dsn() -> str:
    return get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")


async def test_every_active_instrument_has_a_current_row() -> None:
    """D-09: same query as the seed guard and the nightly audit."""
    conn = await asyncpg.connect(_dsn())
    try:
        uncovered = await conn.fetch(
            """
            SELECT i.symbol FROM instruments i
            WHERE i.is_active AND NOT EXISTS (
                SELECT 1 FROM instrument_classification ic
                WHERE ic.symbol = i.symbol AND ic.scheme = $1 AND ic.valid_to IS NULL)
            """,
            DEFAULT_SCHEME,
        )
        assert [r["symbol"] for r in uncovered] == []
    finally:
        await conn.close()


async def test_source_refs() -> None:
    """D-06: every current source_ref is allowed; single names use the reviewed IBKR triple."""
    conn = await asyncpg.connect(_dsn())
    try:
        refs = await conn.fetch(
            "SELECT DISTINCT source_ref FROM instrument_classification "
            "WHERE scheme = $1 AND valid_to IS NULL",
            DEFAULT_SCHEME,
        )
        assert {r["source_ref"] for r in refs} <= ALLOWED_SOURCE_REFS

        wrong = await conn.fetch(
            """
            SELECT t.symbol, ic.source_ref
            FROM instrument_tags t
            LEFT JOIN instrument_classification ic
              ON ic.symbol = t.symbol AND ic.scheme = $1 AND ic.valid_to IS NULL
            WHERE t.tag = 'single_name_equity' AND t.valid_to IS NULL
              AND ic.source_ref IS DISTINCT FROM $2
            """,
            DEFAULT_SCHEME,
            SOURCE_REF_IBKR_REVIEWED,
        )
        assert [dict(r) for r in wrong] == []
    finally:
        await conn.close()


async def test_no_history_before_build_date() -> None:
    """D-07: the earliest valid_from is on or after the phase build date."""
    conn = await asyncpg.connect(_dsn())
    try:
        earliest = await conn.fetchval("SELECT min(valid_from) FROM instrument_classification")
        assert earliest is not None
        assert earliest >= BUILD_DATE
    finally:
        await conn.close()


async def test_depth() -> None:
    """D-05: single names at level 4; ETF depth follows the fund mandate."""
    conn = await asyncpg.connect(_dsn())
    try:
        shallow = await conn.fetch(
            """
            SELECT t.symbol, n.code, n.level
            FROM instrument_tags t
            JOIN instrument_classification ic
              ON ic.symbol = t.symbol AND ic.scheme = $1 AND ic.valid_to IS NULL
            JOIN classification_node n ON n.scheme = ic.scheme AND n.code = ic.code
            WHERE t.tag = 'single_name_equity' AND t.valid_to IS NULL AND n.level <> 4
            """,
            DEFAULT_SCHEME,
        )
        assert [dict(r) for r in shallow] == []

        rows = await conn.fetch(
            "SELECT symbol, code FROM instrument_classification "
            "WHERE scheme = $1 AND valid_to IS NULL AND symbol = ANY($2::text[])",
            DEFAULT_SCHEME,
            ["SPY", "XLK", "SMH"],
        )
        assert {r["symbol"]: r["code"] for r in rows} == {
            "SPY": "EQ.BROAD",
            "XLK": "EQ.IT",
            "SMH": "EQ.IT.SEMI.EQUIP",
        }
    finally:
        await conn.close()


async def test_classification_service_round_trip() -> None:
    """D-08: the cached read layer against the live tables."""
    service = ClassificationService(_dsn())
    await service.initialize()
    try:
        unclassified = unclassified_code(DEFAULT_SCHEME)
        assert service.name_at_level("SMH", 2) == "Information Technology"
        assert service.node_at_level("SPY", 4) == unclassified
        assert service.node_at_level("SPY", 1, as_of=date(2026, 9, 24)) == unclassified
        assert service.node_at_level("SPY", 2) == "EQ.BROAD"
    finally:
        await service.close()


async def test_active_contract_sectors_come_from_classification() -> None:
    """D-10: Instrument.sector is the level-2 node name, never the flat contract_details field."""
    conn = await asyncpg.connect(_dsn())
    try:
        rows = await conn.fetch(
            """
            SELECT i.symbol, n2.name AS sector_name
            FROM instruments i
            JOIN instrument_classification ic
              ON ic.symbol = i.symbol AND ic.scheme = $1 AND ic.valid_to IS NULL
            JOIN classification_node n ON n.scheme = ic.scheme AND n.code = ic.code
            JOIN classification_node n2 ON n2.scheme = n.scheme AND n2.code = n.path[$2]
            WHERE i.is_active
            """,
            DEFAULT_SCHEME,
            SECTOR_LEVEL,
        )
    finally:
        await conn.close()
    expected = {r["symbol"]: r["sector_name"] for r in rows}

    instruments = get_active_contracts(get_settings(), dimension="backfill")
    assert instruments
    mismatched = {
        i.symbol: (i.sector, expected.get(i.symbol))
        for i in instruments
        if i.symbol in expected and i.sector != expected[i.symbol]
    }
    assert mismatched == {}
    by_symbol = {i.symbol: i.sector for i in instruments}
    assert by_symbol["SMH"] == "Information Technology"
    assert unclassified_code(DEFAULT_SCHEME) not in {
        by_symbol[s] for s in expected if s in by_symbol
    }
