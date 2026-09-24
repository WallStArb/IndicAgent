---
status: closed
priority: P2
filed: 2026-09-24
closed: 2026-09-24
source: Phase 176-08 gate verdict, Query 2 / Step 5
---

# Re-decide alpha.ic.earnings_season_conditioned with a null-controlled rule

## What

176-08's pinned conditioning rule returned `CONDITIONING_VERDICT=SHARPENS`, so
`alpha.ic.earnings_season_conditioned` stayed `true` (`CONDITIONING_ROLLBACK=RETAINED`). The
support is thin: six features qualify in two or more tfs, each on 1 to 10 matched triples,
none among 176-01's 31 sweep survivors, while the population median in-season / parent
`|ic_sharpe_hac|` ratio is 0.96-1.03 in every tf. The rule had no minimum-N and no size-matched
null arm, and the in-season partition is about a third of each cell, so its statistics hit
extreme ratios more often under the null. `up_vol_body_diff`, the motivating feature, does not
qualify anywhere. Details: `.planning/phases/176-earnings-season-calendar-primitive-todo-353/176-GATE-VERDICT.md`.

Every full corpus run pays for the per-symbol and cross-sectional season passes while the key is
`true` (2.4M extra `feature_ic_scores` rows this run).

## Fix direction

Before the next full ic_engine corpus run: pre-register a rule with a minimum triple count per
(feature, tf) and a size-matched null (random calendar blocks of the same length and count as
the in-season window, same cells), evaluate it against the persisted 176-08 rows (no recompute
needed), and set the key through `ConfigService` with a `config_history` reason either way.

## Closure (2026-09-24)

Landed 5c82c8449 (migration 359, conditioning off). Pre-registration 9ac9cbac2.
