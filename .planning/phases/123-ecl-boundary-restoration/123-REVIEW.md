# Phase 123: Code Review Report

**Reviewed:** 2026-06-14T16:30:00Z
**Depth:** standard
**Files Reviewed:** 46
**Status:** issues_found

## Summary

Phase 123 implements the ECL (Extrinsic Confidence Layer) Boundary Restoration — removing all extrinsic emission suppressors from I7 plugins and establishing ECL fields as first-class signal schema annotations. The implementation follows the three-wave structure (A: gate removal + schema, B: factor scores, C: documentation) and generally adheres to the architectural requirements.

**Key Achievement:** All 17 Phase 119 plugins have been successfully converted from dual HMM+CTF gates to single HMM regime gates with CTF as ECL annotation. The `signal_schema.py` correctly defines `SIGNAL_SCHEMA_VERSION = "v3"` and all 5 new ECL fields in `REQUIRED_PIPELINE_FIELDS`.

**Critical Issues Found:** 2
**Warnings:** 8
**Info:** 3

## Critical Issues

### CR-01: _PHASE_119_PLUGINS Not Deleted — Breaks Test Assertions

**File:** `src/intelligence/register_plugins.py:688-710`

**Issue:** The `_PHASE_119_PLUGINS` frozenset (lines 688-710 in research doc) is still present in the codebase. The CONTEXT.md spec A7 requires this frozenset to be deleted entirely, with grep confirmation returning zero hits. This frozenset tracks the 17 plugins that had CTF gates — a category that dissolved after Phase 123 gate removal.

**Impact:** 
- Violates the "single plugin tier" architecture principle — the frozenset creates a permanent subclass distinction that no longer exists
- Test file `test_i6_confluence_enforcement.py` was updated with `_ECL_SHADOW_PLUGINS` list but still references the dissolved category
- Creates two competing sources of truth for which plugins have ECL compliance

**Evidence:**
- `test_i6_confluence_enforcement.py:105-123` defines `_ECL_SHADOW_PLUGINS` as a hardcoded list — this should be derived from TIER_I7 with a filter, not maintained separately
- The CONTEXT.md A7 verification step: `grep -rn "_PHASE_119_PLUGINS" src/ tests/` must return zero hits — currently fails

**Fix:**
```python
# In src/intelligence/register_plugins.py
# DELETE lines 688-710 (the _PHASE_119_PLUGINS frozenset definition)

# In tests/unit/intelligence/test_i6_confluence_enforcement.py
# REPLACE _ECL_SHADOW_PLUGINS hardcoded list with:
_ECL_SHADOW_PLUGINS = sorted([
    name for name in TIER_I7 
    if registry.patterns.get(name) and getattr(registry.patterns.get(name), "shadow_only", False)
])
```

### CR-02: REQUIRED_PIPELINE_FIELDS Gate Violation Risk — All Signals DLQ'd

**File:** `src/intelligence/trading/signal_schema.py:49-64`

**Issue:** The 5 new ECL fields were added to `REQUIRED_PIPELINE_FIELDS` frozenset (lines 58-62) but the implementation does not guarantee that all 37 I7 plugins populate these fields before the pipeline boundary check. If any plugin emits a signal without `factor_scores={}` or `context_features={}`, the `prepare_signals_or_dlq()` terminal boundary will DLQ the entire payload.

**Evidence:**
- AnchoredVWAPReversionPlugin (exempt, requires_i6_confluence=False) correctly implements `factor_scores` and `context_features` (lines 174-211)
- However, 8 exempt plugins in `_I7_I6_EXEMPT` may not have been updated uniformly
- `signal_writer.py:258-265` shows the fields are read from payload but commented out — no DB persistence yet

**Why This is Critical:** The `REQUIRED_PIPELINE_FIELDS` gate is enforced at the Kafka publish boundary. A single missing field causes total signal loss for that bar's entire payload. The architecture doc (Pitfall 1) explicitly warns: "Adding the new fields to REQUIRED_PIPELINE_FIELDS before all 37 plugins emit them causes every signal to be DLQ'd."

