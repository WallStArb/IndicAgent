# Phase 123: ECL Boundary Restoration - Research

**Researched:** 2026-06-14
**Domain:** I7 signal emission gates, signal schema, signal persistence pipeline
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Signal Schema (Wave A)**
- Add 5 new nullable ECL fields to `src/intelligence/trading/signal_schema.py`: `ctf_score: float | None`, `ctf_confirmed: bool | None`, `zone_friction_score: float | None`, `factor_scores: dict | None`, `context_features: dict | None`
- `None` means "no data at emit time"; `0.0` means "genuine neutral reading" - these are semantically distinct populations. No `or 0.0` fallbacks.
- Increment `SIGNAL_SCHEMA_VERSION` by 1 in `signal_schema.py`
- Add all 5 new fields to `REQUIRED_PIPELINE_FIELDS` frozenset - `factor_scores` and `context_features` use `{}` (empty dict, not None) as the "plugin not yet updated" sentinel
- `mtf_alignment` plugin is EXEMPT from CTF gate removal - CTF is its intrinsic signal

**CTF Gate Removal (Wave A)**
- Remove all `if abs(ctf_score) < get_min_ctf_score(): return no_signal()` patterns from all 17 `_PHASE_119_PLUGINS`
- Replacement pattern: `_ctf_raw = features.get("ctf_score"); ctf_score: float | None = float(_ctf_raw) if _ctf_raw is not None else None; ctf_confirmed: bool | None = (abs(ctf_score) >= get_min_ctf_score()) if ctf_score is not None else None`
- Pass `ctf_score=ctf_score, ctf_confirmed=ctf_confirmed` to `emit_signal`
- Affected plugins (17): `ofi_spike`, `cvd_spike`, `ofi_divergence`, `failed_breakout`, `candlestick_pattern_setup`, `session_extremes_setup`, `liquidity_hunt`, `delta_exhaustion`, `lvn_breakout`, `vwap_reclaim`, `vwap_deviation`, `momentum_breakout`, `orb15`, `orb30`, `second_leg_continuation`, `vcp`, `dual_divergence`
- Also: `microstructure_utils.detect_spike_signal` (delegate used by ofi_spike + cvd_spike)

**CTF Composite Violations (Wave A)**
- `delta_exhaustion.py`: Remove `ctf_score_factor` from composite; rebalance to `0.35*exhaustion + 0.30*momentum_reversal + 0.25*volume + 0.10*persistence`
- `microstructure_utils.detect_spike_signal`: Remove CTF gate delegate and `ctf_factor` from composite; rebalance to `0.50*z_score + 0.30*volume + 0.20*persistence`

**Zone Friction Gate Removal (Wave A)**
- Remove all `if zone_friction > _MAX_ZONE_FRICTION: return no_signal()` patterns
- Primary file: `supply_demand_setup.py`; grep for others
- Replacement: annotate as `zone_friction_score: float | None` top-level field, pass to `emit_signal`
- Null-preserving pattern: `_zf_raw = features.get("zone_friction_score"); zone_friction_score: float | None = float(_zf_raw) if _zf_raw is not None else None`

**Exhaustion Guard Audit (Wave A)**
- Run `grep -rn "exhaustion_guard\|exhaustion_score.*no_signal\|no_signal.*exhaustion"` to find any emission suppressors
- Expected result: exhaustion score is already a feature, not a gate - no suppressors found
- If suppressors found: remove gate, annotate as `exhaustion_score: float | None` field

**context_features Promotion - Three-File Change (Wave A)**
- `confidence_utils.py`: Change `capture_signal_features()` from writing to `sig["_shadow"]` to returning the dict; keep backward-compat `_shadow` write during transition
- Every I7 plugin calling `capture_signal_features()`: capture return value into `signal["context_features"]`
- `services/signal_writer.py`: Read new fields from Kafka payload in `_parse_signals()` / `_build_ledger_entries()`

**emit_signal / make_signal_from_frame Threading (Wave A)**
- Add `ctf_score`, `ctf_confirmed`, `zone_friction_score`, `factor_scores`, `context_features` parameters to both functions in `plugin_utils.py`
- All optional, default `None`; pass through to `validate_signal` and the signal dict

**_PHASE_119_PLUGINS Frozenset Removal (Wave A)**
- Delete `_PHASE_119_PLUGINS` frozenset and its comment from `register_plugins.py`
- Grep must return zero hits after deletion

**Test Updates (Wave A)**
- `tests/unit/intelligence/test_i7_extrinsic_contract.py`: Flip assertions - `ctf=0.0 -> no_signal()` becomes `ctf=None -> valid signal with ctf_confirmed=False`
- Any test that mocks signals without the 5 new fields: add `"factor_scores": {}, "context_features": {}`

