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
_synthetic_inputs() below always builds X with the real _FEATURE_NAMES width, and
test_existing_keys_dedup_skips_cell() checks for the deduped key's absence from
the second call's rows rather than asserting the whole result list is empty
(with 155 real features, only the one deduped feature/lookahead key drops out --
the rest of the 154 features still produce rows normally). This is a test-fixture
correction only; the extracted function body itself is untouched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from services.ic_engine import (  # noqa: E402
    _FEATURE_NAMES,
    _POOLED_REGIME_SENTINEL,
    ICEngineConfig,
    _compute_one_regime_cell,
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
        lookahead_fast=1,
        lookahead_mid=5,
        lookahead_slow=20,
        lookahead_extended=60,
        equity_model_enabled=True,
        min_obs_daily=1000,
        hac_max_lag=3,
        cs_chunk_ts=5000,
        symbol_fetch_chunk_rows=5000,
        n_workers=1,
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
    rows, n_skipped = _compute_one_regime_cell(
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
        existing_keys=frozenset(),
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
    rows, _ = _compute_one_regime_cell(
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
        existing_keys=frozenset(),
        training_window_end=None,
        feature_status_map=None,
        run_ts=None,
    )
    assert len(rows) > 0
    assert all(r["regime_scope"] == "symbol_hmm" for r in rows)
    assert all(r["regime"] == "trending_up" for r in rows)
    assert all(r["is_pooled"] is False for r in rows)


def test_existing_keys_dedup_skips_cell():
    """A cell_key already in existing_keys must be skipped (n_skipped incremented),
    never re-appended to result rows -- this is the existing dedup behavior, must
    survive the extraction unchanged."""
    X, returns_mat, complete_mat = _synthetic_inputs()
    config = _make_config()
    mask = np.ones(len(X), dtype=bool)

    # First call to discover one (feature, lookahead) key this synthetic run
    # produces.
    rows, _ = _compute_one_regime_cell(
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
        existing_keys=frozenset(),
        training_window_end="2026-01-01",
        feature_status_map=None,
        run_ts=None,
    )
    assert len(rows) > 0
    feat_name = rows[0]["feature_name"]
    lookahead_bars = rows[0]["lookahead_bars"]
    dedup_key = (feat_name, "TLT", "5m", "trending_up", lookahead_bars, False)
    existing = frozenset({dedup_key})

    rows2, n_skipped2 = _compute_one_regime_cell(
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
        existing_keys=existing,
        training_window_end="2026-01-01",
        feature_status_map=None,
        run_ts=None,
    )
    kept_keys = {
        (r["feature_name"], r["symbol"], r["tf"], r["regime"], r["lookahead_bars"], r["is_pooled"])
        for r in rows2
    }
    assert dedup_key not in kept_keys
    assert n_skipped2 >= 1
