---
reviewers: [gemini, codex]
reviewed_at: 2026-06-05T00:00:00Z
plan_reviewed: atr-validation-hardening.md
---

# Cross-AI Plan Review — ATR Validation Hardening

## Gemini Review

### 1. Summary
The plan is highly sound and addresses a clear technical debt issue: inconsistent, fragile, and duplicated null/zero-handling logic for `atr_14`. Centralizing this validation in the `IntelligencePipeline` transforms an implicit, error-prone dependency into an explicit, type-safe contract. The decision to keep raw `atr_14` for ML consumers while exposing `atr_14_valid` for logic-heavy consumers shows a nuanced understanding of the project's data requirements. The approach is surgical, reduces code bloat, and aligns well with the "silent wrong answers are worse than loud crashes" mantra.

### 2. Strengths
- **Centralized Contract:** Moving validation to the pipeline ingress ensures that downstream I2–I7 consumers work with guaranteed data quality.
- **Non-Destructive:** Retaining raw `atr_14` for model training/features prevents breaking downstream ML pipelines that might require the raw signal.
- **Simplified Plugins:** Removing the `symbol` argument from plugin logic significantly cleans up individual I7 plugin interfaces.
- **Deterministic:** Replacing ad-hoc null checks with a single utility (`get_atr_valid`) makes the system's behavior predictable and easy to audit.

### 3. Concerns
- **MEDIUM — Pipeline Injection Dependency:** Injecting `atr_14_valid` in the pipeline is efficient but creates a hard coupling between the `IntelligencePipeline` and `atr_utils`. Ensure `atr_utils` is stable.
- **MEDIUM — Silent Failures in I7:** If `get_atr_valid(features)` returns `None`, what should an I7 plugin do? If it continues execution without a valid ATR, it might violate the "no silent wrong answers" policy. I7 consumers should explicitly handle `None` by failing or skipping the signal, rather than assuming they can proceed.
- **LOW — Verification Gap:** The grep-based verification misses dynamic/string-constructed keys (e.g., `features.get("atr" + "_14")`).
- **LOW — Backwards Compatibility:** If existing code is updated, ensure no historical data or cached features depend on the previous inconsistent behavior (unlikely, but worth noting).

### 4. Suggestions
- **Strict I7 Handling:** Update the plan for I7 plugins — if `atr_14_valid` is `None`, the I7 plugin should return early (abort signal generation) rather than continuing with a potentially dangerous default.
- **Audit Logging:** If `get_atr_valid` encounters a missing or invalid value, consider adding a metrics counter (`atr_validation_failures`) within the pipeline to catch bad data upstream.
- **Test Case Addition:** Add tests in `tests/unit/intelligence/test_atr_utils.py` validating injection and behavior with malformed, missing, and zero inputs.

### 5. Risk Assessment
**Risk Level: LOW**

The changes are additive (`atr_14_valid` vs `atr_14`) and standardize logic that was already attempting (and often failing) to do the same thing. The primary risk is breaking I7 plugins by changing their expected inputs or handling of nulls, but this is easily mitigated by unit testing during the refactor.

---

## Codex Review

### 1. Summary
The plan is directionally good: centralizing ATR validation and separating raw `atr_14` from tradable `atr_14_valid` directly addresses the duplicated I7 floor logic. The main gap is placement and completeness. In this repo, the correct injection point is likely `feature_pipeline_executor.py:271`, immediately after `i1_result` is finalized and before `frames["i1"]` / I2-I6 execution, not in `services/intelligence_pipeline.py` after `FeaturePipelineExecutor.run()` returns. Also, the plan lists only a subset of ATR consumers.

### 2. Strengths
- Preserves raw `atr_14`, which is important for HMM/ML/training correctness.
- Removes repeated symbol extraction from I7 plugins, which is currently inconsistent.
- `float | None` accessor is a good contract for I7 gate logic: missing/invalid ATR should suppress signal emission, not invent scale.
- Single per-bar validation is consistent with the DAG model.
- Reusing the existing tick-size floor semantics avoids changing signal behavior unnecessarily.

