---
status: pending
priority: P2
filed: 2026-09-18
source: manual investigation of STATE.md's recurring staleness pattern (already flagged
  3x in STATE.md's own "## Session" section, 2026-07-31/2026-08-09/2026-08-14, and in
  memory as feedback_gsd_state_frontmatter_resync); second finding folded in from a
  concurrent session (indicagent-31) hitting the same class of bug independently the
  same day while running /gsd-plan-phase 175
---

# GSD tooling, not IndicAgent code: two commands hardcode field-name/path assumptions this project's `.planning/` structure doesn't match, both silently no-op instead of erroring

## What

Two independent `gsd-sdk`/GSD-workflow commands assume a `.planning/` shape this project
doesn't have, and both fail the same way -- silently doing nothing instead of erroring, so the
symptom looks like "state randomly goes stale" rather than "this command is broken."

**1. `gsd-sdk query state.planned-phase` (root cause of the STATE.md staleness pattern).**
`/gsd-plan-phase`'s own step 13b runs this after plans pass their gates, to update STATE.md to
"ready to execute." Its implementation (`cmdStatePlannedPhase` in
`~/.claude/get-shit-done/bin/lib/state.cjs:1291`) calls `stateReplaceField()` against literal
field labels: `Status:`, `Total Plans in Phase:`, `Last Activity:`, `Last Activity Description:`,
plus a hardcoded `## Current Position` section. **This project's STATE.md has never used any of
those labels** -- it uses `## Session` / `Stopped at:` / `Last session:` / `Resume file:`
instead (a convention that predates this discovery and is itself flagged inline in STATE.md as
recurring-stale). Confirmed live 2026-09-18: ran `gsd-sdk query state.planned-phase --phase 175
--name "..." --plans 5` after Phase 175's planning fully completed (5 plans, 4 waves,
2 review-revision rounds) -- returned `"updated": []`, a structural no-op, not a partial match.
This isn't occasional drift, as the "confirmed 3 times" framing in STATE.md's own body
suggested -- it's a 100% no-op against this project's actual file format, every single
`/gsd-plan-phase` run, silently. Hand-corrected STATE.md's Phase 175 entry this session as a
workaround; the underlying command is still broken for the next phase.

**2. `gap-checker.cjs` hardcodes `CONTEXT.md` instead of the padded-phase filename convention**
(found independently by a concurrent session, indicagent-31, running `/gsd-plan-phase 175` the
same day -- folded in here per their request rather than filing separately). Backs
`/gsd-plan-phase`'s step 13a decision-coverage gate and the standalone gap-analysis command.
This project's phase directories use `{padded_phase}-CONTEXT.md` (e.g.
`175-itr-materiality-filtered-empirical-tags-for-breadth-peer-gro/175-CONTEXT.md`), not a bare
`CONTEXT.md` -- so the gate silently returns "no decisions to check" for every phase in this
project, defeating the coverage check it exists to run. indicagent-31 had already queued this as
local `SendFeedback` but hadn't sent it as of this session; check with them before duplicating.

## Why this matters

Both are the same failure shape: a hardcoded assumption about `.planning/` file structure,
silently satisfied-as-a-no-op rather than erroring when the assumption doesn't hold. That shape
is worse than a crash -- it produces zero signal that anything went wrong, so the symptom
surfaces later and disconnected from the cause (STATE.md "looks stale" three sessions later;
a decision-coverage gate "looks like it passed" with nothing actually checked). Same class of
bug CLAUDE.md's design mindset flags as worse than a loud failure, just in GSD's own tooling
rather than IndicAgent's.

## Fix shape (not investigated yet)

1. For `state.planned-phase`: either (a) make `stateReplaceField()`/`cmdStatePlannedPhase`
   detect and handle this project's `## Session`/`Stopped at:` format as a supported shape, or
   (b) make the no-op loud -- log/return a warning when zero fields matched, instead of a
   silent `updated: []` that looks identical to "nothing needed updating."
2. For `gap-checker.cjs`: derive the CONTEXT.md path from the actual phase directory contents
   (glob for `*-CONTEXT.md`) instead of a hardcoded bare filename, or read the padded-phase
   convention from wherever it's already defined (`naming-system.md` / existing path-resolution
   helpers) rather than assuming an unpadded name.
3. Both are GSD framework code (`~/.claude/get-shit-done/`), not `indicagent` repo code -- fix
   shape may be "submit upstream feedback" rather than a local patch, same disposition as
   todo 284 (AGY stdin invocation, also GSD tooling not IndicAgent code).

## References

- `~/.claude/get-shit-done/bin/lib/state.cjs:1291` -- `cmdStatePlannedPhase`
- `~/.claude/get-shit-done/bin/lib/state-command-router.cjs:73` -- routes `state.planned-phase`
- `~/.claude/get-shit-done/workflows/plan-phase.md:1562` (step 13b), presumably a similar
  line for step 13a's gap-checker invocation
- `feedback_gsd_state_frontmatter_resync` memory -- documents the symptom across 3 prior
  recurrences without having found this root cause; update once this todo lands
- [284](284-gsd-review-agy-stdin-invocation-broken.md) -- same disposition precedent (GSD
  tooling bug, not IndicAgent code, P3)
