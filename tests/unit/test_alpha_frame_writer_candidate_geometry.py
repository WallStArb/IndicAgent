"""Unit tests: AlphaFrameWriter's geometry_source dispatch (Phase 166 Plan 05).

Covers the geometry_source modes at the pure-function level -- no DB, no Kafka. Task 1
(Tests 1-4, this commit): FrameConfig.geometry_source validation + per_cell_scalar
per-(regime,tf) lookup with global fallback + aggregate-not-per-row missing-key accounting.
Task 2 (Tests 5-8) adds the structural mode's derivation in a follow-up commit.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.alpha_frame_writer import (
    FrameConfig,
    _resolve_row_geometry,
    _resolve_scalar_geometry,
)

_SOURCE_PATH = _project_root / "services" / "alpha_frame_writer.py"


def _read_source() -> str:
    return _SOURCE_PATH.read_text()


# ---------------------------------------------------------------------------
# Task 1 -- FrameConfig.geometry_source validation
# ---------------------------------------------------------------------------


def test_geometry_source_defaults_to_global():
    cfg = FrameConfig.from_apr({})
    assert cfg.geometry_source == "global"


def test_geometry_source_accepts_per_cell_scalar_and_structural():
    assert FrameConfig.from_apr({"alpha.frame.geometry_source": "per_cell_scalar"}).geometry_source == "per_cell_scalar"  # fmt: skip
    assert FrameConfig.from_apr({"alpha.frame.geometry_source": "structural"}).geometry_source == "structural"  # fmt: skip


def test_invalid_geometry_source_raises_at_config_load():
    """An invalid geometry_source is validated once, eagerly, at FrameConfig.from_apr load
    time -- the same discipline as stop_atr_mult<=0 -- never rediscovered per-frame deep in a
    --backfill scan."""
    try:
        FrameConfig.from_apr({"alpha.frame.geometry_source": "bogus"})
        raised = False
    except ValueError as error:
        raised = True
        assert "geometry_source" in str(error)
    assert raised


# ---------------------------------------------------------------------------
# Test 1 -- global geometry_source is byte-identical to pre-166-05 behavior
# ---------------------------------------------------------------------------


def test_global_geometry_source_ignores_per_cell_keys_and_cfg_entirely():
    """Regression: even when per-cell keys ARE present in cfg, geometry_source="global" must
    still return the plain global scalars unchanged -- no per-cell lookup performed at all."""
    frame_config = FrameConfig.from_apr(
        {"alpha.frame.stop_atr_mult": "1.5", "alpha.frame.target_r_multiple": "2.0"}
    )
    cfg = {
        "alpha.frame.stop_atr_mult.trending_up.5m": "9.9",
        "alpha.frame.target_r_multiple.trending_up.5m": "9.9",
    }
    missing_stop_keys: set[str] = set()
    missing_target_keys: set[str] = set()

    result = _resolve_row_geometry(
        "global",
        cfg,
        "trending_up",
        "5m",
        frame_config,
        missing_stop_keys,
        missing_target_keys,
    )

    assert result == (1.5, 2.0)
    assert missing_stop_keys == set()
    assert missing_target_keys == set()


# ---------------------------------------------------------------------------
# Tests 2-4 -- per_cell_scalar lookup with fallback + aggregate missing-key accounting
# ---------------------------------------------------------------------------


def test_per_cell_scalar_uses_present_key():
    frame_config = FrameConfig.from_apr({})
    cfg = {
        "alpha.frame.stop_atr_mult.trending_up.5m": "1.2",
        "alpha.frame.target_r_multiple.trending_up.5m": "1.8",
    }
    missing_stop_keys: set[str] = set()
    missing_target_keys: set[str] = set()

    result = _resolve_scalar_geometry(
        cfg, "trending_up", "5m", frame_config, missing_stop_keys, missing_target_keys
    )

    assert result == (1.2, 1.8)
    assert missing_stop_keys == set()
    assert missing_target_keys == set()


def test_per_cell_scalar_falls_back_to_global_on_missing_key():
    frame_config = FrameConfig.from_apr(
        {"alpha.frame.stop_atr_mult": "1.5", "alpha.frame.target_r_multiple": "2.0"}
    )
    missing_stop_keys: set[str] = set()
    missing_target_keys: set[str] = set()

    result = _resolve_scalar_geometry(
        {}, "ranging", "1h", frame_config, missing_stop_keys, missing_target_keys
    )

    assert result == (1.5, 2.0)
    assert missing_stop_keys == {"alpha.frame.stop_atr_mult.ranging.1h"}
    assert missing_target_keys == {"alpha.frame.target_r_multiple.ranging.1h"}


def test_dispatch_per_cell_scalar_matches_direct_call():
    frame_config = FrameConfig.from_apr({"alpha.frame.geometry_source": "per_cell_scalar"})
    cfg = {"alpha.frame.stop_atr_mult.ranging.1h": "1.1"}
    missing_stop_keys: set[str] = set()
    missing_target_keys: set[str] = set()

    result = _resolve_row_geometry(
        "per_cell_scalar",
        cfg,
        "ranging",
        "1h",
        frame_config,
        missing_stop_keys,
        missing_target_keys,
    )

    assert result == (1.1, frame_config.target_r_multiple)
    assert missing_stop_keys == set()
    assert missing_target_keys == {"alpha.frame.target_r_multiple.ranging.1h"}


def test_missing_keys_accumulate_across_rows_without_duplication():
    """The same missing (regime, tf) cell recurring across many rows must add exactly one
    entry to the accumulator set -- the shape that lets _process_partition warn ONCE per
    partition (CLAUDE.md's never-log-per-row rule) regardless of how many rows hit it."""
    frame_config = FrameConfig.from_apr({})
    missing_stop_keys: set[str] = set()
    missing_target_keys: set[str] = set()

    for _ in range(50):
        _resolve_scalar_geometry(
            {}, "ranging", "1h", frame_config, missing_stop_keys, missing_target_keys
        )

    assert missing_stop_keys == {"alpha.frame.stop_atr_mult.ranging.1h"}
    assert missing_target_keys == {"alpha.frame.target_r_multiple.ranging.1h"}


def test_missing_key_warnings_logged_once_per_partition_source_guard():
    """Source-guard companion to the accumulation test above: _process_partition's
    stop/target missing-key warnings live OUTSIDE the per-row streaming loop (mirroring the
    existing missing_hold_keys precedent), each appearing exactly once in source."""
    src = _read_source()
    assert src.count('"alpha_frame_writer.stop_atr_mult_key_missing"') == 1
    assert src.count('"alpha_frame_writer.target_r_multiple_key_missing"') == 1
    assert "missing_stop_keys: set[str] = set()" in src
    assert "missing_target_keys: set[str] = set()" in src
