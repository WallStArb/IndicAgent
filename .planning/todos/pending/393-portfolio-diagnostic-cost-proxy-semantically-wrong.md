---
status: pending
priority: P2
filed: 2026-09-23
source: root-caused closing todo 388 (whose "turnover never reported" premise was stale); this is
  the honest heir of 388's "close the zero-costs caveat on todo 378's result" intent
---

# The portfolio diagnostic's cost proxy is the wrong quantity in the wrong units -- `net_realized_return` is structurally gross at 1d

## What

`run_walk_forward` (scripts/analysis/portfolio_covariance_weighting_diagnostic.py) prices each
rebalance as `sum(per_symbol_turnover * cost_hurdle_row[sym])`, where `cost_hurdle_row` comes
from `alpha_events.cost_hurdle`. That column is **not a transaction cost**:

- It is `alpha_publisher`'s emission-gate threshold -- the min CI lower bound (in **alpha_score
  units**) an emission must clear (`alpha.quant.cost_hurdle.{tf}` APR keys, migration 182).
- Migration 182 seeded all four keys `0.0` ("no-op; raise after calibration"), and for
  `1h`/`1d` specifically records `[user_preference]`: "costs negligible at hourly/daily
  horizon; set to 0.0."
- Migration 260's config_schema comments carry an explicit Pitfall warning against confusing
  this key with the real per-instrument cost mechanism
  (`alpha.construction.cost_hurdle_bps_round_trip`, bps round-trip).

Consequences, both verified from code/migrations (no DB needed):

1. **Structural zero at this diagnostic's cadence.** It runs at `tf='1d'`, where the key is
   user-preference-0.0 -- so `cost` is 0.0 for every step, every arm, forever. This is the
   actual mechanism behind todo 378's "zero transaction costs modeled" caveat
   (`cost=0.0` every step), NOT a missing reporting feature (todo 388's wrong premise).
2. **Wrong units even if nonzero.** Multiplying an alpha_score-unit threshold by a weight
   fraction and subtracting the result from log returns is dimensionally meaningless. Raising
   the APR key to "fix" the zero would inject nonsense, not cost.

The spec itself specified this ("using `alpha_events`' existing cost_hurdle as the
per-instrument cost proxy", Output section) -- the design borrowed a same-named column without
checking what it measures. The module docstring's "do not fix any of this without updating the
spec first" rule applies: the fix starts with a spec revision, not a code edit.

## Fix

1. Spec update first (docs/superpowers/specs/2026-09-16-cross-instrument-covariance-aware-
   portfolio-diagnostic-design.md, Output section): choose a real per-instrument cost source.
   Candidates to evaluate against already-built work (build-vs-OSS lens): the migration-260 bps
   round-trip mechanism (`alpha.construction.cost_hurdle_bps_round_trip` +
   `ops_cost_hurdle_calibration.py` output), a per-instrument spread/ADV-based hurdle, or
   explicitly dropping the cost/net-return fields (a diagnostic that reports gross-only and
   says so is cleaner than one carrying a vacuous `net_realized_return`).
2. Re-point `_fetch_alpha_scores_and_cost_hurdle`/`run_walk_forward`'s cost math at the chosen
   source; keep turnover reporting as-is (correct since `821c67cef`).
3. Re-run the diagnostic only if a real cost source lands (the 2026-09-22 Gate B numbers'
   "gross, not net" caveat stands until then).

Standing rule that still governs ([[feedback_execution_costs_not_gating]]): cost is a reported
diagnostic, never the flip condition on any verdict -- this todo fixes a meaningless number,
it does not add a gate.

## Where

- `scripts/analysis/portfolio_covariance_weighting_diagnostic.py` -- cost_hurdle fetch (lines
  ~561-610), per-step cost computation (~459-461), `net_realized_return`, aggregate
  `mean_cost`/`mean_net_realized_return`, printed per-arm line
- `services/alpha_publisher.py:97-104` -- what `alpha_events.cost_hurdle` actually is
- `production/migrations/182_alpha_cost_hurdle.sql` -- the 0.0 seeds + [user_preference] 1d
- `production/migrations/260_construction_spreads_schema.sql:100,131` -- the Pitfall warning
- Related: [388](../completed/388-l1-turnover-computed-but-never-reported-portfolio-diagnostic.md)
  (closed with the correction that surfaced this), [378](../completed/378-vixy-emlc-feature-backfill-then-gate-b-and-portfolio-diagnostic.md)
  (the result whose "zero costs modeled" caveat this actually addresses)

Proposed P2: real value (the diagnostic's net-return output is currently meaningless and its
headline Sharpe numbers are gross), but nothing gates on it and the caveat is disclosed
everywhere the numbers are cited. Tier is the owner's call.
