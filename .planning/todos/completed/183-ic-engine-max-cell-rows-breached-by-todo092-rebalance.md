---
status: completed
priority: P0
filed: 2026-07-26
closed: 2026-07-27
source: todo 092's live corpus recompute halted itself, discovered when checking run status
---

## CLOSED 2026-07-27: recompute completed clean, both regime groups, zero further breaches

`ic_engine.py` ran 2026-07-26T18:19 UTC -> 2026-07-27T21:55 UTC (~27.6h, one continuous run,
`ic_engine.run_complete`/`status=success`), covering both `equity` and `rates` regime groups
across all 4 timeframes (5m/15m/1h/1d) with zero errors and no further `max_cell_rows`
breaches -- confirming this todo's step 4 concern (rates' worse pre-fix imbalance) did not
recur in practice. 30,788 rows committed, 10,678 skipped (fingerprint-matched), corpus FDR
backfill applied to 618,604 rows. This directly unblocked todo 179's regime-sweep re-run
(T2 confirmed dead on live corrected labels, no longer provisional -- see
`.planning/todos/completed/179-gate166-concurrent-exposure-diagnostic.md`).

## Resolution (2026-07-26, same day, in progress)

Root cause was actually two compounding issues, both found and fixed tonight:

1. **`market_regimes` was not cleanly recomputed under todo 092's fix.** The
   2026-07-24 run of `cross_sectional_regime_model.py` used a correct 49-symbol
   `eq_*`/`intl_*` reference basket (verified — an earlier diagnostic that
   suggested 72 symbols and blamed thin/late-listed names like IBIT was itself
   wrong, a SQL `LIKE 'eq_%'` pattern-matching bug where `_` is a wildcard and
   incorrectly matched the unrelated `equity_beta` tag). The real gap was
   leftover rows from the *retired* `equity_regime_model.py` (superseded by
   `cross_sectional_regime_model.py` in Phase 144) still sitting in the same
   table, plus a small amount of additional real staleness. Re-ran
   `cross_sectional_regime_model.py` for real (no `--tf`/`--dry-run`, all 4 tfs,
   both groups) 2026-07-26 18:04-18:12 UTC — 776,108 rows written, confirmed
   equity/5m now at 372,906 rows, ~99.85% of the theoretical maximum achievable
   regular-session coverage since 2007.
2. **The ceiling itself needed recalibrating**, but not for the reason first
   assumed. Under the now-fully-fresh labels, the true largest cell is actually
   equity/5m `mid_neutral` at 2,964,837 rows (not the `high_bear` cell that
   originally failed, which is now 2,672,683 — regime relabeling shuffled which
   cell is largest). Measured empirically (not extrapolated): a synthetic
   allocation test replicating `ic_engine.py`'s exact cross-sectional assembly
   shape (X_raw → X_nd → per-scale ranks_X_scale, block-chunked `rankdata`) at
   this exact row count peaked at **11.87GB RSS**, comfortably within this
   host's ~22GB free headroom. The 2026-07-18 reference incident (599K rows,
   ~20.5GB peak RSS) predates Phase 162's own OOM fix (bounded, chunked
   `rankdata`) and no longer represents current code's memory shape — extrapolating
   from it (as this todo originally did) overstated the real risk substantially.
   `rates` group's largest cell (steep_wide, 507,034 rows) was never close to
   any ceiling. Migration 259 raised `alpha.ic.max_cell_rows` 1,200,000 →
   4,000,000 with real margin above the measured largest cell, applied
   2026-07-26.
3. Resumed `bash scripts/ops/corpus/ops_corpus_pipeline_run.sh --from-step 5`
   2026-07-26 ~18:19 UTC, same `TRAINING_WINDOW_END`/`WEIGHT_EPOCH` anchor
   (`run_2025122405150000`) as the original run — equity's already-committed
   1d/1h/15m work is reused via fingerprint, not redone. **Still running as of
   this edit — do not mark this todo closed until the full run (5m + rates +
   steps 6-8) completes; re-verify via `ps aux | grep ic_engine` and
   `logs/ic_engine.log` before trusting this note in a future session.**

# `alpha.ic.max_cell_rows` ceiling breached by todo 092's own regime rebalance — corpus recompute halted, blocks todo 179 re-check

## What happened

The todo 092 corpus recompute (`ic_engine.py`, running since 2026-07-25 04:58 UTC) failed by
design at 2026-07-26T00:40:55Z:

```
"Cross-sectional cell tf=5m regime=high_bear has 2627604 rows,
 exceeding alpha.ic.max_cell_rows=1200000."
```

`ic_engine.run_failed`, nonzero exit, `run_step` in `ops_corpus_pipeline_run.sh` halted the
whole pipeline (by design — see the `CellTooLargeError` handler's comment at
`ic_engine.py:3490`: an oversized cell "must fail the whole job... never be silently
skipped"). This is not a bug and not an OOM crash (host memory/load are fine, no dmesg OOM
entries) — the crash-loud ceiling worked exactly as Phase 162 built it.

