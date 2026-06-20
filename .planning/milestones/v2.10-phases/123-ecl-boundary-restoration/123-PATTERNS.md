# Phase 123: ECL Boundary Restoration - Pattern Map

**Mapped:** 2026-06-14
**Files analyzed:** 14 canonical files + 37 plugin files (pattern groups)
**Analogs found:** 14 / 14 (all files have direct codebase analogs)

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/intelligence/trading/signal_schema.py` | schema/utility | transform | self (extension) | exact |
| `src/intelligence/trading/plugin_utils.py` | utility | transform | self (extension) | exact |
| `src/intelligence/trading/confidence_utils.py` | utility | transform | self (extension) | exact |
| `src/intelligence/trading/microstructure_utils.py` | utility | transform | `delta_exhaustion.py` (same CTF gate pattern) | exact |
| `src/intelligence/trading/delta_exhaustion.py` | plugin | CRUD | self (gate removal + rebalance) | exact |
| `src/intelligence/trading/supply_demand_setup.py` | plugin | transform | self (annotation add) | exact |
| 17 `_PHASE_119_PLUGINS` files | plugin | transform | `delta_exhaustion.py` | exact |
| ~20 non-PHASE_119 I7 plugin files | plugin | transform | `ofi_continuation.py` | exact |
| `src/intelligence/register_plugins.py` | config | transform | self (frozenset deletion) | exact |
| `src/intelligence/pipeline/signal_processor.py` | pipeline | request-response | self (extension) | exact |
| `services/signal_writer.py` | service/writer | CRUD | self (extension) | exact |
| `src/persistence/repository/signal_ledger_repository.py` | repository | CRUD | self (extension) | exact |
| `docs/architecture/setup-confidence-patterns.md` | doc | - | self (content update) | exact |
| `tests/unit/intelligence/test_i7_extrinsic_contract.py` | test | - | self (assertion flip) | exact |
| `tests/unit/intelligence/test_i6_confluence_enforcement.py` | test | - | self (import fix) | exact |

---

## Pattern Assignments

### GROUP A: Schema + Threading (`signal_schema.py`, `plugin_utils.py`)

**Analog:** `src/intelligence/trading/signal_schema.py` (self, lines 45-54 and 195-298)
**Analog:** `src/intelligence/trading/plugin_utils.py` (self, lines 201-265)

**Current `REQUIRED_PIPELINE_FIELDS`** (`signal_schema.py` lines 45-54):
```python
REQUIRED_PIPELINE_FIELDS = frozenset(
    {
        "signal_id",
        "status",
        "bar_id",
        "composite_rank",
        "raw_cis_score",
        "filtered_cis_score",
    }
)
```

**Target pattern — add 5 ECL fields** (MUST be added LAST in Wave A, after all plugins emit them):
```python
REQUIRED_PIPELINE_FIELDS = frozenset(
    {
        "signal_id",
        "status",
        "bar_id",
        "composite_rank",
        "raw_cis_score",
        "filtered_cis_score",
        # ECL fields — Phase 123. {} sentinel for absent-plugin, None for field-not-written.
        "ctf_score",
        "ctf_confirmed",
        "zone_friction_score",
        "factor_scores",
        "context_features",
    }
)
```

**Add `SIGNAL_SCHEMA_VERSION` constant** at top of `signal_schema.py` after imports:
```python
# Schema version for Kafka payload. DB column is text; historical: "v1", "v2".
SIGNAL_SCHEMA_VERSION: str = "v3"
```

**Current `make_signal_from_frame` signature** (`signal_schema.py` lines 195-211):
```python
def make_signal_from_frame(
    tf: TradeFrame,
    *,
    symbol: str,
    timeframe: str,
    timestamp: str,
    signal_type: str,
    setup_plugin: str,
    direction: int,
    confidence: float,
    regime_context: str,
    confluence_score: float = 0.0,
    supporting_factors: list[str],
    invalidation_conditions: list[str] | None = None,
    ttl_bars: int | None = None,
    features_snapshot: dict | None = None,
) -> dict:
```

**Target pattern — add 5 ECL params to `make_signal_from_frame`**:
```python
def make_signal_from_frame(
    tf: TradeFrame,
    *,
    # ... all existing params unchanged ...
    features_snapshot: dict | None = None,
    # ECL fields — Phase 123
    ctf_score: float | None = None,
    ctf_confirmed: bool | None = None,
    zone_friction_score: float | None = None,
    factor_scores: dict | None = None,
    context_features: dict | None = None,
) -> dict:
```

**Assignment block inside `make_signal_from_frame`** (after existing `sig["zone_source"]` and framing audit lines, lines ~284-298):
```python
# ECL fields — Phase 123 (after existing framing audit assignments)
sig["ctf_score"] = ctf_score
sig["ctf_confirmed"] = ctf_confirmed
sig["zone_friction_score"] = zone_friction_score
sig["factor_scores"] = factor_scores if factor_scores is not None else {}
sig["context_features"] = context_features if context_features is not None else {}
```

**`emit_signal` in `plugin_utils.py`** (lines 201-265) uses `**signal_fields` which passes through to `make_signal_from_frame`. Because `make_signal_from_frame` has explicit params only (no `**kwargs`), the 5 new ECL fields threaded via `emit_signal(**kwargs)` will be picked up by `make_signal_from_frame`'s new explicit params automatically — no change to `emit_signal`'s signature is required. The `**signal_fields` catch-all already forwards them.

**Verification:** After this change, `emit_signal(trade_frame, ctf_score=0.5, ctf_confirmed=True, ...)` forwards correctly to `make_signal_from_frame`.

---

### GROUP B: CTF Gate Removal Pattern (17 `_PHASE_119_PLUGINS`)

**Analog:** `src/intelligence/trading/delta_exhaustion.py` (lines 96-99 and 143-153)

This pattern repeats across all 17 Phase-119 plugins. The plugin list:
`ofi_spike`, `cvd_spike`, `ofi_divergence`, `failed_breakout`, `candlestick_pattern_setup`,
`session_extremes_setup`, `liquidity_hunt`, `delta_exhaustion`, `lvn_breakout`,
`vwap_reclaim`, `vwap_deviation`, `momentum_breakout`, `orb15`, `orb30`,
`second_leg_continuation`, `vcp`, `dual_divergence`

**Current gate pattern** (`delta_exhaustion.py` lines 96-99):
```python
# Gate 2: I6 ctf_score gate
ctf_score = float(features.get("ctf_score") or 0.0)
if abs(ctf_score) < get_min_ctf_score():
    return no_signal()
