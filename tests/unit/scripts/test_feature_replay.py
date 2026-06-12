"""Static correctness guards for feature_replay.py.

These tests do not execute the script — they inspect source text to enforce
architectural invariants that must never regress:

1. No I1-I6 compute imports (DAG isolation)
2. No uuid4 usage (deterministic signal IDs only)
3. ON CONFLICT preserves identity columns (idempotency)
4. New column names only (migration 125 compliance)
"""

import pathlib

_SCRIPT = pathlib.Path("production/scripts/feature_replay.py")


def _src() -> str:
    return _SCRIPT.read_text()


def test_script_exists() -> None:
    assert _SCRIPT.exists(), f"Expected {_SCRIPT} to exist"


def test_no_i16_compute_imports() -> None:
    """Forbidden: any I1-I6 compute pipeline function imported or called."""
    src = _src()
    forbidden = (
        "run_analysis_pipeline",
        "run_i7_and_persist",
        "IntelligencePipeline",
        "run_tiers",
    )
    for name in forbidden:
        assert name not in src, f"Forbidden compute symbol '{name}' found in feature_replay.py"


def test_no_uuid4() -> None:
    """Deterministic IDs only — uuid4 fallback must not appear."""
    assert "uuid4" not in _src(), "uuid4 found in feature_replay.py — use make_signal_id instead"


def test_on_conflict_identity_columns_not_in_set() -> None:
    """ON CONFLICT SET clause must not overwrite identity columns."""
    src = _src()
    # Find the DO UPDATE SET block
    assert (
        "ON CONFLICT (signal_id, timestamp) DO UPDATE SET" in src
    ), "Expected ON CONFLICT (signal_id, timestamp) DO UPDATE SET in _UPSERT_SIGNAL_SQL"
    # Extract the SET clause lines (between DO UPDATE SET and the closing quote)
    set_start = src.index("ON CONFLICT (signal_id, timestamp) DO UPDATE SET")
    set_block = src[set_start : set_start + 600]
    # Identity columns must not appear after the SET keyword
    for identity_col in ("signal_id =", "timestamp =", "symbol =", "feature_ts ="):
        assert (
            identity_col not in set_block
        ), f"Identity column '{identity_col}' must not be in DO UPDATE SET clause"


def test_new_column_names_only() -> None:
    """Legacy column names from before migration 125 must not appear."""
    src = _src()
    legacy_names = (
        "technical_indicators",
        "pattern_detections",
        "regime_features",
        "confluence_scores",
    )
    for name in legacy_names:
        assert (
            name not in src
        ), f"Legacy column name '{name}' found — use new names after migration 125"


def test_select_uses_new_column_names() -> None:
    """SELECT query must reference migration-125 column names."""
    src = _src()
    required_columns = ("i1", "i2", "i3", "i4", "i5", "smc", "cross_timeframe_context")
    for col in required_columns:
        assert col in src, f"Expected column '{col}' in _SELECT_FEATURES_SQL"


def test_cli_flags_present() -> None:
    """All six CLI flags must be declared in the script."""
    src = _src()
    flags = (
        "--plugins",
        "--symbols",
        "--since",
        "--workers",
        "--shadow-setups",
        "--dry-run",
    )
    for flag in flags:
        assert flag in src, f"CLI flag '{flag}' not found in feature_replay.py"
