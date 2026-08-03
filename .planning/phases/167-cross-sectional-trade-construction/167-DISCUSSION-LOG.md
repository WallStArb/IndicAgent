# Phase 167: Cross-Sectional Trade Construction (cross_sectional_relative_value) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-26
**Phase:** 167-cross-sectional-trade-construction
**Areas discussed:** Ranking input (raw feature vs. ensemble_alpha), feature scope (single vs.
composite), rebalance cadence (per-bar replica vs. cost-gated), universe/tf scope
(15m/equity-80 vs. broader), cost-hurdle treatment (already applied, carried forward)

**Mode:** `--auto` (no interactive AskUserQuestion turns) — this session had already produced
the deep research (cross_sectional_relative_value's falsification script, cost-hurdle sweep, temporal-stability check)
that would normally come from an interactive discussion, so auto-resolution used that existing
evidence rather than generic recommended defaults.

---

## Ranking input: raw feature vs. ensemble_alpha

| Option | Description | Selected |
|--------|-------------|----------|
| Rank on `ctf_momentum` directly | Bypasses the linear ensemble combiner entirely; matches exactly what cross_sectional_relative_value's falsification script measured and validated | ✓ |
| Rank on `ensemble_alpha` | Reuses existing per-symbol combiner output; broader infra reuse but tests an unvalidated, already-Gate-2-failed input | |

**Selected:** Rank on `ctf_momentum` directly.
**Notes:** This is the load-bearing decision of the whole phase. `ensemble_alpha` is the exact
construction Phase 148's Gate 2 failed and todo 179 found has zero regime-conditional edge —
building Phase 167 on top of it would silently retest a rejected input under a new name. cross_sectional_relative_value's
entire result rests on ranking the raw feature.

---

## Feature scope: single feature vs. composite

| Option | Description | Selected |
|--------|-------------|----------|
| `ctf_momentum` only | Exact feature/construction cross_sectional_relative_value validated | ✓ |
| Multi-feature composite score | More "production-grade" but reopens the combiner question the ranking-input decision just resolved the other way | |

**Selected:** `ctf_momentum` only for v1.
**Notes:** Renaissance discipline — earn complexity through proof. Composite scoring is a
legitimate fast-follow once this single-feature construction is live and shadow-validated, not
a v1 requirement.

---

## Rebalance cadence: per-bar replica vs. cost-gated

| Option | Description | Selected |
|--------|-------------|----------|
| Rebalance every bar | Exactly matches cross_sectional_relative_value's measured turnover (~19.5% mean one-way/bar) and its confirmed cost-hurdle survival | ✓ |
| Trade only on ranking changes clearing a cost floor | `trade-construction-layer.md`'s stated future optimization; lower turnover, but untested in this exact form | |

**Selected:** Per-bar replica for v1.
**Notes:** Don't change two variables at once — prove the construction itself works in shadow
measurement before also testing a turnover-reduction optimization on top of it.

---

## Universe/timeframe scope

| Option | Description | Selected |
|--------|-------------|----------|
| 15m, full 80-symbol equity universe | Exactly what cross_sectional_relative_value measured, including the 21/21-year temporal-stability check | ✓ |
| Broader (5m/1h/1d and/or other asset classes) | Untested for this construction; cross_sectional_relative_value's evidence is 15m/equity-specific | |

**Selected:** 15m, equity-80 only.
**Notes:** Extending scope is future work once this exact, proven slice is live.

---

## Cost-hurdle treatment

| Option | Description | Selected |
|--------|-------------|----------|
| Apply todo 030's blended cost-floor convention to actual measured turnover | Already run this session — survives at every tested floor (1-10bp round-trip), both lookahead scales | ✓ |
| Defer cost treatment to a later phase | Would leave ROADMAP Phase 167's own stated "first open item" unresolved | |

**Selected:** Already applied, carried forward as a locked finding.
**Notes:** Formalized into `t3_cross_sectional_long_short_ctf_momentum_check.py`'s
`_cost_hurdle_check` function this session, not left as a one-off scratchpad calculation.

---

## Claude's Discretion

- Shadow-measurement architecture (new table vs. reuse `alpha_frames`) — left for the
  researcher/planner to resolve via codebase investigation, not a user-preference decision.
- Exact `BaseBatch` service shape and file naming — standard implementation detail, not
  discussed.

## Deferred Ideas

- Multi-feature composite ranking (future phase, once single-feature construction proves out)
- Cost-floor-gated rebalance-on-ranking-change optimization (fast-follow)
- Additional timeframes/asset classes (5m/1h/1d, rates/commodity/fx)
- Kelly-fraction sizing, risk modeling, borrow-cost modeling (explicitly out of v1 scope per
  `trade-construction-layer.md`)
