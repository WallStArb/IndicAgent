---
status: pending
priority: P0
filed: 2026-11-07
source: owner ruling 2026-11-07 (reverses the 2026-11-04 decision not to buy pre-2016 history)
---

# Onboard Massive flat files as a vendor: all symbols, all history

## What

Owner 2026-11-07: "no reason not to have it and use it". Buy one month of the Massive Stocks
Advanced plan and keep every flat file. Owner 2026-11-09 sets the scope: both SIP aggregates
(`us_stocks_sip/minute_aggs_v1`, `us_stocks_sip/day_aggs_v1`) at full depth (2003-09-10) to
the present day. The files are unadjusted consolidated SIP. They replace the IBKR pre-2016
bottleneck (about 4 names an hour) and, for the first time, bring in delisted names.

## State (2026-11-10)

- Plan purchased; the paid S3 key is in `.env` as `MASSIVE_S3_*` (the dashboard
  `MASSIVE_API_KEY` is separate).
- Inventory: 5,829 trading days per dataset, minute 86.8 GB and day 1.0 GB, matching the NYSE
  calendar with no missing or extra days. Serve times (LastModified, ETag) for every key are
  in `data/massive/manifest/servetimes_*.jsonl`.
- Full download complete 2026-11-10: all 11,658 files (82 GiB) in `data/massive/files/`, manifest
  records for every inventory key, `--verify` re-hashed all of them with 0 defects. Downloader:
  `scripts/infrastructure/massive/massive_download.py` (credentials on stdin since 15719adb0).
- No separate pilot (owner 2026-11-10: Massive is used regardless). The checks that decide how names
  and spans load are section 8a of the admission design; the old runbook is archived
  (`docs/plans/archive/2026-11-09-massive-pilot-basis-study.md`).
- Admission design, ruled by the lead: `docs/plans/2026-11-10-massive-admission-db-design.md`.
  It is the admission-day execution plan, covering the vendor and kinds, the reader, the 5m
  rescale, the ticker map, the policy switch, and the docs that move with it.

## Rulings in force

- Massive is the yardstick (owner 2026-11-10). Disagreements count as incumbent defects only
  when a third witness agrees (design section 8a).
- Survivorship is measured and disclosed, never a gate (owner 2026-11-10: "there's no better
  option - its the best choice regardless if 70% or 100%").
- Raw is a mapped projection: the archived files are the as-served, ticker-keyed record, and
  a Massive load whose identity premise was wrong can be retracted by load id. This is a law
  528 amendment that the owner rules on together with the admission verdict.
- Pre-2016 5m: Massive primary with no default IBKR fallback; IBKR serves only the gap-list
  names, through symbol rows.
- Canonical stays split-adjusted: selection rescales Massive rows from `corporate_action_current`,
  pinned by a recorded-at horizon. Massive's splits endpoint, captured by a parallel lane,
  is the reconciliation input.
- Storage (lead 2026-11-09): the vendor files as delivered are the keep-everything artifact;
  1m loads into raw only if a hypothesis needs it. A Parquet mirror of canonical is a measured
  decision at the corpus-rerun pilot, not a default build.
- No corpus compute until the data is complete (2026-11-04). The IBKR 5m backfill runs until
  admission and stops then.

## Open

1. Backup of the files and the raw dumps, mandatory before the plan lapses (the files cannot be
   replaced afterwards). Destination (owner 2026-11-10): the owner's second machine (HX370, 64 GB,
   2 TB), pending setup. Until it is up the archive has one copy. Shape when it is: copy
   `data/massive/files/` and `data/massive/manifest/` with checksums, then run the downloader's
   `--verify` against the copy (manifest sha256 is the proof), keep the copy read-only.
2. The owner's admission call (bundled with the law 528 amendment); no verdict step.
3. Admission execution per the design doc, section 8.
4. Deletion list after admission (owner 2026-11-07, strengthened 2026-11-10; Opus review
   before anything runs). Candidates: the IBKR pre-2016 leg (the 534 campaign and its fetcher
   lane), the 596 ask-ledger readers, the completeness gates the file manifest replaces, the
   per-era `bar_source_policy` matrix if one vendor suffices, and the IBKR gateway itself (the
   container, the 607 mitigation, the 544 upgrade decision) if IBKR keeps no data role.
   Delete mechanism, never data.
