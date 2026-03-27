"""Tests for ParityRepository and parity Prometheus metrics.

TDD RED phase — tests written before implementation.
Phase 52.5: ParityAuditorAgent
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Behavior 8: ParityRepository has fetch_window ────────────────────────────


def test_parity_repository_has_fetch_window():
    """Test 8: ParityRepository has fetch_window method accepting table_name parameter."""
    from src.persistence.repository.parity_repository import ParityRepository

    mock_pool = MagicMock()
    repo = ParityRepository(mock_pool)
    assert hasattr(repo, "fetch_window")
    import inspect

    sig = inspect.signature(repo.fetch_window)
    params = list(sig.parameters)
    assert "table_name" in params
    assert "since" in params
    assert "until" in params


# ── Behavior 9: ParityRepository has insert_violations ───────────────────────


def test_parity_repository_has_insert_violations():
    """Test 9: ParityRepository has insert_violations method."""
    from src.persistence.repository.parity_repository import ParityRepository

    mock_pool = MagicMock()
    repo = ParityRepository(mock_pool)
    assert hasattr(repo, "insert_violations")
    import inspect

    sig = inspect.signature(repo.insert_violations)
    params = list(sig.parameters)
    assert "violations" in params
    assert "run_id" in params


# ── Behavior 10: ParityRepository has fetch_clean_cycles ─────────────────────


def test_parity_repository_has_fetch_clean_cycles():
    """Test 10: ParityRepository has fetch_clean_cycles(symbol, tf, threshold) method."""
    from src.persistence.repository.parity_repository import ParityRepository

    mock_pool = MagicMock()
    repo = ParityRepository(mock_pool)
    assert hasattr(repo, "fetch_clean_cycles")
    import inspect

    sig = inspect.signature(repo.fetch_clean_cycles)
    params = list(sig.parameters)
    assert "symbol" in params
    assert "tf" in params
    assert "threshold" in params

    # D-09: these methods must NOT exist (no certification state table)
    assert not hasattr(
        repo, "fetch_certification_state"
    ), "fetch_certification_state must NOT exist per D-09"
    assert not hasattr(
        repo, "update_certification_state"
    ), "update_certification_state must NOT exist per D-09"


# ── Behavior 11: ParityRepository rejects invalid table_name ─────────────────


@pytest.mark.asyncio
async def test_parity_repository_rejects_invalid_table():
    """Test 11: ParityRepository rejects table_name not in allow-list."""
    from src.persistence.repository.parity_repository import ParityRepository

    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pool.acquire = MagicMock(
        return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn), __aexit__=AsyncMock())
    )
    repo = ParityRepository(mock_pool)

    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = datetime(2026, 1, 1, 0, 10, tzinfo=UTC)
    with pytest.raises(ValueError, match="not in allowed"):
        await repo.fetch_window("malicious_table; DROP TABLE --", since, until)


@pytest.mark.asyncio
async def test_parity_repository_accepts_valid_tables():
    """ParityRepository accepts both allowed table names."""
    from src.persistence.repository.parity_repository import ParityRepository

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_pool = AsyncMock()
    mock_pool.__aenter__ = AsyncMock(return_value=mock_pool)
    mock_pool.__aexit__ = AsyncMock()
    mock_pool.acquire = MagicMock()

    # Use context manager pattern for acquire
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock()
    mock_pool.acquire = MagicMock(return_value=cm)

    repo = ParityRepository(mock_pool)
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = datetime(2026, 1, 1, 0, 10, tzinfo=UTC)

    # Should not raise
    result = await repo.fetch_window("intelligence_features", since, until)
    assert isinstance(result, list)

    result = await repo.fetch_window("feature_snapshots_shadow", since, until)
    assert isinstance(result, list)


# ── Behavior 12: PARITY_MATCH_RATE and SHADOW_AHEAD_ROWS_TOTAL exist ─────────


def test_parity_metrics_exist_in_metrics_module():
    """Test 12: PARITY_MATCH_RATE and SHADOW_AHEAD_ROWS_TOTAL exist in metrics.py."""
    from src.observability.metrics import PARITY_MATCH_RATE, SHADOW_AHEAD_ROWS_TOTAL

    # Verify they're usable (Gauge/Counter with labels)
    from prometheus_client import Counter, Gauge

    assert isinstance(PARITY_MATCH_RATE, Gauge)
    assert isinstance(SHADOW_AHEAD_ROWS_TOTAL, Counter)


def test_parity_violations_total_exists():
    """PARITY_VIOLATIONS_TOTAL counter exists in metrics.py."""
    from src.observability.metrics import PARITY_VIOLATIONS_TOTAL
    from prometheus_client import Counter

    assert isinstance(PARITY_VIOLATIONS_TOTAL, Counter)


def test_parity_cycles_total_exists():
    """PARITY_CYCLES_TOTAL counter exists in metrics.py."""
    from src.observability.metrics import PARITY_CYCLES_TOTAL
    from prometheus_client import Counter

    assert isinstance(PARITY_CYCLES_TOTAL, Counter)


# ── insert_violations async test ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_insert_violations_calls_executemany():
    """insert_violations batches FieldViolations using executemany."""
    import uuid
    from src.core.schemas.parity import FieldViolation
    from src.persistence.repository.parity_repository import ParityRepository

    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    violation = FieldViolation(
        ts=ts,
        symbol="ES",
        tf="1m",
        field_name="winner_confidence",
        primary_value="0.7",
        shadow_value="0.8",
        abs_diff=0.1,
    )

    mock_conn = AsyncMock()
    mock_conn.executemany = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock()

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=cm)

    repo = ParityRepository(mock_pool)
    run_id = uuid.uuid4()
    await repo.insert_violations([violation], run_id)

    assert mock_conn.executemany.called


# ── fetch_clean_cycles async test ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_clean_cycles_returns_int():
    """fetch_clean_cycles returns an integer (clean window count)."""
    from src.persistence.repository.parity_repository import ParityRepository

    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=8)  # 8 clean windows out of 12 threshold
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock()

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=cm)

    repo = ParityRepository(mock_pool)
    result = await repo.fetch_clean_cycles("ES", "1m", 12)
    assert isinstance(result, int)
    assert result == 8
