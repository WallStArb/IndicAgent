# Phase 32: Stop Architecture + Extended Divergence Stack - Research

**Researched:** 2026-03-17
**Domain:** Signal lifecycle, trade framing, divergence pattern detection, TimescaleDB schema migration
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**stop_basis Classification**
- All structural levels = `structure_snap`: demand zone, sweep level, OB bottom/top, swing low/high, S/R nearest support/resistance — any stop that landed on a structural level regardless of tier
- `garch_adaptive`: ATR fallback path when `garch_vol_regime` is present (0/1/2) — GARCH scaling always applied (0.8×/1.0×/1.35×)
- `atr_static`: ATR fallback path only when `garch_vol_regime` is missing/null — rare/dead-code path given I4 is always running
- Explicit 1.5×ATR proximity gate: structural stop must be within 1.5×ATR of the raw ATR fallback level to qualify as `structure_snap`; if outside that band, degrade to `garch_adaptive`
- FVG low added to stop hierarchy: `fvg_bottom` (longs) / `fvg_top` (shorts) added as a structural stop candidate in `trade_framer.py`
- `stop_basis` → `intelligence_features`: field must appear in the intelligence features written per bar

**stop_basis Feature Fields**
- `stop_structure_type`: `"ob_bottom"` | `"ob_top"` | `"demand_zone"` | `"supply_zone"` | `"sweep_level"` | `"swing_low"` | `"swing_high"` | `"sr_support"` | `"sr_resistance"` | `"fvg_low"` | `"fvg_high"` | `"atr_fallback"`
- `stop_structure_age_bars`: bars since the structural level was established
- `structural_stop_distance_atr`: `abs(structural_stop - atr_fallback_stop) / atr`
- All three fields logged in both `signal_ledger` and `intelligence_features`

**Chandelier Trailing Stop (SIG-03)**
- Volatility source: `garch_sigma` preferred over ATR-14; ATR-14 as fallback when GARCH unavailable
- `chandelier_vol_source`: `"garch_sigma"` | `"atr_14"` — logged per signal as training feature
- Formula: `highest_high_since_entry - 3×vol` (long); `lowest_low_since_entry + 3×vol` (short); stop tightens monotonically, never widens
- `trailing_stop_price` in `signal_ledger`: JSONB array `[{ts, price}]` — full tightening history, not scalar overwrite
- `trailing_stop_tightening_rate`: slope of last 5 bars of trailing stop movement — pre-computed scalar
- `highest_high_since_entry` / `lowest_low_since_entry`: tracked per signal in lifecycle state from activation bar

**Staleness Score + condition_expired (SIG-04)**
- Primary trigger: HMM regime flip — `hmm_regime` at current bar ≠ `hmm_regime_at_fire`
- Secondary trigger: `sigma_drift_ratio = current_garch_sigma / garch_sigma_at_fire` > 2.0×
- `staleness_score`: composite 0.0–1.0 per bar; computed and logged per bar for every active signal
- Confirmation window: `condition_expired` fires when `staleness_score > threshold for 3 consecutive bars`
- `staleness_trigger_reason`: `"hmm_regime_flip"` | `"vol_drift"` | `"both"`
- Termination: signal terminated immediately as `condition_expired`
- Shadow tracking: when `condition_expired` fires, set `shadow_tracking_start_ts`; continue tracking `shadow_mae`, `shadow_mfe`, `shadow_outcome` for remaining TTL
- Fields added to `signal_ledger`: `shadow_tracking_start_ts`, `shadow_mae`, `shadow_mfe`, `shadow_outcome`
- At signal fire: store `hmm_regime_at_fire` and `garch_sigma_at_fire` in `signal_ledger`

**Divergence Stack — 5-Input Weighted Convergence Score (DIV-04)**
- Full replacement of AND-gate (overrides the "LOCKED DESIGN" docstring)
- Initial weights: RSI=0.30, MACD=0.25, Volume=0.20, OBV=0.15, CMF=0.10
- Weights stored in config (not hardcoded); tunable without code deploy
- Regime-conditioned weights: separate weight sets per `hmm_regime` (0/1/2); initially all regimes use same weights
- Gate: `weighted_score > 0.40 AND n_agreeing >= 3`
- Log every bar: `div_weighted_score`, `div_n_agreeing`, per-input scores always logged
- Per-input feature fields logged every bar: `{input}_divergence_age_bars`, `{input}_divergence_magnitude`

**Three New I5 Divergence Plugins**
- DIV-01: `macd_divergence.py` — peak/trough detection matching `rsi_divergence.py`; consumes `macd_histogram_12_26_9`; outputs `macd_div_bullish`, `macd_div_bearish`, `macd_div_strength`
- DIV-02: Extend `volume_divergence.py` (NOT new plugin): add `obv_div_bullish`, `obv_div_bearish`, `obv_div_strength` alongside existing `vol_div_*`
- DIV-03: `cmf_divergence.py` — linear regression slope approach matching `volume_divergence.py`; consumes `cmf_20`; outputs `cmf_div_bullish`, `cmf_div_bearish`, `cmf_div_strength`
- `divergence_lookback_bars`: logged per plugin output for training sensitivity analysis
- All plugins compute and log on every bar regardless of signal fire

