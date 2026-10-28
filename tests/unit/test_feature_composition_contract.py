"""Contract for migration 533 and the HMM recipe seed (187-12, todo 459): source-level, no DB."""

from __future__ import annotations

import re
import subprocess

from scripts.research import seed_hmm_recipes as seed
from src.intelligence.features.feature_vector_persistence import (
    REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES,
    REGIME_WRITER_OWNED_COLUMN_NAMES,
)
from src.intelligence.research.recipe import RecipeContent
from tests.unit._source_grep_helpers import read_source

_NAME = "533_feature_composition_and_hmm_registration.sql"


def _sql() -> str:
    return re.sub(r"--[^\n]*", "", read_source("production", "migrations", _NAME))


def test_tier_becomes_composition_in_one_transaction():
    sql = _sql()
    assert sql.count("BEGIN;") == 1 and sql.count("COMMIT;") == 1
    assert "metadata - 'tier'" in sql
    assert "WHEN '1_interaction' THEN 'interaction' ELSE 'base'" in sql


def test_cvr_namespace_tier_is_replaced_by_composition():
    sql = _sql()
    assert "DELETE FROM controlled_vocabulary WHERE namespace = 'tier'" in sql
    assert "('composition', 'base'" in sql and "('composition', 'interaction'" in sql


def test_migration_registers_exactly_the_seed_columns_active_with_a_gate():
    sql = _sql()
    for name in seed.EXPECTED_COLUMNS:
        assert f"('{name}'," in sql
    assert sql.count("('hmm_") == len(seed.EXPECTED_COLUMNS)
    assert "'active', true" in sql and "INSERT INTO concept_gate" in sql
    assert "concept_recipe" not in sql  # recipes are the S6 ledger's


def test_seed_columns_are_regime_writer_owned_hmm_columns():
    owned = set(REGIME_WRITER_OWNED_COLUMN_NAMES) | set(REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES)
    assert seed.EXPECTED_COLUMNS <= owned
    assert len(seed.EXPECTED_COLUMNS) == 11


def test_seed_code_pointer_and_commit_are_pinned():
    assert seed.CODE_POINTER == "services.regime_writer:_write_family_results"
    assert "def _write_family_results" in read_source("services", "regime_writer.py")
    assert re.fullmatch(r"[0-9a-f]{40}", seed.CODE_COMMIT)
    commit = subprocess.run(
        ["git", "cat-file", "-t", seed.CODE_COMMIT], capture_output=True, text=True, check=False
    )
    assert commit.stdout.strip() == "commit"


def test_seed_recipes_are_distinct_valid_recipes():
    recipes = seed.recipes()
    assert set(recipes) == seed.EXPECTED_COLUMNS
    assert all(isinstance(r, RecipeContent) for r in recipes.values())
    assert len({r.recipe_hash for r in recipes.values()}) == len(recipes)
    assert all(r.cvr_codes == {"composition": "base"} for r in recipes.values())


def test_genesis_seed_migration_covers_exactly_the_registered_columns():
    sql = re.sub(
        r"--[^\n]*", "", read_source("production", "migrations", "535_hmm_columns_genesis_seed.sql")
    )
    assert "'genesis_seed'" in sql and "registered_by' = 'migration_533'" in sql
    assert "NOT EXISTS" in sql  # idempotent
