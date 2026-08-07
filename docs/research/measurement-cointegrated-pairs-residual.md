# Cointegrated Pairs Residual — Idea (Edge Source Thesis cointegrated_pairs_residual)

**Status:** Pre-registered and run 2026-08-07. **DEAD.** 0/6 named pairs cointegrate in-sample
(Stage 1) — Stages 2-5 never needed to run. See Result below.
**Author:** Claude (Sonnet 5), interactive session, 2026-08-07 — not a Fable dispatch.
**Origin:** Post-mortem of Phase 167's retraction (`ctf_momentum`'s batch-join lookahead leak,
todo 243). Part of the fork-resolution discovery track: back to Signal-Extraction candidates,
not construction, until one independently proves edge.
**Companion to:** `docs/research/data-edge-source-thesis.md` (this is candidate thesis
**cointegrated_pairs_residual**, one of five Signal-Extraction candidates added 2026-08-03).

---

## The core point

A genuinely different grouping than `regime_conditional_persistence` (discrete regime) or
`cross_sectional_relative_value` (broad cross-sectional rank): specific, economically-linked pairs tested for a
stable cointegrating relationship whose short-run deviations mean-revert — the classical
Engle-Granger/Johansen stat-arb structure. This universe's binding constraint (effective breadth
~8-15 across 80 correlated ETFs) rules out a blind correlation scan but doesn't rule out
*economically motivated* pairs — that's exactly the distinction this design enforces.

## Named pairs only — no correlation scan