```

**Target ECL annotation pattern** (REMOVE the gate, REPLACE with):
```python
# ECL annotation: ctf_score is extrinsic context, not an emission gate (Phase 123)
_ctf_raw = features.get("ctf_score")
ctf_score: float | None = float(_ctf_raw) if _ctf_raw is not None else None
ctf_confirmed: bool | None = (abs(ctf_score) >= get_min_ctf_score()) if ctf_score is not None else None
# No return no_signal() — signal always fires if intrinsic criteria met
```

**Pass through to `make_signal_from_frame` / `emit_signal`**:
```python
signal = make_signal_from_frame(
    tf,
    # ... existing args ...
    ctf_score=ctf_score,
    ctf_confirmed=ctf_confirmed,
)
```

**Import change required** — most plugins already import `get_min_ctf_score` from `confidence_utils`. After gate removal, `get_min_ctf_score` is still needed for computing `ctf_confirmed`. No import change needed.

**EXEMPT:** `mtf_alignment` plugin — CTF is its intrinsic signal, not an ECL annotation. Do NOT apply this pattern there.

---

### GROUP C: CTF Composite Removal (`delta_exhaustion.py`)

**Analog:** `src/intelligence/trading/delta_exhaustion.py` (lines 129-154)

**Current composite** (lines 143-154):
```python
# ctf_score_factor: CTF alignment strength (above gate = meaningful)
ctf_score_factor = clamp01(
    (abs(ctf_score) - get_min_ctf_score()) / (1.0 - get_min_ctf_score())
)

# Weights sum to 1.0
raw_conf = (
    0.35 * cvd_z_score
    + 0.30 * price_fail_score
    + 0.20 * hmm_mean_reversion_score
    + 0.15 * ctf_score_factor
)
```

**Target pattern** (REMOVE `ctf_score_factor`, rebalance to 4 intrinsic factors):
```python
# Removed ctf_score_factor — CTF is ECL annotation, not composite factor (Phase 123)
# persistence_score proxy: how persistent the CVD spike magnitude was
persistence_score = clamp01(abs(cvd_spike_z) / 3.0)

