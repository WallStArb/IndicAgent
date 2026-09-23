"""Readers that mean "the compute universe" take their predicate from dimension_where_clause.

Phase 174 code review WR-01: migration 337 left is_active unchanged on the premise that every
active row was also compute-consumed. The D-09 pilot cohort (is_active=true,
compute_eligible=false) broke that premise, and these readers silently pulled it in --
TagCalibrator measured 32 failed-gate symbols into its run-level BH-FDR family. Each reader
now interpolates settings.dimension_where_clause("compute", ...) instead of re-typing the
clause. Lookup-table readers (tick sizes, asset-class vocabularies, API listings)
deliberately keep is_active.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config.settings import dimension_where_clause

_REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("rel_path", "call"),
    [
        ("services/tag_calibrator.py", "dimension_where_clause('compute')"),
        ("services/ic_engine.py", "dimension_where_clause('compute', 'i')"),
        ("services/cross_sectional_spread_tracker.py", 'dimension_where_clause("compute", "i")'),
    ],
)
def test_compute_universe_readers_use_the_shared_clause(rel_path, call):
    assert call in (_REPO / rel_path).read_text()


def test_spread_tracker_panel_sql_renders_the_compute_clause():
    import services.cross_sectional_spread_tracker as tracker

    for sql in (
        tracker._PANEL_SQL_BACKFILL,
        tracker._PANEL_SQL_INCREMENTAL,
        tracker._GATE_PANEL_SQL,
    ):
        assert "i.is_active = true AND i.compute_eligible = true" in sql


def test_dimension_where_clause_qualifies_every_term():
    assert (
        dimension_where_clause("compute", "i") == "i.is_active = true AND i.compute_eligible = true"
    )
    assert dimension_where_clause("compute_1d") == "is_active = true AND compute_eligible_1d = true"
    with pytest.raises(ValueError, match="Unknown dimension"):
        dimension_where_clause("everything")
