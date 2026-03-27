"""Tests for _compare_rows pure function and FieldViolation schema.

TDD RED phase — tests written before implementation.
Phase 52.5: ParityAuditorAgent
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

# ── Behavior 1: FieldViolation model instantiation ───────────────────────────


def test_field_violation_instantiation():
    """Test 1: FieldViolation model instantiates with required fields."""
    from src.core.schemas.parity import FieldViolation

    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    v = FieldViolation(
        ts=ts,
        symbol="ES",
        tf="1m",
        field_name="i1.sma",
        primary_value="100.5",
        shadow_value="100.6",
        abs_diff=0.1,
    )
    assert v.ts == ts
    assert v.symbol == "ES"
    assert v.tf == "1m"
    assert v.field_name == "i1.sma"
    assert v.primary_value == "100.5"
    assert v.shadow_value == "100.6"
    assert v.abs_diff == pytest.approx(0.1)


def test_field_violation_abs_diff_optional():
    """FieldViolation abs_diff can be None for non-numeric fields."""
    from src.core.schemas.parity import FieldViolation

    v = FieldViolation(
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        symbol="NQ",
        tf="5m",
        field_name="session_type",
        primary_value="rth",
        shadow_value="eth",
        abs_diff=None,
    )
    assert v.abs_diff is None


# ── Behavior 2: _compare_rows identical rows returns empty list ───────────────


def test_compare_rows_identical_returns_empty():
    """Test 2: _compare_rows with identical rows returns empty list."""
    from services.parity_auditor_agent import _compare_rows

    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    row = {
        "ts": ts,
        "symbol": "ES",
        "tf": "1m",
        "winner_confidence": 0.75,
        "session_type": "rth",
    }
    result = _compare_rows(row, row.copy())
    assert result == []


# ── Behavior 3: _compare_rows numeric divergence beyond tolerance ─────────────


def test_compare_rows_numeric_divergence_returns_violation():
    """Test 3: _compare_rows with numeric divergence beyond NUMERIC_TOLERANCE returns violation."""
    from services.parity_auditor_agent import NUMERIC_TOLERANCE, _compare_rows

    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    primary = {"ts": ts, "symbol": "ES", "tf": "1m", "winner_confidence": 0.75}
    shadow = {"ts": ts, "symbol": "ES", "tf": "1m", "winner_confidence": 0.76}

    violations = _compare_rows(primary, shadow)
    assert len(violations) == 1
    v = violations[0]
    assert v.field_name == "winner_confidence"
    assert v.symbol == "ES"
    assert v.tf == "1m"
    assert v.abs_diff is not None
    assert v.abs_diff > NUMERIC_TOLERANCE


# ── Behavior 4: _compare_rows within tolerance returns empty ──────────────────


def test_compare_rows_within_tolerance_returns_empty():
    """Test 4: _compare_rows with numeric difference within NUMERIC_TOLERANCE returns empty list."""
    from services.parity_auditor_agent import NUMERIC_TOLERANCE, _compare_rows

    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    tiny_diff = NUMERIC_TOLERANCE / 10  # well within tolerance
    primary = {"ts": ts, "symbol": "ES", "tf": "1m", "winner_confidence": 0.75}
    shadow = {"ts": ts, "symbol": "ES", "tf": "1m", "winner_confidence": 0.75 + tiny_diff}

    violations = _compare_rows(primary, shadow)
    assert violations == []


# ── Behavior 5: _compare_rows JSONB dict divergence recurses ─────────────────


def test_compare_rows_jsonb_dict_recurses_dotted_path():
    """Test 5: _compare_rows with JSONB dict divergence recurses and produces dotted field paths."""
    from services.parity_auditor_agent import _compare_rows

    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    primary = {
        "ts": ts,
        "symbol": "ES",
        "tf": "1m",
        "i1": {"sma": 4500.0, "rsi": 55.0},
    }
    shadow = {
        "ts": ts,
        "symbol": "ES",
        "tf": "1m",
        "i1": {"sma": 4501.0, "rsi": 55.0},  # sma diverges
    }

    violations = _compare_rows(primary, shadow)
    assert len(violations) == 1
    assert violations[0].field_name == "i1.sma"
    assert violations[0].abs_diff == pytest.approx(1.0)


# ── Behavior 6: _compare_rows None vs value ───────────────────────────────────


def test_compare_rows_none_vs_value_produces_violation():
    """Test 6: _compare_rows with None vs non-None value produces a violation."""
    from services.parity_auditor_agent import _compare_rows

    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    primary = {"ts": ts, "symbol": "ES", "tf": "1m", "winner_confidence": None}
    shadow = {"ts": ts, "symbol": "ES", "tf": "1m", "winner_confidence": 0.5}

    violations = _compare_rows(primary, shadow)
    assert len(violations) == 1
    assert violations[0].field_name == "winner_confidence"
    assert violations[0].abs_diff is None  # None comparison, not numeric


# ── Behavior 7: _compare_rows string field divergence ─────────────────────────


def test_compare_rows_string_divergence_produces_violation():
    """Test 7: _compare_rows with string field divergence produces a violation."""
    from services.parity_auditor_agent import _compare_rows

    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    primary = {"ts": ts, "symbol": "ES", "tf": "1m", "session_type": "rth"}
    shadow = {"ts": ts, "symbol": "ES", "tf": "1m", "session_type": "eth"}

    violations = _compare_rows(primary, shadow)
    assert len(violations) == 1
    assert violations[0].field_name == "session_type"
    assert violations[0].abs_diff is None
    assert violations[0].primary_value == "rth"
    assert violations[0].shadow_value == "eth"


# ── Additional edge cases ─────────────────────────────────────────────────────


def test_compare_rows_skips_join_key_columns():
    """Join keys (ts, symbol, tf) are skipped — they're not comparison targets."""
    from services.parity_auditor_agent import _compare_rows

    ts = datetime(2026, 1, 1, tzinfo=UTC)
    # Artificially different ts/symbol/tf to ensure they're skipped
    primary = {"ts": ts, "symbol": "ES", "tf": "1m"}
    shadow = {"ts": ts, "symbol": "NQ", "tf": "5m"}  # different symbol/tf — must be skipped

    violations = _compare_rows(primary, shadow)
    assert violations == []


