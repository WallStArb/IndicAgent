---
status: pending
priority: P2
filed: 2026-09-22
source: found by vulture's CI dead-code gate (todo 309's backlog) during a repo hygiene pass while todo 340 was running in parallel
---

# `l1_turnover` is computed but never called -- the portfolio diagnostic's own spec called for per-arm turnover reporting, it never shipped

## What

`scripts/analysis/portfolio_covariance_weighting_diagnostic.py:262`'s `l1_turnover(w_prev, w_curr)`
has zero callers anywhere in the repo outside its own unit test
(`tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py`). Its docstring is explicit
about intent, not just describing the math:

> Reported per arm per rebalance (Output section, spec) so a mean-variance arm's tendency to churn
> on small mu/Sigma shifts is visible, not hidden behind a gross-return-only report.

This matches todo 378's own closure note verbatim: the Gate B / cross-instrument covariance-aware
portfolio diagnostic's real positive result (`vol_normalized`/`ic_proportional` beating
`equal_weight`, ann. Sharpe ~1.19/~0.95 vs ~0.18) is caveated as "**zero costs modeled**." Turnover
is the input a cost model needs and the spec called for reporting it as a diagnostic (not a gate --
[[feedback_execution_costs_not_gating.md]]'s standing rule that costs are reported, never the flip
condition, still applies) -- the function was built for exactly this and just never got wired into
`run_walk_forward`'s per-arm output.

## Fix

Call `l1_turnover(w_prev, w_curr)` once per arm per rebalance inside `run_walk_forward` (or wherever
the per-arm weight vectors are already available across consecutive rebalances) and add it to
whatever structure already carries `portfolio_exposure_stats`'s gross/net/herfindahl/effective_n
output, so turnover shows up alongside the diagnostic's existing per-arm stats. Not a re-run of the
Gate B result itself -- this is reporting an already-computed-shape metric on top of data the
diagnostic (todo 378, CLOSED) already produced or can regenerate cheaply.

## Where

- `scripts/analysis/portfolio_covariance_weighting_diagnostic.py` -- `l1_turnover` (line 262),
  `portfolio_exposure_stats` (the sibling function it should sit next to in the output),
  `run_walk_forward` (where per-arm weight vectors are available across rebalances)
- `tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py` -- already has direct unit
  coverage of `l1_turnover`'s math; needs a new assertion once it's wired into the report output
- Related: [378](completed/378-vixy-emlc-feature-backfill-then-gate-b-and-portfolio-diagnostic.md)
  (the diagnostic this belongs to, closed with the "zero costs modeled" caveat this fixes)
