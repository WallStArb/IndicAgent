---
status: completed
priority: P0
filed: 2026-09-18
closed: 2026-09-22
source: manual corpus data audit this session (user asked "are there any gaps we need to
  backfill") -- surfaced that the 2026-09-16 nightly-backfill ranking fix (commits
  bcc89d650, 61f354072) hasn't actually closed the freshness gap it was meant to close
---

# Nightly OHLCV backfill's `batch_size=20` throttles the wrong resource -- 151/233 compute-eligible symbols still silently stuck at the original 2026-08-10/12 freeze, job reports `status=success` every night regardless -- CLOSED

## Resolution (2026-09-22)

Implemented fix-shape steps 1-4 (question/delete/simplify/accelerate) exactly as scoped below:
deleted the `LIMIT batch_size` cap on candidate selection in `_select_next_batch()`
(`scripts/infrastructure/backfill/infrastructure_nightly_backfill.py`) -- every compute-eligible
symbol is now dispatched every night, staliest first, relying on `fetch_historical_bars()`'s
existing IBKR rate limiter (55 req/10min, self-pacing, never aborts) as the real throttle
instead of an arbitrary symbol count. Removed the now-dead `_load_config()`/`_DEFAULT_BATCH_SIZE`
and the `infra.ibkr.nightly_backfill_batch_size` APR key (migration 349, same retire-a-dead-key
pattern as migration 344's sibling six days earlier). Updated + passing:
`tests/unit/scripts/test_infrastructure_nightly_backfill.py` (7/7). Reviewed by /simplify's 4
parallel agents (reuse: clean; simplification: trimmed triple-duplicated incident narrative down
to the module docstring as the single source; efficiency + altitude: both independently flagged
that `detect_gaps()` is not actually near-zero-cost on an already-current symbol as this fix's
own justification assumed, and that step 5 below was never implemented -- filed as
[387](../pending/387-nightly-backfill-detect-gaps-cost-scaling-and-staleness-observability.md)
rather than blocking this P0 fix on it).

**Step 5 (automate: staleness gauge + APR alert threshold) deliberately NOT implemented here** --
tracked in 387 above, to be done after measuring whether finding 1 in that todo actually matters
at full 233-symbol scale.

**Todo 366's status decision (referenced below) was NOT forced as part of this fix** -- out of
scope for the P0 freshness bug specifically; 366 remains open at its own priority.

---

## What

`infrastructure_nightly_backfill.py`'s 2026-09-16 fix (replacing a permanent row-count cutoff
with staleness-based ranking) was correct as far as it went, but it left the underlying design
flaw untouched: `_select_next_batch()` does `ORDER BY staleness ASC LIMIT batch_size` at the SQL
level, capping how many symbols get looked at, not how much IBKR fetch work gets done. Verified
live 2026-09-18, two nights after the ranking fix landed:

```
total compute-eligible (is_active AND compute_eligible): 233
fresh (<=3 days stale on 1h):                             82
stuck at the original freeze (>30 days, exactly 2026-08-10/11/12 across ALL 4 tfs): 151
```

151/233 (65%) of the corpus ic_engine is currently training against has had zero new OHLCV bars
in 37+ days, and the job has logged `job_completed_total{job="nightly-backfill",status="success"}`
every single night throughout, including the two nights since the "fix" landed. Silent wrong
answer, not a loud failure -- exactly the failure mode CLAUDE.md's design mindset calls out as
worse than a crash.

**Root cause: the batch-size throttle was sized for the wrong operation.** `detect_gaps()` is
documented as a near-zero-cost no-op on any symbol that's already current -- the actual
rate-limited resource is IBKR historical-data fetch volume, not "number of symbols examined."
`batch_size=20` was evidently picked to bound fetch risk during a large backlog pull, then
reused unexamined as the nightly steady-state cadence. With 233 symbols / 20 per night, the
design *mathematically guarantees* a permanent ~12-day (`ceil(233/20)`) staleness sawtooth once
caught up -- it will never converge tighter than that, by construction, regardless of how many
more nights pass.

