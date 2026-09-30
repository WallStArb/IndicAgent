"""Migration 409: guard_status is present exactly on feature_ic rows of concept_evaluation."""

from __future__ import annotations

from pathlib import Path

import services.feature_lifecycle as fl

_SQL = (
    Path(__file__).resolve().parents[2]
    / "production/migrations/409_concept_evaluation_guard_status_matches_kind.sql"
).read_text()


def test_migration_refuses_on_violation_before_adding_the_check():
    assert _SQL.index("RAISE EXCEPTION") < _SQL.index("ADD CONSTRAINT")
    assert "(evidence_kind = 'feature_ic') = (guard_status IS NOT NULL)" in _SQL
    statements = "\n".join(ln for ln in _SQL.splitlines() if not ln.lstrip().startswith("--"))
    assert "VACUUM" not in statements  # a plain table: no compressed-hypertable step applies


def test_the_only_writer_satisfies_the_check():
    """feature_lifecycle writes data_quality rows and leaves guard_status NULL."""
    assert fl._EVIDENCE_KIND == "data_quality"
    assert "guard_status" not in fl._UPSERT_EVALUATION_SQL
    assert "evidence_kind" in fl._UPSERT_EVALUATION_SQL
