# Phase 119: Remaining 16 Setup Refactoring - Context

**Gathered:** 2026-06-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Apply the 6 GOOD patterns to all 17 remaining NEEDS_REFACTOR I7 setups (roadmap title says 16 — off by 1, MomentumBreakout is included). Wave 1 (8 setups): OFIDivergence, OFISpike, CVDSpike, CandlestickPatternSetup, FailedBreakout, LiquidityHunt, DeltaExhaustion, SessionExtremesSetup. Wave 2 (9 setups): LVNBreakout, ORB15, ORB30, SecondLegContinuation, VCP, VWAPReclaim, DualDivergence, VWAPDeviation, MomentumBreakout.

**The 6 GOOD patterns (applied to all 17):**
1. Multi-factor intrinsic confidence (weighted composite, meaningful factors — see D-03 for gate structure)
2. I6 confluence mandatory (ctf_score, ctf_structure, ctf_trend consumed from frames["i6"])
3. Strict dual gate before OHLCV extraction (regime weight + I6 score — cheap checks first)
4. Continuous hmm_regime_weight (probability gate, not binary string comparison — see D-01)
5. Early gate optimization (mandatory gates run before any OHLCV extraction)
6. shadow_only=True (all 17 setups run in shadow mode until Phase 120 promotes them)

**In scope:**
- All 17 target plugins in `src/intelligence/trading/`
- Adding `shadow_only=True` to all 17 plugins
- Adding `requires_i6_confluence=True` to all 17 plugins (replacing the TODO=False declarations)
- Adding regime gate + I6 gate before OHLCV extraction in all 17 plugins
- Replacing single-factor/meaningless confidence formulas with 4-factor intrinsic composites
- Named `_MIN_*` constants for all feature-scale thresholds (DB-tunable per D-14 pattern)
- validate_tier() enforcement of `requires_i6_confluence=True` (new ArchitectureViolation check)
- validate_tier() regression tests covering all TIER_I7 plugins
- Documentation update + CLAUDE.md 6 GOOD patterns reference

**Out of scope:**
- MomentumBreakout confidence rewrite (its 3-factor formula is already sound — gates only)
- Empirical threshold tuning (Phase 120 handles this via shadow mode feedback)
- PatternCompletion, OFIContinuation, GapAnalysisSetup, CVDDivergence, DivergenceStack (done in Phase 118)
- GOOD setups (TrendFollowing, MeanReversion, LiquiditySweepReclaim, CHoCHReversal, SqueezeExpansion, SupplyDemandSetup) — already correct
- Shadow mode promotion (Phase 120)

</domain>

<decisions>
## Implementation Decisions

### D-01: hmm_regime_weight — Pre-entry gate only

`hmm_regime_weight()` is used as a **pre-entry eligibility gate**, NOT as a confidence formula factor.

```python
# Before any OHLCV extraction (early gate):
if hmm_regime_weight(features, self.regime_type) < _MIN_REGIME_WEIGHT:
    return no_signal()

_MIN_REGIME_WEIGHT = 0.30  # 30% probability mass on target regime
```

**Why:** SoC invariant — confidence = intrinsic signal strength; regime = eligibility check. Orthogonal concerns. Phase 118 was correct to strip hmm_regime_weight from confidence formulas. The roadmap's "continuous regime weighting" means replacing non-existent regime awareness (all 17 broken setups have zero regime influence) with a probability gate — NOT re-introducing it into confidence arithmetic. `hmm_regime_weight()` returns a continuous probability [0,1]; `>= 0.30` replaces the non-existent check with a meaningful threshold.

**Note:** This also implements Early Gate Optimization (GOOD pattern 5) simultaneously — cheap HMM check runs before expensive OHLCV extraction.

---

### D-02: validate_tier() Enforcement

`validate_tier()` adds exactly one new check to the I7 block:

```python
# New check in the I7 block of validate_tier():
if not getattr(plugin, "requires_i6_confluence", None):
    raise ArchitectureViolation(
        f"I7 plugin '{name}' must have requires_i6_confluence=True. "
        f"Phase 119 requires all I7 setups consume I6 cross-timeframe data."
    )
```

- **`requires_i6_confluence=True`**: Enforced permanently. Architectural invariant (cross-timeframe confirmation is a sound, permanent principle). Non-gameable.
- **`shadow_only=True`**: Verified in code review per plan, NOT enforced in `validate_tier`. Truth lives in `shadow_registry` DB table (Phase 120 promotions update DB, not plugin ClassVar). Enforcing in `validate_tier` would create two competing sources of truth.
- **`confidence_factors ClassVar`**: Not added. Cargo-cult (trivially gameable; static count cannot verify meaningful factor diversity). Factor quality is enforced by code review in plans + Phase 120 empirical validation.

---

### D-03: Dual Gate Structure + Threshold Values

**Mandatory dual gate before OHLCV extraction (all 17 setups):**

```python
# Gate 1 (regime — cheap):
if hmm_regime_weight(features, self.regime_type) < _MIN_REGIME_WEIGHT:  # 0.30
    return no_signal()

# Gate 2 (I6 — cheap):
ctf_score = float(features.get("ctf_score") or 0.0)
if abs(ctf_score) < _MIN_CTF_SCORE:  # 0.25
    return no_signal()

# Then: OHLCV extraction (expensive)
```

**Threshold types:**
- **Z-score features** (`ofi_spike_z`, `cvd_spike_z`): Gate at `>= 2.0` — statistically grounded, instrument-agnostic. 2-sigma IS the semantic meaning of a z-score.
- **Feature-scale constants**: Named `_MIN_*` constants per plugin. DB-tunable per existing D-14 pattern (`shadow_registry` gate parameters, never overwritten on restart). Researcher derives semantically reasonable defaults per plugin in plans.

