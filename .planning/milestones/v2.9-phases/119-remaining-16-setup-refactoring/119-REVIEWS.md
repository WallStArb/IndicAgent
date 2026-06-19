---
phase: 119
reviewers: [gemini, codex, ollama]
reviewed_at: 2026-06-10T00:00:00Z
plans_reviewed: [119-01-PLAN.md, 119-02-PLAN.md, 119-03-PLAN.md, 119-04-PLAN.md]
---

# Cross-AI Plan Review — Phase 119

> Reviewed by: Gemini, Codex (OpenAI), Ollama (nemotron-3-nano:4b)
> Claude skipped — running inside Claude Code (independence rule)

---

## Gemini Review

## Review of Phase 119: Remaining 16 Setup Refactoring

### 1. Summary
The plan is highly structured, methodical, and adheres strictly to the defined "6 GOOD patterns" and locked architectural decisions. By breaking the refactoring into distinct waves and separating the infrastructure enforcement (validate_tier) and documentation, the risk of configuration drift is minimized. The plan demonstrates a deep understanding of the existing codebase, particularly regarding the regime-specific gating logic (e.g., using `hmm_trending_weight` for "any" plugins) and the critical need to reorder expensive `extract_ohlcv()` calls behind gates.

### 2. Strengths
- **Architectural Rigor:** Explicitly handles the `requires_i6_confluence` enforcement and re-ordering of `extract_ohlcv()` calls, which is the most common point of failure for latency and data integrity in this pipeline.
- **Regime Awareness:** Clearly differentiates between `hmm_trending_weight` (for "any") and `hmm_regime_weight` (for specific regimes), ensuring the dual gate logic is semantically correct across the diverse set of I7 plugins.
- **Test-Driven Enforcement:** The plan to replace permissive legacy tests with strict `test_requires_i6_confluence_true` and the exclusion of `ctf_score` from perturbation in the extrinsic contract test ensures that the new constraints are enforced rather than just suggested.
- **Shared Infrastructure:** The explicit handling of the `microstructure_utils.py` shared helper ensures consistency across `OFISpike` and `CVDSpike`.

### 3. Concerns
- **(HIGH)** **Complexity of Spike Helper:** Refactoring `detect_spike_signal()` in `microstructure_utils.py` is high-risk. If other plugins depend on this helper, the change could propagate regressions. Ensure the refactor maintains strict backward compatibility for the signature.
- **(MEDIUM)** **DeltaExhaustion Exclusion:** The plan mentions exempting `DeltaExhaustion` from "exhaustion boost/guard" while applying 4-factor confidence. This requires careful verification that the 4-factor composite doesn't implicitly re-introduce the behavior the exemption intends to prevent.
- **(LOW)** **Test coverage for D-04:** MomentumBreakout's 3-factor formula must be explicitly captured in the unit tests to prevent an automated "cleanup" or refactor from inadvertently "correcting" it to 4 factors.

### 4. Suggestions
- **Incremental Refactoring:** For `microstructure_utils.py`, perform the helper refactor as a discrete step with a dedicated unit test *before* applying the plugin-level changes to ensure the helper behavior remains deterministic.
- **Dependency Audit:** Before starting Wave 1, run a quick `grep` or usage scan to confirm that `detect_spike_signal()` is not used by plugins outside the 17 being refactored.
- **Gate Logging:** Given the phase goal of "eliminating ~1M noise signals," ensure that the `no_signal()` returns in the dual gates are logged at a sufficient level to allow post-hoc verification that the gates are firing as expected in shadow mode.

### 5. Risk Assessment
**Overall Risk: MEDIUM**

The plan is sound and well-justified. The primary risk is the sheer volume of changes (17 plugins) and the potential for subtle regressions in the confidence formula logic. The extensive testing strategy and the separation of infrastructure changes (validate_tier) from plugin logic updates are excellent mitigations. High rigor during the `microstructure_utils.py` refactor will be the critical path to success.

---

## Codex Review

## Summary