**Factor Scores Collection (Wave B)**
- Every `compute_full()` in all 37 plugins collects `factor_scores` dict before compositing
- Keys are plugin-specific, values are pre-composite [0, 1] scores, rounded to 4 decimal places
- Pass `factor_scores=factor_scores` to `emit_signal`

**Architecture Doc (Wave C)**
- `git mv docs/architecture/i7-setup-confidence-patterns.md docs/architecture/setup-confidence-patterns.md`
- Update doc: title, add ECL section, update Pattern Vocabulary table
- Update all cross-references across docs/, src/, tests/

### Claude's Discretion
- Order of file modifications within Wave A (the spec identifies dependencies but the exact commit sequence within the wave is implementation-level)
- How to handle signal dicts in unit tests that don't yet include the new ECL fields (use `{}` defaults)
- Whether to add `ctf_score`, `ctf_confirmed`, `zone_friction_score` to LedgerEntry now or leave for Phase 128 writer migration (confirm against signal_writer.py current schema)

### Deferred Ideas (OUT OF SCOPE)
- `--warmup` flag for historical replay - deferred to Phase 124
- ON CONFLICT IS NULL guard for CTF columns in feature_writer - deferred to Phase 124
- 5 over-firing plugin fixes - deferred to Phase 124
- APR parameter migration - deferred to Phase 125
- Clean replay - deferred to Phase 126
- 3-table schema design - deferred to Phase 127
- Database migration - deferred to Phase 128
- Script rewriting - deferred to Phase 129
- CounterfactualTracker daemon - deferred to Phase 130 (v2.11)
- I6 DB bootstrap at daemon startup - deferred to Phase 130 (v2.11)
</user_constraints>

---

## Summary

Phase 123 removes all extrinsic emission suppressors from I7 plugins and promotes the resulting metadata to first-class signal schema fields. The work is pure code refactoring with no DB migration - all 5 new fields (`ctf_score`, `ctf_confirmed`, `zone_friction_score`, `factor_scores`, `context_features`) live in the Kafka payload and `signal_ledger` receives them via the existing `LedgerEntry` mechanism, extended with new fields.

The three waves are independent in direction but sequentially important: Wave A must ship first because it creates the schema fields that Wave B's `factor_scores` depends on, and Wave B content feeds into Wave C's documentation accuracy.

The architecture doc rename (Wave C) is already partially done - `docs/architecture/setup-confidence-patterns.md` exists with correct filename. The file still contains Phase 119 gate language that needs updating to reflect the ECL boundary invariant.

**Primary recommendation:** Implement waves sequentially, commit each wave separately. Wave A is the highest-risk wave (touching 17+ plugin files, signal schema, pipeline boundary, and test assertions) and should be planned with per-task verification steps.

---

## Current State Analysis (VERIFIED from source)

### Signal Schema (`src/intelligence/trading/signal_schema.py`)

**What exists:**

- `REQUIRED_SIGNAL_FIELDS` frozenset: 18 fields checked at plugin construction time
- `REQUIRED_PIPELINE_FIELDS` frozenset: currently 6 fields (`signal_id`, `status`, `bar_id`, `composite_rank`, `raw_cis_score`, `filtered_cis_score`)
- Signal type is `"signal.v1"` (string literal in `validate_signal`)
- `SIGNAL_SCHEMA_VERSION` constant does NOT currently exist in `signal_schema.py` - it is referenced in CLAUDE.md as canonical but has not been defined yet in this file. Historical doc shows it was previously a text constant `"v2"` used in other contexts. Phase 123 creates it fresh with value (likely `3` to acknowledge prior versions).
- `make_signal_from_frame()` - sole public construction path - currently has NO `ctf_score`, `ctf_confirmed`, `zone_friction_score`, `factor_scores`, or `context_features` parameters
- `make_signal_id()` hashes `(symbol, bar_ts, tf, OHLCV, setup_plugin, direction)` - entry_type is NOT in the hash, so multiple entry_types per plugin fire produce the same signal_id (important for Phase 128)

**What needs adding:**
- `SIGNAL_SCHEMA_VERSION` constant (new)
- 5 new nullable fields to `REQUIRED_PIPELINE_FIELDS`
- Schema does not need `validate_signal()` changes - new fields are optional pipeline fields, not required signal construction fields

### `emit_signal` in `plugin_utils.py`

**Current signature:**
```python
def emit_signal(
    trade_frame: TradeFrame,
    *,
    confidence: float,
    entry_type: str,
    stop_loss: float,
    target_1: float,
    target_2: float | None = None,
    **signal_fields: Any,
) -> dict[str, Any]:
```

The `**signal_fields` catch-all passes everything through to `make_signal_from_frame`. This means the 5 new ECL fields can be threaded through `emit_signal` via `**signal_fields` without changing the `emit_signal` signature at all - they will land in `make_signal_from_frame`'s `**kwargs`. However, `make_signal_from_frame` does NOT accept `**kwargs` - it has explicit parameters only. So both functions need explicit parameter additions.

