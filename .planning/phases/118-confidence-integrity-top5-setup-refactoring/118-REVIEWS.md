---
phase: 118
reviewers: [gemini, codex, ollama]
reviewed_at: 2026-06-09T00:00:00Z
plans_reviewed:
  - 118-00-PLAN.md
  - 118-01-PLAN.md
  - 118-02-PLAN.md
  - 118-03-PLAN.md
  - 118-04-PLAN.md
  - 118-05-PLAN.md
---

# Cross-AI Plan Review — Phase 118

## Gemini Review

# Phase 118 Review: Confidence Integrity + Top 5 Refactoring

## 1. Summary
Phase 118 is a critical foundational effort to sanitize ML training data by removing extrinsic, regime-aware, and exhaustion-based confidence modifiers. The planning is exceptionally thorough, demonstrating a strong grasp of the "confidence-intrinsic-only" invariant. By splitting the work into a systemic "Wave 0" strip-down followed by surgical, high-volume refactors, the approach minimizes regression surface area. The primary risks center on mathematical consistency in the newly proposed normalization formulas and ensuring that critical always-log contracts are preserved during the transition to new composite scores.

## 2. Strengths
- **Systemic Approach:** Centralizing the removal of extrinsic modifiers in "Wave 0" ensures a consistent baseline before individual refactors begin.
- **Risk-Awareness:** The identification of the `divergence_stack.py` omission in Wave 0 and the explicit requirement to handle the always-log contract is excellent.
- **Verification Strategy:** The grep-based validation for extrinsic calls is a simple, effective, and mandatory gate.
- **Test-Driven Design:** Requiring unit tests for every refactor, including specific scenarios like formula scaling and monotonic confidence, is exactly what is needed for sensitive signal logic.
- **Data-Driven Decisions:** The requirement to query DB distributions before setting `_CVD_DIV_THRESHOLD` is a professional engineering standard that prevents blind hard-coding.

## 3. Concerns
- **Formula Correctness (HIGH):** As identified in the 118-04 plan, the `cvd_divergence` divisor `(threshold * 125.0 + 2.5)` is mathematically suspect. If implemented as written, it will lead to suppressed signals and failed validation.
- **Dependency Risks (MEDIUM):** While `ofi_ewma_5` availability is flagged, the reliance on other I1 features (e.g., `vol_ratio` in `gap_analysis_setup`) should be verified early to avoid runtime `NoneType` errors.
- **Regime Impact (MEDIUM):** The shift to `regime_type="trend"` in `PatternCompletion` is a significant logic change. While it aligns with quality goals, it may cause a sudden "signal drought" that observers need to account for during the shadow-run.
- **Variable Consistency (LOW):** The `vol_ratio` vs `volume_ratio` nomenclature mismatch in `GapAnalysisSetup` is a minor but common source of bugs.

## 4. Suggestions
- **Immediate Formula Patch:** Before executing 118-04, derive the correct divisor based on the desired p95 distribution rather than the current hard-coded artifact.
- **Feature Guardrails:** Add a standard `is None` check for all inputs used in the new 4-factor formulas. Implement "safe fallback" logic for each plugin that defaults to neutral confidence (e.g., 0.3) if I1 inputs are unavailable.
- **Logging During Shadow Run:** Ensure shadow-only mode logs both the old extrinsic-contaminated score and the new 4-factor intrinsic score for a comparison period.
- **Centralized Math Helpers:** For 4-factor composites, consider a small utility function `normalize_score(value, min, max)` in `src/intelligence/utils.py` to ensure consistent clamping and scaling.

## 5. Risk Assessment
**Overall Risk: MEDIUM**

The architectural goals are clear and the plans are robust. However, the complexity of the new mathematical formulas introduces a non-trivial risk of "silent failure" (where the confidence score is valid but improperly scaled). Risk is kept at MEDIUM because thorough unit testing and shadow-mode execution act as a reliable safety net.

---

## Codex Review

## Summary

