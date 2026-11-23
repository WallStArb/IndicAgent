"""Read-layer round trip for indicagent_v1 (Phase 182, D-08).

The coverage, source_ref, depth, build-date and Instrument.sector checks (D-05, D-06, D-07, D-09,
D-10) measured how complete the classification of the current universe is, a property of production
data that the nightly coverage audit (src/config/classification_coverage.py) already monitors; they
were removed under todo 656 (docs/plans/2026-11-23-integration-harness-plan.md). This round trip
asserts specific symbols' assignments, so it needs the assignment seed of todo 655.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.config.classification_service import (
    DEFAULT_SCHEME,
    ClassificationService,
    unclassified_code,
)
from src.config.settings import get_settings

pytestmark = pytest.mark.integration

BUILD_DATE = date(2026, 9, 25)


def _dsn() -> str:
    return get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")


async def test_classification_service_round_trip() -> None:
    """D-08: the cached read layer against the live tables."""
    service = ClassificationService(_dsn())
    await service.initialize()
    try:
        unclassified = unclassified_code(DEFAULT_SCHEME)
        assert service.node(service.node_at_level("SMH", 2)).name == "Information Technology"
        assert service.node_at_level("SPY", 4) == unclassified
        assert service.node_at_level("SPY", 1, as_of=date(2026, 9, 24)) == unclassified
        assert service.node_at_level("SPY", 2) == "EQ.BROAD"
    finally:
        await service.close()
