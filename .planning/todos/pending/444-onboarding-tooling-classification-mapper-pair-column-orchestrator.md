---
status: pending
priority: P3
filed: 2026-09-26
source: instrument onboarding SOP (docs/foundation/instrument-onboarding-sop.md, gaps 3, 5, 6)
---

# Onboarding tooling: classification mapper, pair column, one resumable command

## What

The SOP's stages 3-9 work, but three steps are manual:

1. **Classification mapper (gap 3).** The 2026-09-26 batch mapped IBKR contract details
   (industry, category, subcategory) to `indicagent_v1` level-4 nodes by hand.
   `classification_ibkr_sourcing.py` reads only names already onboarded. Needed: a read-only
   tool that takes a drawn list, fetches contract details, proposes a node per name, and writes a
   review CSV whose reviewed form is the manifest's `code` and `source_ref` columns.
2. **Pair column (gap 5).** A `spread_leg` tag needs its reciprocal pair written in a migration
   (371, 373). A manifest column naming the partner, written by the onboarder in the same
   transaction, removes the hand migration.
3. **One command (gap 6).** `universe_onboard.py --manifest ...` running stages 5-9 in order,
   resumable from persisted state, stopping at every hold and writing the verify report. It
   composes the existing scripts; it does not reimplement them.

## Gate

Build 3 only after the next batch has run cleanly through the SOP by hand (automate what is
proven). 1 and 2 have no gate. Todo 431 (delete the second instrument writer) goes first.
