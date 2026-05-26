# Phase 100: Plugin Shared Infrastructure - Research

**Researched:** 2026-05-21
**Domain:** Plugin architecture, incremental computation, state management
**Confidence:** HIGH

## Summary

Phase 100 addresses technical debt across 132 plugins (I1-I7 tiers) by extracting shared utilities and introducing a targeted `IncrementalMixin` for the 31 genuine incremental plugins. A comprehensive design document already exists at `docs/plans/2026-05-21-plugin-infrastructure-design.md`, containing detailed analysis of all plugins, state archetype clustering, and migration strategy.

The research confirms the design doc's key findings: 34 plugins claim incremental support, but only 31 have genuine incremental logic. State shapes cluster into 7 archetypes, with 5 HIGH-severity bugs already identified where incremental computation is silently broken or crashes. The current Protocol + dataclass design is optimal for 98 non-incremental plugins, but incremental plugins need a mixin to prevent state-related bugs.

**Primary recommendation:** Execute the design doc's phased approach: (A) fix 5 HIGH bugs, (B) add conformance tests, (C) introduce `IncrementalMixin` for 6 easy plugins first, then expand to remaining incremental plugins. Shared utilities (`wilders_update`, `update_ema`, `get_main_df`) can be extracted in parallel with zero risk.

## Standard Stack

### Core Infrastructure
| Component | Version | Purpose | Why Standard |
|-----------|---------|---------|--------------|
| **Protocol classes** | (`IndicatorPlugin`, `PatternPlugin`) | Structural typing without inheritance | Current design - already optimal for 98 plugins |
| **dataclass plugins** | Python 3.11+ | Plugin instances with config fields | Current design - enables duck typing |
| **PluginRegistry** | `src/intelligence/plugins.py` | Central registration + validation | Current design - validates tier coverage |
| **CircuitBreaker** | `src/observability/circuit_breaker.py` | Per-plugin fault tolerance | Current design - already integrated |
| **PluginExecutor** | `src/intelligence/pipeline/executor.py` | Thread pool execution + state management | Current design - PERF-03 state-as-parameter pattern |