**`make_signal_from_frame` current signature:** explicit named params only - no `**kwargs` catch-all. All 5 new fields must be added as named optional parameters defaulting to `None`.

### `capture_signal_features` in `confidence_utils.py`

**Current behavior (CONFIRMED from source):**
- Returns the shadow dict directly (returns `dict[str, Any]`)
- Called as `capture_signal_features(features, direction, profile_name, existing_confidence)`
- Does NOT write to `sig["_shadow"]` - the docstring says "Returns a standardized dict stored as signal['features_snapshot']"
- The CONTEXT.md spec says "Change from writing to sig['_shadow'] to returning the dict" - this is already the case. The function already returns the dict.
- The actual problem: callsites assign the return value to `signal["features_snapshot"]`, not `signal["context_features"]`. So `context_features` as a top-level key never gets set.

**Callsite pattern (all 37 plugins use one of these forms):**
```python
# Form 1 - inside make_signal_from_frame call
features_snapshot=capture_signal_features(features, direction, "smc", confidence)

# Form 2 - assigned after make_signal_from_frame
signal["features_snapshot"] = capture_signal_features(features, direction, "microstructure", signal["confidence"])

# Form 3 - via supply_demand
features_snapshot=capture_signal_features(features, direction, "smc", confidence)
```

**What needs to change:** Every callsite must additionally set `signal["context_features"] = <return value>`. The return value is already a dict; no function signature change needed. The `_shadow` backward-compat write mentioned in CONTEXT.md is not actually needed since the function already returns the dict directly (no shadow write happening now).

**CTF `or 0.0` fallback in `capture_signal_features` (CONFIRMED from source):**
```python
"ctf_score": float(features.get("ctf_score", 0.0)),
```
This is the "or 0.0" conflation that A2 must fix. All 8 CTF sub-score fields in the function use this pattern. The fix is null-preserving extraction.

### CTF Gate Pattern (CONFIRMED from source)

**In `delta_exhaustion.py` (representative):**
```python
# Gate 2: I6 ctf_score gate
ctf_score = float(features.get("ctf_score") or 0.0)
if abs(ctf_score) < get_min_ctf_score():
    return no_signal()
```
Plus CTF appears in the confidence composite:
```python
ctf_score_factor = clamp01(
    (abs(ctf_score) - get_min_ctf_score()) / (1.0 - get_min_ctf_score())
)
raw_conf = (
    0.35 * cvd_z_score
    + 0.30 * price_fail_score
    + 0.20 * hmm_mean_reversion_score
    + 0.15 * ctf_score_factor  # <-- ECL violation
)
```
Note: the actual current delta_exhaustion.py weights are `0.35/0.30/0.20/0.15` not `0.30/0.25/0.20/0.10` as shown in the spec's BEFORE block. The AFTER rebalance is `0.35/0.30/0.25/0.10`.

**In `microstructure_utils.detect_spike_signal` (CONFIRMED from source):**
```python
ctf_score = float(features.get("ctf_score") or 0.0)
if abs(ctf_score) < get_min_ctf_score():
    return no_signal()
...
ctf_factor = clamp01((abs(ctf_score) - get_min_ctf_score()) / (1.0 - get_min_ctf_score()))
raw = 0.45 * z_score_score + 0.25 * volume_score + 0.20 * ctf_factor + 0.10 * persistence_score
```
This is the exact code to replace per spec. The function uses `make_signal_from_frame` (not `emit_signal`) and sets `signal["features_snapshot"]` directly.

### Zone Friction Gate (CONFIRMED from source)

**`supply_demand_setup.py` does NOT have a `zone_friction` emission gate.** The plugin has:
- Gate 1: must be in demand or supply zone (`in_demand_zone`, `in_supply_zone`)
- Gate 2: not both zones
- Gate 3: freshness threshold (`freshness < self.MIN_FRESHNESS`)

**Zero `zone_friction` references found** in any trading plugin file (`grep -rn "zone_friction\|friction_score" src/intelligence/trading/` returned empty). The zone_friction field is an ECL annotation that will be added to the schema (as nullable), but there are NO existing zone_friction gates to remove. The `grep` from the spec's A5a step will return zero hits immediately.

### Exhaustion Guard (CONFIRMED from source)

`apply_exhaustion_guard()` in `exhaustion_utils.py` is a **confidence penalty modifier** (`confidence -= 0.15`), NOT an emission suppressor. It does not call `no_signal()`. Used in `mtf_alignment`, `second_leg_continuation`, `regime_transition`, `vcp`. These remain as-is - they are confidence adjustments, not emission gates, and do not violate the ECL boundary invariant.

