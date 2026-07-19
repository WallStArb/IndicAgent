---
status: pending
priority: P3
filed: 2026-07-19
source: found while closing out todo 131/132 during an autonomous todo-whittling session
  (discovered pending/131 and pending/132 collide with unrelated completed/131 and
  completed/132)
---

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
