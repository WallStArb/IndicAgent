# IBKR 1d raw deepening (scoped full-scan pass)

Author: Claude (main session, 2026-10-16)
Informed by: ohlcv_raw measurements 2026-10-16; todo 535 item 42 (basis class fix); phase 191
plans 14 and 20; `scripts/infrastructure/backfill/_fetch_queue.py`, `_history_fetch_item.py`,
`_d1_gaps.py`
Status: armed 2026-10-16: `scripts/ops/bars/ops_ibkr_1d_deepening_gate.sh` from bg's crontab
(`11,41 * * * *`, self-removing on completion) launches and retries the pass unattended; an
in-session monitor reports while a session is open (todo 537)

## Problem (measured 2026-10-16)

The ibkr plane's unadjusted 1d raw history is shallow for most of the universe while the fetch
machinery to deepen it already exists:

- `ohlcv_raw` 1d, `kind <> 'smart_adjusted'`: 1,135 of 1,529 names start later than their own
  ibkr 1d head floor (in `ohlcv_provider_head`, median 2000-01-03, min 1980-03-17) plus 7 days.
- Estimated missing sessions to the per-name floor: about 3.66M bars.
- Consumers: the 19 damaged basis names wait for exactly this deepening before the follow-up
  scan can restore them to the unadjusted ibkr basis (todo 535 item 42); plan 20 deletes every
  Tradier row and records first-bar changes, so deepening first means no history loss wherever
  IBKR serves the span; the pre-2023 canonical span can eventually select unadjusted ibkr
  instead of back-adjusted tradier.

The old deep 1d fetch used `ADJUSTED_LAST` (931 names, start 2006-10-05); `smart_adjusted` rows
are excluded from 1d coverage by `DAILY_NOT_COVERAGE_KINDS`, so those names are deepening
candidates too, not just the never-deepened ones.

## Why the standing queue will not finish this

The item planner already plans full depth correctly: `--full-scan` plans every item from
`today - depth_days` (APR `infra.backfill.depth_days.1d` = 9800 days, about 1999-12), the 1d gap
detector asks every missing NYSE session below the vendor's own unadjusted earliest row, and
windows entirely at or before the verified head floor skip. The limiter is cadence, not code:
without `--full-scan`, only a series' weekly gap-fill slot (`infra.backfill.gap_fill_interval_days`
= 7) plans full depth, and the fetcher has been held or paused for much of the recent weeks.
Measured effect: 456 names deepened via old-window asks since 2026-10-06; 366 names answered
`no_data` (their floors are now recorded evidence, todo 526's measured floors).

Note: the queue's `coverage_gap_days` ranks the gap against the symbol's proven depth within the
ibkr plane only, so these items show gap 0 in the ranking. That is a ranking blind spot, not a
planning one; due-ness comes from the 1d daily rule, and with `--full-scan` every queued item
plans its true full-depth window.

## Execution

One scoped pass of the standard fetcher, no code change:

```
cd /home/bg/dev/indicagent && .venv/bin/python scripts/infrastructure/backfill/ohlcv_history_fetcher.py \
  --dimension compute_1d --timeframes 1d --full-scan
```

- Dry run validated 2026-10-16: 1,502 candidate series resolve under `compute_1d` + `1d`
  (`logs/ibkr_history_fetcher_dryrun_20261016T121106.tsv`).
- Budget: APR `infra.backfill.run_budget_minutes` (240 min) per run; relaunch each gate-check
  cycle while the cohort remains. Expected totals: about 2 requests per name (1d chunk size is
  7300 days), roughly 2,300 requests, about 26 hours of stream time at the measured 88 req/h,
  stretched over roughly 2 days wall clock while timer runs interleave.
- Interleaving: 1d items outrank the 5m tail by rank design; the timer's regular runs continue
  making 5m tail and nightly reconcile progress between deepening runs. Canonical 1d catch-up
  continues (full-scan items include the overlap verification asks).
- The 27 unpromoted names are outside `compute_1d` and stay shallow; plan 20's first-bar record
  covers them.

## Gates (checked before every launch)

1. Cutover window two closed: `scripts/ops/bars/ops_raw_cutover_window.py status` shows no open
   window, and `indicagent-ibkr-history-fetcher.timer` is active (plan 14 resumed the units).
2. Clean tree on the fetcher's import surface (fingerprint rule, `code_content_key`):
   `git status --porcelain -- scripts/infrastructure/backfill scripts/ops/bars src/intelligence/bars src/providers`
   is empty.
3. No fetcher process already running (FetcherLock serializes; a lock-held exit is retried next
   cycle).

Interlock: if a cutover window opens while a deepening run is in flight (plan 24 opens one for
fetcher-imported script edits), kill the run before that plan edits its imports.

## Completion and verification

- Cohort query (re-run until stable): names where
  `min(ohlcv_raw.timestamp) WHERE timeframe='1d' AND vendor='ibkr' AND kind <> 'smart_adjusted'`
  exceeds their `ohlcv_provider_head` 1d `head_ts` + 7 days. Done when two consecutive passes
  fetch no bars (remaining names are `no_data`-confirmed floors).
- `ops_capture_completeness` (R6) and the nightly D7 audit stay clean; the selection gate exits 0.
- After completion: re-run the todo 535 item 42 basis follow-up scan and restore the eligible
  damaged names; record the new first-bar facts for plan 20's Tradier deletion accounting.
