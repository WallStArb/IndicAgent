# Phase 18: Financial Math Safety - Research

**Researched:** 2026-03-08
**Domain:** Financial math safety, floating-point precision, API timeouts, concurrency control
**Confidence:** HIGH

## Summary

Phase 18 addresses two critical safety concerns: mathematical correctness in floating-point comparisons and API timeout configuration, plus concurrency protection for shared state in services.

**Floating-Point Comparisons:** Direct `>` or `<` comparisons with float values can fail due to IEEE 754 rounding errors. For example, `0.1 + 0.2 != 0.3` in binary floating-point. The standard solution is epsilon tolerance: `abs(a - b) > EPSILON` where `EPSILON` is a small value like `1e-9` (nine orders of magnitude smaller than typical financial values).

**Magic Numbers:** The codebase contains numerous hardcoded multipliers and thresholds that lack documentation of their purpose and derivation. This makes tuning and debugging difficult without context.

**API Timeouts:** IBKR provider and LLM providers have hardcoded timeouts (20s, 30s) scattered across code. Centralizing these in Settings enables runtime configuration and testing.

**Shared State Concurrency:** Services store per-symbol/timeframe/plugin state in dictionaries (`_plugin_states`, `_i1_plugin_states`, `_latest_signals`) without synchronization. In asyncio event loops, concurrent access can corrupt state or cause race conditions. Per-key `asyncio.Lock()` provides fine-grained protection without global lock contention.

**Primary recommendation:**
1. Add `EPSILON_TOLERANCE = 1e-9` to all math modules, use `abs(a - b) > EPSILON_TOLERANCE` for comparisons
2. Document all magic numbers as named constants with inline comments explaining purpose
3. Centralize timeouts in Settings with `ibkr_timeout_sec` (default 20.0s) and `llm_timeout_sec` (default 60.0s)
4. Add per-key `asyncio.Lock()` dictionaries for state access in services

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.10+ | Base runtime | Required for `asyncio.Lock()` and modern type hints |
| NumPy | Latest | Numerical computing | Used for epsilon-safe comparisons, `np.isclose()` alternative |
| Pydantic Settings | Latest | Configuration | `Field()` with `validation_alias` for env var support |
| asyncio | Built-in | Concurrency | `asyncio.Lock()` for per-key state protection |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | 7.x+ | Testing | Characterization tests for edge cases |
| structlog | Latest | Logging | Service logging in production |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|-------------|-----------|----------|
| Global lock | Per-key lock | Per-key is less contention; global lock serializes all access |
| `math.isclose()` | Epsilon tolerance | `math.isclose()` uses fixed rtol/atol; custom EPSILON provides explicit control |
| Hardcoded values | Settings | Settings enables runtime tuning without code changes |

**Installation:**
```bash
# Already in project requirements
pip install numpy pydantic-settings pytest
```

## Architecture Patterns

### Recommended Project Structure
```
src/
├── config/
│   └── settings.py          # Centralize: ibkr_timeout_sec, llm_timeout_sec
├── core/
│   └── float_utils.py        # NEW: EPSILON_TOLERANCE constant, safe_compare()
├── intelligence/
│   ├── trading/
│   │   ├── trade_framer.py   # Add named ATR multipliers
│   │   ├── cis_scorer.py    # Add EPSILON_TOLERANCE
│   │   └── aggregator.py     # Already has _REGIME_PROB_MIN, _REGIME_DUR_MIN
│   ├── indicators/
│   │   └── rsi.py          # Document zero-loss guard
│   └── llm_providers.py      # Use Settings.llm_timeout_sec
├── providers/
│   └── ibkr.py             # Use Settings.ibkr_timeout_sec
└── services/
    ├── market_analysis_service.py  # Add _plugin_states_locks dict
    ├── indicator_service.py       # Add _i1_plugin_states_locks dict
    └── ai_narrative_service.py   # Add _latest_signals_lock
```

### Pattern 1: Epsilon Tolerance for Floating-Point Comparisons
**What:** Use `abs(a - b) > EPSILON` instead of `a > b` for float comparisons
**When to use:** All floating-point comparisons where exact equality is not required (most financial math)
**Example:**
```python
# Source: IEEE 754 standard, financial best practices
EPSILON_TOLERANCE = 1e-9  # 9 orders of magnitude below typical values

# BAD: Direct comparison fails due to floating-point errors
if slope > 0:
    slope_dir = 1.0

# GOOD: Epsilon-safe comparison
if slope > EPSILON_TOLERANCE:
    slope_dir = 1.0
elif slope < -EPSILON_TOLERANCE:
    slope_dir = -1.0
else:
    slope_dir = 0.0
```