### Claude's Discretion
- Exact staleness score formula (weighting of regime drift vs sigma ratio components)
- Exact `structural_stop_distance_atr` implementation in trade_framer (verify epsilon handling)
- JSONB array append vs separate trailing stop history table (if JSONB write contention arises at scale)
- Exact config format for regime-conditioned divergence weights (nested dict vs DB table)
- `divergence_age_bars` reset condition (reset to 0 when divergence flips direction vs decays below threshold)

### Deferred Ideas (OUT OF SCOPE)
- None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SIG-01 | `trade_framer.py` structure-first stop placement: tries structural levels (OB low, demand zone boundary, swing low, FVG low) within 1.5×ATR of ATR fallback; `stop_basis` field logged in `signal_ledger` | `_resolve_stop_long/short()` in `trade_framer.py` is the exact extension point; `TradeFrame` dataclass gains `stop_basis` and metadata fields |
| SIG-02 | All 17 I7 plugins inherit GARCH-adaptive ATR scaling via centralized `trade_framer.py`; `garch_vol_regime` 0→0.8×, 1→1.0×, 2→1.35× | `frame_trade()` reads `features` dict which already contains `garch_vol_regime` from I4; no per-plugin changes needed |
| SIG-03 | Chandelier Exit trailing stop in `lifecycle_tracker.py`; logged as `trailing_stop_price` per lifecycle update | `evaluate_signal()` signature needs extension: `highest_high`, `lowest_low` injected from service; `_check_active_exit()` adds Chandelier path |
| SIG-04 | Signal staleness score per bar; regime-flip or vol-drift triggers `condition_expired`; `hmm_regime_at_fire` and `garch_sigma_at_fire` stored at generation | Pure-function `evaluate_signal()` cannot read DB; staleness state injected from `signal_lifecycle_service._state` dict keyed by `signal_id` |
| SIG-05 | Time stop verified correct per TF; TTL values reviewed and documented as named constants per TF | Currently `ttl_bars` defaults to 10 in `signal_schema.py`; no per-TF named constants exist yet — research confirms this gap |
| DIV-01 | New I5 plugin `macd_divergence.py` | `rsi_divergence.py` pattern confirmed as template: `find_peaks/find_troughs` from `utils`, min_lookback=50, neighbor=5 |
| DIV-02 | Extend `volume_divergence.py` to add OBV divergence outputs | OBV already computed internally in `volume_divergence.py`; extend `outputs` frozenset + add to I5Patterns schema; `validate_schema_coverage()` will catch missing schema fields |
| DIV-03 | New I5 plugin `cmf_divergence.py` | `volume_divergence.py` linreg slope pattern confirmed; consumes `cmf_20` from I1 (verified in `I1Indicators`) |
| DIV-04 | Upgrade `divergence_stack.py` from 2-input AND-gate to 5-input weighted score | Current AND-gate reads `rsi_div_bullish/bearish` + `vol_div_bullish/bearish`; new version adds `macd_div_*`, `obv_div_*`, `cmf_div_*`; these flow as I5 features in `features` dict |
</phase_requirements>

---

## Summary

Phase 32 touches three distinct code areas: (1) `trade_framer.py` stop classification and GARCH multipliers, (2) `lifecycle_tracker.py` and `signal_lifecycle_service.py` for Chandelier trailing stops and staleness expiry, and (3) divergence plugin stack expansion. All three areas operate on already-established code patterns with no new external dependencies.

The stop architecture changes are purely additive: `frame_trade()` already resolves a structural stop and returns `stop_type`; Phase 32 adds a `stop_basis` label computed from `stop_type`, applies the 1.5×ATR proximity gate, injects the GARCH multiplier into the effective ATR before stop arithmetic, and adds FVG as a tier-0 candidate. The `TradeFrame` dataclass gains three new metadata fields. The `LedgerEntry` dataclass gains 14 new fields. Migration `035_stop_basis_and_divergence_stack.sql` is the next sequential migration.

The lifecycle changes are the most architecturally complex. `lifecycle_tracker.py` is pure (no DB, no state), so Chandelier tracking state (`highest_high_since_entry`, `trailing_stop_history`) and staleness counters (`staleness_consecutive_bars`) must live in `signal_lifecycle_service._state` dicts and be injected into `evaluate_signal()` as parameters. Shadow tracking after `condition_expired` requires a new service-side state machine: expired signals remain in memory with shadow tracking until their remaining TTL elapses.

The divergence expansion is mechanical: two new I5 plugins (`macd_divergence.py`, `cmf_divergence.py`), one extension to `volume_divergence.py`, `I5Patterns` schema additions (six new fields + OBV fields), and `divergence_stack.py` rewrite. The schema coverage check in `validate_schema_coverage()` will immediately catch any missed `I5Patterns` field.

**Primary recommendation:** Execute in three waves — (1) DB migration + `TradeFrame`/`LedgerEntry` dataclass changes + `trade_framer.py` stop_basis logic + `signal_generator_service.py` snapshot writes, (2) `lifecycle_tracker.py` + `signal_lifecycle_service.py` Chandelier/staleness additions, (3) divergence plugin stack expansion + `divergence_stack.py` rewrite.