5. Measured decisions, later: consolidating the nightly update onto Massive (publish lag from
   runbook A12; Alpaca nightly is the incumbent); post-2016 consolidation onto one vendor;
   stage 2 universe (dead names, point-in-time membership, the key rule for reused tickers).
6. Layer refinements not covered by the design doc: session calendar as data (RTH, the 23/5
   SIP session from 2026-12-06, holidays and early closes, read by selection); `trade_count`
   (Massive `transactions`, Alpaca `n`) and Alpaca `vw` as nullable raw columns, kept out of
   compute until a consumer exists.

## Progress 2026-11-11 (session 9ffac575)

Raw loads 2024 to 2016 done through the bulk path (02f14f247), RAW-ONLY with selection deferred. Per year: 1d and 5m loaded all new, windowed compare 0 real differences before and after, canonical unchanged, unselected delta equal to the dry-run Massive-only count (2023 33, 2022 57,444, 2021 63,603, 2020 1, 2019 4,677, 2018 22, 2017 3, 2016 2,369), disk 626 GB free after. Rate 33-37k new rows/s. Spans trim to the first and last present session; gap days are reported in `logs/massive_apply_*` and the dry-run reports. 
## Progress 2026-11-12

Raw loads 2026, 2025 and 2015 to 2003 done (sweep DONE 2026-11-11 23:44Z), same gate per year: compare 0
real differences, canonical unchanged, unselected delta equal to the dry-run count (2015 5m 4,610,064;
2014 4,108,883; 2013 3,609,520; 2012 3,260,535; 2011 2,998,233; 2010 2,794,286; 2009 2,547,327; 2008
2,446,678; 2007 2,174,258; 2006 8,553,383; 2005 10,500,813; 2004 9,738,529; 2003 2,837,988; 2026 56; 2025 39).
All 1d and 5m years 2026 to 2003 are now in raw (403.3M Massive rows), 617 GB disk free. Outstanding: the
section 8a load checks, then step 7 on the lead's call (tooling landed at 1561842d7).

## Ruling 2026-11-12 (lead): keep the IBKR 5m raw rows

The deletion list in Open item 4 does NOT include `ohlcv_raw` rows of vendor ibkr (5m 224.7M rows 2006-06 to 2026-11, 1m 9.8M). They are the only independent witness to Massive: Alpaca shares Massive's upstream (Polygon SIP) in every year, so a Massive defect is invisible to it, and pre-2016 Massive stands alone. The incumbent-defect rule (third witness) and the 8a and 592-class adjudications need it. Keeping costs about nothing (37 GB raw table, disk 29 percent used) and, once step 7 switches policy, the rows are never selected. What does go: the IBKR 5m fetch lane, the ask-ledger and coverage machinery that only chases it, and the timers (item 4's other candidates). Revisit after step 7, the 8a checks and the 592 adjudications; if the rows were never used as a witness, export to a cold gzip archive first and delete only under disk pressure. This narrows the owner's 2026-11-10 reversible-first deletion note; nothing is deleted before the rebuild proves itself either way.

## 8a load checks, first full run 2026-11-12 (worker branch worktree-agent-a982cb955333e9a38, runner not yet landed)

Runner built in three stages and run on the full archive (about 50 minutes). Systemic results: manifest complete (5,829 of 5,829 per dataset), session ok (8 isolated bad days of 527 drawn, no systematic offset), record sanity stop (51 non-positive rows: 50 unowned empty-ticker junk rows and one real QQQ 2004-07-28 low 0.0), volume bands stop (38 of 110 era-by-exchange cells, a smooth drift not a step), vendor-wide price agreement stop in 2003 to 2025, day file against minute file: every era over the 1 percent limit so 1d is built from RTH minutes.