### `_PHASE_119_PLUGINS` Frozenset (CONFIRMED from source)

Defined at `register_plugins.py:688-710`. Contains exactly 17 plugin names. Imported in two test files:
- `tests/unit/intelligence/test_i7_extrinsic_contract.py` - uses it for gate exemption logic and count assertion
- `tests/unit/intelligence/test_i6_confluence_enforcement.py` - uses it for `shadow_only=True` parametrized test

Both test files must be updated when `_PHASE_119_PLUGINS` is deleted from `register_plugins.py`.

### Architecture Doc (CONFIRMED from source)

`docs/architecture/setup-confidence-patterns.md` already exists with the correct filename (rename already done). The file currently has:
- Pattern 3 still documents the CTF gate pattern as a GOOD pattern (needs updating to ECL annotation)
- Pattern Vocabulary table does not yet distinguish EXTRINSIC CONFIDENCE VECTOR (ECL) from confidence factors for `ctf_score`/`zone_friction_score`
- The ECL section referenced in CONTEXT.md Wave C spec does not yet exist in the doc
- Cross-references in `src/intelligence/CLAUDE.md` and `docs/ideas/signal-07-signal-ranker.md` already use `setup-confidence-patterns.md` (correct)
- `docs/foundation/glossary.md` already references `setup-confidence-patterns.md` and mentions ECL fields

### Signal Writer (`services/signal_writer.py`)

**Current `LedgerEntry` construction in `_payload_to_ledger_entries`:** Builds `LedgerEntry` with 24 fields. Does NOT include `ctf_score`, `ctf_confirmed`, `zone_friction_score`, `factor_scores`, or `context_features`. The `LedgerEntry` dataclass (in `signal_ledger_repository.py`) also does not have these fields.

