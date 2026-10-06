---
phase: 185-daily-data-foundation
plan: 30
subsystem: bars / 1d lineage, digests, quality flags
tags: [D-06, D-07, D-09, tradier, lineage, digest, legacy_price_sanity_status, gap_closure]
requires: [185-27]
provides: [tradier-v1 lineage on every stored tradier 1d bar, current 1d digests for every canonical 1d name, 12 replaced 1d legacy flags retired with a record, OLED and RCAT untraced bars traced]
affects: [canonical_bar_lineage, bar_content_digest, bar_quality_flag, bar_derivation_batch, ohlcv_observation (IBKR re-ask), market_data_ohlcv (D2 inserted 7 missing OLED/RCAT bars)]
tech-stack:
  added: []
  patterns: ["one-time repair that imports the write path's statements (TRADIER_LINEAGE_UPSERT_SQL, write_1d_digests) instead of copying them; digest dry run = the writer inside a rolled-back transaction"]
key-files:
  created:
    - scripts/ops/bars/ops_tradier_lineage_backfill.py
    - tests/unit/scripts/test_ops_tradier_lineage_backfill.py
  modified:
    - tests/unit/test_market_data_ohlcv_boundary.py
decisions:
  - "An unmatched bar does not roll back its name's matched lineage: the matched rows commit, the unmatched dates are listed in the batch detail and the batch ends failed. None occurred."
  - "The digest dry run calls write_1d_digests inside an outer transaction and rolls it back, so the stale-month count is the writer's own decision, with no copied digest logic."
  - "Legacy-flag candidates are read as the session user before SET LOCAL ROLE bar_derivation_writer, because that role has no grant on ohlcv_revision; the delete then runs under the role, keyed by symbol and timestamp with rule and timeframe = '1d' in its WHERE, and the transaction aborts if the delete count differs from the candidate count."
  - "The re-ask ran the historical pipeline (client 49, priority lease tier) inside a scratch harness that held the phase 189 FetcherLock, because the pipeline takes only the ibkr_history_stream lease; no phase 189 file was edited and the fetcher service and timer stayed stopped."
metrics:
  duration: 45min
  completed: 2026-10-06
  tasks: 3
  files: 3
---

# Phase 185 plan 30: 1d lineage, digests and replaced legacy flags repaired

Every stored Tradier 1d bar now has tradier-v1 lineage naming an equal TRADIER D1 observation, every canonical 1d name has current digests, and the 12 legacy price-sanity flags on bars Tradier replaced are retired with the replaced IBKR values recorded. Of the 31 untraced IBKR bars, OLED's 4 and RCAT's 1 are now traced. INDA's 26 are still untraced and not quarantined. That is a blocking finding for 185-33, written up below.

## Task 1: repair script

`scripts/ops/bars/ops_tradier_lineage_backfill.py` is a dry run by default and has three modes:

- lineage (default): for the owned names (`TRADIER_OWNED_SQL`, or `--symbols`), runs the loader's `TRADIER_LINEAGE_UPSERT_SQL` and `_TRADIER_LINEAGE_UNMATCHED_SQL`.
- `--digests`: runs `write_1d_digests` over every symbol with a canonical 1d bar, at tradier-v1 for owned names and d2-v1 for the rest.
- `--retire-replaced-legacy-flags`: retires the replaced 1d legacy flags.

`--apply` opens one `bar_derivation_batch` (stage tradier, rule tradier-v1, detail `plan: 185-30`). Each name runs in its own transaction on one serial connection, and writes run under `SET LOCAL ROLE bar_derivation_writer`. The tests use fakes only (13 tests). They cover:

- statement identity
- dry-run no-write
- role-first per-name transactions
- unmatched handling: the batch fails while other names complete
- rule version by ownership
- the rolled-back digest dry run
- the delete's `timeframe = '1d'`, with an intraday legacy flag on a fake left alone
- delete-count mismatch rolls back

## Task 2: live run (2026-10-06, 17:49 to 17:53 UTC)

Before the run, the legacy flag counts by timeframe were 1d 15, 15m 19, 1h 513, 5m 20.