Overall, the Phase 118 plans are coherent and aligned with the stated architectural invariant: confidence must represent signal-intrinsic quality only, while regime, confluence, exhaustion, zone, and SMC context must remain feature inputs for later empirical learning. The sequencing is mostly sound: Wave 0 strips broad extrinsic contamination first, then the five high-volume setup refactors rebuild confidence formulas and gates. The biggest risks are formula correctness, incomplete grep verification, inconsistent structured feature persistence, and implementation drift around "confidence path" versus "feature capture path."

## Strengths

- Clear architectural principle: intrinsic confidence is separated from extrinsic feature context.
- Good dependency ordering: Wave 0 as a serial prerequisite reduces repeated refactor conflicts.
- Strong focus on the highest-volume noisy setups, matching the expected training-data impact.
- Shadow-only requirement is consistently called out for the five refactored setups.
- Most confidence formulas are decomposed into interpretable intrinsic factors with weights summing to 1.0.
- Plans correctly preserve important local contracts, especially DivergenceStack's always-log behavior.
- PatternCompletion research note is precise: the bug is persistence/ML feature availability, not runtime availability.
- CVDDivergence plan correctly recognizes that threshold selection must be empirical rather than arbitrary.

## Concerns

- **HIGH:** Wave 0 grep verification is too narrow. Searching only for `hmm_regime_weight`, `apply_exhaustion_boost`, and `apply_exhaustion_guard` may miss extrinsic confidence contamination via `ctf_score`, `regime`, `zone`, `smc`, `exhaustion`, `confluence`, `liquidity`, or local helper names.

- **HIGH:** The plans do not explicitly require every final confidence to flow through `compose_confidence(raw_conf)`. This is a core invariant and should be verified directly.

- **HIGH:** CVDDivergence magnitude formula is internally inconsistent. `threshold * 125.0 + 2.5` would badly flatten confidence when threshold is `0.5`. This must be corrected before implementation.

- **HIGH:** Wave 0 modifies 15 plugins in one serial plan. The blast radius is large. Without plugin-specific tests or snapshot-style checks, regressions may slip through.

- **MEDIUM:** "Confidence path" is not rigorously defined. Some extrinsic values may still be used indirectly through precomputed scores, helper methods, supporting factor aggregation, or shared scoring functions.

- **MEDIUM:** Plans mention feature capture only indirectly. Tests should prove extrinsic factors are still captured in `capture_signal_features()` after removal from confidence.

- **MEDIUM:** OFIContinuation depends on `ofi_ewma_5` availability. The fallback weighting is sensible but the plan should mandate verification of feature name, null behavior, and sign conventions.

- **MEDIUM:** PatternCompletion's `regime_type: any -> trend` and `requires_i6_confluence=True` may introduce extrinsic gating even though confidence is intrinsic. This should be explicitly distinguished from confidence contamination.

- **MEDIUM:** GapAnalysis timing score can penalize valid later-session gap behavior depending on instrument/session semantics. This is intrinsic only if timing is considered part of setup geometry.

- **MEDIUM:** DivergenceStack persistence score using "max per-input age" may reward stale divergence components. A fresher-is-better score may better reflect intrinsic quality.

- **LOW:** Several formulas use hard ceilings without stating clamp behavior per factor. Individual factors should be clamped to `[0, 1]` before weighting.

- **LOW:** The plans do not mention migration or downstream schema expectations for newly persisted structured PatternCompletion fields.

- **LOW:** CVDDivergence DB percentile queries should be bounded by date range and instrument set to avoid expensive full scans.

## Suggestions

- Add a required final static verification checklist:
  - No extrinsic terms in confidence formulas: `hmm`, `regime`, `ctf`, `i6`, `exhaustion`, `zone`, `smc`, `confluence`, `liquidity_context`.
  - All confidence outputs call `compose_confidence(raw_conf)`.
  - Extrinsic fields still appear only in `capture_signal_features()` or equivalent feature payloads.

- Expand grep to semantic terms:
  ```bash
  rg -n "hmm|regime|ctf|i6|exhaustion|zone|smc|confluence|liquidity|apply_exhaustion|hmm_regime_weight" src/intelligence/trading/
  rg -n "compose_confidence" src/intelligence/trading/
  ```

