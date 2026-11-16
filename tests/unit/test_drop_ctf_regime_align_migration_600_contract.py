"""Migration 600 drops the ctf_regime_align column and nothing else (R2 item 4)."""

from __future__ import annotations

import re
from pathlib import Path

SQL = (
    Path(__file__).resolve().parents[2]
    / "production"
    / "migrations"
    / "600_drop_ctf_regime_align.sql"
).read_text()
STATEMENTS = re.sub(r"--[^\n]*", "", SQL)


def test_it_drops_the_one_column_idempotently_in_a_transaction_and_only_when_empty() -> None:
    assert re.search(r"(?im)^\s*BEGIN;", STATEMENTS)
    assert re.search(r"(?im)^\s*COMMIT;", STATEMENTS)
    assert "DROP COLUMN IF EXISTS ctf_regime_align" in STATEMENTS
    assert len(re.findall(r"(?i)\bALTER TABLE\b", STATEMENTS)) == 1
    # the guards refuse a table holding rows or chunks instead of touching data
    assert "RAISE EXCEPTION 'migration 600: feature_vectors holds rows" in STATEMENTS
    assert "RAISE EXCEPTION 'migration 600: feature_vectors has chunks" in STATEMENTS


def test_it_leaves_the_concept_registry_to_its_service() -> None:
    assert "concept_registry" not in STATEMENTS  # only ConceptRegistryService flips a status
