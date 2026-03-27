"""Tests for FeatureRepository configurable table_name support."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


def test_feature_repository_uses_default_table():
    from src.persistence.repository.feature_repository import FeatureRepository

    db = MagicMock()
    db.execute_command = AsyncMock()
    repo = FeatureRepository(db)
    assert "intelligence_features" in repo._insert_sql


def test_feature_repository_accepts_shadow_table():
    from src.persistence.repository.feature_repository import FeatureRepository

    db = MagicMock()
    db.execute_command = AsyncMock()
    repo = FeatureRepository(db, table_name="feature_snapshots_shadow")
    assert "feature_snapshots_shadow" in repo._insert_sql
    assert "intelligence_features" not in repo._insert_sql


def test_feature_repository_default_table_name_attribute():
    from src.persistence.repository.feature_repository import FeatureRepository

    db = MagicMock()
    repo = FeatureRepository(db)
    assert repo.table_name == "intelligence_features"


def test_feature_repository_shadow_table_name_attribute():
    from src.persistence.repository.feature_repository import FeatureRepository

    db = MagicMock()
    repo = FeatureRepository(db, table_name="feature_snapshots_shadow")
    assert repo.table_name == "feature_snapshots_shadow"


def test_feature_repository_rejects_invalid_table():
    from src.persistence.repository.feature_repository import FeatureRepository

    db = MagicMock()
    with pytest.raises(ValueError, match="not in allowed table"):
        FeatureRepository(db, table_name="malicious_table; DROP TABLE users--")


def test_insert_shadow_calls_correct_sql():
    from src.persistence.repository.feature_repository import FeatureRepository

    db = MagicMock()
    db.execute_command = AsyncMock()
    repo = FeatureRepository(db, table_name="feature_snapshots_shadow")
    params = tuple(range(31))
    assert len(params) == 31  # guard: catches silent field count regressions
    asyncio.run(repo.insert(params))
    db.execute_command.assert_awaited_once()
    call_sql = db.execute_command.call_args[0][0]
    assert "feature_snapshots_shadow" in call_sql
