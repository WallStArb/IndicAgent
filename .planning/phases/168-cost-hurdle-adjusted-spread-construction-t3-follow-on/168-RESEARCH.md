# Phase 168: Cost-Hurdle-Adjusted Spread Construction (T3 Follow-On) - Research

**Researched:** 2026-07-31
**Domain:** Internal quant construction-layer extension (Python/asyncpg batch service,
day-clustered bootstrap statistics, TimescaleDB) — no new external technology, this is a
same-codebase extension of `services/cross_sectional_spread_tracker.py`
**Confidence:** HIGH (code shape, schema, reuse of existing bootstrap machinery — all verified
by direct file read) / MEDIUM (hysteresis margin calibration formula — a genuinely new design
choice, no prior in-repo precedent) / LOW-ASSUMED (specific numeric calibration constants — must
be measured empirically during Wave 0, not assumed here)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01 — Rebalance mechanism: leg-level hysteresis band, not a portfolio-level gate.** The
cost-floor rule operates per-leg, not per-bar-as-a-whole. A symbol currently held in a leg stays
held unless a challenger's rank/score clears a cost-derived margin to displace it. Rejected
alternative: an all-or-nothing "rebalance the whole bar or skip it" gate. This is a small,
natural extension of the existing turnover-measurement machinery (already reads the prior bar's
legs), not new infrastructure. Matches item 5's own literal wording: "trade only ranking
*changes*" (plural, per-instrument).

**D-02 — Construction identity: parallel construction_name, never in-place mutation.** Ship as a
second `construction_spreads.construction_name` value — `ctf_momentum_decile_ls_cost_gated`
(existing baseline is `ctf_momentum_decile_ls`) — computed by the same service class,
parameterized by the new rebalance rule, not a duplicated file. The existing validated baseline
must keep running unmutated so the before/after comparison stays measurable indefinitely,
matching this project's shadow-parity precedent (dual-write + parity-audit pattern, Phase 142B's
counterfactual-before-capital discipline).

**D-03 — Cost-floor value: flat, reusing Phase 167's already-validated 10bp binding tier.** Use
a single flat cost-floor value for the live per-leg gating decision — the same 10bp round-trip
tier Phase 167's Gate 1 already passed at (the most conservative of the four tiers
`net_spread_by_cost_bps` sweeps: 1/3/5/10bp, `alpha.construction.cost_hurdle_bps_round_trip` APR
key). Rejected for v1: a per-symbol liquidity-tier-aware floor — confirmed via direct grep that
this breakdown was never built as queryable infrastructure (no `liquidity_tier` tag exists in
`tag_vocabulary` or anywhere in code).

**D-04 — This phase's Validation Gate: four-part bar, not a single Sharpe comparison.** Promote
the cost-gated construction only if, measured against the `ctf_momentum_decile_ls` baseline over
the identical window:
1. Net-of-cost Sharpe at the 10bp tier improves, with a bootstrap CI on the **delta** (not two
   separately-overlapping point estimates) that clears zero.
2. Gross (pre-cost) spread has NOT meaningfully degraded — hysteresis could quietly hold a
   stale/wrong-signal leg past when it should exit, and cost savings alone could mask that in
   the net number.
3. Turnover reduction is reported as an instrument/diagnostic, not a pass/fail criterion on its
   own.
4. The shuffled-ranking null is re-run against the NEW construction specifically (not inherited
   from baseline).
A flat-or-worse result is an explicitly legitimate outcome (same posture as Phase 143.1's
sign-symmetric HOLD verdict) — this gate can genuinely fail, and that's useful information, not
a phase failure.

### Claude's Discretion

- Exact hysteresis band width / margin formula (e.g., derived from cost-floor ÷ marginal
  IC-per-rank-position, vs. a simpler fixed-rank-buffer) is left to research/planning — the
  *mechanism* (leg-level, cost-derived margin) is locked; the specific calibration is not.