**Not a neutral/random gap.** The 151 stuck symbols are exactly the ones that historically had
*more* 1h rows (crossed the old 150K cutoff earliest -- longer-tenured, more mature names). The
82 fresh symbols skew toward recently onboarded, thinner-history names (VIXY/EMLC among them).
Any downstream measurement sensitive to how current a symbol's data is near the training-window
boundary is currently getting systematically fresher data for new/thin instruments and
systematically stalest data for old/thick ones -- a correlated bias sitting inside the same
population the in-flight `ic_engine` full-corpus run (todo 378's chain) is training against
right now.

**No instrumentation would have caught this without a manual audit.** There is no
`corpus_ohlcv_staleness_days`-shaped gauge or `alert.lag.*`-style APR threshold for batch
corpus freshness, unlike the service-lag pattern already established for live daemons
(`_load_lag_thresholds()` in `service_auditor.py`). This is the same "instrument everything"
gap, just never pointed at this particular pipe.

**Confirmed downstream impact, found 2026-09-18 same session: this staleness has already
silently broken real ITR tag measurements, not just OHLCV freshness.** `TagCalibrator`'s
`semi_cycle` tag (factor proxy `SMH`) never got empirically measured for AMD/ASML/AVGO/EWT/
EWY/NVDA/QCOM/TSM in the 2026-09-16 16:39:43 UTC calibration run -- all 8 sit on their
2026-08-05 human seed while every one of NVDA's *other* 12 tags measured fine in that same
run. Root cause: `SMH` itself is one of the 151 symbols stuck at the 2026-08-10 freeze --
`build_factor_series_cache()` built `semi_cycle`'s factor return series off SMH's stale
window while every dependent symbol's own return series was current, and the resulting
insufficient-overlap skip silently ate all 8 measurements (skip reasons are aggregated into
counters, never logged per-tag, per `measure_matrix()`'s own docstring -- CLAUDE.md's
"never log per-row" pattern, but here it also means nobody would notice a systematic
multi-symbol miss like this without a manual audit). This should self-heal once this todo's
fix lands and SMH's OHLCV catches up -- but the silent-skip-with-zero-observability failure
mode is real and general: any tag whose `factor_series` symbol happens to be stale will
silently kill measurement for its entire dependent peer group, with nothing logged. Worth a
per-tag "N symbols skipped, factor_series staleness = X days" summary line in
`TagCalibrator`'s own run log as a cheap follow-up, independent of fixing the corpus
freshness itself.

## Fix shape (discussed and agreed with user this session, not yet implemented)

Apply Musk's 5-step mandate in order (per this project's own prioritization lens):

1. **Question the requirement.** The real requirement is "corpus staleness for any
   compute-eligible symbol should never silently exceed N days" -- not "backfill 20 symbols a
   night." Nobody had written that requirement down; that's why nothing checks it.
2. **Delete** the `LIMIT batch_size` cap on *candidate selection* in `_select_next_batch()`.
   Checking staleness for all 233 symbols is cheap; there's no reason to throttle it.
3. **Simplify** to one mechanism instead of two conflated regimes (backlog-clearing vs.
   steady-state trickle): iterate all compute-eligible symbols in staleness order every night,
   dispatch fetches, and stop only when an actual IBKR fetch/pacing budget is exhausted --
   not when a symbol-count cap is hit. A bad night with a real backlog naturally spends the
   budget on fewer symbols; a normal night covers everyone because most cost ~0.
4. **Accelerate**: once (3) lands, steady-state staleness converges to whatever IBKR pacing
   capacity actually allows (likely same-day-to-1-day for the full population) instead of a
   guaranteed ~12-day floor, with no further design change needed as the universe grows.
5. **Automate**: add a point gauge (`corpus_ohlcv_staleness_days{symbol}`, OTel `.set()`
   pattern already used elsewhere) plus an `alert.lag.*`-style APR threshold, so a repeat of
   this exact class of silent-success-while-stale bug pages someone instead of waiting for a
   manual audit.

**Separately, force a real decision on todo 366's status** -- it's been sitting P2 "not urgent"
since 2026-09-01 with the 5 live consumer daemons (`ibkr-provider`/`provider-merger`/
`bar-writer`/`bar-aggregator`/`bar-auditor`) in an undefined limbo state (disabled but not
archived, no reactivation date). Either give them a real reactivation deadline, or mark them
ARCHIVED like the rest of the v2.x stack and make the nightly batch mechanism the documented
sole ingestion path -- the current ambiguous state is part of why the staleness bug above went
unnoticed for a month; nobody owns verifying corpus freshness because it's unclear which system
is supposed to be providing it.

## Before implementing

Pull the actual IBKR historical-data pacing limits this codebase's `ibkr.py`/gateway usage
assumes (rate per unique contract/tf pair, requests per rolling window) before picking a
concrete budget unit for step 3 above -- don't guess a number.

## References

- `scripts/infrastructure/backfill/infrastructure_nightly_backfill.py` --
  `_select_next_batch()`, `_load_config()`, `_DEFAULT_BATCH_SIZE`
- `infra.ibkr.nightly_backfill_batch_size` APR key (migration 304)
- Commits `bcc89d650`, `61f354072` -- 2026-09-16 ranking fix (necessary but insufficient)
- [366](366-live-ingestion-consumer-services-never-restarted-after-gateway-fix.md) -- live
  daemon chain status decision, tracked separately, referenced above
- `services/service_auditor.py` -- `_load_lag_thresholds()`, the existing lag-alerting pattern
  to extend to batch corpus freshness
- `project_ibkr_live_ingestion_stalled_2fa` memory -- corrected 2026-09-18 with this session's
  findings