### Pattern 2: Named Constants for Magic Numbers
**What:** Document each magic number as a named constant with inline comment explaining purpose and source
**When to use:** Any hardcoded multiplier, threshold, or ratio in financial calculations
**Example:**
```python
# Source: Renaissance principle: segment relentlessly, degrade gracefully

# ATR multipliers for stop placement (Renaissance: structural levels over hidden constants)
ATR_STOP_DEMAND_MULTIPLIER = 0.25   # Demand zone: nearest_demand_low - ATR×0.25
ATR_STOP_SWEEP_MULTIPLIER = 0.30   # Sweep detected: sweep_level - ATR×0.30
ATR_STOP_OB_MULTIPLIER = 0.20       # Order block: ob_bottom/top ± ATR×0.20
ATR_STOP_SWING_MULTIPLIER = 0.25    # Swing: swing_low/high ± ATR×0.25
ATR_STOP_SR_MULTIPLIER = 0.50       # S/R: nearest_support/resistance ± ATR×0.50
ATR_STOP_FALLBACK_MULTIPLIER = 2.0   # Fallback: entry ± ATR×2.0

# ATR multipliers for zone and target bounds
ATR_ZONE_SWEEP_MULTIPLIER = 0.5      # Sweep/reclaim zone: entry ± ATR×0.5
ATR_ZONE_LOW_MULTIPLIER = 1.0          # Zone lower bound: entry - ATR×1.0
ATR_ZONE_HIGH_MULTIPLIER = 0.5         # Zone upper bound: entry + ATR×0.5
ATR_TARGET_MIN_MULTIPLIER = 0.5       # Minimum target distance: entry ± ATR×0.5
ATR_TARGET_MAX_MULTIPLIER = 8.0       # Maximum target distance: entry ± ATR×8.0

# ATR target multipliers for fallback (RR-based)
ATR_FALLBACK_T1_MULTIPLIER = 2.0      # T1: risk × 2.0
ATR_FALLBACK_T2_MULTIPLIER = 3.5      # T2: risk × 3.5
ATR_FALLBACK_T3_MULTIPLIER = 5.5      # T3: risk × 5.5

# Emergency ATR fallback (Renaissance: degrade gracefully)
ATR_EMERGENCY_FALLBACK_PCT = 0.001  # 0.1% of price as emergency ATR when atr <= 0
```

### Pattern 3: Settings with Validation Aliases
**What:** Use Pydantic `Field()` with `validation_alias` and `AliasChoices()` for flexible env var naming
**When to use:** Configuration values that need runtime tunability via environment variables
**Example:**
```python
# Source: pydantic-settings documentation, best practices for config
from pydantic import Field, AliasChoices

class Settings(BaseSettings):
    # IBKR timeout with flexible environment variable support
    ibkr_timeout_sec: float = Field(
        default=20.0,
        validation_alias=AliasChoices(
            "ib_timeout_sec",
            "IBKR_TIMEOUT_SEC",
            "IB_TIMEOUT_SEC"
        ),
        description="Timeout in seconds for IBKR API operations (connect, requests)",
    )

    # LLM timeout with flexible environment variable support
    llm_timeout_sec: float = Field(
        default=60.0,
        validation_alias=AliasChoices(
            "llm_timeout_sec",
            "LLM_TIMEOUT_SEC"
        ),
        description="Timeout in seconds for LLM provider API calls",
    )
```

### Pattern 4: Per-Key AsyncIO Lock for Shared State
**What:** Use `dict[key, asyncio.Lock]()` for fine-grained state protection
**When to use:** Any service state accessed concurrently (plugin state, signal cache, etc.)
**Example:**
```python
# Source: asyncio documentation, concurrent programming best practices
class MarketAnalysisService:
    def __init__(self, ...):
        # Per-(plugin, symbol, timeframe) state namespace with concurrency protection
        self._plugin_states: dict[tuple[str, str, str], dict] = {}
        self._plugin_states_locks: dict[tuple[str, str, str], asyncio.Lock] = {}

    def _get_state_lock(self, key: tuple[str, str, str]) -> asyncio.Lock:
        """Get or create a lock for a given state key."""
        if key not in self._plugin_states_locks:
            self._plugin_states_locks[key] = asyncio.Lock()
        return self._plugin_states_locks[key]

    async def _run_tier(self, plugins: list[str], tier: str, ...) -> None:
        for pname in plugins:
            p = self._plugin_cache[pname]
            state_key = (pname, symbol, timeframe)

            # Acquire per-key lock before state access
            async with self._get_state_lock(state_key):
                p._state = self._plugin_states.setdefault(state_key, {})
                # Plugin computation here
                tier_result = p.compute_full(frames)
                self._plugin_states[state_key] = p._state  # Write back after
```

