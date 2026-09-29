---
status: pending
priority: P1
filed: 2026-09-29
source: todo 449 pace check (2026-09-29): 5m lane about to start, backfill writes about 5.5x more rows than IBKR returns
---

# Stop storing synthetic-fill bars; record coverage in a ledger instead

## What

`normalize_bars()` (`src/core/bar_normalizer.py`) inserts a flat bar (OHLC = prev_close, volume 0,
`source='synthetic_fill'`) for every interval slot with no real bar, on a continuous 24x7 calendar
grid, and the backfill stores them in `market_data_ohlcv`. Measured on the last 60 days: 1m, 5m,
15m and 1h are 81% to 83% placeholders; 1d is 33%. ETN 1h "stored 175175 bars" for 2006 to 2026 is
the full hourly grid, 4x that for 15m; IBKR did not return that many bars.

Why it is the wrong design here:

- Breaks `no_fill` (unified design section 12): fabricated rows sit in a permanent raw table and
  every reader must remember `market_data_ohlcv_tradeable`. A raw read that forgets it gets a
  silent wrong answer.
- The grid ignores sessions, so about 81% of slots are closed hours and "N gaps detected" is an
  artifact of the grid, not missing data.
- Stores use `ON CONFLICT DO NOTHING`. If a slot holds a synthetic bar and a real bar arrives
  later (old-venue routing per the CLAUDE.md listing-venue note, a late provider correction), the
  placeholder wins. Unverified; the mechanism is there and it fails silently.
- Cost: about 5.5x the rows of the real data in storage, WAL, compression and write time. The 768
  GB disk-full incident (migration 312) was this table.

What the fill provides is a coverage record ("this range was fetched, nothing traded"). That
belongs in a ledger at O(windows), not O(bars). `backfill_status` and `ohlcv_empty_history` are
partial versions of it.

## Steps

1. Consumer audit first (read-only). Who reads `market_data_ohlcv` raw, `synthetic_fill` or the
   canonical grid: `BarAuditor`, `bar_writer`, `bar_aggregator`, `bar_derivation` (already
   excludes `synthetic_fill`), `bar_history_seeder`, `backfill_feature_factory`,
   `_empty_history.py`, the streaming path, and the callers in
   `tests/unit/test_market_data_ohlcv_boundary.py`. Output: which need a contiguous series and
   which only need real bars.
2. Confirm or refute the late-real-bar hazard: find a slot with a `synthetic_fill` row where a
   real bar exists upstream, or prove the write path replaces the placeholder.
3. Design the coverage ledger (one row per symbol, tf, fetched window, real-bar count, fetched-at)
   and decide whether it extends `backfill_status` or is new. Gap-aware fetch reads the ledger,
   not the presence of filled slots.
4. Read-time grid: where a consumer needs a contiguous series, build it from real bars plus the
   exchange session calendar; derived, rebuildable, never stored.
5. Stop calling `normalize_bars()` in the backfill paths (`infrastructure_run_historical_pipeline.py`
   store pass and the one-time normalization pass, `backfill_feature_factory.py`).
6. Migration deleting `source = 'synthetic_fill'` rows: compressed hypertable, so
   decompress, delete, recompress, then a bare `VACUUM market_data_ohlcv;` last (CI-enforced,
   `docs/foundation/timescaledb-compressed-column-migration.md`). Measure chunk count and disk
   headroom first (performance SOP).

## Timing

Ideally lands before the todo 449 5m lane starts (HTF lane on attempt 23, about 221 of 698
symbols on 2026-09-29; the 5m lane follows in `intraday_chain.sh`). That avoids about 0.8B
placeholder rows for the 458 missing 5m names. Editing the backfill script while a run is going:
`ic_engine` does not import it, but confirm before the edit. Step 1 and 2 can run now with no
edit.

## Related

Todo 449 (intraday backfill), todo 453 (pipelined persistence), todo 124 (tradeable view), todo
433 and phase 185 (backfill and `ohlcv_empty_history`), phase 186 (deletes the legacy
`forward_returns` table; check whether it also touches this).

## Findings, steps 1 and 2 (2026-09-29)

Step 2, the late-real-bar hazard, is confirmed and measured, not just possible.

- Both writers (`store_bars` in the historical pipeline, `services/bar_writer.py`) insert with
  `ON CONFLICT (timestamp, symbol, timeframe) DO NOTHING`, so a stored placeholder is never
  replaced by a real bar.