---

## Standard Stack

### Core (no new dependencies required)
| Library | Current Version | Purpose | Notes |
|---------|-----------------|---------|-------|
| numpy | existing | Peak/trough detection, linreg slope, Chandelier high/low tracking | Already used in all I5/I7 plugins |
| asyncpg | existing | JSONB append for `trailing_stop_price` history array | Already used in `signal_lifecycle_service` |
| pydantic | existing | `I5Patterns` schema extension | `extra='forbid'` — new fields MUST be declared |
| structlog | existing | Per-bar staleness score logging | Already used throughout |

### No New Installations Required
All Phase 32 functionality uses libraries already present in `.venv`. No `pip install` steps.

---

## Architecture Patterns

### Recommended Project Structure (new files only)
```
src/intelligence/patterns/
├── macd_divergence.py          # DIV-01: new I5 plugin
├── cmf_divergence.py           # DIV-03: new I5 plugin
└── volume_divergence.py        # DIV-02: extended in place

production/migrations/
└── 035_stop_basis_and_divergence_stack.sql  # next migration number
```

### Pattern 1: stop_basis Label from stop_type
`_resolve_stop_long/short()` already returns `(stop_price, stop_type_str)` where `stop_type_str` is one of `"demand_zone"`, `"sweep_level"`, `"ob_bottom"`, `"ob_top"`, `"swing_low"`, `"swing_high"`, `"sr_support"`, `"sr_resistance"`, `"atr"`. Phase 32 maps these to `stop_basis` based on two conditions:

```python
# GARCH multiplier on effective ATR (applied before any stop calculation)
GARCH_MULTIPLIERS = {0: 0.8, 1: 1.0, 2: 1.35}
garch_regime = int(features.get("garch_vol_regime") or 1)  # default normal
effective_atr = atr * GARCH_MULTIPLIERS.get(garch_regime, 1.0)

# After _resolve_stop_long/short() returns (stop_price, stop_type):
atr_fallback_stop = entry - effective_atr * ATR_STOP_FALLBACK_MULTIPLIER  # longs
structural_distance_atr = abs(structural_stop - atr_fallback_stop) / effective_atr

if stop_type == "atr":
    stop_basis = "garch_adaptive" if garch_vol_regime is not None else "atr_static"
else:
    # Structural — check 1.5×ATR proximity gate
    if structural_distance_atr <= 1.5:
        stop_basis = "structure_snap"
    else:
        stop_basis = "garch_adaptive"  # structural stop too far — degrade
```

### Pattern 2: FVG as Structural Stop Tier
Insert FVG as tier 0 (highest priority) in `_resolve_stop_long()`. FVG low for longs is `fvg_bottom` when `fvg_type == 1`; for shorts `fvg_top` when `fvg_type == -1`:

```python
# Priority 0 (new): FVG low/high
fvg_type = _fval(features, "fvg_type")
fvg_bottom = _fval(features, "fvg_bottom")
if fvg_type == 1.0 and fvg_bottom > EPSILON_TOLERANCE and fvg_bottom < entry:
    stop = fvg_bottom - atr * ATR_STOP_OB_MULTIPLIER  # same clearance as OB
    if stop < entry - EPSILON_TOLERANCE:
        return min(stop, min_stop), "fvg_low"
```

### Pattern 3: Chandelier State in Lifecycle Service
`lifecycle_tracker.py` is pure — all per-signal state injected from service:

```python
# In signal_lifecycle_service._state dicts (keyed by signal_id):
self._chandelier_high: dict[str, float] = {}   # highest_high_since_entry
self._chandelier_low: dict[str, float] = {}    # lowest_low_since_entry
self._trailing_stop_history: dict[str, list] = {}  # [{ts, price}, ...]
self._staleness_consecutive: dict[str, int] = {}   # bars above threshold

# evaluate_signal() extended signature:
def evaluate_signal(
    signal, *, high, low, close,
    current_mae=0.0, current_mfe=0.0,
    chandelier_high=None,    # injected from service
    chandelier_low=None,     # injected from service
    hmm_regime_now=None,     # for staleness check
    garch_sigma_now=None,    # for sigma_drift_ratio
) -> tuple[Transition | None, dict]:  # returns (transition, updated_state)
```

**Important:** The current `evaluate_signal()` returns `Transition | None`. Phase 32 returns a 2-tuple `(Transition | None, state_updates)` to propagate Chandelier high/low updates back to the service. This is a breaking change — all callers in tests must be updated.

### Pattern 4: Staleness Score Formula
Claude's discretion applies here. Recommended formula (log-linear, range-bounded):

