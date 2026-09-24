# Pre-registration: re-decide earnings-season conditioning with a dependence-robust null (todo 403)

Author: Claude Opus 5.5, 2026-09-24

Status: PRE-REGISTERED. Committed before the query below is run. The verdict section is
appended after the run and does not edit anything above it.

## Why re-decide

Phase 176-08's pinned rule returned `CONDITIONING_VERDICT=SHARPENS` and kept
`alpha.ic.earnings_season_conditioned = true`. That rule had no minimum N and no null: the six
qualifying features rest on 1 to 10 matched triples each, the population in-season / parent
`|ic_sharpe_hac|` ratio is 0.96 to 1.03 in every tf, and the in-season partition is about a
third of each cell, so its statistics reach extreme ratios more often by chance
(`.planning/phases/176-earnings-season-calendar-primitive-todo-353/176-GATE-VERDICT.md`). While
the key stays `true`, every full corpus run pays for the season passes (2.4M extra
`feature_ic_scores` rows in 176-08).

## Why this null, and not random calendar blocks

Todo 403 suggested a null built from random calendar blocks with the season's length and count.
That needs IC recomputed from raw rows, which the todo also rules out. The persisted cells
already carry what a size-matched test needs: every in-season and off-season cell has its own
block-bootstrap CI (`ic_ci_lower`, `ic_ci_upper`), computed on that partition's own sample. A
smaller partition gets a wider CI. A difference test that scales by those CIs is size-matched
by construction, and it can be evaluated on the persisted 176-08 rows with no recompute.

## Rule

Data: `feature_ic_scores`, `training_window_end = '2025-12-24 05:15:00+00'`, read-only.

1. Matched triples exactly as in 176-08's Rule 2 operationalization (in-season cell, off-season
   cell, unconditioned parent; per-symbol season cells matched to `regime_scope='pooled'`,
   cross-sectional sub-cells to their `cross_sectional` parent). A triple is usable iff the parent
   has `passes_fdr = true` and a nonzero `ic_value`, and both season cells have non-null
   `ic_value`, `ic_ci_lower` and `ic_ci_upper` with a positive CI width.
2. Per triple: `se = (ic_ci_upper - ic_ci_lower) / (2 * 1.959964)` for each season cell;
   `d = sign(ic_parent) * (ic_in - ic_off)`; `z = d / sqrt(se_in^2 + se_off^2)`. Positive `z`
   means the in-season effect is stronger in the parent's own direction.
3. Unit: (feature, tf), pooling per-symbol and cross-sectional triples as 176-08 did. A unit is
   eligible iff it has at least 10 usable triples.
4. Unit statistic: `m = median(z)`. Unit p-value: `p = min(1, 2 * (1 - Phi(m)))`. This bound
   holds under any dependence between a unit's triples (they share market factors across
   symbols): each `z` is marginally standard normal under the null, so
   `P(median >= m) <= P(#{z >= m} >= n/2) <= n * (1 - Phi(m)) / (n/2)` by Markov's inequality.
5. Multiplicity: Benjamini-Yekutieli at q = 0.05 across all eligible units (valid under
   arbitrary dependence between units).
6. Verdict:
   - `INSUFFICIENT_N` iff fewer than 30 eligible units. Key unchanged.
   - `SHARPENS` iff at least one feature is BY-significant in two or more tfs. Key stays `true`.
   - `NOT_SHARPENED` otherwise. Set `alpha.ic.earnings_season_conditioned = false` through a
     migration with a `config_history` reason citing this document. Rollback token `DISABLED`.
7. Mirror arm, reported alongside and not part of the verdict: the same rule with `d` negated
   (off-season stronger). If the mirror yields as many BY-significant units as the in-season arm,
   the verdict section says so.

## What this does not decide

- Whether earnings-season rows already persisted stay. They stay (never drop measured data).
- Whether conditioning on a different calendar primitive would sharpen. Out of scope.

## Verdict (run 2026-09-24, after the pre-registration commit 9ac9cbac2)

Script: `scripts/analysis/earnings_season_conditioning_null_controlled.py`, read-only against
window 2025-12-24 05:15 UTC.

- 682 (feature, tf) units have usable triples; 249 are eligible (at least 10 triples).
- Median over units of the unit `median(z)`: 5m -0.011, 15m -0.032, 1h +0.011, 1d -0.290. The
  central tendency is null in every tf, so the result is not only the bound's conservatism.
- In-season arm: 0 of 249 units BY-significant. Strongest: `bars_since_52w_low` 1h, median z
  +2.12 on 12 triples, p bound 0.034, far from the BY threshold.
- Mirror arm: 0 of 249. Strongest: `up_vol_ratio_fast` 1d, +2.49, p bound 0.013.
- Of 176-08's six qualifying features, only `trend_direction` 1h reaches the in-season top 15
  (median z +0.62, 10 triples); none comes near significance.

**CONDITIONING_VERDICT=NOT_SHARPENED.** `alpha.ic.earnings_season_conditioned` is set to `false`
by migration 359, rollback token `DISABLED`. The 176-08 SHARPENS token stands as what the old
rule returned; this rule supersedes it for the APR decision.
