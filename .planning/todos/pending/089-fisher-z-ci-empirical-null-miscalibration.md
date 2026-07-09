# 089 — Fisher-z analytic CI is empirically miscalibrated: 38% SUSPECT rate across most strata

**Source:** L4-2 empirical null calibration diagnostic, run 2026-07-09. Supersedes the L4-2 scope
of todo 071 (see `docs/research/measurement-ic-engine.md`'s Measurement Gaps table, new row dated
2026-07-09, for the durable record). Evidence trail: `scripts/ops/alpha/ops_ic_null_calibration.py`,
commits `93824f57` (circular-shift null kernel function), `20f639d4` (pooled-sentinel sampling
fix), `640050f1` (the n_valid-vs-pre-filter-count comparison fix that produced the trustworthy
final run).

## The finding, precisely

Circular-shift permutation (200 resamples/cell, seed=42) was run against a 66-cell stratified
sample of `feature_ic_scores` at the CI/FDR gate boundary. Of the 66 sampled cells, 29 were
evaluated (37 skipped: insufficient N after completeness filtering, unmapped lookahead scales, or
genuine remaining corpus drift — the earlier "corpus drift" explanation for most skips was itself
found to be wrong by code review and fixed in `640050f1`; residual skips are smaller and more
mundane now).

**11 of 29 evaluated cells (38%) flagged SUSPECT** (`se_ratio > 1.2`, meaning the empirical null's
standard error exceeds the analytic Fisher-z prediction by more than 20%).

SUSPECT cells span **4 of 8 sampled `(tf, is_pooled)` strata**:
- `tf=5m, is_pooled=false`: 2 SUSPECT
- `tf=15m, is_pooled=false`: 1 SUSPECT
- `tf=1d, is_pooled=false`: 3 SUSPECT
- `tf=1d, is_pooled=true`: 5 SUSPECT

This is **not** confined to one corner of the design space (e.g. not just the already-known-thin
`1d` timeframe) — `5m` and `15m`, which have abundant N (tens of thousands of observations per
cell), also show SUSPECT cells.

Several SUSPECT cells show severe non-normality alongside the SE gap, not just a wider-than-
expected variance: `hurst`/BIL/1d (`se_ratio=2.242`, Shapiro `p=0.0000`), `ret_autocorr_1`/VNQ/5m
(`se_ratio=2.200`, Shapiro `p=0.0000`). This suggests the Fisher-z CLT-normality assumption itself
may be breaking down for some features, not only the SE magnitude being off.

Full cell-by-cell table: `.superpowers/sdd/task-2-live-run-output.md` (this session's captured
stdout, the twice-corrected authoritative run — do not use the two earlier buggy runs referenced
inside that file for numbers).

## Affected mechanism

`_fisher_z_ci` in `src/intelligence/statistics/ic_math.py` — the analytic confidence interval this
diagnostic tested against the empirical permutation null.

## Downstream exposure

`_fisher_z_ci` is the exact mechanism behind `ic_ci_lower`, which gates:
- BH-FDR pass/fail (`passes_fdr` in `feature_ic_scores`)
- Walk-forward validation
- The **EIC-04 hard gate** that was just used to unblock Phase 142B (PASS at a razor-thin
  35/1585 = 2.21%, a threshold recalibrated from 0.60 based on a p-value histogram interpretation
  that itself assumes this same CI machinery is trustworthy)

A 38% SUSPECT rate spanning most strata, including high-N timeframes, is evidence the analytic CI
may be systematically too narrow — which would mean some currently-passing gates (individual
features, ensemble variants E1/E2, and possibly EIC-04 itself) are more marginal than their
reported p-values suggest. This todo states that connection factually; it does not conclude
whether EIC-04/Phase 142B's unblocking should be reconsidered — that is a decision for the project
owner, not resolved here.

## Proposed next steps

1. **A full-corpus confirmation run may be warranted before acting**, given the stakes (this
   touches every CI-gated promotion in the stack). The 66-cell stratified sample is a diagnostic,
   not an exhaustive census — before reopening bootstrap machinery, consider whether a broader run
   (all strata, more cells per stratum, or the full `feature_ic_scores` table) changes the picture
   materially, or just tightens the same conclusion.
2. **Reopening circular block bootstrap in the kernel is the natural fix per the original design
   doc** (`docs/plans/2026-07-09-ic-null-calibration-design.md`), but treat this as the leading
   candidate, not a foregone conclusion, until step 1's confirmation (or the project owner's
   explicit call) settles it. If pursued: implement circular block bootstrap in `ic_math.py`,
   giving the currently-dead `alpha.ic.bootstrap_seed`, `alpha.ic.bootstrap_resamples`, and
   `alpha.ic.bootstrap_block_size.{5m,15m,1h,1d}` APR keys (migrations 161, 165, 177; zero readers
   since circular block bootstrap was removed from `ic_engine.py`) their first real reader.
3. Do **not** delete the `alpha.ic.bootstrap_*` APR keys — this todo is the reason they need to
   stay live pending the decision above.
4. Whatever is decided, record the decision explicitly in the methodology-change-ledger (per this
   project's existing pre-commitment convention for gate-affecting decisions) before any gate
   threshold or promotion status is touched as a consequence.

**Priority:** high — this bears directly on whether currently-passing gates (feature promotion,
BH-FDR, EIC-04) are as reliable as their reported p-values claim. Not urgent to execute
immediately, but should not sit indefinitely given what it touches.
