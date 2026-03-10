# Phase 12: Signal Integrity — Research

**Researched:** 2026-03-04
**Domain:** I7 plugin regime gating, shadow signal mechanics, signal_ledger persistence, signal_lifecycle_service extension
**Confidence:** HIGH — all findings sourced directly from existing codebase

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Gating Location — Hybrid: class attribute + aggregator enforcement**
- Each I7 plugin declares `regime_type: str = "any" | "trend" | "mean_reversion"` as a class attribute
- The aggregator reads this attribute and applies thresholds centrally (one place to tune prob/duration thresholds)
- Replaces the current `REGIME_ELIGIBILITY` dict — self-documenting at the plugin level, no separate dict to maintain
- Gate thresholds stay in aggregator constants: `_REGIME_PROB_MIN = 0.60`, `_REGIME_DUR_MIN = 5` (raised from 0.55/3)

**Regime Sourcing — Cascade (slow-clock gating)**
- Each signal TF gates on the next-higher TF's HMM via a `_regime_cache` maintained in signal_generator_service
- Bar data (OHLCV, indicators, entry/stop/target logic) stays in its own TF — no cross-TF price data mixing
- The regime label is a categorical market state (not bar data), sourced one step up

| Signal TF | Regime authority |
|-----------|-----------------|
| 1m        | 5m HMM          |
| 5m        | 15m HMM         |
| 15m       | 1h HMM          |
| 1h        | 4h HMM          |
| 4h        | 1d HMM          |
| 1d        | 1d HMM (own)    |