```python
def compute_staleness_score(
    hmm_regime_now: int,
    hmm_regime_at_fire: int,
    garch_sigma_now: float,
    garch_sigma_at_fire: float,
) -> tuple[float, str]:
    regime_drift = 0.0 if hmm_regime_now == hmm_regime_at_fire else 1.0
    sigma_ratio = garch_sigma_now / garch_sigma_at_fire if garch_sigma_at_fire > 0 else 1.0
    # Normalize sigma ratio: 1.0 → 0 contribution; 2.0× → 0.5; 3.0× → 0.75 (log-scale)
    import math
    sigma_component = min(1.0, math.log(max(sigma_ratio, 1.0)) / math.log(3.0))
    # Weighted blend: regime flip is decisive (0.6 weight), vol drift is supporting (0.4)
    score = round(0.6 * regime_drift + 0.4 * sigma_component, 4)
    if regime_drift > 0 and sigma_component >= 0.5:
        reason = "both"
    elif regime_drift > 0:
        reason = "hmm_regime_flip"
    else:
        reason = "vol_drift"
    return score, reason
```

The threshold for `condition_expired` is 0.5 (hypothesis; continuous `staleness_score` value logged so training pipeline finds empirical threshold). 3-consecutive-bar confirmation prevents single noisy bar kills.

### Pattern 5: JSONB Trailing Stop History Append
`trailing_stop_price` is a JSONB array `[{ts, price}, ...]`. Each lifecycle tick appends one entry. asyncpg cannot append in-place; pattern is read-compute-write:

```python
# In signal_lifecycle_service — per tick when active:
current_history = sig.get("trailing_stop_price") or []
new_entry = {"ts": bar_time.isoformat(), "price": round(new_trailing_stop, 4)}
updated_history = current_history + [new_entry]
# Write via dedicated UPDATE SQL:
# UPDATE signal_ledger SET trailing_stop_price = $2::jsonb,
#   trailing_stop_tightening_rate = $3 WHERE signal_id = $1::uuid
```

This requires a new SQL function `record_chandelier_update()` in `signal_ledger.py`.

**Alternative:** If JSONB append becomes a write contention issue at scale (60 instruments × 4 TF × many active signals), a separate `trailing_stop_history` table can replace the array. Flag for Claude's discretion; start with JSONB.

### Pattern 6: Divergence Plugin Template
All three new divergence plugins follow the same structure. `macd_divergence.py` mirrors `rsi_divergence.py` (peak/trough approach); `cmf_divergence.py` mirrors `volume_divergence.py` (linreg slope approach):

```python
@dataclass
class MACDDivergencePlugin:
    name: str = "MACDDivergence"
    outputs: frozenset[str] = frozenset({"macd_div_bullish", "macd_div_bearish", "macd_div_strength"})
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"pattern", "momentum"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=100),)
    neighbor: int = 5
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        # Read pre-computed macd_histogram_12_26_9 from I1 features
        # Do NOT recompute MACD — consume from features dict
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}
        close = df["close"].to_numpy(dtype=float)
        # Build histogram series from single feature scalar is wrong —
        # need full MACD histogram series from bar history.
        # Solution: compute from df["close"] directly (same as RSIDivergence computes its own RSI)
        # See Code Examples section for full implementation.
```

**Critical note on MACD histogram:** The `features` dict provides only the latest bar's `macd_histogram_12_26_9` scalar. For divergence detection, we need the MACD histogram series across the lookback window. Follow `rsi_divergence.py`'s pattern: compute the full series from `df["close"]` inside `compute_full()`. Do not try to read a series from `features`.

### Pattern 7: DivergenceStack Weighted Score
The rewritten `divergence_stack.py` must always return scoring fields even when no signal fires (Renaissance: log everything):

```python
def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
    features = frames.get("features") or {}
    # ... compute per-input scores ...
    div_weighted_score = sum(weight * score for ...)
    n_agreeing = sum(1 for score in active_scores if score > 0)

    # Always return scoring metadata (even on no-signal)
    base_output = {
        "div_weighted_score": round(div_weighted_score, 4),
        "div_n_agreeing": n_agreeing,
        # per-input fields ...
    }

    if div_weighted_score > 0.40 and n_agreeing >= 3:
        # ... add signal fields ...
        return {**base_output, "signal_type": ..., "direction": ..., ...}
    return {**base_output, "signal_type": "none", "direction": 0, "confidence": 0.0}
```

**Important:** `DivergenceStackPlugin.outputs` frozenset currently only contains signal-type fields. It must be expanded to include all always-logged scoring fields. These do NOT go into `I5Patterns` (I5 is upstream of I7); they flow through the signal features pipeline instead.

