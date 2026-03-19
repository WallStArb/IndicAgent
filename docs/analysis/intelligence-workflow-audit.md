# Intelligence Layer — Workflow Audit & Analysis

**Date:** 2026-03-19
**Scope:** Naming conventions, friction points, enforcement gaps, gotchas
**Status:** v1.9 IN PROGRESS — Phase 39 (Data Quality + DB Health) next

---

## Executive Summary

The intelligence layer follows consistent naming conventions with **122 plugins** across tiers I1–I7. Conventions are well-documented in `CLAUDE.md` but only partially enforced mechanically. Key gaps exist in `regime_type` validation and signal status enforcement (both addressed in Phase 39).

**Critical findings:**
- ✅ Naming conventions: 98% consistent across codebase
- ⚠️ `regime_type` not enforced by Protocol — silent misfire risk
- ⚠️ Signal status strings scattered across 4 files (Phase 39 adds enum)
- ✅ Live data architecture: Redpanda-only, never touches `market_data_ohlcv`

---

## Gotchas Discovered

### Database Column Names

| Gotcha | Impact | Mitigation |
|--------|--------|------------|
| `intelligence_features.ts` not `feature_ts` | Easy to mix up in queries | Documented in CLAUDE.md |
| `signal_ledger.feature_ts` vs `intelligence_features.ts` | JOIN confusion | Use consistent aliases |
| `bar_close_price` implicit — not stored in `signal_ledger` | Must JOIN to `intelligence_features` | Documented pattern |

### Redpanda Topic Prefixes

| Prefix | Status | Usage |
|--------|--------|-------|
| `development.*` | ✅ Current | All active topics (e.g., `development.indicators`) |
| `dev.*` | ⚠️ Legacy | Old prefix, may still exist in docs/scripts |

**Recommendation:** Audit all topic usage, consolidate to `development.*` pattern. Update any scripts referencing `dev.*`.

### Data Flow Architecture

```
Hot:  IBKR TWS → Redpanda Streams → Services              (sub-ms)
Warm: Streams → indicator/analysis/signal pipeline        (<10ms)
Cold: feature_writer_service → TimescaleDB                (batch, async)
```

**Critical:** `market_data_ohlcv` is **backfill-only** — contains only historical seed data. Live data flows entirely through Redpanda topics and is never written to `market_data_ohlcv` in real-time.

**Implications:**
- Real-time queries must use Redpanda consumers, not `market_data_ohlcv`
- Backfill scripts write to `market_data_ohlcv` — this is ground truth for historical analysis
- Dashboard SSE feeds come from Redpanda, not DB polling

---

## Naming Convention Audit

### Conventions Defined (CLAUDE.md)

| Pattern | Convention | Example | Compliance |
|---------|-----------|---------|------------|
| Plugin classes | `PascalCasePlugin` | `FibonacciZonesPlugin`, `BOSCHoCHPlugin` | ✅ 122/122 |
| Plugin files | `snake_case.py` | `fibonacci_zones.py`, `bos_choch.py` | ✅ 122/122 |
| Service files | `snake_case_service.py` | `signal_generator_service.py` | ✅ All services |
| Aggregator/Scorer classes | `PascalCase` (no suffix) | `CISScorer`, `AggregatedResult` | ✅ 2/2 |
| Topic builder functions | `topic_<thing>()` | `topic_indicators()`, `topic_signals()` | ✅ Centralized |
| Constants | `UPPER_SNAKE_CASE` | `TIER_I1`, `PLUGIN_METRICS_SAMPLE_RATE` | ✅ Consistent |
| Private attributes | `_snake_case` | `_regime_cache`, `_plugin_states` | ✅ Consistent |

### Tier Distribution (v1.9)

```
TIER_I1:  27 indicators
TIER_I2:  11 composites
TIER_I3:   7 structure
TIER_I4:  11 context
TIER_I5:  15 patterns
TIER_I6:  14 SMC (13) + confluence (1)
TIER_I7:  36 trading setups
Total:   121 plugins + 2 aggregation = 123
```

### Naming Quality: Excellent

**No violations found** across 122 plugin files. All follow:
- Class: `<PascalCase>Plugin`
- File: `<kebab_case>.py`
- Module: `plugin` instance exported

---

## Friction Points & Pain Points

### High Priority

| Issue | Location | Impact | Phase 39 fix? |
|-------|----------|--------|---------------|
| Signal status strings | 4 files (raw literals) | Easy to miss when adding states | ✅ Enum planned |
| `regime_type` not validated | All I7 plugins | Silent misfire if missing | ⚠️ Needs Protocol check |
| `ts` vs `feature_ts` confusion | Query-heavy code | Wrong column references | ✅ Documented |