The plans are directionally strong and mostly aligned with Phase 119's intent: enforce I6 confluence, move cheap gates before expensive OHLCV work, replace weak confidence formulas, and keep everything in shadow mode. The biggest risks are scope mismatch and test-contract drift. `TIER_I7` currently has more than the 22 "compliant setups" referenced in the docs plan, while Plan 119-03 proposes enforcing `requires_i6_confluence=True` across all `TIER_I7`. Unless the omitted I7 plugins are also remediated or explicitly exempted, validation/tests will fail. There is also a material inconsistency around VWAPDeviation being described as already 4-factor compliant in the phase context but as "keep existing 3-factor" in Plan 119-02.

## Plan 119-01 Review

### Strengths

- Correctly identifies `detect_spike_signal()` as the shared choke point for OFISpike and CVDSpike.
- Places spike dual gates after the cheap z-score threshold and before ATR/OHLCV access, which matches the early gate goal.
- Correctly calls out `regime_type="any"` requiring `hmm_trending_weight()`.
- Preserves the DeltaExhaustion exemption behavior and avoids reintroducing exhaustion boosts/guards.
- Separates ClassVar-only plugin changes from shared helper logic for OFISpike/CVDSpike.

### Concerns

- **(HIGH)** Existing spike tests still assert that CTF/HMM affect confidence additively. The plan mentions implementation and verification but not required test rewrites for tests that wire HMM/CTF into confidence.
- **(MEDIUM)** The spike helper's proposed `volume_score` may tempt reading `df["volume"]` before the gate. It must derive from already-merged features, or run only after the gate.
- **(MEDIUM)** "I6 confluence" should consume `frames["i6"]` explicitly enough that missing `i6` cannot silently pass with neutral zeros unless that is intended fail-closed behavior.
- **(LOW)** FailedBreakout's up/down HMM gate needs a clear implementation shape so it does not accidentally use `max(up, down)` where direction-specific gating is intended.

### Suggestions

- Add explicit test updates for spike behavior: HMM is gate-only, CTF below threshold blocks, and CTF perturbation either changes confidence only where expected or is excluded from the right contract test.
- Define helper constants once: `_MIN_REGIME_WEIGHT = 0.30`, `_MIN_CTF_SCORE = 0.25`, `_SPIKE_THRESHOLD = 2.0`.
- Add one helper-level regression proving ATR/OHLCV helpers are not touched when regime or CTF gate fails.

### Risk Assessment

**MEDIUM.** The helper-centered approach is sound, but shared-helper changes can break both spike plugins and existing tests unless the behavioral contract is updated deliberately.

## Plan 119-02 Review

### Strengths

- Correctly separates gates-only plugins from confidence-rewrite plugins.
- Correctly preserves MomentumBreakout's 3-factor formula per D-04.
- Calls out binary HMM checks that need replacement with continuous probability gates.
- Identifies OHLCV reorder work for VWAPDeviation and MomentumBreakout.

### Concerns

- **(HIGH)** **VWAPDeviation contradiction.** Phase context says it already has a compliant 4-factor formula, but Plan 119-02 says "keep existing 3-factor confidence." If it is actually 3-factor, this violates the success criteria; if it is 4-factor, the plan text is wrong. Must be resolved before implementation.
- **(HIGH)** Plan 119-02 does not explicitly enumerate `shadow_only=True` and `requires_i6_confluence=True` ClassVar updates for all 9 plugins in the must_haves text (they are implicitly required but not surfaced per-plugin).
- **(MEDIUM)** DualDivergence regime type is left undecided. This must be resolved before implementation because it determines whether to use `hmm_regime_weight(..., "ranging")` or `hmm_trending_weight()`.
- **(MEDIUM)** VCP's proposed `momentum_context` using HMM probability as an intrinsic confidence factor risks violating D-01 if it is additive rather than strictly a gate.
- **(LOW)** ORB gap alignment should be clearly bounded with `clamp01` and not double-count CTF or regime context.

### Suggestions

- Fix VWAPDeviation plan text before coding (4-factor vs 3-factor contradiction).
- Add an explicit per-plugin checklist: regime_type, shadow_only, requires_i6_confluence, gate function, OHLCV-before-gate status, confidence factor count.
- For VCP, use HMM only as the pre-entry gate. If "momentum_context" remains, source it from non-HMM intrinsic trend/price/volume features.
- Resolve DualDivergence regime type in the plan, not during implementation.

