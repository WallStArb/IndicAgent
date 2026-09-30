# Split-seam audit

Author: phase 185 plan 15 (ops_seam_audit.py)
Informed by: D-21, D-24, D1 ohlcv_observation (fresh TRADES run and stored corpus), src/intelligence/bars/seams.py, corporate_actions.py

Generated 2026-09-30 against fetch run c9b625b5-5fc4-4656-8b49-06fd93062123. Thresholds: threshold.seam.rel_tol=0.002, threshold.seam.min_run=5, threshold.seam.ratio_snap_tol=0.01.

## First-audited names (D-24)

- MRNA (2026-08-19): event, not a split: the stored/fresh ratio stays 1 through the date
  - common days compared: 1960; seams: 0
  - stored/fresh close ratio around the date:
    2026-08-17 ratio 1.000000
    2026-08-18 ratio 1.000000
    2026-08-19 ratio 1.000000
    2026-08-20 ratio 1.000000
    2026-08-21 ratio 1.000000
- ALMS (2026-09-01): event, not a split: the stored/fresh ratio stays 1 through the date
  - common days compared: 562; seams: 0
  - stored/fresh close ratio around the date:
    2026-08-28 ratio 1.000000
    2026-08-31 ratio 1.000000
    2026-09-01 ratio 1.000000
    2026-09-02 ratio 1.000000
    2026-09-03 ratio 1.000000
    2026-09-04 ratio 1.000000

## Counts

- names audited: 931
- seams found: 0
- splits inferred (corporate_action rows): 0
- unexplained disagreements: 74
- names skipped for missing fresh data or overlap: 0

## Splits inferred

| Symbol | Last old-scale day | Kind | Factor | Run days |
| --- | --- | --- | --- | --- |

## Unexplained disagreements (top 30 by run length)

| Symbol | Run | Factor | Days | Max rel dev | Reason |
| --- | --- | --- | --- | --- | --- |
| DBA | 2007-06-29 to 2007-06-29 | 0.997732 | 1 | 0.0000 | non-constant disagreement |
| DBA | 2007-07-10 to 2007-07-10 | 0.997796 | 1 | 0.0000 | non-constant disagreement |
| DBA | 2007-07-23 to 2007-07-23 | 0.996897 | 1 | 0.0000 | non-constant disagreement |
| DBB | 2007-07-03 to 2007-07-03 | 0.996315 | 1 | 0.0000 | non-constant disagreement |
| DBB | 2007-07-16 to 2007-07-16 | 0.996721 | 1 | 0.0000 | non-constant disagreement |
| DBB | 2007-07-24 to 2007-07-24 | 0.993671 | 1 | 0.0000 | non-constant disagreement |
| FXY | 2007-08-16 to 2007-08-16 | 1.002970 | 1 | 0.0000 | non-constant disagreement |
| GDX | 2006-10-05 to 2006-10-05 | 0.997399 | 1 | 0.0000 | non-constant disagreement |
| GDX | 2006-10-12 to 2006-10-12 | 0.997700 | 1 | 0.0000 | non-constant disagreement |
| HYG | 2007-06-12 to 2007-06-12 | 1.003202 | 1 | 0.0000 | non-constant disagreement |
| HYG | 2007-06-22 to 2007-06-22 | 1.002134 | 1 | 0.0000 | non-constant disagreement |
| HYG | 2007-06-26 to 2007-06-26 | 1.002921 | 1 | 0.0000 | non-constant disagreement |
| HYG | 2007-07-25 to 2007-07-25 | 1.002125 | 1 | 0.0000 | non-constant disagreement |
| HYG | 2007-08-03 to 2007-08-03 | 1.006433 | 1 | 0.0000 | non-constant disagreement |
| HYG | 2007-08-16 to 2007-08-16 | 1.006116 | 1 | 0.0000 | non-constant disagreement |
| HYG | 2007-09-12 to 2007-09-12 | 1.005505 | 1 | 0.0000 | non-constant disagreement |
| HYG | 2007-09-25 to 2007-09-25 | 1.002010 | 1 | 0.0000 | non-constant disagreement |
| LMT | 2026-08-06 to 2026-08-06 | 0.993412 | 1 | 0.0000 | non-constant disagreement |
| MARA | 2026-08-06 to 2026-08-06 | 1.027230 | 1 | 0.0000 | non-constant disagreement |
| MO | 2026-08-06 to 2026-08-06 | 1.015351 | 1 | 0.0000 | non-constant disagreement |
| MOO | 2026-08-06 to 2026-08-06 | 0.995950 | 1 | 0.0000 | non-constant disagreement |
| MS | 2026-08-06 to 2026-08-06 | 1.019649 | 1 | 0.0000 | non-constant disagreement |
| MSTR | 2026-08-06 to 2026-08-06 | 1.007847 | 1 | 0.0000 | non-constant disagreement |
| MUB | 2007-12-24 to 2007-12-24 | 1.002179 | 1 | 0.0000 | non-constant disagreement |
| NAD | 2026-08-06 to 2026-08-06 | 0.997455 | 1 | 0.0000 | non-constant disagreement |
| NEE | 2026-08-06 to 2026-08-06 | 1.012057 | 1 | 0.0000 | non-constant disagreement |
| NFLX | 2026-08-06 to 2026-08-06 | 1.006242 | 1 | 0.0000 | non-constant disagreement |
| NLY | 2026-08-06 to 2026-08-06 | 0.997352 | 1 | 0.0000 | non-constant disagreement |
| NTR | 2026-08-06 to 2026-08-06 | 0.988766 | 1 | 0.0000 | non-constant disagreement |
| NVR | 2026-08-06 to 2026-08-06 | 0.996040 | 1 | 0.0000 | non-constant disagreement |

## Skipped names

none

## Reading of the result (orchestrator, 2026-09-30)

No split or seam was found in 931 names, so `corporate_action` stays empty and no `split_seam` flag was written. The stored closes and the fresh TRADES closes agree apart from 74 isolated single-day differences, none a constant-ratio run, so none is forced into a split.

Two patterns sit inside the 74. Thirty of the listed rows are early-history ETF days (2006 and 2007: DBA, DBB, HYG, GDX, FXY, MUB and others) that differ by 0.2 to 0.7% on a single day. Twelve names (LMT, MARA, MO, MS, MSTR, MOO, NAD, NEE and others) differ on 2026-08-06 only, by 0.7 to 2.7%, with the days either side matching exactly. For LMT the stored close is 579.01 and the fresh SMART TRADES close is 582.85. This audit cannot say which side is right: the stored close may have been taken before the day's final print, or IBKR may have revised it since. Plan 10's scrub pass and the D7 daily-versus-intraday check (plan 23) are the places to settle it, because the aggregated 5m closes are a third, independent reading.

D-24's two named cases, MRNA 2026-08-19 and ALMS 2026-09-01, are events and not splits: the stored/fresh ratio stays 1 through both dates.
