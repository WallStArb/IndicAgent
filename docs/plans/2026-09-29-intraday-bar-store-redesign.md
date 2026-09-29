# Intraday bar store redesign

**Author:** Claude (Sonnet 5.5), 2026-09-29, at Brandon's request ("seems like that needs a
redesign"), after the todo 462 measurements.
**Status:** proposed. Amends phase 185 (D-15, plans 185-12, 185-20, 185-23); todo 462 is the
working record.
**Informed by:** `docs/plans/2026-09-26-daily-data-foundation.md` (D1, D2b, D-15),
`.planning/todos/pending/462-stop-storing-synthetic-fill-bars-record-coverage-instead.md`.

## What is wrong

The backfill pads `market_data_ohlcv` with flat placeholder bars for every calendar-grid slot the
provider did not return, and treats a stored placeholder as proof the slot was handled. Measured
2026-09-29:

- 81% to 83% of intraday rows are placeholders (1m, 5m, 15m, 1h); 33% of 1d rows.
- A placeholder is never replaced by a real bar (`ON CONFLICT DO NOTHING`), and gap detection
  counts it as present, so a missing bar becomes a permanent, unflagged hole.
- 155,022 15m slots hold real 5m volume while the 15m row is a placeholder (about 18.7B shares).
  Concentrated, not uniform: 15m real coverage of 5m-active slots is 99.6% to 100.0% for 2007 to
  2023, then 97.7% (2024), 94.5% (2025) and 98.4% (2026). Thirteen names (CCJ, COP, CRM, CTVA,
  CVS, DAL, DHI, DOCS, DOW, DUK, ECL, ELV, EMR) have every 2025 slot as a placeholder, and the
  hole is in `feature_vectors`: CCJ has 3,875 15m rows in 2024 and none in 2025.
- The fill's 1h grid (`:00` slots) disagrees with the provider's (a 09:30 half-hour bar, then
  hourly), so 1h carries a second, structural defect.

The 458 names without 5m history cannot be measured this way; assume the same mechanism.

## First principles

1. A stored bar is an assertion about the market. Store only what the provider observed.
2. Absence is typed and lives outside the bar table: not asked, asked and empty, market closed
   (session calendar), provider hole.
3. Redundancy is error detection. Independent measurements of one quantity must reconcile, and a
   mismatch raises an alarm; it is never resolved by first write wins.
4. One writer per table, and canonical bars are a pure function of raw observations under a
   versioned rule. A rule that cannot emit a placeholder makes the defect impossible.
5. Completeness is a measured, exported property of every (symbol, timeframe, year), not an
   assumption from row counts.

## Target design

| Layer | Content | Writer |
|---|---|---|
| Requests | every provider request, window, outcome (`ohlcv_request`, live since 185-09) | the fetch |
| Raw intraday | the provider's bars for 5m (and the sampled 15m/1h), real only, never padded | the fetch |
| Canonical intraday | 5m as observed; 15m and 1h derived from 5m on session-anchored edges (D-15, `session_grid`) | the derivation (185-11/12) |
| Coverage | union of answered request windows | read from `ohlcv_request`, no new table |
| Checks | 15m and 1h fetched versus derived; intraday versus 1d volume; masked-slot count | the daily audit (185-23) |
| Completeness | per (symbol, tf, year) share of expected session slots holding a real bar | audit, exported to Grafana and read as a D0 label |

Decisions this fixes:

- 5m is the one intraday fetch that feeds research. 15m and 1h are derived, never padded.
- The HTF lane already running (15m, 1h) is kept as a reconciliation corpus for its names, not
  extended. It is cheap next to 5m: observed request windows are up to 729 days at 15m and 1h,
  against up to 88 days at 5m, roughly 17 requests per name against 80 or more.
- The 5m lane stays paused until `--real-bars-only` is smoke tested, then runs with it (built,
  todo 462).
- 1d is out of this redesign; it stays on D2. The placeholder path for 1d goes with D2's writer.

## What it deletes

`normalize_bars` in the backfill store path and its one-time normalization mode; gap inference
from the presence of a row; placeholder counting in `bar_auditor`; the `:00` fill grid for 1h; the
tradeable view's `volume > 0` as a stand-in for "real" (a `source` predicate replaces it once no
placeholders remain). Nothing is added as a new table.

## Migration order (each step gated, none skipped)

1. `--real-bars-only` and answered-window gap detection (done, default off).
2. Smoke test one 5m symbol; resume the 5m lane with the flag.
3. Coverage seeding at (symbol, tf, day) from real bars only, so a session day with no real bar is
   uncovered and gets asked again. Coverage before 2026-09-28 is otherwise absent.
4. Derive 15m and 1h from 5m for the 240 names with 5m (D-15), starting with the 13 names and the
   2024 to 2026 holes; compare against the fetched bars and record the disagreement rate.
5. Digest check: the `bar_content_digest` of real rows is identical before and after, per symbol
   and timeframe.
6. Delete `source = 'synthetic_fill'` rows (compressed hypertable: decompress, delete, recompress,
   bare `VACUUM`, the CI-enforced pattern).
7. Remove the fill from the backfill code and the auditor; switch the tradeable view.
8. Phase 186's `feature_vectors` rebuild reads the derived bars. It must not run over stored
   15m/1h that still contain placeholders (185-12 already gates it; this makes the reason
   concrete).

## Success criteria

- Zero `synthetic_fill` rows in `market_data_ohlcv` outside 1d, and no code path that writes one.
- Completeness at or above the measured 2007 to 2023 level (99.6% or better) for every 5m-active
  name and year, or a typed reason for each shortfall.
- The 13 names' 2025 15m and 1h rebuilt from 5m, and `feature_vectors` for them complete.
- A daily audit alarms on a coarse placeholder or hole over real finer-timeframe volume.
- Research verdicts on 15m and 1h that touched the affected names and years are listed in the
  research ledger with their sample loss.

## Open questions

- Whether 5m-derived 1h agrees with the provider's 1h at the 09:30 half-hour edge; measure before
  the derived 1h replaces it (D-15 says it does).
- How coverage seeding treats a session day where a thin name legitimately did not trade.
- Whether the measured 2024 to 2026 concentration comes from one backfill event; the lane logs for
  the affected names may say.