### Risk Assessment

**MEDIUM-HIGH.** Most work is straightforward, but the VWAPDeviation contradiction and VCP HMM-confidence risk could directly violate locked decisions.

## Plan 119-03 Review

### Strengths

- The `validate_tier()` enforcement matches locked D-02: missing or false `requires_i6_confluence` should fail startup.
- Replacing the TODO-rationale test with a strict true-value test is directionally correct for hard enforcement.
- Excluding only `ctf_score` from perturbation for Phase 119 plugins is a narrow and defensible contract adjustment.
- Keeps the confidence range assertion intact.

### Concerns

- **(HIGH)** **TIER_I7 scope.** `TIER_I7` currently has more than 22 plugins. Strict `requires_i6_confluence=True` enforcement over all `TIER_I7` will fail on startup unless every I7 plugin not touched by Phase 118/119 also has `requires_i6_confluence=True`. This must be resolved before Plan 03 is executed.
- **(HIGH)** The docs plan claims "22 compliant I7 setups" but Plan 119-03 enforces all `TIER_I7`. This scope contradiction must be surfaced.
- **(MEDIUM)** Excluding `ctf_score` from perturbation only for the 17 Phase 119 plugins is correct only if every Phase 119 confidence formula may receive CTF input. Plugins with CTF as gate-only should still be tested for confidence invariance where possible.
- **(MEDIUM)** Full-suite green may require updating existing per-plugin tests that assert old confidence formulas or old skip behavior.

### Suggestions

- Decide explicitly: either Phase 119 includes every non-compliant `TIER_I7` plugin, or enforcement must have a documented temporary exemption mechanism. Given D-02 is locked, the cleaner answer is to expand implementation scope or split enforcement until all `TIER_I7` complies.
- Add a test that `validate_tier()` raises on `requires_i6_confluence=False`, not just missing.
- Build `_PHASE_119_PLUGINS` from exact plugin names and assert it has length 17 to prevent silent drift.
- Keep perturbation exclusions surgical: remove only `ctf_score`, not `ctf_structure_alignment` or `ctf_trend_alignment`.

### Risk Assessment

**HIGH.** This is the enforcement gate. If scope is not reconciled with the actual `TIER_I7` registry, CI/startup validation will break even if the 17 target plugins are correctly refactored.

## Plan 119-04 Review

### Strengths

- Good timing: documenting the pattern after enforcement prevents more one-off setup implementations.
- Includes the important `hmm_trending_weight()` rule for `regime_type="any"`.
- Links enforcement to `validate_tier()` and shadow registry behavior.
- The no-em-dash constraint is called out explicitly.

### Concerns

- **(HIGH)** "Table of all 22 compliant I7 setups" conflicts with actual `TIER_I7` breadth and Plan 119-03's all-I7 enforcement.
- **(MEDIUM)** "Canonical reference: ofi_continuation.py line ranges" is fragile. Line numbers will drift quickly after refactors.
- **(MEDIUM)** The phase goal mentions zone friction penalties, but the implementation plans barely address them. Documentation should clarify whether zone friction is still part of the 6 GOOD patterns or a separate captured/gated context.
- **(LOW)** "Verified current status" should be generated from actual plugin registry/test output where possible, not manually maintained.

### Suggestions

- Replace fixed line ranges with symbol references, e.g. `OFIContinuationPlugin.compute_full`.
- Document the exact distinction between pre-entry gates, confidence factors, captured extrinsic fields, and zone friction penalties.
- Make the compliant table match the actual enforcement set, or label it "Phase 118/119 setup subset" instead of "all I7."
- Include a short anti-pattern section: `hmm_regime_weight(features, "any")`, binary HMM regime checks, OHLCV before gate, additive HMM confidence.

### Risk Assessment

**MEDIUM.** Documentation itself is low execution risk, but inaccurate scope language will mislead future work and mask enforcement failures.

## Overall Recommendations (Codex)