### Anti-Patterns to Avoid
- **Putting I7 scoring fields in I5Patterns schema**: `DivergenceStackPlugin` is an I7 plugin; its outputs flow through the signal bus, not the `IntelligenceEvent.i5` sub-model. The three new I5 plugins (`macd_divergence`, `cmf_divergence`) and the extended `volume_divergence` DO need `I5Patterns` schema entries.
- **Mutating `evaluate_signal()` to be stateful**: It must stay pure. Pass all state as parameters; return state updates.
- **Re-computing I1 indicators inside I5/I7 plugins**: Consume from `features` dict (scalars) or `df` (full series). For divergence detection needing full series, compute from `df["close"]` (like RSIDivergence does internally).
- **Using `garch_sigma` directly without None guard**: `garch_sigma` can be `None` if GARCH hasn't warmed up. Always `garch_sigma or atr_14` pattern.
- **Adding `stop_basis` as a field to `TradeFrame` without also updating callers**: `signal_generator_service.py` reads specific fields from `frame` via attribute access; new fields added to `TradeFrame` must also be extracted and passed to `LedgerEntry`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| MACD histogram series | Custom EMA/MACD compute in plugin | Compute from `df["close"]` using same pattern as `RSIDivergencePlugin._rsi_series()` | All data already in `df`; histogram = MACD line - signal line; avoids divergence from canonical I1 values |
| Peak/trough detection | Custom argmax/argmin | `from ..utils import find_peaks, find_troughs` | Already exists, battle-tested in RSIDivergence |
| Linear regression slope | `np.polyfit()` | `VolumeDivergencePlugin._linreg_slope()` static method | Already exists; numerically stable; reuse as static or copy pattern |
| GARCH sigma null guard | `if garch_sigma is None: skip` | `garch_sigma = float(features.get("garch_sigma") or 0.0) or atr_14` | Consistent fallback pattern across entire codebase |
| Trailing stop history JSON | Custom serialization | Standard `json.dumps/loads` via asyncpg JSONB codec | JSONB codec already registered in `get_connection()` |
| Schema coverage validation | Manual field verification | Run `validate_schema_coverage()` at startup | Already wired in `register_all_plugins()`; hard-crashes on missing I5 schema fields |

---

## Common Pitfalls

### Pitfall 1: evaluate_signal() Return Type Change Breaks Tests
**What goes wrong:** `evaluate_signal()` currently returns `Transition | None`. Adding Chandelier state requires returning state updates too. If changed to `tuple[Transition | None, dict]`, all 17 callers in unit tests will break with `TypeError: cannot unpack non-iterable NoneType`.
**Why it happens:** Test mocking pattern uses `signal_lifecycle_service` tests that call `evaluate_signal()` via the service, and unit tests that call it directly.
**How to avoid:** Either (a) keep the signature as `Transition | None` and pass Chandelier state as mutable dicts into `evaluate_signal()` that it writes to, or (b) introduce a new `evaluate_signal_extended()` wrapper. Option (a) is cleaner — use `chandelier_state: dict` as an output parameter mutated in-place.
**Warning signs:** Any test importing `lifecycle_tracker.evaluate_signal` directly.

### Pitfall 2: LedgerEntry.to_insert_params() Element Count Mismatch
**What goes wrong:** `to_insert_params()` currently returns 39 elements. Adding 14 new `signal_ledger` fields means 53 elements. Every test that asserts on the count or the SQL INSERT column list will fail.
**Why it happens:** The INSERT SQL is a literal string; parameter count is implicit.
**How to avoid:** Update `_INSERT_SQL`, `to_insert_params()`, and the `$N` parameter placeholders atomically. Update any test that hardcodes `assert len(params) == 39`.
**Warning signs:** `asyncpg.exceptions.TooManyParametersError` at runtime.

### Pitfall 3: I5Patterns extra='forbid' Rejects New DIV Fields
**What goes wrong:** `I5Patterns` has `extra='forbid'`. If a plugin outputs a field not declared in `I5Patterns`, `IntelligenceEvent` validation raises `ValidationError` and the entire bar is dropped.
**Why it happens:** `validate_schema_coverage()` only checks fields in plugin.outputs; if the plugin computes a field but doesn't list it in `outputs`, it will silently pass coverage but fail at runtime.
**How to avoid:** For each new I5 plugin output field, add it to BOTH the plugin's `outputs` frozenset AND `I5Patterns` model fields. Run `validate_schema_coverage()` in tests.
**Warning signs:** `market_analysis_service` logs `ValidationError` for the symbol/TF after deploying new plugins.

### Pitfall 4: DivergenceStack Always-Log Fields Not in signal_features
**What goes wrong:** `div_weighted_score`, `div_n_agreeing`, and per-input fields logged on every bar need to reach `intelligence_features`. If `DivergenceStackPlugin.outputs` only lists them but they're not part of any I5/I7 schema, they won't be serialized into `IntelligenceEvent` and won't flow to `feature_writer_service`.
**Why it happens:** I7 plugin outputs flow through the signal bus (`signals:SYMBOL:TF`), not through `IntelligenceEvent`. The `intelligence_features` JSONB is written from `IntelligenceEvent` fields, not from signal bus fields.
**How to avoid:** Divergence scoring fields need to flow via `IntelligenceEvent` (I5 layer) OR be added to the `feature_writer_service` enrichment path. Best solution: the three I5 plugins (`macd_divergence`, `cmf_divergence`, extended `volume_divergence`) log their per-input fields through I5Patterns naturally. For `div_weighted_score` and `div_n_agreeing` (I7 outputs), they should be included in `signal_features` via `_build_feature_rows()` which reads from the `features` dict — but only if the signal fires. The CONTEXT.md says "log every bar" — this requires making the DivergenceStack fields available to `feature_writer_service` via the `intelligence_features` i7 JSONB column.
**Warning signs:** `intelligence_features` rows missing `div_weighted_score` for bars where no signal fired.