- MSFT 15m, 2024-08-06 12:45 to 15:45 ET: 12 consecutive regular-session slots are
  `synthetic_fill` with volume 0, while SPY has real bars for the same slots. In the same window
  MSFT 5m has 36 real bars (2.81M shares) and 1h has 3 real bars (3.90M shares). MSFT traded; the
  15m table says it did not.
- Scale, 2024 only, 15m: 35,454 placeholder rows across 100 symbols have real 5m volume in the
  same slot (3.86B shares hidden). Only names with 5m history are counted, so the true count is
  higher. For SPY, AAPL, QQQ the regular-session 15m placeholders (283 each) match holidays and
  half days, so liquid names are mostly clean; the damage sits in the mid and small names.
- Cause of the MSFT gap is not established (missed fetch then fill, versus a provider hole). The
  design makes either permanent.

Step 1, consumer audit (source: `_ALLOW_LIST` in `tests/unit/test_market_data_ohlcv_boundary.py`
plus greps). Raw-table readers that depend on the placeholders and must change with the ledger:

- `infrastructure_run_historical_pipeline.py`: `_detect_gaps` treats a prior synthetic fill as
  "already handled" so closed weekend and holiday slots are not re-requested from IBKR. This is
  the coverage bookkeeping the ledger replaces. It is also why the hazard above is silent.
- `services/bar_auditor.py`: counts all rows including placeholders to find calendar gaps. Needs
  the ledger plus a session calendar for the same answer.
- `scripts/ops/pipeline/ops_pipeline_status.py`: wants the full grid, gaps are the signal.
- `infrastructure_truncate_derived_tables.sh`: re-seeds `backfill_status` from the full grid
  after a truncate. Re-seed from the ledger instead.
- `infrastructure_nightly_backfill.py` (`_select_stalest`): ranks by latest raw bar, proxy only.
- `infrastructure_ibkr_chunk_and_rate_limit_probe.py`: "has any row" check, needs the ledger.
- `services/bar_derivation.py`: archives and deletes stored 15m/1h segments, placeholders
  included. It already excludes `synthetic_fill` from what it archives; the delete and checksum
  logic must be re-checked once no placeholders exist.
- Display surface `src/api/routes/market_data.py`: needs a decision (session-calendar grid at
  read time, or show real bars only).
- Dead v2.x code (`signal_replay_auditor`, `signal_probe_auditor`, `debug_batch_agent_memory`):
  no action.

Also call `normalize_bars`: `services/backfill_feature_factory.py`, `services/bar_aggregator.py`,
`src/providers/ibkr.py`, `src/providers/ibkr_adapter.py`, `src/intelligence/services/bar_history_seeder.py`,
`src/core/schemas/bar_message.py`. Not yet read; the streaming ones (aggregator, adapter, seeder)
may need fills for a streaming series and are the open question for step 4.

Remaining: read those normalizer callers, then steps 3 to 6. Steps 5 and 6 should wait on the
gap-detection replacement, because removing the fill without the ledger makes `_detect_gaps`
re-request every closed slot forever.

## Step 3 design: the coverage ledger (2026-09-29)

Decision: a DB table, a new one. `backfill_status` is one row per (symbol, tf) with a
`fetch_complete` flag, so it cannot say which windows were fetched. `ohlcv_empty_history` records
only the leading empty range before a provider's first bar. Neither answers "was this window
fetched, and did it return anything", which is what `_detect_gaps` currently infers from the
presence of placeholder rows.

Why DB and not a file: the coverage row must commit in the same transaction as the bars of the
chunk it describes (a coverage row without its bars is a silent loss; bars without a row are only
a re-fetch); the auditor, the backfill lanes and the nightly all read it; concurrent lanes would
race on a file. Size is tiny (one row per fetched chunk, merged when adjacent), so not a
hypertable, no compression, no VACUUM concern.

Shape, named per the naming system as `ohlcv_fetch_coverage` (confirm against
`docs/foundation/naming-system.md` before the migration):

- key: `(symbol, timeframe, provider, window_start)`; columns `window_end`, `n_real_bars`,
  `outcome` (`ok` | `empty` | `error`), `fetched_at`, `provenance` (`fetch` | `seeded`).
- `window_end` is exclusive; adjacent `ok` and `empty` windows for the same key are merged by the
  writer.
- an `empty` window (fetched, provider returned nothing) is what stops closed weekends, holidays
  and pre-listing ranges from being re-requested; it replaces the placeholder-as-bookkeeping role.
  It is a window, not a slot, so no session calendar is needed for gap detection.
