---
status: pending
priority: P2
filed: 2026-07-20
source: todo 149's Task 6 live pilot, 2026-07-20 -- empirical measurement of BarAuditor's
  ongoing price-sanity audit pass against the real 215.6M-row market_data_ohlcv backlog.
---

# `price_sanity_status` historical backlog needs a dedicated one-time backfill, not a bigger `BarAuditor` batch size

## Problem

Todo 149 added `BarAuditor._run_price_sanity_audit()`: each 5-minute audit cycle classifies
one APR-governed batch (`infra.bar_auditor.price_sanity_batch_size`, default 500) of
`price_sanity_status IS NULL` rows and writes a verdict. Task 6's live pilot measured
7.55s for one 500-row batch against the real, mostly-compressed hypertable (215,618,330
rows still unaudited at pilot time). At the current default and BarAuditor's existing 300s
cadence, clearing the full backlog would take **~431,000 cycles, ~4.1 years**.

**The fix is NOT to raise `infra.bar_auditor.price_sanity_batch_size` to compensate.**
`indicagent-bar-auditor.service` has `WatchdogSec=60` -- a batch large enough to make a
meaningful dent in 215M rows (e.g. the 50k-100k range) risks the per-cycle audit pass
alone exceeding the watchdog window, especially given Task 1's own empirically-verified
finding that `UPDATE`s against this table's compressed chunks (248/250 compressed) are
far more expensive than a read of the same rows suggests. A watchdog-killed, endlessly
restarting `BarAuditor` is worse than the current slow drip. This is also a mismatch of
concerns: `BarAuditor`'s bounded per-cycle batch exists to audit the **live incoming bar
stream** without adding latency to its other job (gap detection) -- conflating that with
"clear 20 years of history" is optimizing the wrong requirement (5-Step Mandate step 1:
make requirements less dumb before accelerating).

## Fix

File a dedicated one-time bulk backfill tool (matching the shape of existing bulk-history
tools in this codebase, e.g. `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py`
or the corpus rebuild scripts under `scripts/ops/corpus/`) that:

- Runs OUTSIDE `BarAuditor`'s 5-minute cadence, as its own bounded operator-invoked job
  (or a systemd oneshot), not competing with the watchdog contract of a `Type=simple`
  daemon.
- Reuses Task 1's live-verified TimescaleDB lessons: decompress the affected chunks
  explicitly first (`decompress_chunk()`) rather than relying on a read-only `EXPLAIN`
  test as evidence the write path is cheap; a literal time-range-bounded pass per chunk
  or symbol batch, not one unbounded `UPDATE` over the whole table.
- Reuses `classify_candidate_bar`/`count_corroborating_symbols_batch` from
  `src/intelligence/statistics/price_sanity.py` (todo 149's Task 2/3) -- same
  classification logic as the live daemon, no second implementation.
- Can be safely resumed/re-run (idempotent on already-audited rows via
  `WHERE price_sanity_status IS NULL`) if interrupted mid-run.
- Once the historical backlog is cleared, `BarAuditor`'s existing 500/cycle default is
  correctly sized for its actual ongoing job: auditing new bars as they arrive, which is
  a tiny fraction of 215M rows per cycle.

## Additional finding (final whole-branch review, 2026-07-20)

`BarAuditor`'s candidate discovery orders unaudited rows oldest-first (`ORDER BY timestamp`
ASC). This means a *newly-arriving* corrupt live print is never reached and never stamped
`confirmed_corrupt`/`market_event` until the entire multi-year-older backlog ahead of it
drains -- so until this todo's backfill tool completes, the guard provides **no protective
value for the live data stream either**, not just for historical queries. The `IS DISTINCT
FROM 'confirmed_corrupt'` view predicate means unaudited bars still pass through as visible
(not a correctness regression), but the stated goal ("every consumer inherits protection")
is not actually delivered until this backfill lands. Worth reconsidering whether the ongoing
`BarAuditor` task should process newest-first (or interleave old/new) so incoming bars get
near-real-time protection while this backfill separately handles the historical debt --
independent of whichever ordering/priority this todo's fix ultimately picks.

## Sizing

Medium -- new script, but reuses all classification/corroboration logic already built and
tested in todo 149 Tasks 2-3; the only new work is the bulk-batching/chunk-decompression
orchestration, and Task 1's migration already discovered and documented the relevant
TimescaleDB cost traps to avoid re-discovering empirically.

## References

- `.superpowers/sdd/task-6-report.md` in the `todo-149-price-sanity-guard` worktree --
  exact pilot numbers (7.55s/500 rows, 215,618,330 row backlog)
- `docs/superpowers/plans/2026-07-20-bar-ingestion-price-sanity-guard.md` -- todo 149's
  full plan; this backfill is explicitly out of scope for that plan's Task 6 ("present the
  number, do not silently pick a new batch size ... without review")
- `src/intelligence/statistics/price_sanity.py` -- shared classification/corroboration
  primitives to reuse, not reimplement
- `/etc/systemd/system/indicagent-bar-auditor.service` -- `WatchdogSec=60`, the constraint
  that rules out simply raising the daemon's own batch size
