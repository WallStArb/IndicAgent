# Plan 185-12 Summary: derived 15m/1h grid live rewrite and nightly chaining

Status: complete (task 2 finished inline by the orchestrator after the executor's 429 stop,
per the owner directive of 2026-09-27). Tasks 1a/1b landed earlier (commits 6185ff1c8, 3c0c68fc7,
c64bc5d52, 9f2ef1c53): single archive writer, pipeline reroute with RTH-grid gap detection,
nightly chaining, atomic request-and-bars persist, partial_constituents flags, lane guard.

## Baseline (pre-rewrite, /tmp/18512_masked_baseline.json)

Masked 15m slots (synthetic-fill coarse row while tradeable 5m carried volume): 155,022 slots,
18.7B hidden 5m volume, spanning 12 years. Worst years: 2025 (84,032 slots, 13 symbols),
2024 (35,454, 100), 2026 (17,925, 193).

## Pilot and cutover

- Pilot `--symbols SPY,AAPL,XLU --apply`: 33 s, 501,816 derived rows, 493,739 archived originals.
- Cutover: lane pipeline killed by PID, orphans swept to zero, no ClientWrite backend; the chain
  loop respawned on the reroute code (~23:33 UTC) and its 15m/1h fetches land in the archive only.
- Full run 1 (23:35 UTC) failed the archive verify on the 3 pilot symbols: their re-derived rows
  counted as removable originals and the value-sum compare crossed sources. Fix: removable means
  original observations only (verify and archive-from-table exclude `derived_5m` and
  `synthetic_fill`; derived rows are rebuildable cache, re-derivation deletes and regenerates them).
- Full run (00:20-00:53 UTC): 233 derived, 7 excluded_lane, 1 no_5m, 33,219,966 derived rows,
  status completed. Idempotency proven by the re-run itself (second pass over all symbols with
  digests present: n_archive_rows 0, no failures).

## D-15 verification (all six live checks pass)

`tests/integration/test_derived_grid_live.py`, executed directly against the live DB (the pytest
suite is blocked at fixture setup by todo 486, not by this file):

1. No derived symbol has 1h rows at two minutes in a session (scoped to derived symbols; the
   not-yet-derived majority keeps the old :00/:30 mix until todo 449 reaches them).
2. Derived 1h rows are all `derived_5m` and session-anchored: each bar sits an integral number of
   hours after the session open. mcal encodes real late opens (2006-12-27 opened 09:32 for Ford's
   moment of silence; 147 symbols correctly carry :32 1h bars that day), so the plan's hard ":30"
   criterion was wrong as written, not the data.
3. Derived 15m/1h bars equal a direct SQL aggregation of the tradeable 5m (5 symbols x 5 sessions,
   fixed seed). The oracle must take first-open/last-close, not min(open)/max(close) (caught on
   LMT 2009-07-23), and thin sessions legitimately aggregate fewer than 3/12 constituents
   (XTL 2019-09-05); unanswered holes are the partial_constituents flag's job.
4. Session identities: first derived 1h open equals the 1d open exactly; 1h volume within 1% of
   the 1d volume. Exact volume equality is not a property of the data-generating process
   (measured over all 1.03M derived sessions: 90.3% exact, p99 relative deficit 0.26%, both
   directions occur; official 1d volume counts auction prints and odd lots the 5m grid does not
   carry, GLD 2007-06-22 deficit 0.19%).
5. Archive holds the removed observations: no synthetic_fill ever archived; the latest completed
   batch records n_archive_rows and its tagged rows are a subset.
6. bar_content_digest_current covers 5m/15m/1h for every derived symbol.

## D-14 scrub ports

`ops_scrub_historical_pass.py --tf 15m --apply`: 124,197 flags (gap_before_next 123,800,
return_magnitude 397), 68.5 s. `--tf 1h --apply`: 812 flags (626 + 186), 34 s. Zero quarantines.

## Post-rewrite measurements

- Masked-slot baseline rerun: 155,022 -> 13,033, and every remaining slot is ACRS (2020-2022),
  which is not derived (waiting on 5m like the rest of the lane set). Zero masked slots for
  derived symbols: acceptance met.
- No-insert-since-cutover: post-rewrite table totals 15m 175,076,596 / 1h 45,524,070 (down from
  the pre-rewrite reference 293,198,992 / 75,439,309: the rewrite replaced stored segments with
  derived rows only where 5m exists). Lane fetches since the cutover are observable only in the
  archive (e.g. AJG: 26 recent 15m bars/day archived; the table's partial pre-cutover rows are
  the old process's writes). No new ibkr_named 15m/1h entered market_data_ohlcv after the
  respawn.

## jsonb double-encoding found and fixed (live bug, repaired)

The grid batches' `detail` came out as `["{}", "{...}"]` and 3,355,343 bar_quality_flag rows'
`detail` as JSON strings: BaseBatch's pooled connections register the jsonb codec
(encoder=json.dumps), so a str parameter already typed jsonb by `$n::jsonb` double-encodes as a
string scalar, and jsonb `||` on two scalars concatenates into an array. Fix: cast through text
(`$n::text::jsonb`) in `services/bar_derivation_batch.py` (asyncpg pair; the psycopg twins were
already correct) and `services/bar_derivation.py`'s flag insert; verified dual-safe on bare and
codec connections before committing. Data repaired in place: flags unwrapped
(`(detail #>> '{}')::jsonb`), batch detail/apr_snapshot decoded; all ten flag rules and all seven
batch rows now objects.

## Deviations

- Executor 429 kill mid task 2; the orchestrator finished inline (owner directive 2026-09-27).
- A temporary fail-closed gate kept the nightly from running the first full rewrite unattended;
  it was never committed and is now removed (the chained stage runs `--changed-only --apply`
  against a populated digest table, so a clean night is a digest comparison per symbol).
- The integration suite itself is blocked by todo 486 (conftest replay of migration 426 fails on
  the scratch DB); the D-15 battery ran as the test module's own assertions over a live psycopg
  connection instead.
- `--symbols SPY,AAPL,XLU` comma form parses now (nargs="*" previously took it as one bogus
  symbol; main() splits on commas).

## Nightly

`_run_grid_stage` restored: `--stage grid --changed-only --apply` plus the lane-guard exclude
file, after the legs. First chained run: tonight 05:00 UTC.
