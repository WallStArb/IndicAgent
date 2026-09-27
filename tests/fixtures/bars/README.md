# Bar known-answer fixtures (phase 185)

Captured 2026-09-27. These fixtures are the D-10 known-answer set: every phase 185
scrubbing and derivation rule is validated against them before it touches research
data. Pure-rule tests under `tests/unit/bars/` read them without a database.

## corrupt_1d_dry_run_2026_09_26.txt

The 2026-09-26 dry-run report of
`scripts/ops/corpus/ops_known_corrupt_print_cleanup.py --tf 1d` (its default mode;
never run with `--apply`), copied byte-for-byte out of the generating session's
scratchpad before /tmp cleanup. Sections: `## CONFIRMED_CORRUPT (45)`,
`## AMBIGUOUS (1864)`, `## MARKET_EVENT (27)`. The 45 CONFIRMED_CORRUPT rows are the
known corrupt prints no rule may clear; the 27 MARKET_EVENT rows (26 on the
2010-05-06 Flash Crash plus EWW 2006-11-07) are the known answers for D-11's
corroboration-clearing ceiling; the 1,864 AMBIGUOUS rows are edge bars that are not
candidates. sha256:
`0a9694d58dceaa6e18ced54ea603d02774a0b138a2f7c8b9f3905504420c82ed`

## price_sanity_status_rows.csv

Every `market_data_ohlcv` row with a non-null `price_sanity_status` at capture time
(567 rows, all timeframes), read from the raw table because the tradeable view hides
`confirmed_corrupt` rows. Live count by status at capture (2026-09-27):
confirmed_corrupt 67 (1d 15, 15m 19, 5m 20, 1h 13), ambiguous 16, plausible 484.
This is the source set plan 04 migrates into `bar_quality_flag` (the 67 rows).

## seam_candidates_mrna_alms.csv

MRNA and ALMS 1d bars from 2026-07-01 through the latest stored date (118 rows), the
first two split-seam candidates for D-24's seam audit: MRNA around 2026-08-18/19 and
ALMS around 2026-08-31/09-01, where stored closes should show a constant split ratio.

## spy_5m_2025_11_28_half_day.csv

SPY 5m bars on the 2025-11-28 early-close session (42 bars, 09:30-13:00 ET), the
known answer for session-anchored grid edges on a short session.

## spy_5m_dst_2025_03_10_2025_11_03.csv

SPY 5m bars on both 2025 DST transition sessions (78 bars each, 156 rows). Bar
timestamps are UTC; the session dates are America/New_York dates, so these days pin
the DST offset handling of any session-grid derivation.

## spy_1d_2024.csv

SPY 1d bars for calendar 2024 (252 trading days), a clean contiguous daily series for
derivation and reconciliation checks.

Regenerate with:
`.venv/bin/python scripts/ops/bars/ops_export_known_answer_fixtures.py`
(the export is SELECT-only; row counts will drift as the live data grows, so do not
regenerate casually once tests pin these counts).
