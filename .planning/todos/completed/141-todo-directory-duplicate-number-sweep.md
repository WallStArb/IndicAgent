---
status: closed
priority: P3
filed: 2026-07-19
closed: 2026-07-27
source: found while closing out todo 131/132 during an autonomous todo-whittling session
  (discovered pending/131 and pending/132 collide with unrelated completed/131 and
  completed/132)
---

## RESULT (2026-07-27): all 8 collision groups resolved.

Re-ran the duplicate check (`ls pending completed deferred | grep -oE '^[0-9]+' | sort | uniq -c`)
first -- confirmed the same 8 groups this todo found were still live (3 of the 7 real
collisions had separately been closed to `completed/` since filing, changing their location but
not resolving the number clash). Per the recommended approach: renumbered the later-filed file
in each group to the next free number at the end of the sequence (determined by git's
add-commit date, `git log --diff-filter=A --follow --format=%ad`), keeping the earlier-filed
file's original number:

- `021`: NOT a real collision -- `completed/021-analog-engine.md` and
  `deferred/021-analog-engine.md` were the same item recorded in two states (diffed identical
  except for a closing note), confirming this todo's own suspicion. Deleted the stale
  pre-closure `deferred/` copy.
- `011-alpha-events-is-shadow-column.md` -> `190-...md` (011 kept by `asset-class-regime-model`)
- `029-feature-scoring-beyond-ic.md` -> `191-...md` (029 kept by `executable-returns-fix`)
- `121-ic-engine-coarse-resume-no-checkpoint.md` -> `192-...md` (121 kept by `bool-apr-flag-string-cast-bug`)
- `122-ic-engine-checkpoint-blind-to-apr-config-drift.md` -> `193-...md` (122 kept by `ibkr-hist-rate-limiter-hangs-full-test-suite`)
- `130-drift-api-route-broken-import.md` -> `194-...md` (130 kept by `ic-engine-incremental-write-late-fdr-backfill`)
- `131-vocabulary-drift-should-extend-basebatch.md` -> `195-...md` (131 kept by `ic-engine-cross-sectional-bootstrap-threading`)
- `132-vocabulary-drift-hardcoded-namespace-taxonomies.md` -> `196-...md` (132 kept by `ic-engine-cheapest-tf-first`)

Grepped the repo for bare-number/path cross-references to each renamed slug before renaming and
fixed the live ones found: `.planning/todos/PRIORITIES.md`, `docs/research/measurement-ic-engine.md`
(1 path link + 2 prose "todo 029" mentions), 3 `.planning/milestones/v3.1-phases/142B.1-*` `@`-import paths, and
2 cross-references between other todo files (`completed/130`↔`completed/193` mutual references,
now `completed/194`↔`completed/193`... `130`→`192`). Deliberately did NOT sweep every historical
`.planning/phases/*` doc beyond the live `@`-import paths -- those are point-in-time snapshots
per this project's existing convention, not live navigation surfaces. Verified zero remaining
duplicate numbers across `pending/`+`completed/`+`deferred/` after the sweep.

# `.planning/todos/` has 8 duplicate-number groups across pending/completed/deferred

## Finding

Same class of bug as [101](101-migration-duplicate-number-sweep.md) (which found 14 duplicate
groups in `production/migrations/`), but for the todo directory itself:

```
011 (pending/... none; completed x2: alpha-events-is-shadow-column / asset-class-regime-model)
021 (completed: analog-engine; deferred: analog-engine -- possibly the same item filed twice,
     check before treating as independent)
029 (pending: feature-scoring-beyond-ic; completed: executable-returns-fix)
121 (completed x2: bool-apr-flag-string-cast-bug / ic-engine-coarse-resume-no-checkpoint)
122 (completed: ibkr-hist-rate-limiter-hangs-full-test-suite; deferred:
     ic-engine-checkpoint-blind-to-apr-config-drift)
130 (completed x2: ic-engine-incremental-write-late-fdr-backfill / drift-api-route-broken-import)
131 (pending: vocabulary-drift-should-extend-basebatch; completed:
     ic-engine-cross-sectional-bootstrap-threading)
132 (pending: vocabulary-drift-hardcoded-namespace-taxonomies; completed:
     ic-engine-cheapest-tf-first)
```

Unlike the migrations case, these files are never applied against a live system by number, so
there's no functional-conflict risk — this is pure prose/filename hygiene. But it does mean any
future cross-reference by bare number ("see todo 131") is ambiguous without also naming the file,
and the numbering sequence itself can no longer be trusted to find the next free slot by
inspection alone (confirmed while filing this todo: `ls | grep -oE '^[0-9]+' | sort -n | uniq -c`
is the check that should run before filing, not just eyeballing the highest number seen).

`021`'s pending/completed/deferred split is worth a closer look before batching into the general
renumber — if `completed/021-analog-engine.md` and `deferred/021-analog-engine.md` are the same
item recorded in two states rather than two distinct items sharing a number, that's a different
bug (a todo that got both closed and re-deferred) than a genuine number collision.

## Recommended approach

Same shape as todo 101's recommendation: renumber the later-filed file in each collision to the
next free number at the end of the sequence, grep the repo for bare-number prose references
("todo 131", "[[131-...]]") before renaming, and add a pre-flight duplicate check (the one-liner
above) to whatever process assigns the next todo number, so this doesn't silently regrow.

## Not in scope for this todo

Actually performing the renumber — low urgency, prose-only risk, no live-system blast radius
unlike 101. Finding + recommended approach only.