# volume_score: relative volume expansion at exhaustion point
volume_score = rel_volume_score(features)

# Weights sum to 1.0: 0.35/0.30/0.25/0.10
raw_conf = (
    0.35 * cvd_z_score
    + 0.30 * price_fail_score
    + 0.25 * hmm_mean_reversion_score
    + 0.10 * persistence_score
)
```

**Import change for `delta_exhaustion.py`**: Add `rel_volume_score` to the `confidence_utils` import (it is already defined at `confidence_utils.py` line 65). The existing import block at lines 21-27 needs `rel_volume_score` added.

**factor_scores dict** (Wave B — same file):
```python
factor_scores = {
    "cvd_z_score": round(cvd_z_score, 4),
    "price_fail_score": round(price_fail_score, 4),
    "hmm_mean_reversion_score": round(hmm_mean_reversion_score, 4),
    "persistence_score": round(persistence_score, 4),
}
# Pass to make_signal_from_frame:
signal = make_signal_from_frame(..., ctf_score=ctf_score, ctf_confirmed=ctf_confirmed, factor_scores=factor_scores)
```

---

### GROUP D: CTF Composite Removal (`microstructure_utils.py`)

**Analog:** `src/intelligence/trading/microstructure_utils.py` (lines 82-111)

**Current composite** (lines 102-111):
```python
ctf_factor = clamp01((abs(ctf_score) - get_min_ctf_score()) / (1.0 - get_min_ctf_score()))

price_return_z = features.get("price_return_z")
if price_return_z is not None:
    persistence_score = clamp01(abs_spike_z / max(1.0, abs(float(price_return_z))) - 1.0)
else:
    persistence_score = 0.3

# Weights sum to 1.0
raw = 0.45 * z_score_score + 0.25 * volume_score + 0.20 * ctf_factor + 0.10 * persistence_score
```

**CTF gate** (lines 82-85):
```python
# Gate 2: I6 ctf_score gate — both gates precede any OHLCV access
ctf_score = float(features.get("ctf_score") or 0.0)
if abs(ctf_score) < get_min_ctf_score():
    return no_signal()
```

**Target pattern** (remove gate, remove `ctf_factor`, rebalance):
```python
# ECL annotation (Phase 123): ctf_score captured, not gated
_ctf_raw = features.get("ctf_score")
ctf_score: float | None = float(_ctf_raw) if _ctf_raw is not None else None
ctf_confirmed: bool | None = (abs(ctf_score) >= get_min_ctf_score()) if ctf_score is not None else None

# ... (keep existing atr + close logic) ...

# persistence_score: ratio of spike to price return z
price_return_z = features.get("price_return_z")
if price_return_z is not None:
    persistence_score = clamp01(abs_spike_z / max(1.0, abs(float(price_return_z))) - 1.0)
else:
    persistence_score = 0.3

