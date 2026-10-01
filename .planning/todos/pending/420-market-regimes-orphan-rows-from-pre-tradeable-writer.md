---
status: pending
priority: P2
filed: 2026-09-24
source: Phase 179 V4 diagnosis (weekend 1d regime labels)
---

# market_regimes keeps orphan rows the current writer no longer produces

## What

`cross_sectional_regime_model` recomputes full history each run and upserts (`ON CONFLICT DO
UPDATE`), never deleting. Rows it wrote before 7054f6da5 (2026-07-16, switch to
`market_data_ohlcv_tradeable`) at timestamps it no longer labels survive: 1,223,265 weekend rows
for equity and rates across all four tfs (1d: 2,012 equity + 912 rates; 5m: 595,008 + 266,454;
15m: 198,336 + 88,818; 1h: 49,539 + 22,186), latest 2026-07-05 (equity) / 2026-06-28 (rates).
Commodity and fx have none.

Verified harmless for IC today: no `feature_vectors` row falls on a weekend at any tf, so none of
these join a cell. Not yet measured: weekday orphans (intraday timestamps the current writer no
longer labels) that could coincide with a real feature row and hand a cell a stale label.

## What to do

1. Dry-run the writer and diff its (group, tf, ts) set against `market_regimes`; report orphan
   counts by weekday/weekend and how many orphan timestamps join a `feature_vectors` row.
2. Make the writer replace each (regime_group, tf) history atomically (delete + insert in one
   transaction), since it always recomputes full history; delete the orphans.
3. Any orphan that joined a feature row changes IC cells: land with the next planned recompute
   (ic_engine's market_regimes watermark will invalidate the affected cells).

## Triage 2026-09-26 (backlog review with the owner)

Part of the regime refit bundle anchored on todo 248: one `regime_writer` refit lands 248, 286, 292, 289, 341 and 420 together. Order: 426 step 2 (per-chunk writes for UPDATE writers), then 290 (refit memory), then the refit, then 411's refresh. Regime columns can enter books as features (todo 435), so their correctness is on the feature path.



## Unified design note (2026-09-26)

Fold into the phase 186 rebuild's regime inputs: `market_regimes` orphan rows are removed before the rebuild consumes regime columns.

## Deferred rerun owner (2026-09-27, plan-phase)

Plan 186-18 task 3 fixes the orphan mechanism but defers the actual orphan-delete rerun
(`cross_sectional_regime_model --accept-orphan-delete`) whenever the changed-row join count
J > 0. The rerun is owned by the 186-26 executor (task 1's conditional step): it runs after
186-20's parity report is on main (guaranteed by the 186-26 <- 186-23 <- 186-20 dependency
chain) and before the rebuild launch (the rebuild consumes regime inputs; waiting for the
feature_vectors swap would be too late). This todo closes only after that rerun lands, not
when 186-18 merges.

## 186-18 status (2026-09-30): mechanism fixed, cleanup run deferred

Landed: `cross_sectional_regime_model` replaces each (regime_group, tf) history atomically
(`_replace_group_tf`: temp stage, diff, DELETE + INSERT, one commit, rollback on any error),
refuses an orphan share above APR `alpha.regime.cross_sectional.max_orphan_delete_fraction`
(0.01, migration 419) unless `--accept-orphan-delete`, and `--dry-run` reports the diff.

Dry run on the current bars (`evidence/186-18-market-regimes-dry-run.json`), enabled groups equity,
rates, commodity and fx over four tfs: stored 5,354,790 rows, 3,511,736 orphaned (equity 2,427,789,
rates 1,083,947), all in equity and rates; commodity and fx orphan none. Weekend orphans
total 1,223,265 (equity 844,895, rates 378,370), exactly this todo's figure. Weekday orphans are
2,288,471, not zero: the old writer stored rows for bars `market_data_ohlcv_tradeable` no longer
serves (synthetic and flat-carry-forward placeholders), so the stored history is larger than what the
current bars produce (equity 5m stored 2,084,617, produced 376,494).

Changed rows (same timestamp, different label or probability vector): equity 344,378 and commodity
126,656 (rates 0, fx 354). New rows 15,050. J, the orphaned plus changed plus new timestamps that join
a feature_vectors row of the same tf, is 510,835 (186,132 of them equity 5m changed rows), so the
cleanup would change the cells 186-20 replays. 186-20-SUMMARY.md is not on main, so per the plan the
cleanup run was not executed and the `market_regimes` rows are untouched. Rerun owner unchanged: the
186-26 executor runs `python services/cross_sectional_regime_model.py --accept-orphan-delete`, then
`VACUUM (ANALYZE) market_regimes;`, after 186-20's parity report is on main and before the rebuild
launch. This todo stays pending until that rerun lands.

## Replace mechanics after the 186-18 review (2026-09-30, migration 421)

The replace no longer deletes and reinserts a whole history: it takes the cell's advisory lock
(a concurrent run on the same cell is refused), deletes only the orphans and upserts only the
changed and new rows (market_regimes is a plain table, not a hypertable), and checks that the rows
written equal the diff. Two guards: orphaned over `max_orphan_delete_fraction` (0.01) and changed
over `alpha.regime.cross_sectional.max_changed_fraction` (0.05) of the stored rows. The cleanup run
therefore needs reviewed counts, not a boolean:

    python services/cross_sectional_regime_model.py --accept-orphan-delete N --accept-changed M \
        --reason "todo 420 cleanup"

N and M must cover every cell's orphaned and changed rows (take them from a fresh `--dry-run`; the
largest orphaned cell is equity 5m, 1,710,775; the largest changed is equity 5m, 186,132); the
decision is appended to `market_regimes_override` in the same transaction. Observed changed
fractions today: equity 5m 0.089, 15m 0.179, 1h 0.167, 1d 0.675; commodity 15m 0.727, 1h 0.719, 1d
0.960 (5m 0.0006); fx 1h 0.012; rates 0. The 186-26 executor's plan text still says
`--accept-orphan-delete` without a count: use the form above.