### 3. Concerns
- **HIGH — Injection point is probably wrong as written.** `services/intelligence_pipeline.py` receives `fp_result` after I1-I6 and event construction. To affect I2-I6 and I7 flat features, inject after I1 carry-forward handling and before `frames["i1"] = dict(i1_result)` in `feature_pipeline_executor.py:271`.
- **HIGH — Listed scope is incomplete.** Repo search shows additional ATR consumers in SMC/I3/I4/I5/composites/services: `bos_choch.py`, `volume_profile.py`, `fibonacci_zones.py`, `market_profile.py`, `session_levels.py`, `candlestick_patterns.py`, `key_level_reaction.py`, `momentum_accel.py`, `signal_tracker.py`, and narrative prompts.
- **MEDIUM — Fallbacks weaken the "no silent wrong answers" principle.** Keeping fallbacks like `or 1.0` and `or 0.5` should be explicitly classified as "non-trading display/normalization fallback" and tested.
- **MEDIUM — Schema not declared.** `atr_14_valid` should be declared on `I1Indicators` in `schemas.py` even though `extra="allow"` currently permits it. Declaring it makes the contract visible and protects future schema tightening.
- **MEDIUM — Unknown symbol/tick size behavior undefined.** The new injection should define behavior for unknown symbols. Prefer returning `None` and logging/metricing once, not silently accepting raw ATR.
- **LOW — Verification grep is incomplete.** Misses bracket access, single quotes, `getattr(intel.i1, "atr_14")`, and local variables named `atr_14`.
- **LOW — `get_atr_valid(features) or 0.0` hides invalid data.** For I7, callers should branch on `None` and return `no_signal()`.

### 4. Suggestions
- Move injection into `FeaturePipelineExecutor.run()` after I1 result/carry-forward is finalized: `i1_result["atr_14_valid"] = get_atr_with_floor(i1_result, symbol)`.
- Add `atr_14_valid: float | None = None` to `I1Indicators` in `schemas.py`.
- For I7 plugins, require explicit None guard:
  ```python
  atr = get_atr_valid(features)
  if atr is None:
      return no_signal(...)
  ```
- Expand audit commands:
  ```bash
  rg -n "atr_14|get_atr_with_floor|get_atr_valid" src services tests -g '*.py'
  rg -n "get\([\"']atr_14|\[[\"']atr_14|getattr\([^,]+,[\"']atr_14" src services -g '*.py'
  ```
- Add integration test proving I2-I6 and I7 receive the injected field.
- Validate cross-timeframe cached intel behavior — older cached events may not contain `atr_14_valid`.

### 5. Risk Assessment
**Risk Level: MEDIUM**

The core idea is sound, but the proposed injection location and consumer inventory are likely incomplete. If implemented exactly as written, it may not harden I2-I6 at all and may leave several silent ATR paths untouched. With injection moved into `FeaturePipelineExecutor`, schema made explicit, and verification broadened, risk drops to LOW-MEDIUM.

---

## Consensus Summary

### Agreed Strengths
- Preserving raw `atr_14` for ML/HMM is the right call — both reviewers flagged this as well-designed
- Removing the symbol argument from 30 I7 plugins is a clean simplification
- `float | None` return contract is correct for I7 gate logic
- Single validation point per bar aligns with the DAG model

### Agreed Concerns (highest priority)
1. **I7 None handling must be explicit** (both) — `get_atr_valid()` returning `None` should cause the plugin to return `no_signal()`, not fall through to `or 0.0`. The fallback pattern defeats the purpose of the gate.
2. **Verification grep is incomplete** (both) — use `rg` with broader patterns; the current greps miss bracket access, single quotes, and local variable assignments.

### Critical Finding (Codex only — needs verification)
3. **Injection point may be wrong (HIGH)** — Codex identified that `services/intelligence_pipeline.py` may receive the assembled feature dict *after* I1-I6 have run, meaning injection there would only affect I7. The plan intends to harden all downstream tiers. Verify the exact point in `feature_pipeline_executor.py` where I1 output is finalized and I2+ dispatch begins — that is where injection belongs.
4. **Consumer scope is incomplete (HIGH)** — Additional ATR consumers exist in `bos_choch.py`, `fibonacci_zones.py`, `market_profile.py`, `session_levels.py`, etc. Run the expanded `rg` audit before implementation to get the true list.

### Divergent Views
- Gemini rates overall risk LOW; Codex rates MEDIUM — the difference is entirely due to the injection point concern. If that is confirmed correct or corrected, both would converge to LOW.
- Gemini doesn't flag schema declaration; Codex does (add `atr_14_valid` to `I1Indicators`).