- Require factor-level clamps in every composite formula before weighting.

- For CVDDivergence, replace the magnitude normalization with an explicit empirical range:
  ```python
  div_mag_score = clamp01((abs(cvd_div) - threshold) / (upper_ref - threshold))
  ```
  where `upper_ref` is selected from p90/p95 of live data distribution.

- For CVDDivergence DB query, define lookback window, instruments included, minimum sample count, and fallback if data is sparse.

- For DivergenceStack, reconsider persistence scoring — prefer freshness-based score over max-age reward.

- Add negative tests for every refactored plugin proving extrinsic inputs do not change confidence while intrinsic inputs remain constant.

- Add a small "contract test" over all I7 plugins verifying: `shadow_only=True` where required, confidence in `[0.0, 0.95]`, extrinsic-only perturbations leave confidence unchanged.

## Final Risk Assessment

Overall Phase 118 risk is **MEDIUM-HIGH**. The direction is architecturally correct but the phase touches many high-volume signal paths and training-data semantics. Largest risks: incomplete detection of extrinsic confidence contamination, CVDDivergence formula defect, insufficient contract tests around structured feature persistence and always-log behavior.

---

## Ollama Review (qwen3.5:4b)

# Phase 118 Execution Plan Review

## Wave 0 (118-00)

**Summary:** Wave 0 is the foundational clean-up pass for 15+ I7 plugins to strip extrinsic modifiers. Clear dependency management with Wave 1 depending on Wave 0. Includes verification via grep.

**Strengths**
- Clear "Wave 1 depends on Wave 0" structure ensures clean codebase state.
- Explicit `shadow_only=True` flagging helps track which modifiers remain.
- Includes final verification grep.

**Concerns**
- `divergence_stack.py` exclusion from Wave 0 creates a potential inconsistency — if the stack logic is complex or feeds into other I7 plugins, this could introduce "double-extrinsic" application if not carefully managed in Wave 5. (MEDIUM)
- Grep command scope must search ALL `*.py` files in the I7 trading directory. (LOW)

**Risk Assessment: MEDIUM**

## OFIContinuation (118-01)

**Strengths:** Focuses on `abs(ofi_ewma_20)` magnitude. Explicit `_CVD_DIV_THRESHOLD` constant. `shadow_only=True` for validation.

**Concerns**
- Relies on `ofi_ewma_5` from I1 — new dependency chain that must be tested. (MEDIUM)
- Formula needs verification if threshold changes dynamically. (LOW)

**Risk Assessment: LOW**

## PatternCompletion (118-02)

**Strengths:** Addresses a critical JSONB persistence issue. Minimal scope. Regime filter correctly adjusted.

**Concerns**
- `shadow_only=True` might prevent testing actual behavior if not configured for real-time validation. (MEDIUM)
- ML impact if PatternCompletion is used for training data cleaning — JSONB fix must not corrupt dataset structure. (MEDIUM)

**Risk Assessment: LOW**

## GapAnalysisSetup (118-03)

**Strengths:** Explicit threshold. Consistent variable naming (`vol_ratio` verified).

**Concerns**
- Mathematical inconsistency in divisor formula: `threshold * 125.0 + 2.5` produces wrong range. (HIGH)
- Data leakage risk if extrinsic stripping is not calibrated correctly. (MEDIUM)

**Risk Assessment: HIGH** (due to divisor formula issue shared across plans)

## CVDDivergence (118-04)

**Strengths:** Empirical threshold derivation via DB query. Gradient confidence approach. `shadow_only=True`.

**Concerns**
- Divisor formula is wrong or contradictory — directly impacts signal accuracy. (HIGH)
- `bars_since_session_start` None handling needed. (MEDIUM)

**Risk Assessment: HIGH**

## DivergenceStack (118-05)

**Strengths:** Implements always-log pattern. Composite signal combination. `shadow_only=True`.

