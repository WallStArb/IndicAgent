---
status: pending
priority: P1
filed: 2026-09-26
source: 2026-09-26 universe expansion code review
---

# Re-screen 14 small caps the history screen failed on IBKR pacing, not on evidence

## What

The 2026-09-26 history screen recorded 70 of 195 drawn small caps as having no daily bar
before 2016-09-26. For 14 of them the probe had exhausted its retries on IBKR pacing
errors, and `fetch_historical_bars` returns `[]` for both cases, so their FAIL is not
evidence:

- IWM draw: VOR, PAYO, ACVA, RDW, SGHC, SDRL
- IWV rank-1001 draw: NUVB, CMDB, PWP, AGL, VSTS, CNXC, MFP, CLBK

The screen now makes a control fetch (SPY, same window) after every empty probe and
reports INCONCLUSIVE when that also comes back empty.

## Next

1. After the gateway is idle, run
   `universe_expansion_history_screen.py --draw config/universe/r2k_draw_2026_09_26.csv
   --draw config/universe/r3k_rank1001_draw_2026_09_26.csv --history-before 2016-09-26
   --only <the 14>`.
2. Classify any that pass, onboard them into their original cohort through
   `universe_expansion_onboard_manifest.py`, backfill 1d, promote.
3. Update `history_screen_2026_09_26.csv` and `config/universe/README.md` with the result.
