---
status: completed
priority: P1
filed: 2026-08-08
resolved: 2026-08-08
source: user-directed rigor review of the plan to refine single-security alpha using
  Phase 163-165 features; reopens a partial finding from todo 179 (completed
  2026-07-31) that was never diagnosed to root cause
---

# Does `alpha_score` carry real per-symbol idiosyncratic breadth, or is it mostly
# re-deriving a single systematic directional bet? Diagnose before any sizing fix.

## What

Phase 148/166's Gate 2 (execution proof) fails primarily on concentration risk:
[todo 179](179-gate166-concurrent-exposure-diagnostic.md) found the OOS
champion population fires ~22 average simultaneous positions per bar (median 5, p90 68,
max 89), **~99.5% of them the same direction**. Dividing each frame's risk contribution
by concurrent-position count (zero change to entry/exit logic) nearly quadrupled Sharpe
(0.44 -> 1.96) and cut the max-drawdown ratio 40% (26.18 -> 15.79) — real, but still far
short of the 0.25 ceiling, and todo 179 closed without asking *why* the construction
co-fires this heavily in the first place.

## Why this matters more than the sizing fix

1/N-style risk-scaling patches the symptom (drawdown) without answering whether there's
real idiosyncratic information being spent.

## What to do

Check (1) cross-sectional correlation of `alpha_score`'s sign across symbols at the same
`bar_ts`, (2) whether removing the dominant systematic component recovers real,
lower-concentration signal, (3) whether that residual actually predicts forward returns.

## Resolution (2026-08-08)

`alpha_frames` (todo 179's original population) is now empty — regenerated/truncated away
since. Used `alpha_events` instead (8.86M rows, OOS-spanning, `direction`/`alpha_score`
columns) — the actual emission-gated signal stream, arguably more relevant than the raw
frame table for this question.

**Finding 1 — confirmed and sharpened, not just replicated.** Same-direction concurrency
is more extreme than todo 179's own number, across every timeframe (bar_ts >= 2025-12-24):

| tf | mean concurrent | pct same direction | n bars |
|---|---|---|---|
| 15m | 78.3 (of ~80) | **100.0%** | 1,721 |
| 1h | 34.8 | **100.0%** | 724 |
| 1d | 33.7 | **100.0%** | 123 |
| 5m | 10.5 | 99.6% | 10,757 |

At 15m/1h/1d, literally every symbol emitting in a given bar agrees on direction, every
single time. This is not "mostly correlated bets" — it's a single systematic call.

**Finding 2 — real nuance, not a flat "it's all one factor."** Cross-sectionally
demeaning `alpha_score` per `(tf, bar_ts)` and re-checking sign agreement on the
*residual*: drops to 54.1-61.8% (near-random 50% baseline) across all 4 tfs. So real
idiosyncratic dispersion does exist once the common per-bar level is removed — the
99.5-100% raw figure isn't because symbols have no relative information, it's because a
large, persistent common directional level swamps it in sign space almost every bar.
Variance decomposition confirms the common component is NOT dominant in variance terms
(explains only 12.0-34.6% of raw cross-sectional variance depending on tf) — it dominates
*sign outcomes* because its typical magnitude is large relative to the idiosyncratic
spread around it, not because idiosyncratic variance is negligible.

**Finding 3 — the residual carries the real (small) predictive signal; the common
component doesn't.** `forward_returns` only has OOS-window (bar_ts >= 2025-12-24) rows at
15m (`executable_open_to_open`, `complete_mid=true`) — 5m/1h/1d genuinely have zero rows
there, confirmed directly, not a query bug. At 15m (n=134,721): raw `alpha_score`'s
correlation with forward return is essentially zero/slightly negative (`ic_raw=-0.00129`);
the cross-sectionally-demeaned residual's correlation is small but positive and ~3.5x
larger in magnitude (`ic_residual=0.00453`). **Diagnostic-tier only** — plain Pearson
`corr()`, no day-clustered bootstrap, no shuffled null, no significance test. Not a gate
result, not proof, but a real and suggestive first look.

## Conclusion

`alpha_score` as currently constructed IS substantially a disguised single systematic
directional bet in sign-space — refining it by adding Phase 163-165's features to the
same linear ensemble combination will very likely reproduce this exact degeneracy,
regardless of feature quality, because the combination mechanism itself produces the
collapse, not a shortage of good inputs. The idiosyncratic residual (after removing the
per-bar common component) shows real dispersion and a suggestive positive IC where the
raw signal shows ~zero — pointing toward a construction that explicitly strips the common
component before trading (cross-sectional demeaning/ranking, same spirit as
`statistical_factor_residual`/`cross_sectional_relative_value`) rather than one more
attempt at the raw per-symbol directional construction.

## Follow-on (not this todo's scope, worth filing separately if pursued)

A properly-powered version of Finding 3 (day-clustered bootstrap, shuffled-ranking null,
BH-FDR, same discipline as everything else in this project) at 15m, since that's the only
tf with OOS `forward_returns` coverage right now. This is functionally close to testing
`alpha_score`'s own residual the same way `cross_sectional_relative_value` tested
`ctf_momentum`'s ranking — a natural, well-motivated next Signal-Extraction candidate if
the refinement plan proceeds down this path instead of the raw-feature-addition path.