Admitting only structurally-linked pairs avoids the exact multiple-comparisons trap this
project's own FDR discipline exists to catch — a merely-correlated pair of distinct sector ETFs
is a factor exposure question (`statistical_factor_residual`'s territory), not a cointegration
candidate.

| Pair | Linkage |
|---|---|
| `EEM` / `VWO` | Both track broad emerging markets |
| `EFA` / `EZU` | Overlapping developed-ex-US / Eurozone baskets |
| `MCHI` / `FXI` | Both track China large-cap |
| `IEF` / `TLT` | Same yield curve, different duration |
| `GDX` / `GLD` | Gold miners vs. the metal they extract |
| `OIH` / `XOP` | Oilfield services vs. E&P — overlapping energy exposure |

Confirmed live 2026-08-07: all 6 have deep, complete OHLCV history at 5m/15m/1d, fresh through
2026-07-28.

## Staged design

**Stage 1 — Cointegration screen (daily closes, in-sample).**
`statsmodels.tsa.stattools.coint(log_price_a, log_price_b)` per pair — existing project
dependency (already used for BH-FDR elsewhere via `statsmodels.stats.multitest`), zero new
library risk. This specific function has zero prior usage in this repo; it's the one genuinely
new external call this design introduces. Reject any pair with p ≥ 0.05.

**Stage 2 — OOS stability check.** Re-run Stage 1 on the held-out OOS window alone. A pair
cointegrated in-sample but not OOS is noise, not structure — dropped regardless of Stage 1's
result.

**Stage 3 — Ornstein-Uhlenbeck fit** for pairs that survive both. Model the spread as
`dX_t = θ(μ - X_t)dt + σdW_t`, fit `θ` via OLS on the discretized AR(1) form
(`X_{t+1} - X_t = θ(μ - X_t)Δt + ε`), derive half-life `ln(2)/θ`. This replaces an arbitrary
lookback-window z-score with a closed-form, data-fitted parameter — no hand-tuned lookback to
justify, standard stat-arb sizing/holding-period signal for a cointegrated spread.

**Stage 4 — Falsification bar.** Does the OU-implied z-score predict forward reversion?
Day-clustered bootstrap CI (`ic_math.py::_circular_block_bootstrap_ic`) on residual-z vs.
`forward_returns.executable_open_to_open`, at `tf=15m` (the turnover/cost-relevant tf — not
`1d`, which would hide the turnover cost this construction structurally incurs). If CI crosses
zero for every surviving pair, dead.

**Stage 5 — Cost gate, pre-registered before seeing the Stage 4 number.** Same cost-hurdle sweep
that already killed `ctf_vwap_align`/`ctf_regime_align` on turnover, applied to the netted
spread at the most conservative cost tier. A mean-reverting spread traded on a z-score band is
structurally high-turnover — this gate isn't optional, and reporting Stage 4's number without it
would repeat the exact mistake that killed those two sibling features only after they'd already
cleared their CI.

## Reuse plan — what's new code vs. existing primitives

| Need | Source |
|---|---|
| Fetch daily/15m closes | `services/backfill_feature_factory.py::_fetch_bars_from_db`, `_connect_db` |
| Engle-Granger cointegration test | `statsmodels.tsa.stattools.coint` (existing dependency, standard implementation) |
| OU parameter fit | `statsmodels.regression.linear_model.OLS` (existing dependency) |
| Day-clustered bootstrap CI | `src/intelligence/statistics/ic_math.py::_circular_block_bootstrap_ic` |
| Cost-hurdle sweep | Reuse `cross_sectional_relative_value`'s existing cost-tier sweep logic (`services/cross_sectional_spread_tracker.py`), not a new implementation |
| Spread construction, z-score, OU half-life derivation | **New** — pure glue, ~15-20 lines total |

## Data verified live, 2026-08-07

`market_data_ohlcv_tradeable`, `feature_vectors` @ 15m, and `forward_returns` (all
`executable_open_to_open`) are solid for all 12 symbols across the 6 pairs — matching row
counts, fresh through 2026-07-28. Stages 1-4 touch none of the tables affected by the concurrent
CTF-fix corpus work.

**One caveat, deliberately sequenced:** Stage 5's optional comparison against existing
per-feature IC context would read `feature_ic_scores`, which is currently incomplete for these
12 symbols — a live `ic_engine.py --refresh --tf 15m` process (unrelated, a separate corpus pass
over the rates/fx/commodity/sector universe) was still running as of this doc's writing, per-symbol
rows only, no cross-sectional aggregation finalized yet, 15m-only. Wait for that job to finish
before trusting any `feature_ic_scores` read for these symbols. Does not block Stages 1-4.

## Promotion boundary

A PASS here does not auto-promote to a live construction — that is a separate, later decision.
If it does promote, `construction_spreads`' existing schema (`construction_name`, per-cost-tier
`net_spread_*_by_cost_bps` JSONB) is the pattern to follow for a live tracker, matching
`ctf_momentum_decile_ls`'s shape — not a new table design.

## Result (run 2026-08-07)

**DEAD.** Engle-Granger test (`statsmodels.tsa.stattools.coint`, `trend="c"`, `autolag="aic"`),
in-sample split (`--split-date 2024-01-01`):

| Pair | In-sample p-value | Stage 1 |
|---|---|---|
| EEM/VWO | 0.2116 | FAIL |
| EFA/EZU | 0.6185 | FAIL |
| MCHI/FXI | 0.6628 | FAIL |
| IEF/TLT | 0.2408 | FAIL |
| GDX/GLD | 0.4069 | FAIL |
| OIH/XOP | 0.7399 | FAIL |

**0/6 pairs pass Stage 1** (all p ≥ 0.05, most well above it — no pair is even borderline).
Stages 2-5 (OOS stability, OU fit, bootstrap CI, cost gate) never ran — nothing survived to feed
them. This is a clean, unambiguous negative result per the pre-registered rule: none of the
6 economically-linked pairs this project's own instrument universe offers show a genuine
cointegrating relationship at daily granularity. Script:
`scripts/analysis/cointegrated_pairs_residual_pilot.py`.

## References

- `docs/research/data-edge-source-thesis.md` — hub doc, thesis summary
- `services/cross_sectional_spread_tracker.py` — existing cost-hurdle sweep + D-04 gate governance pattern
- `src/intelligence/statistics/ic_math.py` — reused statistical primitives
