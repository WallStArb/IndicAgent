---
status: pending
priority: P2
filed: 2026-11-24
source: indicagent-3d, readiness check of ic_measure against the rebuilt tables (lead item C)
---

# ic_measure targets are price-only: dividends are not in the open-to-open return

## What

`build_target_panels` (`src/intelligence/measure/targets.py`) builds the S0 panels without the dividend grid (`dividends=False`) and the measure's panel digest leaves dividends out on purpose (`services/ic_measure.py`, `panels_digest`: a dividend revision cannot change an IC). The targets are therefore `panel.forward_returns` on price-only opens. CLAUDE.md says a spec that holds across a session boundary declares `panel.total_return`; every 1d horizon in `alpha.ic_measure.horizons` (1, 2, 5, 10) does. An ex-dividend drop enters the target as a negative return, which biases a feature correlated with the yield (`dividend_yield`, `size_proxy` and the like) on the ex-date rows and adds noise to the rest.

## Deadline

Decided before the first IC run after the corpus rerun: CLAUDE.md says a spec that holds across a session boundary declares `panel.total_return`, and every 1d horizon in `alpha.ic_measure.horizons` does. The measurement plan: on the 1d pilot rows, the IC of `dividend_yield`-linked columns (`dividend_yield`, `size_proxy`) and the rank correlation of the full per-column IC vector between the price-only and the total-return target at each horizon, plus the share of target rows that straddle an ex-date.

## Return-free facts (measured 2026-11-24, light read-only counts, no return or IC read)

On Massive ex-dates inside stage 2 member months (2003-09-10 to 2025-12-23): 194,375 events on 5,838 names over 978,350 member-months, about 0.2 events per member-month, so a 1d target window of h sessions straddles an ex-date on about 0.95 percent x h of rows (an upper estimate across all member-months, uncovered names included): about 1 percent at h 1, 2 at h 2, 5 at h 5, 10 at h 10. Yield on those events: median 0.49 percent, 90th percentile 1.56, 99th 4.5; 1,507 events above 5 percent and 327 above 10 percent (specials). The lead's ruling (2026-11-24): decide on these facts, with no with-and-without IC comparison (that would be a counted look), and record the decision in the ledger before the first IC run.

## Done when

The materiality is read on return-free facts first (Musk step 1; owner ruling 2026-11-20): on the 1d pilot rows, the IC of `dividend_yield` and two unrelated columns with and without a total-return target at each horizon, and the share of target rows that straddle an ex-date inside `dividend_event_coverage`. If the difference is below the noise of the IC, record the price-only choice in the ledger as a disclosed property and close; if not, the target moves to total return for covered names (outside coverage dividends are unknown, never zero) under a methodology-change entry before the first IC run that is counted.