### Anti-Patterns to Avoid
- **Direct float comparisons:** `if slope > 0:` fails on edge cases due to rounding errors. Use epsilon tolerance.
- **Global lock for all state:** `_lock = asyncio.Lock()` protects everything but causes contention. Use per-key locks.
- **Hardcoded timeouts:** `timeout=20` scattered in code. Centralize in Settings for tunability.
- **Magic numbers without comments:** `0.25`, `0.5`, etc. without documentation are unmaintainable. Use named constants with inline comments.
- **Unprotected shared state:** Dictionary access from concurrent tasks without locks can corrupt state. Always use locks.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Floating-point epsilon comparison | Custom `abs(a-b) > EPSILON` logic repeated | `np.isclose(a, b, rtol=0, atol=EPSILON)` for vectors, `math.isclose()` for scalars | Built-in handles edge cases, tested; custom logic error-prone |
| Settings management | Custom config parsing from environment | `pydantic-settings.BaseSettings` with `Field()` and `validation_alias` | Type-safe, validates on load, flexible env var naming |
| Lock management | Per-key lock creation boilerplate | `dict.get_or_create(key, asyncio.Lock)` pattern | Simplifies code, ensures single lock instance per key |

**Key insight:** Python's `asyncio.Lock()` is efficient for fine-grained concurrency control; global locks serialize all access and eliminate parallelism benefits. Per-key locks allow concurrent operations on different keys.

## Common Pitfalls

### Pitfall 1: Floating-Point Precision in Direction Determination
**What goes wrong:** `slope_dir = 1.0 if slope > 0 else (-1.0 if slope < 0 else 0.0)` fails when slope is `1e-15` due to accumulated rounding errors
**Why it happens:** Binary floating-point cannot represent some decimal values exactly; repeated operations accumulate error
**How to avoid:** Use epsilon tolerance: `if slope > EPSILON: ... elif slope < -EPSILON: ... else: 0.0`
**Warning signs:** Test values near zero or when comparing results of sequential operations

### Pitfall 2: ATR Emergency Fallback Without Documentation
**What goes wrong:** `atr = abs(entry) * 0.001` when ATR is zero; meaning of `0.001` (0.1%) unclear to maintainers
**Why it happens:** Fallback logic written to prevent division by zero, but magic number lacks context
**How to avoid:** Document as `ATR_EMERGENCY_FALLBACK_PCT = 0.001  # 0.1% of price as emergency ATR`
**Warning signs:** Any fallback branch with magic multiplier has no comment explaining the value

### Pitfall 3: Regime Threshold Scattered Across Files
**What goes wrong:** `_REGIME_PROB_MIN = 0.60` in aggregator.py, but similar thresholds in cis_scorer.py lack documentation
**Why it happens:** Different developers add thresholds without consulting existing patterns
**How to avoid:** Centralize all regime thresholds with consistent naming and inline comments
**Warning signs:** Same numeric value (0.35, 0.60) appears in multiple files with different names

### Pitfall 4: Race Conditions in Plugin State Access
**What goes wrong:** `_plugin_states[(pname, symbol, tf)]` read/write in concurrent async tasks can corrupt state
**Why it happens:** asyncio event loop processes multiple symbols/timeframes in parallel; shared dict has no synchronization
**How to avoid:** Add `_plugin_states_locks: dict[tuple, asyncio.Lock]` and use `async with lock:` around all access
**Warning signs:** Any shared dict modified in async context without lock protection

## Code Examples

Verified patterns from official sources:

### Epsilon-Safe Direction Comparison
```python
# Source: IEEE 754 floating-point standard, financial computing best practices
EPSILON_TOLERANCE = 1e-9

# Safe direction extraction (replaces raw > 0 / < 0)
def _safe_direction(value: float) -> int:
    """Return direction with epsilon tolerance."""
    if value > EPSILON_TOLERANCE:
        return 1
    elif value < -EPSILON_TOLERANCE:
        return -1
    else:
        return 0

# Usage in CIS scorer:
slope_dir = _safe_direction(slope)
macd_dir = _safe_direction(macd)
roc_dir = _safe_direction(roc)
```

