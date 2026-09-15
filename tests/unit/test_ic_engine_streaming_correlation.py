"""Numerical-equivalence and cluster-label-identity coverage for Phase 174 Plan 09's
blocked two-pass streaming correlation (`_streaming_feature_correlation`) and its
column-wise `X_nd` memmap build (`_build_column_wise_x_nd`).

Every case anchors its assertion against numpy's `corrcoef` explicitly (never against
itself) -- the point of this file is proving the replacement is numerically identical
to the pre-Plan-09 implementation, not merely internally consistent. All cases use
small synthetic arrays; the claim under test is numerical identity, not scale.
"""

import subprocess
import sys
import textwrap

import numpy as np
import pytest

from services.ic_engine import (
    _build_column_wise_x_nd,
    _cluster_features,
    _streaming_feature_correlation,
)


def _orthonormal_pair(n: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Two mean-centered, unit-norm, mutually orthogonal vectors -- so that
    `y = rho*x + sqrt(1-rho**2)*z` has Pearson correlation with `x` EXACTLY `rho`
    by construction (up to float64 rounding), not approximately."""
    rng = np.random.default_rng(seed)
    a = rng.standard_normal(n)
    a = a - a.mean()
    a = a / np.linalg.norm(a)
    b = rng.standard_normal(n)
    b = b - b.mean()
    b = b - (b @ a) * a
    b = b / np.linalg.norm(b)
    return a, b


# ---------------------------------------------------------------------------
# Case 1: correlation equivalence across several synthetic structures.
# ---------------------------------------------------------------------------


def _well_conditioned(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.standard_normal((400, 6)).astype(np.float32)


def _correlated_pairs(seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = 400
    a = rng.standard_normal(n)
    b = a + rng.standard_normal(n) * 0.05
    c = rng.standard_normal(n)
    d = rng.standard_normal(n)
    return np.column_stack([a, b, c, d]).astype(np.float32)


def _with_constant_column(seed: int = 2) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = 400
    a = rng.standard_normal(n)
    const = np.full(n, 7.0)
    b = rng.standard_normal(n)
    return np.column_stack([a, const, b]).astype(np.float32)


def _with_nan_entry(seed: int = 3) -> np.ndarray:
    """One NaN value inside one column -- poisons that column's row/col of the
    correlation matrix (sum/mean/Gram entries touching it become NaN), exactly
    as it does for numpy's own `corrcoef`, without affecting the OTHER columns'
    mutual correlation."""
    rng = np.random.default_rng(seed)
    n = 400
    a = rng.standard_normal(n)
    b = rng.standard_normal(n)
    b[17] = np.nan
    c = rng.standard_normal(n)
    return np.column_stack([a, b, c]).astype(np.float32)


_STRUCTURE_CASES = {
    "well_conditioned": _well_conditioned,
    "correlated_pairs": _correlated_pairs,
    "constant_column": _with_constant_column,
    "nan_entry": _with_nan_entry,
}


@pytest.mark.parametrize("structure", list(_STRUCTURE_CASES))
def test_correlation_matches_reference_various_structures(structure: str) -> None:
    """Streaming correlation matches numpy's own `corrcoef` within atol=1e-6,
    elementwise, across several synthetic structures -- anchored explicitly
    against the reference, not against itself."""
    X = _STRUCTURE_CASES[structure]()
    ref = np.corrcoef(X.T)
    out = _streaming_feature_correlation(X, None, row_block=37)
    np.testing.assert_allclose(out, ref, atol=1e-6, equal_nan=True)


# ---------------------------------------------------------------------------
# Case 2: block-size invariance -- a throughput knob, never a statistic.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("structure", list(_STRUCTURE_CASES))
def test_block_size_invariance(structure: str) -> None:
    """Same input at row_block in {1, 7, len(X)} produces matrices equal within
    atol=1e-6 -- block size is a throughput knob (infra.ic_engine.corr_row_block),
    it must never change the computed correlation values."""
    X = _STRUCTURE_CASES[structure]()
    n = len(X)
    results = [_streaming_feature_correlation(X, None, row_block=rb) for rb in (1, 7, n)]
    for out in results[1:]:
        np.testing.assert_allclose(out, results[0], atol=1e-6, equal_nan=True)


# ---------------------------------------------------------------------------
# Case 3: cluster-label identity -- what actually propagates downstream through
# expand_int, not just the correlation matrix itself.
# ---------------------------------------------------------------------------


def _cluster_structure_cases() -> list[np.ndarray]:
    cases = []
    rng = np.random.default_rng(10)
    n = 300

    # (a) all independent -> every column its own cluster.
    cases.append(rng.standard_normal((n, 5)).astype(np.float32))

    # (b) two perfectly-correlated pairs + one independent.
    a = rng.standard_normal(n)
    c = rng.standard_normal(n)
    cases.append(np.column_stack([a, a, c, c, rng.standard_normal(n)]).astype(np.float32))

    # (c) all columns near-identical -> single cluster.
    base = rng.standard_normal(n)
    cases.append(
        np.column_stack([base + rng.standard_normal(n) * 0.001 for _ in range(4)]).astype(
            np.float32
        )
    )

    # (d) chain: a~b~c but a and c only weakly linked (transitive single-linkage).
    a = rng.standard_normal(n)
    b = a + rng.standard_normal(n) * 0.05
    c = b + rng.standard_normal(n) * 0.05
    d = rng.standard_normal(n)
    cases.append(np.column_stack([a, b, c, d]).astype(np.float32))

    # (e) mixed magnitudes.
    e1 = rng.standard_normal(n) * 100
    e2 = e1 * 0.5 + rng.standard_normal(n) * 0.1
    e3 = rng.standard_normal(n) * 0.001
    cases.append(np.column_stack([e1, e2, e3]).astype(np.float32))

    return cases


@pytest.mark.parametrize("case_idx", range(5))
def test_cluster_label_identity_across_structures(case_idx: int) -> None:
    """_cluster_features(streaming_corr, t) returns labels array-equal to
    _cluster_features(reference_corr, t) -- labels, not just the correlation
    matrix, are what propagate downstream through expand_int."""
    X = _cluster_structure_cases()[case_idx]
    t = 0.70
    ref_labels = _cluster_features(np.corrcoef(X.T), t)
    stream_labels = _cluster_features(_streaming_feature_correlation(X, None, 13), t)
    assert np.array_equal(ref_labels, stream_labels)


# ---------------------------------------------------------------------------
# Case 4: degenerate handling -- a constant column's NaN row/col.
# ---------------------------------------------------------------------------


def test_degenerate_column_nan_handled_identically() -> None:
    """A constant column produces a NaN correlation row/col that nan_to_num
    zeroes identically in both paths; assert labels match."""
    X = _with_constant_column()
    t = 0.70
    ref_labels = _cluster_features(np.corrcoef(X.T), t)
    stream_labels = _cluster_features(_streaming_feature_correlation(X, None, 11), t)
    assert np.array_equal(ref_labels, stream_labels)


# ---------------------------------------------------------------------------
# Case 5: single-column and zero-column inputs.
# ---------------------------------------------------------------------------


def test_single_column_input_returns_single_label() -> None:
    X = np.random.default_rng(4).standard_normal((50, 1)).astype(np.float32)
    corr = _streaming_feature_correlation(X, None, row_block=17)
    assert corr.shape == (1, 1)
    labels = _cluster_features(corr, cluster_max_corr=0.70)
    assert labels.shape == (1,)
    assert len(set(labels)) == 1


def test_zero_column_mask_does_not_raise() -> None:
    X = np.random.default_rng(5).standard_normal((50, 3)).astype(np.float32)
    mask = np.zeros(3, dtype=bool)
    corr = _streaming_feature_correlation(X, mask, row_block=17)
    assert corr.shape == (0, 0)
    labels = _cluster_features(corr, cluster_max_corr=0.70)
    assert labels.shape == (0,)


# ---------------------------------------------------------------------------
# Case 6: numerical stability on a large-mean input (the catastrophic-
# cancellation case the two-pass form exists to handle).
# ---------------------------------------------------------------------------


def test_large_mean_numerical_stability() -> None:
    """Columns with a large offset relative to their variance -- the
    catastrophic-cancellation case a single-pass (sum-of-squares-minus-square-
    of-sum) implementation would fail. Empirically confirmed while writing this
    test: at mean_offset=20000/std=0.01, a naive single-pass float64
    accumulation diverges from the reference by ~5e-3 (details in this test's
    own single-pass comparison), while the two-pass streaming implementation
    stays within 1e-6 -- pinning the design decision, not just asserting it."""
    rng = np.random.default_rng(6)
    n = 2000
    mean_offset = 20000.0
    std = 0.01
    a = rng.standard_normal(n) * std + mean_offset
    b = rng.standard_normal(n) * std + mean_offset * 0.5 + a * 0.4
    X = np.column_stack([a, b]).astype(np.float32)

    ref = np.corrcoef(X.T)
    stream = _streaming_feature_correlation(X, None, row_block=37)
    np.testing.assert_allclose(stream, ref, atol=1e-6, equal_nan=True)

    # Naive single-pass float64 accumulation, for comparison only (not the
    # implementation under test) -- demonstrates the cancellation the two-pass
    # form above avoids.
    Xf = X.astype(np.float64)
    n_ = Xf.shape[0]
    mean = Xf.sum(axis=0) / n_
    cov_singlepass = (Xf.T @ Xf) / n_ - np.outer(mean, mean)
    std_sp = np.sqrt(np.diag(cov_singlepass))
    with np.errstate(invalid="ignore", divide="ignore"):
        corr_singlepass = cov_singlepass / np.outer(std_sp, std_sp)
    singlepass_err = np.nanmax(np.abs(corr_singlepass - ref))
    stream_err = np.nanmax(np.abs(stream - ref))
    assert singlepass_err > 1e-4, (
        "test construction check: the single-pass comparison must actually show "
        f"catastrophic cancellation (got {singlepass_err}), or this test isn't "
        "pinning anything"
    )
    assert stream_err < 1e-6


# ---------------------------------------------------------------------------
# Case 7: column-wise X_nd build equals the boolean-index result.
# ---------------------------------------------------------------------------


def test_column_wise_x_nd_equals_boolean_index_and_cleans_up(tmp_path) -> None:
    X_raw = np.random.default_rng(7).standard_normal((200, 8)).astype(np.float32)
    mask = np.array([True, False, True, True, False, False, True, True])

    X_nd, cleanup = _build_column_wise_x_nd(X_raw, mask, str(tmp_path))
    assert np.array_equal(np.asarray(X_nd), X_raw[:, mask])

    scratch_files_before = list(tmp_path.glob("*.memmap"))
    assert len(scratch_files_before) == 1

    cleanup()

    scratch_files_after = list(tmp_path.glob("*.memmap"))
    assert scratch_files_after == []


def test_column_wise_x_nd_zero_columns_skips_memmap(tmp_path) -> None:
    """A zero-column mask returns an empty in-RAM array and a no-op cleanup --
    np.memmap cannot back a zero-byte file, and there is nothing to stage."""
    X_raw = np.random.default_rng(8).standard_normal((50, 4)).astype(np.float32)
    mask = np.zeros(4, dtype=bool)

    X_nd, cleanup = _build_column_wise_x_nd(X_raw, mask, str(tmp_path))
    assert X_nd.shape == (50, 0)
    assert list(tmp_path.glob("*.memmap")) == []
    cleanup()  # must not raise


# ---------------------------------------------------------------------------
# Case 8/9: cluster identity at the threshold boundary -- the brittleness case
# where a tiny correlation difference between the streaming and reference paths
# CAN flip a linkage-cut merge.
# ---------------------------------------------------------------------------

_CLUSTER_MAX_CORR = 0.70


@pytest.mark.parametrize("delta", [1e-3, 1e-5, 1e-7])
@pytest.mark.parametrize("position", ["below", "at", "above"])
@pytest.mark.parametrize("row_block", [1, 7, "full"])
def test_cluster_identity_at_threshold_boundary(
    delta: float, position: str, row_block: int | str
) -> None:
    """_cluster_features cuts the linkage at t = sqrt(0.5 * (1 - cluster_max_corr)),
    so a correlation sitting exactly on cluster_max_corr lands exactly on the
    cut. Column pairs are constructed with an EXACT (by orthonormal-basis
    construction) true Pearson correlation at cluster_max_corr - delta, exactly
    cluster_max_corr, and cluster_max_corr + delta. For every (delta, position,
    row_block) combination, the streaming path's cluster labels are array-equal
    to the reference (`np.corrcoef`) path's labels -- empirically, no residual
    tolerance band exists at any tested delta down to 1e-7 (see this file's
    docstring / the plan SUMMARY's named tolerance-policy note: NONE was
    needed), so this asserts EXACT identity, never a loosened comparison.
    """
    n = 2000
    x, z = _orthonormal_pair(n, seed=99)
    sign = {"below": -1, "at": 0, "above": 1}[position]
    rho = _CLUSTER_MAX_CORR + sign * delta
    y = rho * x + np.sqrt(1.0 - rho**2) * z
    X = np.column_stack([x, y]).astype(np.float32)

    rb = n if row_block == "full" else row_block

    ref_labels = _cluster_features(np.corrcoef(X.T), _CLUSTER_MAX_CORR)
    stream_labels = _cluster_features(
        _streaming_feature_correlation(X, None, rb), _CLUSTER_MAX_CORR
    )
    assert np.array_equal(ref_labels, stream_labels), (
        f"label mismatch at delta={delta} position={position} row_block={row_block}: "
        f"ref={ref_labels} stream={stream_labels}"
    )


# ---------------------------------------------------------------------------
# Case 10: X_nd teardown does not precede its readers.
#
# A real post-teardown read through a closed+unlinked np.memmap is memory-unsafe
# at the OS level -- empirically confirmed while writing this test to segfault
# the CPython process outright on this platform/numpy version, rather than raise
# a catchable ValueError (matching this module's own documented caveat: "any
# read of that view after close() raises ValueError ... or is a platform-
# dependent invalid read elsewhere"). Running that read in-process would crash
# the whole pytest run, not just fail one test. This case therefore runs the
# read in an isolated subprocess and asserts the READ NEVER SILENTLY SUCCEEDS
# WITH DATA -- either a clean exception or a hard crash both prove the mapping
# is genuinely gone, which is the load-bearing claim (X_sub_nd is a live reader,
# so its teardown must wait for every reader to finish) -- not the specific
# failure mechanism.
# ---------------------------------------------------------------------------


def test_x_nd_teardown_does_not_precede_readers(tmp_path) -> None:
    script = textwrap.dedent(f"""
        import numpy as np
        from services.ic_engine import _build_column_wise_x_nd

        X_raw = np.arange(80, dtype=np.float32).reshape(20, 4)
        mask = np.array([True, True, False, True])
        X_nd, cleanup = _build_column_wise_x_nd(X_raw, mask, {str(tmp_path)!r})

        # X_sub_nd is a VIEW over X_nd, exactly like the per-scale loop's own
        # X_sub_nd = X_nd[0:n_raw:scale_stride] -- prove it is a live reader
        # BEFORE teardown.
        X_sub_nd = X_nd[0:20:2]
        assert np.array_equal(np.asarray(X_sub_nd), X_raw[0:20:2][:, mask])

        cleanup()

        # Any read through X_sub_nd after teardown must not return silently-
        # wrong data. print() only runs if the read returns normally.
        value = X_sub_nd[0, 0]
        print("READ_SUCCEEDED", value)
        """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert "READ_SUCCEEDED" not in result.stdout, (
        "post-teardown read through X_sub_nd returned data instead of failing "
        f"loudly: stdout={result.stdout!r}"
    )
    assert result.returncode != 0, (
        "post-teardown read must fail loudly (exception or crash), got a clean "
        f"exit 0: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
