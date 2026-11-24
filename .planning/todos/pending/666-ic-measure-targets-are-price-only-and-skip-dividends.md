---
status: pending
priority: P3
filed: 2026-11-24
source: indicagent-3d, readiness check of ic_measure against the rebuilt tables (lead item C)
---

# ic_measure targets are price-only: dividends are not in the open-to-open return

## What

`build_target_panels` (`src/intelligence/measure/targets.py`) builds the S0 panels without the dividend grid (`dividends=False`) and the measure's panel digest leaves dividends out on purpose (`services/ic_measure.py`, `panels_digest`: a dividend revision cannot change an IC). The targets are therefore `panel.forward_returns` on price-only opens. CLAUDE.md says a spec that holds across a session boundary declares `panel.total_return`; every 1d horizon in `alpha.ic_measure.horizons` (1, 2, 5, 10) does. An ex-dividend drop enters the target as a negative return, which biases a feature correlated with the yield (`dividend_yield`, `size_proxy` and the like) on the ex-date rows and adds noise to the rest.

## Done when

The materiality is measured first (Musk step 1; owner ruling 2026-11-20): on the 1d pilot rows, the IC of `dividend_yield` and two unrelated columns with and without a total-return target at each horizon, and the share of target rows that straddle an ex-date inside `dividend_event_coverage`. If the difference is below the noise of the IC, record the price-only choice in the ledger as a disclosed property and close; if not, the target moves to total return for covered names (outside coverage dividends are unknown, never zero) under a methodology-change entry before the first IC run that is counted.
