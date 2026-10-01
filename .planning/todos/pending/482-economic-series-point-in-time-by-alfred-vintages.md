---
status: pending
priority: P1
filed: 2026-10-01
source: macro context layer council pass (docs/ideas/signal-macro-context-layer.md)
---

# Economic series: availability and revisions from ALFRED vintages, not an assumed lag

## What

`economic_series_observation` stamps every backfilled FRED row with an assumed `available_at` (the end
of the business day after the observation date) and stores today's revised values. Measured
2026-10-01 against ALFRED:

- `THREEFYTP10` is a weekly release: the 2024-01-02 value was first published 2024-01-09, and the
  history was revised 2024-08-12. The stored rows are about a week early and hold revised values.
- Daily series first-release lag over Q1 2024 (61 days each): `DGS10` and `DFII10` 1 day (49), 3
  (10), 4 (2); `BAA10Y` 1 (47), 2 (1), 3 (10), 4 (3). The rule is early on holiday weekends and on
  `BAA10Y`'s two-day days.
- A monthly series under the rule would be weeks early (CPI January 2024: first release
  2024-02-13). Tier 2 FRED series must not be added before this lands.

No consumer reads the table yet, so a clean reload is cheap now.

## Recommendation

1. Fetch FRED series through ALFRED: `output_type=4` (initial release) for each observation's first
   value and first-release date, and the vintage rows for revisions; ALFRED caps a request at 2,000
   vintage dates, so fetch long daily series in windows.
2. `available_at` = the end (next 00:00 UTC) of the vintage date; basis `vintage`. Keep the
   assumed rule only for the NY Fed, renamed `declared_rule` (08:00 New York time on the next
   business day), and verify it from forward fetch times.
3. Per-series `kind` (`daily_level`, `reference_period`, `schedule`) in the series registry
   (`economic_series_observation_coverage`); the writer refuses a declared rule on a
   `reference_period` series.
4. Drop the APR `revision` field (vintages measure it).
5. Standing audits in the writer run, reported and never repaired: SOFR and EFFR across FRED and the
   NY Fed (2026-10-01: SOFR agrees on all 2,122 common days), the identity `T10Y2Y = DGS10 - DGS2`
   (2026-10-01: 3 days off, worst 2 bp; 1 day with a missing leg), and gaps against the publication
   calendar.
6. Truncate and reload, verify the vintage-based `available_at` against the measured lags above,
   then re-run the writer twice (the second appends nothing).

## Acceptance

- No FRED row has basis other than `vintage`; `THREEFYTP10` first rows match its first-release
  values.
- A unit test per availability rule, including a Friday, a holiday weekend and a monthly series.
- Audit counts appear in the run log and the outcome counter.
