# Phase 168: Cost-Hurdle-Adjusted Spread Construction (T3 Follow-On) - Context

**Gathered:** 2026-07-31
**Status:** Ready for planning

<domain>
## Phase Boundary

Build `trade-construction-layer.md`'s Minimal Design item 5 — "trade only ranking changes that
clear a per-trade cost floor" — the rebalance rule Phase 167 deliberately deferred (its own
D-03: "implementing it in the SAME pass as building the construction changes two variables at
once... build the exact-replica version first, prove it holds up, then evaluate the
reduced-turnover variant as a fast-follow with its own before/after comparison"). This phase
turns the existing `cross_sectional_spread_tracker.py`'s cost-hurdle sweep — currently a
LIVE-computed but purely descriptive measurement (`net_spread_by_cost_bps`, informing nothing)
— into a real, prescriptive construction-layer decision that controls which legs get swapped
each bar, then proves that decision actually improves net-of-cost Sharpe relative to Phase 167's
already-validated exact-replica baseline.

Does NOT touch live capital, does NOT build execution/portfolio-sizing infrastructure (still
gated behind Phase 156-159 per STATE.md), does NOT add new features, does NOT build a per-symbol
liquidity taxonomy (deferred — see below), does NOT change the ranking feature (`ctf_momentum`),
tf (`15m`), or universe (80-symbol equity) Phase 167 already validated.

</domain>

<decisions>
## Implementation Decisions

