---
phase: 151
reviewers: [codex]
reviewed_at: 2026-07-24T23:57:57.000Z
plans_reviewed:
  - 151-01-PLAN.md
  - 151-02-PLAN.md
  - 151-03-PLAN.md
  - 151-04-PLAN.md
  - 151-05-PLAN.md
  - 151-06-PLAN.md
  - 151-07-PLAN.md
  - 151-08-PLAN.md
---

# Cross-AI Plan Review — Phase 151

**Reviewer selection:** `review.default_reviewers` is configured to `["codex"]` in this project — only Codex was invoked (no `--all`/individual-reviewer flag was passed). Antigravity (`agy`) is also installed but not in the default set. Claude was skipped per this workflow's own self-identification rule (running inside Claude Code CLI).

## Codex Review

**Summary**

This is a strong, execution-oriented plan set. It decomposes Phase 151 into small enough waves to keep schema changes, compute wiring, migrations, tests, and measurement scripts aligned, and it does a good job of surfacing known asymmetries instead of pretending they do not exist. The main risks are operational, not conceptual: the plans are highly coupled across many files and migrations, several steps depend on long-running recomputes, and one live-path gap is explicitly deferred rather than fixed. Rated as coherent and largely complete, but not low-risk.

**Strengths**
- Each wave has a concrete output contract: fields, migrations, APR keys, tests, and acceptance checks are all enumerated.
- The dependency chain is mostly sensible, with the schema/config work landing before recompute and IC-screening.
- The plans reuse existing pipeline primitives instead of inventing parallel architecture, which reduces implementation surface.
- Statistical methodology is treated seriously: BH-FDR pools, partial IC, sparse-flag bootstraps, and explicit allow-lists are all called out.
- The plans explicitly record live/batch asymmetries and known gaps instead of burying them.
- Migration numbering, registry/dataclass alignment, and placeholder-count checks are all guarded — exactly the right class of invariant for this codebase.
- The interaction layer is constrained with a hard cap and permanent regression tests, the right way to keep the BH-FDR pool from degenerating.

**Concerns**
- **HIGH** — `151-07`'s `--recompute` design is not fully failure-atomic for a partition rebuild. A delete-then-batch-insert path can still leave a partition partially repopulated if the job dies after the first commit but before all batches complete.
- **HIGH** — `151-04` explicitly leaves `FeatureCache.update_cross_asset()` broken on the live path, with the new and existing cross-asset fields frozen at `0.0`. Acceptable for batch IC measurement, but a serious correctness gap for any downstream live use.
- **HIGH** — The recompute and sweep waves depend on long-running multi-hour jobs plus exact restart hygiene — operationally fragile, especially with orphaned workers and shared DB writers.
- **MEDIUM** — `151-05` and `151-08` rely on sparse or low-coverage objects (`ret_div_1m_5m`, `opex_flag`, `quad_witching_flag`) where statistical power is structurally weak. Plans acknowledge this, but control-matching and gating rules are still somewhat degree-of-freedom heavy.
- **MEDIUM** — `151-02` seeds `alpha.ensemble.cluster_regime_conditioned=true` by default, which may materially increase `ic_engine` wall-clock across all routed symbols. Needs a clearer runtime budget and rollback strategy if the extra pass proves too expensive.
- **MEDIUM** — Several waves depend on tuple-shaped payloads (`CrossAssetValues`, `CtfValues`) and a growing number of positional outputs — brittle and easy to break with a small field-order mistake.
- **MEDIUM** — `151-06`'s finite-guard choice for compound products (`nan_to_num(..., posinf=0.0, neginf=0.0)`) can silently collapse extreme but valid values to zero, hiding tail behavior rather than merely protecting against overflow.
- **LOW** — `151-01`'s persistence-slice instructions are slightly confusing about when the new slice is added. Intent is recoverable, but wording is easy to misread during implementation.
- **LOW** — The plan set is very large and tightly sequenced. Even with good tests, a small naming or count mismatch can cascade into later waves.

**Suggestions**
- Move tuple-like payloads into a shared module or dataclass so `CrossAssetValues` and `CtfValues` stop relying on positional unpacking conventions.
- Make `--recompute` resumable per partition, or at least add a partition-completion manifest so a crash cannot leave a partially rebuilt corpus with no easy recovery path.
- Add explicit live-vs-batch parity assertions for the known batch-only fields so `0.0`/`None` placeholders cannot be mistaken for real signals.
- Tighten the sparse-event methodology into a small reusable helper with pre-registered control matching and minimum-episode checks, so analysis doesn't drift across flags and timeframes.
- Consider making the live-path cross-asset gap a blocker for any phase that expects live feature consumers, even if batch IC work can proceed meanwhile.
- Add a runtime-switch or budget check around the extra `symbol_hmm` pass before seeding `cluster_regime_conditioned=true` in production.
- For compound features, prefer explicit clipping or a documented numerical range proof over silent zeroing when protecting against overflow.

**Risk Assessment**

**HIGH.** The design itself is solid, but the execution footprint is large and tightly coupled: five migrations, a corpus recompute, two IC sweeps, several schema/config contract changes, and a deliberate live-path asymmetry. Testing and invariant checks reduce risk materially, but the recompute path and live-path gap are both serious enough not to classify this as medium-risk.

---

## Consensus Summary

Single-reviewer pass (Codex only, per `review.default_reviewers` config) — no cross-reviewer agreement/divergence to synthesize. Codex's own findings, ranked:

### Top concerns (Codex, HIGH severity)
1. `151-07`'s `--recompute` mode isn't failure-atomic per partition — a crash mid-run can leave a partially rebuilt corpus with no resumability.
2. `151-04` knowingly ships a live-path correctness gap (`FeatureCache.update_cross_asset()` frozen at `0.0`) — already flagged by the planner as "filed as a todo, not fixed inline," but Codex independently rates it HIGH rather than deferrable.
3. The overall execution footprint (5 migrations, multi-hour recompute, 2 IC sweeps) is operationally fragile, consistent with this project's own documented orphan-worker/OOM history for similar-shaped jobs.

### Notable divergence from the planner's own self-assessment
The planner's own summary (recorded in ROADMAP.md's "Planning-time decisions recorded") treated the `FeatureCache.update_cross_asset()` live-path gap as a same-bug-class-as-todo-158 finding worth filing separately, not blocking. Codex explicitly disagrees, suggesting it should be treated as a phase-blocking issue for any phase that expects live feature consumers. Worth a direct decision before executing, not silently defaulting to the planner's original call.

To incorporate this feedback into the plans:
`/gsd-plan-phase 151 --reviews`
