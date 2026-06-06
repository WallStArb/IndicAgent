---
reviewers: [gemini, codex]
reviewed_at: 2026-06-05T00:00:00Z
spec_reviewed: docs/plans/2026-06-05-stop-target-hardening.md
---

# Cross-AI Review — Stop/Target Hardening

---

## Gemini Review

### 1. Summary
The proposed changes represent a maturation of the `IndicAgent` trade lifecycle, shifting from a rigid, discrete-regime model to a more fluid, state-aware geometry. The transition to continuous GARCH scaling and institutional level inclusion is well-aligned with institutional trading practices. The state machine modifications for T1/T2 breakeven progression are logically sound and effectively address the "giving back profit" problem. The strategy is surgically targeted and avoids unnecessary architectural overhead, though it introduces non-trivial state dependency in the lifecycle tracker that requires careful verification.

### 2. Strengths
- **Adaptive Buffer Math:** Moving from discrete steps to continuous `garch_vol_ratio` scaling eliminates the cliff-effect and improves sensitivity to intraday volatility spikes.
- **Institutional Level Integration:** Adding Weekly Pivots, Asian H/L, and AVWAP bands provides the model with "market memory" that it previously ignored, likely improving the win-rate/hit-rate ratio at T1.
- **Logical Breakeven Progression:** The T1-hit-as-breakeven approach is a standard institutional risk-reduction technique that appropriately prioritizes capital preservation after the initial edge is validated.
- **Surgical Implementation:** The plan is exceptionally well-scoped, reusing existing infrastructure and avoiding database schema migrations.

### 3. Concerns
- **[HIGH] State Explosion/Staleness:** In `lifecycle_tracker.py`, the introduction of `t1_hit_bar` and `breakeven_stop` creates an implicit dependency on the signal's historical state. If a trade experiences a network disconnect or process restart, ensuring these states are correctly recovered from the `signal_ledger` (or recomputed) is critical to prevent "orphaned" breakeven stops.
- **[MEDIUM] Institutional Level Congestion:** Unifying target collection is excellent, but simply adding new target types might increase the number of "clusters" that trigger the RR filter prematurely. There is a risk that the ATR range filter becomes a bottleneck for signals that *should* be taken but are filtered because too many institutional candidates (e.g., AVWAP, Fibs) are clustered too close to the entry.
- **[MEDIUM] Hard Cap Vulnerability:** `ADAPTIVE_BUFFER_HARD_CAP = 1.40` is a sensible safety measure, but during "flash crash" or news-event scenarios, if this cap is hit, the resulting stop might still be too tight, leading to a "stop-run" exit just before a mean reversion.
- **[LOW] Numerical Stability:** In `_adaptive_buffer`, the `hurst` logic includes nested floating-point comparisons. Ensure that `hurst_exponent` is strictly validated as a `float` before these operations to prevent type errors.

### 4. Suggestions
- **State Recovery Test:** Create a unit test simulating a `lifecycle_tracker` recovery from a serialized state that contains a `t1_hit_bar`. Confirm the `breakeven_stop` correctly computes the entry price.
- **Target Selection Priority:** In the unified `_collect_target_candidates`, add a weight or hierarchy to the targets. Institutional levels (Weekly Pivots) should likely be prioritized over general Fibonacci clusters if the list needs to be pruned due to proximity constraints.
- **Logging Observability:** Add structlog events for the `breakeven_stop` transition. Specifically, log the `signal_id`, `t1_price`, and the new `breakeven_stop` value. It is vital to see exactly when the system shifts risk.
- **Shock Threshold Sensitivity:** Consider if the `3.0` threshold for `garch_shock` is too high. A value of `3.0` is extremely rare; test the sensitivity to `2.5` to ensure the logic actually engages when a significant shock occurs.

### 5. Risk Assessment
**Overall Risk: MEDIUM**

While the individual mathematical components (`_adaptive_buffer`) are low risk and easily unit-testable, the state machine change in `lifecycle_tracker.py` is stateful and introduces a new exit path. Any bug here directly impacts capital preservation and realized PnL. Rigorous testing of the transition sequence (T1 hit → breakeven → stop breach) is mandatory before deployment.

---

## Codex Review

### Summary
The spec is directionally strong: it targets real failure modes in volatility scaling, structural target coverage, and post-T1 risk management without adding new service boundaries. The main weakness is that Change 3 is under-specified for a deterministic bar-based lifecycle engine. Moving T1 from terminal exit to state advancement changes outcome semantics, restart behavior, intrabar ordering, and ledger comparability. Without explicit rules for same-bar target/stop collisions and persistent breakeven state, this can create silent wrong labels.

### Strengths
- Adaptive buffer removes the regime 1→2 cliff and uses `garch_vol_ratio`, which better matches continuous volatility behavior.
- Shock floor is a good guard against GARCH regime lag.
- Keeping `stop_loss` immutable and storing the trail as overlay state is the right data-integrity choice.
- Not unifying stop resolution is correct; the long/short stop logic has real directional asymmetry.
- Unifying target collection should reduce duplicated drift between long/short target logic.
- Adding institutional levels is sensible because they already exist upstream and fit the system's structural-target philosophy.
- Ordering breakeven stop before chandelier/staleness/TTL is conceptually right once the breakeven state is valid.

