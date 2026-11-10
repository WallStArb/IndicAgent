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