### Pitfall 5: Staleness State Not Restored After Service Restart
**What goes wrong:** `signal_lifecycle_service` stores `hmm_regime_at_fire` and `garch_sigma_at_fire` in-memory via `signal_ledger` DB row; but Chandelier state (`_chandelier_high/_low`) and staleness consecutive counter (`_staleness_consecutive`) are in-memory only. After a restart, all active signals lose their tracking state.
**Why it happens:** The service loads active signals from DB on startup via `get_active_signals()`, but the in-memory dicts are empty.
**How to avoid:** On startup, re-seed `_chandelier_high/_low` and `_staleness_consecutive` from the DB. This requires `trailing_stop_price` JSONB history (can derive last trailing stop from history array) and `staleness_score` field (can resume with 0 consecutive bars — conservative). Document this clearly in the service startup code.
**Warning signs:** `condition_expired` triggers after service restart on signals that were previously near-stale.

### Pitfall 6: TTL Per-TF Constants (SIG-05)
**What goes wrong:** Currently `ttl_bars` defaults to 10 for all timeframes in `signal_schema.py`. For a 1h signal, 10 bars = 10 hours of waiting; for 1m, 10 bars = 10 minutes. These very different economic meanings were never differentiated.
**Why it happens:** `ttl_bars` is passed from the I7 plugin via the signal dict, but no current I7 plugin sets it explicitly — they all rely on the default of 10.
**How to avoid:** Define a `TF_TTL_BARS` constant dict in `signal_generator_service.py` (not in individual plugins), apply it after aggregation when building `LedgerEntry`. The I7 plugin outputs remain unchanged. Reasonable hypothesis values: `{"1m": 20, "5m": 12, "15m": 8, "1h": 6}` — rationale: shorter TF signals are more time-sensitive; log the actual TTL value as a feature for later ML optimization.
**Warning signs:** `ttl_expired_*` outcomes dominating signal_ledger on 1m TF (TTL too short) or 1h TF signals accumulating for 10+ hours (TTL too long).

---

## Code Examples

### Stop Basis Classification (verified pattern)
```python
# Source: CONTEXT.md decisions + trade_framer.py current pattern
GARCH_MULTIPLIERS = {0: 0.8, 1: 1.0, 2: 1.35}
STRUCTURE_SNAP_PROXIMITY_ATR = 1.5  # hypothesis — log actual distance for training

def _classify_stop_basis(
    stop_type: str,
    stop_price: float,
    entry: float,
    effective_atr: float,
    garch_vol_regime: int | None,
    direction: int,
) -> tuple[str, str]:
    """Return (stop_basis, stop_structure_type)."""
    if stop_type == "atr":
        if garch_vol_regime is not None:
            return "garch_adaptive", "atr_fallback"
        return "atr_static", "atr_fallback"

    # Structural — compute ATR fallback stop for proximity check
    atr_fallback = entry - effective_atr * ATR_STOP_FALLBACK_MULTIPLIER if direction == 1 \
                   else entry + effective_atr * ATR_STOP_FALLBACK_MULTIPLIER
    distance_atr = abs(stop_price - atr_fallback) / effective_atr if effective_atr > 0 else 0.0

    if distance_atr <= STRUCTURE_SNAP_PROXIMITY_ATR:
        return "structure_snap", _stop_type_to_structure_type(stop_type)
    else:
        return "garch_adaptive", _stop_type_to_structure_type(stop_type)

def _stop_type_to_structure_type(stop_type: str) -> str:
    mapping = {
        "demand_zone": "demand_zone", "supply_zone": "supply_zone",
        "sweep_level": "sweep_level",
        "ob_bottom": "ob_bottom", "ob_top": "ob_top",
        "swing_low": "swing_low", "swing_high": "swing_high",
        "sr_support": "sr_support", "sr_resistance": "sr_resistance",
        "fvg_low": "fvg_low", "fvg_high": "fvg_high",
    }
    return mapping.get(stop_type, "atr_fallback")
```

### MACD Histogram Series Computation (for macd_divergence.py)
```python
# Source: rsi_divergence.py pattern + standard MACD formula
# Compute MACD histogram from close series (same pattern as RSIDivergence._rsi_series)
@staticmethod
def _macd_histogram_series(close: np.ndarray, fast=12, slow=26, signal=9) -> np.ndarray:
    """Compute MACD histogram series. Returns same-length array as close."""
    def ema(arr, period):
        out = np.zeros_like(arr)
        k = 2.0 / (period + 1)
        out[0] = arr[0]
        for i in range(1, len(arr)):
            out[i] = arr[i] * k + out[i-1] * (1 - k)
        return out

    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    return macd_line - signal_line  # histogram
```

### Volume Divergence Extension (OBV outputs)
```python
# Source: volume_divergence.py existing OBV computation
# Extend VolumeDivergencePlugin.outputs frozenset:
outputs: frozenset[str] = frozenset({
    "vol_div_bullish", "vol_div_bearish", "vol_div_strength",
    "obv_div_bullish", "obv_div_bearish", "obv_div_strength",  # NEW
})

# In compute_full(), after existing OBV slope logic — reuse same obv_slope/price_slope:
# The existing logic already computes norm_price and norm_obv.
# Add OBV divergence outputs using same logic as vol_div (they're the same computation):
obv_bullish = bullish  # OBV IS the vol divergence in this plugin — it's the same
obv_bearish = bearish  # Rename semantically: vol_div_* = OBV divergence vs price
```