- Reconcile the `TIER_I7` scope before implementation. This is the main blocker.
- Fix VWAPDeviation's factor-count contradiction before implementation.
- Add explicit test-update tasks for spike helper tests and any plugin tests that encode old confidence formulas.
- Treat HMM strictly as a pre-entry gate everywhere; avoid using HMM probability as a confidence factor, including VCP.
- Add one mechanical audit after Waves 1 and 2: no target plugin should access `extract_ohlcv()`, `df["close"]`, `df["volume"]`, ATR, or frame trade construction before regime and CTF gates pass.

---

## Ollama Review (nemotron-3-nano:4b)

## Cross-AI Plan Review – Phase 119 Refactor

### 1. Summary
Plans 119-01 and 119-02 aim to apply the 6 GOOD confidence + dual-gate + re-order patterns to the remaining 17 I7 setups, while Plan 119-03 enforces the new `requires_i6_confluence` flag via a new `validate_tier()` check, and Plan 119-04 produces the required architecture documentation. Overall the effort is well-structured, leverages the Phase 118 precedent, and targets the critical risk: generating clean "no-signal" events via gates rather than noisy false signals.

### 2. Strengths
- **Comprehensive ownership** – each plan lists exact files, tasks and deliverables.
- **Correct implementation of D-01/D-04** – `hmm_trending_weight` used only as a gate; additive hmm/CTF terms removed.
- **Early-gate optimisation** – for 4+ plugins OHLCV extraction is pushed after the dual-gate layer, protecting expensive data pulls.
- **Confidence formulas are composite** – weights sum to 1.0 and map clearly to semantic factors (z-score, volume, ctf, persistence).
- **CI & contract testing baked in** – ctf_score perturbation exclusions limit regression risk.
- **Documentation plan** – new `i7-setup-confidence-patterns.md` records the pattern template and gate thresholds.
- **Low scope creep** – no introduction of new risk factors in the current scope.

### 3. Concerns

| # | Item | Severity | Rationale |
|---|------|----------|-----------|
| 1 | **Latent gate ordering bug** – In plugins where re-order changes the index of `close`, an exception could be raised after the double-gate. | HIGH | Refactor of `detect_spike_signal` / re-ordered `close` may expose a mismatch between gate logic and data access. |
| 2 | **CTF-score perturbation safety** – The test set removes `ctf_score` from the perturbed dict for the 17 Phase-119 plugins, but if any gate still references a zero-value CTF metric, the confidence range could be incorrectly shrunk. | MEDIUM | The assertion `[0.0, 0.95]` still passes; ensure no unintended narrowing. |
| 3 | **Shadow-registry truth** – No test exists to verify that `validate_tier()` indeed marks plugins with `shadow_only=True` as non-compliant, risking silent drift. | LOW | Minor; can be added as a quick regression. |
| 4 | **Missing test for composite confidence** – Composite factors (e.g., `leg_quality`, `breakout_margin`) are new; no unit test asserts all weight components are >= 0 and <= 1. | MEDIUM | Could trigger false-positive `extrinsic_contract` failures in CI. |
| 5 | **Documentation table count** – Claims "22 compliant I7 setups (5 + 17)". Verify that no other I7 plugins were missed. | LOW | Trivial fix. |

### 4. Suggestions
- **Add a unit test** that asserts the dual-gate never raises due to an `IndexError` from `close` index.
- **Extend `test_i7_extrinsic_contract.py`** to verify that after gate removal, the confidence range never drops below 0.2.
- **Insert documentation reminder** that a `shadow_registry` test can be added to the CI pipeline.
- **Create sanity checks** in composite confidence functions to guarantee each weight factor is in [0,1]; assert this for all new plugins.
- **Round table count** – update `i7-setup-confidence-patterns.md` to "22" and embed a script snippet that lists all *.py files matching the I7 naming pattern to double-check completeness.

### 5. Risk Assessment
**Overall Risk: MEDIUM**

The biggest risk stems from the dual-gate change combined with re-ordered OHLCV access. If a gate fires to "no-signal" before OHLCV, we must guarantee that the missing signal does not trigger downstream alerts. Correcting the suggested checks will drive this from MEDIUM to LOW for the upcoming CI run.

