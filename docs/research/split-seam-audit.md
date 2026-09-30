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

- names audited: 2
- seams found: 0
- splits inferred (corporate_action rows): 0
- unexplained disagreements: 0
- names skipped for missing fresh data or overlap: 0

## Splits inferred

| Symbol | Last old-scale day | Kind | Factor | Run days |
| --- | --- | --- | --- | --- |

## Unexplained disagreements (top 30 by run length)

| Symbol | Run | Factor | Days | Max rel dev | Reason |
| --- | --- | --- | --- | --- | --- |

## Skipped names

none