**Wait — verify:** Looking at `volume_divergence.py` carefully, `vol_div_bullish/bearish` IS already the OBV divergence (the plugin computes OBV internally and uses its slope for divergence). The CONTEXT.md decision to "extend" rather than add a new plugin is because they're the same computation. The new `obv_div_*` outputs are aliases with the same values, or the plugin adds a parallel CMF-style computation using the `obv` I1 feature directly (from `features.get("obv")`). Given the CONTEXT.md intent, the cleanest interpretation: extend `volume_divergence.py` to also output `obv_div_*` fields (computed from the internal OBV series) alongside the existing `vol_div_*` fields.

### TTL Per-TF Named Constants
```python
# Source: lifecycle_tracker.py default of 10 + CONTEXT.md SIG-05 requirement
# In signal_generator_service.py (not in individual plugins):
TF_TTL_BARS: dict[str, int] = {
    "1m": 20,   # 20 min window for 1m signals
    "5m": 12,   # 60 min window for 5m signals
    "15m": 8,   # 2 hour window for 15m signals
    "1h": 6,    # 6 hour window for 1h signals
}
```

---

## State of the Art

| Old Approach | Current Approach | Phase 32 Change | Impact |
|--------------|------------------|-----------------|--------|
| ATR fixed multiplier stops | Structural stop hierarchy in `trade_framer.py` | GARCH-adaptive scaling + `stop_basis` label + FVG tier | All 17 plugins inherit without per-plugin changes |
| No stop quality metadata | `stop_type` string only | `stop_basis` + `stop_structure_type` + `stop_structure_age_bars` + distance metric | ML pipeline can segment signal quality by stop type |
| No trailing stop | Static stop_loss at signal fire | Chandelier trailing stop tracked per bar in lifecycle | Active signal stop tightens with favorable price movement |
| No signal staleness | Signal lives until stop/target/TTL | Staleness score triggers `condition_expired` outcome | Shadow tracking validates whether staleness logic adds alpha |
| 2-input AND-gate divergence | `rsi_div > 0.3 AND vol_div > 0.3` | 5-input weighted score + `n_agreeing >= 3` | ~40% recall expansion while maintaining quality bar |
| Fixed TTL default = 10 | Same TTL for all TF | Per-TF named constants | Economically meaningful TTL per timeframe |

---

## Open Questions

1. **Divergence always-log path for I7 outputs**
   - What we know: `div_weighted_score` and `div_n_agreeing` must be logged on every bar (CONTEXT.md), but I7 plugin outputs don't flow through `IntelligenceEvent`
   - What's unclear: Whether to add these as I5 fields (would be computed before I7 fires, but DivergenceStack is I7 so the scores come from I7 not I5), or to log them via the i7 JSONB payload in `intelligence_features`
   - Recommendation: Log `div_weighted_score` and `div_n_agreeing` in the I7 signal bus payload even when no signal fires (DivergenceStack returns them in `_no_signal()` return dict), and include them in the `intelligence_features.i7` JSONB written by `feature_writer_service`. This is consistent with the "i7 JSONB = all ranked setups" pattern already documented.

2. **Chandelier DB write frequency**
   - What we know: Active signals receive one lifecycle tick per 1m bar; 60 instruments × active signals = potentially high write frequency
   - What's unclear: Whether JSONB history append per bar is acceptable write load on TimescaleDB
   - Recommendation: Start with JSONB (simpler); if write contention emerges in production, migrate to a separate `trailing_stop_history` table. Log as technical debt decision in plan comments.

3. **Structure age_bars source**
   - What we know: `stop_structure_age_bars` needs to know when the structural level was established. For swing_low: `swing_low_age_bars` exists in `I3Structure`. For demand zones, OBs, FVGs: no equivalent age field in the schema.
   - What's unclear: Whether `demand_freshness` (0.0–1.0) can be inverted to estimate age bars, or whether age should be approximated.
   - Recommendation: For levels with direct age fields (`swing_low_age_bars`, `swing_high_age_bars`, `support_age_bars`, `resistance_age_bars`), use them. For zones without age fields (demand, supply, OB, FVG), set `stop_structure_age_bars = None` initially and log the limitation.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (`.venv/bin/pytest`) |