**Concerns**
- Mathematical consistency with corrected divisor in 118-03/04 must be maintained. (MEDIUM)
- Variable naming standardization (`vol_ratio` vs `volume_ratio`) needed across plans. (LOW)
- Specific tests for always-log behavior needed. (MEDIUM)

**Risk Assessment: MEDIUM**

---

## Consensus Summary

All three reviewers independently analyzed the same 6 plans. The following consensus emerged.

### Agreed Strengths

1. **Wave 0 as serial prerequisite** — universally recognized as the right structural decision to prevent shared-file conflicts between the extrinsic strip and the intrinsic formula upgrades.
2. **Empirical CVD threshold via DB query** — all reviewers noted this as a professional standard that prevents blind threshold jumps (from 0.002 to 0.5 is a 250x change).
3. **shadow_only=True consistency** — all plans call this out; all reviewers recognized it as the appropriate production safety gate.
4. **Test coverage requirements** — every plan requires unit tests with specific behavioral scenarios (gate rejection, formula scaling, monotonic confidence).
5. **DivergenceStack always-log preservation** — the special always-log contract is correctly identified and respected across plans.
6. **PatternCompletion data-flow bug characterization** — research correctly identifies the issue as structured JSONB field persistence for ML, not runtime data availability.

### Agreed Concerns

1. **CVDDivergence magnitude normalization formula is broken (HIGH — all 3 reviewers)**
   - The divisor `threshold * 125.0 + 2.5` produces approximately 65.0 when threshold=0.5, which compresses virtually all divergence values to near-zero confidence. The note in the plan says "range is 0.0 at 0.5 → 1.0 at 3.0" but that requires a divisor of 2.5, not 65.0.
   - **Fix before executing 118-04 Task 2:** Use `upper_ref = p90_value` from the DB distribution query, and compute `div_mag_score = clamp01((abs(cvd_div) - threshold) / (upper_ref - threshold))`.

2. **Wave 0 grep verification scope is too narrow (HIGH — Gemini + Codex)**
   - Searching only for `hmm_regime_weight`, `apply_exhaustion_boost`, `apply_exhaustion_guard` misses CTF, zone, SMC, and any locally renamed extrinsic helpers.
   - **Add broader semantic grep:** `rg -n "ctf_score\|in_supply_zone\|in_demand_zone\|fvg_type\|ob_type\|choch_detected\|bos_detected\|price_in_premium" src/intelligence/trading/` with manual review of hits to distinguish confidence path from capture path.

3. **divergence_stack.py exclusion from Wave 0 needs tight control (MEDIUM — all 3 reviewers)**
   - All reviewers noted this creates a gap where Wave 0's "clean" state is partial. The plan does handle it (Wave 5 includes the strip), but the final Phase 118 grep must explicitly include divergence_stack.py.

4. **Feature variable name verification required before implementation (MEDIUM — Gemini + Codex)**
   - `vol_ratio` vs `volume_ratio` in GapAnalysis, `ofi_ewma_5` availability in OFIContinuation, `cvd_slope_5bar` convention in CVDDivergence. These must be read from the actual files before writing formula code.

5. **Factor-level clamping before weighting (LOW-MEDIUM — Codex)**
   - Every factor in every formula should use `min(1.0, max(0.0, ...))` before the weighted sum. Several formulas in the plans assume the result is naturally bounded but do not explicitly state the clamp.

### Divergent Views

- **Gemini** suggests a centralized `normalize_score(value, min, max)` utility in `confidence_utils.py`. **Codex** says inline clamping is consistent with existing plugin patterns. Given CLAUDE.md's principle of "ruthless complexity elimination" and the existing `compose_confidence()` pattern, inline clamping is the right call — no new utility needed.

- **Gemini** flags PatternCompletion regime drought as a concern to "account for during shadow run." **Codex** correctly notes this is a deliberate quality-over-quantity decision and should be documented rather than hedged. The shadow-only flag ensures no production impact.

- **Ollama** correctly identifies the CVD divisor issue and the always-log contract, but confuses some plugin tier nomenclature (refers to GapAnalysis as "I9", OFIContinuation as "I12"). The structural observations are still valid despite the labeling errors.