**Fix:** Implement the verification gate from CONTEXT.md A1b:
```bash
# Before deploying REQUIRED_PIPELINE_FIELDS addition, verify:
for plugin in TIER_I7:
    # Load each plugin and inspect compute_full() for:
    # 1. factor_scores dict construction
    # 2. context_features = capture_signal_features(...) assignment
    # 3. Both passed to make_signal_from_frame() or emit_signal()
    # If any plugin fails this check, REQUIRED_PIPELINE_FIELDS addition is unsafe
```

**Recommended Sequence:**
1. Create verification script that loads all 37 plugins and inspects their `make_signal_from_frame()` calls
2. Run verification BEFORE adding to REQUIRED_PIPELINE_FIELDS
3. Only add to REQUIRED_PIPELINE_FIELDS after verification passes
4. Consider adding {} defaults in `make_signal_from_frame()` as defense-in-depth

## Warnings

### WR-01: mtf_alignment CTF Gate Exemption Not Documented in Code

**File:** `src/intelligence/register_plugins.py` (commentary missing)

**Issue:** The CONTEXT.md A1 spec states: "`mtf_alignment` plugin is EXEMPT from CTF gate removal — CTF is its intrinsic signal." However, there is no code comment or documentation explaining this exemption in the plugin file itself. A future developer could mistakenly apply the CTF ECL pattern to mtf_alignment, breaking its core logic.

**Fix:** Add explicit documentation in `mtf_alignment.py`:
```python
# EXEMPT from Phase 123 CTF ECL annotation pattern:
# CTF is this plugin's INTRINSIC signal, not extrinsic context.
# The plugin consumes CTF scores as its primary detection input.
# Do NOT apply ctf_score/ctf_confirmed ECL fields here.
```

### WR-02: zone_friction_score Not Populated Despite Being in Schema

**File:** `src/intelligence/trading/signal_schema.py:320`

**Issue:** The `REQUIRED_PIPELINE_FIELDS` includes `zone_friction_score` (line 60) and `make_signal_from_frame()` accepts it (line 224), but none of the reviewed plugins populate this field. The RESEARCH.md A5a confirms zone_friction gates do not exist (grep returns zero), but the spec says to annotate zone_friction_score as ECL, not ignore it.

**Impact:** Zone friction data exists in I3 features (`supply_demand_zones.py` publishes it) but is never carried to the signal schema. The ML model will miss this extrinsic context signal.

**Fix:** Implement zone_friction extraction in at least one affected plugin (e.g., `supply_demand_setup.py`):
```python
# In supply_demand_setup.py compute_full():
_zf_raw = features.get("zone_friction_score")
zone_friction_score: float | None = float(_zf_raw) if _zf_raw is not None else None
# Pass to make_signal_from_frame(..., zone_friction_score=zone_friction_score)
```

### WR-03: Signal Writer Comments Out ECL Field Reading

**File:** `services/signal_writer.py:258-265`

**Issue:** Lines 258-265 are commented-out code showing `ctf_score`, `ctf_confirmed`, `zone_friction_score`, `factor_scores`, `context_features` reading from the payload. The comment says "Phase 123 ECL fields: read from payload, not yet persisted (Phase 128 3-table migration)." This creates ambiguity about whether the fields are actually being read.

**Evidence:** The active code path (lines 168-257) builds LedgerEntry without ECL fields. The comment implies they're read, but they're not.

**Fix:** Either:
1. Remove the commented code entirely if ECL fields are NOT yet persisted, OR
2. Uncomment and add `ctf_score`, `ctf_confirmed`, `zone_friction_score` to LedgerEntry dataclass if they ARE being carried through Kafka

The current state suggests the fields flow through Kafka but are dropped at persistence — this needs explicit clarification.