- Whether the parity/comparison query lives as a new script (T3-script-style, matching Phase
  167's own `t3_cross_sectional_long_short_ctf_momentum_check.py` precedent) or as a permanent
  view/report over `construction_spreads` is a planning-level implementation choice.

### Deferred Ideas (OUT OF SCOPE)

- **Per-symbol empirical liquidity-tier cost floor** — deriving a per-symbol transaction-cost
  estimate empirically from `market_data_ohlcv_tradeable` (e.g., Corwin-Schultz high-low spread
  estimator, Amihud illiquidity ratio). Explicitly gated on Phase 168 shipping and its D-04 gate
  resolving first (pass or HOLD) — should become its own future phase, not a `pending/` todo.
- **Hysteresis band calibration methodology** — left to research/planning (this document), not
  locked in CONTEXT.md.
- No live capital, no execution/portfolio-sizing infrastructure (Phase 156-159).
- No new features, no per-symbol liquidity taxonomy.
- No change to the ranking feature (`ctf_momentum`), timeframe (`15m`), or universe (80-symbol
  equity) — Phase 167 already validated these.

</user_constraints>

<phase_requirements>
## Phase Requirements

No `phase_req_ids` are registered for Phase 168 (`phase_req_ids` is null in ROADMAP.md) — this
phase is scoped entirely by its own `168-CONTEXT.md` (D-01 through D-04 above), not by
`.planning/REQUIREMENTS.md` IDs. `.planning/REQUIREMENTS.md` does not exist in this repository
(confirmed: file read attempt returned "does not exist"), consistent with this project's
per-phase CONTEXT.md-driven planning model rather than a global requirements register. The
planner should treat D-01 through D-04 as the binding requirement set for this phase, mapped to
research support below:

| ID | Description | Research Support |
|----|-------------|-------------------|
| D-01 | Leg-level hysteresis rebalance rule | See "Architecture Patterns" — new `hysteresis_legs()` function slots between `decile_legs()` and `one_way_turnover()`; concrete algorithm and margin-formula recommendation below |
| D-02 | Parallel `construction_name`, no baseline mutation | See "Package/Schema" section — confirmed zero schema change; `_CONSTRUCTION_NAME` becomes a per-instance/parameterized attribute, not a module constant |
| D-03 | Flat 10bp cost floor, reuse existing APR key | See "Architecture Patterns" — reuse `max(alpha.construction.cost_hurdle_bps_round_trip)`, no new cost-value APR key needed |
| D-04.1 | Delta-CI Sharpe gate | See "Don't Hand-Roll" — `frame_gate_passes`/`evaluate_frame_gate` are domain-agnostic and directly reusable on a paired delta series; only the delta-series construction is new |
| D-04.2 | Gross-spread non-degradation check | See "Architecture Patterns" — reuse `evaluate_spread_gate`-style day-clustered comparison on `gross_spread_{fast,slow}`, or a simpler mean-delta diagnostic |
| D-04.3 | Turnover-reduction diagnostic (non-gating) | Directly available from already-persisted `one_way_turnover` column for both construction_names — pure SQL aggregation, no new code |
| D-04.4 | Shuffled-ranking null re-run against new construction | See "Common Pitfalls" — the existing null (`shuffled_ranking_null_p`) is memoryless/stateless and CANNOT be reused unmodified for a stateful hysteresis construction; needs a sequential-state variant |

</phase_requirements>

## Summary

Phase 168 is a pure extension of an already-shipped, already-validated service
(`services/cross_sectional_spread_tracker.py`, Phase 167, both live Validation Gates PASSED
2026-07-27). Nothing about the domain, database, or statistical toolchain is new — the entire
phase is: (1) a new leg-selection function that adds "stickiness" to the existing decile-ranking
mechanic, (2) a second logical partition in an already-future-proofed table
(`construction_name` is `text`, no enum, zero schema change), and (3) a new comparison/gate mode
that reuses the exact day-clustered bootstrap machinery Phase 167 already reuses from
`counterfactual_tracker.py`, applied to a *paired delta* series instead of a single arm.

The one place this phase requires genuinely new design (not just wiring) is the hysteresis
margin/band-width calibration (Claude's Discretion) and the shuffled-ranking null for the new
construction, because the null as currently implemented is **memoryless per-bar** (each shuffle
draw permutes one bar's ranks independently and recomputes legs from scratch) while the
hysteresis construction is **stateful across bars** (this bar's legs depend on which symbols
were held last bar). A permutation-based null for a stateful construction must simulate the
entire sequential leg-holding history under each shuffled draw, not just recompute one bar in
isolation — this is a real, scoped extension, not a drop-in reuse, and should be sized as its
own task/plan.

The delta-CI machinery for D-04 criterion 1, by contrast, needs **no new statistics at all**:
`counterfactual_tracker.frame_gate_passes`/`evaluate_frame_gate` operate on an arbitrary
`(value, cluster_id)` sequence and compute a one-sided 95% CI that the *mean* clears zero — they
have no knowledge of what "value" represents. Feeding them a per-bar **delta** series
(`net_spread_cost_gated[bar_ts] - net_spread_baseline[bar_ts]`, day-clustered by `bar_ts::date`)
at the binding 10bp cost tier produces exactly the delta-CI D-04.1 asks for, using the identical
function Phase 167 already calls. The only new work is building that aligned, matched-bar delta
series from two already-persisted `construction_spreads` partitions — pure SQL/Python wiring, no
new bootstrap.

**Primary recommendation:** Add a `CrossSectionalSpreadTracker` constructor parameter
(`construction_variant: str`, default the existing baseline behavior) rather than a subclass or
second file, matching D-02's explicit mandate. Add one new pure function
`hysteresis_legs(prior_long, prior_short, ranked_symbols, feature_values, decile_fraction,
margin) -> tuple[list[str], list[str]] | None` that sits between the existing `decile_legs()`
call and the existing `one_way_turnover()` call, implementing a standard "buffer rule" /
"banding" mechanism (the same pattern index providers like Russell/FTSE use to reduce
reconstitution turnover — see Sources). Add a fourth CLI mode,
`--evaluate-delta-gate`, to the same service file, reusing `write_verdict_artifact` for a new
`gate_delta` verdict. For the margin formula itself, recommend an empirically-calibrated,
cost-derived z-score margin (Option A below) as primary, with a fixed-rank-buffer (Option B) as
the pragmatic fallback if Option A's calibration step is judged too much for a v1 pass — both
are laid out with concrete tradeoffs in Architecture Patterns.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Leg-level hysteresis decision (D-01) | Batch compute service (`services/`) | — | Pure function, no I/O; same tier as existing `decile_legs()`/`one_way_turnover()` |
| Cost-hurdle net-of-cost computation | Batch compute service | — | Unchanged, reused verbatim (`net_spread_by_cost_bps`) |
| Second construction_name persistence | Database/Storage (TimescaleDB) | Batch compute (writer) | `construction_spreads` hypertable, DAG invariant #3 (writer, not inline compute, but this service already owns its own writes per Phase 167 precedent — see Pitfall note below) |
| Delta-CI Validation Gate (D-04.1) | Batch compute service (read-only reporting branch) | — | Same shape as existing `--evaluate-gate`/`--evaluate-attribution` modes, bare `asyncpg.connect`, no pool |
| Gross-spread non-degradation check (D-04.2) | Batch compute service | — | Same reporting branch as above |
| Turnover diagnostic (D-04.3) | Database/Storage (SQL aggregation) | Batch compute | Directly queryable from persisted `one_way_turnover` column, no new compute needed |
| Shuffled-ranking null, new construction (D-04.4) | Batch compute service | — | Needs a new stateful/sequential null-simulation loop (see Common Pitfalls) |
| Verdict artifact | Filesystem/audit-trail (`logs/construction_verdicts/`) | — | Reuses `write_verdict_artifact` unchanged |
| APR keys (margin, etc.) | Database/Storage (`config_schema`/`config_state`) | — | Standard APR migration pattern, matches migration 260/261 |

No browser/client or frontend-server tier applies — this is a headless batch analytics service,
same as its Phase 167 predecessor.

## Standard Stack

No new libraries. This phase is 100% additive code inside an existing, already-pinned stack:

### Core (existing, reused unchanged)
| Library | Version (as pinned in repo) | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `asyncpg` | already pinned | DB pool, cursors, jsonb codec | `BaseBatch`'s required driver (DAG invariant); `cross_sectional_spread_tracker.py` already imports it |
| `numpy` | already pinned | RNG for shuffled null, `lstsq` for attribution regression | Already used by `shuffled_ranking_null_p`/`attribution_verdict` in the same file |
| `structlog` | already pinned | Logging | Matches every batch service in the repo |

### Alternatives Considered
None — CLAUDE.md and D-02 both mandate extending the existing service class, ruling out any
new-library or new-service-architecture alternative before it could be considered.

**Installation:** none required — no `pip install` / `npm install` for this phase.

## Package Legitimacy Audit

**Not applicable.** This phase installs zero new external packages. All code additions live
inside `services/cross_sectional_spread_tracker.py` (and possibly a new migration file and a new
test file), using only `asyncpg`, `numpy`, and `structlog`, all already present in
`requirements`/pinned and already imported by this exact module. The Package Legitimacy Gate
protocol (slopcheck, registry verification) is therefore skipped — there is nothing to audit.

## Architecture Patterns

### System Architecture Diagram

```
feature_vectors (ctf_momentum) ─┐
forward_returns (return_fast/   ├──► Panel query (unchanged, _PANEL_SQL_TEMPLATE)
  return_slow, executable OTO)  ┘         │
                                           ▼
                          decile_legs(symbols, values, decile_fraction)
                                           │
                              (baseline)   │   (cost-gated, NEW)
                                 │         ▼
                                 │   hysteresis_legs(prior_long, prior_short,
                                 │      symbols, values, decile_fraction, margin)
                                 │         │
                                 ▼         ▼
                          spread_from_legs()   [UNCHANGED — same function, either leg set]
                                           │
                                           ▼
                          one_way_turnover(prior_legs, cur_legs)   [UNCHANGED]
                                           │
                                           ▼
                          net_spread_by_cost_bps()   [UNCHANGED]
                                           │
                                           ▼
                    INSERT construction_spreads (construction_name = variant-specific)
                                           │
                    ┌──────────────────────┴──────────────────────┐
                    ▼                                              ▼
     --evaluate-gate / --evaluate-attribution          --evaluate-delta-gate  (NEW)
     (per-construction, UNCHANGED, run twice —         reads BOTH construction_name
      once per construction_name)                       partitions, joins on bar_ts,
                                                          builds paired delta series,
                                                          feeds frame_gate_passes(),
                                                          runs gross-spread check,
                                                          runs turnover diagnostic,
                                                          runs NEW stateful shuffled null
                                                                │
                                                                ▼
                                              write_verdict_artifact("gate_delta", ...)
                                              [UNCHANGED helper, new verdict_name]
```

### Recommended Project Structure

No new files required beyond a migration and a test file — matches D-02's "same service class,
parameterized" mandate literally:

```
services/
└── cross_sectional_spread_tracker.py   # extended in place:
                                          #   - new hysteresis_legs() pure function
                                          #   - CrossSectionalSpreadTracker gains a
                                          #     construction_variant constructor param
                                          #   - new --evaluate-delta-gate CLI mode +
                                          #     _run_evaluate_delta_gate()
production/migrations/
└── 27X_construction_cost_gated_apr.sql # new APR keys (margin formula params)
tests/unit/
└── test_cross_sectional_spread_tracker.py  # extended: hysteresis_legs cases,
                                              # delta-gate grouping, stateful null
tests/integration/
└── test_cross_sectional_spread_tracker.py  # extended: second construction_name
                                              # backfill row-per-bar, watermark
                                              # scoped independently per construction_name
```

### Pattern 1: Hysteresis leg selection (D-01) — the "buffer rule" / "banding" pattern

**What:** A currently-held leg member is displaced only when a challenger's feature-value
margin over the held member's feature value exceeds a threshold. This is the same mechanism
index providers (Russell, FTSE) call "banding": a constituent already in the index stays unless
it falls outside a wider buffer zone around the inclusion threshold, specifically to reduce
turnover from small, meaningless rank changes while still admitting large, meaningful ones
[CITED: lseg.com/en/insights/ftse-russell — Russell reconstitution banding methodology].

**When to use:** Exactly Phase 168's D-01 mechanism — per-leg, per-symbol, pairwise comparison,
never a whole-bar gate.

**Concrete algorithm (recommended):**

```python
def hysteresis_legs(
    prior_long: frozenset[str],
    prior_short: frozenset[str],
    ranked_symbols: Sequence[str],
    feature_values: Sequence[float],
    decile_fraction: float,
    margin: float,
) -> tuple[list[str], list[str]] | None:
    """Leg-level hysteresis: a held symbol stays held unless a challenger's feature value
    clears `margin` over the weakest held member's value. Symmetric for long/short legs.

    Same input-validation contract as decile_legs() (raises on length mismatch / non-finite
    values) — reuses that function's target/ideal ranking as the starting point, then applies
    stickiness on top.
    """
    ideal = decile_legs(ranked_symbols, feature_values, decile_fraction)
    if ideal is None:
        return None  # same degenerate-universe rule as the baseline construction
    ideal_short, ideal_long = ideal
    n_leg = len(ideal_long)

    value_by_symbol = dict(zip(ranked_symbols, feature_values, strict=True))
    present = set(ranked_symbols)

    # A previously-held symbol that has dropped out of this bar's panel entirely
    # (feature/return unavailable) cannot be "held" — force-exit it. This is the one
    # case hysteresis MUST NOT override: there is no return series to attribute a held
    # position to.
    held_long = {s for s in prior_long if s in present}
    held_short = {s for s in prior_short if s in present}

    def resolve_leg(held: set[str], ideal_leg: list[str], direction: int) -> list[str]:
        # direction=+1 for long (higher value = stronger), -1 for short (lower = stronger)
        challengers = sorted(
            (s for s in present if s not in held),
            key=lambda s: direction * value_by_symbol[s],
            reverse=True,
        )
        leg = sorted(held, key=lambda s: direction * value_by_symbol[s], reverse=True)
        # Trim oversized legs first (universe shrank) by weakest-held-first.
        leg = leg[:n_leg]
        ci = 0
        while len(leg) < n_leg and ci < len(challengers):
            leg.append(challengers[ci]); ci += 1
        # Displacement pass: weakest held vs strongest remaining challenger.
        changed = True
        while changed and ci < len(challengers):
            changed = False
            leg.sort(key=lambda s: direction * value_by_symbol[s])  # weakest first
            weakest = leg[0]
            challenger = challengers[ci]
            if direction * (value_by_symbol[challenger] - value_by_symbol[weakest]) > margin:
                leg[0] = challenger
                ci += 1
                changed = True
        return leg

    long_leg = resolve_leg(held_long, ideal_long, direction=1)
    short_leg = resolve_leg(held_short, ideal_short, direction=-1)
    return short_leg, long_leg
```

This is deliberately a **new function**, not a modification of `one_way_turnover()` — CONTEXT.md's
"code_context" section phrases D-01 as extending `one_way_turnover()`, but the actual code
insertion point is *before* turnover measurement, between `decile_legs()`'s ranking output and
`one_way_turnover()`'s frozenset-diff call. `one_way_turnover()` itself needs **zero code
changes**: it already takes `(prev_long, prev_short, cur_long, cur_short)` frozensets and is
agnostic to how `cur_long`/`cur_short` were produced.

**Edge case that must be designed explicitly (no existing precedent covers it):** a currently
held symbol whose feature value has moved to the *opposite* side of the cross-section (a former
long holding whose momentum reversed to strongly negative) is handled correctly by the algorithm
above because `resolve_leg` only searches among `present` symbols not already held by *this*
leg — it does not special-case "was held by the other leg." A symbol cannot be held by both legs
simultaneously by construction (each leg's `resolve_leg` call is independent, but since a
`decile_fraction <= 0.5` keeps `2*n_leg <= n`, and `ideal_long`/`ideal_short` are disjoint by
`decile_legs()`'s own construction, held-long and held-short sets should never overlap under a
correctly-implemented hysteresis rule — the planner should add a unit test asserting
`long_leg` ∩ `short_leg` == ∅` as a correctness invariant, since a bug here would be exactly
the "silent wrong answer" class CLAUDE.md forbids).

### Pattern 2: Margin formula — two options, both concrete

**Option A (recommended, cost-derived per D-01's literal wording):** Convert the flat cost floor
into a required feature-value margin using an empirically-measured "bps per unit feature z-score"
conversion constant, computed ONCE from data Phase 167 already measured (not a live model):

```
margin_z = cost_floor_bps_round_trip / bps_per_feature_z
```

where `bps_per_feature_z` is a new APR key (e.g. `alpha.construction.bps_per_feature_z`),
seeded `[initial_estimate]` from a one-time calculation:
`gross_spread_fast_bp_mean / mean(long_leg_feature_value - short_leg_feature_value)` over the
Phase 167 backfilled corpus (both quantities are already persisted in `construction_spreads`,
so this is a single read-only SQL query the planner scopes as a Wave 0 calibration task, not new
statistical machinery). At `cost_floor_bps_round_trip=10` and Phase 167's already-published
`gross_spread_fast≈5.9bp` over roughly a full decile-to-decile spread, this produces a bounded,
data-grounded margin rather than an arbitrary constant.

**Tradeoff:** requires one calibration query before the margin is meaningful (small, bounded,
one-time — not equivalent to the deferred "0c calibration" work in
`trade-construction-layer.md`, which is about calibrating the *signal itself* into return units
for sizing; this is only calibrating a conversion factor for the *hysteresis threshold*). Still
introduces one new empirical constant that must be documented with its provenance
`[initial_estimate]` per APR mandate, and re-validated if `ctf_momentum`'s cross-sectional
distribution shifts materially.

**Option B (fallback, simpler):** A fixed-rank-buffer — a challenger must be more than `N`
rank-positions better than the weakest held member to displace it (`N` an APR key, e.g.
`alpha.construction.hysteresis_rank_buffer`, integer, default 1-2). This is NOT literally
"cost-derived" in the sense of dollars/bps, but can be *validated as* cost-effective empirically
by treating `N` as a small grid (`{0, 1, 2, 3}`) swept against the D-04 gate itself during
planning/execution — the smallest `N` that clears D-04's delta-CI is the calibrated answer,
consistent with "earn complexity through proof" rather than deriving `N` analytically up front.

**Recommendation:** Ship Option A as the v1 mechanism (it more literally satisfies D-01's locked
"cost-derived margin" wording and requires no new statistical machinery, only one calibration
query), but design the margin computation as a single, swappable function
(`resolve_margin_z(cfg) -> float`) so Option B can be substituted with a one-line change if
Option A's calibration constant proves unstable across the OOS window (a real risk worth a Wave 0
check: compute `bps_per_feature_z` separately on in-sample vs. OOS segments and confirm they are
not wildly divergent before trusting a single corpus-wide constant).

### Pattern 3: Delta-CI gate (D-04.1) — reuse, don't reimplement

`frame_gate_passes(pnl_r_values, cluster_ids, min_n, bootstrap_max_n, bootstrap_batch,
bootstrap_random_state)` (`services/counterfactual_tracker.py:173`) takes an arbitrary sequence
of scalar values and cluster ids and returns `(passes, ci_lower, ci_upper)` where `passes` is
`ci_lower > 0`. It has no knowledge of "pnl" semantics. Feed it a **delta series**:

```python
# Build the paired, bar-aligned delta at the binding (max) cost tier, per scale.
binding_bps = max(cost_bps)  # matches Gate 1's own binding-tier convention
delta_values = []
cluster_ids = []
for bar_ts in sorted(set(cost_gated_rows) & set(baseline_rows)):
    net_gated = cost_gated_rows[bar_ts][f"net_spread_{scale}_by_cost_bps"][str(binding_bps)]
    net_base = baseline_rows[bar_ts][f"net_spread_{scale}_by_cost_bps"][str(binding_bps)]
    delta_values.append(net_gated - net_base)
    cluster_ids.append(bar_ts.date())

passes, ci_lower, ci_upper = frame_gate_passes(
    delta_values, cluster_ids, min_n, bootstrap_max_n, bootstrap_batch, bootstrap_random_state
)
# passes == True means the delta's 95% CI clears zero: the cost-gated construction's
# net-of-cost spread is statistically distinguishable-and-better than the baseline's,
# NOT two overlapping point estimates (exactly D-04.1's requirement).
```

This has **no precedent for the "delta" framing specifically** in this codebase — a targeted
search of `gate166_frame_recalibration_eval.py` (the closest prior "compare candidate vs.
baseline" gate in this project, Phase 166) confirms it evaluates each candidate's CI
*independently* and compares point estimates, exactly the "two separately-overlapping point
estimates" pattern D-04.1 explicitly rejects. Phase 168 is the first construction-comparison gate
in this codebase to require a genuine paired-delta CI. The reuse insight above (feed the SAME
function a delta series) means this is still zero new bootstrap code — only the delta-series
construction (the SQL/Python wiring to align two `construction_spreads` partitions on `bar_ts`)
is new.

**Recommended implementation location:** a new `--evaluate-delta-gate` CLI mode inside
`cross_sectional_spread_tracker.py` (matching `--evaluate-gate`/`--evaluate-attribution`'s
existing shape: bare `asyncpg.connect`, read-only, `write_verdict_artifact("gate_delta", ...)`),
rather than a new standalone script. Phase 167's own `t3_cross_sectional_long_short_ctf_momentum_check.py`
precedent was a standalone script specifically because no production service existed yet at that
point; Phase 168 is explicitly comparing two already-productionized `construction_spreads`
partitions written by the same service class (D-02), so the natural, D-02-consistent home is a
fourth mode on the same class, not a resurrection of the pre-productionization script pattern.

### Pattern 4: Gross-spread non-degradation check (D-04.2)

Simplest correct implementation: run the SAME day-clustered `frame_gate_passes` machinery on the
**delta of `gross_spread_{fast,slow}`** (not net-of-cost) between the two constructions, but
gate on a **non-degradation** criterion rather than "improves": pass iff
`ci_upper` (the delta's upper CI bound) does not fall meaningfully below zero — i.e., the
gross-spread delta's CI does not exclude zero-or-better. Concretely: reuse `frame_gate_passes`
but interpret its return value differently (a "no meaningful degradation" pass condition is
`ci_lower > -epsilon_bps` for some small tolerance, or simply: the delta's CI does not lie
entirely below zero). This is a mechanical variant of the same reused function — no new
statistics, only a different pass/fail interpretation of the same CI output, which the planner
should implement as a distinct small wrapper (`gross_spread_not_degraded(delta_values,
cluster_ids, ...)`) rather than overloading `frame_gate_passes`'s own `passes` semantics.

### Pattern 5: Turnover-reduction diagnostic (D-04.3)

No new code needed beyond a read-only SQL aggregation — both constructions already persist
`one_way_turnover` per bar:

```sql
SELECT construction_name, avg(one_way_turnover) AS mean_turnover,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY one_way_turnover) AS median_turnover
FROM construction_spreads
WHERE construction_name IN ('ctf_momentum_decile_ls', 'ctf_momentum_decile_ls_cost_gated')
  AND tf = '15m' AND bar_ts >= $1  -- alpha.validation.oos_start
  AND one_way_turnover IS NOT NULL
GROUP BY construction_name;
```

Reported in the verdict artifact as a labeled `diagnostic` block, explicitly NOT contributing to
`gate_delta_passes` (per D-04.3's own "instrument, not pass/fail" framing) — this distinction
should be structurally visible in the payload shape (a separate `diagnostics` key, never mixed
into the `passes`-bearing fields), mirroring how Gate 1's `in_sample_diagnostic_grid` is already
kept structurally separate from `oos_grid` in the existing `gate1` artifact.

### Anti-Patterns to Avoid

- **Do not compute `bps_per_feature_z` (Option A's margin conversion) live/per-run.** It should
  be a calibrated-once APR constant with `[initial_estimate]` provenance, re-measured
  deliberately (a new migration/config_history entry) if revisited — never silently recomputed
  inside the hot path, which would make the margin threshold itself drift bar-to-bar in a way
  that defeats reproducibility of the gate verdict.
- **Do not implement the delta-CI by subtracting two independently-computed `ci_lower` values.**
  That reproduces exactly the "two separately-overlapping point estimates" failure mode D-04.1
  is written to prevent (Phase 166's gate166 script is the in-repo example of this anti-pattern
  being used correctly for a *different* purpose — independent-candidate scoring — but it is the
  wrong shape for a paired comparison).
- **Do not reuse `shuffled_ranking_null_p`/`mean_gross_spread_over_bars` unmodified for the
  cost-gated construction's null.** They are memoryless per-bar (see Common Pitfalls) — doing so
  would silently test the wrong null hypothesis (whether the decile-ranking mechanic is real, not
  whether the *hysteresis+decile* mechanic is real) and produce a confidently wrong D-04.4
  verdict.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Day-clustered bootstrap CI (single-arm or delta) | A new bootstrap/CLT implementation | `counterfactual_tracker.frame_gate_passes`/`evaluate_frame_gate` | Domain-agnostic over `(value, cluster_id)` pairs; already handles the BCa-vs-CLT method switch at scale, already seeded/reproducible via `alpha.scoring.bootstrap_random_state` |
| Verdict artifact persistence | A new JSON-writing helper | `write_verdict_artifact()` (`cross_sectional_spread_tracker.py:460`) | Already handles non-finite coercion, strict-JSON, accumulate-never-overwrite with second-level collision handling (WR-05 fix already landed) |
| APR config loading/validation | Ad hoc `os.environ`/direct config reads | `services/_batch_utils.py`'s `load_apr_dict_async`/`cfg()` + `validate_construction_config()` pattern | Matches the ASVS V5 range-validation-at-load pattern already established for this exact module |
| Cross-sectional decile ranking | A new ranking function | `decile_legs()` (`cross_sectional_spread_tracker.py:114`) — call it first to get the "ideal" target, then apply hysteresis on top | Already proven correct, already has the tie-break/NaN-guard invariants this phase must not regress |

**Key insight:** Every statistical and infrastructural primitive Phase 168 needs already exists
in this codebase and was purpose-built by Phase 167 for exactly this class of problem (day-
clustered spread-portfolio gating). The only genuinely new code is (1) the hysteresis
leg-selection function itself, (2) the delta-series construction/wiring for D-04.1/D-04.2, and
(3) the stateful null-simulation loop for D-04.4. Everything else is composition of existing,
already-tested functions.

## Common Pitfalls

### Pitfall 1: Reusing the memoryless shuffled null for a stateful construction

**What goes wrong:** `shuffled_ranking_null_p` (`cross_sectional_spread_tracker.py:318`) permutes
each bar's feature values independently and recomputes `decile_legs` from scratch every bar,
every draw — it has no concept of "held from last bar." If called as-is against the cost-gated
construction (i.e., swapping in `hysteresis_legs` for `decile_legs` inside a copy of the same
loop), each simulated bar would compute hysteresis against the **real, unshuffled** prior bar's
held legs while using **shuffled** current-bar ranks — a hybrid that tests neither the real
mechanism nor a coherent null.

**Why it happens:** The existing null was correctly designed for a memoryless construction; the
new construction is stateful. The function signature doesn't obviously signal this incompatibility
— it would run without error and produce a plausible-looking but wrong `null_p`.

**How to avoid:** Build a new null-simulation function that, per shuffle draw, walks bars in
`bar_ts` order and carries forward *that draw's own* simulated `(prior_long, prior_short)` state
— i.e., the null must simulate a full alternate hysteresis-construction history per draw, not a
single independently-shuffled bar. This is the direct structural analogue of the live
`CrossSectionalSpreadTracker._execute_inner`'s own `process_bar` closure (which already threads
`prior_long`/`prior_short` via `nonlocal`), so the pattern to copy is that closure's state-passing
shape, not `shuffled_ranking_null_p`'s current stateless one.

**Warning signs:** A `null_p` for the cost-gated construction that looks suspiciously similar to
the baseline's already-published `null_p=0.0` values without having changed the null's actual
mechanics — if the new null is a copy-paste of the old one with `decile_legs` swapped for
`hysteresis_legs` and nothing else, it silently tests the wrong hypothesis.

### Pitfall 2: `--backfill` prior-leg seeding bug class (already fixed once, watch for recurrence)

**What goes wrong:** Phase 167's own code review (CR-01, now fixed) found that `--backfill`
mode seeding `prior_long`/`prior_short` from the table's globally-latest row (rather than
`frozenset()`) fabricates a non-null `one_way_turnover` for what should be the genuinely-first
bar. The fix already lives in the shipped code (`_execute_inner`, lines ~912-923: `mode ==
"backfill"` unconditionally seeds empty frozensets). **When adding a second
`construction_name` variant, this exact bug class can reappear** if the watermark/prior-leg
query is not scoped by `construction_name` — a backfill of the NEW `ctf_momentum_decile_ls_cost_gated`
partition must not accidentally seed its "prior legs" from the OLD `ctf_momentum_decile_ls`
partition's rows (they are different construction identities and must never cross-contaminate
turnover/hysteresis state).

**How to avoid:** Every SQL query touching `construction_spreads` in the extended service
(`_GATE_ROWS_SQL`, the prior-row seed query, the watermark query) already filters by
`construction_name = $1` — the planner must verify the SAME filter is threaded through for the
new variant's own `_CONSTRUCTION_NAME`-equivalent value, and that a construction-name mismatch
cannot silently leak state between the two partitions. Add a unit/integration test explicitly
asserting that backfilling the cost-gated variant when the baseline variant already has rows
produces the same result as backfilling into an empty table (the exact regression CR-01 fixed
for the single-construction case, now needed for the two-construction case).

### Pitfall 3: Held symbol drops out of the current bar's panel

**What goes wrong:** The panel query filters `fv.ctf_momentum IS NOT NULL AND fr.complete_fast =
true AND fr.complete_slow = true AND i.is_active = true` — a symbol can legitimately disappear
from a single bar's cross-section (a data gap, a temporarily-inactive instrument). If the
hysteresis logic doesn't explicitly handle "a held symbol is absent from `ranked_symbols` this
bar," a naive implementation might either crash (KeyError looking up its feature value) or
silently retain it in the leg with a stale/missing return contribution.

**How to avoid:** Pattern 1's algorithm above explicitly filters `held_long =
{s for s in prior_long if s in present}` before any margin comparison — an absent held symbol is
force-exited, never silently retained. This must be unit-tested directly (a symbol present in
`prior_long` but absent from this bar's `ranked_symbols`).

### Pitfall 4: `long_leg` / `short_leg` overlap after hysteresis

**What goes wrong:** Because `resolve_leg` is called independently for the long and short legs,
a bug that lets the same symbol end up in both (e.g., a symbol whose feature value flips sign
extremely and both legs' challenger searches independently pick it up before checking the other
leg's membership) would silently corrupt `spread_from_legs()`'s dollar-neutral assumption.

**How to avoid:** Add an explicit invariant check/assertion (`assert not (set(long_leg) &
set(short_leg))`) either inside `hysteresis_legs` itself (raising `ValueError`, matching this
module's established "fail loud" convention) or as a dedicated unit test covering an adversarial
feature-value sequence designed to probe this. Given `decile_fraction <= 0.5` is already
range-validated by `validate_construction_config`, and `ideal_long`/`ideal_short` from
`decile_legs()` are disjoint by construction, this should not be reachable with a correct
implementation — but it is exactly the class of failure that would be a "silent wrong answer"
if it ever did occur, so a hard assertion is warranted per CLAUDE.md's stated discipline.

### Pitfall 5: Margin formula drift between in-sample and OOS

**What goes wrong:** If Option A's `bps_per_feature_z` conversion constant is calibrated only on
in-sample data and the cross-sectional distribution of `ctf_momentum` (or the realized
gross-spread-per-unit-z relationship) shifts materially OOS, the margin threshold could be
mis-calibrated for the exact window D-04's gate is measured against — biasing the result in
either direction without it being visible in the gate's own output.

**How to avoid:** As noted in Pattern 2, compute the conversion constant separately on in-sample
vs. OOS segments during Wave 0 and confirm they are not wildly divergent (a simple sanity check,
not a new statistical framework) before trusting a single corpus-wide constant baked into an APR
seed.

## Code Examples

### Reused, unchanged: day-clustered bootstrap gate call shape

```python
# Source: services/counterfactual_tracker.py:173 (frame_gate_passes signature, verified by
# direct file read 2026-07-31)
passes, ci_lower, ci_upper = frame_gate_passes(
    pnl_r_values=delta_values,       # NEW for Phase 168: a delta series, not a raw pnl series
    cluster_ids=cluster_ids,          # day-of-bar_ts, same convention as every other gate
    min_n=min_n,                      # alpha.scoring.min_strategy_n APR key, existing
    bootstrap_max_n=bootstrap_max_n,  # alpha.scoring.bootstrap_max_n APR key, existing
    bootstrap_batch=bootstrap_batch,  # alpha.scoring.bootstrap_batch APR key, existing
    bootstrap_random_state=bootstrap_random_state,  # alpha.scoring.bootstrap_random_state, existing
)
```

### Reused, unchanged: verdict artifact write

```python
# Source: services/cross_sectional_spread_tracker.py:460 (write_verdict_artifact, verified by
# direct file read 2026-07-31)
artifact_path = write_verdict_artifact("gate_delta", payload)  # new verdict_name, same helper
```

### New: schema confirmation — zero migration needed for the second construction_name

```sql
-- production/migrations/260_construction_spreads_schema.sql:50 (verified by direct file read)
-- construction_name is `text NOT NULL`, deliberately not an enum, specifically so future
-- constructions can be added "without schema churn" (migration 260's own comment, line 47-49).
-- PRIMARY KEY (construction_name, tf, bar_ts) already partitions correctly by construction
-- identity. Confirms CONTEXT.md's own claim: Phase 168 needs ZERO schema migration for the
-- construction_spreads table itself. Only a migration for new APR keys (margin formula
-- constants) is needed.
```

## State of the Art

Not applicable in the usual "external ecosystem changed" sense — this is an internal-codebase
extension. The one relevant "state of the art" note is domain-external: hysteresis/banding
rebalance rules are a decades-old, well-established mechanism in index construction (Russell/FTSE
methodology), not a novel technique this phase is inventing — see Sources.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Option A's `bps_per_feature_z` conversion constant, calibrated once from Phase 167's already-persisted `gross_spread_fast`/leg-value-gap data, produces a stable and meaningful margin threshold | Architecture Patterns, Pattern 2 | If the relationship between feature-value gap and realized spread is materially non-linear or unstable across the OOS window, the margin could be mis-calibrated, producing either too-sticky (misses real signal changes) or too-loose (no turnover reduction) hysteresis. Mitigated by the explicit in-sample-vs-OOS drift check in Pitfall 5, but that check itself is new work, not yet run. |
| A2 | A fourth `--evaluate-delta-gate` CLI mode on the same service class is the correct architectural home (vs. a standalone script) | Architecture Patterns, Pattern 3 | This is a planning-level implementation choice CONTEXT.md explicitly leaves open (Claude's Discretion); if the planner disagrees, a standalone script mirroring `t3_cross_sectional_long_short_ctf_momentum_check.py`'s shape is a reasonable, low-risk alternative — no functional consequence either way, only a maintainability preference. |
| A3 | `hysteresis_legs()`'s recommended pairwise "weakest-held vs. strongest-challenger, iterate until stable" algorithm shape is the correct interpretation of D-01's "leg-level hysteresis" wording | Architecture Patterns, Pattern 1 | An alternative valid interpretation (not developed in depth here) could instead gate on the *aggregate* leg composition change rather than pairwise per-symbol swaps; the pairwise version was chosen because it most literally matches D-01's own "a symbol... stays held unless a challenger... clears a margin" per-instrument phrasing, and because it composes cleanly with the existing `one_way_turnover()` frozenset-diff measurement without any changes to that function. |
| A4 | Next-free migration number is 275 (highest on disk is 274 as of this research session) | Architecture Patterns, Recommended Project Structure | Per todo 095's documented collision risk (also called out explicitly in Phase 167's own migration 260 header), the planner/executor MUST re-verify `ls production/migrations/ \| sort -n \| tail` against the live DB immediately before applying any new migration — this number can and has drifted between research and execution in concurrent-session scenarios (see MEMORY.md's `feedback_concurrent_sessions_shared_dir`). |

## Open Questions

1. **Should the gross-spread non-degradation check (D-04.2) share statistical machinery with the
   Sharpe-delta gate (D-04.1), or should it be a simpler descriptive comparison (e.g., a fixed
   percentage-degradation tolerance band, not a bootstrap CI)?**
   - What we know: D-04.2's own wording ("has NOT meaningfully degraded") is softer than D-04.1's
     "improves... clears zero" — it may not need the full rigor of a bootstrap CI to be a
     legitimate check.
   - What's unclear: whether a simple threshold ("gross spread delta mean within ±X% of
     baseline") is sufficient, or whether the same bootstrap-CI rigor D-04.1 uses should apply
     for consistency and to avoid a double standard within the same four-part gate.
   - Recommendation: default to reusing the same `frame_gate_passes` delta-CI machinery (Pattern
     4 above) for consistency and because it's already available at zero marginal statistical
     cost — but flag this for the planner's/discuss-phase's explicit confirmation since CONTEXT.md
     did not fully specify D-04.2's statistical rigor level.

2. **How many bars does the OOS window actually contain for the cost-gated construction once
   built?** Phase 167's own OOS window (`alpha.validation.oos_start`) produced 650 bars / 130
   day-clusters for the baseline — comfortably above `alpha.scoring.min_strategy_n=30`. The
   cost-gated construction runs over the identical window/universe, so this should carry over
   directly, but the planner should confirm this is still true (no shrinkage from the hysteresis
   mechanism itself, which doesn't skip bars any differently than the baseline) rather than
   assume it.

3. **What is the correct behavior when `hysteresis_legs` returns `None` (degenerate universe,
   same rule as `decile_legs`) but `prior_long`/`prior_short` are non-empty?** The existing
   baseline's `process_bar` simply skips the bar entirely and does not update `prior_long`/
   `prior_short` (they retain their pre-skip value for the next real bar). The planner should
   confirm this same "skip and carry forward unchanged state" behavior is correct for the
   cost-gated variant too (it should be — a degenerate bar has no valid legs to persist as new
   "prior" state either way), and add an explicit test for it (Phase 167's own test suite does
   not appear to test this exact interaction for the baseline, based on the test name list
   reviewed).

## Environment Availability

Skipped — this phase has no new external dependencies. It runs entirely inside the existing
TimescaleDB/asyncpg/Python venv stack already confirmed live and in active use by
`services/cross_sectional_spread_tracker.py` (Phase 167, shipped and running `--evaluate-gate`/
`--evaluate-attribution` against the live DB as of 2026-07-27). `.venv/bin/pytest` and
`PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent` are both already-verified
working commands per CLAUDE.md.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4+ (`pytest-asyncio` 1.1+, `asyncio_mode=auto`) — same as Phase 167 |
| Config file | `pytest.ini` (repo root) |
| Quick run command | `.venv/bin/pytest tests/unit/test_cross_sectional_spread_tracker.py -x` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| D-01 | `hysteresis_legs()` basic stickiness (held symbol survives a small challenger margin) | unit | `pytest tests/unit/test_cross_sectional_spread_tracker.py::test_hysteresis_legs_holds_below_margin -x` | ❌ Wave 0 |
| D-01 | `hysteresis_legs()` displaces when margin cleared | unit | `pytest tests/unit/test_cross_sectional_spread_tracker.py::test_hysteresis_legs_displaces_above_margin -x` | ❌ Wave 0 |
| D-01 | Held symbol absent from current panel force-exits (Pitfall 3) | unit | `pytest tests/unit/test_cross_sectional_spread_tracker.py::test_hysteresis_legs_force_exits_absent_symbol -x` | ❌ Wave 0 |
| D-01 | Long/short leg disjointness invariant (Pitfall 4) | unit | `pytest tests/unit/test_cross_sectional_spread_tracker.py::test_hysteresis_legs_no_overlap -x` | ❌ Wave 0 |
| D-02 | Backfilling cost-gated variant with baseline rows already present does not leak state (Pitfall 2) | integration (requires_db) | `pytest tests/integration/test_cross_sectional_spread_tracker.py::test_backfill_second_construction_name_isolated -x` | ❌ Wave 0 |
| D-04.1 | Delta-series construction aligns matching `bar_ts` correctly, feeds `frame_gate_passes` | unit | `pytest tests/unit/test_cross_sectional_spread_tracker.py::test_evaluate_delta_gate_alignment -x` | ❌ Wave 0 |
| D-04.4 | New stateful shuffled null produces a coherent per-draw sequential simulation (Pitfall 1) | unit | `pytest tests/unit/test_cross_sectional_spread_tracker.py::test_stateful_shuffled_null_carries_state -x` | ❌ Wave 0 |
| D-04 | `--evaluate-delta-gate` live run produces a real verdict artifact | manual/integration | `services/cross_sectional_spread_tracker.py --evaluate-delta-gate` against live DB after both constructions are backfilled | ❌ Wave 0 (manual, matches Phase 167's own Manual-Only Verifications precedent) |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/test_cross_sectional_spread_tracker.py -x`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -q`
- **Phase gate:** Full suite green, PLUS a live `--evaluate-delta-gate` run producing a real
  (not mocked) D-04 verdict — mirrors Phase 167-VALIDATION.md's own binding rule that a unit-test
  pass alone does not constitute "the construction is validated."

### Wave 0 Gaps
- [ ] `tests/unit/test_cross_sectional_spread_tracker.py` — extend with `hysteresis_legs()`
      cases (stickiness, displacement, absent-symbol force-exit, no-overlap invariant),
      delta-series alignment, stateful null
- [ ] `tests/integration/test_cross_sectional_spread_tracker.py` — extend with second-
      construction-name backfill isolation
- [ ] No new test framework install needed

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | Internal batch service, no auth surface (matches Phase 167) |
| V3 Session Management | No | N/A |
| V4 Access Control | No | N/A |
| V5 Input Validation | Yes | APR range-validation-at-load pattern (`validate_construction_config`-style), extended to cover the new margin/rank-buffer APR key(s) — matches Phase 167's own T-167-01 threat treatment |
| V6 Cryptography | No | No secrets/crypto surface in this phase |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|-----------------------|
| SQL injection via caller-supplied filter values | Tampering | Already mitigated repo-wide by asyncpg `$1`/`$2` placeholder binding — no string interpolation of caller values into SQL text (T-167-04 precedent, must be preserved in any new query for the delta-gate mode) |
| Malformed/out-of-range APR value silently accepted | Tampering / Denial of Service | Extend `validate_construction_config` (or add a parallel validator) to range-check the new margin/rank-buffer APR key(s) before any panel work begins, raising `ValueError` rather than clamping (T-167-01 precedent) |
| Cross-construction state leakage (Pitfall 2) | Tampering / Information Disclosure (of a wrong verdict, not literal data exposure) | Every `construction_spreads` query must filter by `construction_name`; add an explicit isolation test as scoped above |

## Sources

### Primary (HIGH confidence — direct file reads this session)
- `services/cross_sectional_spread_tracker.py` (full file, 1658 lines) — all function
  signatures, the CLI entrypoint, the existing `--evaluate-gate`/`--evaluate-attribution` shape
- `services/counterfactual_tracker.py` — `frame_gate_passes` (line 173),
  `evaluate_frame_gate` (line 907), `_DEFAULT_BOOTSTRAP_RANDOM_STATE` (line 84)
- `production/migrations/260_construction_spreads_schema.sql` — full schema, APR seed pattern
- `production/migrations/261_construction_null_p_threshold.sql` — confirms WR-01 already fixed
- `production/migrations/270_construction_spreads_compression.sql` — compression policy pattern
- `docs/research/trade-construction-layer.md` — Minimal Design step 5, Validation Gates section,
  full live-verdict transcription
- `.planning/phases/167-cross-sectional-trade-construction-t3/167-CONTEXT.md`,
  `167-VALIDATION.md`, `167-REVIEW.md` — locked D-01 through D-05, test infrastructure shape,
  the CR-01/WR-01/WR-05 findings this phase must not regress
- `scripts/analysis/gate166_frame_recalibration_eval.py` (structure grep) — confirmed no
  existing paired-delta-CI precedent in this codebase; every prior "candidate vs. baseline"
  gate in this repo uses independent single-arm CIs

### Secondary (MEDIUM confidence)
- [Russell reconstitution June 2026: Larger leaders, stronger small caps | LSEG](https://www.lseg.com/en/insights/ftse-russell/russell-reconstitution-june-2026-larger-leaders-stronger-small-caps) — confirms the "banding"/buffer-rule mechanism as an established, real-world index-construction pattern analogous to the recommended `hysteresis_legs()` design
- [Four Decades of Russell US Indexes Reconstitution | LSEG](https://www.lseg.com/content/dam/ftse-russell/en_us/documents/research/four-decades-russell-reconstitution.pdf) — background on banding's turnover-reduction purpose

### Tertiary (LOW confidence)
- None — no unverified single-source claims were used for load-bearing recommendations in this
  document. The margin-formula recommendation (Option A) is flagged in the Assumptions Log as
  needing empirical Wave 0 validation, not presented as a verified fact.

## Metadata

**Confidence breakdown:**
- Standard stack / schema / reuse of existing bootstrap machinery: HIGH — every claim verified
  by direct read of the actual source file, migration file, or test file this session
- Hysteresis leg-selection algorithm shape: MEDIUM — a reasoned design grounded in an
  established external pattern (index banding) and this codebase's own conventions (frozenset
  diffing, fail-loud invariants), but genuinely new code with no in-repo precedent to verify
  against
- Margin calibration formula (Option A's specific numeric approach): LOW-ASSUMED — the mechanism
  (cost-floor ÷ empirically-measured bps-per-feature-z) is a first-principles design choice, not
  verified against any existing calibration in this codebase; flagged in Assumptions Log (A1) as
  needing a Wave 0 empirical stability check before being trusted as a locked constant
- Stateful shuffled-null requirement: HIGH — derived directly from reading the existing
  `shuffled_ranking_null_p`/`mean_gross_spread_over_bars` implementation and confirming it is
  memoryless per-bar; the conclusion that a stateful construction needs a different null
  implementation follows directly from that code, not from assumption

**Research date:** 2026-07-31
**Valid until:** 30 days (stable, internal-codebase domain — no external ecosystem to go stale;
re-verify the migration-number Assumption A4 immediately before execution regardless of this
window, per todo 095's standing collision-risk note)
