# 316 - 80 active ETF symbols (SPY, QQQ, DIA, IWM, GLD, sector SPDRs, etc.) silently absent from `feature_vectors` for weeks -- checkpoint desync, root-caused and code-fixed

**Filed:** 2026-08-14
**Source:** User asked "isn't the full corpus like 250 symbols?" while reviewing `regime_writer`'s
"151 symbols" scope during the 2026-08-13 disk-full-incident recovery. That question surfaced a
real, previously-unnoticed gap: `feature_vectors` currently has only 151 distinct symbols, but
`instruments` has **231 active** (`is_active = true`).

## What -- confirmed via direct DB query, not inferred

```sql
SELECT count(*) FROM instruments i
WHERE i.is_active = true
AND NOT EXISTS (SELECT 1 FROM feature_vectors fv WHERE fv.symbol = i.symbol);
-- 80
```

**All 80 missing symbols are ETFs from the original pre-expansion universe** (`instruments.created_at`
in {2026-05-15, 2026-06-06, 2026-07-02} -- 32+26+22=80, zero overlap with the 2026-08-05/06
151-symbol stock expansion). The list includes the most important, most liquid instruments in the
whole corpus: **SPY, QQQ, DIA, IWM, GLD, SLV, TLT, XLF, XLE, XLK, XLV, XLI, XLP, XLU, XLY, XLB, XLC,
XLRE**, plus international/commodity/bond/factor ETFs (EWZ, EWJ, EWG, EEM, EFA, DBA, DBB, DBC, AGG,
HYG, LQD, TIP, IEF, SHY, MUB, MTUM, QUAL, USMV, RSP, VYM, VTV, VUG, and more -- full list of 80 in
the investigation transcript). **The 151 present symbols are the newly-expanded individual-stock
universe** (AA, AAPL, ADM, AEP, AMD, AMT, AMZN, ...) -- fully populated with deep history (bar_ts
back to 2005-09-29 for the oldest names).

**This is not a data-availability gap.** All 80 missing symbols have full raw OHLCV coverage in
`market_data_ohlcv_tradeable` (SPY: 395,057 5m rows, 2006-07-07 through 2026-08-11) and
`backfill_status` shows `status='complete'`, `fetch_complete=true` for every tf except 1m
(`started_at=2026-07-08`, `completed_at` spread across 2026-07-29). `git log` confirms
`backfill_feature_factory.py` had 36.7M pre-existing `feature_vectors` rows as of 2026-07-27
(commit `b9445add8`, todo 176) -- consistent with these 80 ETFs having been genuinely, successfully
computed at that time. Something removed that data from `feature_vectors` afterward (exact
mechanism not pinned down -- no `TRUNCATE`/`DROP TABLE` found in migrations; most likely an
intentional wipe-and-rebuild ahead of the 08-05/06 stock expansion that was never followed by a
`--refresh` recompute pass for the ETF cohort specifically). **Root cause of why this went
undetected for ~2+ weeks, independent of how the data was lost:**

## Root cause -- confirmed by reading the code, not guessed

`services/backfill_feature_factory.py`'s `run_compute_stage()` checkpoints per (symbol, tf) purely
on `backfill_status.status == 'complete'` (line ~1015, pre-fix) -- a side-table flag with **no
transactional or FK coupling to `feature_vectors` itself**. When `feature_vectors` loses data for a
pair whose `backfill_status` still says `'complete'`, every future run of `run_compute_stage`
silently and permanently treats that pair as done (`compute_skip_complete`, logged at `info`, not
even a warning) -- with zero mechanism to notice or self-heal. Exactly the "silent wrong answer"
CLAUDE.md's own principles warn against, and it held for 2+ weeks undetected until a human asked
"isn't the corpus bigger than that?"

## Fix -- code landed this session, commit pending on a feature branch

