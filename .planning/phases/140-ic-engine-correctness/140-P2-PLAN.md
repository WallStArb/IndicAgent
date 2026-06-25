---
phase: 140-ic-engine-correctness
plan: P2
type: execute
wave: 2
depends_on: [P0, P1]
files_modified:
  - services/ic_engine.py
autonomous: true

must_haves:
  truths:
    - "Features are hierarchically clustered on their correlation matrix per (symbol, tf, regime) before BH-FDR"
    - "Only the cluster representative (highest |ic_value| in the cluster) has its p-value entered into the BH-FDR batch"
    - "Non-representative cluster members are written with passes_fdr=false and bh_adjusted_p=NULL"
    - "Every feature_ic_scores row gets a cluster_id reflecting its cluster within that run"
    - "The cluster correlation threshold is read from APR key alpha.ic.cluster_max_corr"
  artifacts:
    - path: "services/ic_engine.py"
      provides: "Hierarchical clustering + representative-only BH-FDR + cluster_id persistence"
      contains: "fcluster"
  key_links:
    - from: "ic_engine clustering (scipy linkage/fcluster)"
      to: "pvals_flat / pval_result_idxs (BH-FDR batch)"
      via: "only representative feature p-values appended"
      pattern: "cluster"
    - from: "ic_engine result dict cluster_id"
      to: "feature_ic_scores.cluster_id column"
      via: "_INSERT_BODY cluster_id parameter"
      pattern: "cluster_id"
---

<objective>
Add feature-collinearity clustering to the IC engine so BH-FDR is applied to one representative per correlated cluster, not to all 61 features independently. This stops dense feature clusters (momentum x5, RSI x3, calendar x10, etc.) from inflating the effective evidence for their factor and over-weighting the ensemble.

Purpose: BH-FDR assumes approximately independent hypotheses. Correlated features (e.g. momentum_z_fast/mid/slow) violate this, biasing multiple-testing correction and downstream ensemble weights. Clustering + representative selection restores the independence assumption.

Output: Per-(symbol, tf, regime) hierarchical clustering in `_compute_symbol_tf`, cluster_id persisted on every row, and BH-FDR run on representatives only.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/phases/140-ic-engine-correctness/140-RESEARCH.md
@CLAUDE.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add cluster_id to result dict and INSERT SQL</name>
  <read_first>
    - services/ic_engine.py (lines 119-149 — _INSERT_BODY, _POOLED_INSERT_SQL, _REGIME_INSERT_SQL; lines 778-815 — the result dict append)
    - .planning/phases/140-ic-engine-correctness/140-RESEARCH.md ("Schema Changes" — cluster_id semantics)
  </read_first>
  <action>
    NOTE: read the CURRENT (post-P0) services/ic_engine.py — the per-scale loop was refactored in plan P0.

    1. Add `cluster_id` to `_INSERT_BODY` (services/ic_engine.py ~lines 119-137):
       - Add `cluster_id` to the column list after `regime_label_source, computed_at` (i.e. `..., computed_at, cluster_id`).
       - Add `%(cluster_id)s` to the VALUES list in the matching position.
       The ON CONFLICT clauses in `_POOLED_INSERT_SQL` / `_REGIME_INSERT_SQL` are unchanged (cluster_id is not
       part of any key).

    2. Add `"cluster_id": None` to the result dict appended at lines ~778-808. It is populated in Task 2;
       initialize to `None` here so every dict has the key (psycopg2.extras.execute_batch requires all named
       params present in every row).
  </action>
  <verify>
    - `grep -n "cluster_id" services/ic_engine.py` shows the column in _INSERT_BODY, the %(cluster_id)s value, and the result-dict key
    - `python -c "import ast; ast.parse(open('services/ic_engine.py').read())"` — parses
    - `.venv/bin/ruff check services/ic_engine.py` — clean
  </verify>
  <acceptance_criteria>
    - Source: `_INSERT_BODY` column list includes `cluster_id` and VALUES includes `%(cluster_id)s`.
    - Source: the result dict appended in `_compute_symbol_tf` includes a `"cluster_id"` key.
    - Behavior: file parses and lints clean.
  </acceptance_criteria>
  <done>Every feature_ic_scores row written by the engine carries a cluster_id (None until Task 2 populates it).</done>
