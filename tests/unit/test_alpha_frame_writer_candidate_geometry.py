"""Unit tests: AlphaFrameWriter's geometry_source dispatch (Phase 166 Plan 05).

Covers the three geometry_source modes (global | per_cell_scalar | structural) at the
pure-function level -- no DB, no Kafka. Task 1 (Tests 1-4): FrameConfig.geometry_source
validation + per_cell_scalar per-(regime,tf) lookup with global fallback + aggregate-not-
per-row missing-key accounting. Task 2 (Tests 5-8): structural mode's derivation via
structural_confluence.resolve_structural_zone, the tier="atr" scalar fallback, and the
degenerate-stop-distance ValueError-skip contract (todo 162) preserved for both the scalar
seed and the final effective geometry.
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
    _resolve_structural_geometry,
)
from src.intelligence.trading import structural_confluence

_SOURCE_PATH = _project_root / "services" / "alpha_frame_writer.py"


def _read_source() -> str:
    return _SOURCE_PATH.read_text()


def setup_function(_fn):
    """Reset structural_confluence's module-level config singleton before every test in this
    file -- a prior test (in this file or another) calling set_config_service would otherwise
    leak a non-default threshold into a later test's zone-resolution math (module-level global,
    shared across the whole pytest process)."""
    structural_confluence.set_config_service(None)


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


# ---------------------------------------------------------------------------
# Tests 5-8 -- structural geometry_source
# ---------------------------------------------------------------------------

_ENTRY = 100.0
_ATR = 2.0
_SCALAR_STOP_ATR_MULT = 1.5  # seed window: (97.0, 100.0) for direction="long"
_TARGET_R_MULTIPLE = 2.0


def test_structural_mode_derives_stop_from_confluence_zone():
    """Test 5: a single strong S/R candidate inside the scalar-seed window resolves to
    tier="single" and an effective_stop_atr_mult that differs from the pure scalar seed
    (stop != entry - global_mult*atr)."""
    # sr_support at 98.5 = entry(100) - 0.75*atr(2.0) -- strictly inside (97.0, 100.0).
    features = {"sr_support_dist": 0.75}

    result = _resolve_structural_geometry(
        features,
        "long",
        _ENTRY,
        _ATR,
        _SCALAR_STOP_ATR_MULT,
        _TARGET_R_MULTIPLE,
        min_stop_price_fraction=0.0,
    )

    assert result is not None
    effective_stop_atr_mult, target_r_multiple = result
    assert effective_stop_atr_mult != _SCALAR_STOP_ATR_MULT
    assert target_r_multiple == _TARGET_R_MULTIPLE


def test_structural_mode_falls_back_to_scalar_when_tier_atr():
    """Test 6: no Phase-163 columns populated (NULL_PENDING_163) -> resolve_structural_zone
    returns tier="atr" -> the function returns the scalar seed UNCHANGED."""
    features: dict[str, float] = {}

    result = _resolve_structural_geometry(
        features,
        "long",
        _ENTRY,
        _ATR,
        _SCALAR_STOP_ATR_MULT,
        _TARGET_R_MULTIPLE,
        min_stop_price_fraction=0.0,
    )

    assert result == (_SCALAR_STOP_ATR_MULT, _TARGET_R_MULTIPLE)


def test_structural_mode_honors_degenerate_atr_skip_on_scalar_seed():
    """Test 7a: the scalar-seed stop itself is degenerate (razor-thin on a near-zero ATR) --
    compute_frame_geometry's min_stop_price_fraction guard (todo 162) fires before the
    structural zone is even resolved. Returns None (caller skips the frame)."""
    result = _resolve_structural_geometry(
        {"sr_support_dist": 0.75},
        "long",
        entry_price=100.0,
        atr=0.0001,
        scalar_stop_atr_mult=1.5,
        target_r_multiple=2.0,
        min_stop_price_fraction=0.001,
    )
    assert result is None


def test_structural_mode_honors_degenerate_atr_skip_on_resolved_structural_stop():
    """Test 7b: the scalar seed passes, but the RESOLVED structural stop (very close to
    entry) is degenerate under a strict min_stop_price_fraction floor -- the second
    compute_frame_geometry call (post structural-zone-resolution) must also raise-and-skip,
    not just the first."""
    # sr_support at 99.998 = entry(100) - 0.001*atr(2.0) -- inside (97.0, 100.0), and the
    # single-best zone (radius 0.25*atr=0.5) centers on it: zone_low ~= 99.498.
    features = {"sr_support_dist": 0.001}

    result = _resolve_structural_geometry(
        features,
        "long",
        entry_price=100.0,
        atr=2.0,
        scalar_stop_atr_mult=1.5,
        target_r_multiple=2.0,
        min_stop_price_fraction=0.01,  # requires stop_distance >= 1.0; resolved ~0.502
    )
    assert result is None


def test_structural_effective_stop_atr_mult_matches_zone_low_formula():
    """Test 8: the effective stop_atr_mult snapshotted onto the row is EXACTLY
    abs(entry_price - zone_low) / atr for the resolved single-best zone (long direction) --
    not an approximation. Cross-checks the exact numeric value zone_engine.py's ported
    _pick_single_best/_expand_to_min_width math produces for this fixture."""
    features = {"sr_support_dist": 0.75}  # support price = 98.5

    result = _resolve_structural_geometry(
        features,
        "long",
        _ENTRY,
        _ATR,
        _SCALAR_STOP_ATR_MULT,
        _TARGET_R_MULTIPLE,
        min_stop_price_fraction=0.0,
    )

    assert result is not None
    effective_stop_atr_mult, _ = result
    # single_level_radius_atr default 0.25 -> r = 0.5; zone_low = 98.5 - 0.5 = 98.0;
    # effective_stop_atr_mult = abs(100 - 98.0) / 2.0 = 1.0.
    assert abs(effective_stop_atr_mult - 1.0) < 1e-9


def test_structural_mode_short_direction_uses_zone_high():
    """The short-direction mirror of Test 8 -- resistance above entry, effective stop derived
    from zone_high (the bound away from entry on the stop side for a short)."""
    # sr_resist at 101.5 = entry(100) + 0.75*atr(2.0) -- inside (100.0, 103.0) for short's
    # (entry, stop_seed) window.
    features = {"sr_resist_dist": 0.75}

    result = _resolve_structural_geometry(
        features,
        "short",
        _ENTRY,
        _ATR,
        _SCALAR_STOP_ATR_MULT,
        _TARGET_R_MULTIPLE,
        min_stop_price_fraction=0.0,
    )

    assert result is not None
    effective_stop_atr_mult, _ = result
    # zone_high = 101.5 + 0.5 = 102.0; effective_stop_atr_mult = abs(100 - 102.0) / 2.0 = 1.0.
    assert abs(effective_stop_atr_mult - 1.0) < 1e-9


def test_dispatch_structural_falls_back_to_scalar_when_market_data_missing():
    """When entry_price/atr/features can't be resolved for a bar (no market data at that
    bar_ts -- a data-availability gap, distinct from the degenerate-ATR condition
    compute_frame_geometry guards against), the dispatch degrades to the scalar seed rather
    than skipping the frame."""
    frame_config = FrameConfig.from_apr(
        {"alpha.frame.geometry_source": "structural", "alpha.frame.stop_atr_mult": "1.5"}
    )
    missing_stop_keys: set[str] = set()
    missing_target_keys: set[str] = set()

    result = _resolve_row_geometry(
        "structural",
        {},
        "ranging",
        "1h",
        frame_config,
        missing_stop_keys,
        missing_target_keys,
        features=None,
        direction="long",
        entry_price=None,
        atr=None,
    )

    assert result == (1.5, frame_config.target_r_multiple)


def test_dispatch_structural_derives_from_zone_when_market_data_present():
    frame_config = FrameConfig.from_apr({"alpha.frame.geometry_source": "structural"})
    missing_stop_keys: set[str] = set()
    missing_target_keys: set[str] = set()

    result = _resolve_row_geometry(
        "structural",
        {},
        "ranging",
        "1h",
        frame_config,
        missing_stop_keys,
        missing_target_keys,
        features={"sr_support_dist": 0.75},
        direction="long",
        entry_price=_ENTRY,
        atr=_ATR,
    )

    assert result is not None
    effective_stop_atr_mult, _ = result
    assert effective_stop_atr_mult != frame_config.stop_atr_mult


# ---------------------------------------------------------------------------
# Source guards -- no second write path, structural imports wired correctly (DAG Invariant 3)
# ---------------------------------------------------------------------------


def test_structural_confluence_imported_not_duplicated():
    src = _read_source()
    assert "from src.intelligence.trading.structural_confluence import" in src
    assert "resolve_structural_zone" in src
    assert "set_config_service" in src


def test_no_second_write_path_only_existing_batch_flush():
    """DAG Invariant 3: geometry is computed in the existing write pass; the only persistence
    call remains the pre-existing per-chunk executemany flush (2 call sites: mid-loop
    chunk-size flush + end-of-partition final flush -- unchanged count from before this
    plan)."""
    src = _read_source()
    assert src.count("await wconn.executemany(self._INSERT_SQL, chunk)") == 2


def test_config_service_wired_once_at_writer_init_not_per_partition():
    src = _read_source()
    assert src.count("set_config_service(") == 1
    # Wired inside _execute_inner (once per run), not _process_partition (once per partition).
    execute_inner_idx = src.index("async def _execute_inner")
    process_partition_idx = src.index("async def _process_partition")
    set_config_call_idx = src.index("set_config_service(_build_structural_config_service")
    assert execute_inner_idx < set_config_call_idx < process_partition_idx