| Measure | Before | After |
|---|---|---|
| Stored tradier 1d bars (1,266 names) | 6,271,834 | 6,271,834 |
| ...without tradier-v1 lineage (acceptance query) | 6,251,647 on 1,263 names | 0 |
| canonical_bar_lineage 1d rule tradier-v1 | 20,187 | 6,271,834 |
| canonical_bar_lineage 1d rule d2-v1 | 3,901,313 | 737,055 (737,043 after task 2, +12 from task 3's D2 run) |
| Stale d2-v1 rows on tradier bars (dry run) | 3,164,270 on 740 names | 0 |
| Unmatched tradier bars (no equal observation) | 0 | 0 |
| 1d digest stale months (dry run, 1,502 names) | 300,151 (tradier-owned 299,937 over 1,266; IBKR-owned 214 over 31 of 236 names) | 0 |
| Tradier-owned names with no 1d digest | 523 | 0 |
| bar_content_digest_current 1d tradier-v1 | 966 months, 3 names | 300,903 months, 1,266 names |
| 1d legacy_price_sanity_status flags | 15 | 3 (DIA, EDV, EWG) |
| Intraday legacy flags | 15m 19, 1h 513, 5m 20 | 15m 19, 1h 513, 5m 20 (unchanged) |

- Timing: 10 names (A to ACIW, 51,253 rows) applied in 0.8 s, then the remaining 1,256 names (6,200,394 rows) in 71 s. `VACUUM ANALYZE canonical_bar_lineage` followed. Afterwards the table has 7,046,147 live tuples and 0 dead.
- The plan expected 3,179,486 stale d2-v1 rows on 743 names. The measured figure is 3,164,270 on 740 names because 185-27's live run had already rewritten SPY, AAPL and XOM.
- The plan expected the 178 IBKR-owned names with late flags to show stale months. Only 31 IBKR-owned names did (214 months). The digest covers only non-quarantine flag rules, so a flag written after the digest changes a month only when it adds or removes a non-quarantine rule. The batch detail lists the 31 names.
- All 12 retired flags match the must_haves list: DBC 2007-08-17, EFA 2008-09-29, FXI 2007-02-27, FXY 2008-09-24, GLD 2007-09-10, IWM 2007-08-08, RSP 2007-08-01, SPY 2007-04-02, VWO 2007-05-02, VWO 2007-12-28, XRT 2007-09-18, XRT 2008-09-19. Each has its detail, stored source (tradier) and replaced `ohlcv_revision` row (old OHLCV, `old_source ibkr_named`, load_id) recorded in batch `04b04144-fc14-4f87-8bf9-66f759344cfe`. EFA 2008-09-29 (price_sanity) and XRT 2008-09-19 (ohlc_invariant) stay quarantined by their own rules. The re-digest of the 10 names inserted 0 rows, because legacy flags are quarantine flags and so are not in the digest.
- Batches: lineage `d08b89a5-d819-41b4-b753-59fa49f003da` (10 names) and `998fb6d8-24d6-478d-87f2-5091461d98b7`; digests `d7fdecf5-e78e-46a8-ab66-709d94c073d0`; retirement `04b04144-fc14-4f87-8bf9-66f759344cfe`. All four completed.
- Display quirk: in apply mode the lineage line prints `stored 0 needs_lineage 0` because those counts are read only in a dry run. The `lineage_rows` field is the applied count.

## Task 3: the 31 untraced IBKR bars

Before the re-ask there were 31 stored IBKR 1d bars with no lineage and no D1 observation, none of them quarantined: INDA 26 (2012-05-07 to 2012-12-17), OLED 4 (2013-02-20, 21, 22, 25) and RCAT 1 (2006-10-03).

Steps taken:

1. Confirmed nothing held the lease or lock (no `lease:` or `lock:` sessions in pg_stat_activity), the fetcher service and timer were inactive, and the gateway was authed ("Login has completed" 02:22 UTC).
2. A scratch harness held `FetcherLock` (holder `ops-185-30-reask:49`) and probed client 41: ping True, SPY qualified, head 1993-01-29.
3. The harness then ran `infrastructure_run_historical_pipeline.py --symbols INDA,OLED,RCAT --timeframes 1d --dimension compute_1d --client-id 49 --lease-tier priority`. Fetch run `f0afe2e0-86e6-4b6c-9188-5a013ffb9b5d` made 8 requests, captured 970 observations and had 0 fetch errors. The pipeline's own chained D2 stage (`--stage daily --symbols INDA,OLED,RCAT --apply`) then ran as batch `4cd4ffd4-e8ab-4144-bd99-1aada81b9992`, which completed with derived 2, tradier_owned 1 and 7 changed bars, all `missing`: new IBKR dates for OLED (+3) and RCAT (+4), and 0 value changes.
4. Before the run, a D2 dry run on the three names reported 0 changed bars.

Outcome:

- OLED, 4 bars: traced. The fresh SMART observations are equal to the stored bars, and D2 wrote d2-v1 lineage.
- RCAT 2006-10-03: traced. IBKR's answer extended before the requested window start and holds an equal flat bar (7462.6866, volume 0).
- INDA, 26 bars: still untraced. INDA is Tradier-owned (an accepted Tradier load), so D2 returns `tradier_owned` and never writes its IBKR lineage. Tradier holds no observation on those dates. The re-ask did land IBKR observations for all 26 dates: 25 are equal to the stored bar, and 2012-08-03 differs (stored high 21.69, IBKR now 21.68). All 26 bars have volume 0, so `market_data_ohlcv_tradeable` already hides them from compute reads. None carries a quarantine flag.

### Untraced quarantined 1d bars

None are quarantined. The 26 INDA bars below are untraced and unquarantined, which is a blocking finding for 185-33. Per the plan they were not flagged by hand.

INDA 2012-05-07, 2012-05-21, 2012-05-25, 2012-06-05, 2012-07-09, 2012-07-11, 2012-07-24, 2012-07-26, 2012-07-27, 2012-08-01, 2012-08-03, 2012-08-06, 2012-08-08, 2012-08-10, 2012-08-23, 2012-08-28, 2012-09-04, 2012-09-10, 2012-09-11, 2012-09-21, 2012-09-24, 2012-09-28, 2012-11-21, 2012-12-04, 2012-12-12, 2012-12-17.

Task 3's automated verify returns 26, not 0. That criterion is unmet. For 185-33, the general case is IBKR orphan bars on Tradier-owned names: 821 stored IBKR-source 1d bars on 260 Tradier-owned names are dates Tradier did not return (FISV 53, UNL 36, INDA 28, CFFN 22, VRT 20, ...). D2 skips these names, so no live writer owns these bars. 795 of them still carry d2-v1 lineage from before Tradier took the name over. INDA's 26 are the ones with none. 185-33 needs to decide one rule for this whole class: quarantine, a lineage rule for IBKR bars on a Tradier-owned name, or deletion through D2.

## Verification

- `pytest` on the new test, `test_canonical_lineage_digest_writer_boundary`, `test_market_data_ohlcv_boundary`, `test_market_data_ohlcv_writer_boundary`, `test_market_data_ohlcv_scrub_input_boundary`, `test_compressed_hypertable_write_boundary`, `test_tradier_daily_lineage`, `test_tradier_daily_plan` and `test_bar_derivation_daily`: passed. `pytest tests/unit -k boundary`: passed.
- ruff and black are clean on every touched file.
- Acceptance: tradier bars without tradier-v1 lineage = 0; post-apply `--digests` dry run = 0 stale months (rerun after task 3's D2 run, still 0); 1d legacy flags = 3; intraday legacy counts unchanged. Task 3 verify: 26 (unmet; see above).
- Not run: `repro_frozen` (nothing under `src/intelligence/research/` or `statistics/` was touched) and the full `pytest tests/unit/`.

## Deviations from plan

### Auto-fixed issues

**1. [Rule 3 - Blocking] Raw market_data_ohlcv boundary allow-list entry**
- The script reads raw `market_data_ohlcv`: lineage and digests must cover zero-volume provider bars (INDA's 2012 bars are volume 0), and the legacy read joins a flag to its stored source. `test_market_data_ohlcv_boundary` failed until the script was allow-listed with that reason. The plan's files list did not include the test.
- Commit: a39e1cdec. Commit 43baa915d, which precedes it, fails this test on its own. Neither is pushed.

**2. [Rule 2] Dry-run exit code on unmatched bars**
- A dry run exits 1 when unmatched bars exist, the same as apply, so a finding is never a silent 0. None occurred.

**3. [Rule 3] Fetcher lock around the re-ask**
- The plan's path (`infrastructure_run_historical_pipeline.py`) takes the `ibkr_history_stream` lease but not the phase 189 `FetcherLock`. A scratch harness (not committed) held the lock for the probe and the pipeline subprocess. No phase 189 file was edited.

### Plan expectations that differed from the data

- The re-ask covered more than the 31 dates. The pipeline asks every D1 gap in its 7,300-day window. RCAT had 465 gap sessions (776 observations from 2006-10-12 to 2013-09-26), OLED 3 and INDA 25. That came to 8 requests and 970 observations in total.
- The plan worried that RCAT 2006-10-03 sat outside the 1d depth window (7,300 days reaches back to 2006-10-11). IBKR's answer extended earlier and covered it.

## Known stubs

None.

## Threat flags

None. Every write path, role and table was in the plan's threat model.

## TDD gate compliance

- RED: 6f949a32f, which failed on import before the script existed.
- GREEN: 43baa915d.

## Commits

- 6f949a32f test(185-30): failing tests for the 1d lineage, digest and legacy-flag repair script
- 43baa915d feat(185-30): one-time 1d repair script for Tradier lineage, digests and replaced legacy flags
- a39e1cdec test(185-30): allow-list the 1d repair script's raw market_data_ohlcv reads

## Self-Check: PASSED

The created files exist and all three task commits resolve in `git log`.