</task>

<task type="auto">
  <name>Task 2: Hierarchical clustering + representative-only BH-FDR</name>
  <read_first>
    - services/ic_engine.py (the post-P0 regime loop: degenerate detection on X_regime, per-scale subsampling, the result-dict append, and the BH-FDR block at ~lines 817-824)
    - .planning/phases/140-ic-engine-correctness/140-RESEARCH.md (Issue 4, "Cluster-Aware BH-FDR", Pitfall 4, "Don't Hand-Roll" table, and the scipy code block)
    - CLAUDE.md (APR mandate — cluster_max_corr must come from ConfigService, not a literal)
  </read_first>
  <action>
    Implement per-(symbol, tf, regime) feature clustering in `_compute_symbol_tf` (services/ic_engine.py).

    1. Imports at top of file:
       `from scipy.cluster.hierarchy import linkage, fcluster`
       `from scipy.spatial.distance import squareform`

    2. Read the APR threshold once where other APR values are loaded (the `apr` dict / `_load_apr`):
       `cluster_max_corr = apr["cluster_max_corr"]` (add `cluster_max_corr` to whatever `_load_apr` returns,
       reading config key `alpha.ic.cluster_max_corr` with fallback 0.70). Do NOT hardcode 0.70 in the loop.

    3. Inside the regime loop, AFTER degenerate detection produces `non_degenerate_mask` and `X_regime_nd`,
       and BEFORE the per-scale loop, compute clusters on the full non-degenerate regime matrix (one set of
       clusters per (symbol, tf, regime), stable across scales):
       ```
       n_nd = X_regime_nd.shape[1]
       if n_nd >= 2:
           corr = np.corrcoef(X_regime_nd.T)            # [n_nd, n_nd]
           corr = np.nan_to_num(corr, nan=0.0)          # guard constant-after-degenerate edge cases
           dist = np.sqrt(0.5 * (1.0 - np.clip(corr, -1.0, 1.0)))
           np.fill_diagonal(dist, 0.0)
           Z = linkage(squareform(dist, checks=False), method="average")
           # cluster_max_corr is a CORRELATION threshold; convert to distance threshold
           dist_threshold = np.sqrt(0.5 * (1.0 - cluster_max_corr))
           cluster_ids_nd = fcluster(Z, t=dist_threshold, criterion="distance")  # 1-based ints, len n_nd
       else:
           cluster_ids_nd = np.ones(n_nd, dtype=int)
       ```
       Expand `cluster_ids_nd` back to full feature space with a sentinel for degenerate features:
       build `cluster_id_full` (len n_features) where degenerate positions are None/0 and non-degenerate
       positions take their cluster id. Use the same `_expand`-style mapping already used for ic_full.

    4. Representative selection: a representative must be chosen using IC magnitude, but IC is computed
       per-scale. Decide representatives at the point BH-FDR is collected. The existing code accumulates
       `pvals_flat` / `pval_result_idxs` across all scales+regimes for one (symbol, tf), then runs
       `multipletests` once (lines ~817-824). Change this so that within each (regime, scale, cluster) group,
       only the feature with the largest `abs(ic_value)` enters `pvals_flat`:
       - When appending each result dict, also record its `cluster_id` (from `cluster_id_full[feat_idx]`),
         its `abs(ic_value)`, and its result_idx, keyed by `(regime_label, lookahead_bars, cluster_id)`.
       - After the regime/scale loops, for each group pick the representative = max abs(ic_value); append ONLY
         the representative's p-value to `pvals_flat` (with its result_idx in `pval_result_idxs`). For
         non-representatives in the group, set `bh_adjusted_p=None` and `passes_fdr=False` directly on their
         result dict.
       - Keep the existing degenerate handling (p_val NaN -> passes_fdr False) — degenerate features have no
         cluster and never become representatives.
       Then run the existing `multipletests(pvals_flat, ...)` on representatives only and write
       `bh_adjusted_p`/`passes_fdr` back via `pval_result_idxs` exactly as today.

       IMPORTANT: do not change the per-scale IC / CI / walk-forward / Sharpe computation. Clustering only
       changes (a) which features enter the BH-FDR batch and (b) the cluster_id written on each row.

    5. Write `cluster_id` into each result dict (replace the `None` placeholder from Task 1) using the integer
       from `cluster_id_full[feat_idx]` (cast to int, or None for degenerate). cluster_id is local to the run
       (Pitfall 4) — that is acceptable and documented in the migration comment.

    Add a structlog info line per (symbol, tf) summarizing clustering, e.g.
    `_logger.info("ic_engine.clustering", symbol=symbol, tf=tf, regime=regime_label, n_clusters=int(cluster_ids_nd.max()), n_features=n_nd)`.
    Do NOT use the reserved `event=` kwarg.
  </action>
  <verify>
    - `.venv/bin/ruff check services/ic_engine.py` — clean
    - `grep -n "fcluster\|linkage\|squareform" services/ic_engine.py` confirms scipy imports + use
    - `grep -n "cluster_max_corr" services/ic_engine.py` confirms APR-backed threshold (no literal 0.70 in loop)
    - Run unit test below
    - After a scoped ic_engine run (1 symbol, post-migration): `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -tAc "SELECT count(DISTINCT cluster_id) FROM feature_ic_scores WHERE cluster_id IS NOT NULL"` > 1
  </verify>
  <acceptance_criteria>
    - Source: scipy `linkage`, `fcluster`, `squareform` imported and used to cluster `X_regime_nd`.
    - Source: cluster threshold read from `apr["cluster_max_corr"]` (APR `alpha.ic.cluster_max_corr`); no numeric correlation literal in the clustering block.
    - Source: only one feature per `(regime, lookahead, cluster_id)` group (max abs ic_value) is appended to `pvals_flat`; non-representatives get `passes_fdr=False`, `bh_adjusted_p=None`.
    - Source: each result dict's `cluster_id` is set from the per-regime cluster assignment.
    - Behavior: a unit test `tests/unit/test_ic_engine_clustering.py` builds a synthetic X with two perfectly-correlated feature pairs plus one independent feature, runs the clustering snippet (extract it into a small pure helper `_cluster_features(X_nd, cluster_max_corr) -> np.ndarray` so it is unit-testable), and asserts: correlated pairs share a cluster id, the independent feature is in its own cluster, and total clusters == 3.
    - Test: `.venv/bin/pytest tests/unit/test_ic_engine_clustering.py -q` passes.
  </acceptance_criteria>
  <done>BH-FDR runs on one representative per correlated cluster; every IC row carries its cluster_id; the correlation threshold is APR-tunable.</done>
</task>

</tasks>

<verification>
- `.venv/bin/ruff check services/ic_engine.py` — clean
- `.venv/bin/pytest tests/unit/test_ic_engine_clustering.py -q` — pass
- `.venv/bin/pytest tests/unit/ -q` — no new failures
- Scoped run populates feature_ic_scores.cluster_id with >1 distinct cluster
</verification>

<success_criteria>
- Hierarchical clustering applied per (symbol, tf, regime) using alpha.ic.cluster_max_corr
- Only cluster representatives receive BH-FDR; members carry cluster_id and passes_fdr=false
- cluster_id column populated on every new IC row
</success_criteria>

<output>
After completion, create `.planning/phases/140-ic-engine-correctness/140-P2-SUMMARY.md`
</output>
