# Phase 119: Remaining 16 Setup Refactoring - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-09
**Phase:** 119-remaining-16-setup-refactoring
**Areas discussed:** hmm_regime_weight placement, validate_tier enforcement, Dual gate threshold values, MomentumBreakout scope

---

## hmm_regime_weight placement

| Option | Description | Selected |
|--------|-------------|----------|
| Pre-entry gate only | hmm_regime_weight() evaluates before signal fires; confidence stays intrinsic-only | ✓ |
| Soft gate multiplier on confidence threshold | Regime weight modulates minimum confidence threshold | |
| Back in the confidence formula | hmm_regime_weight() returns to weighted confidence composite (reverting Phase 118) | |

**User's choice:** Deferred to Renaissance Council first-principles analysis — Claude applied SoC reasoning.
**Notes:** User twice invoked "Renaissance Council / Jim Simons rigor" rather than selecting an option directly. Claude concluded: confidence = intrinsic signal strength; regime gate = eligibility check. Orthogonal concerns. Phase 118 was architecturally correct. "Continuous" in the roadmap refers to using probability function vs. binary string comparison, not adding it back to the confidence formula.

---

## validate_tier enforcement

| Option | Description | Selected |
|--------|-------------|----------|
| requires_i6_confluence=True + shadow_only=True | Both ClassVar booleans enforced in validate_tier | |
| requires_i6_confluence=True only | I6 integration is permanent architectural invariant; shadow_only is transient | |
| Add confidence_factors ClassVar (count-based) | New ClassVar enforcing >= 4 in validate_tier | initially selected, then revised |

**User's choice:** Initially selected confidence_factors ClassVar, then invoked Renaissance rigor analysis.
**Notes:** After first-principles analysis, Claude overrode the initial selection. confidence_factors is cargo-cult (trivially gameable). shadow_only belongs in shadow_registry DB truth source, not a startup check. Final decision: validate_tier enforces requires_i6_confluence=True only (new ArchitectureViolation check). shadow_only verified in code review per plan.

---

## Dual gate threshold values

| Option | Description | Selected |
|--------|-------------|----------|
| Pattern enforcement + reasonable defaults, named constants | Named _MIN_* constants, same approach as Phase 118 | ✓ (via analysis) |
| Pattern only — no numeric gates | Structure enforced but no specific values | |
| Conservative defaults — tighten via shadow feedback | High thresholds, loosen via Phase 120 data | |

**User's choice:** Deferred to Renaissance Council analysis — Claude applied statistical principles.
**Notes:** User invoked rigor analysis again. Claude resolved: z-score thresholds at 2.0 (statistically grounded, instrument-agnostic); mandatory dual gate = regime (0.30) + I6 ctf_score (0.25); feature-scale constants as named _MIN_* with DB-tunable values. "Conservative defaults" framing was rejected — goal is structural soundness, not volume suppression.

---

## MomentumBreakout scope

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — full treatment (shadow_only=True, I6 gate, regime gate) | 3-factor formula kept, gates added. 17 total setups. | ✓ |
| Partial — gates only, no confidence rewrite | MomentumBreakout already has sound formula from Phase 118 | |

**User's choice:** Full treatment.
**Notes:** MomentumBreakout's 3-factor confidence formula (roc_score + vol_score + break_margin) is sound and stays unchanged. Phase 119 adds the mandatory gates only. Roadmap title said "16 remaining" — corrected to 17 (Wave 1=8, Wave 2=9). MomentumBreakout goes in Wave 2 (119-02).

---

## Claude's Discretion

- **hmm_regime_weight gate value (0.30)**: User deferred to Claude. Set to 0.30 as minimum meaningful probability mass on target regime.
- **I6 ctf_score gate value (0.25)**: User deferred to Claude. Set to 0.25 as minimum meaningful cross-timeframe confirmation.
- **validate_tier final decision**: User initially selected count-based enforcement, but Claude overrode after rigorous analysis with explicit user-requested rigor. Final: requires_i6_confluence=True only.

## Deferred Ideas

None — discussion stayed within phase scope.