---

## Consensus Summary

### Agreed Strengths
- **Wave structure is sound**: separating 8 easy setups (Wave 1) from 9 harder ones (Wave 2) plus enforcement (Plan 03) and docs (Plan 04) is well-organized.
- **Regime-type awareness is correct**: all three reviewers praised the `hmm_trending_weight` / `hmm_regime_weight` distinction for `regime_type="any"` vs specific regime plugins.
- **detect_spike_signal shared helper approach is correct**: OFISpike/CVDSpike delegate to the helper; refactoring the helper once is the right pattern.
- **Test enforcement strategy is sound**: replacing permissive TODO-rationale tests with strict true-value asserts, and the surgical ctf_score exclusion from perturbation for exactly the 17 Phase-119 plugins.
- **DeltaExhaustion exempt_exhaustion invariant is well-guarded**: all reviewers noted the plan's explicit preservation constraint.

### Agreed Concerns
1. **(HIGH — Codex/Ollama) TIER_I7 scope vs. validate_tier() enforcement**: The current `TIER_I7` list contains more than 22 plugins. Plan 119-03 enforces `requires_i6_confluence=True` across ALL `TIER_I7`. If any I7 plugin outside the Phase 118/119 22-plugin set lacks `requires_i6_confluence=True`, startup validation will break. **This must be audited before Plan 03 executes.** Resolution: either all TIER_I7 plugins already have it (verify with grep), or add a temporary exemption mechanism for the non-refactored subset.

2. **(HIGH — Codex) VWAPDeviation factor count contradiction**: Phase context says "ALREADY COMPLIANT in structure" (4-factor), but Plan 119-02 says "keep existing 3-factor confidence." This is a direct contradiction. Must be resolved by reading the file before planning the task.

3. **(HIGH — Gemini/Codex) detect_spike_signal() consumer audit needed**: Both reviewers flagged the risk of other consumers using the shared helper. A quick `grep -rn "detect_spike_signal" src/` scan should confirm only OFISpike + CVDSpike use it.

4. **(MEDIUM — Codex) VCP HMM-as-confidence-factor risk**: The plan proposes `momentum_context_score` sourced from `hmm_probability`. This risks violating D-01 (HMM is gate-only, never a confidence additive). The factor should be sourced from non-HMM price/volume/trend features instead.

5. **(MEDIUM — Codex) DualDivergence regime type unresolved**: The plan leaves the regime_type to be "verified" at implementation time. This must be determined before implementation since it controls which gate function to use.

### Divergent Views
- **TIER_I7 scope**: Codex raised it as a HIGH blocker; Gemini and Ollama did not surface it. It should be treated as HIGH — a `grep -rn "requires_i6_confluence" src/intelligence/trading/` across the full trading directory would resolve this immediately.
- **Gate ordering crash risk**: Ollama raised a potential `IndexError` from re-ordered `close` access as HIGH; Codex treated it as MEDIUM. The concern is legitimate — verifying each plugin's `close` access is after the gate (not just extract_ohlcv) is the right acceptance criterion.
- **Confidence range lower bound**: Ollama suggested asserting confidence never drops below 0.2; Gemini/Codex did not. This is a reasonable guard for `compose_confidence()` output but not a blocking concern.

---

## Action Items Before Execution

1. **Run now (2 minutes):** `grep -rn "requires_i6_confluence" src/intelligence/trading/ | grep "= False"` — if any plugin outside the 17 Phase-119 targets still has `False`, Plan 03 enforcement will need adjustment.
2. **Run now:** `grep -n "detect_spike_signal" src/intelligence/trading/*.py` — confirm only ofi_spike.py and cvd_spike.py call the helper.
3. **Read the file:** Open `vwap_deviation.py` and count confidence factors — 3 or 4? Fix the Plan 02 description accordingly.
4. **Resolve before Plan 02 execution:** DualDivergence regime_type — read the class and determine "mean_reversion" or "any".
5. **Resolve before Plan 02 execution:** VCP `momentum_context_score` — use a non-HMM feature source (e.g., `features.get("price_momentum_score")` or a derived price/volume factor) to avoid D-01 violation.

