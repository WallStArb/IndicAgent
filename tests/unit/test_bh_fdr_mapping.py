"""Unit test: BH-FDR order-preservation assertion.

Verifies that statsmodels.stats.multitest.multipletests with method='fdr_bh'
preserves input order -- the q-value at index i corresponds to the p-value
at index i. This is the correctness requirement for ic_engine.py's BH-FDR
correction pass, which assigns q-values back to result rows by flat index.

No DB, no Kafka. Pure statsmodels.
"""

from __future__ import annotations

import numpy as np
from statsmodels.stats.multitest import multipletests


def test_bh_fdr_output_length_matches_input():
    """multipletests must return q-values of the same length as input p-values."""
    pvals = np.array([0.9, 0.001, 0.5, 0.02, 0.8])
    reject, q, _, _ = multipletests(pvals, alpha=0.05, method="fdr_bh")
    assert len(q) == len(pvals), f"Expected q length {len(pvals)}, got {len(q)}"
    assert len(reject) == len(pvals)


def test_bh_fdr_preserves_input_order():
    """q[argmin(pvals)] == min(q) -- smallest p maps to smallest q."""
    pvals = np.array([0.9, 0.001, 0.5, 0.02, 0.8])
    reject, q, _, _ = multipletests(pvals, alpha=0.05, method="fdr_bh")

    # The q-value at the index of the smallest p must be the overall minimum q
    smallest_p_idx = int(np.argmin(pvals))
    assert q[smallest_p_idx] == q.min(), (
        f"Order preservation violated: q at smallest-p index {smallest_p_idx} "
        f"is {q[smallest_p_idx]:.6f} but min(q) is {q.min():.6f}"
    )


def test_bh_fdr_does_not_sort_output():
    """multipletests does NOT sort the output -- indices match input positions."""
    # Shuffle deliberately: put smallest p at index 1, not 0
    pvals = np.array([0.9, 0.001, 0.5, 0.02, 0.8])
    reject, q, _, _ = multipletests(pvals, alpha=0.05, method="fdr_bh")

    # Verify the sort order of q matches the sort order of p
    # If output were sorted, q[0] would be the smallest q -- check it is NOT
    # (since pvals[0]=0.9 is the largest p, its q should be large, not small)
    assert q[0] > q[1], (
        "multipletests appears to have sorted the output: "
        f"q[0]={q[0]:.6f} should be > q[1]={q[1]:.6f} (pvals[0]=0.9 > pvals[1]=0.001)"
    )


def test_bh_fdr_index_correspondence():
    """q-value rank ordering must match p-value rank ordering (ignoring ties).

    BH correction is monotone-preserving: if p[i] < p[j] then q[i] <= q[j].
    We verify this by checking that each pair (i, j) where p[i] < p[j] also
    has q[i] <= q[j]. This captures the order-preservation guarantee without
    being fragile to how ties in q-values (caused by BH cummin) are sorted.
    """
    pvals = np.array([0.9, 0.001, 0.5, 0.02, 0.8])
    reject, q, _, _ = multipletests(pvals, alpha=0.05, method="fdr_bh")

    # For all pairs (i, j): p[i] < p[j] must imply q[i] <= q[j]
    n = len(pvals)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if pvals[i] < pvals[j]:
                assert q[i] <= q[j] + 1e-12, (
                    f"BH order violation: p[{i}]={pvals[i]} < p[{j}]={pvals[j]} "
                    f"but q[{i}]={q[i]:.6f} > q[{j}]={q[j]:.6f}. "
                    "multipletests must preserve rank ordering of p-values in output."
                )


def test_bh_fdr_reject_at_significant_p():
    """Very small p-values must be rejected at alpha=0.05 after BH correction."""
    pvals = np.array([0.9, 0.001, 0.5, 0.02, 0.8])
    reject, q, _, _ = multipletests(pvals, alpha=0.05, method="fdr_bh")
    # p=0.001 at index 1 should be rejected
    assert reject[1], f"p=0.001 was not rejected after BH correction (q={q[1]:.4f})"


def test_bh_fdr_monotonic_q_with_sorted_p():
    """BH q-values must be non-decreasing when p-values are sorted ascending."""
    # Sorted p-values: BH q-values must be non-decreasing
    pvals_sorted = np.array([0.001, 0.01, 0.05, 0.1, 0.5, 0.9])
    reject, q, _, _ = multipletests(pvals_sorted, alpha=0.05, method="fdr_bh")
    # q must be non-decreasing (BH enforces monotonicity via cummin on sorted p)
    diffs = np.diff(q)
    assert np.all(
        diffs >= -1e-15
    ), f"BH q-values not non-decreasing for sorted p-values: q={q}, diffs={diffs}"
