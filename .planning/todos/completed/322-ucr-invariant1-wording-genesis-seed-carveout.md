# 322 - CLAUDE.md's UCR Invariant 1 wording doesn't acknowledge the established migration genesis-seed pattern

**Filed:** 2026-08-15
**Source:** `/review` (code-review skill) during todo 320's (Velocity Primitives Extension)
cleanup pass.

## What

CLAUDE.md's Unified Concept Registry section states: *"the ONLY code path that flips `status` is
`ConceptRegistryService` (`src/intelligence/concept_registry_service.py`) — no LLM, no proposer
override, ever (Invariant 1)."*

Migration 316 (todo 320) seeds 6 new `concept_registry` rows with `status='active'` directly via
raw SQL INSERT, bypassing `ConceptRegistryService` entirely. This is not a new deviation --
verified against migrations 288, 289, 290, 291 (all four insert `status` sourced from
`feature_registry.status`, which was itself hardcoded `'active'` at INSERT time before migration
311 dropped that table). Every tier-`0_atomic` feature primitive this codebase has ever added has
been genesis-seeded as `'active'` via a raw migration, never through `ConceptRegistryService`.

## Why this is a doc problem, not a code problem

The established, repeated (5 migrations now) pattern makes sense on its own terms: a migration
adding a new atomic primitive to `FeatureVector` is schema-definition-time DDL, not a runtime
lifecycle transition (candidate promoted to active based on evidence, or demoted based on decay) --
that's what `ConceptRegistryService` actually governs, per its own domain (`ensemble_strategy`'s
`record_comparison_outcome()`, `feature` domain's `ic_engine.py` post-run hook). Invariant 1's
current wording doesn't distinguish "genesis seed a new concept row at schema-add time" from
"flip an existing concept's lifecycle status based on evidence" -- it reads as covering both, but
5 migrations' worth of practice treats only the latter as governed.

## Fix

Tighten Invariant 1's wording in CLAUDE.md to explicitly carve out migration-time genesis seeding
(a new `concept_registry` row's initial `status` at INSERT, set directly by the migration that
adds the corresponding `FeatureVector` field) from the "ONLY `ConceptRegistryService` flips
status" rule (which governs subsequent lifecycle transitions on an existing row). Purely a
documentation-precision fix -- no code or migration behavior change; the practice is already
consistent across 5 migrations, only the stated invariant lags it.

## Closed 2026-08-21

Fixed both places Invariant 1 is stated, not just CLAUDE.md's condensed version -- the todo's
own fix note only named CLAUDE.md, but CLAUDE.md's UCR paragraph explicitly points to
`docs/foundation/unified-concept-registry.md` as the "Full spec," and that doc restates
Invariant 1 as item 1 of "The Nine Invariants." Leaving one fixed and the other stale would
have just moved the same doc-drift problem down one level instead of closing it.

Both now read: the ONLY code path that flips an **existing** concept's `status` is
`ConceptRegistryService` -- exempt: migration-time genesis seeding, which is
schema-definition-time DDL establishing a new concept's existence, not a runtime lifecycle
transition on an existing row.

Re-verified the "5 migrations" claim directly before citing it (not trusted from the filing
text alone) -- confirmed 288/289/290/291/316 all `INSERT INTO concept_registry ... status,
... VALUES (..., 'active', ...)` via direct grep + read of each file. 316 (todo 320) seeds
directly since `feature_registry` no longer exists (migration 311); 288/289/290/291 predate
that and sourced `status` from `feature_registry.status`, itself hardcoded `'active'` at
INSERT time -- both variants are the same genesis-seed pattern, worth noting in the full-spec
doc's version since it's the one making the historical claim.

No code or migration behavior change, as scoped -- documentation-precision fix only.