### New Components (Phase 100)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **IncrementalMixin** | New | Enforce state contract for incremental plugins | For 31 genuine incremental plugins |
| **Shared utility functions** | New | Extract common patterns (Wilder's EMA, OHLCV extraction) | For all 132 plugins incrementally |

### NOT Using
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Protocol + dataclass | Full ABC with base class | Protocol is simpler - no inheritance hierarchy |
| Targeted mixin | Generic IncrementalPlugin[TState] | Mixin captures 100% of bug prevention with 20% complexity |
| Per-plugin migration | Big-bang refactor | Incremental adoption - zero blast radius |

**Installation:**
```bash
# No new dependencies - pure Python refactoring
# Existing tests: pytest tests/unit/intelligence/test_plugin_incremental.py
```

## Architecture Patterns

### Current Plugin Architecture

**Plugin Protocol (src/intelligence/plugins.py):**
```python
class IndicatorPlugin(Protocol):
    name: ClassVar[str]
    outputs: ClassVar[set[str]]
    min_lookback: ClassVar[int]
    supports_incremental: ClassVar[bool]
    capability_tags: ClassVar[set[str]]
    inputs: ClassVar[list[InputSpec]]
    
    def compute_full(frames: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]: ...
    def compute_next(windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]: ...
```

**Executor dispatch (src/intelligence/pipeline/executor.py:80-112):**
```python
def _timed_plugin_call(plugin, frames, state: dict) -> Any:
    """Incremental compute_next() when supported and has state, else compute_full()."""
    if getattr(plugin, "supports_incremental", False) and state:
        result = plugin.compute_next(frames, state=state)
    else:
        result = plugin.compute_full(frames)
    
    # Renaissance validation: incremental plugins MUST return _state
    if getattr(plugin, "supports_incremental", False) and isinstance(result, dict):
        if "_state" not in result:
            raise ValueError(f"{plugin.name}: incremental plugins MUST return _state")
    
    return result, duration_ms
```

### Recommended Project Structure
```
src/intelligence/
├── plugins/
│   ├── base.py                    # Protocol classes (unchanged)
│   └── mixins.py                  # NEW: IncrementalMixin, shared utilities
├── features/
│   ├── i1_indicators/             # 28 plugins (migrate to shared utils)
│   ├── i2_composites/             # 10 plugins
│   ├── i3_structure/              # 8 plugins (MarketProfile, SessionLevels)
│   └── ...
└── pipeline/
    ├── executor.py                # PERF-03 state-as-parameter (unchanged)
    └── state_manager.py           # Checkpoint/restore (unchanged)
```

### Pattern 1: IncrementalMixin (NEW)

**What:** Enforce state contract for 31 genuine incremental plugins
**When to use:** Plugins with `supports_incremental=True` and genuine stateful logic
**Example:**
```python
class IncrementalMixin:
    """Owns fallback-to-full and _state return contract.
    
    Plugins implement:
    - _compute_full_core(frames) -> dict          # pure outputs, no _state
    - _compute_next_core(frames, state) -> dict   # pure outputs, no _state
    - _seed_state(frames) -> dict                 # extract state from full computation
    
    The mixin provides compute_full() and compute_next() with:
    - Automatic state fallback (if not state -> compute_full)
    - Automatic _state attachment to output
    - State never None in _compute_next_core
    """
    
    def compute_full(self, frames, *, state=None):
        result = self._compute_full_core(frames)
        if not result:
            return {}
        result["_state"] = self._seed_state(frames)
        return result
    
    def compute_next(self, windows, *, state=None):
        if not state:
            return self.compute_full(windows)
        result = self._compute_next_core(windows, state)
        if isinstance(result, dict):
            result["_state"] = state
        return result
```

### Pattern 2: Shared Utility Functions (NEW)

**What:** Extract repeated patterns into module-level functions
**When to use:** Any plugin can adopt incrementally
**Example:**
```python
# src/intelligence/plugins/mixins.py

def wilders_update(prev: float, new_val: float, period: int) -> float:
    """Wilder's smoothing: (prev * (period-1) + new) / period."""
    return (prev * (period - 1) + new_val) / period

def update_ema(current: float, prev_ema: float, span: int) -> float:
    """EMA update: alpha * current + (1-alpha) * prev_ema, alpha=2/(span+1)."""
    alpha = 2.0 / (span + 1)
    return alpha * current + (1.0 - alpha) * prev_ema

def get_main_df(frames: dict, min_bars: int) -> pd.DataFrame | None:
    """Extract and validate main DataFrame. Returns None if insufficient data."""
    df = frames.get("main")
    if df is None or len(df) < min_bars:
        return None
    return df
```

### Anti-Patterns to Avoid
- **Base class with template method**: Current Protocol IS the template - no need for `_extract_inputs()` / `_compute()` / `_build_output()` hooks that split simple 50-line plugins into fragments
- **Full ABC for all 132 plugins**: 98 plugins don't need incremental logic - mixin targets only the 31 that do
- **Typed state dataclasses (Generic[TState])**: Too much machinery for 31 plugins - can add later as non-breaking enhancement

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| **Wilder's smoothing** | Inline arithmetic in 7+ plugins | `wilders_update()` function | Bug fixes touch one place (MFI bug was duplicate code) |
| **EMA updates** | Inline alpha calculation in ~17 plugins | `update_ema()` function | Same pattern in MACD, Bollinger, Keltner, PPO, 13 others |
| **OHLCV extraction** | `frames.get("main")` guards in every plugin | `get_main_df()` function | 35+ non-I7 plugins have identical validation logic |
| **State fallback** | Manual `if not state: return compute_full()` | `IncrementalMixin` | 5 HIGH bugs from missing state returns |
| **State threading** | `self._state` assignment before dispatch | PERF-03 `state=` parameter | Concurrency hazard - threadpool + shared instances = race condition |

**Key insight:** The design doc's analysis found 5 HIGH-severity bugs where incremental plugins either (1) read `self._state` instead of the `state` parameter, or (2) forget to return `_state` in `compute_next`. A mixin prevents both classes of bugs by owning the state contract entirely.

## Common Pitfalls

### Pitfall 1: State Parameter Shadowing
**What goes wrong:** Plugin writes `state = {}` at the start of `compute_next()`, shadowing the passed-in state parameter
**Why it happens:** Developer habit from pre-PERF-03 code when `self._state` was the only state
**How to avoid:** `IncrementalMixin` owns the state parameter - plugins only implement `_compute_next_core(frames, state)` where state is never None
**Warning signs:** Executor validation error: "incremental plugins MUST return _state in result dict"

### Pitfall 2: Missing `_state` Return
**What goes wrong:** `compute_next()` returns output dict without `_state` key - state not persisted
**Why it happens:** Plugin author forgets to add `result["_state"] = state` before returning
**How to avoid:** `IncrementalMixin` automatically attaches `_state` to output - plugins cannot forget
**Warning signs:** State manager checkpoints are empty, incremental values jump around

### Pitfall 3: `self._state` Concurrency Hazard
**What goes wrong:** Multiple threads read/write `plugin._state` during parallel execution - race condition
**Why it happens:** PERF-03 stopped assigning `plugin._state` before dispatch, but legacy plugins still read it
**How to avoid:** Lint gate forbids `self._state` in migrated plugins - conformance tests verify no writes
**Warning signs:** Inconsistent indicator values, test flakiness, crashes in incremental mode

### Pitfall 4: Delegation Plugins Claiming Incremental
**What goes wrong:** Plugin sets `supports_incremental=True` but `compute_next()` just calls `compute_full()`
**Why it happens:** Developer copied incremental flag without implementing incremental logic
**How to avoid:** Set `supports_incremental=False` on delegation plugins (CVD, OFI, MAComposite)
**Warning signs:** No performance benefit from incremental mode, `compute_next()` is one-line delegation

### Pitfall 5: Architecture Assumptions About State Shape
**What goes wrong:** Code assumes all incremental plugins have `{prev_close: float}` state
**Why it happens:** Documentation oversimplified the 7 state archetypes
**How to avoid:** Design doc correctly identifies 7 archetypes - migration is per-plugin, not per-archetype
**Warning signs:** Code tries to "extract common patterns" across incompatible state shapes

## Code Examples

Verified patterns from actual codebase:

### Current Working Pattern (ATR - correctly implemented)
```python
# src/intelligence/features/i1_indicators/atr.py

@dataclass
class ATRPlugin:
    name: str = "ATR"
    supports_incremental: bool = True
    periods: list[int] = None
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        # ... compute ATR using pandas ...
        out["_state"] = {  # ✅ Correct: returns state
            f"atr_{p}": {
                "prev_atr": float(val),
                "prev_close": float(close.iloc[-1]),
            }
        }
        return out

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        if not state:  # ✅ Correct: fallback to full
            return self.compute_full(windows)
        # ... incremental update using state parameter ...
        out["_state"] = state  # ✅ Correct: returns updated state
        return out
```

### Buggy Pattern (RSI - design doc finding)
```python
# src/intelligence/features/i1_indicators/rsi.py

def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
    if not self._state:  # ❌ BUG: reads self._state instead of state parameter
        return self.compute_full(windows)
    # ... uses self._state directly ...
    # ❌ BUG: never returns _state - incremental never activates
    return out
```

### IncrementalMixin Fix (proposed)
```python
# After applying IncrementalMixin

class RSIPlugin(IncrementalMixin):
    def _compute_full_core(self, frames: dict[str, Any]) -> dict[str, Any]:
        # ... pure computation, no state logic ...
        return {f"rsi_{p}": float(rsi[-1]) for p in self.periods}

    def _seed_state(self, frames: dict[str, Any]) -> dict[str, Any]:
        # ... extract Wilder's smoothing state ...
        return {f"rsi_{p}": {"avg_gain": up_val, "avg_loss": down_val, ...} ...}

    def _compute_next_core(self, windows: dict[str, Any], state: dict) -> dict[str, Any]:
        # ✅ state is guaranteed non-None
        # ✅ no fallback logic needed
        # ✅ no _state return needed
        return {f"rsi_{p}": calculate_rsi(state[p], ...) ...}
```

### Shared Utility Adoption (before/after)
```python
# BEFORE (duplicated in 7+ plugins)
up_val = (up_val * (period - 1) + max(delta, 0)) / period
down_val = (down_val * (period - 1) + max(-delta, 0)) / period

# AFTER (wilders_update function)
from src.intelligence.plugins.mixins import wilders_update
up_val = wilders_update(up_val, max(delta, 0), period)
down_val = wilders_update(down_val, max(-delta, 0), period)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `self._state` assignment before dispatch | PERF-03 state-as-parameter | Phase 089 | Fixed concurrency hazard, enabled incremental plugins |
| Manual state fallback validation | Executor enforces `_state` return | Phase 089 | Catches state corruption bugs early |
| Protocol + dataclass (optimal) | No change needed | Existing | Already optimal for 98 non-incremental plugins |
| IncrementalMixin (proposed) | Fix 5 HIGH bugs in incremental plugins | Phase 100 | Prevents state parameter shadowing, missing returns |

**Deprecated/outdated:**
- Pre-PERF-03 pattern: Plugin executor assigned `plugin._state` before threadpool dispatch → race condition across symbols/timeframes
- Big-bang refactor idea: "Rewrite all plugins to use base class" → Rejected in favor of incremental mixin adoption

## Open Questions

1. **Migration order for complex plugins**
   - What we know: Design doc proposes phases A-G, starting with 6 easy plugins (ATR, ADX, Stochastic, WilliamsR, MFI, VolumeZscore)
   - What's unclear: Whether GARCH, Kalman, HMM, BOCPD (3 "hard" plugins) should wait for Phase C validation or can proceed in parallel
   - Recommendation: Execute phases A-C first (fix bugs, add tests, migrate 6 easy plugins), validate with Phase 093's 10K-bar stability tests, then proceed to complex plugins

2. **Typed state dataclasses**
   - What we know: Design doc evaluates `IncrementalPluginBase[Generic[TState]]` with typed state dataclasses
   - What's unclear: Whether IDE autocomplete and compile-time key checking justify the complexity
   - Recommendation: Defer - can add later as non-breaking enhancement once all plugins are on mixin

3. **CVD/OFI per-symbol state architecture**
   - What we know: These plugins use `self._state` per-symbol sub-dicts instead of the `state` parameter
   - What's unclear: Whether to fix the architecture or just set `supports_incremental=False`
   - Recommendation: Isolated sprint - architectural bug needs design doc before fix

## Sources

### Primary (HIGH confidence)
- `docs/plans/2026-05-21-plugin-infrastructure-design.md` - Complete analysis of all 132 plugins, state archetypes, migration strategy
- `src/intelligence/plugins.py` - Protocol classes (IndicatorPlugin, PatternPlugin)
- `src/intelligence/pipeline/executor.py` - PluginExecutor, _timed_plugin_call wrapper, PERF-03 state threading
- `src/intelligence/register_plugins.py` - Plugin registration, tier lists, schema validation
- `src/observability/circuit_breaker.py` - CircuitBreaker with allow_request/record_failure/record_success

### Secondary (MEDIUM confidence)
- `src/intelligence/features/i1_indicators/atr.py` - Example of correctly implemented incremental plugin
- `src/intelligence/features/i1_indicators/rsi.py` - Example of buggy incremental plugin (design doc finding)
- `src/intelligence/features/i1_indicators/bollinger.py` - Example of Rolling Window + Running Sum archetype
- `tests/unit/intelligence/test_plugin_incremental.py` - Test infrastructure for incremental validation

### Tertiary (LOW confidence)
- `src/intelligence/trading/plugin_utils.py` - Existing shared utilities for I7 plugins (no_signal, extract_ohlcv)
- `.claude/skills/add-plugin/SKILL.md` - Plugin development workflow (confirms Protocol + dataclass approach)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All components verified in codebase, design doc is authoritative
- Architecture: HIGH - Protocol + dataclass design is confirmed optimal, mixin approach is well-validated
- Pitfalls: HIGH - 5 HIGH-severity bugs already identified in design doc, conformance tests will catch regressions
- Migration strategy: MEDIUM - Phases A-C are low-risk, complex plugins (GARCH/HMM/BOCPD) need individual validation

**Research date:** 2026-05-21
**Valid until:** 30 days (stable architecture - no moving parts)
**Next review:** After Phase C completion (6 easy plugins migrated + conformance tests passing)
