---
status: completed
priority: P3
filed: 2026-07-12
completed: 2026-07-13
source: Phase 144 execution session — user request to unify docs related specifically to
  stratification/classification (security types, asset classes, attributes, regimes) under a
  consistent topic-clustered naming scheme
---

## Completed 2026-07-13

All 3 files renamed via `git mv` exactly per the mapping below (`regime-multi-regime-layer.md`
→ `stratification-dimension-unification.md`, `platform-security-classification-hierarchy.md`
→ `stratification-security-classification-hierarchy.md`, `data-instrument-tag-calibrator.md`
→ `stratification-instrument-tag-calibrator.md`). Repo-wide grep-and-sed sweep fixed every
cross-reference (14 + 6 + 8 hits across `docs/`, `.planning/ROADMAP.md`, phase context docs, and
sibling todos); verified zero remaining hits on any old filename outside this file itself.

**Extended beyond the original rename-only scope, same session:** the user separately asked
whether a unified umbrella doc existed for this cluster (analogous to
`concept-governance-registries.md`) — it didn't. Created
`docs/research/stratification-governance-registries.md` as a thin index (component table +
status + "why this stays thin" + relationship to Concept Governance Registries), added a
pointer from `concept-governance-registries.md`'s Related Docs, and added a catalog.md row.
Also added a short "prior art" note to `stratification-dimension-unification.md`'s Contract
section citing the archived I1-I7 `PatternPlugin`/`validate_tier()` tier-registration pattern as
validated precedent for the `StratificationDimension` `Protocol` shape — `concept-governance-
registries.md` had independently made the same connection when it considered and rejected
migrating `shadow_registry` in wholesale.

# Rename the stratification/classification doc cluster to a unified `stratification-*` prefix

## Scope (narrowed 2026-07-12 — see correction below)

An earlier draft of this todo proposed renaming all 29 `docs/research/*.md` files across
multiple clusters (governance, predictor, execution, etc.). User corrected: the actual ask is
narrower — only the docs specifically about **stratification/classification**: security types,
asset classes, instrument attributes, regimes. Not a full-directory sweep.

## Decision made (2026-07-12)

User chose **topic-clustered prefixes** (e.g. `stratification-*`) over two alternatives: keeping
the existing organic `platform-*` prefixes as-is, or skipping renaming entirely and only fixing
cross-references. No existing spec governs `docs/research/*.md` filenames —
`docs/foundation/naming-system.md` only covers code surfaces (Python classes, Kafka topics, DB
tables, source file names), not research-doc filenames.

## Cluster in scope

**`stratification-*`** (regime/classification providers — what state is the market/instrument in,
what kind of thing an instrument is):
- `regime-multi-regime-layer.md` → `stratification-dimension-unification.md` (the doc's own
  title is "StratificationDimension — A Unified Conditioning Layer")
- `platform-security-classification-hierarchy.md` → `stratification-security-classification-hierarchy.md`
- `data-instrument-tag-calibrator.md` → `stratification-instrument-tag-calibrator.md` (measures
  the tag *values* that `regime_group`/classification routing consume — same family)

**Explicitly NOT in scope** (adjacent but a different concern, don't fold in):
- `platform-controlled-vocabulary.md` — its own text says it has "deliberately zero relationship
  to instruments" (platform-wide symbolic codes, not instrument classification). Leave as `platform-*`.
- `platform-unified-concept-registry.md` / `concept-governance-registries.md` — governance/
  lifecycle layer for features+alpha+strategies broadly; only tangentially touches stratification
  via one `regime_model` domain (see todo 105/106). Not a rename target here.
- Everything else in `docs/research/` (CaseSubstrate, confluence, feature-interaction-factory,
  trade-construction, data-sourcing, canonical-simulator, fable-*.md review narratives, etc.) —
  unrelated to this cluster, no rename.

## Scope of the actual sweep

For each of the 3 renamed files: `git mv`, then grep the WHOLE repo (not just `docs/`) for the
old filename — `.planning/`, `CLAUDE.md`, test files, and other `docs/research/*.md` files all
contain live cross-references (verified this session: `platform-security-classification-hierarchy.md`
alone is referenced by ≥4 sibling docs plus ROADMAP.md; `regime-multi-regime-layer.md` is
referenced under its old name `intel-12-stratification-dimension.md` in at least 4 places per
that doc's own provenance note). Confirm zero remaining hits on each old filename before
committing. Same verification pattern as todo 057 (doc-crossref-phase-renumbering-sweep).

**Blocked on:** nothing technical — pure documentation reorganization, no code/schema
dependency. P3 housekeeping; do alongside another doc-crossref pass rather than as a dedicated
session.

## References

- This session's discussion (2026-07-12) — traced the cross-doc structure of the stratification/
  classification family while investigating how Phase 144's `regime_group`, the tag calibrator,
  and Security Classification Hierarchy relate.
- `.planning/todos/pending/057-doc-crossref-phase-renumbering-sweep.md` — sibling mechanism/
  precedent for the cross-reference-correction half of this work.
- `.planning/todos/pending/105-concept-registry-regime-model-domain-seed.md`,
  `.planning/todos/deferred/106-formalize-stratification-dimension-contract.md` — related but
  separate todos (Concept Registry seeding, StratificationDimension contract formalization);
  this todo is pure renaming, not design work.
