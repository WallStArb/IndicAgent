---
status: pending
priority: P1
filed: 2026-09-26
source: 2026-09-26 universe expansion code review
---

# Onboard the 70 drawn small caps the history screen dropped

## What

The 2026-09-26 history screen dropped 70 of the 195 drawn small caps as having no IBKR
daily bar before 2016-09-26 (`config/universe/history_screen_2026_09_26.csv`). The screen
was wrong in two ways:

- For 14 of the 70 the probe exhausted its retries on IBKR pacing, so FAIL was not evidence:
  VOR, PAYO, ACVA, RDW, SGHC, SDRL (IWM draw); NUVB, CMDB, PWP, AGL, VSTS, CNXC, MFP, CLBK
  (IWV rank-1001 draw).
- A SMART-routed probe finds no bar before a name's last listing-venue move (todo 433), so
  names that changed venue after 2016 also failed.

Dropping them tilted the onboarded small caps toward long-listed firms, against the
stratified design. The screen has been deleted (owner decision 2026-09-26): drawn names are
onboarded as drawn, and the research panel's own coverage rules handle short histories.

## Next

1. Classify the 70 (the other 125 drawn names were classified the same way, from IBKR
   contract details), add them to a manifest with their original cohort, onboard through
   `universe_expansion_onboard_manifest.py`, backfill 1d, promote.
2. Update `config/universe/README.md`: the draws are then onboarded in full, apart from any
   name IBKR cannot qualify.
