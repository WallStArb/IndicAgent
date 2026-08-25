"""Unit tests for _compute_one_regime_cell (extracted per-regime-cell IC compute)
and the dual-write pass restructuring in _compute_symbol_tf.

No live DB -- these tests call the pure, module-level per-cell function directly
with tiny synthetic numpy arrays.

Deviation from the task-1-brief.md scaffolding (recorded here, not silently):
the brief's original _synthetic_inputs(n_features=...) let the caller choose an
arbitrary feature count. The real _compute_one_regime_cell derives n_features from
the module-level `len(_FEATURE_NAMES)` constant (the production FeatureVector
schema, 155 fields) -- NOT from X_aligned.shape[1] -- so a synthetic X with a
different column count crashes inside _expand() (mask/array length mismatch).
_synthetic_inputs() below always builds X with the real _FEATURE_NAMES width.

162-03 Task 3 update: _compute_one_regime_cell no longer accepts an existing_keys
parameter -- the whole-cell fingerprint gate in main() is now the SOLE skip
decision, applied BEFORE this function is ever called, so a dispatched cell
always recomputes every feature unconditionally. The former
test_existing_keys_dedup_skips_cell() (which proved the per-feature dedup
mechanism this function used to implement) is replaced below by
test_compute_one_regime_cell_always_recomputes_every_feature, which proves the
inverse: two consecutive calls with identical inputs both return the FULL row
set every time, with no signature or behavior for suppressing a subset. The
existing_keys-removal structural regression (no parameter, no source reference)
is covered separately by tests/unit/test_ic_engine_fingerprint.py.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import numpy as np
import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from services.ic_engine import (  # noqa: E402
    _FEATURE_NAMES,
    _POOLED_REGIME_SENTINEL,
    ICEngineConfig,
    _compute_one_regime_cell,
    _group_cells_for_metrics,
    _merge_skip_reasons,
)


def _make_config() -> ICEngineConfig:
    """Minimal-but-complete ICEngineConfig for a tiny synthetic run.

    ICEngineConfig has grown many required fields since todo/plan authorship
    (Phase 143+ fields with no defaults) -- constructed here using the same
    full-field pattern as tests/unit/test_hac_ic_sharpe.py, with a handful of
    values overridden to keep the synthetic run's stride/reliability gates
    small enough for n_rows=40.
    """
    return ICEngineConfig(
        min_observations=500,
        fdr_alpha=0.05,
        walk_forward_folds=1,
        sharpe_window_size=50,
        sharpe_window_size_subsampled=50,
        sharpe_min_windows=3,
        subsample_min_stride=1,
        min_reliable_n=4,
        cluster_max_corr=0.8,
        lookahead_fast={"5m": 1, "15m": 1, "1h": 1, "1d": 1},
        lookahead_mid={"5m": 6, "15m": 2, "1h": 2, "1d": 2},
        lookahead_slow={"5m": 12, "15m": 5, "1h": 20, "1d": 5},
        lookahead_extended={"5m": 39, "15m": 10, "1h": 60, "1d": 10},
        active_scales={
            "5m": ("fast", "mid", "slow", "extended"),
            "15m": ("fast", "mid", "slow", "extended"),
            "1h": ("fast", "mid"),
            "1d": ("fast", "mid", "slow", "extended"),
        },
        equity_model_enabled=True,
        hac_max_lag=3,
        cs_chunk_ts=5000,
        symbol_fetch_chunk_rows=5000,
        n_workers=1,
        blas_threads_per_worker=1,
        bootstrap_resamples=50,
        bootstrap_block_size={"5m": 2},
    )


def _synthetic_inputs(n_rows: int = 40):
    """Build synthetic (X, returns_mat, complete_mat) with the REAL feature
    width (len(_FEATURE_NAMES)) -- see module docstring for why this can't be
    an arbitrary small number."""
    rng = np.random.default_rng(42)
    n_features = len(_FEATURE_NAMES)
    X = rng.standard_normal((n_rows, n_features)).astype(np.float32)
    returns_mat = rng.standard_normal((n_rows, 4)).astype(np.float64)  # 4 = len(_SCALES)
    complete_mat = np.ones((n_rows, 4), dtype=bool)
    return X, returns_mat, complete_mat


def test_pooled_cell_produces_is_pooled_true_rows():
    X, returns_mat, complete_mat = _synthetic_inputs()
    config = _make_config()
    rng = np.random.default_rng(1)
    rows, n_skipped, _skip_reasons = _compute_one_regime_cell(
        _POOLED_REGIME_SENTINEL,
        True,
        np.ones(len(X), dtype=bool),
        "pooled",
        X_aligned=X,
        returns_mat=returns_mat,
        complete_mat=complete_mat,
        config=config,
        symbol="TEST",
        tf="5m",
        rng=rng,
        training_window_end=None,
        feature_status_map=None,
        run_ts=None,
    )
    assert len(rows) > 0
    assert all(r["is_pooled"] is True for r in rows)
    assert all(r["regime_scope"] == "pooled" for r in rows)


def test_regime_cell_uses_resolved_regime_scope_param():
    """The resolved_regime_scope argument controls the written regime_scope --
    not a recomputed is_pooled/cross_sectional flag inside the function."""
    X, returns_mat, complete_mat = _synthetic_inputs()
    config = _make_config()
    rng = np.random.default_rng(1)
    mask = np.ones(len(X), dtype=bool)
    rows, _, _skip_reasons = _compute_one_regime_cell(
        "trending_up",
        False,
        mask,
        "symbol_hmm",
        X_aligned=X,
        returns_mat=returns_mat,
        complete_mat=complete_mat,
        config=config,
        symbol="TLT",
        tf="5m",
        rng=rng,
        training_window_end=None,
        feature_status_map=None,
        run_ts=None,
    )
    assert len(rows) > 0
    assert all(r["regime_scope"] == "symbol_hmm" for r in rows)
    assert all(r["regime"] == "trending_up" for r in rows)
    assert all(r["is_pooled"] is False for r in rows)


def test_compute_one_regime_cell_always_recomputes_every_feature():
    """162-03: _compute_one_regime_cell has no per-feature skip mechanism of its
    own -- the whole-cell fingerprint gate in main() is the SOLE skip decision,
    applied BEFORE this function is ever called. Two consecutive calls with
    identical inputs must both return the full row set every time (same feature/
    lookahead keys present both times), proving no dedup/suppression happens
    inside this function anymore.
    """
    X, returns_mat, complete_mat = _synthetic_inputs()
    config = _make_config()
    mask = np.ones(len(X), dtype=bool)

    rows, n_skipped, skip_reasons = _compute_one_regime_cell(
        "trending_up",
        False,
        mask,
        "symbol_hmm",
        X_aligned=X,
        returns_mat=returns_mat,
        complete_mat=complete_mat,
        config=config,
        symbol="TLT",
        tf="5m",
        rng=np.random.default_rng(1),
        training_window_end="2026-01-01",
        feature_status_map=None,
        run_ts=None,
    )
    assert len(rows) > 0

    rows2, n_skipped2, skip_reasons2 = _compute_one_regime_cell(
        "trending_up",
        False,
        mask,
        "symbol_hmm",
        X_aligned=X,
        returns_mat=returns_mat,
        complete_mat=complete_mat,
        config=config,
        symbol="TLT",
        tf="5m",
        rng=np.random.default_rng(2),
        training_window_end="2026-01-01",
        feature_status_map=None,
        run_ts=None,
    )
    keys1 = {
        (r["feature_name"], r["symbol"], r["tf"], r["regime"], r["lookahead_bars"], r["is_pooled"])
        for r in rows
    }
    keys2 = {
        (r["feature_name"], r["symbol"], r["tf"], r["regime"], r["lookahead_bars"], r["is_pooled"])
        for r in rows2
    }
    assert keys1 == keys2, "identical inputs must produce the identical full key set both times"
    assert len(rows) == len(rows2)
    # n_skipped only ever reflects degenerate-feature/insufficient-n skips now,
    # never an "already_present" dedup skip -- both calls have identical inputs,
    # so their skip counts must match exactly.
    assert n_skipped == n_skipped2
    assert skip_reasons == skip_reasons2


def test_degenerate_feature_populates_skip_reasons() -> None:
    """todo 009/2026-07-31 fix: skip_reasons must attribute a degenerate (constant)
    column to 'degenerate_feature' with the correct count -- this breakdown is what
    the caller (main process) now uses to emit IC_ENGINE_CELLS_SKIPPED_TOTAL, since
    this function itself never touches OTel (runs inside a ProcessPoolExecutor
    worker with no metrics exporter initialized)."""
    X, returns_mat, complete_mat = _synthetic_inputs()
    X[:, 0] = 5.0  # feature 0 constant -> std == 0 -> degenerate
    config = _make_config()
    mask = np.ones(len(X), dtype=bool)

    rows, n_skipped, skip_reasons = _compute_one_regime_cell(
        _POOLED_REGIME_SENTINEL,
        True,
        mask,
        "pooled",
        X_aligned=X,
        returns_mat=returns_mat,
        complete_mat=complete_mat,
        config=config,
        symbol="TEST",
        tf="5m",
        rng=np.random.default_rng(1),
        training_window_end=None,
        feature_status_map=None,
        run_ts=None,
    )

    # n_rows=40 also makes the extended scale's stride-39 subsample (n_independent=2)
    # fall below min_reliable_n=4, so insufficient_n fires too -- assert the
    # decomposition sums correctly rather than a brittle single-reason count.
    assert skip_reasons.get("degenerate_feature") == 1
    assert n_skipped == sum(skip_reasons.values())
    # Degenerate features still get a row per surviving scale (ic_value=None), same
    # as before this fix -- skip_reasons is bookkeeping for the metric, not a filter
    # on result_rows.
    degenerate_rows = [r for r in rows if r["feature_name"] == _FEATURE_NAMES[0]]
    assert degenerate_rows
    assert all(r["ic_value"] is None for r in degenerate_rows)


def test_insufficient_n_populates_skip_reasons() -> None:
    """A cell too small to clear min_reliable_n must attribute every feature's skip
    to 'insufficient_n' -- both the pre-subsample size check and the post-valid-mask
    check share this same reason string (see _compute_one_regime_cell's two
    insufficient_n sites)."""
    X, returns_mat, complete_mat = _synthetic_inputs(n_rows=40)
    config = dataclasses.replace(_make_config(), min_reliable_n=1000)  # unreachable
    mask = np.ones(len(X), dtype=bool)

    rows, n_skipped, skip_reasons = _compute_one_regime_cell(
        _POOLED_REGIME_SENTINEL,
        True,
        mask,
        "pooled",
        X_aligned=X,
        returns_mat=returns_mat,
        complete_mat=complete_mat,
        config=config,
        symbol="TEST",
        tf="5m",
        rng=np.random.default_rng(1),
        training_window_end=None,
        feature_status_map=None,
        run_ts=None,
    )

    assert rows == []
    n_scales = len(config.active_scales_for("5m"))
    assert skip_reasons.get("insufficient_n") == n_scales * len(_FEATURE_NAMES)
    assert n_skipped == n_scales * len(_FEATURE_NAMES)


class TestMergeSkipReasons:
    """_merge_skip_reasons accumulates per-cell skip_reasons dicts into a running
    total, in place -- the pure (OTel-free) mechanism _compute_symbol_tf uses to
    combine skip breakdowns across its pooled call + regime_passes loop before
    returning them to the caller for eventual emission."""

    def test_merges_disjoint_reasons(self) -> None:
        total: dict[str, int] = {"degenerate_feature": 2}
        _merge_skip_reasons(total, {"insufficient_n": 3})
        assert total == {"degenerate_feature": 2, "insufficient_n": 3}

    def test_accumulates_shared_reason(self) -> None:
        total: dict[str, int] = {"insufficient_n": 3}
        _merge_skip_reasons(total, {"insufficient_n": 4})
        assert total == {"insufficient_n": 7}

    def test_empty_addition_is_a_no_op(self) -> None:
        total: dict[str, int] = {"degenerate_feature": 1}
        _merge_skip_reasons(total, {})
        assert total == {"degenerate_feature": 1}

    def test_empty_total_absorbs_addition(self) -> None:
        total: dict[str, int] = {}
        _merge_skip_reasons(total, {"degenerate_feature": 1, "insufficient_n": 2})
        assert total == {"degenerate_feature": 1, "insufficient_n": 2}


def test_group_cells_for_metrics_treats_regime_scope_as_part_of_grouping_key():
    """Two rows sharing the same regime label and is_pooled=False but differing
    only in regime_scope (one 'cross_sectional', one 'symbol_hmm' from a
    dual-write pass) must be treated as two distinct metric emissions, not
    merged into one -- otherwise a dual-write cell silently conflates its
    count with the primary cross-sectional cell that happens to share the
    same HMM regime label string."""
    all_results = [
        {"regime": "trending_up", "is_pooled": False, "regime_scope": "cross_sectional"},
        {"regime": "trending_up", "is_pooled": False, "regime_scope": "cross_sectional"},
        {"regime": "trending_up", "is_pooled": False, "regime_scope": "symbol_hmm"},
    ]

    emissions = _group_cells_for_metrics(all_results, symbol="TLT", tf="5m")

    assert len(emissions) == 2

    counts_by_scope = {attrs["regime_scope"]: count for attrs, count in emissions}
    assert counts_by_scope == {"cross_sectional": 2, "symbol_hmm": 1}

    for attrs, _ in emissions:
        assert attrs["symbol"] == "TLT"
        assert attrs["tf"] == "5m"
        assert attrs["regime"] == "trending_up"


def test_group_cells_for_metrics_pooled_rows_grouped_separately():
    """Pooled rows (is_pooled=True, regime=_POOLED_REGIME_SENTINEL) must form
    their own emission, distinct from any regime-stratified rows even if a
    (mis-constructed) row shared a regime label -- is_pooled is still part of
    the grouping key alongside regime_scope."""
    all_results = [
        {"regime": _POOLED_REGIME_SENTINEL, "is_pooled": True, "regime_scope": "pooled"},
        {"regime": _POOLED_REGIME_SENTINEL, "is_pooled": True, "regime_scope": "pooled"},
        {"regime": "trending_up", "is_pooled": False, "regime_scope": "cross_sectional"},
    ]

    emissions = _group_cells_for_metrics(all_results, symbol="TLT", tf="5m")

    assert len(emissions) == 2
    counts = sorted(count for _, count in emissions)
    assert counts == [1, 2]


def test_compute_one_regime_cell_attributes_scales_correctly_for_reduced_tf():
    """Behavioral regression guard for the per-tf active-scale-set correctness
    invariant (2026-07-30 design; Task 3 code review Finding 2).

    test_ic_engine_active_scales_boundary.py only proves no bare `_SCALES`
    module-constant token remains in ic_engine.py -- it is a static grep and
    cannot catch a column-misalignment bug where returns_mat/complete_mat are
    built against one scale ordering but read back against a different one.
    That is exactly the silent-wrong-answer failure mode this design exists to
    prevent: `_compute_one_regime_cell` indexes `returns_mat[:, scale_idx]` /
    `complete_mat[:, scale_idx]` purely by position, with no name check, so a
    caller that disagreed with this function about scale order would silently
    mislabel one scale's IC as another's.

    Exercises tf="1h" -- the live default with only 2 active scales (fast,
    mid; slow/extended dropped, per ACTIVE_SCALES_FALLBACKS_BY_TF), NOT the
    historical 4-scale case every other test in this file uses. Builds a
    returns_mat sized [n_rows, 2] (matching what _compute_symbol_tf now
    actually constructs for this tf -- n_scales = len(active_scales_for(tf)),
    not a fixed 4) where column 0 (fast) is feature 0's raw values (perfect
    rank correlation, IC=+1.0 exactly, no ties) and column 1 (mid) is feature
    0's negation (perfect anti-correlation, IC=-1.0 exactly). A column-swap
    bug -- e.g. 'mid' silently reading fast's column, or the matrix being
    built in a different scale order than it's read back in -- would flip
    these signs. The row keyed by lookahead_bars=1 (fast, per
    _make_config's lookahead_fast["1h"]) must show ic_value +1.0 and the row
    keyed by lookahead_bars=2 (mid) must show -1.0: proof of correct
    attribution end-to-end through the real function, not just via grep.
    """
    rng = np.random.default_rng(7)
    n_rows = 40
    n_features = len(_FEATURE_NAMES)
    X = rng.standard_normal((n_rows, n_features)).astype(np.float32)

    # tf="1h" -> exactly 2 active scales (fast, mid) in the live default, so
    # returns_mat/complete_mat are shaped [n_rows, 2] -- NOT [n_rows, 4] like
    # every other synthetic input in this file (those use tf="5m", which still
    # has all 4 scales active). Getting this width wrong is itself part of
    # what the correctness invariant guards against.
    returns_mat = np.zeros((n_rows, 2), dtype=np.float64)
    returns_mat[:, 0] = X[:, 0].astype(np.float64)  # fast: identical to feature 0 -> IC = +1.0
    returns_mat[:, 1] = -X[:, 0].astype(np.float64)  # mid: negated feature 0 -> IC = -1.0
    complete_mat = np.ones((n_rows, 2), dtype=bool)

    # _make_config()'s bootstrap_block_size only has a "5m" key -- add "1h" so
    # config.bootstrap_block_size[tf] doesn't KeyError for this tf.
    config = dataclasses.replace(_make_config(), bootstrap_block_size={"5m": 2, "1h": 2})
    mask = np.ones(n_rows, dtype=bool)

    rows, _, _skip_reasons = _compute_one_regime_cell(
        _POOLED_REGIME_SENTINEL,
        True,
        mask,
        "pooled",
        X_aligned=X,
        returns_mat=returns_mat,
        complete_mat=complete_mat,
        config=config,
        symbol="TEST",
        tf="1h",
        rng=np.random.default_rng(1),
        training_window_end=None,
        feature_status_map=None,
        run_ts=None,
    )

    feature0_name = _FEATURE_NAMES[0]
    feature0_rows = {r["lookahead_bars"]: r for r in rows if r["feature_name"] == feature0_name}

    # config.lookahead_fast["1h"] = 1, config.lookahead_mid["1h"] = 2 (_make_config).
    # Exactly these two lookahead_bars values should be present -- proof that only
    # the 2 active scales were attempted (slow=20/extended=60 for 1h were NOT),
    # matching the measured-completeness fix this whole design exists to land.
    assert set(feature0_rows.keys()) == {1, 2}, (
        "expected exactly 2 active scales' worth of rows for tf=1h "
        f"(fast->lookahead_bars=1, mid->lookahead_bars=2), got lookahead_bars="
        f"{sorted(feature0_rows.keys())}"
    )
    assert feature0_rows[1]["ic_value"] == pytest.approx(1.0), (
        "fast scale (lookahead_bars=1) must read returns_mat column 0 -- got "
        f"ic_value={feature0_rows[1]['ic_value']!r}, expected +1.0 (column-misalignment "
        "regression: fast is reading a different column than it was built with)"
    )
    assert feature0_rows[2]["ic_value"] == pytest.approx(-1.0), (
        "mid scale (lookahead_bars=2) must read returns_mat column 1 -- got "
        f"ic_value={feature0_rows[2]['ic_value']!r}, expected -1.0 (column-misalignment "
        "regression: mid is reading a different column than it was built with)"
    )
