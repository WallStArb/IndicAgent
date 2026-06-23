"""Unit test: IC engine idempotency and ON CONFLICT DO NOTHING SQL assertions.

Verifies:
  1. The skip-set dedup logic: cells already in existing_keys are skipped.
  2. Both INSERT SQL constants (_POOLED_INSERT_SQL, _REGIME_INSERT_SQL) contain
     ON CONFLICT ... DO NOTHING (idempotent upsert).
  3. is_pooled handling: pooled and regime rows use separate SQL with separate
     ON CONFLICT column lists.

No DB, no Kafka. Pure Python inspection of module constants and logic.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import (
    _POOLED_INSERT_SQL,
    _POOLED_REGIME_SENTINEL,
    _REGIME_INSERT_SQL,
)

# ---------------------------------------------------------------------------
# Helper: replicate the skip-set check as used in _compute_symbol_tf
# ---------------------------------------------------------------------------


def cell_already_present(
    existing_keys: set,
    feature_name: str,
    symbol: str,
    tf: str,
    regime: str,
    lookahead_bars: int,
    is_pooled: bool,
) -> bool:
    """Replicate the idempotency check from ic_engine._compute_symbol_tf.

    A cell is skipped if (feature_name, symbol, tf, regime, lookahead_bars, is_pooled)
    is already in the existing_keys set loaded at startup.
    """
    return (feature_name, symbol, tf, regime, lookahead_bars, is_pooled) in existing_keys


# ---------------------------------------------------------------------------
# Tests: skip-set dedup logic
# ---------------------------------------------------------------------------


def test_skip_returns_true_for_existing_cell():
    """cell_already_present returns True when the cell key is in existing_keys."""
    existing_keys = {
        ("rsi_fast", "SPY", "5m", "trending_up", 1, False),
        ("rsi_fast", "SPY", "5m", "_pooled", 1, True),
    }
    assert cell_already_present(existing_keys, "rsi_fast", "SPY", "5m", "trending_up", 1, False)


def test_skip_returns_false_for_new_cell():
    """cell_already_present returns False when the cell key is not in existing_keys."""
    existing_keys = {
        ("rsi_fast", "SPY", "5m", "trending_up", 1, False),
    }
    # Different feature
    assert not cell_already_present(
        existing_keys, "macd_hist", "SPY", "5m", "trending_up", 1, False
    )
    # Different symbol
    assert not cell_already_present(existing_keys, "rsi_fast", "TLT", "5m", "trending_up", 1, False)
    # Different regime
    assert not cell_already_present(
        existing_keys, "rsi_fast", "SPY", "5m", "trending_down", 1, False
    )


def test_skip_is_pooled_key_differs_from_regime_key():
    """is_pooled=True and is_pooled=False with same other fields are distinct keys."""
    existing_keys = {
        ("rsi_fast", "SPY", "5m", "_pooled", 1, True),
    }
    # is_pooled=False should NOT be found even though feature/symbol/tf/lookahead match
    assert not cell_already_present(existing_keys, "rsi_fast", "SPY", "5m", "_pooled", 1, False)


def test_skip_pooled_sentinel_regime():
    """_POOLED_REGIME_SENTINEL is the key used for pooled cells in existing_keys."""
    # The ic_engine uses _POOLED_REGIME_SENTINEL = "_pooled" as the regime key
    # for pooled (is_pooled=True) rows.
    existing_keys = {
        ("rsi_fast", "SPY", "5m", _POOLED_REGIME_SENTINEL, 1, True),
    }
    assert cell_already_present(
        existing_keys, "rsi_fast", "SPY", "5m", _POOLED_REGIME_SENTINEL, 1, True
    )


# ---------------------------------------------------------------------------
# Tests: ON CONFLICT DO NOTHING in INSERT SQL
# ---------------------------------------------------------------------------


def test_pooled_insert_sql_contains_do_nothing():
    """_POOLED_INSERT_SQL must contain ON CONFLICT ... DO NOTHING (idempotent)."""
    assert "DO NOTHING" in _POOLED_INSERT_SQL, (
        "_POOLED_INSERT_SQL does not contain 'DO NOTHING'. "
        "This means re-runs will raise duplicate key violations instead of "
        "being idempotent. Check the ON CONFLICT clause in services/ic_engine.py."
    )


def test_regime_insert_sql_contains_do_nothing():
    """_REGIME_INSERT_SQL must contain ON CONFLICT ... DO NOTHING (idempotent)."""
    assert "DO NOTHING" in _REGIME_INSERT_SQL, (
        "_REGIME_INSERT_SQL does not contain 'DO NOTHING'. "
        "This means re-runs will raise duplicate key violations instead of "
        "being idempotent. Check the ON CONFLICT clause in services/ic_engine.py."
    )


def test_pooled_insert_sql_conflict_clause_is_for_pooled():
    """Pooled INSERT ON CONFLICT must reference the is_pooled=true partial index."""
    # The pooled partial index is: WHERE is_pooled = true
    # ON CONFLICT must use the column list + WHERE clause matching that index
    sql_upper = _POOLED_INSERT_SQL.upper()
    assert "IS_POOLED" in sql_upper or "is_pooled" in _POOLED_INSERT_SQL, (
        "_POOLED_INSERT_SQL ON CONFLICT clause does not reference is_pooled column. "
        "It must match the partial index WHERE is_pooled = true."
    )
    assert "WHERE IS_POOLED = TRUE" in sql_upper.replace("\n", " ").replace(
        "  ", " "
    ), "_POOLED_INSERT_SQL WHERE clause in ON CONFLICT must be 'WHERE is_pooled = true'"


def test_regime_insert_sql_conflict_clause_is_for_regime():
    """Regime INSERT ON CONFLICT must reference the is_pooled=false partial index."""
    sql_upper = _REGIME_INSERT_SQL.upper()
    assert "WHERE IS_POOLED = FALSE" in sql_upper.replace("\n", " ").replace(
        "  ", " "
    ), "_REGIME_INSERT_SQL WHERE clause in ON CONFLICT must be 'WHERE is_pooled = false'"


def test_pooled_and_regime_inserts_have_different_conflict_clauses():
    """Pooled and regime INSERT statements must use separate ON CONFLICT column lists."""
    # Pooled: no regime column in conflict list (regime is always '_pooled' sentinel)
    # Regime: includes regime column in conflict list
    # Both must have DO NOTHING but with different partial index WHERE conditions
    assert _POOLED_INSERT_SQL != _REGIME_INSERT_SQL, (
        "Pooled and regime INSERT SQL are identical -- they should use different "
        "ON CONFLICT column lists and WHERE conditions matching their respective "
        "partial indexes."
    )