`_load_fv_presence_map()` (new) queries `feature_vectors` once per `run_compute_stage()` run for
the actual (symbol, tf) pairs present, and the checkpoint now requires **both** `status='complete'`
**and** presence in that set before skipping. A desync logs `compute_checkpoint_desynced` at
`warning` level (so a future recurrence is visible, not silent) and falls through to a real
recompute. TDD: failing test written first
(`test_compute_resume_recomputes_when_status_complete_but_no_fv_rows`), confirmed failing on
`AttributeError` before the fix existed, passing after. Pre-existing
`test_compute_resume_skips_complete_pairs` updated to mock the new presence check for its
correctly-synced scenario. Full suite green (`tests/unit/ -q`, 37/37 in the changed file, no
regressions elsewhere). `/simplify` 4-angle review run on the diff -- see this todo's own commit
for what it found/fixed.

## What's NOT done yet -- the actual data remediation

The code fix prevents this class of bug from recurring silently and enables recompute, but **does
not by itself restore the missing rows** -- that requires actually running
`backfill_feature_factory.py --compute-only` (now correctly detects the 80-symbol gap and will
recompute them; add `--refresh` if any of them still show `status='complete'` with a since-fixed
desync check that's already false by the time this runs, or just let the new presence check do its
job unconditionally). **Deliberately NOT run this session** -- `regime_writer`'s 5th relaunch is
mid-run against the same `feature_vectors` compressed hypertable (see
`project_disk_full_incident_2026_08_13` memory), and running a second heavy writer against the same
compressed hypertable concurrently is exactly the failure shape [[todo 314]] just found (write
sessions collide with each other, not just with TimescaleDB's compression policy job). Sequence
this AFTER `regime_writer`'s current run (`regime` + `regime_volatility` passes) completes.

## Status

pending, **P0** -- confirmed correctness bug per CLAUDE.md's "Causal bugs get fixed regardless of
measured benefit" rule; the 80 missing symbols include the most liquid, most important instruments
in the entire universe (SPY/QQQ/DIA/IWM/GLD/TLT/sector SPDRs) and every downstream consumer
(`regime_writer`, `ic_engine`, `ensemble_trainer`, `alpha_publisher`) has been silently operating on
a corpus missing them for at least 2 weeks. Code fix landed; data remediation queued behind the
live `regime_writer` run.

## What to do

1. **Once `regime_writer`'s current run completes and job 1065 (compression policy) is
   re-enabled** ([[todo 314]]'s cleanup step), run
   `.venv/bin/python -m services.backfill_feature_factory --compute-only` -- should pick up all 80
   ETF symbols automatically now that the presence check is live, no explicit `--symbols` list
   needed. Expect this to be pure compute (no IBKR fetch, `fetch_complete` already true) --
   probably fast relative to a full fetch+compute run, but respect
   `compressed_hypertable_write_session`'s exclusive-access expectations against `feature_vectors`.
2. **Verify after running:** re-check `count(*) FROM instruments WHERE is_active AND NOT EXISTS
   (... feature_vectors ...)` returns 0, not just that the job exited 0 -- this bug's whole
   signature was a job reporting success while writing nothing.
3. **Pin down the actual deletion mechanism**, if worth the effort -- not required for the fix to
   be complete (the checkpoint desync is fixed regardless of *why* the data was lost), but useful
   to know whether this is a one-time historical event or a recurring operational gap (e.g. does
   every future corpus rebuild need an explicit "don't forget `--refresh` for pre-existing symbols"
   step, or was this a one-off).
4. **Consider a standing automated audit**: `instruments.is_active` universe vs. `feature_vectors`
   symbol coverage, alerting on any gap -- this bug was found by a human asking a question, not by
   any existing monitoring. Todo 272 (instrument-tag peer-group coverage auditor) is the closest
   existing precedent for this shape of check; could extend it or add a sibling.
5. Re-run `regime_writer` for the 80 newly-recomputed symbols once their `feature_vectors` rows
   land (they'll have `regime`/`regime_volatility` NULL until a regime pass includes them).

## Where

- `services/backfill_feature_factory.py` -- `_load_fv_presence_map()` (new), `run_compute_stage()`
  checkpoint logic (fixed)
- `tests/unit/services/test_backfill_feature_factory.py` -- new + updated tests
- `backfill_status` / `feature_vectors` -- the two tables whose desync caused this
