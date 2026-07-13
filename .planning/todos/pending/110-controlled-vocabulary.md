---
status: pending
priority: P3
filed: 2026-07-13
source: doc-organization session — Controlled Vocabulary had zero todo tracking it at all
---

**Registered as ROADMAP Phase 160** (2026-07-13, supersedes orphaned Phase 135) — see
`.planning/ROADMAP.md` for the live phase entry. This todo stays as prioritization context;
`/gsd-discuss-phase 160` is the next step, not yet run.

# Controlled Vocabulary

Single todo for this system (Type 3b of `docs/research/concept-governance-registries.md`).
Canonical design doc: `docs/research/concept-controlled-vocabulary.md`.

**Status:** Design complete, build unscheduled, **and previously untracked by any todo** — this
gap was found, not inherited from an existing item. No dependency blocks it: Phase 134 (the
originally-cited gate, converting `signal_outcome`/`entry_type`/`signal_status` to Postgres ENUM
types) shipped 2026-06-18, and the doc's own text confirms "this design has no build dependency
today; it is gated purely on prioritization."

## What it would build

Three tables (`controlled_vocabulary`, `vocabulary_group`, `vocabulary_group_member`) +
`VocabularyService`, covering `signal_outcome`, `entry_type`, `regime_hmm`,
`regime_cross_sectional`, `tier`, `timeframe`, `asset_class`, `session_type`, and more —
currently scattered as hardcoded Python string literals and Postgres `CHECK` constraints with no
single place governing valid values or their meaning.

## Open question, not resolved here

Whether `tag_vocabulary` (live, 71 tags, migrations 227/228 — a structurally similar
named-vocabulary-plus-assignment table) should be generalized/subsumed by this system once built,
or genuinely needs to stay separate (confidence-weighted many-to-many assignment vs. simple enum
membership). Flagged in conversation 2026-07-13, never examined in either doc — unlike the
Security Classification Hierarchy overlap, which *was* explicitly considered and reasoned through
(see `concept-controlled-vocabulary.md`'s "Out of Scope: Hierarchical Instrument Classification"
section).