Lead rulings (2026-11-12): (1) the stops on record sanity, volume and price agreement are gate-design artifacts, not Massive defects: unowned rows are not a stop, volume drift is a labelled definition difference (todo 518) and only a step or an out-of-range ratio stops, and level agreement against IBKR is confounded by IBKR non-split adjustments (constant level factors) and the day-file close, so agreement is judged on RTH-built 1d and on level-invariant returns, with constant-factor name-years classed as adjustment-level; (2) REVERSED later the same day: Massive 1d stays the served day file (the official close; RTH minutes cannot reproduce it), see todo 610; (3) a revision round is with the worker; the runner lands on main after an independent review.

## Owner 2026-11-12: the IBKR 5m backfill is ended permanently

The campaign will never reach the universe Massive covers (36,735 tickers against 1,529) and costs weeks of throttled requests for a weaker source, so it does not resume: `indicagent-ibkr-history-fetcher.timer` stays disabled (since 2026-11-10; the last run ended 2026-11-11 with 688 items deferred). The stored rows (224.7M, 1,529 names, partial pre-2016) remain a spot-check witness only. The fetcher lane, its ask-ledger and coverage machinery and the timer unit go on the deletion list after step 7, with the Opus review.

## Ruling 2026-11-12 (lead, after the owner's challenge): delete the IBKR 5m raw rows after three gates

Supersedes the "keep" ruling above. Once the 8a spot check has run and its results are archived, Massive is the source of truth and a witness we will never complete (no more fetching) is not worth carrying. Delete `ohlcv_raw` rows of vendor ibkr, timeframe 5m (224.7M rows; the 1m rows, 9.8M, follow the same rule) and their `ohlcv_revision` and `ohlcv_coverage` lineage, as an excluded-source deletion with a tombstone (vendor, reason, date, todo, row counts), the shape of migration 589. Order, because IBKR rows still feed selection until the policy switch:
1. The 8a runner's final results are landed and archived as records (flags register, era tables, the disagreement ledger), so the spot check outlives its data.
2. The split and wick sweeps with Massive as witness (todos 608, 592, 595) are done, since they use IBKR as the independent arm.
3. Step 7 stage 2 is proven (IBKR retired from 5m selection, byte-exact reproduction and the seam witnesses pass), so no canonical row depends on an IBKR raw row.
Then: a gzip export to `data/backups/` first (one file per year, manifest sha256, cheap insurance), then the migration, then `ops_selection_gate --compare` to show canonical unchanged. The 1d IBKR raw rows are NOT in this deletion (they are the 1d fallback and witness for 1998 to 2003 and gap names) and get their own decision at the deletion-list review.

## 8a load checks, round 4 (commit ca319f428 on branch worktree-agent-a982cb955333e9a38; independent review running)

Era stop now follows the design text: only the unexplained `other` class above 0.5 percent stops an era, unless a dominant exchange (share at least 0.6, lift at least 3) or at most 50 names explain it; last_print, rounding, time shift and scale are labelled classes. Result on the full archive: systemic checks ok (record sanity, session, volume bands, manifest complete), vendor-wide return agreement ok, partition pass 17,597, flagged 12,804, unresolved 3,079, stop 0 (33,480 cells). 2014 to 2026 ok on both timeframes; 2008 to 2013 ok after flagging (1d 2008 ARCX ETF convention, 1d 2009 six names); 2003 to 2007 1d is the unresolved close-convention bucket (all 3,079 unresolved cells). Detector coverage: IBKR 1d 94 to 100 percent every era; IBKR 5m 0 percent 2003 to 2005, 74 to 83 percent 2006 to 2015, about 30 to 33 percent from 2016. Open: a third witness for the 2003 to 2007 close convention; 2013 5m other residual sits in many names with no explanation. Gate before step 7: the independent review, then land the runner on main.

## 8a independent review of ca319f428: verdict NO, round 5 in progress (2026-11-12)

