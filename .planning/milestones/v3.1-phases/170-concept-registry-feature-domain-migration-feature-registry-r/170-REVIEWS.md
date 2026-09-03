---
phase: 170
reviewers: [codex]
reviewed_at: 2026-08-04T13:47:13Z
plans_reviewed: [170-01-PLAN.md, 170-02-PLAN.md, 170-03-PLAN.md, 170-04-PLAN.md, 170-05-PLAN.md, 170-06-PLAN.md, 170-07-PLAN.md, 170-08-PLAN.md]
---

# Cross-AI Plan Review — Phase 170

Only `codex` was invoked, per `review.default_reviewers` config (`["codex"]`). `antigravity`,
`claude`, and `ollama` were detected as available on this system but not included, since no
`--all` or individual reviewer flag was passed and the configured default scopes to codex only.

## Codex Review

**Summary**
The phase plan is unusually rigorous: it sequences schema, seed, service hardening, rehearsal, shadow-mode dual write, reader cutover, and irreversible drop in a way that makes the one-way door explicit rather than accidental. The strongest part is the use of parity verification and gated progression, which is the right shape for a live governance migration. The main risk is not missing scaffolding, but that the later waves depend on real corpus data and on proof of an end-to-end dual-write run that may not yet exist, so the phase is technically well-structured but operationally likely to stall unless the upstream data gate is satisfied.

**Strengths**
- Clear wave ordering: schema first, then data seed, then sync service, then rehearsal, then dual-write, then reader cutover, then DROP.
- Good use of hard gates and explicit abort conditions, especially for the irreversible Plan 08.
- The plans distinguish between structural parity, behavioral parity, and observational evidence, which is exactly what this migration needs.
- The migration plans are self-checking: replay assertions, row-count parity, and verifier scripts reduce reliance on manual review.
- The shadow-mode approach in Plan 06 is the right mitigation for a split-brain cutover.
- The plan explicitly fixes two subtle audit bugs in the cascade trigger design, not just the mechanical table shape.
- The docs/todo closure work is scoped as follow-up rather than mixed into the critical-path runtime changes.

**Concerns**
- **HIGH**: Plan 05 onward is currently gated on `alpha_ensemble_ic` having real rows, and the project context says it is `0` as of 2026-08-04. That means the phase is effectively blocked after Plan 04 until the corpus rebuild lands, so the roadmap should be treated as incomplete until that upstream dependency is satisfied.
- **HIGH**: Plan 08's evidence gate can still be vacuous if `decay_cells_flagged` is not guaranteed to emit on every lifecycle-hook execution. If that metric can be absent even when the hook runs, zero divergences plus zero recorded runs could still accidentally authorize the DROP.
- **HIGH**: The irreversible DROP depends on the parity verifier and shadow-mode behavior staying perfectly aligned across multiple files. That is correct in principle, but it creates a large blast radius if any one of the later repoints drifts from the others.
- **MEDIUM**: Plan 03's replay logic depends on the exact historical genesis shape from migration 225. The plan says to mirror it exactly, but it would be safer if the migration or verifier cited the precise source rows or SQL pattern more explicitly so there is no room for an incorrect assumption about `from_status` or timestamp semantics.
- **MEDIUM**: Plan 07 changes the lineage query from array order to alphabetical `array_agg(... ORDER BY p.name)`. The plan correctly notes that order may not be load-bearing, but if any downstream consumer hashes, caches, or serializes the parent list, this could subtly alter behavior unless order-insensitivity is proven end to end.
- **MEDIUM**: The new `concept_parent` cycle guard is sound in spirit, but the plan only explicitly tests insert-time self-cycles and a general ancestor cycle. It would be wise to confirm update-path behavior and concurrent edge insertion behavior, since recursive guards can be fragile under real write pressure.
- **LOW**: Several acceptance checks rely on source grep counts or string presence. Those are useful guardrails, but they should not replace behavioral assertions, especially on the async registry service and the dual-write comparison path.

**Suggestions**
- Add one explicit "evidence of a completed lifecycle-hook run" artifact for Plan 08 that is independent of `decay_cells_flagged`, or document why that metric is guaranteed to be emitted on every dual-write run.
- Make the Plan 03 replay mapping cite the exact migration 225 seed SQL or captured rows in the migration header, not just a verbal instruction to "mirror exactly."
- For Plan 07's parent ordering change, either preserve original order with ordinality or add a test proving the downstream consumer is order-insensitive.
- Add at least one concurrency-oriented test around the `concept_parent` cycle guard or the sync lifecycle path, since the phase is explicitly about live governance behavior under write pressure.
- Prefer behavioral tests over source-text checks where possible, especially for the FDR guard and the dual-write divergence assertions.
- Treat the blocked data gate in Plan 05 as a first-class phase status, not just an implementation detail, so there is no ambiguity about why the later waves are not yet executable.

**Risk Assessment**
**HIGH**

The plan quality is good, but the phase is still high risk because it touches live governance state, introduces a new permanent schema shape, performs a one-way data migration, and ends with destructive table drops. The gating is thoughtful and the sequencing is strong, but the dependency on real corpus rows and on a successful shadow-mode rehearsal means the phase is operationally fragile until those upstream conditions are actually met.

---

## Consensus Summary

Single reviewer (codex only, per config) — no cross-model consensus to synthesize. Treat all
findings above as one independent opinion, not an agreed-upon multi-model verdict.

### Agreed Strengths
N/A — single reviewer.

### Agreed Concerns
N/A — single reviewer. Highest-severity individual findings, for visibility:
1. Plans 05-08 are gated on `alpha_ensemble_ic` having real rows (0 as of 2026-08-04) — already
   known and by design (see ROADMAP.md Phase 170's "Depends on" line), not a new finding, but
   codex is right that this should read as "phase blocked" rather than "phase planned," until
   the corpus rebuild lands.
2. Plan 08's DROP-authorizing evidence gate may be vacuous if `decay_cells_flagged` isn't
   guaranteed to emit on every lifecycle-hook run under dual write — a genuinely new finding,
   distinct from the "zero runs vs. zero divergences" distinction the plan already handles;
   this is about whether the *metric itself* is trustworthy as a completion signal.
3. Plan 07's `array_agg(... ORDER BY p.name)` reordering of parent lineage vs. the original
   array order could matter to any downstream consumer that hashes/caches/serializes the
   parent list — worth an explicit order-insensitivity check before relying on it.

### Divergent Views
N/A — single reviewer.