| Config file | none — project root discovery |
| Quick run command | `.venv/bin/pytest tests/unit/test_trade_framer.py tests/unit/test_lifecycle_tracker.py tests/unit/test_divergence_stack.py -x -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SIG-01 | `stop_basis` computed correctly for all 3 values | unit | `pytest tests/unit/test_trade_framer.py -x` | ❌ Wave 0 |
| SIG-01 | FVG tier wins when fvg_bottom within 1.5×ATR | unit | `pytest tests/unit/test_trade_framer.py::test_fvg_stop_basis -x` | ❌ Wave 0 |
| SIG-02 | GARCH multiplier applied to effective ATR (0.8/1.0/1.35) | unit | `pytest tests/unit/test_trade_framer.py::test_garch_multiplier -x` | ❌ Wave 0 |
| SIG-02 | Proximity gate degrades structure_snap to garch_adaptive when distance > 1.5×ATR | unit | `pytest tests/unit/test_trade_framer.py::test_proximity_gate -x` | ❌ Wave 0 |
| SIG-03 | Chandelier stop computed correctly (long/short) | unit | `pytest tests/unit/test_lifecycle_tracker.py::test_chandelier_trailing -x` | ❌ Wave 0 |
| SIG-03 | Trailing stop tightens monotonically, never widens | unit | `pytest tests/unit/test_lifecycle_tracker.py::test_chandelier_monotonic -x` | ❌ Wave 0 |
| SIG-04 | `condition_expired` fires after 3 consecutive bars of staleness_score > threshold | unit | `pytest tests/unit/test_lifecycle_tracker.py::test_staleness_expiry -x` | ❌ Wave 0 |
| SIG-04 | Shadow tracking continues after condition_expired | unit | `pytest tests/unit/test_signal_lifecycle_service.py::test_shadow_tracking -x` | ❌ Wave 0 |
| SIG-05 | TTL per-TF constants are documented named values | unit | `pytest tests/unit/test_signal_generator_service.py::test_ttl_constants -x` | ❌ Wave 0 |
| DIV-01 | MACDDivergencePlugin detects bullish/bearish divergence | unit | `pytest tests/unit/test_macd_divergence.py -x` | ❌ Wave 0 |
| DIV-02 | VolumeDivergencePlugin outputs obv_div_* fields | unit | `pytest tests/unit/test_volume_divergence.py::test_obv_outputs -x` | ❌ Wave 0 |
| DIV-03 | CMFDivergencePlugin detects divergence using cmf_20 | unit | `pytest tests/unit/test_cmf_divergence.py -x` | ❌ Wave 0 |
| DIV-04 | DivergenceStack fires when score > 0.40 AND n_agreeing >= 3 | unit | `pytest tests/unit/test_divergence_stack.py::test_weighted_score_gate -x` | ❌ Wave 0 |
| DIV-04 | DivergenceStack logs scoring fields even when no signal fires | unit | `pytest tests/unit/test_divergence_stack.py::test_always_log -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/ -x -q`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -v`
- **Phase gate:** Full unit suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/test_trade_framer.py` — SIG-01/SIG-02 stop_basis + GARCH multiplier tests
- [ ] `tests/unit/test_lifecycle_tracker.py` — SIG-03/SIG-04 Chandelier + staleness tests (extend existing file if it exists)
- [ ] `tests/unit/test_macd_divergence.py` — DIV-01
- [ ] `tests/unit/test_cmf_divergence.py` — DIV-03
- [ ] `tests/unit/test_divergence_stack.py` — DIV-04 (replace/extend existing AND-gate tests)
- [ ] Check whether `tests/unit/test_volume_divergence.py` exists; extend for DIV-02

---

## Sources

### Primary (HIGH confidence)
- Direct code inspection: `src/intelligence/trading/trade_framer.py` — full `frame_trade()` flow, stop hierarchy, `TradeFrame` dataclass
- Direct code inspection: `src/intelligence/trading/lifecycle_tracker.py` — `evaluate_signal()` pure function, `Transition` dataclass, current state management
- Direct code inspection: `src/intelligence/trading/signal_ledger.py` — `LedgerEntry` (39-field tuple), all SQL strings
- Direct code inspection: `src/intelligence/trading/divergence_stack.py` — current 2-input AND-gate, all parameters
- Direct code inspection: `src/intelligence/patterns/rsi_divergence.py` — template for `macd_divergence.py`
- Direct code inspection: `src/intelligence/patterns/volume_divergence.py` — OBV internal computation, linreg slope pattern
- Direct code inspection: `src/intelligence/schemas.py` — `I4Context.garch_sigma`, `I4Context.garch_vol_regime`, `SMCContext.fvg_bottom`, `SMCContext.fvg_top`, `I5Patterns.extra='forbid'`
- Direct code inspection: `src/intelligence/register_plugins.py` — `TIER_I5`, `TIER_I7`, `validate_schema_coverage()`
- Direct code inspection: `services/signal_lifecycle_service.py` — service state dicts, bar processing loop
- Direct code inspection: `production/migrations/034_cis_learning_loop.sql` — confirms next migration is `035`
- Direct code inspection: `.planning/REQUIREMENTS.md` SIG-01–SIG-05, DIV-01–DIV-04

### Secondary (MEDIUM confidence)
- `.planning/phases/32-stop-architecture-extended-divergence-stack/32-CONTEXT.md` — all locked decisions
- `.planning/STATE.md` — confirmed Phase 31 complete, phase 32 next; verified key facts (LedgerEntry 39 elements, garch_vol_regime field exists)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all existing libraries; no new dependencies
- Architecture: HIGH — all patterns verified against actual code; no guesswork
- Pitfalls: HIGH — LedgerEntry count, I5Patterns forbid, evaluate_signal return type all verified against live code
- TTL per-TF: MEDIUM — current default verified as 10; recommended values are hypotheses, not verified against outcome data

**Research date:** 2026-03-17
**Valid until:** 2026-04-17 (stable codebase; only invalidated by Phase 32 execution itself)