- gap detection = requested range minus the union of `ok` and `empty` windows. `error` windows
  are never subtracted.
- single writer: the historical pipeline's store path, one connection in main (workers stay
  compute-only). The chunk persist and its coverage row go in one transaction.

Seeding (the open part). Seeding coverage from existing rows would legitimize the bad windows
(the MSFT 2024-08-06 hole is inside a stored run). Recommended: seed at (symbol, tf, day)
granularity from real bars only, `provenance='seeded'`, and treat a session day with no real bar
as uncovered so it is re-fetched. Separately, repair the known masked 15m slots (35,454 in 2024
alone) by deriving 15m from real 5m where 5m exists, using the `bar_derivation` path, and
re-fetching the rest; the 5m-against-15m mismatch is the detector. Decide whether seeding needs
the session calendar (`src/` has none for this yet; check before assuming).

Steps 4 to 6 change accordingly: read-time grid only for the API route and any streaming
consumer step 1 shows needs it; stop calling `normalize_bars()` in backfill only after the
ledger drives `_detect_gaps`; the delete migration runs last and ends with a bare `VACUUM`.

## Revision to the step 3 design: use phase 185's `ohlcv_request`, no new table (2026-09-29)

The step 3 design above proposed a new `ohlcv_fetch_coverage` table. That duplicates a table phase
185 already built. `ohlcv_request` (plans 185-02/03, written since 185-09 on 2026-09-28) records one
row per provider request: symbol, timeframe, route, `window_start`, `window_end`, `outcome`
(`bars` | `no_data` | `timeout` | `failed`), `n_bars`. Coverage is the union of `bars` and
`no_data` windows; `no_data` is the "fetched, nothing there" case that stops closed slots being
re-requested. Keep the gap-subtraction rule from the design (`timeout` and `failed` never
subtract) and drop the new table.

Limits found (2026-09-29): `ohlcv_request` holds 5,948 rows, all since 2026-09-28. It says
nothing about the historical 2006 to 2026-09-27 fetches, so the seeding problem in the design
stands. `window_start` is populated for every historical-pipeline row, but confirm a `bars`
window guarantees the whole range was answered (IBKR chunking) before gap detection trusts it.

Phase 185 overlap, and where this todo belongs (recommendation: absorb into 185, not a parallel
track):

- D-15 (UD-25, todo 446): the derivation writes 15m and 1h from 5m on session-anchored edges; the
  stored IBKR 15m/1h become raw observations. That decides what a synthetic 15m/1h row means, and
  the repair of masked 15m slots here is the same derivation.
- 185-12 (write-path switch) and 185-20 (intraday verify-only, empty history, gated recovery) are
  the natural homes for dropping the fill and switching gap detection to `ohlcv_request`.
- D-26 / 185-23 daily audit: add "session-slot with placeholder while a finer timeframe has
  volume" as a reconciliation check; it is the 15m-versus-5m mismatch query used here.
- Timing conflict: 185 is at 11/24 with wave 3 next and the dispatch is paused on quota, while
  the 5m lane starts when the HTF lane ends (about 10 hours after 2026-09-29 18:30 UTC). The
  interim decision for the 5m lane (stop the fill via a flag, or accept the placeholders and
  delete them under 185) is the owner's.

## Council design (supersedes the two design sections above where they differ, 2026-09-29)

Principles, in order:

1. A stored bar is an assertion about the market. Store only what the provider observed. Absence
   is typed and lives elsewhere: not fetched (no `ohlcv_request` window covers it), fetched and
   empty (`no_data`), market closed (`nyse_sessions`, `src/intelligence/bars/sessions.py`, built
   in 185-06; never stored), provider hole (found by reconciliation, below). The fill turns all
   four into the positive claim "price unchanged, volume 0", which is wrong for the last one and
   for every closed slot.
2. Redundancy is error detection. Independent measurements of one quantity must reconcile: a
   coarser bar equals the aggregate of its finer bars, and daily volume equals the intraday sum.
   A mismatch is an alarm, never resolved by first-write-wins. The 35,454 masked 2024 slots were
   visible only because a finer timeframe happened to exist.
3. One writer, pure function. Canonical bars = f(observations, rule version), the 185 D2 model
   already used for 1d and D-15 for 15m/1h. A rule that cannot emit a placeholder makes the
   hazard impossible by construction, and replaces `ON CONFLICT DO NOTHING` (first write wins,
   stale on revision) for canonical rows.
4. Fail loud at the write. A session window that returns zero bars for a name with earlier
   volume is recorded and flagged, not filled.
