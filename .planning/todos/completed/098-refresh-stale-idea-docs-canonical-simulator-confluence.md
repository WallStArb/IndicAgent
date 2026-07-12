---
status: completed
priority: P2
created: 2026-07-11
completed: 2026-07-12
---

# Refresh two stale idea docs against shipped work

**Context:** 2026-07-11 catalog.md audit (see `docs/research/catalog.md` v1.2 changelog)
verified content drift, not just link rot, in two Cluster 1 docs.

## 1. `docs/research/platform-canonical-simulator.md` — critical priority, do first

Last Fable-reviewed 2026-07-03. Still poses open questions as unresolved that were actually
settled when Phase 142B executed 2026-07-10:
- "gross or net of cost?" (SHADOW-REVIEW's Sharpe/drawdown criteria)
- "does `alpha_frames` get a `corpus_run_id`/`weight_epoch` column at 142B's P1 migration?"

`SHADOW-REVIEW.md` is already frozen and `alpha_frames`/`CounterfactualTracker` already shipped
(migrations 214+215). Need a Fable pass reconciling this doc's design against what was actually
built, not what was proposed.

## 2. `docs/research/intel-confluence-detection-persistence-layer.md` — high priority

Last Fable-reviewed 2026-07-03 — oldest review date in Cluster 1, predates Phase 143's
`feature_registry` lifecycle state machine that confluences (as "governed predictors") are
supposed to plug into. Needs re-verification against the executed lifecycle mechanics.

## Deliberately NOT included here (wait)

`measurement-governance-monitor.md` (IntegrityMonitor) and `measurement-ic-engine.md` were both
reviewed 2026-07-06 against *planned* Phase 143 and are entangled with Phase 143.1's eligibility
redesign (todo 094, sign-symmetric ensemble eligibility) which hasn't executed yet. Refreshing
them now would go stale again within days — bundle one combined refresh after 143.1 lands
instead of doing it twice.

**How to apply:** dispatch as a Fable review (Agent tool, `model: fable`) when session budget
allows — this was deferred specifically because a Fable pass is context-expensive and the
originating session had ~9% left.

## Resolution (2026-07-12)

Both items dispatched as parallel Fable agents and completed.

1. **Canonical Simulator** (v2 → v2.1): both open questions settled — gross/net resolved exactly
   as the doc recommended (SHADOW-REVIEW gates on gross, net is reporting-only); `corpus_run_id`/
   `weight_epoch` confirmed added by migration 214, citing this doc by name. Real drift caught and
   flagged (not papered over): the cost reporting column shipped as a copy-through snapshot, not a
   live cost-kernel computation — judged defensible but noted two consumers still needing fresh
   computation. Priority downgraded critical → high; flagged that the ledger currently measures a
   99.99% long-only book pending todo 094.
2. **Confluence Persistence Layer**: full re-verification against Phase 143's executed lifecycle
   mechanics found the doc's stated promotion bar (`n >= 100 AND bootstrap_ci_lower > 0`) was the
   dead v2.x `shadow_registry` mechanic, not the live counter-based recovery gate (2 consecutive
   passing runs AND 2000 independent observations) — corrected. Also updated: gate-6 sign-asymmetry
   caveat now reflects that Phase 143.1's sign-symmetric predicate has already shipped (behind
   `alpha.ensemble.sign_symmetric`, currently `false` in live APR); decay section now notes the
   materiality gate and regime-shift hold the live hook applies; retracted an incorrect claim about
   automated retirement (`deprecated` is operator-only); fixed a governance doc pointer typo.

`docs/research/catalog.md` updated with both new review dates/summaries.