# Weights sum to 1.0: 0.50/0.30/0.20 (ctf_factor removed)
raw = 0.50 * z_score_score + 0.30 * volume_score + 0.20 * persistence_score
confidence = compose_confidence(raw)
```

**Remove from imports in `microstructure_utils.py`**: `get_min_ctf_score` is no longer needed in the composite calculation but IS still needed for `ctf_confirmed` computation — keep the import.

**Pass ECL fields through**:
```python
signal = make_signal_from_frame(
    tf,
    # ... existing args ...
    ctf_score=ctf_score,
    ctf_confirmed=ctf_confirmed,
)
signal["features_snapshot"] = capture_signal_features(...)
signal["context_features"] = signal["features_snapshot"]
```

**factor_scores dict** (Wave B):
```python
factor_scores = {
    "z_score_score": round(z_score_score, 4),
    "volume_score": round(volume_score, 4),
    "persistence_score": round(persistence_score, 4),
}
```

---

### GROUP E: `confidence_utils.py` — Fix `or 0.0` Fallbacks

**Analog:** `src/intelligence/trading/confidence_utils.py` (lines 166-188)

**Current pattern** (lines 169-172) — `or 0.0` conflates cold-start with neutral:
```python
shadow: dict[str, Any] = {
    "profile": profile_name,
    "existing_confidence": round(existing_confidence, 4),
    "ctf_score": float(features.get("ctf_score", 0.0)),
    "ctf_trend_alignment": float(features.get("ctf_trend_alignment", 0.0)),
    "ctf_structure_alignment": float(features.get("ctf_structure_alignment", 0.0)),
    "ctf_regime_agreement": float(features.get("ctf_regime_agreement", 0.0)),
    "ctf_fvg_alignment": float(features.get("ctf_fvg_alignment", 0.0)),
    "ctf_ob_alignment": float(features.get("ctf_ob_alignment", 0.0)),
    ...
```

**Target pattern** — null-preserving extraction for all 8 CTF base fields:
```python
def _nullable_float(features: dict, key: str) -> float | None:
    """Null-preserving float extraction: None = absent, 0.0 = genuine neutral."""
    _raw = features.get(key)
    return float(_raw) if _raw is not None else None

shadow: dict[str, Any] = {
    "profile": profile_name,
    "existing_confidence": round(existing_confidence, 4),
    "ctf_score": _nullable_float(features, "ctf_score"),
    "ctf_trend_alignment": _nullable_float(features, "ctf_trend_alignment"),
    "ctf_structure_alignment": _nullable_float(features, "ctf_structure_alignment"),
    "ctf_regime_agreement": _nullable_float(features, "ctf_regime_agreement"),
    "ctf_fvg_alignment": _nullable_float(features, "ctf_fvg_alignment"),
    "ctf_ob_alignment": _nullable_float(features, "ctf_ob_alignment"),
    # ... I4 macro fields already use None-preserving pattern (lines 177-188) ...
```

**Note:** The I4 macro fields (lines 177-188) already use `features.get(key)` without `or 0.0` fallbacks — they are correct. Only the 6 CTF base fields in the initial dict literal need fixing. The `ctf_momentum_divergence`, `ctf_sr_confluence`, etc. block below (lines 192-228) also already uses null-preserving extraction.

**Exhaustion fields** (lines 225-232) also use `or 0.0` fallbacks and need fixing:
```python
# BEFORE:
shadow["exhaustion_score"] = float(features.get("exhaustion_score", 0.0))

# AFTER (null-preserving):
_exh_raw = features.get("exhaustion_score")
shadow["exhaustion_score"] = float(_exh_raw) if _exh_raw is not None else None
```

---

### GROUP F: `context_features` Promotion — All 37 Plugin Callsites

**Analog:** `src/intelligence/trading/ofi_continuation.py` (lines 177-192) — Form 1 (inline)
**Analog:** `src/intelligence/trading/microstructure_utils.py` (lines 129-143) — Form 2 (post-assign)

**Form 1 — inline inside `make_signal_from_frame` call** (current, e.g. `ofi_continuation.py` lines 177-192):
```python
signal = make_signal_from_frame(
    tf_result,
    symbol=frames.get("symbol", ""),
    timeframe=tf,
    timestamp=features.get("timestamp", ""),
    signal_type=sig_type,
    setup_plugin=self.name,
    direction=direction,
    confidence=confidence,
    regime_context=regime_context,
    supporting_factors=supporting,
    features_snapshot=capture_signal_features(
        features, direction, "microstructure", confidence
    ),
)
return signal
```

**Target Form 1** (capture return value into both `features_snapshot` AND `context_features`):
```python
ctx = capture_signal_features(features, direction, "microstructure", confidence)
signal = make_signal_from_frame(
    tf_result,
    symbol=frames.get("symbol", ""),
    timeframe=tf,
    timestamp=features.get("timestamp", ""),
    signal_type=sig_type,
    setup_plugin=self.name,
    direction=direction,
    confidence=confidence,
    regime_context=regime_context,
    supporting_factors=supporting,
    features_snapshot=ctx,
    context_features=ctx,
    # Phase 123: ECL annotations
    ctf_score=ctf_score,          # present in PHASE_119_PLUGINS; None in others if not computed
    ctf_confirmed=ctf_confirmed,
    factor_scores=factor_scores,  # Wave B: populated before this call
)
return signal
```

**Form 2 — post-assign** (current, e.g. `microstructure_utils.py` lines 129-143):
```python
signal = make_signal_from_frame(
    tf,
    symbol=..., timeframe=..., timestamp=...,
    signal_type=sig_type,
    setup_plugin=setup_plugin,
    direction=direction,
    confidence=confidence,
    regime_context=regime_context,
    supporting_factors=supporting,
)
signal["features_snapshot"] = capture_signal_features(
    features, direction, "microstructure", signal["confidence"]
)
return signal
```

**Target Form 2**:
```python
signal = make_signal_from_frame(
    tf,
    symbol=..., timeframe=..., timestamp=...,
    signal_type=sig_type,
    setup_plugin=setup_plugin,
    direction=direction,
    confidence=confidence,
    regime_context=regime_context,
    supporting_factors=supporting,
    ctf_score=ctf_score,
    ctf_confirmed=ctf_confirmed,
    factor_scores=factor_scores,
)
ctx = capture_signal_features(features, direction, "microstructure", signal["confidence"])
signal["features_snapshot"] = ctx
signal["context_features"] = ctx
return signal
```

**Key rule:** `features_snapshot` is preserved for backward compat. `context_features` is the new canonical field. Both point to the same dict object (no copy needed).

---

### GROUP G: `supply_demand_setup.py` — Zone Friction Annotation

**Analog:** `src/intelligence/trading/supply_demand_setup.py` (self, confirmed no gate exists)

Per RESEARCH.md: there are NO `zone_friction.*no_signal()` patterns to remove. The grep returns zero hits. The only change needed is adding `zone_friction_score` as a nullable annotation field:

**Addition at end of `compute_full()`** before `make_signal_from_frame`:
```python
# ECL annotation: zone_friction_score — captured, not gated (Phase 123)
_zf_raw = features.get("zone_friction_score")
zone_friction_score: float | None = float(_zf_raw) if _zf_raw is not None else None
```

**Pass to `make_signal_from_frame`**:
```python
signal = make_signal_from_frame(
    tf,
    ...,
    zone_friction_score=zone_friction_score,
)
```

---

### GROUP H: Factor Scores Pattern (Wave B — all 37 plugins)

**Analog:** `src/intelligence/trading/ofi_continuation.py` (lines 148-167) — shows the 4-factor composite that becomes `factor_scores`

**Current pattern** (compute factors, sum, no dict):
```python
magnitude_score = clamp01((abs(ofi_ewma) - mag_threshold) / max(1e-9, upper_ref - mag_threshold))
alignment_score = 1.0 if float(ofi_ewma5) * ofi_ewma > 0 else 0.3
persistence_score = clamp01((count - min_bars) / max(1, min_bars))
volume_score = clamp01((rel_vol - 1.0) / 1.5)

raw_conf = (
    0.40 * magnitude_score
    + 0.25 * alignment_score
    + 0.20 * persistence_score
    + 0.15 * volume_score
)
confidence = compose_confidence(raw_conf)
```

**Target pattern** (collect into `factor_scores` dict BEFORE compositing):
```python
magnitude_score = clamp01((abs(ofi_ewma) - mag_threshold) / max(1e-9, upper_ref - mag_threshold))
alignment_score = 1.0 if float(ofi_ewma5) * ofi_ewma > 0 else 0.3
persistence_score = clamp01((count - min_bars) / max(1, min_bars))
volume_score = clamp01((rel_vol - 1.0) / 1.5)

# Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
factor_scores = {
    "magnitude_score": round(magnitude_score, 4),
    "alignment_score": round(alignment_score, 4),
    "persistence_score": round(persistence_score, 4),
    "volume_score": round(volume_score, 4),
}

raw_conf = (
    0.40 * magnitude_score
    + 0.25 * alignment_score
    + 0.20 * persistence_score
    + 0.15 * volume_score
)
confidence = compose_confidence(raw_conf)
```

**Naming convention:** Key names are plugin-specific descriptive names, not generic `factor_N`. Values are `round(x, 4)` floats in [0, 1].

---

### GROUP I: `register_plugins.py` — `_PHASE_119_PLUGINS` Deletion

**Analog:** `src/intelligence/register_plugins.py` (lines 684-710)

**Current block** (lines 684-710):
```python
# Phase 119 refactored plugins: Wave-1 (8) + Wave-2 (9) = 17 total.
# These plugins have dual HMM+CTF gate, 4-factor confidence composites, shadow_only=True,
# and requires_i6_confluence=True. Used by test_i7_extrinsic_contract.py to exclude ctf_score
# from extrinsic perturbation (ctf_score is a gate for these plugins, not a perturbable extrinsic).
_PHASE_119_PLUGINS: frozenset[str] = frozenset(
    [
        # Wave-1: 8 plugins
        ofi_spike_plugin.name,
        ...
        dual_divergence_plugin.name,
    ]
)
```

**Target:** Delete the entire block (lines 684-710). No replacement constant needed — the category is dissolved in Phase 123; all I7 plugins are now uniform (no CTF gates).

**Blast radius check after deletion:**
```bash
grep -rn "_PHASE_119_PLUGINS" src/ tests/
```
Must return zero hits. Two test files import it; both must be updated before this deletion (see GROUP J and K).

---

### GROUP J: `test_i7_extrinsic_contract.py` — Assertion Flip

**Analog:** `tests/unit/intelligence/test_i7_extrinsic_contract.py` (self, lines 486-540)

**Three changes required:**

**Change 1 — Remove `_PHASE_119_PLUGINS` import** (line 33):
```python
# REMOVE:
from src.intelligence.register_plugins import _PHASE_119_PLUGINS
```

**Change 2 — Flip perturbation logic** (lines 505-509):
```python
# CURRENT (ctf_score excluded from perturbation for Phase-119 plugins):
perturbation_keys = {
    k: v
    for k, v in _EXTRINSIC_KEYS.items()
    if not (k == "ctf_score" and plugin_name in _PHASE_119_PLUGINS)
}

# TARGET (ctf_score is now always perturbable — no plugin has a CTF gate):
perturbation_keys = copy.deepcopy(_EXTRINSIC_KEYS)
# ctf_score=0.9 perturbation must NOT change confidence for ANY plugin
```

**Change 3 — Delete `test_phase_119_plugins_count()`** (lines 536-540):
```python
# DELETE entirely:
def test_phase_119_plugins_count():
    assert len(_PHASE_119_PLUGINS) == 17, (
        f"_PHASE_119_PLUGINS should have 17 members, got {len(_PHASE_119_PLUGINS)}: "
        f"{sorted(_PHASE_119_PLUGINS)}"
    )
```

**Change 4 — Extend `test_extrinsic_still_captured_in_features_snapshot`** (lines 564-597):
```python
# ADD assertion after existing features_snapshot check:
# Phase 123: context_features must also be populated
ctx = result.get("context_features", {})
assert ctx, "context_features must be populated (Phase 123)"
assert "ctf_score" in ctx, "ctf_score must appear in context_features"
assert ctx["ctf_score"] == pytest.approx(0.8), f"ctf_score in context_features must equal 0.8"
```

**Docstring update** — the module docstring (lines 1-24) references Phase 119 gate exemption logic. Update to reflect Phase 123 ECL dissolution.

---

### GROUP K: `test_i6_confluence_enforcement.py` — Import Fix

**Analog:** `tests/unit/intelligence/test_i6_confluence_enforcement.py` (self, lines 13-18)

**Current import** (line 15):
```python
from src.intelligence.register_plugins import (
    _I7_I6_EXEMPT,
    _PHASE_119_PLUGINS,
    TIER_I7,
    register_all_plugins,
)
```

**Target** (remove `_PHASE_119_PLUGINS`):
```python
from src.intelligence.register_plugins import (
    _I7_I6_EXEMPT,
    TIER_I7,
    register_all_plugins,
)
```

**Check for usage of `_PHASE_119_PLUGINS` in the file body** — per RESEARCH.md, the parametrize at line 104 uses `sorted(_PHASE_119_PLUGINS)`. That block needs a replacement parametrize source. Resolution per RESEARCH.md: use all TIER_I7 plugins that have `shadow_only=True`, or delete the test if Phase 120 already promoted them. Verify with:
```bash
grep -n "_PHASE_119_PLUGINS" tests/unit/intelligence/test_i6_confluence_enforcement.py
```

---

### GROUP L: `signal_writer.py` + `signal_ledger_repository.py` — ECL Field Handling

**Analog:** `services/signal_writer.py` (lines 168-240) — `_payload_to_ledger_entries`
**Analog:** `src/persistence/repository/signal_ledger_repository.py` (lines 54-180) — `LedgerEntry` + `_INSERT_SQL`

**Current `LedgerEntry` dataclass** (lines 54-98) — 24 fields, last is `calibrated_confidence`. No ECL fields.

**Current `_payload_to_ledger_entries`** pattern: reads specific fields from `sig`, builds `LedgerEntry(...)`. No ECL field reads.

**Decision from RESEARCH.md Open Question 3:** Defer `LedgerEntry` + `_INSERT_SQL` changes to Phase 128. Phase 123 only establishes the Kafka payload fields. `signal_writer.py` reads the new fields from payload but does NOT write them to DB yet.

**Target pattern for `signal_writer.py`** — read ECL fields from payload, log as metadata (no DB write yet):
```python
# In _payload_to_ledger_entries, after signal_id extraction:
# ECL fields — read for future Phase 128 DB write; logged for audit (Phase 123)
_ctf_score = sig.get("ctf_score")       # float | None
_ctf_confirmed = sig.get("ctf_confirmed")  # bool | None
_zone_friction_score = sig.get("zone_friction_score")  # float | None
_factor_scores = sig.get("factor_scores", {})  # dict, {} = plugin not yet updated
_context_features = sig.get("context_features", {})  # dict, {} = absent
# NOTE: These fields are persisted to signal_events in Phase 128.
# For Phase 123, they exist in the Kafka payload only.
```

**If any tests break expecting `LedgerEntry` to accept ECL fields**, add them as optional attrs with `None` defaults to `LedgerEntry` but WITHOUT adding them to `_to_row()` or `_INSERT_SQL`. This keeps the dataclass in sync with the signal dict without a DB migration.

---

### GROUP M: `signal_processor.py` — `context_features` Injection Point

**Analog:** `src/intelligence/pipeline/signal_processor.py` (lines 475-527) — `prepare_signals_or_dlq`

**The `context_features` field is populated at the plugin level** (GROUP F), not in `signal_processor.py`. The processor's role is the terminal `REQUIRED_PIPELINE_FIELDS` gate (lines 516-526).

**No structural change to `signal_processor.py`** is needed for Wave A. The processor will:
1. Accept signals with the new ECL fields (they pass through naturally via the signal dict)
2. Enforce `REQUIRED_PIPELINE_FIELDS` after Wave A's new fields are added to the frozenset

**The REQUIRED_PIPELINE_FIELDS check** (lines 516-519 — do not change the pattern):
```python
missing = REQUIRED_PIPELINE_FIELDS - set(sig.keys())
if missing:
    self._signal_dlq_total.add(1)
    SIGNAL_PROCESSOR_DLQ_TOTAL.add(1, {"reason": "pipeline_fields_missing"})
    self._logger.error(
        "signal_processor.pipeline_fields_missing",
        plugin=sig.get("setup_plugin", "unknown"),
        missing_fields=sorted(missing),
    )
    continue
```

This pattern already DLQs signals missing any `REQUIRED_PIPELINE_FIELDS` key. Adding `factor_scores` and `context_features` to the frozenset (GROUP A) is sufficient — no processor logic changes needed.

---

### GROUP N: Architecture Doc (`docs/architecture/setup-confidence-patterns.md`)

**Analog:** `docs/architecture/setup-confidence-patterns.md` (self — content update only, file exists)

Three content sections to update:
1. **Title / intro** — remove Phase 119 CTF gate as GOOD pattern; it is now an ECL anti-pattern
2. **Pattern Vocabulary table** — add row distinguishing `CONFIDENCE FACTOR` (intrinsic, in composite) from `EXTRINSIC CONFIDENCE VECTOR (ECL)` (annotated, not gated)
3. **Pattern 3** — update description: the CTF dual gate is no longer Pattern 3's "GOOD" example; instead, ECL annotation is the new pattern
4. **New ECL section** — define the ECL boundary invariant: "Only the HMM regime gate is permitted to suppress emission; all ECL vectors are annotations"

No `git mv` needed — file already exists at correct path per RESEARCH.md.

---

## Shared Patterns

### Null-Preserving Float Extraction
**Source:** `src/intelligence/trading/confidence_utils.py` + RESEARCH.md spec
**Apply to:** All CTF score reads in `_PHASE_119_PLUGINS`, `microstructure_utils.py`, `confidence_utils.py` CTF fields, `supply_demand_setup.py` zone_friction

```python
# Pattern: None = field absent; 0.0 = genuine neutral. Never use `or 0.0`.
_raw = features.get("ctf_score")
ctf_score: float | None = float(_raw) if _raw is not None else None
```

### Feature Dict Merge Pattern
**Source:** `src/intelligence/trading/delta_exhaustion.py` (lines 70-79), same in all I7 plugins
**Apply to:** All I7 plugins (already established, do not change)

```python
features = {
    **(frames.get("i1") or {}),
    **(frames.get("i2") or {}),
    **(frames.get("i3") or {}),
    **(frames.get("i4") or {}),
    **(frames.get("i5") or {}),
    **(frames.get("smc") or {}),
    **(frames.get("i6") or {}),
}
```

### Confidence Composition
**Source:** `src/intelligence/trading/confidence_utils.py` (line 77-93)
**Apply to:** All I7 plugins — unchanged by Phase 123, all composites still route through `compose_confidence()`

```python
confidence = compose_confidence(raw_conf)  # clamps to [0.0, 0.95], rounds to 4dp
```

### `clamp01` for Factor Scores
**Source:** `src/intelligence/trading/confidence_utils.py` (line 60-62)
**Apply to:** All Wave B `factor_scores` dict values — all factors must be pre-clamped before collection

```python
factor_scores = {
    "factor_name": round(clamp01(raw_factor), 4),  # always [0,1], always 4dp
}
```

---

## Ordering Invariant

**Wave A implementation order** (enforced by `REQUIRED_PIPELINE_FIELDS` blast radius):

1. `signal_schema.py` — add `SIGNAL_SCHEMA_VERSION` and 5 params to `make_signal_from_frame`; do NOT add to `REQUIRED_PIPELINE_FIELDS` yet
2. `confidence_utils.py` — fix `or 0.0` fallbacks (null-preserving extraction)
3. `microstructure_utils.py` — CTF gate removal + composite rebalance + ECL annotation
4. `delta_exhaustion.py` — CTF gate removal + composite rebalance + ECL annotation
5. All 17 `_PHASE_119_PLUGINS` (excluding delta_exhaustion already done) — CTF gate removal + ECL annotation
6. `supply_demand_setup.py` — zone_friction annotation (no gate to remove)
7. All 37 plugin callsites — `context_features` promotion (Form 1 and Form 2 patterns)
8. `tests/unit/intelligence/test_i6_confluence_enforcement.py` — remove `_PHASE_119_PLUGINS` import
9. `tests/unit/intelligence/test_i7_extrinsic_contract.py` — assertion flip + test deletion
10. `register_plugins.py` — delete `_PHASE_119_PLUGINS` frozenset
11. `signal_schema.py` — NOW add 5 new fields to `REQUIRED_PIPELINE_FIELDS` (safe: all plugins emit them)
12. `services/signal_writer.py` — read ECL fields from payload (no DB write)

**Wave B** (after Wave A green):
13. All 37 plugins — add `factor_scores` dict before composite, pass to `make_signal_from_frame`

**Wave C:**
14. `docs/architecture/setup-confidence-patterns.md` — content update

---

## No Analog Found

All files have close analogs in the codebase. No novel patterns are introduced that require RESEARCH.md reference patterns instead of codebase analogs.

| File / Pattern | Note |
|---|---|
| `SIGNAL_SCHEMA_VERSION = "v3"` | No prior constant in `signal_schema.py`; use text string per DB column type (text NOT NULL, historical: "v1", "v2") |
| `factor_scores` dict pattern | New pattern for Phase 123; naming convention established here (plugin-specific keys, `round(x, 4)` values) |

---

## Metadata

**Analog search scope:** `src/intelligence/trading/`, `src/intelligence/pipeline/`, `src/intelligence/register_plugins.py`, `services/signal_writer.py`, `src/persistence/repository/signal_ledger_repository.py`, `tests/unit/intelligence/`
**Files scanned:** 15 source files read in full; grep used to locate `_PHASE_119_PLUGINS`, `REQUIRED_PIPELINE_FIELDS`, `prepare_signals_or_dlq`
**Pattern extraction date:** 2026-06-14