### WR-04: capture_signal_features or 0.0 Fallbacks Not Fully Removed

**File:** `src/intelligence/trading/confidence_utils.py:183-249`

**Issue:** The function uses `_nullable_float()` helper (lines 65-74) for CTF fields, which correctly preserves None semantics. However, line 191 shows `"vix_level": features.get("vix_level")` without `_nullable_float()` — direct get() call returns None if key absent, but the function should use consistent null-preserving extraction for ALL extrinsic fields.

**Fix:** Apply consistent pattern:
```python
# Line 191: Use explicit None check or _nullable_float for all I4 fields
"vix_level": _nullable_float(features, "vix_level"),
"vix_z": _nullable_float(features, "vix_z"),
# etc.
```

### WR-05: factor_scores Empty Dict {} vs None Semantic Gap

**File:** Multiple I7 plugins

**Issue:** The CONTEXT.md spec establishes `{}` (empty dict) as the "plugin emitted no factors" sentinel for `factor_scores` and `context_features`, while `None` means "field not written." However, `make_signal_from_frame()` lines 320-321 use `if factor_scores is not None else {}`, which means:
- Plugins that don't pass `factor_scores` kwarg get `{}`
- Plugins explicitly passing `factor_scores=None` also get `{}`

This conflates two distinct states.

**Fix:** Choose one semantic:
```python
# Option A: {} means no factors (current spec)
sig["factor_scores"] = factor_scores if factor_scores is not None else {}
sig["context_features"] = context_features if context_features is not None else {}

# Option B: None means no factors (simpler)
sig["factor_scores"] = factor_scores  # allow None through
sig["context_features"] = context_features  # allow None through
```

The spec (CONTEXT.md A1b) explicitly states {} is the sentinel, so Option A is correct — but the implementation should document this choice explicitly at the assignment point.

### WR-06: Confidence Composite Weight Rebalance Verification Missing

**File:** `src/intelligence/trading/delta_exhaustion.py:162-167`

**Issue:** The delta_exhaustion composite was rebalanced from 4 factors including `ctf_score_factor` to 4 factors excluding it (lines 162-167). The new weights are `0.35/0.30/0.25/0.10` summing to 1.0. However, there's no comment or test verifying the weight sum invariant.

**Impact:** Future modifications could accidentally break the sum=1.0 invariant, causing confidence values outside [0, 1] before clamping.

**Fix:** Add invariant assertion:
```python
weights = [0.35, 0.30, 0.25, 0.10]
assert abs(sum(weights) - 1.0) < 1e-9, f"Composite weights must sum to 1.0, got {sum(weights)}"
raw_conf = (
    weights[0] * cvd_z_score +
    weights[1] * price_fail_score +
    weights[2] * hmm_mean_reversion_score +
    weights[3] * persistence_score
)
```

### WR-07: Test _ECL_SHADOW_PLUGINS List Not Derived from TIER_I7

**File:** `tests/unit/intelligence/test_i6_confluence_enforcement.py:105-123`

**Issue:** The `_ECL_SHADOW_PLUGINS` list is hardcoded with 17 plugin names (lines 105-123). This creates a third source of truth (after TIER_I7 and the registry) for which plugins have ECL compliance. If a new plugin is added to TIER_I7 with `shadow_only=True`, this test would need manual updating.

**Fix:** Derive from registry:
```python
_ECL_SHADOW_PLUGINS = sorted([
    name for name in TIER_I7
    if registry.patterns.get(name) 
    and getattr(registry.patterns.get(name), "shadow_only", False)
    and name not in _I7_I6_EXEMPT
])
```

### WR-08: SIGNAL_SCHEMA_VERSION Type Mismatch with DB Column

**File:** `src/intelligence/trading/signal_schema.py:15`

**Issue:** `SIGNAL_SCHEMA_VERSION = "v3"` is a string, matching the historical pattern ("v1", "v2"). However, the comment says "Integer semantics are intended but text type preserved for DB compat." This creates cognitive load — the version is conceptually an integer but practically a string.

