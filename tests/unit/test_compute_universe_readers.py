"""Readers that mean "the compute universe" must filter on compute_eligible, not bare is_active.

Phase 174 code review WR-01: migration 337 left is_active unchanged on the premise that every
active row was also compute-consumed. The D-09 pilot cohort (is_active=true,
compute_eligible=false) broke that premise, and these readers silently pulled it in --
TagCalibrator measured 32 failed-gate symbols into its run-level BH-FDR family. Lookup-table
readers (tick sizes, asset-class vocabularies, API listings) deliberately keep is_active.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]

# (file, a substring unique to the query that must carry the compute_eligible filter)
_COMPUTE_UNIVERSE_QUERIES = [
    ("services/tag_calibrator.py", "SELECT symbol FROM instruments WHERE is_active = true"),
    ("services/ic_engine.py", "LEFT JOIN instrument_tags t ON t.symbol = i.symbol"),
    ("services/cross_sectional_spread_tracker.py", "JOIN instruments i ON i.symbol = fv.symbol"),
]


@pytest.mark.parametrize(("rel_path", "anchor"), _COMPUTE_UNIVERSE_QUERIES)
def test_compute_universe_query_filters_compute_eligible(rel_path, anchor):
    source = (_REPO / rel_path).read_text()
    assert source.count(anchor) == 1, f"{rel_path}: anchor not unique, update this test"
    start = source.index(anchor)
    window = source[start : start + 600]
    assert "compute_eligible = true" in window, (
        f"{rel_path}: compute-universe query filters is_active only; the 1d-only pilot "
        "cohort (compute_eligible=false) leaks in"
    )
