"""Unit test: ic_engine _compute_symbol_tf returns rows, not writes.

Verifies the compute/write split following regime_writer pattern:
- _compute_symbol_tf returns pooled_rows, regime_rows (no DB writes)
- Return contract is dict with keys: pooled_rows, regime_rows, all_results, n_skipped

This test validates the function signature and return structure without a live DB.
No actual compute is performed -- we're checking the contract only.

Related to Task 001: ic_engine compute/write split.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import _compute_cross_sectional_tf, _compute_symbol_tf


def test_compute_symbol_tf_return_keys():
    """_compute_symbol_tf must return dict with specific keys (compute/write split)."""
    # Check function signature
    sig = inspect.signature(_compute_symbol_tf)
    params = list(sig.parameters.keys())
    expected_params = [
        "dsn",
        "symbol",
        "tf",
        "training_window_end",
        "existing_keys",
        "config",
        "tracer",
        "run_ts",
        "rng",
        "feature_status_map",
        "mr_dict",
    ]
    assert params == expected_params, f"Expected params {expected_params}, got {params}"

    # Check docstring mentions no DB writes
    docstring = _compute_symbol_tf.__doc__
    assert docstring is not None, "_compute_symbol_tf must have docstring"
    assert (
        "No DB writes" in docstring or "pure compute" in docstring
    ), "Docstring must mention no DB writes / pure compute"
    assert "pooled_rows" in docstring, "Docstring must mention pooled_rows in return"
    assert "regime_rows" in docstring, "Docstring must mention regime_rows in return"


def test_compute_symbol_tf_has_no_db_write_code():
    """_compute_symbol_tf should not contain execute_batch calls.

    This is a simple grep check for the pattern. After the compute/write split,
    execute_batch should only be in _write_ic_results. A leading conn.commit()
    is permitted -- it clears a stale read-only transaction so a named
    (server-side) cursor can be declared (same precondition regime_writer.py's
    _compute_symbol_tf and ensemble_ic_engine.py's pooled fetch document at
    their own named-cursor call sites); that's a transaction-boundary reset,
    not a persistence operation, so it doesn't violate the invariant this test
    guards -- which is that no result rows get written from compute.
    """

    source = inspect.getsource(_compute_symbol_tf)

    # execute_batch should NOT be in _compute_symbol_tf
    assert "execute_batch" not in source, (
        "_compute_symbol_tf should not contain execute_batch "
        "(DB writes moved to _write_ic_results)"
    )


def test_write_ic_results_exists():
    """_write_ic_results function must exist for serial writes."""
    import services.ic_engine as ic_module

    assert hasattr(ic_module, "_write_ic_results"), (
        "_write_ic_results function must exist " "(serial write function for main process)"
    )

    # Check signature -- focused write helper: conn + split row lists only.
    sig = inspect.signature(ic_module._write_ic_results)
    params = list(sig.parameters.keys())
    expected_params = [
        "conn",
        "pooled_rows",
        "regime_rows",
    ]
    assert params == expected_params, f"Expected params {expected_params}, got {params}"

    # Check docstring mentions serial write
    docstring = ic_module._write_ic_results.__doc__
    assert docstring is not None, "_write_ic_results must have docstring"
    assert "serial" in docstring.lower(), "Docstring must mention serial write"
    assert "main process" in docstring.lower(), "Docstring must mention main process"


def test_write_ic_results_has_db_write_code():
    """_write_ic_results should contain execute_batch for DB writes."""
    import services.ic_engine as ic_module

    source = inspect.getsource(ic_module._write_ic_results)

    # execute_batch SHOULD be in _write_ic_results
    assert "execute_batch" in source, "_write_ic_results must contain execute_batch for DB writes"

    # commit() SHOULD be in _write_ic_results
    assert "conn.commit()" in source, "_write_ic_results must call conn.commit() for DB writes"


def test_compute_cross_sectional_tf_takes_dsn_not_live_connection():
    """_compute_cross_sectional_tf must take a dsn string, not a live connection
    held across its whole call (todo 125, 2026-07-17).

    Mirrors _compute_symbol_tf's todo-102 fix: the clustering + circular block
    bootstrap resampling phase runs for hours with zero DB traffic. A connection
    passed in and held open across that phase is architecturally the same defect
    todo 102 fixed for the per-symbol path -- just never generalized to this
    sibling function, which is why the 143.1-07 corpus re-run crashed twice at
    the identical transition point (first cell finishes compute, next cell's
    first query dies on the now-silently-dropped connection).
    """
    sig = inspect.signature(_compute_cross_sectional_tf)
    params = list(sig.parameters.keys())
    assert "dsn" in params, (
        "_compute_cross_sectional_tf must accept 'dsn' (connection string) -- "
        "not a live 'conn', which forces the caller to hold one connection open "
        "across the entire multi-hour compute-only phase"
    )
    assert "conn" not in params, (
        "_compute_cross_sectional_tf must not accept a live 'conn' parameter -- "
        "it should open its own short-lived connection internally (todo 102 pattern)"
    )


def test_compute_cross_sectional_tf_closes_connection_before_clustering():
    """The connection opened inside _compute_cross_sectional_tf must be closed
    before the CPU-only clustering/bootstrap phase begins -- not held open across
    it (todo 125, same pattern as _compute_symbol_tf's todo 102 fix).

    Structural regression guard: fails if a future edit re-introduces a
    long-held connection by moving the close() call after (or removing it
    before) the first CPU-only compute call, _cluster_features(.
    """
    source = inspect.getsource(_compute_cross_sectional_tf)

    assert "conn.close()" in source, (
        "_compute_cross_sectional_tf must close its own connection once the "
        "fetch phase is done, before the clustering/bootstrap compute begins"
    )

    close_idx = source.index("conn.close()")
    cluster_idx = source.index("_cluster_features(")
    assert close_idx < cluster_idx, (
        "conn.close() must appear before the first CPU-only compute call "
        "(_cluster_features) -- the connection must not be held open across "
        "the multi-hour clustering/bootstrap phase"
    )


def test_cross_sectional_rankdata_output_is_float32_not_float64():
    """rankdata()'s 2D per-scale output (ranks_X_scale) must be cast to float32
    immediately, matching X_raw's own float32 optimization one line above it in
    this same function (2026-07-19 OOM fix).

    scipy.stats.rankdata ALWAYS returns float64 regardless of input dtype (verified
    directly: rankdata(np.array(..., dtype=np.float32)).dtype == float64) -- so the
    file's existing float32 comment ("Halves the memory of X_raw, X_nd, and every
    per-scale subsample copy below") was never actually true for this specific
    array. For the largest cross-sectional cells (5m/low_bull, ~581K-599K
    timestamps), this 2D float64 array is the single largest live allocation in
    the per-scale loop, alongside X_raw/X_nd/X_sub/X_sub_nd (four more float32
    copies of comparable size all alive simultaneously at the least-subsampled
    "fast" scale) -- confirmed root cause of the 2026-07-18 OOM kill
    (anon-rss 20.5GB on a 29GB host, dmesg-confirmed). Casting to float32 does not
    change any statistical result: rank order is exact in float32 for any n well
    under 2**24 (~16.8M), and every downstream consumer (_vectorized_ic,
    _p_values_from_ic, _circular_block_bootstrap_ic) only ever uses rank ORDER,
    never rank magnitude precision.
    """
    source = inspect.getsource(_compute_cross_sectional_tf)

    rankdata_idx = source.index("ranks_X_scale = rankdata(X_sub_nd, axis=0)")
    line_end = source.index("\n", rankdata_idx)
    rankdata_line = source[rankdata_idx:line_end]

    assert "astype(np.float32)" in rankdata_line, (
        "ranks_X_scale = rankdata(X_sub_nd, axis=0)[valid_mask] must cast to "
        "float32 (e.g. .astype(np.float32) on the rankdata(...) call) -- "
        "rankdata() always returns float64 regardless of input dtype, so this "
        "array silently defeats X_raw's float32 memory optimization one line "
        "above and is the single largest live allocation for the biggest "
        "cross-sectional cells"
    )


def test_per_symbol_rankdata_output_is_float32_not_float64():
    """Same bug, same fix, sibling function: _compute_symbol_tf has the
    identical rankdata()-defeats-float32 pattern at its own per-scale ranking step
    (single-column and per-fold rankdata calls elsewhere in this function are small
    and don't need this -- only the full [n_valid, n_features] one does). Per-symbol
    cells are far smaller than pooled cross-sectional cells so this alone wasn't
    what caused the 2026-07-18 OOM, but this codebase has already fixed the same
    bug class in only one sibling before (todo 102's connection-lifecycle fix,
    not generalized to _compute_cross_sectional_tf until todo 125, three months
    later, after it caused two more crashes) -- fixing both together here instead
    of waiting for this one to bite too.
    """
    source = inspect.getsource(_compute_symbol_tf)

    rankdata_idx = source.index("ranks_X_scale = rankdata(X_sub_nd, axis=0)")
    line_end = source.index("\n", rankdata_idx)
    rankdata_line = source[rankdata_idx:line_end]

    assert "astype(np.float32)" in rankdata_line, (
        "_compute_symbol_tf's ranks_X_scale = rankdata(X_sub_nd, axis=0)[valid_mask] "
        "must cast to float32 too -- same defect, same fix as "
        "_compute_cross_sectional_tf's identical line"
    )


def test_cross_sectional_per_scale_subsample_uses_slice_not_fancy_index():
    """The per-scale subsample (X_sub, X_sub_nd, returns_sub, complete_sub) must
    use basic slicing, not `arr[np.arange(...)]` fancy indexing (2026-07-19 OOM
    fix). Regular-stride subsampling is exactly expressible as a slice
    (`arr[0:n:stride]`), which numpy returns as a VIEW sharing memory with the
    source array -- fancy indexing with an explicit index array always allocates
    a full copy, even when the selected elements are evenly strided. For the
    largest cross-sectional cells this was 2 extra full-cell-sized float32
    copies (X_sub, X_sub_nd) alive simultaneously alongside X_raw/X_nd at the
    least-subsampled ("fast") scale -- on top of the rankdata float64 promotion
    fixed separately, confirmed empirically to produce bit-identical downstream
    results (view vs copy: identical rankdata output, identical boolean-mask
    results, no aliasing risk since every later slice of the view still copies).
    """
    source = inspect.getsource(_compute_cross_sectional_tf)

    assert "sub_idx = np.arange(" not in source, (
        "_compute_cross_sectional_tf must not build an explicit sub_idx index "
        "array for regular-stride subsampling -- arr[np.arange(0, n, stride)] "
        "copies; arr[0:n:stride] is a view of the same elements"
    )
    assert "X_raw[sub_idx]" not in source and "X_nd[sub_idx]" not in source, (
        "_compute_cross_sectional_tf must not fancy-index X_raw/X_nd with an "
        "explicit index array -- use slice syntax (arr[0:n:stride]) so numpy "
        "returns a view instead of a copy"
    )


def test_per_symbol_per_scale_subsample_uses_slice_not_fancy_index():
    """Same fix, sibling function: _compute_symbol_tf's per-scale subsample
    (X_sub_scale, X_sub_nd, returns_sub, complete_sub) must use slicing too."""
    source = inspect.getsource(_compute_symbol_tf)

    assert "sub_idx = np.arange(0, n_regime_raw" not in source, (
        "_compute_symbol_tf must not build an explicit sub_idx index array for "
        "regular-stride subsampling -- same fix as _compute_cross_sectional_tf"
    )
    assert "X_regime[sub_idx]" not in source and "X_regime_nd[sub_idx]" not in source, (
        "_compute_symbol_tf must not fancy-index X_regime/X_regime_nd with an "
        "explicit index array -- use slice syntax so numpy returns a view "
        "instead of a copy"
    )


def test_run_ic_worker_return_keys():
    """_run_ic_worker must return rows for corpus-level BH-FDR and serial write."""
    import services.ic_engine as ic_module

    sig = inspect.signature(ic_module._run_ic_worker)
    # Worker accepts single args tuple
    params = list(sig.parameters.keys())
    assert params == ["args"], f"Expected single 'args' param, got {params}"

    # Check docstring mentions returning rows and corpus-level BH-FDR fields
    docstring = ic_module._run_ic_worker.__doc__
    assert docstring is not None, "_run_ic_worker must have docstring"
    assert "pooled_rows" in docstring, "Docstring must mention pooled_rows in return"
    assert "regime_rows" in docstring, "Docstring must mention regime_rows in return"
    assert "pvals_flat" in docstring, "Docstring must mention pvals_flat for corpus BH-FDR"