- Implementation: `_regime_cache: dict[symbol, dict[tf, {hmm_regime, hmm_regime_prob, hmm_regime_duration}]]`
- Updated on every intelligence event arrival (any TF)
- Gate map constant: `{"1m": "5m", "5m": "15m", "15m": "1h", "1h": "4h", "4h": "1d", "1d": "1d"}`
- If cache entry missing (higher TF not yet seen): skip gate (don't suppress on absent data)

**Shadow Signal Mechanics**
- Suppressed signals are written to `signal_ledger` with `status='regime_suppressed'`
- Entry/stop/target levels are populated normally — setup logic runs fully before the gate decision
- `signal_lifecycle_service` queries `regime_suppressed` signals alongside `pending` at startup
- Shadow signals are virtually activated at signal bar close — no zone-activation check required
- MAE/MFE tracked normally until TTL expiry using the signal's own entry/stop/target levels
- Status never changes from `regime_suppressed` (never becomes `active`)
- At TTL: 8-class outcome written — this is the counterfactual ("what would have happened")
- Only lifecycle code change: extend initial DB query to include `regime_suppressed` status; skip zone-activation logic for those entries

**Regime Map — All 17 I7 Plugins**
| Plugin | `regime_type` |
|--------|--------------|
| TrendFollowing | `trend` |
| MomentumBreakout | `trend` |
| LiquidityHunt | `trend` |
| MTFAlignment | `trend` |
| SqueezeExpansion | `trend` |
| MeanReversion | `mean_reversion` |
| VWAPDeviation | `mean_reversion` |
| FVGFill | `mean_reversion` |
| LiquiditySweepReclaim | `mean_reversion` |
| SessionExtremesSetup | `mean_reversion` |
| CHoCHReversal | `any` |
| RegimeTransition | `any` |
| DivergenceStack | `any` |
| PatternCompletion | `any` |
| GapAnalysisSetup | `any` |
| CandlestickPatternSetup | `any` |
| SupplyDemandSetup | `any` |

Summary: 5 trend-only · 5 mean-reversion-only · 7 any-regime

### Claude's Discretion
- Exact field name for `regime_type` attribute (could be `regime_type`, `regime_class`, `allowed_regimes`)
- Whether `_regime_cache` is a dict-of-dicts or a flat `(symbol, tf)` keyed dict
- How to handle the edge case where 4h/1d intelligence streams are not yet subscribed

### Deferred Ideas (OUT OF SCOPE)
- Whether I7 plugins should run on 4h/1d bars (currently signal_generator subscribes to 1m/5m/15m/1h only) — defer to backlog
- Empirical reclassification of `any` plugins based on shadow signal outcome data — v1.5+
- Regime-adaptive plugin parameters (I1/I4 parameter values adapt to hmm_regime) — already in v2 backlog
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SIGINT-01 | Every I7 plugin reads `hmm_regime` from IntelligenceEvent SMC tier and applies regime-appropriate gate before firing (trend/momentum: regime 1 or 2 only; mean-reversion: regime 0 only) | `regime_type` class attribute + aggregator enforcement replaces REGIME_ELIGIBILITY dict; HMM fields confirmed in SMCContext schema |
| SIGINT-02 | Every I7 plugin applies conviction gate — `hmm_regime_prob < 0.60` suppresses signal regardless of setup logic | Aggregator already has `_REGIME_PROB_MIN` constant; raise from 0.55 to 0.60; gate now uses higher-TF regime_cache value |
| SIGINT-03 | Every I7 plugin applies stability gate — `hmm_regime_duration < 5` suppresses signal | Aggregator already has `_REGIME_DUR_MIN` constant; raise from 3 to 5; same code path as SIGINT-02 |
| SIGINT-04 | Regime authority uses 5m or 15m timeframe HMM, not 1m | `_regime_cache` in signal_generator_service caches higher-TF HMM; gate map constant maps each signal TF to its authority TF |
| SIGINT-05 | All suppressed signals appear in `signal_ledger` with `status='regime_suppressed'`; lifecycle tracks their MAE/MFE/outcome as shadow signals | LedgerEntry already has `status` field; `build_ledger_entries()` needs regime_eligible/suppression_reason logic; lifecycle query extension + virtual-activation path for shadow signals |
</phase_requirements>

---

## Summary

Phase 12 adds regime-aware gating to all 17 I7 plugins. The core mechanic is a three-check gate in the aggregator: regime type compatibility (trend vs. mean-reversion vs. any), conviction probability threshold (>= 0.60), and regime stability duration (>= 5 bars). All three checks use HMM regime data from a higher timeframe than the signal's own timeframe — this "slow-clock" cascade is the key innovation ensuring 1m signals are not gated on noisy 1m HMM.

The shadow signal mechanic is equally important: rather than silently discarding regime-ineligible signals, they are written to signal_ledger with `status='regime_suppressed'` and tracked by signal_lifecycle_service for counterfactual MAE/MFE/outcome. This creates the feedback data needed to validate and tune gate thresholds empirically over 90 days.

The implementation touches four files in a controlled way: (1) all 17 I7 plugin classes get a `regime_type` class attribute, (2) `aggregator.py` replaces `REGIME_ELIGIBILITY` dict with attribute introspection and adds shadow signal output path, (3) `signal_generator_service.py` adds `_regime_cache` and passes higher-TF regime to aggregate(), (4) `signal_lifecycle_service.py` extends its DB query and adds a virtual-activation code path for `regime_suppressed` signals.

**Primary recommendation:** Implement in strict order — plugins first (pure attribute additions, zero logic change), then aggregator (regime gate + shadow output), then signal_generator (cache + wiring), then lifecycle (query + virtual-activation). Each step is independently testable before the next.

---

## Standard Stack

This phase is a pure Python refactoring within the existing stack. No new libraries are needed.

### Existing Components (confirmed by code inspection)

| Component | File | Current State | Change Required |
|-----------|------|--------------|----------------|
| `REGIME_ELIGIBILITY` dict | `aggregator.py:20-27` | 6 plugins covered, silent drop | Replace with `regime_type` attribute introspection |
| `_REGIME_PROB_MIN` | `aggregator.py:29` | `0.55` | Raise to `0.60` |
| `_REGIME_DUR_MIN` | `aggregator.py:30` | `3` | Raise to `5` |
| `aggregate()` gate block | `aggregator.py:94-110` | Silently drops; never records suppressed | Add shadow output: tagged signals pass through to `all_ranked` |
| `AggregatedResult` | `aggregator.py:46-59` | No regime metadata fields | No change needed — shadow signals flow through `all_ranked` |
| `build_ledger_entries()` | `signal_generator_service.py:183-250` | Always writes `status="pending"` | Conditional status based on `regime_eligible` flag on signal dict |
| `_process_single_message()` | `signal_generator_service.py:588-638` | No `_regime_cache` | Add cache update from incoming IntelligenceEvent |
| `_process_bar()` | `signal_generator_service.py:447-586` | Passes same-TF features to aggregate() | Extract higher-TF regime from cache; pass as separate arg |
| `get_active_signals()` | `signal_ledger.py:173-183` | Queries `('pending', 'active')` only | Add `'regime_suppressed'` to query set |
| `_evaluate_signals_against_bar()` | `signal_lifecycle_service.py:163-289` | Zone-activation applies to all signals | Skip `_check_zone_activation` for `regime_suppressed` signals |
| `LedgerEntry.status` | `signal_ledger.py:48` | `"pending"` default | No model change; value supplied at creation |
| `SMCContext.hmm_regime` | `schemas.py:496` | `float | None` | No change; confirmed available |
| `SMCContext.hmm_regime_prob` | `schemas.py:497` | `float | None` | No change |
| `SMCContext.hmm_regime_duration` | `schemas.py:501` | `float | None` | No change |

---

## Architecture Patterns

### Pattern 1: Class Attribute on I7 Plugins

**What:** Add `regime_type: str = "trend" | "mean_reversion" | "any"` as a dataclass field with a default value on each I7 plugin class.

**When to use:** Attribute lives on the plugin class, is self-documenting, and is readable by the aggregator without a separate registry.

**Established pattern:** All I7 plugins are `@dataclass` with class-level string attributes (`name`, `outputs`, `inputs`, `capability_tags`). The new attribute follows the exact same pattern. No `__init__` changes; dataclass handles it.

```python
# Source: src/intelligence/trading/trend_following.py (existing pattern)
@dataclass
class TrendFollowingPlugin:
    name: str = "trad_TrendFollowing"
    outputs: frozenset[str] = frozenset({...})
    capability_tags: frozenset[str] = frozenset({"trading", "trend"})
    # NEW — add this line to each plugin:
    regime_type: str = "trend"   # or "mean_reversion" or "any"
```

**Critical:** The `regime_type` attribute must have a default value (not just a type annotation) for dataclass compatibility. Existing fields like `name` use this exact pattern.

### Pattern 2: Aggregator Gate — Replace Dict Lookup with Attribute Introspection

**What:** Replace the `REGIME_ELIGIBILITY` dict with direct attribute reads from plugin objects. The aggregator already receives signal dicts tagged with `setup_plugin` name; use the plugin registry to get the plugin object and read `regime_type`.

**Problem with direct object access:** The aggregator currently operates on signal dicts, not plugin objects. The `setup_plugin` key is a string name.

**Two implementation options (Claude's discretion):**

Option A — Build a local map at module load from registry:
```python
# In aggregator.py (module level, after imports)
from src.intelligence.plugins import registry

def _build_regime_type_map() -> dict[str, str]:
    """Build plugin_name -> regime_type map from registered plugins."""
    result = {}
    for name, plugin in registry.patterns.items():
        result[name] = getattr(plugin, "regime_type", "any")
    return result

# Called once at first aggregate() call or module import
```

Option B — Pass regime_type on the signal dict itself (tagged at plugin execution time in `_run_setup_plugins()`):
```python
# In signal_generator_service._run_setup_plugins():
result["setup_plugin"] = name
result["regime_type"] = getattr(plugin, "regime_type", "any")  # tag here
signals.append(result)
```

**Recommendation:** Option B (tag at plugin execution) is cleaner — it keeps the aggregator stateless and avoids registry coupling. The signal dict already carries all metadata the aggregator needs.

**Gate logic in aggregate() with shadow signal support:**
```python
# Instead of dropping non-eligible signals, tag them and let them flow to all_ranked
REGIME_MAP = {
    "trend":           [1, 2],
    "mean_reversion":  [0],
    "any":             [0, 1, 2],
}

for sig in signals:
    plugin_regime_type = sig.get("regime_type", "any")
    allowed_regimes = REGIME_MAP[plugin_regime_type]

    # Determine if gate is active (high confidence + stable regime)
    regime_gate_active = (
        hmm_regime is not None
        and float(hmm_regime_prob) >= _REGIME_PROB_MIN
        and int(hmm_regime_duration) >= _REGIME_DUR_MIN
    )

    if regime_gate_active and current_regime not in allowed_regimes:
        sig["regime_eligible"] = False
        sig["suppression_reason"] = "regime_type"
    elif regime_gate_active and float(hmm_regime_prob) < _REGIME_PROB_MIN:
        sig["regime_eligible"] = False
        sig["suppression_reason"] = "regime_prob"
    elif regime_gate_active and int(hmm_regime_duration) < _REGIME_DUR_MIN:
        sig["regime_eligible"] = False
        sig["suppression_reason"] = "regime_duration"
    else:
        sig["regime_eligible"] = True
        sig["suppression_reason"] = None
```

**Note on gate logic ordering:** The CONTEXT.md specifies three separate suppression reasons:
- `regime_type` — wrong regime for this plugin (e.g., trend plugin in ranging market)
- `regime_prob` — regime probability below threshold (uncertain regime label)
- `regime_duration` — regime too new (fewer than 5 bars)

The prob and duration checks suppress ALL plugins regardless of regime_type. The regime_type check only suppresses type-restricted plugins. Priority order for suppression_reason: `regime_prob` first, then `regime_duration`, then `regime_type`.

### Pattern 3: Regime Cache in signal_generator_service

**What:** A two-level dict caching the most recent HMM regime data for each (symbol, TF) pair. Updated on every intelligence event arrival. Used to look up the higher-TF regime before calling aggregate().

```python
# Instance variable in SignalGeneratorService.__init__:
self._regime_cache: dict[str, dict[str, dict]] = defaultdict(dict)
# Structure: {symbol: {tf: {"hmm_regime": float, "hmm_regime_prob": float, "hmm_regime_duration": float}}}

# Gate map constant (module level):
_REGIME_AUTHORITY_TF: dict[str, str] = {
    "1m": "5m", "5m": "15m", "15m": "1h",
    "1h": "4h", "4h": "1d", "1d": "1d",
}

# In _process_single_message() — cache update before calling _process_bar():
smc = event.smc
if smc.hmm_regime is not None:
    self._regime_cache[symbol][timeframe] = {
        "hmm_regime": smc.hmm_regime,
        "hmm_regime_prob": smc.hmm_regime_prob or 0.0,
        "hmm_regime_duration": smc.hmm_regime_duration or 0,
    }

# In _process_bar() — look up authority TF:
authority_tf = _REGIME_AUTHORITY_TF.get(timeframe, timeframe)
regime_data = self._regime_cache.get(symbol, {}).get(authority_tf)
# regime_data is None if authority TF not yet seen → skip gate
```

**Edge case: 4h/1d not subscribed.** The service currently subscribes to `["1m", "5m", "15m", "1h"]` only. The cache for `"4h"` and `"1d"` will always be empty. Per CONTEXT.md: if cache entry missing, skip gate (don't suppress on absent data). This means 1h signals will have no regime gating until 4h intelligence arrives — acceptable; 1h signals are already high-TF and relatively rare.

### Pattern 4: Shadow Signal Flow in build_ledger_entries()

**What:** `build_ledger_entries()` currently always sets `status="pending"`. It needs to inspect `regime_eligible` on each signal to set the correct status.

**Current flow:**
```
_run_setup_plugins() → signals list → aggregate() → AggregatedResult.all_ranked → build_ledger_entries() → LedgerEntry(status="pending")
```

**New flow:**
```
_run_setup_plugins() → signals tagged with regime_type → aggregate() → tags with regime_eligible/suppression_reason → AggregatedResult.all_ranked contains ALL signals (eligible + suppressed) → build_ledger_entries() → LedgerEntry(status="pending" | "regime_suppressed")
```

**Key insight:** The current `all_ranked` only contains signals that passed the `active` filter (direction != 0 AND signal_type != "none"). Shadow signals are active (they fired) but regime-ineligible. They should appear in `all_ranked` with `regime_eligible=False`. The `was_selected` flag is `False` for shadow signals.

```python
# In build_ledger_entries():
for sig in result.all_ranked:
    regime_eligible = sig.get("regime_eligible", True)
    suppression_reason = sig.get("suppression_reason")

    if not regime_eligible:
        status = "regime_suppressed"
    elif rank == 1 and result.selected_signal is not None:
        status = "pending"
    else:
        status = "pending"  # non-selected eligible signals are still "pending"
    # ... rest of LedgerEntry construction
```

**Note:** Non-selected eligible signals (rank > 1) retain `status="pending"` — this is existing behavior. Only regime-ineligible signals get `status="regime_suppressed"`.

### Pattern 5: Shadow Signal Virtual Activation in signal_lifecycle_service

**What:** Shadow signals start in `regime_suppressed` status. The lifecycle service needs to track their MAE/MFE from the start (virtually activated at signal bar close) without a zone-activation check.

**Current lifecycle state machine:**
- `pending` → (zone activation) → `active` → (stop/target/TTL) → exit status
- `pending` → (TTL without activation) → `expired` (outcome: `never_activated`)

**Shadow signal state machine:**
- `regime_suppressed` → (TTL) → exit status (outcome: one of 8 classes)
- Never enters `active` state
- MAE/MFE tracked as if active from t=0 (bar close of signal fire)

**Lifecycle query extension:**
```python
# In signal_ledger.py — update _SELECT_ACTIVE_SQL:
_SELECT_ACTIVE_SQL = """
SELECT * FROM signal_ledger
WHERE status IN ('pending', 'active', 'regime_suppressed')
ORDER BY timestamp DESC
"""
```

**Shadow signal handling in `_evaluate_signals_against_bar()`:**
```python
# In the loop over relevant signals:
status = sig.get("status")

if status == "regime_suppressed":
    # Skip zone-activation logic (always considered "active" for MAE/MFE)
    # Evaluate for stop/target/TTL directly as if active
    # The lifecycle_tracker.evaluate_signal() needs status == "active" to check exits
    # Inject status override for the evaluation:
    sig_for_eval = {**sig, "status": "active"}
    transition = evaluate_signal(sig_for_eval, high=..., low=..., close=..., ...)
    # But on actual DB write: status stays "regime_suppressed" until exit
    # On exit: write to DB with appropriate final status (same as active exits)
    ...
elif status == "pending":
    # existing zone-activation check path
    ...
elif status == "active":
    # existing active exit check path
    ...
```

**Alternative approach:** Initialize shadow signals into `_mae` and `_mfe` at startup with `0.0` values, then process them through the active-exit path of `evaluate_signal()` with a status override. This is cleaner than branching on every bar.

### Anti-Patterns to Avoid

- **Silently dropping suppressed signals:** Current behavior in aggregator that this phase replaces. Shadow signals MUST flow through to `all_ranked` and be persisted.
- **Applying regime gate before setup logic runs:** Setup logic must run fully first; gate decision is made after all signals have computed.
- **Gating on same-TF HMM:** SIGINT-04 explicitly forbids this. Always use the `_REGIME_AUTHORITY_TF` map.
- **Updating `_regime_cache` only for 5m+ events:** The cache must be updated for ALL timeframes on every event arrival so higher-TF entries are always fresh.
- **Changing shadow signal status to `active`:** Shadow signals never become `active`. Their status is `regime_suppressed` until exit, at which point the exit status reflects the counterfactual outcome.
- **Writing `was_selected=True` for a regime-suppressed signal:** A suppressed signal can never be the selected signal. `was_selected` should always be `False` for regime_suppressed entries.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HMM regime state | Custom regime tracker | Existing `SMCContext.hmm_regime/hmm_regime_prob/hmm_regime_duration` fields | Already computed by HMMRegimePlugin in I6 SMC tier; confirmed in schemas.py:496-501 |
| Plugin metadata registry | Separate REGIME_ELIGIBILITY dict | `regime_type` class attribute on each plugin | Self-documenting, no sync required, consistent with `name`/`capability_tags` pattern |
| Shadow signal TTL computation | New timer logic | Existing `_bars_elapsed()` and TTL check in `evaluate_signal()` | The lifecycle_tracker already handles TTL correctly via timestamp-based computation |
| New DB persistence layer | Custom shadow signal table | Existing `signal_ledger` with `status='regime_suppressed'` | Same schema, same queries, same P&L tracking — just a new status value |
| Regime probability smoothing | Custom smoothing filter | Use raw `hmm_regime_prob` from HMM plugin | HMMRegimePlugin already outputs calibrated probability; additional smoothing would duplicate effort |

---

## Common Pitfalls

### Pitfall 1: aggregate() Receives Empty all_ranked After Regime Filter

**What goes wrong:** Current gate code mutates the `signals` list with a list comprehension filter before the `active = [...]` filter. If all signals are regime-ineligible, `all_ranked` is empty and no ledger entries are written — shadow signals are lost.

**Why it happens:** The current `signals = [s for s in signals if ...]` drops non-eligible signals before they can become `all_ranked`. Shadow signals need to remain in the list but be tagged as ineligible.

**How to avoid:** Do not filter signals out of the list. Instead, tag each signal with `regime_eligible=True/False` and `suppression_reason`. Then `active = [s for s in signals if s.get("direction", 0) != 0 and s.get("signal_type") != "none"]` works correctly for active signal selection, while shadow signals (direction != 0 but regime_eligible=False) flow into `all_ranked` through the build path.

**Warning signs:** `result.all_ranked` is empty even though plugins fired. No regime_suppressed rows appear in signal_ledger.

### Pitfall 2: aggregate() Passes Suppressed Signals to CIS Scorer

**What goes wrong:** The CIS scorer runs on `plugin_outputs` built from ALL signals (line 113: `plugin_outputs = {s["setup_plugin"]: s for s in signals}`). If shadow signals are included, the CIS bucket scores are computed with suppressed plugin context — this may be acceptable or undesirable depending on perspective.

**Why it happens:** CIS runs before the regime filter. In the current code order: regime filter → build plugin_outputs → run CIS. In the new code, tagging replaces filtering, so suppressed signals remain in the list passed to CIS.

**How to avoid:** This is a judgment call. Since CIS reads market features (not signal dicts directly for its bucket computations), including suppressed signals in `plugin_outputs` has minimal impact. Document the choice and leave CIS behavior unchanged. If CIS direction conflicts with regime gate, the regime gate wins (suppressed signals never become `selected_signal`).

### Pitfall 3: `_regime_cache` Not Populated at Service Start

**What goes wrong:** On service startup, `_regime_cache` is empty. The first 1m bars processed have no 5m HMM data yet. The gate is skipped entirely (correct per CONTEXT.md: skip gate if cache entry missing). However, if the service restarts after 4h of operation, the cache is cleared and the first few bars processed after restart will skip the gate even if 5m data is arriving in the stream.

**Why it happens:** `defaultdict(dict)` starts empty on every service instantiation. No cache warm-up from Redis or DB is performed.

**How to avoid:** This is acceptable by design — "don't suppress on absent data." The cost is a few unfiltered signals per restart. Document this in service docstring. The alternative (pre-loading cache from stream history) adds complexity not worth the benefit for a service restart that takes < 1 minute to warm up naturally.

### Pitfall 4: regime_type Attribute Missing on a Plugin (Defaulting Silently)

**What goes wrong:** If a developer adds a new I7 plugin without `regime_type`, `getattr(plugin, "regime_type", "any")` silently defaults to `"any"` — the new plugin is unintentionally exempt from regime gating. No startup crash, no warning.

**Why it happens:** `getattr` with a default is permissive by design.

**How to avoid:** Add a `registry.validate_tier()` check or a separate validation function that asserts all I7 plugins have `regime_type` set to one of the allowed values. Best place: in the existing `registry.validate_tier(I7_PLUGINS, "I7")` call in signal_generator_service, or a new validation step at the aggregator module level. At minimum, document the expectation in `src/intelligence/CLAUDE.md`.

### Pitfall 5: Shadow Signals Triggering Zone-Activation in Lifecycle Service

**What goes wrong:** If `status='regime_suppressed'` is added to the lifecycle query but the zone-activation check is not skipped for those signals, the lifecycle service will wait for zone entry before starting MAE/MFE tracking. Shadow signals that never touch the zone will expire with `outcome='never_activated'` — incorrect, they should be evaluated from bar close.

**Why it happens:** The lifecycle service applies the same evaluation path to all non-expired signals regardless of status.

**How to avoid:** In `_evaluate_signals_against_bar()`, branch on `sig.get("status") == "regime_suppressed"` before calling `evaluate_signal()`. For shadow signals, inject `status="active"` into the dict passed to `evaluate_signal()` so it takes the active-exit path directly. Track their MAE/MFE from first bar (initialize `_mae[sid] = 0.0`, `_mfe[sid] = 0.0` immediately, not waiting for activation transition).

### Pitfall 6: to_insert_params() Tuple Length Mismatch

**What goes wrong:** `signal_ledger.py:to_insert_params()` returns a fixed-length tuple matched to the INSERT SQL. No new columns are being added to signal_ledger in Phase 12 — `regime_eligible` and `suppression_reason` are signal dict metadata consumed by the service, not stored as separate DB columns. If someone tries to add DB columns for these, the tuple length must match.

**Why it happens:** The `was_selected` field already conveys selection status; `status='regime_suppressed'` conveys suppression; `suppression_reason` would be a useful addition but is not in scope per CONTEXT.md.

**How to avoid:** Phase 12 does NOT add new DB columns. The `suppression_reason` is encoded implicitly in `status='regime_suppressed'` and in existing `regime_context` field if needed. Confirm: `to_insert_params()` currently returns 36 elements (confirmed from test_signal_ledger.py:165) and this does not change in Phase 12.

---

## Code Examples

### Existing Plugin Dataclass Pattern (confirmed from trend_following.py)

```python
# Source: src/intelligence/trading/trend_following.py
@dataclass
class TrendFollowingPlugin:
    name: str = "trad_TrendFollowing"
    outputs: frozenset[str] = frozenset({...})
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "trend"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    regime_threshold: float = 0.5
    # ... other numeric attrs
    _state: dict = field(default_factory=dict)
    # NEW: regime_type follows exactly this pattern
    regime_type: str = "trend"
```

### Existing Aggregator Gate Block (confirmed from aggregator.py:93-110)

```python
# Source: src/intelligence/trading/aggregator.py (CURRENT — to be replaced)
if features is not None:
    hmm_regime = features.get("hmm_regime")
    hmm_regime_prob = features.get("hmm_regime_prob", 0.0)
    hmm_regime_duration = features.get("hmm_regime_duration", 0)
    regime_gate_active = (
        hmm_regime is not None
        and float(hmm_regime_prob) >= _REGIME_PROB_MIN  # currently 0.55
        and int(hmm_regime_duration) >= _REGIME_DUR_MIN  # currently 3
    )
    if regime_gate_active:
        current_regime = int(hmm_regime)
        signals = [
            s for s in signals
            if s.get("setup_plugin") not in REGIME_ELIGIBILITY
            or current_regime in REGIME_ELIGIBILITY[s["setup_plugin"]]
        ]
```

### Existing Signal_ledger get_active_signals SQL (confirmed from signal_ledger.py:173-183)

```python
# Source: src/intelligence/trading/signal_ledger.py (CURRENT — to be extended)
_SELECT_ACTIVE_SQL = """
SELECT * FROM signal_ledger
WHERE status IN ('pending', 'active')
ORDER BY timestamp DESC
"""
# Phase 12 change: add 'regime_suppressed' to the IN clause
```

### Existing _process_single_message (confirmed from signal_generator_service.py:588-638)

```python
# Source: services/signal_generator_service.py (CURRENT)
async def _process_single_message(self, symbol, timeframe, fields, stream_name, message_id):
    event = _parse_intelligence_event(fields)
    # ... parse bar, features
    # Phase 12: ADD cache update here
    # smc = event.smc
    # if smc.hmm_regime is not None:
    #     self._regime_cache[symbol][timeframe] = {
    #         "hmm_regime": smc.hmm_regime,
    #         "hmm_regime_prob": smc.hmm_regime_prob or 0.0,
    #         "hmm_regime_duration": smc.hmm_regime_duration or 0,
    #     }
    await self._process_bar(symbol, timeframe, bar, features, frames, timestamp, ...)
```

### Existing _evaluate_signals_against_bar loop (confirmed from signal_lifecycle_service.py:163-289)

```python
# Source: services/signal_lifecycle_service.py (relevant section)
for sig in relevant:
    sid = str(sig["signal_id"])
    # ...
    transition = evaluate_signal(sig_with_extras, high=..., low=..., close=..., ...)
    if transition is None:
        # Update in-memory MAE/MFE for active signals
        if sig.get("status") == "active":
            # ... MAE/MFE update
    # Phase 12: also update MAE/MFE if status == "regime_suppressed"
    # Phase 12: skip zone-activation for regime_suppressed; pass status="active" to evaluate_signal
```

---

## State of the Art

| Old Approach | Current Approach | Phase 12 Change |
|--------------|-----------------|-----------------|
| `REGIME_ELIGIBILITY` dict (6 plugins) | Dict lookup in aggregate() | Plugin class attribute `regime_type`; dict deleted |
| Silent drop of ineligible signals | Filter list comprehension | Tag signals; pass all to `all_ranked`; suppress in DB via status |
| Same-TF HMM gating | Same-TF features passed to aggregate() | Higher-TF `_regime_cache` lookup per signal TF |
| `_REGIME_PROB_MIN = 0.55` | Current threshold | Raised to `0.60` |
| `_REGIME_DUR_MIN = 3` | Current threshold | Raised to `5` |
| No shadow signal tracking | No counterfactual data | `status='regime_suppressed'` + lifecycle MAE/MFE/outcome |
| `get_active_signals()` queries `('pending', 'active')` | Current | Add `'regime_suppressed'` to query |

---

## Open Questions

1. **suppression_reason storage in signal_ledger**
   - What we know: `status='regime_suppressed'` encodes that suppression happened, but not why (regime_type vs. regime_prob vs. regime_duration)
   - What's unclear: Whether a `suppression_reason TEXT` column should be added to signal_ledger to enable per-reason analytics
   - Recommendation: CONTEXT.md says "Aggregator excludes ineligible signals from selection but records them in signal_ledger with `status='regime_suppressed'`" — this suggests status is the primary field. Adding suppression_reason as a DB column would enable `WHERE suppression_reason = 'regime_prob'` queries for threshold tuning. Suggest adding it as a nullable TEXT column in Phase 12 migration since it's lightweight and high analytical value. However, it's not in the locked decisions, so it's Claude's discretion.

2. **4h/1d regime authority when streams not subscribed**
   - What we know: signal_generator subscribes to `["1m", "5m", "15m", "1h"]` only; 4h/1d intelligence streams are not in `_stream_map`
   - What's unclear: Whether 4h/1d intelligence events are published at all (market_analysis_service may compute them)
   - Recommendation: Per CONTEXT.md, "if cache entry missing, skip gate." For 1h signals, the authority is 4h HMM — if not subscribed, the 1h gate is always skipped. This is acceptable. Document in code comment. Adding 4h/1d subscription is deferred to backlog.

3. **regime_type validation at startup**
   - What we know: `getattr(plugin, "regime_type", "any")` silently defaults if attribute missing
   - What's unclear: Whether to add explicit validation
   - Recommendation: Add a simple assertion loop after `register_all_plugins()` in signal_generator_service, logging a WARNING (not crash) if any I7 plugin lacks `regime_type`. This is low-cost and prevents silent misconfiguration.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest with asyncio-mode=auto |
| Config file | `pytest.ini` (project root) |
| Quick run command | `.venv/bin/pytest tests/unit/intelligence/test_aggregator.py -v -m unit` |
| Full suite command | `.venv/bin/pytest tests/unit/ -v -m unit` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SIGINT-01 | Trend plugin suppressed in regime=0; mean-reversion suppressed in regime 1/2 | unit | `.venv/bin/pytest tests/unit/intelligence/test_aggregator.py -k "regime" -v` | ✅ (TestRegimeEligibilityFilter exists, needs update) |
| SIGINT-01 | All 17 plugins have `regime_type` attribute with valid value | unit | `.venv/bin/pytest tests/unit/intelligence/test_i7_registration.py -v` | ✅ (needs new test added) |
| SIGINT-02 | Gate skipped when hmm_regime_prob < 0.60 (new threshold) | unit | `.venv/bin/pytest tests/unit/intelligence/test_aggregator.py -k "prob" -v` | ✅ (test_gate_bypassed_when_regime_prob_low needs threshold update to 0.60) |
| SIGINT-03 | Gate skipped when hmm_regime_duration < 5 (new threshold) | unit | `.venv/bin/pytest tests/unit/intelligence/test_aggregator.py -k "duration" -v` | ✅ (test_gate_bypassed_when_regime_duration_short needs threshold update to 5) |
| SIGINT-04 | aggregate() receives higher-TF regime data, not same-TF | unit | `.venv/bin/pytest tests/unit/intelligence/test_aggregator.py -v` | ✅ (new test needed: regime from cache, not features) |
| SIGINT-05 | Suppressed signals appear in all_ranked with regime_eligible=False | unit | `.venv/bin/pytest tests/unit/intelligence/test_aggregator.py -k "shadow" -v` | ❌ Wave 0 |
| SIGINT-05 | build_ledger_entries sets status='regime_suppressed' for ineligible signals | unit | `.venv/bin/pytest tests/unit/service_tests/ -k "ledger" -v` | ❌ Wave 0 |
| SIGINT-05 | get_active_signals query includes regime_suppressed status | unit | `.venv/bin/pytest tests/unit/intelligence/test_signal_ledger.py -k "active" -v` | ✅ (TestGetActiveSignals needs assertion update) |
| SIGINT-05 | Lifecycle service skips zone-activation for regime_suppressed signals | unit | `.venv/bin/pytest tests/unit/intelligence/ -k "shadow" -v` | ❌ Wave 0 |

### Existing Tests Requiring Updates (NOT new files)

| File | Test | Change Required |
|------|------|----------------|
| `tests/unit/intelligence/test_aggregator.py:TestRegimeEligibilityFilter` | `test_gate_bypassed_when_regime_prob_low` | Change probe value from 0.50 to 0.54 (below new threshold 0.60) |
| `tests/unit/intelligence/test_aggregator.py:TestRegimeEligibilityFilter` | `test_gate_bypassed_when_regime_duration_short` | Change duration from 2 to 4 (below new threshold 5) |
| `tests/unit/intelligence/test_aggregator.py:TestRegimeEligibilityFilter` | All tests that import `REGIME_ELIGIBILITY` | Update to import nothing (dict deleted) or `_REGIME_PROB_MIN` / `_REGIME_DUR_MIN` |
| `tests/unit/intelligence/test_signal_ledger.py:TestGetActiveSignals` | `test_returns_entries` | Add regime_suppressed to expected returnable statuses |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/intelligence/test_aggregator.py tests/unit/intelligence/test_i7_registration.py tests/unit/intelligence/test_signal_ledger.py -v -m unit`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -m unit`
- **Phase gate:** Full unit suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/unit/intelligence/test_aggregator.py` — add `TestShadowSignals` class covering: suppressed signals in all_ranked, regime_eligible=False flag, suppression_reason values, shadow signals DO have direction/entry/stop populated
- [ ] `tests/unit/intelligence/test_signal_ledger.py` — add test: `build_ledger_entries` with regime_suppressed signals writes `status='regime_suppressed'`
- [ ] `tests/unit/intelligence/test_lifecycle_shadow.py` — new file: shadow signal virtual-activation (no zone check), MAE/MFE tracking from bar 0, status stays `regime_suppressed` until TTL

*(Existing test infrastructure covers pytest config, asyncio, and fixtures — no framework install needed)*

---

## Sources

### Primary (HIGH confidence)
- Direct code inspection: `src/intelligence/trading/aggregator.py` — existing REGIME_ELIGIBILITY, _REGIME_PROB_MIN, _REGIME_DUR_MIN, aggregate() gate block
- Direct code inspection: `src/intelligence/trading/signal_ledger.py` — LedgerEntry schema, INSERT SQL, _SELECT_ACTIVE_SQL, to_insert_params() 36-element tuple
- Direct code inspection: `services/signal_generator_service.py` — _process_single_message(), _process_bar(), build_ledger_entries(), _stream_map (1m/5m/15m/1h only)
- Direct code inspection: `services/signal_lifecycle_service.py` — _evaluate_signals_against_bar(), MAE/MFE tracking, zone-activation path
- Direct code inspection: `src/intelligence/schemas.py:496-501` — SMCContext.hmm_regime, hmm_regime_prob, hmm_regime_duration field definitions
- Direct code inspection: `src/intelligence/trading/trend_following.py` — plugin dataclass pattern (confirmed regime_type attribute follows existing name/capability_tags pattern)
- Direct code inspection: `src/intelligence/trading/lifecycle_tracker.py` — evaluate_signal() signature, Transition dataclass, status branching
- Direct code inspection: `src/intelligence/register_plugins.py:293-311` — TIER_I7 list (17 plugins confirmed)
- Direct code inspection: `tests/unit/intelligence/test_aggregator.py` — existing TestRegimeEligibilityFilter tests and probe values (0.55/3 thresholds confirmed)
- Direct code inspection: `tests/unit/intelligence/test_signal_ledger.py:165` — to_insert_params() length confirmed as 36
- Direct code inspection: `pytest.ini` — asyncio-mode=auto, unit marker, test path configuration

### Secondary (MEDIUM confidence)
- `.planning/phases/12-signal-integrity/12-CONTEXT.md` — locked decisions, regime map, shadow signal mechanics (authoritative user decisions)
- `.planning/REQUIREMENTS.md` — SIGINT-01..05 full text with success criteria

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all components verified by direct code inspection
- Architecture patterns: HIGH — patterns derived from reading actual implementation files
- Pitfalls: HIGH — pitfalls derived from reading existing code's edge cases (current gate logic, existing status machine, etc.)
- Test mapping: HIGH — existing test file structure confirmed; Wave 0 gaps identified by absence

**Research date:** 2026-03-04
**Valid until:** 2026-04-04 (stable codebase — no external dependencies in scope)