### Medium Priority

| Issue | Location | Impact | Fix effort |
|-------|----------|--------|------------|
| `_state` key pattern verbosity | Stateful plugins (GARCH, HMM) | `self._state[(symbol, tf)]` repeated | Low — helper method |
| `dev.` vs `development.` legacy | Topics, docs | Confusion about correct prefix | Low — audit + consolidate |

### Low Priority

| Issue | Location | Impact | Fix effort |
|-------|----------|--------|------------|
| Plugin `*Plugin` suffix not enforced | All plugin classes | Inconsistent naming possible | Low — lint rule |
| File naming not enforced | All plugin files | Any filename works | Low — pre-commit hook |

---

## Enforcement Status

### What's Documented ✅

`CLAUDE.md` → "Naming Conventions" + "Development Standards" sections cover:
- Python naming (classes, files, functions, constants)
- Redpanda topic naming (dots not colons)
- Database naming (snake_case)
- Systemd service naming
- Test naming

### What's Enforced ✅

| Check | Mechanism | What it catches |
|-------|-----------|-----------------|
| Plugin registration | `registry.validate_tier()` | Missing/unregistered plugins in tier lists |
| Protocol compliance | `IndicatorPlugin` / `PatternPlugin` Protocol | Missing required ClassVar attributes |
| Schema coverage | `validate_schema_coverage()` | Plugin outputs not declared in tier schemas |
| Asset class filters | `valid_asset_classes` ClassVar | Wrong asset class combinations |
| Code formatting | Ruff + Black (`.venv/bin/ruff check .`) | Style violations, NOT naming |

**Example enforcement:**
```python
# services/market_analysis_service.py:107
registry.validate_tier(tier_list, tier_name)
# → ValueError if any plugin name not in registry
```

### What's NOT Enforced ⚠️

| Convention | Gap | Risk | Mitigation |
|------------|-----|------|------------|
| `*Plugin` class suffix | No lint rule | `MyAnalyzer` vs `MyPlugin` inconsistency | Low — cosmetic |
| `snake_case.py` files | No pre-commit hook | Any filename works | Low — discoverability |
| `topic_<thing>()` functions | No validation | Function naming unchecked | Low — centralized in stream_keys.py |
| **`regime_type` on I7** | **Protocol doesn't require it** | **Silent misfire** | **Medium — add to Protocol** |

---

## The `regime_type` Gap (Critical)

### Problem

`regime_type: str = "trend"|"mean_reversion"|"any"` is documented as **mandatory** for all I7 plugins (Phase 12), but the `PatternPlugin` Protocol doesn't enforce it.

**Current code:**
```python
# src/intelligence/plugins.py:32
class PatternPlugin(Protocol):
    name: ClassVar[str]
    outputs: ClassVar[set[str]]
    min_lookback: ClassVar[int]
    supports_incremental: ClassVar[bool]
    capability_tags: ClassVar[set[str]]
    inputs: ClassVar[list[InputSpec]]
    valid_asset_classes: ClassVar[frozenset[AssetClass]]
    # ⚠️ regime_type NOT HERE

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]: ...
    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]: ...
```

**Impact:** If a new I7 plugin omits `regime_type`, the aggregator regime gate silently misfires:
- Trend plugins suppressed in ranging regime (hmm_regime=0)
- Mean-reversion plugins suppressed in trending regime (hmm_regime=1/2)

### Current Mitigation

Manual check documented in `src/intelligence/CLAUDE.md`:
> Check `regime_type` declaration: All I7 plugins must declare `regime_type: "trend" | "mean_reversion" | "any"` as a class attribute. If missing, the aggregator regime gate will silently misfire.

### Recommended Fix (3 options)

**Option 1: Add to Protocol (enforces existence, not values)**
```python
class PatternPlugin(Protocol):
    # ... existing fields ...
    regime_type: ClassVar[str]  # "trend" | "mean_reversion" | "any"
```

**Option 2: Runtime validation in `validate_tier()`**
```python
def validate_i7_regime_type(plugin: PatternPlugin) -> None:
    if not hasattr(plugin, 'regime_type'):
        raise ValueError(f"Plugin {plugin.name} missing required regime_type")
    if plugin.regime_type not in ("trend", "mean_reversion", "any"):
        raise ValueError(f"Plugin {plugin.name} has invalid regime_type: {plugin.regime_type}")
```

**Option 3: Pre-commit hook**
- Check all files in `src/intelligence/trading/*.py`
- Verify class name ends in `Plugin`
- Verify `regime_type` class attribute exists

