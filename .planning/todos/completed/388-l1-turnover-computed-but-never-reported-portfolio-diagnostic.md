---
status: closed
priority: P2
filed: 2026-09-22
closed: 2026-09-23
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
- Related: [378](378-vixy-emlc-feature-backfill-then-gate-b-and-portfolio-diagnostic.md)
  (the diagnostic this belongs to, closed with the "zero costs modeled" caveat this corrects)

## Closed 2026-09-23 -- premise was stale; the real residual is re-filed as todo 393

The todo's central claim ("turnover never shipped into the per-arm output") was wrong, and its
recommended fix would have regressed a real bug fix. What actually happened, verified against
git history before acting (todo 308's standing lesson):

1. **Turnover reporting shipped with the diagnostic itself.** Commit `9c2a8fa24` (2026-09-16,
   "walk-forward orchestration") wired per-arm per-rebalance turnover into every step dict,
   `mean_turnover` into the aggregates, and the printed per-arm line -- exactly what this todo
   asked for, six days before it was filed.
2. **`l1_turnover()` was then deliberately retired from the live path.** Commit `821c67cef`
   (2026-09-16, "symbol-misaligned turnover" fix) replaced the positional-array `l1_turnover`
   call with the per-symbol dict turnover computation, because a positional array silently
   misaligns (or crashes) when the active instrument set changes composition between refits --
   which the spec allows by design. The dict version computes the same
   `sum(|w_t - w_{t-1}|)` over the union symbol set, generalizing it to set changes. Vulture's
   "zero callers" flag was real dead code, not an unwired feature.
3. **Action taken here:** deleted the dead `l1_turnover` + its two unit tests + the
   vulture_whitelist entry (whose "real gap, not dead code" comment encoded this todo's wrong
   premise). 25 tests green after deletion.
4. **The "zero costs modeled" caveat does NOT close with turnover reporting.** Root-caused
   without needing the DB: `alpha_events.cost_hurdle` is not a transaction cost at all -- it is
   `alpha_publisher`'s emission-gate threshold (min CI lower bound, alpha_score units; migration
   182), seeded `0.0` by design and set to `0.0` for 1d by explicit `[user_preference]`
   ("costs negligible at daily horizon"). The diagnostic multiplies it by weight-change and
   subtracts it from log returns: wrong quantity, wrong units, structurally always zero at this
   diagnostic's 1d cadence. Migration 260's own comments carry a Pitfall warning against
   exactly this confusion with the real bps-based cost mechanism
   (`alpha.construction.cost_hurdle_bps_round_trip`). The honest heir of this todo's intent is
   filed as [393](../pending/393-portfolio-diagnostic-cost-proxy-semantically-wrong.md): give the
   diagnostic a real per-instrument cost proxy (spec update required first, per the module's
   own "do not fix without updating the spec" docstring).