## Why this is happening now, and not before

`alpha.ic.max_cell_rows=1,200,000` was sized "~2x that largest known cell" against the
2026-07-18 OOM incident's 5m/`low_bull` cell (~599K rows, ~20.5GB peak RSS) —
`config_schema.description` states this explicitly. Todo 092's whole point (migrations
257/258, causal-rank regime rebalancing) was to reduce population imbalance between regime
cells — STATE.md records the equity fix roughly halving imbalance (13.8x→7.1x at 5m). A
minority regime like `high_bear` legitimately holding far more bars post-fix is the rebalance
working as intended, not a data bug. The ceiling was never re-baselined against the new,
more-balanced distribution's largest cell — this is the first full corpus run under the
corrected labels, so it's the first time anything could have caught this.

## What's safe and what's blocked

**Committed and safe (incremental per-cell writes, nothing lost):** equity group's full
80-symbol per-symbol pass, plus all 9 regime cross-sectional cells at 1d, 1h, and 15m.

**Not yet computed:** equity's 5m tf (failed on its first cell, `high_bear`), the entire
`rates` regime group (steps 4-5 never repeated for it), and steps 6-8 (`ic_shrinkage`,
`ensemble_trainer`, `alpha_publisher`) — so corrected regime labels have not propagated to
`ensemble_weights`/`ensemble_alpha` yet. This blocks the todo 179 re-check (STATE.md's Current
Focus explicitly says the 234-cell no-edge sweep should be redone against corrected labels
once this recompute lands) and blocks Phase 164/165's fork decision, which is waiting on that
re-check.

## Why this isn't a safe "just raise the ceiling and rerun"

The reference OOM cell (599K rows) hit ~20.5GB peak RSS on this 29GB host. The failing cell
here is 2,627,604 rows — ~4.4x the reference. Per the Phase 162 design doc (ROADMAP.md, Phase
162 section), the base float32 assembly arrays (`X_raw`/`X_nd`) scale linearly with cell size
("~1.4GB at a 2x cell; linear with a small constant") — the transient `rankdata` blowup that
caused the original OOM is already bounded by feature-axis chunking, but the base arrays are
not. Extrapolating linearly, a 4.4x cell could need memory in a range that would OOM this host
outright (not just crash Python loudly) if `max_cell_rows` is simply raised without further
work.

The Phase 162 design doc pre-registered exactly this contingency and deferred it: *"if the
synthetic oversized-cell test shows base assembly itself breaching budget, the second lever is
memmap-backed assembly to scratch disk (basic-slice subsampling returns views on a memmap
unchanged); contingent, measured first, not built preemptively."* That contingency has now
triggered for real.

## Recommended path (needs a decision, not a blind config change)

1. **Measure first.** Check actual peak RSS need for a cell this size before deciding —
   either a synthetic oversized-cell test (as the Phase 162 doc originally proposed) or by
   watching `ps`/`free` live if/when this cell is retried. Don't guess from linear
   extrapolation alone.
2. **If assembly memory is within this host's real headroom** (currently ~22GB available per
   `free -h`), raising `alpha.ic.max_cell_rows` with fresh justification (new migration,
   `changed_by`/`reason` citing this incident and the measurement) may be sufficient.
3. **If not**, build the memmap-backed assembly fallback the Phase 162 doc already scoped —
   this is real new work, not a config tweak, and should go through a proper plan, not a
   quick patch to a live production recompute.
4. **Either way, re-check whether `rates`' regime cells have a similar imbalance shift** from
   todo 092's fix (STATE.md: `curve_z`/`credit_z` imbalance was worse pre-fix, 30.8x vs
   equity's 12-17x) — if `rates`' largest cell also breaches the ceiling, this needs to be
   solved once, not per-regime-group as each one is hit.
5. Resume via `bash scripts/ops/corpus/ops_corpus_pipeline_run.sh --from-step 5` once a fix
   is chosen — the equity per-symbol/1d/1h/15m work already done does not need to be redone.

## References

- `services/ic_engine.py:225-227,552-554,806-809,3490-3496` — `CellTooLargeError`,
  `max_cell_rows` config field, the raise site, and the deliberate re-raise (not
  swallow-and-continue) in the symbol-loop handler
- `production/migrations/` — original `alpha.ic.max_cell_rows` seed migration (2026-07-18 OOM
  incident, sized 2x the reference cell)
- ROADMAP.md, Phase 162 section ("Reconciled 2026-07-19... Todo 140 fork resolved") — the
  memmap-backed-assembly contingency this incident triggers
- `[[project_todo092_breadth_regime_causal_rank_fix]]` — the regime rebalance that changed
  population distribution and caused this
- `.planning/todos/completed/179-gate166-concurrent-exposure-diagnostic.md` — blocked on this
  recompute completing
- `logs/ic_engine.log.1` — full run log, failure at 2026-07-26T00:40:55.271400Z
