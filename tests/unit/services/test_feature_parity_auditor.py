"""Unit tests for FeatureParityAuditor audit logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_pool(total_rows: int, field_counts: dict[str, int]) -> MagicMock:
    """Return a mock asyncpg pool where fetchval returns controlled values.

    total_rows: returned for the COUNT(*) query (no $1 bind param).
    field_counts: mapping from field name to the FILTER count for that field.
    """
    conn = AsyncMock()

    async def mock_fetchval(sql: str, *args):
        # First call (no args): total row count query
        if not args:
            return total_rows
        # Subsequent calls: per-field FILTER count
        field = args[0]
        return field_counts.get(field, 0)

    conn.fetchval = mock_fetchval

    pool = MagicMock()
    pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(),
        )
    )
    return pool


@pytest.mark.asyncio
async def test_violation_when_field_missing(monkeypatch):
    """When dt_db_confidence is 100% NULL (count==0), it appears in the violations list."""
    import services.feature_parity_auditor as mod

    mock_gauge = MagicMock()
    mock_counter = MagicMock()
    monkeypatch.setattr(mod, "FEATURE_PARITY_NULL_FIELDS_TOTAL", mock_gauge)
    monkeypatch.setattr(mod, "FEATURE_PARITY_AUDITS_RUN_TOTAL", mock_counter)

    pool = _make_pool(
        total_rows=500,
        field_counts={
            "dt_db_confidence": 0,  # missing — violation
            "hs_confidence": 300,
            "tri_confidence": 250,
        },
    )

    violations = await mod._run_audit(pool)

    assert "dt_db_confidence" in violations
    assert "hs_confidence" not in violations
    assert "tri_confidence" not in violations
    mock_gauge.set.assert_called_once_with(1, {})
    mock_counter.add.assert_called_once_with(1, {})


@pytest.mark.asyncio
async def test_clean_when_all_fields_present(monkeypatch):
    """When all fields have non-zero counts, violations list is empty."""
    import services.feature_parity_auditor as mod

    mock_gauge = MagicMock()
    mock_counter = MagicMock()
    monkeypatch.setattr(mod, "FEATURE_PARITY_NULL_FIELDS_TOTAL", mock_gauge)
    monkeypatch.setattr(mod, "FEATURE_PARITY_AUDITS_RUN_TOTAL", mock_counter)

    pool = _make_pool(
        total_rows=800,
        field_counts={
            "dt_db_confidence": 400,
            "hs_confidence": 350,
            "tri_confidence": 300,
        },
    )

    violations = await mod._run_audit(pool)

    assert violations == []
    mock_gauge.set.assert_called_once_with(0, {})
    mock_counter.add.assert_called_once_with(1, {})


@pytest.mark.asyncio
async def test_no_recent_rows_returns_empty_violations(monkeypatch):
    """When intelligence_features has no rows in the last hour, audit returns empty and sets gauge to 0."""
    import services.feature_parity_auditor as mod

    mock_gauge = MagicMock()
    mock_counter = MagicMock()
    monkeypatch.setattr(mod, "FEATURE_PARITY_NULL_FIELDS_TOTAL", mock_gauge)
    monkeypatch.setattr(mod, "FEATURE_PARITY_AUDITS_RUN_TOTAL", mock_counter)

    pool = _make_pool(total_rows=0, field_counts={})

    violations = await mod._run_audit(pool)

    assert violations == []
    mock_gauge.set.assert_called_once_with(0, {})
    mock_counter.add.assert_called_once_with(1, {})


@pytest.mark.asyncio
async def test_multiple_violations_recorded(monkeypatch):
    """When multiple fields are 100% NULL, all appear in violations list."""
    import services.feature_parity_auditor as mod

    mock_gauge = MagicMock()
    mock_counter = MagicMock()
    monkeypatch.setattr(mod, "FEATURE_PARITY_NULL_FIELDS_TOTAL", mock_gauge)
    monkeypatch.setattr(mod, "FEATURE_PARITY_AUDITS_RUN_TOTAL", mock_counter)

    pool = _make_pool(
        total_rows=600,
        field_counts={
            "dt_db_confidence": 0,
            "hs_confidence": 0,
            "tri_confidence": 0,
        },
    )

    violations = await mod._run_audit(pool)

    assert set(violations) == {"dt_db_confidence", "hs_confidence", "tri_confidence"}
    mock_gauge.set.assert_called_once_with(3, {})
