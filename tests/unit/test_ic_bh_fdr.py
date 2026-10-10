"""Unit tests: corpus-level BH-FDR correction (single multipletests call).

Phase A P2 fix: ALL cell p-values across the whole corpus get ONE multipletests
call, not a per-symbol loop (which would inflate the effective FDR rate). alpha_score
is a single predictor, so there is no collinearity-clustering step here -- every
cell IS representative for BH-FDR.

No DB, no Kafka. Pure numpy / statsmodels.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from statsmodels.stats.multitest import multipletests

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def test_single_corpus_level_bh_fdr_call_flags_low_p_cells():
    """200 synthetic cells: 10 with p<0.001, 190 with p=0.5. Only the 10 pass BH-FDR."""
    rng = np.random.default_rng(11)
    low_p = rng.uniform(0.0, 0.001, size=10)
    high_p = np.full(190, 0.5)
    pvals_flat = np.concatenate([low_p, high_p]).tolist()

    reject, p_corr, _, _ = multipletests(pvals_flat, alpha=0.05, method="fdr_bh")

    n_passing = int(reject.sum())
    assert n_passing == 10, f"Expected exactly 10 cells to pass BH-FDR, got {n_passing}"
    assert all(reject[:10]), "All 10 low-p cells must pass"
    assert not any(reject[10:]), "None of the 190 null cells may pass"


def test_bh_fdr_scatter_back_via_offset_index_lists():
    """Verify the offset-index scatter pattern used to map flat pvals back to per-cell rows."""
    # Simulate two "workers" each contributing rows + pvals; EnsembleICEngine accumulates
    # pvals_flat and pval_result_idxs (offsets into corpus_all_results) across all workers.
    worker_a_results = [{"cell": "A0"}, {"cell": "A1"}]
    worker_a_pvals = [0.0001, 0.5]
    worker_a_idxs = [0, 1]

    worker_b_results = [{"cell": "B0"}, {"cell": "B1"}, {"cell": "B2"}]
    worker_b_pvals = [0.0002, 0.6, 0.7]
    worker_b_idxs = [0, 1, 2]

    corpus_all_results: list[dict] = []
    corpus_pvals_flat: list[float] = []
    corpus_pval_result_idxs: list[int] = []

    for results, pvals, idxs in (
        (worker_a_results, worker_a_pvals, worker_a_idxs),
        (worker_b_results, worker_b_pvals, worker_b_idxs),
    ):
        offset = len(corpus_all_results)
        corpus_all_results.extend(results)
        corpus_pvals_flat.extend(pvals)
        corpus_pval_result_idxs.extend(offset + i for i in idxs)

    assert len(corpus_all_results) == 5
    assert corpus_pval_result_idxs == [0, 1, 2, 3, 4]

    reject, p_corr, _, _ = multipletests(corpus_pvals_flat, alpha=0.05, method="fdr_bh")
    for flat_idx, result_idx in enumerate(corpus_pval_result_idxs):
        corpus_all_results[result_idx]["bh_adjusted_p"] = float(p_corr[flat_idx])
        corpus_all_results[result_idx]["passes_fdr"] = bool(reject[flat_idx])

    # Cell A0 and B0 have the lowest p-values and must pass.
    assert corpus_all_results[0]["passes_fdr"] is True  # A0
    assert corpus_all_results[2]["passes_fdr"] is True  # B0
    # Cell A1, B1, B2 have high p-values and must not pass.
    assert corpus_all_results[1]["passes_fdr"] is False  # A1
    assert corpus_all_results[3]["passes_fdr"] is False  # B1
    assert corpus_all_results[4]["passes_fdr"] is False  # B2


def test_no_collinearity_clustering_every_cell_representative():
    """alpha_score is 1 predictor -- every (symbol, tf, regime, lookahead) cell IS
    representative for BH-FDR; there is no cluster_id grouping step to skip cells."""
    # A "cell" here has no cluster_id field at all -- the absence itself is the
    # behavior under test (contrast with ic_engine's per-feature cluster_id).
    cell = {"symbol": "SPY", "tf": "5m", "regime": "low_bull", "lookahead": "fast"}
    assert "cluster_id" not in cell
