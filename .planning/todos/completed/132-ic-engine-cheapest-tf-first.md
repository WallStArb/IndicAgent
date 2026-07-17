---
status: completed
priority: P2
filed: 2026-07-17
closed: 2026-07-17
source: user noticed the corpus rebuild processes tf=5m (the most expensive,
  most-rows-per-cell tier) first, spending its first many hours entirely in the
  timeframe most exposed to an unrelated crash before banking any rows
---

# `ic_engine.py`'s cross-sectional pass processed 5m (slowest, riskiest) tf first — reordered to cheapest-first

## Finding

`_DEFAULT_TFS = ["5m", "15m", "1h", "1d"]` set the iteration order for both the per-symbol
and cross-sectional passes. The cross-sectional pass (`_compute_cross_sectional_tf`) writes
each `(regime_group, tf, regime_label)` cell's rows immediately on completion (todo 130), but
per-cell cost scales steeply with pooled row count: a `5m` cell can have ~361674 rows (~1h+
even after todo 131's bootstrap-threading fix), while `1d` cells with the same symbol set have
roughly 1/80th the rows and finish in about a minute. Processing `5m` first meant the run spent
its first many hours entirely inside the tier most likely to hit an unrelated crash (OOM,
connection drop, host reboot, todo 128's original bug) with zero cross-sectional rows banked
anywhere.

## Fix

Reordered `_DEFAULT_TFS` to `["1d", "1h", "15m", "5m"]` — cheapest/fastest tier first. Verified
before changing that this is safe: `market_regimes` regime-label sets are identical across all
4 tfs for both enabled regime groups (`equity`: 9 labels, `rates`: 6 labels, checked directly via
query, not assumed) — the one order-sensitive line in the cross-sectional loop
(`tfs[0]` used as an arbitrary anchor tf to fetch a group's regime-label list) returns the same
result regardless of which tf ends up first.

No APR migration: `_DEFAULT_TFS` is an argparse default (`--tf` already fully CLI-overridable),
not a hardcoded numeric threshold/weight/period/count — an ordering/sequencing default, not an
APR-mandate target.

Not TDD'd as new behavior (a list-literal reorder with no new logic); verified via full
`tests/unit/` suite (no test asserts tf order) plus a live DB check confirming the
`tfs[0]`-as-anchor read stays correct under the new order.

## Not yet done

- Nothing outstanding. Purely a sequencing change to reduce the corpus rebuild's exposure
  window to an unrelated mid-run crash, complementing (not superseding) todo 131's per-cell
  speedup.