---

### D-04: MomentumBreakout Scope

MomentumBreakout gets full Phase 119 treatment:
- 3-factor intrinsic confidence formula (roc_score + vol_score + break_margin) is sound — **keep as-is**
- Add: `shadow_only=True`, regime gate, I6 early gate, `requires_i6_confluence=True`
- Goes in Wave 2 (119-02) with the other 9 remaining setups
- Roadmap title said "16 remaining" — it's 17. The plan listings (Wave 1=8, Wave 2=9) were correct.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Signal Quality Crisis Context
- `docs/plans/2026-06-07-signal-quality-crisis-root-cause-analysis.md` — Full root cause analysis with GOOD/MODERATE/NEEDS_REFACTOR cluster data, 6 GOOD patterns, Council analytical review (read the Council review section carefully — it overrides specific threshold values from earlier in the doc)

### Phase 118 Established Patterns (reference implementations)
- `.planning/phases/118-confidence-integrity-top5-setup-refactoring/118-RESEARCH.md` — Per-plugin analysis of OFIContinuation, PatternCompletion, GapAnalysisSetup, CVDDivergence, DivergenceStack. Multi-factor confidence formula templates.
- `.planning/phases/118-confidence-integrity-top5-setup-refactoring/118-VERIFICATION.md` — What Phase 118 verified as complete (what NOT to re-do)

### Reference Implementations (read before writing any plugin)
- `src/intelligence/trading/ofi_continuation.py` — Primary reference: magnitude gate + 4-factor intrinsic composite + compose_confidence
- `src/intelligence/trading/liquidity_sweep_reclaim.py` — Reference: dual gates + I6 integration + continuous regime weighting
- `src/intelligence/trading/choch_reversal.py` — Reference: I6 confluence + zone penalties

### Architecture Invariants
- `src/intelligence/plugins/base.py` — ArchitectureViolation, PatternPlugin Protocol, PluginRegistry.validate_tier() (I7 block at line ~130)
- `src/intelligence/register_plugins.py` — TIER_I7 list (single source of truth for all I7 plugins)
- `src/intelligence/trading/confidence_utils.py` — compose_confidence(), hmm_regime_weight(), capture_signal_features(), clamp01()

### Design Principles
- `docs/foundation/principles.md` — Full principles doc (empirical over theoretical, data quality, SoC)
- `CLAUDE.md` — Key rules section: parallel dicts → dataclass, shadow governance, signal logic rules

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `hmm_regime_weight(features, regime_type)` in `confidence_utils.py` — use for D-01 gate on all 17 setups
- `compose_confidence(raw: float)` in `confidence_utils.py` — wraps all final confidence values
- `capture_signal_features(features, direction, tier, confidence)` — must be called for all signal dicts
- `clamp01(x)` in `confidence_utils.py` — use everywhere instead of `min(1.0, max(0.0, x))`
- `extract_ohlcv(frames, min_lookback)` — call AFTER the dual gate, not before
- `no_signal()` in `plugin_utils.py` — return value for all gate failures
- `frames.get("i6") or {}` — standard pattern for merging I6 features into the flat dict

### Established Patterns
- **Dual gate before OHLCV**: ofi_continuation.py lines 90-100 shows regime + magnitude gate running before OHLCV extraction
- **4-factor intrinsic composite**: ofi_continuation.py lines 145-168 — 4 named score variables, explicit weights summing to 1.0
- **Named constants at module level**: `_MIN_OFI_MAGNITUDE`, `_MIN_CONSECUTIVE_BARS` etc. (DB-tunable)
- **shadow_only=True**: explicit ClassVar declaration (not inherited — must be explicitly set, as in ofi_continuation.py:55)
- **requires_i6_confluence=True**: ClassVar declaration — must change from False+TODO to True with the TODO removed

### Integration Points
- `validate_tier()` in `src/intelligence/plugins/base.py:113` — add requires_i6_confluence=True enforcement in I7 block
- `TIER_I7` in `src/intelligence/register_plugins.py:610` — single source of truth, no changes needed
- `shadow_registry` table — all 17 plugins auto-enrolled at startup via `shadow_registry_ensure()`
- `tests/unit/intelligence/test_i7_extrinsic_contract.py` — existing parametrized contract test over all I7 plugins; update to also assert shadow_only=True and requires_i6_confluence=True

</code_context>

<specifics>
## Specific Ideas

- **MomentumBreakout confidence unchanged**: The 3-factor formula (0.40*roc_score + 0.35*vol_score + 0.25*break_margin) introduced in Phase 118 is sound. Phase 119 adds gates only — no confidence rewrite.
- **Z-score threshold is 2.0 everywhere**: For `ofi_spike_z`, `cvd_spike_z`, and any other z-score features, `>= 2.0` is the gate. Not 1.5, not 2.5. Statistically grounded, instrument-agnostic.
- **I6 gate uses ctf_score**: `abs(features.get("ctf_score") or 0.0) >= 0.25` is the second mandatory gate. ctf_score is the primary I6 cross-timeframe score; ctf_structure and ctf_trend are used as supporting factors in the confidence composite or supporting_factors list.
- **LiquidityHunt already has requires_i6_confluence=True**: Verify in plans — it may only need shadow_only=True and gate additions.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 119-Remaining-16-Setup-Refactoring*
*Context gathered: 2026-06-09*
