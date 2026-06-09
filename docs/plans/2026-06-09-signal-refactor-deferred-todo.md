# Signal Refactor Deferred Items — Phase 118 Simplify Pass

**Date:** 2026-06-09
**Source:** `/simplify` pass on Phase 118 diff
**Status:** under-review
**Related arc doc:** `docs/plans/2026-06-07-signal-quality-crisis-root-cause-analysis.md`

Items deferred because they require scope beyond the Phase 118 diff or are multi-phase policy decisions. Each item is ready to pick up as a named sub-task in a future phase.

---

## TODO Items

### T-01: Per-instrument OFI thresholds → Settings/config
**File:** `src/intelligence/trading/ofi_continuation.py`
**What:** `_OFI_PARAMS` is a hardcoded dict of `(p75_gate, p90_upper_ref)` per instrument. These are starting values derived analytically (CVD discrete values; OFI from RCA analysis). Shadow mode will refine them, but there's no write-back path — the values live in source code, not config.
**Target:** Move to `Settings` as `per_instrument_plugin_config: dict[str, InstrumentPluginConfig]` or `contract_metadata` table so shadow promotion can update them without a code deploy.
**Phase scope:** Fits as a Wave 0 task in Phase 120 or later once shadow mode has produced real p75/p90 data.
**Priority:** medium — values are safe stubs; shadow mode won't be corrupted, just can't self-update.

---

### T-02: Exhaustion guard partial removal — complete the extrinsic strip
**Files:** 10+ remaining I7 plugins still call `apply_exhaustion_guard()` / `apply_exhaustion_boost()`
**What:** Phase 118 stripped exhaustion modifiers from 5 plugins as part of the intrinsic-only confidence policy. ~10 plugins still use exhaustion as a confidence modifier, creating inconsistency: some signals penalized for exhaustion, others not, based solely on which phase touched them.
**Policy question:** Is exhaustion extrinsic (capture only, don't modify confidence) or intrinsic (it IS the signal for DeltaExhaustion)? Phase 118 answer: extrinsic for all plugins except `DeltaExhaustion` itself.
**Target:** Run the same extrinsic strip Wave 0 across all remaining callers. `apply_exhaustion_guard()` and `apply_exhaustion_boost()` should be removed from `exhaustion_utils.py` once no callers remain.
**Phase scope:** Phase 119 Wave 0 (system-wide extrinsic strip already planned). See `docs/ideas/signal-08-i7-confidence-architecture.md`.
**Priority:** high — confidence distribution is inconsistent across plugins until this is done.

---

### T-03: Zone friction asymmetry — complete the extrinsic strip
**Files:** `src/intelligence/trading/momentum_breakout.py`, `trend_following.py` (stripped); `cis_scorer.py`, `supply_demand_setup.py` (still use zone features in confidence)
**What:** Same policy issue as T-02 but for zone friction penalties. Removed from 2 plugins in Phase 118, intact in others.
**Target:** Zone awareness belongs either in a shared `apply_zone_friction()` helper with a clear in/out-of-confidence decision, or entirely in I6 CTF scores (which already exist). If the policy is "zone context is extrinsic," strip it from all remaining callers.
**Phase scope:** Phase 119 Wave 0 alongside T-02.
**Priority:** high — same confidence distribution inconsistency concern.

---

### T-05: `microstructure_utils.py` — extrinsic factors not yet stripped
**File:** `src/intelligence/trading/microstructure_utils.py`
**What:** `detect_spike_signal()` still adds `ctf_score` (+0.15 weight) and `hmm_regime_weight` (+0.10 centered) to confidence. Phase 117 wired these in; Phase 118 Wave 0 stripped the 5 setup plugins but missed the shared spike util. `ofi_spike` and `cvd_spike` both inherit this.
**Target:** Phase 119 Wave 0 — apply same extrinsic strip. `ctf_score` moves to `supporting_factors` append only; `hmm_regime_weight` removed.
**Priority:** high — same inconsistency concern as T-02 and T-03; these are high-volume spike plugins.

---

### T-04: `weighted_confidence()` helper for 4-factor pattern
**File:** `src/intelligence/trading/confidence_utils.py`
**What:** Every Phase 118 refactored plugin now contains the same scaffold: clamp each factor, define weights summing to 1.0, compute weighted sum, pass to `compose_confidence()`. The weights-sum-to-1.0 invariant is currently enforced only by comment.
**Target:** `weighted_confidence(factors: list[tuple[float, float]]) -> float` in `confidence_utils.py` that accepts `[(weight, score), ...]`, asserts `sum(weights) ≈ 1.0`, and returns `compose_confidence(sum(w*s))`.
**Hold reason:** Each plugin's factors are domain-specific (different names, different computation). The shared part is only the final sum + ceiling clamp — a single line. Three similar lines > premature abstraction. Revisit after Phase 120 when all 37 I7 plugins have been refactored; at that point the pattern is mature enough to abstract.
**Phase scope:** Post-Phase-120, when the full plugin set is on intrinsic-only confidence.
**Priority:** low — the `clamp01()` fix from Phase 118 already eliminated the noise; the remaining duplication is 1 line per plugin.
