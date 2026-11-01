---
status: pending
priority: P3
filed: 2026-08-06
source: found while updating docs for the AnalogEngine -> PrecedentEngine naming
  correction (2026-07-09 rename, missed by stratification-dimension-unification.md's
  own 2026-08-01 reconciliation pass and several other docs) during a Phase 145
  discuss-phase session
---

# `docs/foundation/v3-north-star.md`'s PrecedentEngine mechanics section predates the D4 rescope

## What's wrong

`docs/foundation/v3-north-star.md` is marked `Status: Canonical — foundational v3.0
philosophy` and lives in `docs/foundation/` (the canonical doc home per CLAUDE.md), but
its PrecedentEngine (originally "AnalogEngine") mechanics section was written
2026-06-20 and has not been reconciled against the later D4 rescope that
`docs/research/intel-precedent-engine.md` and `docs/foundation/glossary.md` both
already carry:

- Describes a **Score Object** / separate scoring-and-combiner system — D4 deleted
  this; there is no separate scoring/combiner system in the current design.
- Frames PrecedentEngine and AlphaEngine as **independent annotators that can "agree
  or disagree"** — this is the exact error the glossary's `PrecedentEngine` entry
  explicitly flags and corrects: *"An earlier version of this entry said 'both are
  independent and additive' — that was a real error, since corrected; do not repeat
  it."* PrecedentEngine's predictors register into and are measured/weighted by
  AlphaEngine's own IC/ensemble machinery — "one model, one book," not two.
- Describes PrecedentEngine annotating **`signal_events`** post-emission — `signal_events`
  is v2.x, archived, no live consumer as of 2026-07-02 per CLAUDE.md's Architecture
  section.

The 2026-08-06 naming pass (AnalogEngine → PrecedentEngine, mechanical rename only)
fixed the terminology in this doc and added an inline staleness note pointing to
`docs/research/intel-precedent-engine.md`, but did not attempt to reconcile the
mechanics themselves — that requires actually cross-referencing every claim in this
doc's PrecedentEngine sections (roughly lines 320-590) against the D4 rescope doc,
which is real design-judgment work, not a mechanical find-replace.

## Fix direction

Read `docs/research/intel-precedent-engine.md` in full (the current, correct,
D4-rescoped design) alongside `docs/foundation/v3-north-star.md`'s PrecedentEngine
sections, and either:
1. Rewrite the mechanics sections in `v3-north-star.md` to match D4, keeping only the
   North Star philosophy blockquote as the doc's load-bearing content, or
2. Strip the PrecedentEngine mechanics out of `v3-north-star.md` entirely (it's a
   philosophy doc, not an architecture spec) and point readers to
   `intel-precedent-engine.md` for mechanics, keeping `v3-north-star.md` scoped to
   just the North Star principle it's actually named for.

Option 2 is probably cleaner — this doc doesn't need to carry a second, independently
decaying copy of PrecedentEngine's architecture when a dedicated canonical doc already
exists and is kept current.

Not urgent: PrecedentEngine/v3.2 is gated behind v3.15 (Phases 144/145) and v3.1's OOS
proof holding at scale, per `.planning/PROJECT.md`. No live consumer reads this doc's
mechanics section today.

## References

- `docs/foundation/v3-north-star.md` (lines ~320-590, PrecedentEngine sections)
- `docs/research/intel-precedent-engine.md` — current, correct, D4-rescoped design
- `docs/foundation/glossary.md` — `PrecedentEngine` entry, already carries the
  "not a second book" correction this todo generalizes to v3-north-star.md
- `docs/research/catalog.md` — rename record (AnalogEngine → PrecedentEngine, commit
  `1d41f1da`, 2026-07-09)
