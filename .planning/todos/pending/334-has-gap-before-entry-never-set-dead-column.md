# 334 - `forward_returns.has_gap_before_entry` is never set; a designed data-quality flag has been dead since the table existed

**Filed:** 2026-08-16
**Source:** Answering "do we have all the forward returns correct?" -- a general integrity check
on `forward_returns`, not a specific bug report.

## Finding

`forward_returns.has_gap_before_entry` (boolean, `NOT NULL DEFAULT false`, migration
`156_ic_engine_tables.sql`) exists specifically to flag when a computed forward return spans
a data gap at entry -- a real data-quality signal, not decoration.

**It has never been set.** `forward_return_writer.py` -- confirmed the sole writer of this
table -- contains zero references to this column (`grep -n has_gap_before_entry
services/forward_return_writer.py` returns nothing). `git log --all -S
"has_gap_before_entry" -- services/forward_return_writer.py` returns zero commits across the
entire repo history -- this was never wired up, not removed by a regression. Confirmed live:
100% of 103,099,559 rows have `has_gap_before_entry = false` (the DDL default), no exceptions.

**Downstream consumer is silently degenerate as a result.**
`scripts/ops/corpus/ops_cost_hurdle_calibration.py`'s Step 3 (`_step3_gap_contamination`,
"todo 030") reads this column directly (`GROUP BY has_gap_before_entry`) to measure whether
gap-contaminated bars show a materially different return distribution, and contains a
todo-generation template recommending `WHERE has_gap_before_entry = false` be added to
`ic_engine.py`'s `forward_returns` join if a material effect is found. Since the input column
is permanently false for every row, this check can only ever produce one group (`False`),
`gap_fraction` is always 0, and the check has never been able to detect anything since it was
written -- not "checked and found clean," structurally incapable of ever firing.

**Practical exposure:** if forward returns spanning a genuine data gap (e.g. an IBKR
disconnect, a backfill hole, a stale flat-carry-forward bar per `market_data_ohlcv`'s ~82%
synthetic-fill population noted in CLAUDE.md) are currently mixed into the corpus
indistinguishably from clean returns, nothing today protects `ic_engine`'s IC measurement
from them -- exactly the "silent wrong answer" class CLAUDE.md's principles rule out. Whether
this is actually costing real IC quality is unmeasured (that's what the dead check was
supposed to tell us).

## Not yet checked (scope for the fix)

1. What should "gap before entry" mean now? `forward_return_writer.py`'s own docstring notes
   a 2026-07-30 change made `complete_{scale}` bar-indexed rather than session-boundary-aware
   (todo 208) -- the gap-detection semantics this column was designed under may predate that
   change and need re-deriving, not just re-implementing the original intent.
2. Cheapest correct source for gap detection: `market_data_ohlcv_tradeable`'s own bar
   continuity (a missing expected bar_ts within a session) is the obvious candidate, but needs
   confirming against the same bar-indexed convention `complete_{scale}` now uses.
3. Once fixed, `ops_cost_hurdle_calibration.py`'s Step 3 becomes a real, runnable check for
   the first time -- worth actually running it (not just fixing the writer) to see whether the
   gap-contamination effect it was designed to catch is present and material in this corpus.

## Fix

Needs design (bar-indexed gap semantics, not a one-line mechanical fix) -- not attempted this
session. `pending/`, not `deferred/`: self-contained, no external gate, doesn't require a
phase-scoped plan, just needs the semantics question above resolved before writing the code.


## Resolution (2026-08-16, same session)

**Fixed going forward, not backfilled retroactively.** Applying the 5-step mandate:
reusing `market_data_gaps` (BarAuditor's own gap-tracking table) was considered and
rejected -- `BarAuditor` (`indicagent-bar-auditor.service`) is confirmed
inactive/disabled with no log file (likely never run on this box), and
`market_data_gaps` is empty. Wiring this column to that table would trade one
silent-always-false bug for another (empty upstream instead of never-read).

**Implementation** (migration 318, `services/forward_return_writer.py`): computed
locally off the same window pass already producing `open_entry` --
`entry_ts = LEAD(m.timestamp, 1) OVER w` alongside the existing
`LEAD(m.open, 1) OVER w AS open_entry`, no new join, no new table scan. Two
APR-backed thresholds (`alpha.forward_returns.gap_multiplier=3`,
`alpha.forward_returns.gap_max_seconds=14400`) bound the flag: a floor against
1-bar noise, a ceiling that excludes normal overnight/weekend closures -- the
exact mistake todo 208 already made once for `complete_{scale}` ("overnight/weekend
gaps are a known, accepted market property"), deliberately not repeated here.

Ceiling default (4h) is calibrated for equity/ETF RTH sessions only -- confirmed
live all 231 corpus symbols are `asset_class=equity` (todo 316/universe-expansion
memory), and confirmed with the user (2026-08-16) that no futures/fx symbols are
currently turned on. NOT yet safe for a mixed-asset-class corpus (a futures
symbol's ~1h daily maintenance break would fall inside the current floor/ceiling
window and get misflagged) -- asset-class-aware widening is the real follow-up
if/when futures/fx symbols are added, not attempted here since the case doesn't
exist yet (no premature complexity for a scenario with zero live rows).

**Verified**: 29/29 `test_forward_return_writer.py` tests pass (2 new, both other
27 unchanged -- SQL-shape assertions, no behavior regression). Live smoke test
against real SPY 15m data: 0/442 rows flagged (clean data, no false positives).
Synthetic positive-control test (isolated CTE, no real table touched): a
fabricated 2h15min intrasession gap correctly flags `true`; a fabricated 21h
overnight closure correctly stays `false`; end-of-series (no `entry_ts`) correctly
stays `false`. Full 5,295-test unit suite green.

**Explicitly NOT done this session**: retroactive backfill of the 103M existing
`forward_returns` rows. `forward_returns` is a compressed TimescaleDB hypertable
(confirmed during todo 333's cleanup, same session) -- a full-table `UPDATE`
touching every row would decompress far more chunks than todo 333's narrow
301K-row/15m-only `DELETE` did, at meaningfully higher risk (same underlying
mechanism as the 2026-08-13 768GB disk-full incident, at a much larger blast
radius here). Needs the full `docs/foundation/performance-investigation-sop.md`
treatment (measure first, not theorize) before attempting, as its own separate
piece of work -- not bundled into this fix. Until that backfill runs, existing
rows retain their pre-fix `has_gap_before_entry=false` default; only rows written
by future writer runs get the real computed value.

**Status: not closing this todo yet** -- the writer fix is done and verified, but
the retroactive-backfill follow-up above is real, scoped, un-started work. Revisit
when planning that backfill (or when it becomes blocking for
`ops_cost_hurdle_calibration.py`'s Step 3 actually being run for the first time).
