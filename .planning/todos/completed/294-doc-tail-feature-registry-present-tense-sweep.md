# 294 - Docs still describing `feature_registry` in the present tense after its retirement

**Filed:** 2026-08-10
**Source:** Phase 170 Plan 08 Task 3(e)
**Status:** pending, not blocking

## What

`feature_registry`/`feature_transition_log` were DROPped by migration 311 (Phase 170,
2026-08-10). `docs/research/concept-unified-registry.md` (Status line, Invariant 9,
revision history) and `docs/foundation/glossary.md` were updated in the same session as
the drop. `grep -rl feature_registry docs/` still finds 44 files.

Most are historical plan/review/analysis documents where a past-tense mention is CORRECT
and must not be rewritten (this project's convention: revision history and dated research
docs are append-only / stand as a record of what was true at the time, not retroactively
edited — same rule CLAUDE.md applies to comments). This todo's job is a targeted audit for
the smaller subset making PRESENT-TENSE claims that `feature_registry` is live/current,
which are now factually wrong, not the full 44-file list.

**Candidates flagged during Phase 170 (not verified this session — check present-tense
claims specifically, not just presence of the string):**
- `docs/research/measurement-ic-engine.md`
- `docs/research/intel-feature-interaction-factory.md`
- `docs/research/measurement-governance-monitor.md`
- `docs/research/catalog.md`

## What NOT to do

Do not blindly sed-replace `feature_registry` -> `concept_registry` across all 44 files —
most are correct as historical record. Read each candidate, confirm it makes a present-tense
"is live" claim (not "was migrated from" / "used to be"), and only reword those.

## Where

- `grep -rln "feature_registry" docs/` for the full candidate list
- `production/migrations/311_retire_feature_registry.sql` — the drop this todo is downstream of

## Closed 2026-08-21

Checked all 4 flagged candidates plus verified every claim against live code/schema
before editing (not trusted from the doc text alone):

**Fixed (genuine present-tense claims, now wrong):**
- `docs/research/measurement-ic-engine.md` (2 occurrences) — claimed `ops_ic_shrinkage.py`
  skips features lacking `feature_registry.group_name`. Verified live:
  `ops_ic_shrinkage.py` reads `concept_registry.group_name` directly (confirmed by direct
  grep). Both occurrences corrected with an inline note, the dated 2026-07-06 quote left
  intact as historical record per this project's append-only convention.
- `docs/research/catalog.md` — one row's summary column referenced
  `feature_registry.group_name`; corrected to `concept_registry.group_name`. This doc is
  "Status: current," a living index, not a dated snapshot.
- `docs/research/intel-feature-interaction-factory.md` (2 occurrences) — an ambient
  "(61 rows, live in production)" factual claim about `feature_registry`, and an "interim
  state (Concept Registry not built)" branch whose premise no longer holds (Concept
  Registry shipped). Both corrected with dated notes; the doc's own broader "historical/
  superseded context" framing left untouched.
- `docs/research/intel-symbol-state-query-layer.md` (3 of 5 occurrences) — the 3 inside
  the actual design proposal body (not a numeric snapshot) corrected to
  `concept_registry.group_name`, including a substantive fix beyond the table-name swap:
  the doc's own architectural claim ("group_name's fixed DB check-constraint") is now
  wrong in a way that matters to the design's reasoning -- `concept_registry.group_name`
  (migration 283) is deliberately UNCONSTRAINED TEXT policed by CVR, unlike
  `feature_registry.group_name`'s old 11-value CHECK, so the doc's own "a migration is
  only needed for a genuinely new category" premise no longer holds either.

**Deliberately NOT fixed, with reasons recorded inline (not just silently skipped):**
- `intel-symbol-state-query-layer.md`'s "What Exists" section (2 occurrences) — this
  section is an explicitly dated 2026-07-31 verification snapshot with many OTHER equally
  stale numbers (36.8M `feature_vectors` rows / 80 symbols, now ~106M rows / 231 symbols
  per `.planning/STATE.md`) — fixing only the table name while leaving every count wrong
  would look like a full refresh when it isn't one. Flagged with a note instead: this
  section needs a full live-verification pass before the doc is planned, not a piecemeal
  string fix.
- `docs/research/measurement-governance-monitor.md` (~15 occurrences) — read in full
  before deciding, not skipped on a header glance. This doc is "draft — rearchitected...
  for independent iteration," dated (2026-07-06 re-verification, original 2026-07-02),
  and its `feature_registry` references are already consistently framed in transitional
  language throughout ("feature_registry today, migrating to concept_registry... later")
  — self-aware of the transition already, matching this project's own convention that
  dated research docs stand as record of what was true when written. A ~15-occurrence
  rewrite of a doc explicitly marked "being rearchitected" is real design-doc surgery, not
  a present-tense string sweep -- exactly what this todo's own "do not blindly rewrite"
  instruction warns against.

Verified every table/column substitution against live migrations (283/284/311) and live
code (`ops_ic_shrinkage.py`, `ic_engine.py`) before writing it, not assumed from the
old doc text. No code changes -- doc-only, as scoped.