5. Delete only after proof. The migration removing `source = 'synthetic_fill'` runs after a
   check that the digest of the real rows (`bar_content_digest`, 185-06) is identical before and
   after, per symbol and timeframe.
6. Measure before acting. First run the 15m-versus-5m mismatch over all years and every
   timeframe pair (1m to 5m, 5m to 15m, 15m to 1h, intraday to 1d) to size the provider-hole
   rate; 2024 alone was 35,454 at 15m.

What this deletes: the fill, the `normalize_bars` store path and the one-time normalization
mode in the backfill, presence-of-a-row gap inference, and placeholder counting in
`bar_auditor`. What it adds: no table (coverage is `ohlcv_request`), one reconciliation check
(185-23), and the derivation rule reused for intraday.

Open question the council did not settle: the HTF lane spends the single IBKR history stream on
15m and 1h that D-15 will derive from 5m. Independent 15m/1h are worth keeping as a sampled
reconciliation set (they size the hole rate per timeframe), not as a full-universe duplicate.
Let the current HTF run finish; 185-20 decides whether further redundant fetches are scheduled.

Interim for the 5m lane (owner's call): two changes, both behind the Done-Coding gate. A flag on
the pipeline that skips the fill store, passed only by `intraday_5m_lane.sh` (not yet running, so
safe to edit; do not touch `intraday_chain.sh` or the HTF lane script while their loops run),
and `detect_gaps` subtracting `ohlcv_request` windows with outcome `bars` or `no_data`. The
default stays the old behaviour, so the running HTF loop is unchanged.

## Interim built (2026-09-29): `--real-bars-only` and answered-request coverage

Landed for the 5m lane, default off so the running HTF loop is unchanged:

- `scripts/infrastructure/backfill/_request_coverage.py`: `load_answered_windows()` reads
  `ohlcv_request` (SMART, TRADES, outcome `bars` or `no_data`) into merged windows;
  `AnsweredWindows.covers()` tests a whole bar slot.
- `detect_gaps(..., answered=)` drops covered slots; the pipeline's `--real-bars-only` skips
  `normalize_bars` and turns coverage on for 5m, 15m and 1h on equities. 1d and other asset
  classes stay on the placeholder path.
- Correction to the design above: `detect_gaps` already uses session slots (04:00 to 20:00 ET,
  holidays excluded), so closed hours were never gaps. What the placeholders hid was session
  slots a thin name simply did not trade in; without a ledger those are re-requested every run.
  The stored fill itself (`normalize_bars`) is 24x7, not session-aware.
- `ohlcv_request.window_*` is not the range of the returned bars: IBKR durations round up to
  whole days, so a short window's answer holds bars from before `window_start`. A `count >=
  n_bars` corroboration failed on 195 of 400 requests for that reason; the shipped check is
  "at least one stored row in the window". On stored data 2,720 of 3,000 15m and 1h answers pass;
  the 280 that do not are all windows under 1.5 days (recent gap fills), which are simply
  re-requested.
- Gate: targeted and full `tests/unit/` pass; ruff and black clean. `/simplify` and `/review`
  were not run because they act on the shared checkout, which holds the phase 186 session's
  uncommitted files; the diff was reviewed by hand instead. Run both before the follow-on work.

Not done: the historical seeding (coverage before 2026-09-28 is absent from `ohlcv_request`),
the 15m-versus-5m repair, the reconciliation check, and the placeholder-delete migration. The
all-years mismatch measurement is in
`/tmp/claude-1000/-home-bg-dev-indicagent/c9b4a667-5f8e-4a01-9a9a-c600d9f38b64/scratchpad/mismatch_results.tsv`
(a scratch path, copy the result into this todo when it finishes).

The 5m lane is paused by `logs/backfill_ops/PAUSE_5M` (checked in `intraday_5m_lane.sh`). To
resume: pass `--real-bars-only` in the lane script, run one symbol as a smoke test, confirm no
`synthetic_fill` rows for it and that its `ohlcv_request` windows cover the run, then delete
the marker.

## Measurement: coarse placeholders masking real 5m volume, all years (2026-09-29)

A placeholder row in the coarse timeframe whose slot holds real 5m volume (tradeable view). Only
names and years with 5m history are counted, so these are floors. Method: per year, join
`synthetic_fill` 15m or 1h rows to `date_bin` sums of 5m volume; scratch script and full table in
the session scratchpad (`mismatch.sh`, `mismatch_results.tsv`).

- 15m (the grid aligns with the 09:30 open, so this reading is clean): 155,022 masked slots and
  about 18.7B shares hidden across 2007 to 2026. By year: 2010 854 (68 names), 2016 997, 2018
  1,722, 2021 6,540 and 2022 4,780 (one name each), 2024 35,454 (100 names), 2025 84,032 (13
  names, about a full year each), 2026 17,925 (193 names). The 2025 and 2026 counts are the
  worst: 13 names whose 2025 15m is entirely placeholder while 5m is real, and 193 names with
  recent 15m holes.
- 1h: 14,986 to 81,019 masked slots per year on 150 to 240 names. Do not read this as provider
  holes. The stored 1h grid has a real 09:30 half-hour bar and then hourly bars, while the fill
  writes `:00` slots, so a placeholder at 09:00 ET sits beside the real 09:30 bar and the 5m
  volume inside that hour is counted against it (MSFT 2024-08-05: placeholders at 08:00, 09:00,
  16:00, 17:00 ET, real bars at 09:30, 10:00 to 15:00). That is a second defect of the same fill
  (a grid that disagrees with the provider's session anchoring, the D-15 / UD-25 finding), and
  the 1h provider-hole rate needs a session-anchored comparison before it is quoted.

Implication for the repair: 15m masked slots are derivable from 5m today (155K rows), and the 2025
names with a whole year of placeholder 15m are the first candidates. Re-check the 1h repair against
the D-15 session-anchored derivation instead of a `:00` join.

## Finding: the 2025 whole-year placeholders are permanent holes that reached `feature_vectors` (2026-09-29)

The 13 names with every regular-session 15m slot of 2025 (6,464 each) as a placeholder while 5m is
real are CCJ, COP, CRM, CTVA, CVS, DAL, DHI, DOCS, DOW, DUK, ECL, ELV and EMR. CCJ shows the shape:
15m real bars 2023 6,476, 2024 3,875, 2025 0, 2026 1,064; 1h real 2023 1,036, 2024 0, 2025 0, 2026
292; 5m real and complete for every year (19,392 in 2025). The row counts look complete (35,040
15m rows in 2025) because the fill writes the whole grid.

- Nothing repairs it. These names are not in the HTF lane's list (`all.symbols`, built 2026-09-27
  from names without intraday rows), and `detect_gaps` counts a placeholder as present, so even a
  run that included them would report no gaps.
- It propagated. `feature_vectors` for CCJ has 3,875 15m rows in 2024 and none in 2025, against
  full 5m and 1d. A 15m or 1h signal sees these names as absent for those years with no flag: a
  silent coverage bias in the corpus, not a wrong value (the tradeable view keeps the placeholder
  values out, so the failure is missing data, not fabricated data).
- The fix for names with real 5m is derivation, not re-fetch: 5m is complete for them, and D-15
  (185-12/17) derives 15m and 1h from it on session-anchored edges ahead of the phase 186
  rebuild. Names without 5m (the HTF lane's 698) get real bars from the fetch and are derived
  once the 5m lane runs.
- Sized (per year, share of 5m-active 15m slots holding a real 15m bar): 2007 to 2023 is 99.6% to
  100.0% (2006 85.3%), then 2024 97.7%, 2025 94.5% (13 names below 50%), 2026 98.4% (13 names
  below 50%); 2021 and 2022 have one name below 50% each. So the defect is concentrated in recent
  years and a small set of names, not spread across the corpus. Only the 240 names with 5m are
  measurable. Redesign: `docs/plans/2026-09-29-intraday-bar-store-redesign.md`.

## Reuse correction (2026-09-29, after the architecture review)

Two earlier steps in this todo are already covered by phase 185 and are not new work:

- Deleting 15m and 1h placeholders and repairing the 13 names is `BarDerivation --apply`
  (`services/bar_derivation.py`, the rewrite of stored rows is plan 185-12): it archives the stored rows,
  verifies checksums, deletes the segment (placeholders included) and writes derived rows with
  digests in one transaction per symbol.
- 15m/1h gap detection on IBKR's own RTH grid and a parity check of fetched versus derived bars
  are in 185-12.

What is new here is 5m and 1m (185 never touches them), the answered-window plan, atomic
request-and-bars persistence, coverage-aware derivation flags, and the completeness audit. All of
it, with the DAG, is in `docs/plans/2026-09-29-intraday-bar-store-redesign.md`. 185-12 edits the
same pipeline file as `--real-bars-only`, so plan 185-12 against the current file.
