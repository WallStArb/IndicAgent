---
status: pending
priority: P3
filed: 2026-09-09
source: user-requested "renaissance cleanup" audit of docs/ — the premise (too many files
  accumulating) was checked and found false; the real finding is stale cross-references
---

# `docs/` doesn't have a file-count problem — it has 152 broken internal links, concentrated in identifiable clusters

## What was checked, and why a mass-archive pass was NOT done

User asked whether `docs/` needs a "renaissance cleanup" (accumulated files). Checked before
acting, per this project's own "verify then delete, don't flag" discipline:

- `docs/plans/archive/` (176 files) and `docs/research/archive/` (83 files) already exist and
  are actively used — most recent archival commit `ae391ad77`, 64 commits touched `docs/` in
  the last 30 days. This is not neglected.
- Spot-checked the highest-confidence "probably stale" candidate batch — the 15 `fable-2026-07-*.md`
  review docs in `docs/research/` — for live references before considering archiving any of
  them. Every single one is still actively cross-referenced (2-15+ live docs each: foundation/,
  research/, `.planning/ROADMAP.md`, milestone phase docs, completed/pending todos). None are
  orphaned; archiving any would break real, current documentation trails (the exact failure
  mode `feedback_close_referenced_concept_docs` memory warns about).
- `docs/analysis/` (23 files, CSVs/JSONs/reports) is raw evidence backing already-recorded
  verdicts (e.g. `n1_*.json` backs the `nonlinear_interaction_combiner` finding in the new
  construction-verdict-ledger) — retained evidence, not clutter, per this project's own
  "never drop data that could contain signal" principle.
- `docs/renaissance-rigor-playbook/` (17 files) is a deliberate, versioned, portable-foundation
  package (its own naming-system.md doc says explicitly: "travels with a new project unchanged")
  — not accumulated cruft.

**Conclusion: the file-count premise is false. No mass-archive pass is warranted.**

## What's actually real: 152 broken internal markdown links

Scripted check (link target resolved relative to the referring file, `docs/*/archive/`
excluded) across 208 non-archive `.md` files under `docs/`. Three clusters:

1. **35 links** reference an old `intel-NN-name.md` numbered scheme (e.g. `intel-12-
   stratification-dimension.md`, `intel-13-analog-engine.md`) that was superseded by today's
   unnumbered naming (`intel-case-substrate.md`, etc.) — the rename happened but citing docs
   were never swept.
2. **46 links**, concentrated in 26 files across `docs/architecture/`, `docs/data/`,
   `docs/platform/`, `docs/intelligence/`, `docs/development/`, `docs/operations/`,
   `docs/reference/` — cite each other and don't resolve. Worth checking whether these
   directories are pre-v3.0 documentation that never got updated (this project's `CLAUDE.md`
   already flags several v2.x/v1 subsystems as ARCHIVED with no live consumer — if these docs
   describe those systems, the fix is archiving the whole doc, not repairing its links, per
   `feedback_check_archived_before_investigating`) versus genuinely current v3.0 docs with
   stale sibling references that need real fixes.
3. **71 links**, everything else — a real mix, not yet triaged individually.

## What to do

Not attempted in this session — real work, deserves its own dedicated pass rather than a rushed
tail-end fix: for each broken link, decide fix / mark-historical / archive-the-whole-source-doc.
Start with cluster 1 (mechanical — the old numbering scheme has clear successors, largely a
find-and-replace) and cluster 2 (check archived-subsystem status first, per the memory note
above, before spending effort repairing any individual link inside those dirs).

## Verification

- Live scripted check, 2026-09-09, 208 non-archive `.md` files scanned under `docs/`.
- Fable-review cross-reference check: `grep -rl` for each of the 15 `docs/research/fable-2026-07-*.md`
  filenames across the repo (excluding `archive/`), live, same session.
