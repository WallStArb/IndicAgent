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
