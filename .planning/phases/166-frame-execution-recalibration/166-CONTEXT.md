# Phase 166: Frame/Execution Recalibration - Context

**Gathered:** 2026-07-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Diagnose why Phase 148's Gate 2 (execution proof) failed while Gate 1 (signal proof) passed,
design and implement a recalibrated stop/target/hold frame that acts on that diagnosis, and
produce a fresh, independently-validated proposal ready for its own gate evaluation. This phase
does NOT re-run Gate 2 itself (D-04: that measurement is consumed/frozen) and does NOT touch
live capital or portfolio/execution infrastructure (Phases 149-159 stay gated behind this
phase's outcome, per STATE.md).

Read this phase entirely through a Renaissance-style rigor lens: every parameter change must be
earned empirically (measured against the IC decay curve or a real comparative evaluation), never
adopted because it is more sophisticated or "feels right." Prefer the simplest mechanism that
clears the bar; add structural complexity (v2.x's VP/SR stop hierarchy) only where it
demonstrably wins over the scalar baseline.

</domain>

<decisions>
## Implementation Decisions

### Scope: diagnose, implement, and re-validate
- **D-01:** Phase 166 is not diagnosis-only. It must: (a) compare current
  `stop_atr_mult`/`target_r_multiple`/`hold_max_bars` calibration against the empirical IC decay
  curve, (b) design and implement a recalibrated frame mechanism, (c) run that new proposal
  through a fresh validation gate (new `gate_id`, not a re-run of `gate2_execution`) before this
  phase is considered complete. A diagnosis with no testable alternative is a dead end, not a
  next action (this is exactly what todo 174 warned against).
- **D-02:** Confirmed baseline facts (verified in codebase during discussion, not assumptions):
  `alpha.frame.hold_max_bars.<regime>.<tf>` IS already empirically calibrated — EIC-02 in
  `services/ensemble_ic_engine.py`, `_calibrate_hold_max_bars()`, median hold-bars across
  qualifying symbols per (regime, tf) cell, gated to champion `weight_version` only (CR-02).
  `alpha.frame.stop_atr_mult` (1.5) and `alpha.frame.target_r_multiple` (2.0) are NOT — single
  global `[initial_estimate]` scalars from migration 205/214, never conditioned on regime/tf,
  never revisited since Phase 142B. This is the real gap to close.

### Recalibration approach: empirical comparison, not a priori choice
- **D-03:** Do not commit to either a pure ATR-scalar fix or a v2.x-style structural port up
  front. Build both candidates and let measured performance against the IC decay
  curve / new validation gate decide:
  1. **Scalar candidate** — extend the existing EIC-02 pattern (`_calibrate_hold_max_bars`) to
     also derive `alpha.frame.stop_atr_mult.<regime>.<tf>` and
     `alpha.frame.target_r_multiple.<regime>.<tf>`, same median-across-qualifying-symbols
     methodology, same champion-weight_version gate.
  2. **Structural candidate (broadened 2026-07-23)** — not VP/SR-only. Port v2.x's full
     archived structural stop-basis toolkit, using `src/intelligence/trading/zone_engine.py`'s
     confluence scoring as the unifying mechanism rather than reaching for `trade_framer.py`'s
     VP/SR-only `_classify_stop_basis`/`_select_vp` in isolation:
     - VP/SR: POC/VAH/VAL, session VP (1m/5m) vs rolling VP (15m/1h+)
     - Swing structure: `src/intelligence/features/i3_structure/swing_detector.py`,
       `trend_structure.py`
     - Fibonacci zones: `src/intelligence/features/i3_structure/fibonacci_zones.py`
     - SMC: order blocks, liquidity pools/sweeps, BOS/CHOCH, premium/discount —
       `src/intelligence/features/smc_context/` (`order_blocks.py`, `liquidity_pools.py`,
       `liquidity_sweeps.py`, `bos_choch.py`, `premium_discount.py`)
     - Anchored VWAP: `src/intelligence/context/anchored_vwap.py`
     Reuse `structure_snap_proximity_atr` as the proximity-gate concept, migrated as a proper
     APR key (not v2.x's bare `_cfg()` default) per this phase's Migrate-as-you-go rule. This is
     a scope broaden from the original VP/SR-only framing (research agent must determine
     whether this reaches into `src/intelligence/archive/` directly or has a real dependency on
     Phases 163 "VP/SR Structural Primitives" / 164 "SMC Institutional Footprint Primitives" —
     both currently unexecuted — and flag that dependency explicitly for planning).
  3. Score both against the same held-out criteria; keep the winner, discard the loser
     (or keep neither if both fail — that is a valid, informative outcome). No permanent
     complexity survives without a measured win.
- **D-04:** This directly answers the user's ask to "look at what good ideas/logic could be
  reused/resurfaced/reimagined from v2 trade lifecycle/tradeframer and applied to v3" — the
  answer is: evaluate it empirically as a competing candidate, not adopt it by inspection.

### Regime-window coverage: disclose, don't gate
- **D-05:** The `mid_bull`-only OOS coverage (2 of 8 direction/regime cells evaluable in Phase
  148) is treated as a **parallel finding**, not a blocking prerequisite. Phase 166 measures and
  transparently discloses the coverage limitation (same posture as Phase 148's SCORE-04
  documentation-only note) — any new proposal's validation result is scoped explicitly to what
  the available OOS window can say. Resolving true regime-window sufficiency likely requires a
  much larger corpus/OOS-window expansion (multiple full market regimes), which is out of scope
  here and should be filed as its own follow-on todo if this phase's evidence makes the gap
  concrete enough to act on.

### Structural candidate scope resolution (2026-07-23, post-research)
- **D-06:** RESEARCH.md's exhaustive live-schema check found the full broadened toolkit
  (D-03.2: VP/SR + swing/fib + SMC + anchored VWAP, unified via a ported `zone_engine.py`)
  requires feature columns that are 100% absent from v3's live `feature_vectors` — building it
  in full would require executing/planning Phases 163 (VP/SR, planned not executed), 164 (SMC,
  not even planned), and 165 (swing/fib, researched not planned), plus net-new anchored-VWAP
  scoping. That is multi-phase work Phase 166 cannot absorb under its own D-01 completion
  mandate. **Resolved scope:** the structural candidate ships in two parts —
  - **Part 1 (built in this phase):** port `zone_engine.py`'s 3-tier confluence-resolution
    architecture (declarative candidate-spec table → dedup → cluster → diverse-cluster
    preference → single-best → ATR fallback; `ZoneCandidate`/`_find_clusters`/`_score_cluster`/
    `_pick_single_best` are portable nearly unmodified) into a new v3-native module
    (`src/intelligence/trading/structural_confluence.py`), populated only with what Phase 163
    makes live (VP POC/VAH/VAL reconstructed-price fields, `sr_support_dist`/`sr_resist_dist`,
    `resistance_strength`/`support_strength`/`*_age_bars`). This is real multi-source confluence
    (VP + S/R independently), not a VP/SR-only downgrade — it's data-limited, not
    architecture-limited.
  - **Part 2 (deferred):** extend the same spec table with SMC/swing/fib/anchored-VWAP sources
    once Phases 164/165 (+ new anchored-VWAP scoping) land. File one consolidated follow-on todo
    at Phase 166's completion, and leave an explicit extension-point comment in
    `structural_confluence.py` pointing at that todo.
  - **Phase 163 execution is a real prerequisite for Part 1** — its columns exist in schema but
    are 100% NULL until it runs. Treat `/gsd-execute-phase 163` as Wave 0 of Phase 166's plan
    (Phase 163 is fully planned/reviewed/execution-ready per STATE.md — low-risk, independent).
  - Full reasoning: `166-RESEARCH.md`'s "Broadened Structural Candidate" section (Q1-Q4).

### Folded Todos
- **088 — hold_max_bars censoring not tracked** (`.planning/todos/pending/088-...md`): the
  existing EIC-02 calibration mechanism (which this phase's scalar candidate extends) can't
  distinguish a confirmed IC-decay boundary from right-censored (no-data) cells. Must be
  accounted for before trusting or extending that mechanism to stop/target — a censored cell
  silently returning the ceiling scale would corrupt both the scalar candidate's calibration and
  any comparison against the structural candidate.
- **096 — hold horizon vs feature lookahead mismatch** (`.planning/todos/pending/096-...md`):
  P0, the stride-bias fix shipped (migration 230), but the todo's own last update (2026-07-19)
  states the full 3-step corpus recalibration (`ic_engine` → `ensemble_trainer` reweight →
  `ensemble_ic_engine` decay walk) was never confirmed complete post-fix. Before this phase
  trusts current `hold_max_bars` values as a correct baseline to compare stop/target against
  (or as ground truth for the scalar candidate's methodology), verify — do not assume — that the
  champion weight_version's `hold_max_bars` keys were derived post-estimator-fix (check
  `ensemble_weights.updated_at` / `ensemble_ic_engine` log timestamps against the 143.1-08
  champion epoch, 2026-07-21).
- **172 — path-dependent frame statistics order-sensitivity sweep**
  (`.planning/todos/pending/172-...md`): the exact class of bug that broke Gate 2's `c4`
  reproducibility (order-sensitive cumulative-sum drawdown walk over tied `bar_ts` rows). Any
  new validation-gate script this phase writes to score the scalar/structural candidates must
  aggregate same-timestamp frames before any cumulative/path-dependent statistic — do not
  re-introduce the bug this todo tracks.
- **173 — ensemble_alpha 1h/1d OOS scoring gap** (`.planning/todos/pending/173-...md`): zero OOS
  rows at 1h for any weight_version, zero at 1d for the champion. This bounds which timeframes
  this phase's recalibration and new validation gate can actually be evaluated against —
  disclose the same 5m/15m-only coverage limitation Gate 1 already carries, don't claim broader
  coverage than the data supports.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Origin and prior verdict
- `.planning/todos/completed/174-gate2-execution-failure-frame-recalibration-investigation.md`
  — this phase's full origin, scope note, and promotion record
- `docs/plans/archive/2026-07-22-phase148-promotion-decision.md` — Gate 1 PASS / Gate 2 FAIL verdict,
  full SHADOW-REVIEW criteria table, c4 reproducibility investigation, regime-stratified
  companion table (§"Regime-stratified companion")
- `docs/plans/SHADOW-REVIEW.md` — the frozen five criteria Gate 2 evaluated against (a new gate
  for this phase's proposal should state explicitly whether it reuses these criteria or defines
  new ones — a planning decision, not locked here)
- `.planning/phases/148-alpha-scoring-system/148-CONTEXT.md` — D-01 through D-08,
  including the explicit deferral of this exact diagnosis to a future phase
- `.planning/ROADMAP.md` (~line 1378, Phase 148 section) — the pre-registered "frame problem,
  recalibrate against IC decay curve" playbook this phase executes

### Existing calibration mechanism to extend (scalar candidate)
- `services/ensemble_ic_engine.py` — `_calibrate_hold_max_bars()` (~line 1063),
  `_select_hold_bars_from_decay` — the exact pattern to mirror for `stop_atr_mult`/
  `target_r_multiple`: per-(regime,tf) median across qualifying symbols, champion-weight_version
  gated (CR-02), `is_pooled=true` rows excluded
- `production/migrations/205_alpha_frames_schema.sql`, `207_alpha_frames_target_r_multiple.sql`,
  `190_alpha_ensemble_ic.sql` — current APR seeding for `alpha.frame.stop_atr_mult`,
  `alpha.frame.target_r_multiple`, `alpha.frame.hold_max_bars.<regime>.<tf>`
- `services/alpha_frame_writer.py` — where `stop_atr_mult`/`target_r_multiple` are read
  (`_cfg()` calls, ~line 158) and snapshotted onto each frame at scan time
- `services/counterfactual_tracker.py` — where the frame's snapshotted stop/target/hold values
  are actually simulated bar-by-bar to produce `counterfactual_pnl_r`

### v2.x structural stop hierarchy (structural candidate, archived/no live consumer)
- `src/intelligence/trading/trade_framer.py` — `_classify_stop_basis()` (~line 298), `_select_vp()`
  (~line 339): ATR-fallback vs VP/SR structure-snap classification, session VP (1m/5m) vs
  rolling VP (15m/1h+) selection, `structure_snap_proximity_atr` threshold. Archived per
  `src/intelligence/CLAUDE.md` — no live consumer, but logic is intact and portable.
- `src/intelligence/trading/zone_engine.py` — confluence-based zone scoring; the unifying
  mechanism for the broadened structural candidate (D-03, 2026-07-23), scoring across all
  structural stop-basis sources rather than VP/SR in isolation
- `src/intelligence/features/i3_structure/swing_detector.py`, `trend_structure.py`,
  `fibonacci_zones.py` — swing structure and fib zone primitives
- `src/intelligence/features/smc_context/order_blocks.py`, `liquidity_pools.py`,
  `liquidity_sweeps.py`, `bos_choch.py`, `premium_discount.py` — SMC institutional footprint
  primitives
- `src/intelligence/context/anchored_vwap.py` — anchored VWAP
- Phase 163 "VP/SR Structural Primitives" (`.planning/phases/163-*`, PLANNED not executed) and
  Phase 164 "SMC Institutional Footprint Primitives" (registered, not planned) — check whether
  the broadened structural candidate has a real dependency on these landing first, or can reach
  into `src/intelligence/archive/`/`src/intelligence/features/`/`src/intelligence/trading/`
  directly without them

### Folded todos (full text)
- `.planning/todos/pending/088-hold-max-bars-censoring-not-tracked.md`
- `.planning/todos/pending/096-frame-hold-horizon-vs-feature-lookahead-mismatch.md`
- `.planning/todos/pending/172-path-dependent-frame-statistics-order-sensitivity-sweep.md`
- `.planning/todos/pending/173-ensemble-alpha-1h-1d-oos-scoring-gap.md`

### Project principles (Renaissance rigor lens)
- `docs/foundation/principles.md` — earn promotion through proof, empirical over theoretical,
  never drop data that could contain signal
- `docs/foundation/adaptive-parameter-registry.md` — every tunable value APR-backed;
  `structure_snap_proximity_atr` and any new stop-classification thresholds ported from v2.x
  must be migrated as APR keys, not hardcoded constants (Migrate-as-you-go rule)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_calibrate_hold_max_bars()` / `_select_hold_bars_from_decay` (`ensemble_ic_engine.py`) —
  direct template for the scalar candidate's stop/target calibration function
- `_classify_stop_basis()` / `_select_vp()` (`trade_framer.py`, archived) — direct template for
  the structural candidate; already handles session-VP-vs-rolling-VP timeframe selection and
  HTF fallback
- `ConfigService.set()` — the APR write path both candidates need (already used by EIC-02)

### Established Patterns
- APR snapshot-at-scan-time: frames record the APR value active when the frame was created
  (`alpha_frames.stop_atr_mult`, `max_hold_bars`), not a live join at simulation time — any new
  per-(regime,tf) stop/target keys must follow this same snapshot discipline, per the
  snapshot-vs-live-APR anti-pattern already learned in Phase 142B (see project memory
  `project_phase142b_code_review_fixes.md`)
- Champion-weight_version gating (CR-02): calibration writes only fire for the champion
  ensemble, never a challenger under evaluation — both new candidates must respect this
- ProcessPoolExecutor workers are compute-only, single serial writer connection in main —
  applies to any new corpus-scan script this phase writes (per CLAUDE.md Key Rules)

### Integration Points
- New APR keys (`alpha.frame.stop_atr_mult.<regime>.<tf>`,
  `alpha.frame.target_r_multiple.<regime>.<tf>`, plus any structural-candidate keys) feed into
  `alpha_frame_writer.py`'s existing `_cfg()` read path — should be additive/backward-compatible
  with the current global-scalar fallback, not a breaking schema change
- New validation gate writes to `gate_evaluations` alongside `gate1_signal`/`gate2_execution`,
  following the same audit-log pattern (timestamp, gate_id, result, evidence JSON)

</code_context>

<specifics>
## Specific Ideas

User specifically wants v2.x's trade lifecycle / trade_framer logic evaluated for reuse in v3,
not discarded just because v2.x is archived — "look at what good ideas/logic could be
reused/resurfaced/reimagined from V2 trade lifecycle/tradeframer and applied to our V3." This
is captured as the structural candidate in D-03, evaluated empirically rather than ported
wholesale.

User also explicitly invoked the Renaissance/Jim Simons framing (ruthless simplicity, clean
DAG data flow, guard against hidden bias, component reuse, SoC, async patterns) as the design
lens for this phase — reflected throughout the decisions above (empirical comparison over a
priori choice, reuse of the EIC-02 pattern before inventing a new one, APR discipline for any
ported v2.x constants).

</specifics>

<deferred>
## Deferred Ideas

- Resolving regime-window sufficiency for real (multi-regime OOS corpus expansion) — likely a
  much larger, separately-scoped phase if Phase 166's evidence makes the gap concrete enough to
  act on. Not this phase's scope (see D-05).
- New-gate naming and whether it reuses `SHADOW-REVIEW.md`'s frozen five criteria or defines new
  ones — left to planning, not locked by this discussion.

### Reviewed Todos (not folded)
None — the generic `todo.match-phase` scorer returned ~53 matches, nearly all scoring the
generic 0.6 keyword-match ceiling with no specific relevance (confirmed noise, same pattern
observed for Phase 148). The four todos folded above were identified directly from Phase 148's
own promotion-decision record and STATE.md's todo tracking, not from the scorer.

</deferred>

---

*Phase: 166-frame-execution-recalibration*
*Context gathered: 2026-07-23*
