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
    _BROADCAST_CLUSTER_ID_OFFSET,
    _FEATURE_NAMES,
    CellTooLargeError,
    ICEngineConfig,
    _blocked_bootstrap_ci,
    _compute_cross_sectional_tf,
    _compute_one_broadcast_cell,
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


def test_compute_symbol_tf_has_no_context_features_daily_path():
    """_compute_symbol_tf must not reintroduce the deleted daily-cadence path (D-01).

    Phase 173 Plan 02 deleted the bespoke CONTEXT_FEATURES daily-cadence
    significance block: 231 redundant per-symbol significance tests of the
    literal same macro time series, each entering BH-FDR independently -- a
    hand-maintained broadcast-feature frozenset that todo 270's own comment
    named as "the cautionary example why" a hardcoded list doesn't scale. CI
    enforcement here is the only thing standing between a future edit and
    quietly reintroducing that exact failure mode.
    """
    source = inspect.getsource(_compute_symbol_tf)

    assert "CONTEXT_FEATURES" not in source, (
        "_compute_symbol_tf must not reference CONTEXT_FEATURES -- the daily-cadence "
        "significance path was deleted in Phase 173 (D-01); broadcast features are now "
        "measured in a separate broadcast cell, not a hand-maintained frozenset here"
    )
    assert "context_features" not in source, (
        "_compute_symbol_tf must not query the context_features table -- that path was "
        "deleted in Phase 173 (D-01)"
    )
    assert "min_obs_daily" not in source, (
        "_compute_symbol_tf must not reference min_obs_daily -- that config field was "
        "removed along with the daily-cadence path it exclusively gated (Phase 173 D-01)"
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


def test_compute_cross_sectional_tf_calls_broadcast_cell_after_fetch_closes():
    """Phase 173 Plan 04: _compute_one_broadcast_cell( must appear textually
    AFTER the fetch `with short_lived_conn(dsn) as conn:` block has closed --
    same connection-scoping invariant as its per-symbol-pooled sibling call
    (test_compute_cross_sectional_tf_closes_connection_before_clustering), for
    the identical reason: the 143.1-07 corpus re-run crashed twice at the
    transition point where a connection was held open across a multi-hour
    compute-only phase."""
    source = inspect.getsource(_compute_cross_sectional_tf)

    assert "_compute_one_broadcast_cell(" in source
    with_idx = source.index("with short_lived_conn(dsn) as conn:")
    call_idx = source.index("_compute_one_broadcast_cell(")
    assert with_idx < call_idx, (
        "_compute_one_broadcast_cell( must appear after the "
        "short_lived_conn(dsn) with-block has closed"
    )

    with_line = source[: source.index("\n", with_idx)].splitlines()[-1]
    with_indent = len(with_line) - len(with_line.lstrip())
    call_line_start = source.rindex("\n", 0, call_idx) + 1
    call_line_end = source.index("\n", call_idx)
    call_line = source[call_line_start:call_line_end]
    call_indent = len(call_line) - len(call_line.lstrip())
    assert call_indent <= with_indent, (
        "_compute_one_broadcast_cell( must be dedented outside the "
        "short_lived_conn(dsn) with-block, not nested inside it"
    )


def test_compute_cross_sectional_tf_calls_broadcast_cell_before_cluster_groups():
    """Phase 173 Plan 04 (D-07): _compute_one_broadcast_cell( must appear
    textually BEFORE the cluster_groups representative-selection loop, so
    broadcast rows enter the SAME corpus-level BH-FDR family as per-symbol
    pooled rows -- no separate FDR pass, no new table."""
    source = inspect.getsource(_compute_cross_sectional_tf)

    broadcast_call_idx = source.index("_compute_one_broadcast_cell(")
    cluster_groups_idx = source.index("cluster_groups: dict[tuple, list[tuple[float, int]]] = {}")
    assert broadcast_call_idx < cluster_groups_idx, (
        "_compute_one_broadcast_cell( must appear before the cluster_groups "
        "representative-selection loop -- broadcast rows must be present in "
        "all_results before that loop runs"
    )


def test_compute_cross_sectional_tf_extends_all_results_with_broadcast_rows():
    """The broadcast cell's returned rows must be merged into all_results (via
    .extend, not a separate write path) and its skipped-feature count added to
    n_skipped -- same accounting contract as the per-symbol pooled cell."""
    source = inspect.getsource(_compute_cross_sectional_tf)
    assert "all_results.extend(broadcast_results)" in source
    assert "n_skipped += broadcast_skipped" in source


def test_cluster_representative_grouping_never_mixes_broadcast_and_per_symbol_cluster_ids():
    """T-173-10 mitigation: exercises _compute_cross_sectional_tf's actual
    trailing cluster-representative-selection loop logic (group_key =
    (regime, lookahead_bars, cluster_id)) against a synthetic all_results list
    mixing offset (broadcast, >= _BROADCAST_CLUSTER_ID_OFFSET) and non-offset
    (per-symbol) cluster_id values at the SAME (regime, lookahead_bars) pair --
    no group key may contain rows from both sides of the offset. No live DB
    needed: this logic operates purely on already-computed dict rows."""
    all_results = [
        {"regime": "calm", "lookahead_bars": 5, "cluster_id": 3, "ic_value": 0.1},
        {"regime": "calm", "lookahead_bars": 5, "cluster_id": 3, "ic_value": 0.2},
        {
            "regime": "calm",
            "lookahead_bars": 5,
            "cluster_id": 3 + _BROADCAST_CLUSTER_ID_OFFSET,
            "ic_value": 0.3,
        },
        {"regime": "calm", "lookahead_bars": 5, "cluster_id": None, "ic_value": 0.4},
    ]
    # Mirrors _compute_cross_sectional_tf's exact grouping construction.
    cluster_groups: dict[tuple, list[tuple[float, int]]] = {}
    for result_idx, r in enumerate(all_results):
        cid = r["cluster_id"]
        if cid is None:
            continue
        group_key = (r["regime"], r["lookahead_bars"], cid)
        ic_val = r["ic_value"]
        abs_ic = abs(ic_val) if ic_val is not None else 0.0
        cluster_groups.setdefault(group_key, []).append((abs_ic, result_idx))

    for key, members in cluster_groups.items():
        cids = {all_results[idx]["cluster_id"] for _, idx in members}
        all_broadcast = all(c >= _BROADCAST_CLUSTER_ID_OFFSET for c in cids)
        all_per_symbol = all(c < _BROADCAST_CLUSTER_ID_OFFSET for c in cids)
        assert (
            all_broadcast or all_per_symbol
        ), f"group_key {key} mixes broadcast and per-symbol cluster_id values: {cids}"
    # The offset-partitioned broadcast group and the non-offset per-symbol
    # group must resolve to two distinct group_keys, never one merged group.
    assert len(cluster_groups) == 2


def test_cross_sectional_fetch_does_not_route_bar_ts_through_float32_accumulator():
    """Phase 173 Plan 03 (D-05): bar_ts_chunks must be a plain list, appended to
    directly -- never passed to X_acc.append_chunk (Float32ChunkAccumulator is
    float32-only; a datetime is not float32-safe data). Source-introspection,
    same justification as this file's other structural tests: the function
    requires a live database to exercise behaviorally.
    """
    source = inspect.getsource(_compute_cross_sectional_tf)

    assert "bar_ts_chunks: list[np.ndarray] = []" in source, (
        "bar_ts_chunks must be declared as a plain list, mirroring "
        "ret_chunks/cmp_chunks's own un-accumulator-ed pattern"
    )
    assert "bar_ts_chunks.append(np.array([r[0] for r in batch], dtype=object))" in source, (
        "bar_ts_chunks must be appended to directly from the batch's bar_ts "
        "column (row[0]), one array per chunk"
    )
    assert "np.concatenate(bar_ts_chunks)" in source, (
        "bar_ts_chunks must be concatenated once via np.concatenate, matching "
        "the np.vstack(ret_chunks)/np.vstack(cmp_chunks) idiom"
    )

    # X_acc.append_chunk must never be called on bar_ts_chunks/a bar_ts value --
    # the only append_chunk call in this function must be the pre-existing
    # feature-matrix one.
    append_chunk_calls = [line for line in source.splitlines() if "X_acc.append_chunk(" in line]
    assert len(append_chunk_calls) == 1, (
        f"expected exactly one X_acc.append_chunk( call (the feature matrix), "
        f"found {len(append_chunk_calls)}: {append_chunk_calls}"
    )
    assert "bar_ts" not in append_chunk_calls[0], (
        "X_acc.append_chunk( must never be called with bar_ts -- "
        "Float32ChunkAccumulator must not be extended to carry a timestamp"
    )


def test_cross_sectional_fetch_asserts_bar_ts_row_alignment():
    """Phase 173 Plan 03 (D-05, T-173-07): a crash-loud RuntimeError guard must
    compare len(bar_ts_arr) to len(X_raw) after concatenation -- per CLAUDE.md
    ('silent wrong answers are worse than loud crashes'), a misalignment here
    would silently mis-associate a broadcast feature value with the wrong
    timestamp in Plan 04, producing a plausible-looking but wrong IC.
    """
    source = inspect.getsource(_compute_cross_sectional_tf)

    assert "bar_ts_arr = np.concatenate(bar_ts_chunks)" in source
    guard_idx = source.index("if len(bar_ts_arr) != len(X_raw):")
    raise_idx = source.index("raise RuntimeError(", guard_idx)
    assert raise_idx - guard_idx < 200, (
        "the RuntimeError raise must immediately follow the length-mismatch "
        "guard, not be a coincidental later occurrence"
    )
    # The guard must be placed AFTER the X_raw early-return (X_raw is None) --
    # the no-data path must stay unchanged.
    early_return_idx = source.index("if X_raw is None:")
    assert early_return_idx < guard_idx, (
        "the bar_ts alignment guard must come after the X_raw is None "
        "early-return, not before it"
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
    """_compute_one_regime_cell (per-symbol), _compute_one_cross_sectional_cell
    (per-symbol pooled cross-sectional), and _compute_one_broadcast_cell (Phase
    173 Plan 04) must all delegate their rank/IC/CI/fold compute to the shared,
    feature-blocked _subsample_and_rank helper (162-01 Task 3, todos 139/140) --
    a hand-pasted rank fix in one sibling can no longer diverge from the others."""
    regime_source = inspect.getsource(_compute_one_regime_cell)
    cross_sectional_source = inspect.getsource(_compute_one_cross_sectional_cell)
    broadcast_source = inspect.getsource(_compute_one_broadcast_cell)

    assert (
        "_subsample_and_rank(" in regime_source
    ), "_compute_one_regime_cell must call _subsample_and_rank"
    assert (
        "_subsample_and_rank(" in cross_sectional_source
    ), "_compute_one_cross_sectional_cell must call _subsample_and_rank"
    assert (
        "_subsample_and_rank(" in broadcast_source
    ), "_compute_one_broadcast_cell must call _subsample_and_rank"


def test_subsample_and_rank_source_unchanged_by_broadcast_cell_plan():
    """Source-hash pin (Task 1 acceptance criteria): _subsample_and_rank's body
    must be byte-for-byte unchanged by Phase 173 Plan 04 -- the plan reuses the
    kernel unmodified, never edits it. Hash captured from the pre-Plan-04 source
    (identical to Plan 03's committed state, since Plan 04 makes zero edits to
    this function)."""
    import hashlib

    source = inspect.getsource(_subsample_and_rank)
    digest = hashlib.sha256(source.encode()).hexdigest()
    assert digest == "490777dba07fb9b2a224c139617f07b6c3ccacc36701e926c88694fbb5b20e2d", (
        "_subsample_and_rank's source changed -- Phase 173 Plan 04 must reuse "
        "this kernel byte-for-byte unmodified"
    )


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


# ---------------------------------------------------------------------------
# Phase 173 Plan 03 (D-01/D-05/D-08, todo 270): broadcast-aware column split.
# Full round-trip tests against _compute_one_cross_sectional_cell -- synthetic
# in-memory arrays shaped exactly like the real cell (n_features = len(
# _FEATURE_NAMES), matching the row-emission loop's `enumerate(_FEATURE_NAMES)`
# -- a smaller synthetic feature count, as used by the CellTooLargeError test
# above, only exercises the early-return gate, never reaches row emission).
# ---------------------------------------------------------------------------


def _broadcast_test_config(**overrides) -> ICEngineConfig:
    """Small-bootstrap ICEngineConfig for full round-trip cross-sectional cell
    tests -- single active scale (fast) and bootstrap_resamples cut from the
    production default (2000) to 20 for unit-test speed. tf='1d' avoids the
    e-value pilot (_E_VALUE_PILOT_TFS = {'5m'} only), keeping cumulative_e_value
    uniformly None and out of scope for these tests."""
    import dataclasses as _dc

    base_config = ICEngineConfig(
        min_observations=500,
        fdr_alpha=0.05,
        walk_forward_folds=0,
        sharpe_window_size=2000,
        sharpe_min_windows=10,
        subsample_min_stride=1,
        min_reliable_n=2,
        cluster_max_corr=0.70,
        lookahead_fast={"5m": 1, "15m": 1, "1h": 1, "1d": 1},
        lookahead_mid={"5m": 6, "15m": 2, "1h": 2, "1d": 2},
        lookahead_slow={"5m": 12, "15m": 5, "1h": 20, "1d": 5},
        lookahead_extended={"5m": 39, "15m": 10, "1h": 60, "1d": 10},
        active_scales={
            "5m": ("fast",),
            "15m": ("fast",),
            "1h": ("fast",),
            "1d": ("fast",),
        },
        equity_model_enabled=True,
        hac_max_lag=3,
        cs_chunk_ts=5000,
        symbol_fetch_chunk_rows=5000,
        n_workers=1,
        blas_threads_per_worker=1,
        bootstrap_resamples=20,
    )
    if overrides:
        base_config = _dc.replace(base_config, **overrides)
    return base_config


def _broadcast_test_inputs(
    n_rows: int = 40, seed: int = 11
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Synthetic X_raw/returns_mat/complete_mat shaped like one real chunked-
    fetch result: n_features columns (matching _FEATURE_NAMES exactly), one
    active scale."""
    n_features = len(_FEATURE_NAMES)
    rng_data = np.random.default_rng(seed)
    X_raw = rng_data.normal(size=(n_rows, n_features)).astype(np.float32)
    returns_mat = rng_data.normal(size=(n_rows, 1))
    complete_mat = np.ones((n_rows, 1), dtype=bool)
    return X_raw, returns_mat, complete_mat


def _call_cell(X_raw, returns_mat, complete_mat, *, broadcast_mask=None, seed=99):
    config = _broadcast_test_config()
    return _compute_one_cross_sectional_cell(
        "calm",
        X_raw=X_raw,
        returns_mat=returns_mat,
        complete_mat=complete_mat,
        config=config,
        tf="1d",
        rng=np.random.default_rng(seed),
        training_window_end=None,
        feature_status_map=None,
        run_ts=None,
        prior_e_values={},
        broadcast_mask=broadcast_mask,
    )


def test_compute_one_cross_sectional_cell_none_and_all_false_broadcast_mask_match():
    """Backward-compatibility guarantee (Task 1 <behavior>): broadcast_mask=None
    (the default, every pre-Plan-03 call site) must produce row-for-row identical
    output to an explicit all-False mask -- this change is a pure no-op when no
    feature carries the broadcast flag."""
    n_features = len(_FEATURE_NAMES)
    X_raw, returns_mat, complete_mat = _broadcast_test_inputs()

    rows_none, skipped_none = _call_cell(X_raw, returns_mat, complete_mat, broadcast_mask=None)
    rows_false, skipped_false = _call_cell(
        X_raw, returns_mat, complete_mat, broadcast_mask=np.zeros(n_features, dtype=bool)
    )

    assert skipped_none == skipped_false
    assert rows_none == rows_false
    assert len(rows_none) == n_features  # every feature non-degenerate, none masked


def test_compute_one_cross_sectional_cell_excludes_broadcast_feature_names_from_output():
    """Zero emitted rows carry a feature_name that is masked broadcast -- at the
    one active scale this config uses, and by extension at any scale (the mask
    is applied identically inside the per-scale loop for every scale)."""
    n_features = len(_FEATURE_NAMES)
    X_raw, returns_mat, complete_mat = _broadcast_test_inputs()
    broadcast_idx = [0, 5, 10]
    broadcast_mask = np.zeros(n_features, dtype=bool)
    broadcast_mask[broadcast_idx] = True
    broadcast_names = {_FEATURE_NAMES[i] for i in broadcast_idx}

    rows, _ = _call_cell(X_raw, returns_mat, complete_mat, broadcast_mask=broadcast_mask)

    emitted_names = {r["feature_name"] for r in rows}
    assert emitted_names.isdisjoint(broadcast_names)


def test_compute_one_cross_sectional_cell_row_count_equals_scales_times_non_broadcast_features():
    """Row count equals len(scales) * (n_features - broadcast_count), not
    len(scales) * n_features -- this config uses exactly one active scale."""
    n_features = len(_FEATURE_NAMES)
    X_raw, returns_mat, complete_mat = _broadcast_test_inputs()
    broadcast_idx = [0, 5, 10]
    broadcast_mask = np.zeros(n_features, dtype=bool)
    broadcast_mask[broadcast_idx] = True

    rows, _ = _call_cell(X_raw, returns_mat, complete_mat, broadcast_mask=broadcast_mask)

    n_scales = 1  # _broadcast_test_config's active_scales["1d"] == ("fast",)
    assert len(rows) == n_scales * (n_features - len(broadcast_idx))


def test_compute_one_cross_sectional_cell_degenerate_non_broadcast_feature_still_emits_nan_row():
    """A degenerate (zero-variance) feature that is NOT masked broadcast must
    still emit its NaN row exactly as before this change -- the two exclusion
    conditions (degenerate vs. symbol-invariant) must not get conflated."""
    n_features = len(_FEATURE_NAMES)
    X_raw, returns_mat, complete_mat = _broadcast_test_inputs()
    degenerate_idx = 7
    X_raw = X_raw.copy()
    X_raw[:, degenerate_idx] = 1.0  # constant -> degenerate

    broadcast_idx = [0, 5, 10]  # deliberately excludes degenerate_idx
    broadcast_mask = np.zeros(n_features, dtype=bool)
    broadcast_mask[broadcast_idx] = True

    rows, n_skipped = _call_cell(X_raw, returns_mat, complete_mat, broadcast_mask=broadcast_mask)

    degenerate_name = _FEATURE_NAMES[degenerate_idx]
    degenerate_rows = [r for r in rows if r["feature_name"] == degenerate_name]
    assert len(degenerate_rows) == 1
    assert degenerate_rows[0]["ic_value"] is None  # NaN -> None via _nan_to_none
    assert n_skipped == 1  # the degenerate feature, not the 3 broadcast features
    assert len(rows) == n_features - len(broadcast_idx)  # degenerate row still counted


def test_broadcast_read_query_has_no_status_filter():
    """T-173-15 mitigation, locked decision (173-03-PLAN.md <planner_findings>
    'Read/write population alignment'): the broadcast-set read predicate must
    carry no cr.status filter and no COALESCE. A status filter would silently
    re-admit a deprecated broadcast feature into the per-symbol cell; NULL =
    'true' is not true, so an unflagged row (no COALESCE needed) is simply not
    selected -- degrading to today's behavior for the 5 candidate rows and 2
    gate-less tombstones Plan 01 never writes."""
    import services.ic_engine as ic_module

    source = inspect.getsource(ic_module.main)
    start_idx = source.index("SELECT cr.name FROM concept_registry cr")
    end_idx = source.index(")", start_idx)
    query_block = source[start_idx:end_idx]

    assert "cr.status" not in query_block, (
        "broadcast-set read query must not filter on cr.status -- an unflagged-"
        "for-status row must still stay excluded from the per-symbol cell"
    )
    assert "COALESCE" not in query_block, (
        "broadcast-set read query must not COALESCE the metadata read -- "
        "NULL = 'true' correctly evaluates to not-selected for an unflagged row"
    )


def test_broadcast_feature_read_intersects_feature_names():
    """T-173-01 mitigation: the source between the broadcast SELECT and the
    frozenset assignment must reference _FEATURE_NAMES -- a database-sourced
    feature name must be intersected against the code-defined column set before
    it is stored anywhere, never trusted directly (these names flow toward
    _compute_cross_sectional_tf's f-string SQL column-list construction)."""
    import services.ic_engine as ic_module

    source = inspect.getsource(ic_module.main)
    select_idx = source.index("SELECT cr.name FROM concept_registry cr")
    frozenset_idx = source.index("broadcast_features: frozenset[str] = frozenset(")
    window = source[select_idx:frozenset_idx]

    assert "_FEATURE_NAMES" in window, (
        "the broadcast-name read must be intersected against _FEATURE_NAMES "
        "before being stored in broadcast_features -- T-173-01's mitigation"
    )


# ---------------------------------------------------------------------------
# Phase 173 Plan 04 (D-01..D-07, todo 270): _compute_one_broadcast_cell --
# the correctly-specified broadcast significance test. Synthetic in-memory
# fixtures shaped like one real chunked-fetch result: n_features columns
# (matching _FEATURE_NAMES exactly, same convention as Plan 03's tests above),
# G distinct bar_ts groups x S "symbol" rows per group.
# ---------------------------------------------------------------------------

from datetime import UTC, datetime, timedelta  # noqa: E402


def _broadcast_cell_config(**overrides) -> ICEngineConfig:
    """Small-bootstrap ICEngineConfig for _compute_one_broadcast_cell tests --
    single active scale (fast, lookahead=1) so subsample stride=1 and no group
    is dropped by subsampling; min_reliable_n low enough for small synthetic
    fixtures; tf='1d' (out of the e-value pilot's scope regardless, per
    <planner_findings> -- cumulative_e_value is always None for broadcast rows)."""
    import dataclasses as _dc

    base_config = ICEngineConfig(
        min_observations=500,
        fdr_alpha=0.05,
        walk_forward_folds=0,
        sharpe_window_size=2000,
        sharpe_min_windows=10,
        subsample_min_stride=1,
        min_reliable_n=2,
        cluster_max_corr=0.70,
        lookahead_fast={"5m": 1, "15m": 1, "1h": 1, "1d": 1},
        lookahead_mid={"5m": 6, "15m": 2, "1h": 2, "1d": 2},
        lookahead_slow={"5m": 12, "15m": 5, "1h": 20, "1d": 5},
        lookahead_extended={"5m": 39, "15m": 10, "1h": 60, "1d": 10},
        active_scales={
            "5m": ("fast",),
            "15m": ("fast",),
            "1h": ("fast",),
            "1d": ("fast",),
        },
        equity_model_enabled=True,
        hac_max_lag=3,
        cs_chunk_ts=5000,
        symbol_fetch_chunk_rows=5000,
        n_workers=1,
        blas_threads_per_worker=1,
        bootstrap_resamples=20,
    )
    if overrides:
        base_config = _dc.replace(base_config, **overrides)
    return base_config


def _broadcast_bar_ts(n_groups: int, symbols_per_group: int) -> np.ndarray:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    ts_list = []
    for g in range(n_groups):
        ts = start + timedelta(minutes=5 * g)
        ts_list.extend([ts] * symbols_per_group)
    return np.array(ts_list, dtype=object)


def _broadcast_cell_inputs(
    n_groups: int = 6,
    symbols_per_group: int = 3,
    broadcast_idx: tuple[int, ...] = (0, 5, 10),
    seed: int = 17,
):
    """Synthetic X_raw/returns_mat/complete_mat/bar_ts_arr/broadcast_mask, with
    broadcast_idx columns held IDENTICAL within every group (satisfies the
    cross-symbol-invariance guard by construction)."""
    n_features = len(_FEATURE_NAMES)
    n_rows = n_groups * symbols_per_group
    rng = np.random.default_rng(seed)
    X_raw = rng.normal(size=(n_rows, n_features)).astype(np.float32)

    if broadcast_idx:
        group_vals = rng.normal(size=(n_groups, len(broadcast_idx))).astype(np.float32)
        for g in range(n_groups):
            sl = slice(g * symbols_per_group, (g + 1) * symbols_per_group)
            X_raw[sl, list(broadcast_idx)] = group_vals[g]

    bar_ts_arr = _broadcast_bar_ts(n_groups, symbols_per_group)
    broadcast_mask = np.zeros(n_features, dtype=bool)
    if broadcast_idx:
        broadcast_mask[list(broadcast_idx)] = True

    returns_mat = rng.normal(size=(n_rows, 1))
    complete_mat = np.ones((n_rows, 1), dtype=bool)

    return bar_ts_arr, X_raw, returns_mat, complete_mat, broadcast_mask


def _call_broadcast_cell(
    bar_ts_arr, X_raw, returns_mat, complete_mat, broadcast_mask, *, config=None, seed=101
):
    if config is None:
        config = _broadcast_cell_config()
    return _compute_one_broadcast_cell(
        "calm",
        bar_ts_arr=bar_ts_arr,
        X_raw=X_raw,
        returns_mat=returns_mat,
        complete_mat=complete_mat,
        broadcast_mask=broadcast_mask,
        config=config,
        tf="1d",
        rng=np.random.default_rng(seed),
        training_window_end=None,
        feature_status_map=None,
        run_ts=None,
    )


def test_broadcast_cell_grouping_uses_no_sort_or_unique():
    """Acceptance criteria: the grouping code path (the executable body, not
    the docstring's own prose explaining the constraint) must contain none of
    np.unique, np.sort, np.argsort, or a pandas groupby -- each sorts and/or
    allocates additional full-length temporaries over the largest cell, exactly
    the 2026-07-08 OOM profile the boundary-scan design exists to avoid."""
    fn = _compute_one_broadcast_cell
    full_source = inspect.getsource(fn)
    docstring = fn.__doc__ or ""
    # Strip the docstring (which legitimately names the forbidden APIs in
    # prose, to document the constraint) so this checks executable code only.
    body_source = full_source.replace(docstring, "", 1)
    for forbidden in ("np.unique", "np.sort(", ".sort(", "np.argsort", "groupby", ".sort_values("):
        assert forbidden not in body_source, (
            f"_compute_one_broadcast_cell's executable body must not use "
            f"{forbidden!r} in its grouping code path (sort-free boundary-scan "
            "design, T-173-12)"
        )


def test_broadcast_cell_invariance_guard_uses_nan_safe_reductions():
    """Acceptance criteria: the invariance guard must use np.fmax.reduceat/
    np.fmin.reduceat (NaN-ignoring), never np.maximum.reduceat/
    np.minimum.reduceat (NaN-propagating) -- a data gap must not be
    misclassified as an invariance violation."""
    source = inspect.getsource(_compute_one_broadcast_cell)
    assert "np.fmax.reduceat" in source
    assert "np.fmin.reduceat" in source
    assert "np.maximum.reduceat" not in source
    assert "np.minimum.reduceat" not in source


def test_broadcast_cell_empty_mask_returns_empty_without_calling_subsample_and_rank(monkeypatch):
    """<behavior>: given an empty broadcast mask, the function returns an empty
    row list and does not call _subsample_and_rank."""
    import services.ic_engine as ic_module

    bar_ts_arr, X_raw, returns_mat, complete_mat, broadcast_mask = _broadcast_cell_inputs(
        n_groups=4, symbols_per_group=3, broadcast_idx=()
    )

    def _spy(*args, **kwargs):
        raise AssertionError("_subsample_and_rank must not be called for an empty broadcast mask")

    monkeypatch.setattr(ic_module, "_subsample_and_rank", _spy)

    rows, n_skipped = _call_broadcast_cell(
        bar_ts_arr, X_raw, returns_mat, complete_mat, broadcast_mask
    )
    assert rows == []
    assert n_skipped == 0


def test_broadcast_cell_none_mask_returns_empty():
    """<behavior>: broadcast_mask=None is treated identically to an all-False
    mask -- early-return, no compute attempted."""
    bar_ts_arr, X_raw, returns_mat, complete_mat, _ = _broadcast_cell_inputs(
        n_groups=4, symbols_per_group=3
    )
    rows, n_skipped = _call_broadcast_cell(bar_ts_arr, X_raw, returns_mat, complete_mat, None)
    assert rows == []
    assert n_skipped == 0


def test_broadcast_cell_empty_bar_ts_arr_returns_empty_without_raising():
    """Codex review finding (Task 4): a genuinely empty bar_ts_arr must early-
    return ([], 0), not raise an uncontrolled IndexError from indexing
    group_starts=[0] into a zero-length array. Currently unreachable via the
    single call site (_compute_cross_sectional_tf already returns early on
    X_raw is None before ever calling this function), but this function is
    tested as an independent unit with its own contract -- a defensive guard
    here costs nothing and matches the crash-loud-but-controlled philosophy
    the rest of this function follows."""
    n_features = len(_FEATURE_NAMES)
    empty_bar_ts = np.array([], dtype=object)
    empty_X = np.zeros((0, n_features), dtype=np.float32)
    empty_returns = np.zeros((0, 1))
    empty_complete = np.zeros((0, 1), dtype=bool)
    broadcast_mask = np.zeros(n_features, dtype=bool)
    broadcast_mask[0] = True

    rows, n_skipped = _call_broadcast_cell(
        empty_bar_ts, empty_X, empty_returns, empty_complete, broadcast_mask
    )
    assert rows == []
    assert n_skipped == 0


def test_broadcast_cell_collapses_to_one_row_per_distinct_bar_ts():
    """<behavior>/acceptance: given a bar_ts array with G distinct values over N
    rows, the collapsed feature matrix has exactly G rows -- observed via
    n_independent (usable-group count) on emitted rows, since stride=1 and
    every group is complete means no group is dropped by subsampling or the
    completeness gate."""
    n_groups, symbols_per_group = 7, 4
    bar_ts_arr, X_raw, returns_mat, complete_mat, broadcast_mask = _broadcast_cell_inputs(
        n_groups=n_groups, symbols_per_group=symbols_per_group
    )

    rows, _ = _call_broadcast_cell(bar_ts_arr, X_raw, returns_mat, complete_mat, broadcast_mask)

    assert len(rows) > 0
    for r in rows:
        assert r["n_independent"] == n_groups


def test_broadcast_cell_every_row_has_pooled_broadcast_identity():
    """<behavior>: every emitted row has symbol=='POOLED', is_pooled is True,
    regime==regime_label, regime_scope=='cross_sectional', cumulative_e_value
    is None. Every emitted row's cluster_id is at least 10000."""
    n_groups, symbols_per_group = 6, 3
    bar_ts_arr, X_raw, returns_mat, complete_mat, broadcast_mask = _broadcast_cell_inputs(
        n_groups=n_groups, symbols_per_group=symbols_per_group
    )

    rows, _ = _call_broadcast_cell(bar_ts_arr, X_raw, returns_mat, complete_mat, broadcast_mask)

    assert len(rows) > 0
    for r in rows:
        assert r["symbol"] == "POOLED"
        assert r["is_pooled"] is True
        assert r["regime"] == "calm"
        assert r["regime_scope"] == "cross_sectional"
        assert r["cumulative_e_value"] is None
        assert r["cluster_id"] is not None
        assert r["cluster_id"] >= _BROADCAST_CLUSTER_ID_OFFSET


def test_broadcast_cell_aggregate_return_matches_hand_computed_mean():
    """<behavior>/acceptance: the aggregate return for group g at scale j equals
    the arithmetic mean of that group's rows' returns_mat[:, j], for a fixture
    with 3 symbols and 4 timestamps. A broadcast feature and a hand-computed
    per-group mean return are both constructed as strictly increasing in group
    index g, so a perfect Spearman correlation (IC == 1.0 exactly) is only
    reachable if the aggregate the function actually used equals the true
    per-group mean -- any other aggregation of these known inputs breaks the
    monotonic 1:1 mapping."""
    n_groups, symbols_per_group = 4, 3
    n_features = len(_FEATURE_NAMES)
    broadcast_col = 3

    bar_ts_arr = _broadcast_bar_ts(n_groups, symbols_per_group)
    X_raw = np.zeros((n_groups * symbols_per_group, n_features), dtype=np.float32)
    returns_mat = np.zeros((n_groups * symbols_per_group, 1))
    for g in range(n_groups):
        sl = slice(g * symbols_per_group, (g + 1) * symbols_per_group)
        X_raw[sl, broadcast_col] = float(g)
        returns_mat[sl, 0] = [float(g + s) for s in range(symbols_per_group)]
    complete_mat = np.ones((n_groups * symbols_per_group, 1), dtype=bool)

    broadcast_mask = np.zeros(n_features, dtype=bool)
    broadcast_mask[broadcast_col] = True

    config = _broadcast_cell_config(min_reliable_n=2)
    rows, _ = _call_broadcast_cell(
        bar_ts_arr, X_raw, returns_mat, complete_mat, broadcast_mask, config=config
    )

    assert len(rows) == 1
    assert rows[0]["ic_value"] == pytest.approx(1.0)
    assert rows[0]["n_independent"] == n_groups


def test_broadcast_cell_raises_on_within_group_variance_violation():
    """<behavior>/acceptance: raises rather than returning results when a
    masked column's within-bar_ts spread exceeds
    config.broadcast_variance_threshold (T-173-09)."""
    bar_ts_arr, X_raw, returns_mat, complete_mat, broadcast_mask = _broadcast_cell_inputs(
        n_groups=4, symbols_per_group=3, broadcast_idx=(2,)
    )
    # Break invariance: group 0 occupies rows [0, 1, 2] -- disagree row 1 by far
    # more than any plausible float32 rounding tolerance.
    X_raw[1, 2] += 5.0

    with pytest.raises(RuntimeError, match="[Bb]roadcast invariance violated"):
        _call_broadcast_cell(bar_ts_arr, X_raw, returns_mat, complete_mat, broadcast_mask)


def test_broadcast_cell_raises_on_non_contiguous_bar_ts():
    """<behavior>/acceptance/T-173-16: raises rather than proceeding when a
    bar_ts value appears in two non-adjacent runs -- the ORDER BY invariant
    this whole design rests on has broken."""
    bar_ts_arr, X_raw, returns_mat, complete_mat, broadcast_mask = _broadcast_cell_inputs(
        n_groups=3, symbols_per_group=2, broadcast_idx=(1,)
    )
    bar_ts_arr = bar_ts_arr.copy()
    bar_ts_arr[-1] = bar_ts_arr[0]  # non-adjacent repeat of the first group's ts

    with pytest.raises(RuntimeError, match="contiguity invariant violated"):
        _call_broadcast_cell(bar_ts_arr, X_raw, returns_mat, complete_mat, broadcast_mask)


def test_broadcast_cell_all_nan_group_column_does_not_trip_invariance_guard():
    """<behavior>: a broadcast column that is NaN for every symbol in a group
    does NOT raise -- an all-NaN group is a data gap, not an invariance
    violation."""
    n_groups, symbols_per_group = 4, 3
    bar_ts_arr, X_raw, returns_mat, complete_mat, broadcast_mask = _broadcast_cell_inputs(
        n_groups=n_groups, symbols_per_group=symbols_per_group, broadcast_idx=(4,)
    )
    sl = slice(symbols_per_group, 2 * symbols_per_group)  # group 1's entire span
    X_raw[sl, 4] = np.nan

    rows, _ = _call_broadcast_cell(bar_ts_arr, X_raw, returns_mat, complete_mat, broadcast_mask)
    assert isinstance(rows, list)  # did not raise


def test_broadcast_cell_below_min_reliable_n_emits_zero_rows():
    """<behavior>/D-06: given fewer than min_reliable_n usable groups for a
    scale, the function emits no rows for that scale."""
    bar_ts_arr, X_raw, returns_mat, complete_mat, broadcast_mask = _broadcast_cell_inputs(
        n_groups=1, symbols_per_group=3, broadcast_idx=(6,)
    )
    config = _broadcast_cell_config(min_reliable_n=2)  # 1 distinct bar_ts < 2

    rows, n_skipped = _call_broadcast_cell(
        bar_ts_arr, X_raw, returns_mat, complete_mat, broadcast_mask, config=config
    )
    assert rows == []
    assert n_skipped >= 1


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
