# Phase 173: Broadcast Feature Significance Correction - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-21
**Phase:** 173-Broadcast Feature Significance Correction
**Areas discussed:** Cell scope (broadcast feature population), Aggregate-return construction,
Downstream integration

---

## Cell scope (broadcast feature population)

| Option | Description | Selected |
|--------|-------------|----------|
| All 23, retire CONTEXT_FEATURES' old path | One unified broadcast mechanism, no lingering second bug left in production; slightly larger diff | ✓ |
| Only the 20 uncovered features | Smaller diff now; leaves CONTEXT_FEATURES' correlated-multiple-testing bug unfixed as a separate future item | |

**User's choice:** All 23, retire CONTEXT_FEATURES' old path.
**Notes:** Direct pick, no follow-up needed.

---

## Aggregate-return construction

| Option | Description | Selected |
|--------|-------------|----------|
| Per-cell reuse, equal-weighted | Regime-conditional broadcast significance; zero new data infrastructure — reuses `_compute_one_cross_sectional_cell`'s already-fetched `returns_mat` for the regime_group's own peer symbols | ✓ |
| Single global whole-universe series | One broadcast significance number per feature/tf, decoupled from regime stratification; needs a new aggregate-return table/query | |

**User's choice:** Per-cell reuse, equal-weighted (arrived at via explicit user direction to
re-derive the decision under Renaissance-council rigor rather than accept the presented
"Recommended" label at face value).
**Notes:** Stress-tested rather than rubber-stamped. Key points from that pass:
- A global aggregate would collapse real asset-class heterogeneity (vix_z plausibly predicts
  bonds differently than equities) into one number — the one unconditional test in a system
  where every other measurement is regime-stratified.
- Per-cell reuse means the SAME feature (e.g. vix_z) gets tested once per (regime_group, tf,
  regime_label) against DIFFERENT Y (that group's own aggregate return) — these are genuinely
  distinct hypotheses, not pseudo-replication of each other.
- Small regime/tf cells will more often hit the `min_reliable_n` floor and get skipped than the
  per-symbol path does (N divided by ~n_symbols_in_group) — judged correct behavior, not a flaw:
  a thin stratum SHOULD report insufficient N rather than inflated significance.
- Equal-weighted (not cap-weighted): no market-cap/weighting data exists anywhere in this
  codebase for the ETF/futures/FX universe; building that now to satisfy an untested weighting
  hypothesis would violate "empirical over theoretical." Revisit only if evidence later shows it
  matters.

---

## Downstream integration

| Option | Description | Selected |
|--------|-------------|----------|
| Same table, same FDR family | passes_fdr/concept_registry/ensemble_trainer eligibility all keep working unmodified; smallest downstream blast radius | ✓ |
| Separate table/FDR family | Cleaner conceptual separation but requires updating every downstream reader to know about a second source | |

**User's choice:** Same table, same FDR family — sharpened further during the rigor pass.
**Notes:** Considered adding a new `is_broadcast` column to `feature_ic_scores` to disambiguate
broadcast rows from ordinary per-symbol rows at a glance, but rejected it: that would create a
second place to keep a classification in sync. `concept_registry.metadata` is already the
designated single source of truth for this classification (2026-08-11 decision); resolve
broadcast-ness by joining it at read time instead of duplicating the flag. Row shape reuses the
existing `symbol='POOLED'`/`is_pooled=True` sentinel convention exactly, since D-03 computes
broadcast rows at the identical `(regime_group, tf, regime_label)` granularity as today's
cross-sectional cells.

---

## Claude's Discretion

- Exact mechanics of the new broadcast-variance detector that writes `concept_registry.metadata`
  (oneshot script vs. wired into an existing batch pass; file location).
- Whether `_compute_one_broadcast_cell` is implemented as a fully separate function or a thin
  wrapper around `_compute_one_cross_sectional_cell` with a pre-collapsed input — the kernel
  reuse and the "never touch the chunked accumulator" constraint are locked, the exact function
  boundary is not.
- Test coverage shape and unit test organization.

## Deferred Ideas

Todo-matcher tool returned ~104 near-universal keyword matches (noise — generic term overlap).
Manually reviewed a handful of plausible titles instead; none folded, each independent:
038 (PCA/collinearity diagnostic), 039 (tag-stratified IC population check, different path),
135 (regime grid shape validation, different question), 186 (a different combiner script's
bootstrap approximation), 214 (much larger ic_engine/ensemble_ic_engine compute-core refactor),
227 (bootstrap early-stop optimization, orthogonal to this phase either way).
