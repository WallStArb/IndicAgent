---
phase: 140
reviewers: [codex]
reviewed_at: 2026-06-25T00:00:00Z
plans_reviewed: [140-P0-PLAN.md, 140-P1-PLAN.md, 140-P2-PLAN.md, 140-P3-PLAN.md]
notes: |
  Antigravity: failed (known stdout drop bug — empty output).
  Ollama (qwen3.5:4b): failed (v1/chat/completions API unresponsive despite /v1/models up).
---

# Cross-AI Plan Review — Phase 140

## Codex Review

**Summary**

The plan is strong overall: it targets the right failure modes, keeps the P0 label/IC fixes separated from the later methodology work, and uses APR-backed thresholds instead of hardcoding. The sequencing is mostly sound, but there are a few correctness and scoping ambiguities that matter a lot in a quantitative pipeline: the meta-FDR denominator is probably too broad, the clustering threshold semantics are slightly overstated, and the `training_window_end` freeze needs a precise capture point plus timezone discipline to avoid subtle PK drift.

**Strengths**

- The dependency structure is sensible: P0 fixes unblock label correctness, P1 migration unblocks both P2 and P3, and the later waves build on that foundation.
- The plan correctly treats the stride bug and overnight-gap contamination as hard correctness blockers, not tuning issues.
- Per-scale subsampling is the right architectural fix, and moving degenerate detection to full regime data is a good call.
- The ET date gate for intraday forward returns is the minimal change that addresses the stated overnight contamination without changing daily behavior.
- The migration plan keeps all numeric thresholds in APR, which matches the repo's parameter-registry rules.
- The clustering work is scoped to a single run and avoids treating cluster IDs as global semantics, which is the right stance.
- The tests are focused on observable behavior and SQL shape, which is appropriate for these changes.
- The plan avoids mixing compute, persistence, and transport concerns.

**Concerns**

- **HIGH:** The P3 meta-FDR query likely uses the wrong universe. Filtering only `is_pooled = false AND reliable = true` will count rows that the ensemble never consumes if they also fail walk-forward or have null `ic_sharpe`. That can suppress pass rates artificially and exclude otherwise valid features. The denominator should match the actual ensemble eligibility universe more closely.
- **HIGH:** The P2 clustering wording is too strong. `fcluster(..., criterion='distance')` on a linkage tree does not guarantee that every pair inside a cluster has correlation above the threshold. It is a dendrogram distance cutoff, not a strict pairwise-correlation guarantee. The plan should describe that precisely to avoid false assumptions downstream.
- **HIGH:** `datetime.fromisoformat(args.training_window_end)` without explicit timezone normalization risks naive or non-UTC input. That conflicts with the repo's UTC-only invariant and can silently shift the boundary used for PK stability.
- **MEDIUM:** The pipeline note for `training_window_end` is operationally underspecified. Capturing `MAX(bar_ts)` at literal pipeline start is wrong if step 1 populates `feature_vectors`; the freeze point should be after feature factory finishes and before both forward-return and IC steps consume the value.
- **MEDIUM:** The low-coverage warning in P3 is heuristic and may miss the most important failure mode: a partial run where all features are uniformly under-covered. Comparing `min_cells` vs `max_cells` does not tell you whether the run is materially incomplete relative to the expected universe.
- **MEDIUM:** The P0/P2 test strategy is a bit shallow. The stride test checks arithmetic, but not the shared degenerate-mask behavior or the `_compute_ic_rolling_metrics` call contract. The forward-return test checks SQL strings, but not an actual ET boundary case.
- **MEDIUM:** A 50% meta-FDR gate is quite strict for a cross-asset, cross-TF corpus. It will favor broad, stable factors and may suppress useful niche features that are genuinely strong in a subset of symbols or timeframes.
- **LOW:** The migration plan is ambiguous about audit semantics for `config_state`. It mentions `updated_at` and possibly `config_history`, but the repo's existing migrations often use `version = version + 1`. That needs to be pinned to the actual schema/convention before writing the migration.
- **LOW:** The intraday `complete_{scale}` fix is date-based, which is correct for the stated overnight-gap bug, but it does not distinguish RTH vs extended-hours within the same ET date. If the source series includes ETH bars, a future refinement may still be needed.

**Suggestions**

- Tighten the P3 aggregation query to match the actual ensemble selection universe, or explicitly justify why `reliable=true` alone is the right denominator.
- Add a stronger meta-FDR coverage warning based on the expected `(symbol, tf)` universe, not only min/max cells.
- Normalize `training_window_end` to UTC explicitly and reject naive datetimes.
- Move the pipeline freeze point for `training_window_end` to after step 1 completes, then pass the same value into both forward-return and IC steps if you want the corpus to be internally consistent.
- Add one test that exercises an actual ET boundary, ideally near midnight or DST transition, rather than only checking SQL text.
- Add one regression test that asserts `non_degenerate_mask` is computed once on full regime data and reused across scales.
- In the clustering docs/comments, say "distance-threshold dendrogram clustering" rather than implying a hard pairwise-correlation guarantee.
- Revisit whether 0.50 is the right meta-gate default after measuring the empirical pass-rate distribution; 0.50 is defensible as a conservative starting point, but it is not obviously optimal.

**Risk Assessment**

**HIGH.**
This is a correctness-heavy change set in the core alpha pipeline. P0 affects the actual labels and the statistical power of IC estimates, P2 changes the multiple-testing procedure, and P3 changes which features are even eligible for ensemble weight. The plan is generally well-structured, but a mistake in the meta-FDR denominator or the timing of `training_window_end` would silently skew downstream alpha generation.

---

## Consensus Summary

Single reviewer (Codex). Antigravity and Ollama both failed.

### Agreed Strengths

- Wave ordering correct: P0 correctness blockers in wave 1, statistical methodology in wave 2
- APR compliance maintained throughout — no hardcoded thresholds in code
- Per-scale subsampling and degenerate mask on full regime data are the right architectural choices
- ET date gate is minimal and correct for the overnight gap problem

### Agreed Concerns

- **HIGH — meta-FDR denominator mismatch (P3):** The eligibility query `is_pooled=false AND reliable=true` likely includes rows the ensemble never consumes (also need walk-forward pass and non-null ic_sharpe). Wrong denominator silently suppresses valid features.
- **HIGH — clustering semantics overstated (P2):** `fcluster` with `criterion='distance'` is a dendrogram cutoff, not a pairwise-correlation guarantee. Code comments must say "distance-threshold" not "all pairs within cluster have corr > threshold."
- **HIGH — training_window_end UTC normalization (P0):** `datetime.fromisoformat()` accepts naive datetimes. Must reject naive input or force UTC — the repo's UTC invariant is non-negotiable.
- **MEDIUM — training_window_end freeze point (P0/corpus_pipeline_run.sh):** MAX(bar_ts) captured at pipeline start is wrong if step 1 (feature factory) still runs and adds bars. Freeze must happen after step 1 completes, then be passed to both forward_return_writer and ic_engine.
- **MEDIUM — 50% meta-gate may be too aggressive:** Will suppress niche but genuinely predictive features that are strong in a subset of symbols/TFs. Revisit after measuring empirical pass-rate distribution.

### Divergent Views

N/A — single reviewer.