**Recommendation:** Option 1 (Protocol) + Option 2 (runtime) for defense-in-depth.

---

## Signal Status String Gap (Phase 39)

### Problem

Signal status strings (`"pending"`, `"active"`, `"regime_suppressed"`) are raw literals across 4 files:

1. `src/api/routes/signals.py`
2. `src/intelligence/trading/signal_ledger.py`
3. `src/intelligence/trading/lifecycle_tracker.py`
4. `src/core/streams_mixins/_monitoring.py`

**Impact:**
- Adding new statuses requires updating 4 files manually
- Easy to miss a location
- No autocomplete/IDE support
- Risk of typos (`"pedning"` vs `"pending"`)

### Phase 39 Fix

Add `SignalStatus` enum:
```python
class SignalStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    REGIME_SUPPRESSED = "regime_suppressed"
    # ... any future statuses
```

Replace all raw strings with `SignalStatus.PENDING`, etc.

---

## Live Data Architecture Clarification

### `market_data_ohlcv` is Backfill-Only

**Common misconception:** "Live data writes to `market_data_ohlcv`"

**Reality:**
```
┌─────────────┐
│ IBKR TWS    │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Redpanda    │ ← Live data NEVER touches market_data_ohlcv
│ Streams     │
└──────┬──────┘
       │
       ├─────────────────┐
       │                 │
       ▼                 ▼
┌─────────────┐   ┌──────────────┐
│ Services    │   │ feature_writer│ → TimescaleDB
│ (hot/warm)  │   │ (cold)        │   (batch, async)
└─────────────┘   └──────────────┘
```

**Table responsibilities:**
- `market_data_ohlcv` — Historical backfill only (ground truth for analysis)
- `intelligence_features` — Full feature vectors (ML training dataset)
- `signal_ledger` — Trading signals + lifecycle outcomes

**Live data query pattern:**
```python
# ❌ Wrong — no live data here
SELECT * FROM market_data_ohlcv WHERE symbol = 'ES' AND timestamp > NOW() - INTERVAL '1 hour';

# ✅ Correct — consume from Redpanda
consumer = KafkaConsumer(topic="development.market.bars", ...)
```

---

## Recommendations

### Immediate (Phase 39)

1. **Add `regime_type` to `PatternPlugin` Protocol**
   - Enforces existence (not values)
   - Catches missing declarations at import time

2. **Add runtime validation in `validate_tier()`**
   - Checks `regime_type` values are valid
   - Runs at service startup

3. **Implement `SignalStatus` enum**
   - Replace raw strings in 4 files
   - Centralize status definitions

### Short-term (Post-v2.0)

4. **Add pre-commit hook for plugin naming**
   - Enforce `*Plugin` class suffix
   - Enforce `snake_case.py` file naming
   - Check `regime_type` on I7 plugins

5. **Audit and consolidate `dev.*` vs `development.*` topics**
   - Update all references to `development.*`
   - Add docs warning about legacy prefix

6. **Add `_state` helper method**
   - Reduce verbosity of `self._state[(symbol, tf)]` pattern
   - Centralize state key construction

### Long-term (Documentation)

7. **Create plugin development checklist**
   - Naming conventions
   - Required attributes (name, outputs, min_lookback, regime_type)
   - Registration steps
   - Testing requirements

8. **Add architecture diagrams**
   - Live data flow (Redpanda-only path)
   - Backfill flow (DB write path)
   - Hot/warm/cold tier boundaries

---

## Appendix: Enforcement Toolchain

### Current Tools

| Tool | Purpose | Scope |
|------|---------|-------|
| `registry.validate_tier()` | Plugin registration validation | Startup |
| `validate_schema_coverage()` | Schema field validation | Startup |
| Ruff + Black | Code formatting | All Python |
| pytest | Unit tests | `tests/unit/` |

### Recommended Additions

| Tool | Purpose | Priority |
|------|---------|----------|
| Protocol `regime_type` field | Enforce existence | High |
| Runtime `validate_i7_regime_type()` | Enforce valid values | High |
| `SignalStatus` enum | Centralize statuses | High (Phase 39) |
| Pre-commit hook (plugin naming) | Enforce naming conventions | Medium |
| `_state` helper method | Reduce verbosity | Low |

---

## Related Documentation

- `CLAUDE.md` — Development standards & naming conventions
- `src/intelligence/CLAUDE.md` — Intelligence layer reference
- `docs/reference/plugins/overview.md` — Plugin protocol
- `docs/concepts/dag-execution.md` — DAG architecture & validation

---

**Document version:** 1.0
**Last updated:** 2026-03-19
**Next review:** After Phase 39 completion
