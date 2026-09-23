---
status: pending
priority: P2
filed: 2026-09-22
source: Codex cross-AI plan review of Phase 176 (176-REVIEWS.md, HIGH severity, explicitly scoped as a follow-up rather than a Phase 176 blocker)
---

# `feature_ic_scores` uniqueness key excludes `regime_scope`, forcing every new scope to encode itself into the `regime` string

## What

The cross-sectional INSERT in `services/ic_engine.py` uses:

    ON CONFLICT (feature_name, symbol, tf, regime, lookahead_bars, training_window_end)
    WHERE is_pooled = true AND symbol = 'POOLED' DO NOTHING

`regime_scope` is **not** part of the uniqueness key, even though it is a first-class column and a
semantic partition of the table. The consequence is that two rows differing only by `regime_scope`
collide, and the loser is silently dropped by `DO NOTHING` — no error, no count, no log line.

`_compute_cross_sectional_tf` is invoked once per `(regime_group, tf, regime_label)`, so any new
scope that reuses a label across parent cells within a tf hits this.

## Why it surfaced now

Phase 176 adds a fourth `regime_scope` value (`earnings_season`) that stratifies each existing
cross-sectional cell into in-season / off-season sub-cells. A bare `in_season` label would collide
across parent cells within the same tf and silently drop rows.

Phase 176 works around it correctly, by parent-qualifying the labels:

    f"{regime_label}__in_season"   and   f"{regime_label}__off_season"

That is sound and is NOT blocked by this todo — plan 176-06 ships with the qualified labels, a
docstring explaining why, and a test pinning the label strings.

## The actual problem

The workaround encodes scope into the `regime` string. That is brittle in three specific ways:

1. **It is a convention, not a constraint.** Nothing in the schema prevents the next scope author
   from using a bare label. The failure mode is silent row loss, which is the worst possible
   feedback signal — the run looks successful and the measurement is simply missing rows.
2. **It overloads one column with two meanings.** `regime` now carries both "which regime" and
   "which scope stratification", parsed apart by a `__` separator convention that lives only in a
   docstring and a test.
3. **It recurs per scope.** Every future scope repeats the same reasoning and the same risk. Phase
   176 is the second scope-shaped addition to this table; there will be more.

## Fix (to be evaluated, not yet decided)

Evaluate adding `regime_scope` to the uniqueness key:

    ON CONFLICT (feature_name, symbol, tf, regime, regime_scope, lookahead_bars, training_window_end)

Open questions that make this a real evaluation rather than a one-line migration:

- The partial unique index carries a `WHERE is_pooled = true AND symbol = 'POOLED'` predicate;
  confirm how many such indexes exist and whether all of them need the same treatment (the
  per-symbol path has its own conflict target).
- `feature_ic_scores` is large (9.86M rows as of 2026-09-22) and this is an index rebuild — check
  whether it is a hypertable and, if compressed, follow
  `docs/foundation/timescaledb-compressed-column-migration.md` including the mandatory trailing
  `VACUUM`.
- Decide what happens to Phase 176's parent-qualified labels if the key changes: leave them (they
  stay correct, just redundant) or migrate them back to bare labels (cleaner, but rewrites rows
  a shipped verdict document already cites). Leaving them is probably right; the verdict document
  in `.planning/phases/176-earnings-season-calendar-primitive-todo-353/176-GATE-VERDICT.md`
  quotes label strings.
- Whether the real fix is instead a CHECK constraint or an insert-time assertion that fails loudly
  on a label collision, which is cheaper than an index rebuild and directly addresses the "silent"
  half of the problem.

## Not urgent

Phase 176's workaround is correct and tested. This is about the next scope, not this one.
</content>