### Rebalance mechanism: leg-level hysteresis band, not a portfolio-level gate
- **D-01:** The cost-floor rule operates per-leg, not per-bar-as-a-whole. A symbol currently
  held in a leg stays held unless a challenger's rank/score clears a cost-derived margin to
  displace it. Rejected alternative: an all-or-nothing "rebalance the whole bar or skip it"
  gate — economically wrong, since the cost of swapping symbol A is independent of whether
  symbol B also needs swapping. This is a small, natural extension of the existing
  `one_way_turnover()` function (already reads the prior bar's legs), not new infrastructure.
  Matches item 5's own literal wording: "trade only ranking *changes*" (plural, per-instrument).

### Construction identity: parallel construction_name, never in-place mutation
- **D-02:** Ship as a second `construction_spreads.construction_name` value —
  `ctf_momentum_decile_ls_cost_gated` (existing baseline is `ctf_momentum_decile_ls`, defined as
  `_CONSTRUCTION_NAME` in `services/cross_sectional_spread_tracker.py:111`) — computed by the
  same service class, parameterized by the new rebalance rule, not a duplicated file. The
  existing validated baseline must keep running unmutated so the before/after comparison D-03
  calls for stays measurable indefinitely, matching this project's shadow-parity precedent
  (dual-write + parity-audit pattern from the v2.1 era, and Phase 142B's counterfactual-before-
  capital discipline). Overwriting the baseline in place would destroy the only mechanism that
  makes this phase's own claim provable.

### Cost-floor value: flat, reusing Phase 167's already-validated 10bp binding tier
- **D-03:** Use a single flat cost-floor value for the live per-leg gating decision — the same
  10bp round-trip tier Phase 167's Gate 1 already passed at (the most conservative of the four
  tiers `net_spread_by_cost_bps` sweeps: 1/3/5/10bp, `alpha.construction.cost_hurdle_bps_round_trip`
  APR key). Rejected for v1: a per-symbol liquidity-tier-aware floor (todo 030's own "liquid
  core / sector ETFs / illiquid international" breakdown) — confirmed via direct grep that this
  breakdown was never built as queryable infrastructure (no `liquidity_tier` tag exists in
  `tag_vocabulary` or anywhere in code; it's a qualitative description in a todo doc, not a
  reusable primitive). Building it now would change a second, unvalidated variable in the same
  pass — exactly what D-03 (Phase 167) warned against. See Deferred Ideas below for the
  follow-on this becomes.

### This phase's Validation Gate: four-part bar, not a single Sharpe comparison
- **D-04:** Promote the cost-gated construction only if, measured against the
  `ctf_momentum_decile_ls` baseline over the identical window:
  1. Net-of-cost Sharpe at the 10bp tier improves, with a bootstrap CI on the **delta** (not
     two separately-overlapping point estimates) that clears zero.
  2. Gross (pre-cost) spread has NOT meaningfully degraded — hysteresis could quietly hold a
     stale/wrong-signal leg past when it should exit, and cost savings alone could mask that in
     the net number.
  3. Turnover reduction is reported as an instrument/diagnostic, not a pass/fail criterion on
     its own — it explains *why* Sharpe moved, it isn't the goal itself.
  4. The shuffled-ranking null is re-run against the NEW construction specifically (not
     inherited from baseline) — the mechanism changed, so "not a construction artifact" must be
     reconfirmed, not assumed.
  A flat-or-worse result is an explicitly legitimate outcome (same posture as Phase 143.1's
  sign-symmetric HOLD verdict) — this gate can genuinely fail, and that's useful information,
  not a phase failure.

### Claude's Discretion
- Exact hysteresis band width / margin formula (e.g., derived from cost-floor ÷ marginal
  IC-per-rank-position, vs. a simpler fixed-rank-buffer) is left to research/planning — the
  *mechanism* (leg-level, cost-derived margin) is locked; the specific calibration is not.
- Whether the parity/comparison query lives as a new script (T3-script-style, matching Phase
  167's own `t3_cross_sectional_long_short_ctf_momentum_check.py` precedent) or as a permanent
  view/report over `construction_spreads` is a planning-level implementation choice.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design and validation (locked, do not re-derive)
- `docs/research/trade-construction-layer.md` — Minimal Design item 5 (the rebalance rule this
  phase builds), Validation Gates section (the pattern D-04's four-part gate extends), "What
  This Explicitly Defers" section (still applies: no Kelly sizing, no risk modeling, no borrow
  cost, no live execution)
- `docs/research/data-edge-source-thesis.md` — T3 section, for the underlying validated result
  this phase's baseline construction rests on

### The prior phase this one extends (do not re-litigate its decisions)
- `.planning/phases/167-cross-sectional-trade-construction-t3/167-CONTEXT.md` — D-01 through
  D-05 (raw-feature ranking, single-feature v1, exact-replica-first sequencing, 15m/equity-only
  scope, cost-hurdle-already-applied) all still hold; this phase does not reopen any of them
- `.planning/phases/167-cross-sectional-trade-construction-t3/167-VALIDATION.md` and
  `167-REVIEW.md` — Phase 167's actual passed-gate evidence (the baseline this phase's D-04
  gate compares against)
- `logs/construction_verdicts/gate1_20260727T112626Z.json` /
  `gate2_20260727T112642Z.json` — Phase 167's recorded live verdict artifacts

### The service this phase extends
- `services/cross_sectional_spread_tracker.py` — `_CONSTRUCTION_NAME` (line 111),
  `one_way_turnover()` (line 191, the function D-01's hysteresis logic extends),
  `net_spread_by_cost_bps()` (line 220, already computes the cost-tier sweep this phase's
  gating decision will finally act on instead of just measuring), `evaluate_spread_gate()`
  (line 394, the existing gate-evaluation pattern D-04 extends), `write_verdict_artifact()`
  (line 460, the existing verdict-recording pattern)

### Cost-hurdle convention
- Todo 030 (cost-hurdle APR calibration) — referenced extensively in Phase 167's context and
  PRIORITIES.md but its own todo file no longer exists under that number in `.planning/todos/`
  (likely absorbed/renumbered); its substance — the blended round-trip cost-floor convention —
  is now embodied live in `alpha.construction.cost_hurdle_bps_round_trip` (APR key, default
  `[1, 3, 5, 10]`) and needs no further archaeology
- `.planning/todos/pending/218-bil-thin-cell-per-symbol-ic-instability.md` — unrelated finding
  from the same session (per-symbol IC measurement artifact on `BIL`), noted here only because
  it surfaced while reviewing the same corpus; not a dependency of this phase

### Base class / architecture pattern
- `src/core/agent/base_batch.py` — `BaseBatch`; `cross_sectional_spread_tracker.py` already
  extends it, the new construction variant should too (parameterized, not a new subclass)

### Phase sequencing
- `.planning/ROADMAP.md` Phase 168 entry — inserted directly after Phase 167, ahead of
  Phase 156-159 (execution/sizing chain, still gated on proceeding past this construction track)
- `.planning/STATE.md` — current in-flight `ic_engine` corpus recompute is unrelated to this
  phase (T3/T5-style analysis reads `feature_vectors`/`forward_returns` directly, not
  `feature_ic_scores`/`market_regimes`); this phase is not blocked by that recompute

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `services/cross_sectional_spread_tracker.py`'s `one_way_turnover()`, `decile_legs()`,
  `spread_from_legs()`, `net_spread_by_cost_bps()` — all pure functions, directly reusable;
  the new leg-level hysteresis decision slots in between `decile_legs()` (today's unconditional
  re-rank) and the turnover computation
- `services/counterfactual_tracker.py`'s `frame_gate_passes`/`evaluate_frame_gate` — the
  day-clustered BCa/CLT bootstrap machinery, same one Phase 167 already reuses for its own
  gates; D-04's Sharpe-delta CI should use the same primitive for consistency
- `write_verdict_artifact()` — existing JSON verdict-recording pattern
  (`logs/construction_verdicts/`), should be reused for this phase's own gate verdict

### Established Patterns
- Every batch/measurement service since Phase 138 extends `BaseBatch` and keeps persistence in
  a dedicated writer path, never inline compute — this phase's variant construction must match
- Shadow-mode-first, parallel-not-replacing validation (Phase 142B, v2.1 dual-write/parity-audit
  precedent) — directly informs D-02

### Integration Points
- Reads `feature_vectors` (`ctf_momentum`) and `forward_returns` — same tables, no new upstream
  dependency
- Writes a second row-set to `construction_spreads` keyed by the new `construction_name` — no
  schema change expected (same table, new logical partition by name)

</code_context>

<specifics>
## Specific Ideas

User explicitly framed this phase's discussion as "design this like Renaissance would... a
council of senior engineers... what would Jim Simons demand" — the four decisions above (D-01
through D-04) were each argued from first principles (what does the literal cost-floor rule
mean; what does earned-complexity/shadow-mode-first actually require; is the liquidity taxonomy
real infrastructure or a hand-typed label; what would a rigorous validation bar look like) rather
than presented as an open menu — this rigor lens should carry into research/planning too.

</specifics>

<deferred>
## Deferred Ideas

- **Per-symbol empirical liquidity-tier cost floor** (raised explicitly by user, discussed and
  deferred this session) — instead of todo 030's hand-typed 3-bucket categorization (never
  built as real infrastructure), derive a per-symbol transaction-cost estimate empirically from
  data already in `market_data_ohlcv_tradeable` (e.g., a Corwin-Schultz high-low spread
  estimator or an Amihud illiquidity ratio — both computable from existing OHLCV bars, zero new
  data collection). Rationale for deferring: this is a second, independently-validatable
  question (does the estimator correlate with real costs? does using it beat the flat-tier
  version, or just add moving parts?) — bundling it into Phase 168 would conflate three
  variables in one pass (rebalance mechanism + parallel construction + per-symbol cost model).
  Explicitly gated on Phase 168 shipping and its D-04 gate resolving first (pass or HOLD) —
  should become its own future phase (needs its own Validation Gate: does the empirical
  estimator beat the flat 10bp tier), not a `pending/` todo, once that happens. Also worth
  connecting to `TagCalibrator`'s (Phase 146) measured-vs-definitional-tag precedent if/when
  built — a liquidity tier should be measured, not manually asserted, matching that project
  convention.
- **Hysteresis band calibration methodology** — left to research/planning (Claude's Discretion
  above), not locked here.

### Reviewed Todos (not folded)
The todo-matcher returned the same non-discriminating uniform scoring Phase 167's own context
noted (56 pending todos, nearly all scored 0.6/0.4 identically). Manually reviewed the full
list — none are specifically about the rebalance-rule/cost-gating construction change itself;
this phase's actual scope was, as PRIORITIES.md itself already noted, "not yet filed as a todo
(it's phase-scoped, not a pending/ item)". No todos folded.

</deferred>

---

*Phase: 168-cost-hurdle-adjusted-spread-construction-t3-follow-on*
*Context gathered: 2026-07-31*
