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

import numpy as np
import pytest

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import (
    CellTooLargeError,
    _blocked_bootstrap_ci,
    _compute_cross_sectional_tf,
    _compute_one_cross_sectional_cell,
    _compute_one_regime_cell,
    _compute_symbol_tf,
    _subsample_and_rank,
)


def test_compute_symbol_tf_return_keys():
    """_compute_symbol_tf must return dict with specific keys (compute/write split)."""
    # Check function signature
    sig = inspect.signature(_compute_symbol_tf)
    params = list(sig.parameters.keys())
    # 162-03: existing_keys removed -- the whole-cell fingerprint gate in main()
    # is the sole skip decision now, replacing the per-feature existing_keys
    # snapshot this function used to receive.
    # Phase 151 Plan 02: cluster_regime_conditioned added, threaded through the
    # identical path dual_write_symbol_hmm already takes (migration 286).
    expected_params = [
        "dsn",
        "symbol",
        "tf",
        "training_window_end",
        "config",
        "tracer",
        "run_ts",
        "rng",
        "feature_status_map",
        "mr_dict",
        "dual_write_symbol_hmm",
        "cluster_regime_conditioned",
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
    """_compute_symbol_tf should not contain executemany calls.

    This is a simple grep check for the pattern. After the compute/write split,
    executemany (psycopg2.extras.execute_batch's replacement post-psycopg3
    migration, 2026-08-03) should only be in _write_ic_results. A leading
    conn.commit() is permitted -- it clears a stale read-only transaction so a
    named (server-side) cursor can be declared (same precondition
    regime_writer.py's _compute_symbol_tf and ensemble_ic_engine.py's pooled
    fetch document at their own named-cursor call sites); that's a
    transaction-boundary reset, not a persistence operation, so it doesn't
    violate the invariant this test guards -- which is that no result rows get
    written from compute.
    """

    source = inspect.getsource(_compute_symbol_tf)

    # executemany should NOT be in _compute_symbol_tf
    assert (
        "executemany" not in source
    ), "_compute_symbol_tf should not contain executemany (DB writes moved to _write_ic_results)"


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
    """_write_ic_results should contain executemany for DB writes."""
    import services.ic_engine as ic_module

    source = inspect.getsource(ic_module._write_ic_results)

    # executemany SHOULD be in _write_ic_results (psycopg2.extras.execute_batch's
    # replacement post-psycopg3 migration, 2026-08-03)
    assert "executemany" in source, "_write_ic_results must contain executemany for DB writes"

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
    """The connection opened inside _compute_cross_sectional_tf must be scoped to
    (and closed before) the CPU-only clustering/bootstrap phase begins -- not held
    open across it (todo 125, same pattern as _compute_symbol_tf's todo 102 fix).

    Post-todo-129 (162-01 Task 1): the explicit conn.close() call was replaced by
    scoping the fetch phase inside a `with short_lived_conn(dsn) as conn:` block --
    short_lived_conn guarantees close() in a finally, including on exception
    mid-fetch, which the old hand-rolled conn.close() call did not.

    Post-162-01 Task 3: the clustering + per-scale compute phase itself moved into
    _compute_one_cross_sectional_cell (a separate function, called after the fetch
    phase's `with` block exits) -- so the connection is now structurally impossible
    to hold open across the compute-only phase, not just conventionally closed
    early. Structural regression guard: fails if a future edit calls
    _compute_one_cross_sectional_cell( from inside the with block (or removes the
    with block entirely).
    """
    source = inspect.getsource(_compute_cross_sectional_tf)

    assert "with short_lived_conn(dsn) as conn:" in source, (
        "_compute_cross_sectional_tf must scope its own connection to the fetch "
        "phase via short_lived_conn(dsn) (todo 129), not hold it open across the "
        "clustering/bootstrap compute begins"
    )
    assert "_compute_one_cross_sectional_cell(" in source, (
        "_compute_cross_sectional_tf must delegate its per-scale compute to "
        "_compute_one_cross_sectional_cell (162-01 Task 3)"
    )

    with_idx = source.index("with short_lived_conn(dsn) as conn:")
    call_idx = source.index("_compute_one_cross_sectional_cell(")
    assert with_idx < call_idx, (
        "_compute_one_cross_sectional_cell( must appear after the "
        "short_lived_conn(dsn) with-block has closed -- the connection must not "
        "be held open across the multi-hour clustering/bootstrap phase"
    )
    # _compute_one_cross_sectional_cell( must be OUTSIDE the with block (dedented
    # back to the function's own indentation), not merely textually after the
    # `with` line -- find the with-block's body indentation and confirm the call
    # sits at a shallower indentation than that.
    with_line = source[: source.index("\n", with_idx)].splitlines()[-1]
    with_indent = len(with_line) - len(with_line.lstrip())
    call_line_start = source.rindex("\n", 0, call_idx) + 1
    call_line_end = source.index("\n", call_idx)
    call_line = source[call_line_start:call_line_end]
    call_indent = len(call_line) - len(call_line.lstrip())
    assert call_indent <= with_indent, (
        "_compute_one_cross_sectional_cell( must be dedented outside the "
        "short_lived_conn(dsn) with-block, not nested inside it"
    )


def test_subsample_and_rank_rankdata_output_is_float32_not_float64():
    """ranks_X_scale (the block-ranked feature matrix) must cast rankdata()'s
    output to float32 (2026-07-19 OOM fix -- rankdata() always returns float64
    regardless of input dtype).

    This is now shared, feature-blocked logic in _subsample_and_rank (162-01
    Task 3, todos 139/140) -- both _compute_one_regime_cell and
    _compute_one_cross_sectional_cell delegate to it, so the guard lives here
    once instead of duplicated per caller.
    """
    source = inspect.getsource(_subsample_and_rank)

    rankdata_idx = source.index(
        "ranks_block = rankdata(X_sub_nd[:, block_start:block_end], axis=0)"
    )
    line_end = source.index("\n", rankdata_idx)
    assert "astype(np.float32)" in source[rankdata_idx:line_end]


def test_subsample_and_rank_fold_rankdata_output_is_float32_not_float64():
    """The walk-forward fold loop's own rankdata() calls (rX_test/rY_test) need
    the same float32 cast as ranks_block/ranks_Y above them -- missed in the
    initial 2026-07-19 OOM fix, then fixed here. Shared, feature-blocked logic
    in _subsample_and_rank (162-01 Task 3)."""
    source = inspect.getsource(_subsample_and_rank)

    rx_idx = source.index("rX_test = rankdata(X_test, axis=0)")
    line_end = source.index("\n", rx_idx)
    assert "astype(np.float32)" in source[rx_idx:line_end]

    ry_idx = source.index("rY_test = rankdata(Y_test)")
    line_end = source.index("\n", ry_idx)
    assert "astype(np.float32)" in source[ry_idx:line_end]


def test_both_cell_functions_call_subsample_and_rank():
    """Both _compute_one_regime_cell (per-symbol) and
    _compute_one_cross_sectional_cell (cross-sectional) must delegate their
    rank/IC/CI/fold compute to the shared, feature-blocked _subsample_and_rank
    helper (162-01 Task 3, todos 139/140) -- a hand-pasted rank fix in one
    sibling can no longer diverge from the other."""
    regime_source = inspect.getsource(_compute_one_regime_cell)
    cross_sectional_source = inspect.getsource(_compute_one_cross_sectional_cell)

    assert (
        "_subsample_and_rank(" in regime_source
    ), "_compute_one_regime_cell must call _subsample_and_rank"
    assert (
        "_subsample_and_rank(" in cross_sectional_source
    ), "_compute_one_cross_sectional_cell must call _subsample_and_rank"


def test_cross_sectional_per_scale_subsample_uses_slice_not_fancy_index():
    """The per-scale subsample (X_sub, X_sub_nd, returns_sub, complete_sub) must
    use basic slicing (a numpy VIEW), not `arr[np.arange(...)]` fancy indexing
    (always a full copy) -- 2026-07-19 OOM fix. See the source comment above
    this block for the full incident rationale.

    This per-cell logic now lives in _compute_one_cross_sectional_cell
    (extracted from _compute_cross_sectional_tf, 162-01 Task 3) -- the guard
    moved with it, unchanged.
    """
    source = inspect.getsource(_compute_one_cross_sectional_cell)

    assert "sub_idx = np.arange(" not in source
    assert "X_raw[sub_idx]" not in source and "X_nd[sub_idx]" not in source
    assert "X_sub = X_raw[0:n_raw:scale_stride]" in source
    assert "X_sub_nd = X_nd[0:n_raw:scale_stride]" in source


def test_per_symbol_per_scale_subsample_uses_slice_not_fancy_index():
    """Same fix, sibling function: _compute_symbol_tf's per-scale subsample
    (X_sub_scale, X_sub_nd, returns_sub, complete_sub) must use slicing too.

    This per-cell logic now lives in _compute_one_regime_cell (extracted from
    _compute_symbol_tf, restore-symbol-hmm-ic-measurement Task 1) -- the guard
    moved with it, unchanged.
    """
    source = inspect.getsource(_compute_one_regime_cell)

    assert "sub_idx = np.arange(0, n_regime_raw" not in source
    assert "X_regime[sub_idx]" not in source and "X_regime_nd[sub_idx]" not in source
    assert "stride = slice(0, n_regime_raw, scale_stride)" in source
    assert "X_regime[stride]" in source and "X_regime_nd[stride]" in source


def _assert_subsample_and_rank_outputs_equal(a: tuple, b: tuple) -> None:
    """Shared assertion for _subsample_and_rank's 8-tuple output: every array must
    match exactly between two calls that are expected to be output-equivalent
    (varying only a wall-time-only parameter like feature_block_columns or
    max_workers). Used by both the feature-blocking and threading equivalence
    tests below."""
    a_X_raw, a_ranks_X, a_ranks_Y, a_ic, a_p, a_ci_lower, a_ci_upper, a_folds = a
    b_X_raw, b_ranks_X, b_ranks_Y, b_ic, b_p, b_ci_lower, b_ci_upper, b_folds = b

    np.testing.assert_array_equal(a_X_raw, b_X_raw)
    np.testing.assert_array_equal(a_ranks_X, b_ranks_X)
    np.testing.assert_array_equal(a_ranks_Y, b_ranks_Y)
    np.testing.assert_array_equal(a_ic, b_ic)
    np.testing.assert_array_equal(a_p, b_p)
    np.testing.assert_array_equal(a_ci_lower, b_ci_lower)
    np.testing.assert_array_equal(a_ci_upper, b_ci_upper)
    assert len(a_folds) == len(b_folds)
    for a_fold, b_fold in zip(a_folds, b_folds):
        np.testing.assert_array_equal(a_fold, b_fold)


def test_subsample_and_rank_feature_blocked_matches_unblocked():
    """Synthetic, DB-free equivalence check (162-01 Task 3): feature-blocked
    output must equal unblocked output on a small in-memory array.

    Calls _subsample_and_rank twice on identical synthetic data with the same
    rng seed -- once with feature_block_columns >= n_features (effectively one
    giant "unblocked" block) and once with a small block size (2 columns per
    block, forcing 5 blocks over 10 features). Every returned array must match
    exactly: rankdata(X, axis=0) ranks each feature column independently of
    its neighbors (Pattern verified live, 2026-07-22 -- a single batched
    rng.integers(size=(B, K)) call consumes the RNG stream identically to B
    sequential rng.integers(size=K) calls), so splitting the feature axis into
    blocks changes neither the per-column rank values nor the bootstrap CI's
    resample indices (the CRITICAL RNG invariant _subsample_and_rank's
    docstring describes).
    """
    from services.ic_engine import _subsample_and_rank

    rng_data = np.random.default_rng(7)
    n_sub = 300
    n_features = 10
    X_sub_nd = rng_data.normal(size=(n_sub, n_features)).astype(np.float32)
    returns_scale = rng_data.normal(size=n_sub)
    valid_mask = np.ones(n_sub, dtype=bool)
    valid_mask[:20] = False  # exercise the mask, not just an all-true trivial case

    common_kwargs = dict(
        walk_forward_folds=3,
        embargo_bars=1,
        min_reliable_n=2,
        bootstrap_block_size=10,
        bootstrap_resamples=50,
        max_workers=1,
    )

    unblocked = _subsample_and_rank(
        X_sub_nd,
        valid_mask,
        returns_scale,
        rng=np.random.default_rng(42),
        feature_block_columns=n_features,  # one giant block == unblocked
        **common_kwargs,
    )
    blocked = _subsample_and_rank(
        X_sub_nd,
        valid_mask,
        returns_scale,
        rng=np.random.default_rng(42),
        feature_block_columns=2,  # 5 blocks over 10 features
        **common_kwargs,
    )

    _assert_subsample_and_rank_outputs_equal(unblocked, blocked)


def test_subsample_and_rank_threaded_matches_serial():
    """Todo 215: config.per_symbol_bootstrap_threads makes the per-symbol path's
    previously-hardcoded max_workers=1 configurable. Threading must change wall
    time only, never output -- same invariant test_subsample_and_rank_feature_
    blocked_matches_unblocked verifies for feature-blocking, applied here to
    thread count: _blocked_bootstrap_ci's resample indices are fully determined
    by starts_matrix before any resampling begins (drawn once, serially, before
    the feature-block loop), and np.percentile(boot_ics, ..., axis=0) is
    invariant to the order results land in along that axis -- so dispatching the
    same n_boot resamples across threads instead of one at a time must not
    change ci_lower/ci_upper (or anything else _subsample_and_rank returns).
    """
    from services.ic_engine import _subsample_and_rank

    rng_data = np.random.default_rng(19)
    n_sub = 400
    n_features = 8
    X_sub_nd = rng_data.normal(size=(n_sub, n_features)).astype(np.float32)
    returns_scale = rng_data.normal(size=n_sub)
    valid_mask = np.ones(n_sub, dtype=bool)
    valid_mask[:30] = False

    common_kwargs = dict(
        walk_forward_folds=3,
        embargo_bars=1,
        min_reliable_n=2,
        bootstrap_block_size=10,
        bootstrap_resamples=80,
        feature_block_columns=3,  # exercise multiple feature blocks too
    )

    serial = _subsample_and_rank(
        X_sub_nd,
        valid_mask,
        returns_scale,
        rng=np.random.default_rng(42),
        max_workers=1,
        **common_kwargs,
    )
    threaded = _subsample_and_rank(
        X_sub_nd,
        valid_mask,
        returns_scale,
        rng=np.random.default_rng(42),
        max_workers=4,
        **common_kwargs,
    )

    _assert_subsample_and_rank_outputs_equal(serial, threaded)


def test_blocked_bootstrap_ci_early_stop_disabled_is_byte_identical_to_pre_todo227():
    """Todo 227: early_stop_enabled=False (the default) must reproduce the exact
    pre-todo-227 behavior -- always spend all starts_matrix.shape[0] resamples,
    regardless of the new (unused, when disabled) early-stop kwargs' values.
    """
    rng = np.random.default_rng(7)
    n_valid = 300
    block_p = 5
    n_boot = 400
    block_size = 12

    X_raw_block = rng.normal(size=(n_valid, block_p))
    Y_scale = rng.normal(size=n_valid)
    n_time_blocks = -(-n_valid // block_size)
    starts_matrix = rng.integers(0, n_valid, size=(n_boot, n_time_blocks))
    offsets = np.arange(block_size)

    baseline = _blocked_bootstrap_ci(X_raw_block, Y_scale, starts_matrix, offsets, n_valid, None)
    # Deliberately absurd early-stop kwargs (would stop almost immediately if
    # early_stop_enabled were True) -- must have zero effect while disabled.
    disabled = _blocked_bootstrap_ci(
        X_raw_block,
        Y_scale,
        starts_matrix,
        offsets,
        n_valid,
        None,
        early_stop_enabled=False,
        early_stop_check_interval=1,
        early_stop_tol=1e9,
        early_stop_min_resamples=1,
        early_stop_stable_checks=1,
    )

    np.testing.assert_array_equal(baseline[0], disabled[0])
    np.testing.assert_array_equal(baseline[1], disabled[1])


def test_blocked_bootstrap_ci_early_stop_matches_truncated_full_computation():
    """Todo 227: "stable" is inherently a two-checkpoint comparison -- the first
    checkpoint that clears early_stop_min_resamples has no prior checkpoint to
    compare against, so it only seeds `prev` and cannot itself trigger a stop.
    With a huge tolerance (guaranteed "stable" on the first real comparison) and
    early_stop_stable_checks=1, the earliest possible stop is therefore the
    SECOND checkpoint to clear the floor -- here, check_interval == min_resamples,
    so that's n_computed == 2 * check_interval. Verifies the early-stopped result
    exactly matches computing the CI from only that many rows of starts_matrix
    the ordinary (disabled) way -- proving early-stop doesn't silently compute a
    different statistic, just fewer resamples of the same one.
    """
    rng = np.random.default_rng(11)
    n_valid = 250
    block_p = 4
    n_boot = 1000
    block_size = 10
    min_resamples = 200
    expected_stop_at = 2 * min_resamples  # see docstring

    X_raw_block = rng.normal(size=(n_valid, block_p))
    Y_scale = rng.normal(size=n_valid)
    n_time_blocks = -(-n_valid // block_size)
    starts_matrix = rng.integers(0, n_valid, size=(n_boot, n_time_blocks))
    offsets = np.arange(block_size)

    early_stopped = _blocked_bootstrap_ci(
        X_raw_block,
        Y_scale,
        starts_matrix,
        offsets,
        n_valid,
        None,
        early_stop_enabled=True,
        early_stop_check_interval=min_resamples,
        early_stop_tol=1e9,  # guaranteed "stable" on the first real comparison
        early_stop_min_resamples=min_resamples,
        early_stop_stable_checks=1,
    )
    truncated_full = _blocked_bootstrap_ci(
        X_raw_block,
        Y_scale,
        starts_matrix[:expected_stop_at],
        offsets,
        n_valid,
        None,
    )

    np.testing.assert_array_equal(early_stopped[0], truncated_full[0])
    np.testing.assert_array_equal(early_stopped[1], truncated_full[1])


def test_blocked_bootstrap_ci_early_stop_never_stops_before_min_resamples():
    """Todo 227: even with a trivially-satisfiable tolerance, early-stop must not
    return before early_stop_min_resamples have been computed -- guards against a
    lucky-noise false stop on very few draws. Checkpoints below the floor are
    skipped entirely (never even seed `prev`), so the first checkpoint AT the
    floor only seeds `prev` -- the earliest possible stop is one more
    check_interval past the floor (see the sibling test's docstring for why a
    stop requires two checkpoints to compare).
    """
    rng = np.random.default_rng(13)
    n_valid = 200
    block_p = 3
    n_boot = 500
    block_size = 8
    min_resamples = 300
    check_interval = 50
    expected_stop_at = min_resamples + check_interval

    X_raw_block = rng.normal(size=(n_valid, block_p))
    Y_scale = rng.normal(size=n_valid)
    n_time_blocks = -(-n_valid // block_size)
    starts_matrix = rng.integers(0, n_valid, size=(n_boot, n_time_blocks))
    offsets = np.arange(block_size)

    early_stopped = _blocked_bootstrap_ci(
        X_raw_block,
        Y_scale,
        starts_matrix,
        offsets,
        n_valid,
        None,
        early_stop_enabled=True,
        early_stop_check_interval=check_interval,
        early_stop_tol=1e9,
        early_stop_min_resamples=min_resamples,
        early_stop_stable_checks=1,
    )
    truncated_at_expected_stop = _blocked_bootstrap_ci(
        X_raw_block, Y_scale, starts_matrix[:expected_stop_at], offsets, n_valid, None
    )

    np.testing.assert_array_equal(early_stopped[0], truncated_at_expected_stop[0])
    np.testing.assert_array_equal(early_stopped[1], truncated_at_expected_stop[1])


def test_subsample_and_rank_early_stop_kwargs_default_to_disabled():
    """Todo 227: _subsample_and_rank callers that don't pass any
    bootstrap_early_stop_* kwarg (every pre-todo-227 call site, and both live
    ic_engine.py call sites when config.bootstrap_early_stop_enabled is False,
    the seeded default) must get byte-identical output to before todo 227 --
    proven by omitting the new kwargs entirely and confirming the result matches
    an explicit early_stop_enabled=False call.
    """
    rng_data = np.random.default_rng(23)
    n_sub = 300
    n_features = 4
    X_sub_nd = rng_data.normal(size=(n_sub, n_features)).astype(np.float32)
    returns_scale = rng_data.normal(size=n_sub)
    valid_mask = np.ones(n_sub, dtype=bool)
    valid_mask[:20] = False

    common_kwargs = dict(
        walk_forward_folds=3,
        embargo_bars=1,
        min_reliable_n=2,
        bootstrap_block_size=10,
        bootstrap_resamples=60,
        feature_block_columns=2,
        max_workers=1,
    )

    omitted = _subsample_and_rank(
        X_sub_nd, valid_mask, returns_scale, rng=np.random.default_rng(5), **common_kwargs
    )
    explicit = _subsample_and_rank(
        X_sub_nd,
        valid_mask,
        returns_scale,
        rng=np.random.default_rng(5),
        bootstrap_early_stop_enabled=False,
        **common_kwargs,
    )

    _assert_subsample_and_rank_outputs_equal(omitted, explicit)


def test_cell_too_large_error_raised_by_both_cell_functions():
    """A cell whose raw row count exceeds config.max_cell_rows fails loudly
    (CellTooLargeError) from BOTH cell functions, never silently routing to an
    alternate algorithm (162-01 Task 3, todo 140). Synthetic in-memory arrays,
    a config with max_cell_rows=5, and a 10-row input -- no DB required.
    """
    import dataclasses

    from services.ic_engine import ICEngineConfig

    base_config = ICEngineConfig(
        min_observations=500,
        fdr_alpha=0.05,
        walk_forward_folds=3,
        sharpe_window_size=2000,
        sharpe_min_windows=10,
        subsample_min_stride=5,
        min_reliable_n=2,
        cluster_max_corr=0.70,
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
    )
    tiny_config = dataclasses.replace(base_config, max_cell_rows=5)

    n_rows = 10
    n_features = 4
    X_aligned = np.random.default_rng(1).normal(size=(n_rows, n_features)).astype(np.float32)
    returns_mat = np.random.default_rng(2).normal(size=(n_rows, 4))
    complete_mat = np.ones((n_rows, 4), dtype=bool)
    rng = np.random.default_rng(3)

    with pytest.raises(CellTooLargeError):
        _compute_one_regime_cell(
            "trending_up",
            False,
            np.ones(n_rows, dtype=bool),
            "symbol_hmm",
            X_aligned=X_aligned,
            returns_mat=returns_mat,
            complete_mat=complete_mat,
            config=tiny_config,
            symbol="TEST",
            tf="1d",
            rng=rng,
            training_window_end=None,
            feature_status_map=None,
            run_ts=None,
        )

    with pytest.raises(CellTooLargeError):
        _compute_one_cross_sectional_cell(
            "trending_up",
            X_raw=X_aligned,
            returns_mat=returns_mat,
            complete_mat=complete_mat,
            config=tiny_config,
            tf="1d",
            rng=rng,
            training_window_end=None,
            feature_status_map=None,
            run_ts=None,
            prior_e_values={},
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