### Concerns
- **[HIGH] Breakeven state persistence is unspecified.** The spec says no schema changes and stores `breakeven_stop` in `chandelier_state`. If that state is only service memory, a restart loses whether T1/T2 was hit. That creates silent lifecycle corruption.
- **[HIGH] Same-bar ambiguity is not resolved.** On a bar where both T1 and the breakeven stop are inside the candle, the engine may assume T1 happened first — not deterministic from OHLC alone.
- **[HIGH] Target semantics change materially.** Today `target_1` is terminal. After this spec, T1 becomes a state marker, not an exit. Existing `SignalOutcome.TARGET_1` meaning, metrics, backtests, and ledger analytics become non-comparable unless explicitly versioned or renamed.
- **[HIGH] `_check_active_exit` needs more than a small reorder.** It currently exits on the highest target hit. If T1 is non-terminal, the function must know which targets are terminal under current trail state. Otherwise same-bar T1/T2/T3 handling can be wrong.
- **[MEDIUM] Adaptive buffer lacks finite/type guards.** `float(features.get(...))` can raise on bad strings, and `NaN`/`inf` can leak through unless explicitly checked. In this codebase, malformed feature values should fail loud or be deterministically clamped.
- **[MEDIUM] Hurst tightening has no lower bound.** Bad upstream values could shrink buffers aggressively. Clamp Hurst to `[0.0, 1.0]`.
- **[MEDIUM] Removing `effective_atr` globally may break metadata consistency.** `_classify_stop_basis()` and zone bounds currently use `effective_atr`. Each site calling `_adaptive_buffer()` independently — the spec must define what the "representative ATR" is for classification purposes.
- **[MEDIUM] Institutional targets may crowd out better targets.** `_pick_targets()` picks the first candidate meeting RR thresholds after distance sorting. Adding weekly pivots, fibs, Asian H/L, and AVWAP without priority/confluence rules can change T1 selection in noisy ways.
- **[MEDIUM] Candidate de-duplication is not specified.** Many levels can cluster at the same or near-same price. Without tick-aware dedupe, T1/T2/T3 can become effectively identical or misleadingly separate.
- **[LOW] "No additional gate" for weekly pivots and Asian H/L may admit stale or irrelevant levels.** This depends on upstream quality, but the framer should require correct side of entry, finite value, and session/timeframe provenance.

### Suggestions
- Persist breakeven trail state durably, or reconstruct it deterministically from ledger/bar replay on startup. If neither exists, this change should include a state-store change despite the "no schema changes" line.
- Add explicit OHLC collision policy. Conservative option: on the same bar, do not advance breakeven and exit via breakeven unless the bar opened beyond/after the target in a provable sequence.
- Split target logic into two concepts: `target_state_hits` and `terminal_exits`.
- Version lifecycle behavior in emitted metadata or ledger analytics — pre- and post-change `target_1` outcomes will mean different things.
- Harden `_adaptive_buffer()`: use a helper to parse finite floats, clamp `garch_vol_ratio` and `hurst_exponent`, decide whether malformed critical values fail loud or fall back with a metric. Add tests at `0.70`, `1.00`, `1.50`, shock `3.0/3.01`, Hurst boundaries, `None`, `NaN`, and invalid strings.
- Tick-aware dedupe target candidates before `_pick_targets()`, preserving strongest label/confluence metadata.
- Add tests for lifecycle cases: T1 only with no exit; T1 then breakeven stop; T1 then T2; T1/T2 same bar; T1 and original stop same bar; restart/replay with existing `t1_hit_bar`; long and short symmetry.

### Risk Assessment
**Overall risk: MEDIUM-HIGH.** Change 1 and Change 2 are moderate-risk if guarded with finite parsing, clamps, dedupe, and focused tests. Change 3 is high-risk because it changes the meaning of target hits and depends on durable state and deterministic intrabar ordering. The spec should address breakeven persistence, same-bar collision policy, and outcome semantics versioning before implementation.

---

## Consensus Summary

### Agreed Strengths
- Continuous `garch_vol_ratio` scaling is the right fix for the discrete cliff — both reviewers confirmed
- `stop_loss` immutability + overlay state in `chandelier_state` is the correct data-integrity choice
- Shock floor guard is sound and addresses GARCH regime lag
- Skipping stop-resolution unification is correct (genuine directional asymmetry)
- Adding institutional levels is clearly the right direction given they're already computed upstream

### Agreed Concerns (both reviewers flagged)
1. **Breakeven state persistence** — if `chandelier_state` is service-local memory only, a restart silently corrupts lifecycle. Either persist it or specify deterministic reconstruction from bar replay. This is the highest-risk gap in the spec.
2. **Institutional target crowding** — adding 4+ new candidate types without priority rules or tick-aware deduplication risks noisy T1 selection. `_pick_targets()` needs a deduplication pass and some ordering logic.
3. **Adaptive buffer type/NaN safety** — `float(features.get(...))` does not guard against bad strings or `NaN`/`inf`. Clamp `garch_vol_ratio` to finite range; clamp `hurst_exponent` to `[0.0, 1.0]`. Malformed values should fail loud per the project's "silent wrong answers are worse than loud crashes" principle.

### Divergent Views
- **Codex** flagged three additional HIGH-severity issues that Gemini did not: (1) same-bar OHLC ambiguity on T1/breakeven collision, (2) change in `target_1` terminal semantics affecting historical ledger comparability, (3) the need for `_check_active_exit` to know which targets are terminal under the current trail state. These deserve spec attention before implementation.
- **Gemini** raised the `garch_shock` threshold (`3.0`) as potentially too conservative — worth a sensitivity check at `2.5`.
- **Codex** is more concerned about outcome-versioning (pre/post T1-is-terminal) than Gemini; this depends on how much backtest/analytics comparability matters to the project.