### Regime Threshold Constants with Documentation
```python
# Source: aggregator.py, Phase 12 (Signal Integrity)
# Regime thresholds (Renaissance: segment relentlessly)
_REGIME_PROB_MIN = 0.60   # minimum confidence to trust regime label (raised from 0.55)
_REGIME_DUR_MIN = 5       # minimum bars before regime is considered stable (raised from 3)

# CIS thresholds (Renaissance: segment relentlessly)
CIS_FIRE_THRESHOLD = 0.35  # abs(CIS) > 0.35 required for signal fire
BUCKET_AGREE_MIN = 3       # Minimum buckets agreeing with CIS direction
BUCKET_NOISE_FLOOR = 0.1   # Minimum |bucket_score| to count as agreeing
```

### RSI Zero-Loss Guard with Documentation
```python
# Source: src/intelligence/indicators/rsi.py (lines 84-85)
# Zero-loss guard (Renaissance: data quality over model complexity)
# When avg_loss == 0 (no downward moves), RSI returns 100.0 (maximum momentum)
# This is mathematically correct: if no loss ever occurred, price only went up
if s["avg_loss"] == 0:
    out[key] = 100.0
else:
    rs = s["avg_gain"] / s["avg_loss"]
    out[key] = 100.0 - 100.0 / (1.0 + rs)
```

### Settings-Based Timeout Configuration
```python
# Source: pydantic-settings documentation
from pydantic import Field, AliasChoices

class Settings(BaseSettings):
    # IBKR timeout with flexible environment variable support
    ibkr_timeout_sec: float = Field(
        default=20.0,
        validation_alias=AliasChoices(
            "ib_timeout_sec",
            "IBKR_TIMEOUT_SEC",
            "IB_TIMEOUT_SEC"
        ),
        description="Timeout in seconds for IBKR API operations (connect, requests)",
    )

    # LLM timeout with flexible environment variable support
    llm_timeout_sec: float = Field(
        default=60.0,
        validation_alias=AliasChoices(
            "llm_timeout_sec",
            "LLM_TIMEOUT_SEC"
        ),
        description="Timeout in seconds for LLM provider API calls",
    )
```