**Key decision point (Claude's Discretion):** Whether to add these 5 fields to `LedgerEntry` + `_INSERT_SQL` now (Phase 123) or defer to Phase 128. The CONTEXT.md flags this as discretion. The spec's A6a says "These fields land on `signal_events` in the 3-table migration (Phase 128). For now they map to the new columns added in migration A1." This implies a DB migration is needed to add the columns to `signal_ledger` - but the CONTEXT.md defers DB migration to Phase 128. **Resolution: add the 5 fields to the Kafka payload (signal schema + `REQUIRED_PIPELINE_FIELDS`) and to `LedgerEntry`/`_INSERT_SQL` in this phase, but require a DB migration for `signal_ledger` columns. Whether to include that migration in Phase 123 or treat it as a Phase 128 prep task needs a call.**

---

## Architecture Patterns

### Wave A Dependency Chain

The correct sequencing within Wave A matters because of the `REQUIRED_PIPELINE_FIELDS` gate:

```
1. signal_schema.py: Add SIGNAL_SCHEMA_VERSION + 5 new fields to REQUIRED_PIPELINE_FIELDS
   → This immediately causes all signals missing new fields to be DLQ'd
   → Must be done LAST in Wave A, not first, OR add fields with {} defaults before the gate
2. plugin_utils.py + signal_schema.py: Thread new params through emit_signal/make_signal_from_frame
3. confidence_utils.py: Fix or 0.0 → None in capture_signal_features
4. microstructure_utils.py: Strip CTF gate + composite (A4)
5. delta_exhaustion.py: Strip CTF composite (A3)  
6. All 17 _PHASE_119_PLUGINS: CTF gate removal (A5)
7. supply_demand_setup.py: zone_friction audit (A5a - expect no gates found)
8. All capture_signal_features callsites: promote context_features (A6a File 2)
9. signal_processor.py: context_features injection (A6a File 3 - actually in signal_writer/LedgerEntry)
10. register_plugins.py: Delete _PHASE_119_PLUGINS (A7)
11. Tests: Fix assertions (A8)
12. REQUIRED_PIPELINE_FIELDS: Add 5 new fields (A1b - safe now that all plugins emit them)
```

The critical insight: `REQUIRED_PIPELINE_FIELDS` addition (A1b) must come AFTER all plugins have been updated to emit the new fields, or all signals will be DLQ'd. The schema type additions (A1) are safe at any point since they only define what's allowed, not required.

### The Three-File Change for context_features

The promotion of `context_features` from ephemeral to persisted requires:
1. `confidence_utils.py`: The function already returns the dict. Add backward-compat: keep returning it, callers just weren't capturing it as `context_features`.
2. Every plugin's `compute_full()`: Capture return value as `signal["context_features"]` instead of (or in addition to) `signal["features_snapshot"]`.
3. `signal_writer.py`: Read `context_features` from Kafka payload and pass to `LedgerEntry`.

**Note on `features_snapshot`:** The existing `features_snapshot` field in signal dicts maps to `features_snapshot` in `make_signal_from_frame()`. The new `context_features` is a parallel top-level field. The Phase 123 approach is to set BOTH - `features_snapshot` for backward compat and `context_features` as the new canonical field.

### Plugin Modification Pattern

For each of the 17 `_PHASE_119_PLUGINS`, the transform is:

```python
# REMOVE (the gate):
ctf_score = float(features.get("ctf_score") or 0.0)
if abs(ctf_score) < get_min_ctf_score():
    return no_signal()

# ADD (ECL annotation):
_ctf_raw = features.get("ctf_score")
ctf_score: float | None = float(_ctf_raw) if _ctf_raw is not None else None
ctf_confirmed: bool | None = (abs(ctf_score) >= get_min_ctf_score()) if ctf_score is not None else None

# PASS to emit_signal (via kwargs or explicit):
# ctf_score=ctf_score, ctf_confirmed=ctf_confirmed
```

For plugins using `make_signal_from_frame` directly (most do), same pattern but pass to `make_signal_from_frame` call.

For `delta_exhaustion.py` and `microstructure_utils.detect_spike_signal`, additionally remove `ctf_score_factor` from the composite and rebalance weights.

### `capture_signal_features` Callsite Update Pattern

37 callsites total. Two forms exist:

```python
# Form 1 (inside make_signal_from_frame) — becomes:
ctx = capture_signal_features(features, direction, "smc", confidence)
signal = make_signal_from_frame(..., features_snapshot=ctx, context_features=ctx)

# Form 2 (after make_signal_from_frame) — becomes:
signal = make_signal_from_frame(...)
ctx = capture_signal_features(features, direction, "microstructure", signal["confidence"])
signal["features_snapshot"] = ctx
signal["context_features"] = ctx
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Null-safe float extraction | Custom None-check boilerplate | The established pattern: `_raw = features.get(key); val = float(_raw) if _raw is not None else None` | Already in use for ctf sub-scores in capture_signal_features; same pattern everywhere |
| Signal dict validation | Custom field presence checks | `REQUIRED_PIPELINE_FIELDS` gate in `signal_processor.prepare_signals_or_dlq` | Already enforced at publish boundary |
| Test signal construction | Manual dict building | Existing test factories + add `"factor_scores": {}, "context_features": {}` defaults | All existing scenarios fire correctly; just add the new fields |

---

## Common Pitfalls

### Pitfall 1: REQUIRED_PIPELINE_FIELDS Added Too Early
**What goes wrong:** Adding the 5 new fields to `REQUIRED_PIPELINE_FIELDS` before all 37 plugins emit them causes every signal to be DLQ'd at the pipeline boundary (`signal_processor.prepare_signals_or_dlq`).
**Why it happens:** The terminal boundary check drops any signal missing pipeline fields. New fields in the frozenset become required immediately.
**How to avoid:** Add the new fields to `REQUIRED_PIPELINE_FIELDS` as the LAST Wave A step, after all plugins have been updated to emit `factor_scores={}` (even if empty) and `context_features` is populated.
**Warning signs:** All signals vanishing to DLQ after A1b commit; signal_writer showing zero ingestion.

### Pitfall 2: `emit_signal` vs `make_signal_from_frame` - Two Separate Functions
**What goes wrong:** `emit_signal` in `plugin_utils.py` uses `**signal_fields` to pass extra kwargs to `make_signal_from_frame`. But `make_signal_from_frame` in `signal_schema.py` has explicit parameters only - it does NOT accept `**kwargs`. Passing new fields through `emit_signal`'s `**signal_fields` will silently fail unless `make_signal_from_frame` also explicitly declares the new parameters.
**Why it happens:** The functions are in different files and the `**` forwarding is not obvious.
**How to avoid:** Add explicit named parameters to BOTH functions. In `make_signal_from_frame`, add `ctf_score: float | None = None, ctf_confirmed: bool | None = None, zone_friction_score: float | None = None, factor_scores: dict | None = None, context_features: dict | None = None` and assign them to the signal dict inside `_make_signal` or directly on `sig`.

### Pitfall 3: `_PHASE_119_PLUGINS` Deletion Blast Radius
**What goes wrong:** Two test files import `_PHASE_119_PLUGINS`. Deleting the frozenset from `register_plugins.py` without updating both test files causes `ImportError` at pytest collection time.
**Why it happens:** `test_i6_confluence_enforcement.py` uses it for shadow_only parametrize test; `test_i7_extrinsic_contract.py` uses it for gate exemption logic and a count assertion test.
**How to avoid:** After deleting `_PHASE_119_PLUGINS`, run `grep -rn "_PHASE_119_PLUGINS" src/ tests/` - must be zero hits. Both test files need substantial rework: the count test disappears, the ctf perturbation exemption logic changes, and the shadow_only test must be replaced with a different list.

### Pitfall 4: Zone Friction Gate Does Not Exist
**What goes wrong:** Spending time searching for `zone_friction.*no_signal()` patterns in plugin files - they do not exist. The grep returns zero hits.
**Why it happens:** The zone_friction gate described in spec docs was never actually implemented as an emission suppressor in supply_demand_setup.py. The plugin gates on zone membership and freshness, not friction score.
**How to avoid:** Run the grep immediately; expect zero hits; add `zone_friction_score: float | None = None` to the schema and emit it (reading from `features.get("zone_friction_score")`), but skip the "gate removal" step since there is no gate.

### Pitfall 5: `capture_signal_features` Already Returns a Dict
**What goes wrong:** The spec's A6a says "Change capture_signal_features() from writing to sig['_shadow'] to returning the dict". This is already done - the function already returns a dict. Implementing a no-op change and wasting time.
**Why it happens:** The spec was written against an older version of the code.
**How to avoid:** Verify the current function signature. The only change needed is (1) fix the `or 0.0` fallbacks (A2), and (2) update callsites to capture the return value as `signal["context_features"]` in addition to `signal["features_snapshot"]`.

### Pitfall 6: `signal_schema_version` is Text, Not Int
**What goes wrong:** Creating `SIGNAL_SCHEMA_VERSION` as an integer (e.g., `3`) when the DB column `signal_schema_version` is `text` type in `signal_ledger`. Causes type mismatch at INSERT.
**Why it happens:** The spec says "increment by 1" implying integer, but historical usage was text strings (`"v1"`, `"v2"`).
**How to avoid:** Check migration 081 and 095 - column is `text NOT NULL`. The constant should be a text string. Given prior `"v1"`, `"v2"` naming, the new value should be `"v3"`. Alternatively, since `signal_ledger` is being dropped in Phase 129, a pragmatic choice is acceptable - just be consistent. The constant exists primarily to version the Kafka payload format. If `LedgerEntry` is not updated in Phase 123, the DB type mismatch doesn't arise yet.

### Pitfall 7: Architecture Doc Has Already Been Renamed
**What goes wrong:** Running `git mv docs/architecture/i7-setup-confidence-patterns.md docs/architecture/setup-confidence-patterns.md` when the target already exists (the rename was done in a prior commit).
**Why it happens:** The file already exists at `docs/architecture/setup-confidence-patterns.md`.
**How to avoid:** Wave C only needs the content update (ECL section, Pattern Vocabulary, Pattern 3 language). The `git mv` step is complete. Verify with `ls docs/architecture/` before running the mv command.

---

## Code Examples

### CTF Gate Removal Pattern (verified against delta_exhaustion.py)

```python
# BEFORE (in delta_exhaustion.py Gate 2):
ctf_score = float(features.get("ctf_score") or 0.0)
if abs(ctf_score) < get_min_ctf_score():
    return no_signal()

# AFTER (ECL annotation):
_ctf_raw = features.get("ctf_score")
ctf_score: float | None = float(_ctf_raw) if _ctf_raw is not None else None
ctf_confirmed: bool | None = (abs(ctf_score) >= get_min_ctf_score()) if ctf_score is not None else None
# No return no_signal() - signal always fires if intrinsic criteria met
```

### delta_exhaustion.py Composite Rebalance (verified against current code)

```python
# CURRENT (weights: 0.35/0.30/0.20/0.15):
raw_conf = (
    0.35 * cvd_z_score
    + 0.30 * price_fail_score
    + 0.20 * hmm_mean_reversion_score
    + 0.15 * ctf_score_factor  # REMOVE THIS
)

# AFTER (weights: 0.35/0.30/0.25/0.10, per spec):
raw_conf = (
    0.35 * cvd_z_score
    + 0.30 * price_fail_score
    + 0.25 * hmm_mean_reversion_score
    + 0.10 * persistence_score  # ADD persistence_score (already computed earlier in the method)
)
```

Note: `delta_exhaustion.py` does not currently compute a `persistence_score`. The spec says rebalance to `0.35*exhaustion + 0.30*momentum_reversal + 0.25*volume + 0.10*persistence`. The current factors are `cvd_z_score`, `price_fail_score`, `hmm_mean_reversion_score`, `ctf_score_factor`. A mapping is needed: `exhaustion=cvd_z_score`, `momentum_reversal=price_fail_score`, `volume=?`, `persistence=?`. The plugin does not compute a volume or persistence score currently. The spec's rebalanced formula may need a literal interpretation - the implementer must decide which existing factor maps to "volume" and "persistence" or add new score computations.

### microstructure_utils.detect_spike_signal Rebalance (verified against current code)

```python
# CURRENT (0.45/0.25/0.20/0.10 with ctf_factor):
ctf_factor = clamp01((abs(ctf_score) - get_min_ctf_score()) / (1.0 - get_min_ctf_score()))
raw = 0.45 * z_score_score + 0.25 * volume_score + 0.20 * ctf_factor + 0.10 * persistence_score

# AFTER (0.50/0.30/0.20 per spec):
raw = 0.50 * z_score_score + 0.30 * volume_score + 0.20 * persistence_score
```

### context_features Promotion Callsite Update

```python
# BEFORE (in most plugins, inside make_signal_from_frame call):
return make_signal_from_frame(
    tf, ...,
    features_snapshot=capture_signal_features(features, direction, "smc", confidence),
)

# AFTER:
ctx = capture_signal_features(features, direction, "smc", confidence)
return make_signal_from_frame(
    tf, ...,
    features_snapshot=ctx,
    context_features=ctx,
)
```

### make_signal_from_frame Extension

```python
# In signal_schema.py, new parameters to make_signal_from_frame:
def make_signal_from_frame(
    tf: TradeFrame,
    *,
    # ... existing params ...
    ctf_score: float | None = None,
    ctf_confirmed: bool | None = None,
    zone_friction_score: float | None = None,
    factor_scores: dict | None = None,
    context_features: dict | None = None,
) -> dict:
    # ... existing logic ...
    # After building sig dict, add new fields:
    sig["ctf_score"] = ctf_score
    sig["ctf_confirmed"] = ctf_confirmed
    sig["zone_friction_score"] = zone_friction_score
    sig["factor_scores"] = factor_scores if factor_scores is not None else {}
    sig["context_features"] = context_features if context_features is not None else {}
    return sig
```

### factor_scores Collection Pattern (Wave B)

```python
# BEFORE:
raw = 0.40 * factor_a + 0.30 * factor_b + 0.20 * factor_c + 0.10 * factor_d
confidence = compose_confidence(raw)

# AFTER:
factor_scores = {
    "factor_a_name": round(factor_a, 4),
    "factor_b_name": round(factor_b, 4),
    "factor_c_name": round(factor_c, 4),
    "factor_d_name": round(factor_d, 4),
}
raw = 0.40 * factor_a + 0.30 * factor_b + 0.20 * factor_c + 0.10 * factor_d
confidence = compose_confidence(raw)
# Pass factor_scores=factor_scores to emit_signal/make_signal_from_frame
```

### Test Updates - Extrinsic Contract

```python
# BEFORE (test_i7_extrinsic_contract.py, ctf perturbation logic):
perturbation_keys = {
    k: v
    for k, v in _EXTRINSIC_KEYS.items()
    if not (k == "ctf_score" and plugin_name in _PHASE_119_PLUGINS)
}

# AFTER (ctf_score is now always perturbable - no gate exemption):
perturbation_keys = copy.deepcopy(_EXTRINSIC_KEYS)
# ctf_score perturbing to 0.9 must NOT change confidence for ANY plugin

# REMOVE: test_phase_119_plugins_count() entirely

# UPDATE: test_extrinsic_still_captured_in_features_snapshot
# The test currently checks features_snapshot["ctf_score"]
# After Phase 123, also check signal["context_features"]["ctf_score"]
```

---

## State of the Art

| Old Approach | Current Approach | Changed | Impact |
|---|---|---|---|
| CTF gate as emission suppressor in 17 plugins | CTF as ECL annotation, always emits | Phase 123 | Eliminates Bias Layer 1; all signals reach training corpus |
| `or 0.0` fallback conflates cold-start with neutral | `None` for no data, `0.0` for genuine neutral | Phase 123 | ML can distinguish cold-start from neutral alignment |
| `capture_signal_features` output in `features_snapshot` only | Also in top-level `context_features` field | Phase 123 | SignalRanker training data preserved in Kafka payload |
| Factor scores as local variables that die at function return | `factor_scores` dict persisted to signal schema | Phase 123 | APR ML weight optimization becomes possible in v2.11 |
| `_PHASE_119_PLUGINS` frozenset tracking gate-having plugins | Category dissolved; no plugins have CTF gates | Phase 123 | Single plugin tier, no exception tracking |

**Architecture doc rename:** `i7-setup-confidence-patterns.md` -> `setup-confidence-patterns.md` was already completed before this phase.

---

## Open Questions

1. **`delta_exhaustion.py` rebalance - which factors map to "volume" and "persistence"?**
   - What we know: spec says `0.35*exhaustion + 0.30*momentum_reversal + 0.25*volume + 0.10*persistence`
   - What's unclear: the current plugin doesn't have distinct volume or persistence scores. Needs either: (a) compute `volume_score = rel_volume_score(features)` and `persistence_score = 0.3` (from microstructure pattern), or (b) use only the 3 existing intrinsic scores and rebalance to 3 factors
   - Recommendation: Add `volume_score = rel_volume_score(features)` (already used in microstructure_utils) and use `persistence_score = clamp01(abs(cvd_spike_z) / 3.0)` as proxy, or pick the 3-factor interpretation. The spirit is clear; exact factoring is implementation discretion.

2. **`SIGNAL_SCHEMA_VERSION` - text or integer, what value?**
   - What we know: DB column is `text NOT NULL` in `signal_ledger`. Historical values were `"v1"`, `"v2"`.
   - What's unclear: Should Phase 123 use `"v3"` (text) or start fresh with integer `3`? The constant doesn't exist in `signal_schema.py` yet, so there's no prior value to increment.
   - Recommendation: Use `"v3"` as a text constant to match the DB column type and historical pattern. Document in `signal_schema.py` that integer semantics are intended but text type is preserved for DB compat until Phase 128 drops `signal_ledger`.

3. **Should LedgerEntry / `_INSERT_SQL` be updated in Phase 123?**
   - What we know: The 5 new fields need to be in the Kafka payload (done via REQUIRED_PIPELINE_FIELDS). They also need to land in DB storage eventually (Phase 128 `signal_events` table). The current `signal_ledger` doesn't have these columns.
   - What's unclear: Should Phase 123 add these columns to `signal_ledger` + `LedgerEntry` now (requires a DB migration), or defer entirely to Phase 128?
   - Recommendation: Defer `LedgerEntry` and DB column changes to Phase 128. Phase 123 establishes the Kafka payload fields. `signal_writer.py` can read them from the payload but drop them for now (or log them as metadata). This avoids a DB migration in Phase 123, which is already high-blast-radius.

4. **`test_i6_confluence_enforcement.py` shadow_only test needs replacement**
   - What we know: Line 104 parametrizes over `sorted(_PHASE_119_PLUGINS)` to test `shadow_only=True`. After deletion, the parametrize source is gone.
   - Recommendation: Replace parametrize source with `TIER_I7` (all I7 plugins) - but then need to know which plugins have `shadow_only=True`. Alternatively, keep the test as-is but import from a new constant, or delete the test since Phase 120 was supposed to have promoted plugins already.

---

## Sources

### Primary (HIGH confidence)
- Source code inspection: `src/intelligence/trading/signal_schema.py` - REQUIRED_PIPELINE_FIELDS, make_signal_from_frame
- Source code inspection: `src/intelligence/trading/plugin_utils.py` - emit_signal signature
- Source code inspection: `src/intelligence/trading/confidence_utils.py` - capture_signal_features current behavior
- Source code inspection: `src/intelligence/trading/microstructure_utils.py` - CTF gate + composite
- Source code inspection: `src/intelligence/trading/delta_exhaustion.py` - CTF gate + composite
- Source code inspection: `src/intelligence/trading/supply_demand_setup.py` - confirmed no zone_friction gate
- Source code inspection: `src/intelligence/trading/exhaustion_utils.py` - confirmed penalty modifier, not emission suppressor
- Source code inspection: `src/intelligence/register_plugins.py:688-710` - _PHASE_119_PLUGINS frozenset
- Source code inspection: `src/intelligence/pipeline/signal_processor.py` - REQUIRED_PIPELINE_FIELDS usage at terminal boundary
- Source code inspection: `services/signal_writer.py` - LedgerEntry construction, no ECL fields
- Source code inspection: `tests/unit/intelligence/test_i7_extrinsic_contract.py` - test assertions to flip
- Source code inspection: `tests/unit/intelligence/test_i6_confluence_enforcement.py` - second _PHASE_119_PLUGINS importer
- Source code inspection: `docs/architecture/setup-confidence-patterns.md` - confirmed rename done, ECL content missing
- Bash grep: zone_friction search - zero hits confirmed
- Bash grep: exhaustion_guard search - confirmed penalty modifier not gate

### Secondary (MEDIUM confidence)
- `.planning/phases/123-ecl-boundary-restoration/123-CONTEXT.md` - locked implementation decisions
- `docs/plans/2026-06-14-v2.10-signal-architecture-refactor.md` - master spec with exact code blocks
- `.planning/REQUIREMENTS.md` - ECL-01, ECL-02, ECL-03 requirements

---

## Metadata

**Confidence breakdown:**
- Wave A gate removal scope: HIGH - all CTF gates found, zone_friction absence confirmed, exhaustion guard non-suppressor confirmed
- Wave A schema changes: HIGH - current REQUIRED_PIPELINE_FIELDS confirmed, threading path clear
- Wave A capture_signal_features: HIGH - function already returns dict, only callsite update needed
- Wave B factor_scores: HIGH - pattern is straightforward, 37 plugins all follow same structure
- Wave C doc update: HIGH - file exists, content gaps identified

**Research date:** 2026-06-14
**Valid until:** 2026-08-14 (stable codebase; no external dependencies)