def test_compare_rows_both_none_no_violation():
    """Both values None — not a violation."""
    from services.parity_auditor_agent import _compare_rows

    ts = datetime(2026, 1, 1, tzinfo=UTC)
    primary = {"ts": ts, "symbol": "ES", "tf": "1m", "winner_confidence": None}
    shadow = {"ts": ts, "symbol": "ES", "tf": "1m", "winner_confidence": None}

    violations = _compare_rows(primary, shadow)
    assert violations == []


def test_compare_rows_multiple_field_violations():
    """Multiple diverging fields produce multiple violations."""
    from services.parity_auditor_agent import _compare_rows

    ts = datetime(2026, 1, 1, tzinfo=UTC)
    primary = {
        "ts": ts,
        "symbol": "ES",
        "tf": "1m",
        "winner_confidence": 0.7,
        "session_type": "rth",
    }
    shadow = {"ts": ts, "symbol": "ES", "tf": "1m", "winner_confidence": 0.8, "session_type": "eth"}

    violations = _compare_rows(primary, shadow)
    assert len(violations) == 2
    field_names = {v.field_name for v in violations}
    assert "winner_confidence" in field_names
    assert "session_type" in field_names


def test_compare_rows_constants():
    """NUMERIC_TOLERANCE and CERTIFICATION_THRESHOLD have correct values."""
    from services.parity_auditor_agent import CERTIFICATION_THRESHOLD, NUMERIC_TOLERANCE

    assert NUMERIC_TOLERANCE == pytest.approx(1e-9)
    assert CERTIFICATION_THRESHOLD == 12