### Per-Key Lock for State Protection
```python
# Source: asyncio documentation, concurrent programming patterns
class IndicatorService:
    def __init__(self, ...):
        self._i1_plugin_states: dict[tuple[str, str, str], dict] = {}
        self._i1_plugin_states_locks: dict[tuple[str, str, str], asyncio.Lock] = {}

    def _get_state_lock(self, key: tuple[str, str, str]) -> asyncio.Lock:
        """Get or create a lock for a given state key."""
        if key not in self._i1_plugin_states_locks:
            self._i1_plugin_states_locks[key] = asyncio.Lock()
        return self._i1_plugin_states_locks[key]

    # Usage in _run_i1_plugins:
    for plugin_name in I1_PLUGINS:
        p = self._i1_plugin_cache[plugin_name]
        state_key = (plugin_name, symbol, timeframe)

        async with self._get_state_lock(state_key):
            p._state = self._i1_plugin_states.setdefault(state_key, {})
            result = p.compute_full(frames)
            self._i1_plugin_states[state_key] = p._state
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|-----------------|--------------|--------|
| Direct float comparison `> 0` | Epsilon tolerance `> EPSILON` | 2026-03-08 (this phase) | Prevents edge case failures in signal direction |
| Hardcoded magic numbers | Named constants with documentation | 2026-03-08 (this phase) | Enables maintainability and tuning |
| Hardcoded timeouts | Settings-based configuration | 2026-03-08 (this phase) | Runtime tunability via environment variables |
| No lock on shared state | Per-key asyncio.Lock() | 2026-03-08 (this phase) | Prevents race conditions in async services |

**Deprecated/outdated:**
- Direct `>` and `<` comparisons for float direction: Use epsilon tolerance instead
- Magic numbers without documentation: Always add inline comment explaining purpose
- Hardcoded API timeouts: Centralize in Settings

## Open Questions

1. **Epsilon value appropriateness for different data scales**
   - What we know: `1e-9` is standard for double-precision, typical in financial applications
   - What's unclear: Whether ATR values (often 0.5-50) need different epsilon than signal scores (-1 to 1)
   - Recommendation: Use `1e-9` consistently; document rationale; revisit if edge cases emerge

2. **Lock granularity for performance impact**
   - What we know: Per-key locks prevent race conditions but add overhead
   - What's unclear: Impact of lock creation/acquisition on service throughput
   - Recommendation: Measure metrics before/after; consider lock-free alternatives if impact is significant

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 7.x+ |
| Config file | `.planning/config.json` (nyquist_validation: true by default) |
| Quick run command | `.venv/bin/pytest tests/unit/intelligence/test_*_plugins.py -k "epsilon or magic or timeout or lock" -x` |
| Full suite command | `.venv/bin/pytest tests/unit/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FIN-01 | Epsilon tolerance used in trade_framer.py comparisons | unit | `pytest tests/unit/intelligence/test_trade_framer.py -k epsilon -x` | Wave 0 |
| FIN-02 | Epsilon tolerance used in cis_scorer.py direction comparisons | unit | `pytest tests/unit/intelligence/test_cis_scorer.py -k epsilon -x` | Wave 0 |
| FIN-03 | All magic numbers documented as named constants | review | Manual code review after implementation | N/A |
| FIN-04 | ATR multipliers documented | review | `grep -n "ATR.*MULTPLIER.*=" src/intelligence/trading/trade_framer.py` | N/A |
| FIN-05 | Regime thresholds documented | review | `grep -n "_REGIME.*=" src/intelligence/trading/aggregator.py` | N/A |
| FIN-06 | RSI zero-loss guard documented | review | `grep -n "Zero-loss" src/intelligence/indicators/rsi.py` | N/A |
| API-01 | Settings.ibkr_timeout_sec exists and has default 20.0s | unit | `.venv/bin/python -c "from src.config.settings import Settings; s = Settings(); assert hasattr(s, 'ibkr_timeout_sec') and s.ibkr_timeout_sec == 20.0"` | Wave 0 |
| API-02 | Settings.llm_timeout_sec exists and has default 60.0s | unit | `.venv/bin/python -c "from src.config.settings import Settings; s = Settings(); assert hasattr(s, 'llm_timeout_sec') and s.llm_timeout_sec == 60.0"` | Wave 0 |
| API-03 | IBKR provider uses Settings.ibkr_timeout_sec | unit | `grep -n "settings.ib_timeout_sec" src/providers/ibkr.py` | Wave 0 |
| API-04 | All LLM providers use Settings.llm_timeout_sec as default | unit | `grep -n "Settings().llm_timeout_sec" src/intelligence/llm_providers.py` | Wave 0 |
| API-05 | market_analysis_service has _plugin_states_locks dict | review | `grep -n "_plugin_states_locks" services/market_analysis_service.py` | N/A |
| API-06 | indicator_service has _i1_plugin_states_locks dict | review | `grep -n "_i1_plugin_states_locks" services/indicator_service.py` | N/A |
| API-07 | ai_narrative_service has _latest_signals_lock | review | `grep -n "_latest_signals_lock" services/ai_narrative_service.py` | N/A |

### Sampling Rate
- **Per task commit:** Quick test for modified module: `pytest tests/unit/intelligence/test_<module>.py -k "test" -x`
- **Per wave merge:** Full test suite: `.venv/bin/pytest tests/unit/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/intelligence/test_trade_framer.py` — epsilon tolerance tests
- [ ] `tests/unit/intelligence/test_cis_scorer.py` — epsilon tolerance tests
- [ ] `tests/unit/config/test_settings.py` — timeout configuration tests
- [ ] Tests for per-key lock acquisition/release (can add to existing service test files)

## Sources

### Primary (HIGH confidence)
- Python IEEE 754 floating-point standard - EPSILON for comparisons: https://en.wikipedia.org/wiki/IEEE_754
- pydantic-settings documentation - `Field()` and `validation_alias`: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
- Python asyncio documentation - `asyncio.Lock()`: https://docs.python.org/3/library/asyncio-sync.html#asyncio.Lock
- Phase 18 plans (18-01-PLAN.md, 18-02-PLAN.md, 18-03-PLAN.md) - Existing context and task definitions

### Secondary (MEDIUM confidence)
- Codebase analysis of existing implementations in trade_framer.py, cis_scorer.py, aggregator.py, rsi.py
- Services analysis: market_analysis_service.py, indicator_service.py, ai_narrative_service.py
- IBKR provider: src/providers/ibkr.py
- LLM providers: src/intelligence/llm_providers.py

### Tertiary (LOW confidence)
- None - all findings verified by direct code inspection and official documentation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Verified by direct code inspection and official Python/docs
- Architecture: HIGH - Patterns verified against asyncio and pydantic documentation
- Pitfalls: HIGH - Issues identified by static analysis of existing code

**Research date:** 2026-03-08
**Valid until:** 2026-04-08 (stable - depends only on Python standard library and patterns)