The review (read-only, adversarial) proved by synthetic injection that a systemic price defect could not stop an era (x100 on 200 names, a missing mid-year split, a close 5 percent wrong on 30 percent of days all passed): returns are level-invariant, level-class names left the clean set, an empty clean set passed vacuously, and `last_print` had no size cap or range test. Also: round 4's rule inverted the written spec (2008 1d, 69 percent of judged names flagged, passed as ok_after_flagging), the dominant-exchange branch did not re-test the remainder and used today's listing, the 2007 unresolved boundary was hardcoded where 2008 to 2013 sits in the same middle regime, flags were inflated by not_listed and no_incumbent_overlap cells, 134 active names (GOOGL, BRK.B, ACN, LIN) sit outside the partition, resumed parts could mix inputs, and the run held one hours-long transaction. The 2014 to 2026 numbers are clean (1d residual at most 0.07 percent apart from 0.26 percent in 2019; 5m at most 0.07 percent). Lead response: design amendment round 5 (thresholds calibrated on the 2014 to 2026 reference and declared before the rerun), worker fixes F1 to F9, full rerun, then a re-review. Step 7 waits on that review; if it fails again, step 7 proceeds on 2014 onward only.

## 8a gating run r5j (2026-11-13, lead): verdict and two named findings

Partition (runner r5j, full 2003 to 2026): Massive admitted for 1d 2014 to 2026 and 5m 2003 to 2006, 2009 to 2012, 2014 to 2026; stopped (keep the incumbent, canonical unchanged for that era) 1d 2004 to 2013 and 5m 2007, 2008, 2013.

- 1d 2005 to 2007: the close-definition witness reads clearly (IBKR close matches the last trade on 83 to 85 percent of days against 41 to 46 percent for the day file), yet the eras stop because about 15 percent of days match neither print. Served from the incumbent for now; the one-definition goal stays open in todo 610.
- 5m 2013: the stop is one window, not the era. AZO 5m close/high/low disagreement is about 2 percent a month through November 2013, 40 percent in December 2013, 8 percent in January 2014, normal by February. In December 2013 Massive's RTH 5m daily high equals the official day-file high on 21 of 21 days; IBKR 5m and IBKR 1d match on 57 percent. The defect sits on the incumbent side around the odd-lot tape change (2013-12-09), but the only witness is Massive's own day file, so no incumbent-defect call is made. Disposition: the pre-registered stop stands (2013 5m keeps IBKR); the window 2013-12-01 to 2014-02-01 is registered as a known incumbent defect span that research compute must not trust until an independent witness settles it. Measure the window across names before registering it (top contributors are high-priced names: AZO, MKL, REGN, GWW, AMG, MA, MTD, BIO).

## OWNER RULING 2026-11-13: IBKR is removed entirely

"Why do we need IBKR? There's definitely not IBKR data that Massive doesn't have." Measured before the ruling: the only IBKR data Massive lacks is 1d from 1998-12-28 to 2003-09-10 (703 names, about 672k rows: survivors only and on IBKR's pre-2008 last-trade close definition, so dropped too); the 22 instruments outside Massive (futures, FX, VIX) are already inactive with no canonical bars; the roughly 110 names with no FIGI or no IBKR contract have their bars in Massive and need only the identity map. Ruling: canonical = Massive 2003-09-10 to 2016-01-04, Alpaca from 2016-01-04, no IBKR default, symbol row or fallback anywhere; canonical starts 2003-09-10. Spans the identity map cannot place (gap list) are gaps, never IBKR. The 8a stops become disclosed flags in the data register, not a source switch. IBKR raw bars: export to one compressed dump in data/backups, verify it restores, then delete every IBKR row (owner choice "export, then delete"). The gateway container, provider code, fetcher lane, ask ledger and todo 544 retire.

Order (lead): step 7 with the no-IBKR policy -> its checks pass -> export and restore-verify -> delete IBKR raw -> retire code, gateway and docs. Raw stays in the database until the rebuild is proven, as the rollback.

Consequences: the 8a runner (branch massive-8a-load-checks) compares against IBKR and cannot run after the deletion, so it is not landed: tag archive/massive-8a-load-checks, keep the r5j and r5k out dirs as the admission record (copied to data/backups). The per-era plan builder (branch step7-plan-8a-input) is likewise archived; step 7 uses a single-policy plan with no 8a input.