**Impact:** If Phase 128 attempts to use integer comparison or arithmetic on schema versions, it will break.

**Fix:** Either:
1. Accept the string convention and remove "integer semantics" from comments, OR
2. Store as `3` (int) and cast to str at DB INSERT time

Given migration 081/095 use text type and the weight of history, Option 1 is safer. Document the decision explicitly.

## Info

### IN-01: Architecture Doc Update Status Unclear

**File:** `docs/architecture/setup-confidence-patterns.md`

**Issue:** CONTEXT.md Wave C requires updating this doc with ECL section and Pattern 3 language changes. The research doc confirms the file exists with correct filename (rename already done). However, it's unclear from the submitted files whether the content updates (ECL section, Pattern Vocabulary table updates, Pattern 3 revision) were actually completed.

**Recommendation:** Verify the doc content matches the ECL boundary invariant. Specifically check:
- Pattern 3 mentions "ECL annotation" not "CTF gate"
- Pattern Vocabulary table distinguishes CONFIDENCE FACTOR from EXTRINSIC CONFIDENCE VECTOR
- ECL section exists with the 5 fields listed

### IN-02: Exhaustion Guard Audit Grep Results Not Included

**Issue:** CONTEXT.md A5a requires running `grep -rn "exhaustion_guard\|exhaustion_score.*no_signal\|no_signal.*exhaustion"` to find emission suppressors. The research doc (line 212) confirms "exhaustion score is already a feature, not a gate" but the actual grep results showing zero hits are not included in the submission.

**Recommendation:** Include the grep output in the phase verification artifacts to prove the audit was run.

### IN-03: Microstructure Utils CTF Removal Not Verified

**File:** `src/intelligence/trading/microstructure_utils.py` (not in file list)

**Issue:** CONTEXT.md A4 lists `microstructure_utils.detect_spike_signal` as requiring CTF gate removal and composite rebalancing. This file was not in the required reading list, so the reviewer cannot verify the changes were made correctly.

**Recommendation:** Include `microstructure_utils.py` in the verification artifacts, or add it to the required reading list for code review.

---

## Positive Findings

1. **ECL Pattern Consistently Applied:** All reviewed plugins correctly implement the null-preserving CTF extraction pattern (`_ctf_raw = features.get("ctf_score"); ctf_score = float(_ctf_raw) if _ctf_raw is not None else None`).

2. **factor_scores Uniformly Implemented:** Every reviewed plugin collects `factor_scores` dict with rounded float values before compositing — this pattern is consistent across the codebase.

3. **context_features Propagation Complete:** All reviewed plugins correctly set both `features_snapshot` and `context_features` from the `capture_signal_features()` return value.

4. **Test Coverage Comprehensive:** The `test_i7_extrinsic_contract.py` tests properly validate ECL field presence and extrinsic perturbation invariance.

5. **Schema Version Management:** `SIGNAL_SCHEMA_VERSION = "v3"` correctly acknowledges the semantic change from v2.

## Verification Recommendations

Before deploying this phase:

1. **Run Critical Fix CR-01 verification:** Execute `grep -rn "_PHASE_119_PLUGINS" src/ tests/` and confirm zero hits.

2. **Run CR-02 verification:** Create script to validate all 37 plugins populate `factor_scores` and `context_features` before `REQUIRED_PIPELINE_FIELDS` enforcement.

3. **Verify architecture doc content:** Confirm `setup-confidence-patterns.md` contains ECL section and updated Pattern 3 language.

4. **Test signal pipeline end-to-end:** Verify a full bar flow from plugin → Kafka → signal_writer produces no DLQ errors for all 37 plugins.

---

_Reviewed: 2026-06-14T16:30:00Z_  
_Reviewer: Claude (gsd-code-reviewer)_  
_Depth: standard_  
_Phase: 123-ecl-boundary-restoration_
