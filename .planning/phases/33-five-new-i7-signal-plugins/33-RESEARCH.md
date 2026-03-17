# Phase 33: Five New I7 Signal Plugins - Research

**Researched:** 2026-03-17
**Domain:** I7 trading setup plugins — Python dataclass plugin protocol, IntelligenceEvent feature consumption, trade_framer stop/target resolution
**Confidence:** HIGH

## Summary

Phase 33 adds six I7 plugins (five market conditions, ORB split into two for statistical segmentation) to `src/intelligence/trading/`. Every plugin in this codebase follows a locked protocol verified by reading four reference implementations and the plugin registry. All six plugins are purely additive: no schema changes, no service changes, and no changes to existing plugins. The signal generator auto-discovers newly registered plugins.

The critical constraint is that trade_framer.py does not have an explicit setup_type branch for any of the new signal type strings. The entry resolution fallback is `"at_close"`, which means plugins that want `at_limit` or `at_pullback` behavior must either (a) name their `signal_type` string to match an existing prefix (`trend_`, `momentum_breakout_`, etc.) or (b) accept that `frame_trade()` falls through to `at_close` and rely on the plugin passing a pre-resolved entry price. The CONTEXT.md decisions specify `at_limit` and `at_pullback` entry types for several plugins. The planner must ensure `frame_trade()` calls use signal_type strings that resolve correctly inside `_resolve_entry()`, or that plugins pass an already-resolved entry price and a signal_type that falls through gracefully.

**Primary recommendation:** Implement all six plugins in the reference `choch_reversal.py` pattern (gate → direction → frame_trade → output dict), calling `frame_trade()` for stop/target sizing. Add stateful `_state` dict for ORB range storage and VCP contraction tracking. Register all six in `register_plugins.py` import block and `TIER_I7` list. Add all six to `aggregator.py` `TREND_SETUPS` or leave unlisted (mean-reversion default) as appropriate.

## User Constraints (from CONTEXT.md)

<user_constraints>
### Locked Decisions

**FailedBreakout (trad_FailedBreakout)**
- Gate: `bos_detected == 1.0` — trust existing confirmation, no additional penetration filter
- Reversal window: 3 bars — close back through BOS level within 3 bars
- Entry trigger: close back through the BOS level
- Entry type: `at_pullback`
- Regime: `mean_reversion` preferred; trend regime reduces confidence ~20% but does not block
- Stop: via `trade_framer.py` — structural snap to BOS level first (within 1.5×ATR), GARCH-adaptive ATR fallback
- Feature logging: `bos_level`, `bars_since_bos`, `reversal_close_delta` logged per signal

**ORB — Two Separate Plugins (trad_ORB15 and trad_ORB30)**
- trad_ORB15: range from 09:30–09:45 ET; fires first bar closing above/below with volume expansion; session gate 09:30–11:30 ET
- trad_ORB30: range from 09:30–10:00 ET; fires first bar closing above/below with volume expansion; session gate 09:30–11:30 ET
- Shared: gap_pct = (open - prior_session_close) / prior_session_close; gap > 0 → bullish bias; threshold 0.1% to filter micro-gaps
- Volume gate: breakout bar volume > 1.5× session average (proxy via `rel_volume` if available)
- Entry type: `at_pullback` on close of breakout bar
- Stop: `trade_framer.py` — structural snap to opening range boundary first, GARCH ATR fallback
- Regime: trend preferred; any regime allowed

**PrevDayLevelTest (trad_PrevDayLevelTest)**
- Levels: PDH (`prior_session_high`), PDL (`prior_session_low`), PDC (`prior_session_close`) — all three active
- Two variants in one plugin via `setup_variant` field: `"fade"` and `"continuation"`
- Fade: price approaches level with reversal momentum; `mean_reversion` regime preferred
- Continuation: price breaks through, pulls back to re-test, holds; `trend` regime preferred
- Proximity gate: within 0.5×ATR of the level
- Entry type: `at_limit` (fade) / `at_pullback` (continuation)
- Stop: `trade_framer.py` structural snap to the level itself (PDH/PDL/PDC as invalidation)

**SecondLegContinuation (trad_SecondLegContinuation)**
- Leg 1: from I3 `swing_high` / `swing_low` fields in IntelligenceEvent
- Fib zone: 38.2%–61.8%; entry target at 50% retracement
- Entry type: `at_limit`
- Targets: T1 = 100% measured move, T2 = 127.2%, T3 = 161.8% of Leg 1 amplitude
- Stop: Leg 1 swing low (long) / swing high (short) via `trade_framer.py`
- Regime: HMM trend regime required
- Qualifying condition: Leg 1 amplitude ≥ 1.0×ATR

**VCP — Volatility Contraction Pattern (trad_VCP)**
- Scope: intraday session only
- Minimum: 3+ successive range contractions (each H-L smaller than prior) with declining volume
- Regime: HMM trend regime required (prob ≥ 0.60) — definitional, not a filter
- Entry trigger: first bar closing above/below most recent contraction's range boundary with volume expansion
- Entry type: `at_pullback`
- Directional bias: follow HMM trend direction
- Stop: `trade_framer.py` structural snap to VCP base

**Cross-Plugin Architecture (all 6)**
- All 6 plugins call `trade_framer.py`
- All 6 fire as production signals immediately (no shadow gate)
- All 6 write to `signal_ledger` with complete feature snapshots
- Entry types: FailedBreakout=at_pullback; ORB15/30=at_pullback; PrevDayFade=at_limit; PrevDayContinuation=at_pullback; SecondLeg=at_limit; VCP=at_pullback

### Claude's Discretion
- Exact ATR buffer for BOS stop in FailedBreakout (0.1–0.25× ATR)
- ORB range high/low storage approach (in-memory state dict vs features)
- VCP contraction detection algorithm (rolling window H-L comparison)
- Exact session average volume computation for ORB volume gate
- `swing_high_age_bars` qualifying threshold for SecondLeg (to avoid stale swings)

### Deferred Ideas (OUT OF SCOPE)
- None — discussion stayed within phase scope
</user_constraints>

## Phase Requirements

<phase_requirements>

| ID | Description | Research Support |
|----|-------------|-----------------|
| PLUG-01 | New I7 plugin `trad_FailedBreakout` — BOS/CHoCH confirmed reversal within N bars; complementary to trad_MomentumBreakout | `bos_detected`, `bos_direction`, `bos_level` confirmed in SMCContext schema; `choch_reversal.py` is reference pattern; `_state` dict tracks bars_since_bos per `(symbol, timeframe)` |
| PLUG-02 | New I7 plugin `trad_OpeningRangeBreakout` — 15-min and 30-min ORB as separate plugins with gap bias and volume gate, NY session only | `prior_session_close`, `session_ny` confirmed in schema; `_ET_TZ`, `_in_window()` available from `session_context.py`; timestamp from `df["timestamp"]` column; stateful range storage in `_state` |
| PLUG-03 | New I7 plugin `trad_PrevDayLevelTest` — PDH/PDL/PDC fade or continuation; `setup_variant` field in output | `prior_session_high`, `prior_session_low`, `prior_session_close` confirmed in I3Structure schema (struct_SessionLevels outputs); `atr_14` for proximity gate |
| PLUG-04 | New I7 plugin `trad_SecondLegContinuation` — Leg 1 + Fib pullback; measured move targets | `swing_high`, `swing_low`, `swing_high_age_bars`, `swing_low_age_bars` confirmed in I3Structure schema; `hmm_regime`, `hmm_regime_prob` in SMCContext; `atr_14` for amplitude filter |
| PLUG-05 | New I7 plugin `trad_VCP` — 3+ successive H-L contractions with declining volume; HMM trend regime required | `hmm_regime`, `hmm_regime_prob` confirmed in SMCContext; volume from `df["volume"]`; `_state` dict tracks contraction history per `(symbol, timeframe)` |

</phase_requirements>

## Standard Stack

### Core
| Component | Location | Purpose | Why Standard |
|-----------|----------|---------|--------------|
| Plugin dataclass | `@dataclass` in `src/intelligence/trading/<name>.py` | Plugin implementation | Locked protocol — all 17 existing I7 plugins use this |
| `frame_trade()` | `src/intelligence/trading/trade_framer.py` | Stop/target resolution | Phase 32 prerequisite — all plugins inherit GARCH-adaptive stops |
| `_ET_TZ` + `_in_window()` | `src/intelligence/context/session_context.py` | ET timezone session gating | Already used by `session_extremes_setup.py` for session windows |
| `_state` dict | Plugin instance attribute | Per `(symbol, timeframe)` stateful tracking | Used by ORB range accumulation, VCP contraction tracking, FailedBreakout BOS age tracking |
| `exhaustion_utils.apply_exhaustion_guard` | `src/intelligence/trading/exhaustion_utils.py` | Confidence penalty for exhausted moves | Used by TrendFollowing, MomentumBreakout — should be applied to trend-chasing plugins |

### Registration
| File | What to Add | How |
|------|-------------|-----|
| `src/intelligence/trading/<plugin>.py` | Plugin file + module-level `plugin = PluginClass()` | New file per plugin |
| `src/intelligence/register_plugins.py` | Import + `registry.register_pattern(plugin)` + TIER_I7 entry | Match pattern of existing 17 plugins |
| `src/intelligence/trading/aggregator.py` | TREND_SETUPS additions for ORB15, ORB30, SecondLeg, VCP | Trend-regime plugins must be in this frozenset |

### No Installation Required
All dependencies already in the codebase. No new packages.

## Architecture Patterns

### Recommended Project Structure
```
src/intelligence/trading/
├── failed_breakout.py       # PLUG-01: trad_FailedBreakout
├── orb15.py                 # PLUG-02a: trad_ORB15
├── orb30.py                 # PLUG-02b: trad_ORB30
├── prev_day_level_test.py   # PLUG-03: trad_PrevDayLevelTest
├── second_leg_continuation.py # PLUG-04: trad_SecondLegContinuation
└── vcp.py                   # PLUG-05: trad_VCP
tests/unit/intelligence/trading/
├── test_failed_breakout.py
├── test_orb15.py
├── test_orb30.py
├── test_prev_day_level_test.py
├── test_second_leg_continuation.py
└── test_vcp.py
```

### Pattern 1: Minimal I7 Plugin (choch_reversal.py pattern)
**What:** `@dataclass` class with mandatory fields, `compute_full()` with sequential gates, `_no_signal()` static method
**When to use:** All six new plugins follow this exact pattern

```python
# Source: src/intelligence/trading/choch_reversal.py (verified)
@dataclass
class MyPlugin:
    name: str = "trad_MyPlugin"
    outputs: frozenset[str] = frozenset({"signal_type", "direction", "entry_price",
                                          "stop_loss", "targets", "confidence",
                                          "regime_context", "supporting_factors"})
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "..."})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=50),)
    regime_type: str = "any"  # "trend" | "mean_reversion" | "any"
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return {}
        # Gates — return self._no_signal() on any failure
        ...

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}

plugin = MyPlugin()
```

### Pattern 2: Stateful Plugin with `_state` dict
**What:** `_state` keyed by `(symbol, timeframe)` tuple for per-instrument memory
**When to use:** ORB (stores range high/low), VCP (stores contraction history), FailedBreakout (stores bars_since_bos)

```python
# Pattern from existing stateful plugins (HMM, GARCH, etc.)
def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
    df = frames.get("main")
    symbol = frames.get("__symbol__", "")
    tf = frames.get("__timeframe__", "")
    key = (symbol, tf)

    state = self._state.get(key, {})
    # ... update state ...
    self._state[key] = state  # ALWAYS write back — required for GARCH/HMM
```

**Critical gotcha from CLAUDE.md:** Plugin state write-back is load-bearing. Always write back `self._state[key]` after updating.

### Pattern 3: Session-Gated Plugin (ORB pattern)
**What:** Convert bar timestamp to ET, check time window with `_in_window()`
**When to use:** ORB15 and ORB30 — both need 09:30–11:30 ET gate and range accumulation

```python
# Source: src/intelligence/context/session_context.py (verified)
from zoneinfo import ZoneInfo
_ET_TZ = ZoneInfo("America/New_York")

def _et_from_utc(ts: datetime) -> datetime:
    return ts.astimezone(_ET_TZ)

def _in_window(et_dt: datetime, start: tuple[int, int], end: tuple[int, int]) -> bool:
    t = (et_dt.hour, et_dt.minute)
    if start <= end:
        return start <= t < end
    return t >= start or t < end

# In compute_full():
ts = df["timestamp"].iloc[-1]
if hasattr(ts, "to_pydatetime"):
    ts = ts.to_pydatetime()
if ts.tzinfo is None:
    ts = ts.replace(tzinfo=UTC)
et = ts.astimezone(_ET_TZ)
in_orb_window = _in_window(et, (9, 30), (11, 30))
```

### Pattern 4: Calling trade_framer
**What:** `frame_trade(setup_type, direction, entry_price, features, atr)` returns `TradeFrame`
**When to use:** All 6 plugins — replaces all per-plugin stop/target math

```python
# Source: src/intelligence/trading/trade_framer.py (verified)
from .trade_framer import TradeFrame, frame_trade

frame = frame_trade(
    setup_type=signal_type,   # e.g. "failed_breakout_long"
    direction=direction,       # 1 or -1
    entry=entry_price,
    features=features,
    atr=atr,
)
if not frame.viable:
    return self._no_signal()

return {
    "signal_type": signal_type,
    "direction": direction,
    "entry_price": frame.entry,
    "stop_loss": frame.stop,
    "targets": [t.price for t in frame.targets],
    "confidence": confidence,
    "regime_context": regime_ctx,
    "supporting_factors": supporting,
    "entry_type": frame.entry_type,  # optional but informative
}
```

**Critical:** The `signal_type` string passed to `frame_trade()` controls `_resolve_entry()` branching. None of the new signal_type strings (`failed_breakout_*`, `orb15_*`, `orb30_*`, `prev_day_*`, `second_leg_*`, `vcp_*`) match any existing prefix in `trade_framer._resolve_entry()`. They all fall through to `"at_close"` entry type, with `entry_price` passed directly as the resolved entry. This is correct behavior: plugins pre-compute their entry price (e.g., the 50% Fib level for SecondLeg, the ORB boundary close for ORB) and pass it as `entry`. The `frame_trade()` then handles stop and target resolution from structural features.

### Pattern 5: Registration in register_plugins.py
**What:** Three-step registration — import, `register_pattern()` call, TIER_I7 list entry
**When to use:** All six new plugins

```python
# Source: src/intelligence/register_plugins.py (verified)
# Step 1: Import at top of file
from .trading.failed_breakout import plugin as failed_breakout_plugin

# Step 2: In register_all_plugins(), with other I7 setups
registry.register_pattern(failed_breakout_plugin)

# Step 3: In TIER_I7 list
TIER_I7: list[str] = [
    ...existing 17...,
    failed_breakout_plugin.name,  # "trad_FailedBreakout"
]
```

**Critical:** `validate_tier()` hard-crashes at startup if any name in TIER_I7 is missing from the registry. Import + register + list entry must all be present together.

### Pattern 6: TREND_SETUPS in aggregator.py
**What:** `frozenset` of plugin names that require trending market for edge; used for Hurst routing
**When to use:** ORB15, ORB30, SecondLegContinuation, VCP are trend-mode plugins; add them

```python
# Source: src/intelligence/trading/aggregator.py (verified)
TREND_SETUPS: frozenset[str] = frozenset(
    {
        "trad_TrendFollowing",
        ...existing...,
        "trad_ORB15",           # new — trend continuation setup
        "trad_ORB30",           # new — trend continuation setup
        "trad_SecondLegContinuation",  # new — trend continuation
        "trad_VCP",             # new — momentum/trend compression
    }
)
```

FailedBreakout and PrevDayLevelTest are NOT in TREND_SETUPS (they are mean-reversion in nature).

### Anti-Patterns to Avoid
- **Re-implementing stop math in each plugin:** All 6 plugins must use `frame_trade()`. No per-plugin ATR arithmetic for stops.
- **Ignoring `frame.viable`:** If `frame_trade()` returns `viable=False`, the plugin must return `_no_signal()`. Skipping this check writes invalid signals.
- **`set`/`list` instead of `frozenset`/`tuple`:** Plugin protocol uses `frozenset[str]` for `outputs`/`capability_tags` and `tuple[InputSpec, ...]` for `inputs`. Wrong types pass silently but violate the protocol.
- **Adding new fields to `I3Structure` or `SMCContext`:** All consumed features already exist. No schema additions needed for Phase 33.
- **Forgetting `regime_type` class attribute:** `validate_tier()` does NOT check this, but the regime gate in `aggregator._regime_gate_signals()` uses it. Missing `regime_type` means the aggregator suppresses or passes the plugin incorrectly based on default behavior.
- **Stale `_state` from prior bar not written back:** If `compute_full()` returns early (e.g., `_no_signal()` on gate failure) without updating `_state`, state from a prior bar is left intact — which is correct for ORB range carry-forward but must be intentional.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Stop placement | Per-plugin ATR arithmetic | `frame_trade()` in `trade_framer.py` | Structural snap + GARCH-adaptive multipliers already implemented; SIG-01/SIG-02 inherited automatically |
| ET timezone conversion | `pytz` or manual offset | `ZoneInfo("America/New_York")` + `_et_from_utc()` from `session_context.py` | DST-correct; already tested in production |
| Session time window check | Inline time comparisons | `_in_window(et_dt, start, end)` from `session_context.py` | Handles midnight-wrap correctly |
| Feature extraction with defaults | `features.get("key", 0.0)` inline everywhere | Pattern from `choch_reversal.py` — direct `features.get()` with `isinstance()` guard | Consistent with codebase; `_fval()` helper in trade_framer.py also available |
| Fibonacci levels | Hand-compute from scratch | Simple arithmetic on `swing_high`, `swing_low` from features | No library needed; three lines of math |

**Key insight:** The trade_framer is the single source of truth for stop/target sizing. Phase 32 ensured GARCH-adaptive multipliers are wired into it. Any plugin that bypasses it gets static ATR stops and misses the adaptive behavior.

## Common Pitfalls

### Pitfall 1: `prior_session_close` is an I3 output, not I4
**What goes wrong:** Developer looks for session level fields in I4Context (SessionContextPlugin) and concludes they are missing.
**Why it happens:** `prior_session_high`, `prior_session_low`, `prior_session_close` are outputs of `struct_SessionLevels` (I3 tier), not `ctx_SessionContext` (I4 tier). They are accessed from `features` dict directly.
**How to avoid:** Confirmed in `I3Structure` schema — fields are at lines 209–211.
**Warning signs:** `features.get("prior_session_high")` returns None consistently.

### Pitfall 2: ORB range storage across bars requires `_state`
**What goes wrong:** ORB plugin computed in current bar only — opening range high/low cannot be known until 09:45 or 10:00 ET, but the plugin fires on the breakout bar which is later.
**Why it happens:** Each `compute_full()` call sees only the current bar's features, not prior bars' features directly.
**How to avoid:** Store `orb_high`, `orb_low`, `range_complete`, `range_date` in `self._state[key]`. Accumulate during the range window, mark complete when window ends, fire on first breakout bar after completion.
**Warning signs:** Plugin never fires in replay because range is never computed.

### Pitfall 3: VCP state must reset at session boundary
**What goes wrong:** VCP contraction list from prior day carries into new session, producing false signals.
**Why it happens:** `_state` persists across compute calls indefinitely unless explicitly cleared.
**How to avoid:** Store `session_date` in state. On each bar, check if `et.date()` != `state["session_date"]` — if so, reset contraction list.
**Warning signs:** VCP fires in pre-market on the first bar of the new day.

### Pitfall 4: trade_framer `at_pullback` entry requires `signal_type` NOT to match any special prefix
**What goes wrong:** Plugin passes `signal_type="trend_long"` for a SecondLeg signal — `_resolve_entry()` applies trend_following pullback logic, overriding the pre-computed Fib entry.
**Why it happens:** `_resolve_entry()` checks `st.startswith("trend_")` and replaces the entry with `nearest_support`.
**How to avoid:** Use distinct signal_type strings for each new plugin (`"failed_breakout_long"`, `"orb15_breakout_long"`, `"second_leg_long"`, etc.). These fall through to `"at_close"` in `_resolve_entry()`, which passes through the pre-computed entry unchanged. The plugin is responsible for computing the correct entry price before calling `frame_trade()`.
**Warning signs:** Trade framer returns a different entry price than the plugin computed.

### Pitfall 5: `bos_level` may be 0.0 or None in replay
**What goes wrong:** FailedBreakout tries to measure reversal delta from `bos_level` but the value is missing, producing division errors or false gates.
**Why it happens:** BOS events are discrete — most bars have `bos_detected=0.0` and `bos_level=None` or `bos_level=0.0`.
**How to avoid:** Guard all BOS field access with `isinstance(val, (int, float)) and val > 0`. Store `bos_level` in `_state[key]` when `bos_detected==1.0` so it persists across bars during the 3-bar reversal window.
**Warning signs:** `bars_since_bos` resets on every bar even when no new BOS fires.

### Pitfall 6: `regime_type` attribute controls aggregator suppression silently
**What goes wrong:** VCP is declared `regime_type="any"` — it fires in ranging markets even though the code has a regime gate. The aggregator regime gate uses `regime_type` to suppress or pass, independent of the plugin's own internal gate.
**Why it happens:** Two separate regime gates exist: the plugin's internal gate (hard return `_no_signal()`) and the aggregator's gate (suppress via `_REGIME_MAP[plugin.regime_type]`). If `regime_type` doesn't match the internal logic, the aggregator may suppress a signal that passed the plugin gate, or vice versa.
**How to avoid:** Declare `regime_type="trend"` for VCP, ORB15, ORB30, SecondLeg. Declare `regime_type="mean_reversion"` for FailedBreakout fade variant. PrevDayLevelTest has two variants — declare `regime_type="any"` since it handles both internally.

### Pitfall 7: FailedBreakout 3-bar window tracking across bars
**What goes wrong:** Plugin marks a BOS event and starts counting, but bar index is not monotonically available in `features` — the plugin only gets the current bar's data.
**Why it happens:** Each `compute_full()` sees the most recent features snapshot, not a bar index counter.
**How to avoid:** Store `bos_detected_ts` (timestamp of the BOS bar) in `_state[key]`. Compute `bars_since_bos` from the elapsed time divided by the timeframe seconds. Or count bars in state by incrementing on each compute call after BOS detected and resetting after window expires or reversal fires.

## Code Examples

Verified patterns from the codebase:

### Feature Field Access (verified from choch_reversal.py)
```python
# Source: src/intelligence/trading/choch_reversal.py
bos_detected = float(features.get("bos_detected", 0.0))
if bos_detected != 1.0:
    return self._no_signal()

bos_direction = int(features.get("bos_direction", 0))
bos_level = features.get("bos_level")  # may be None
```

### ATR Fallback (universal pattern across all I7 plugins)
```python
# Source: choch_reversal.py, session_extremes_setup.py
atr = float(features.get("atr_14", 0.0))
if atr <= 0:
    atr = float(np.mean(high[-14:] - low[-14:]))
if atr <= 0:
    return self._no_signal()
```

### HMM Regime Gate (verified from trend_following.py)
```python
# Source: src/intelligence/trading/trend_following.py
# VCP and SecondLeg use this pattern
hmm_regime = features.get("hmm_regime", 0.0)  # 0=ranging, 1=up, 2=down
hmm_regime_prob = features.get("hmm_regime_prob", 0.0)
if hmm_regime not in (1.0, 2.0):  # not trending
    return self._no_signal()
if hmm_regime_prob < 0.60:         # VCP requires ≥0.60 per CONTEXT.md
    return self._no_signal()
```

### Swing Fields for SecondLeg (verified from I3Structure schema)
```python
# Source: src/intelligence/schemas.py I3Structure
swing_high = features.get("swing_high")        # float | None
swing_low = features.get("swing_low")          # float | None
swing_high_age = features.get("swing_high_age_bars")  # float | None
swing_low_age = features.get("swing_low_age_bars")    # float | None
```

### Session Level Fields for PrevDayLevelTest (verified from I3Structure schema)
```python
# Source: src/intelligence/schemas.py I3Structure (struct_SessionLevels outputs)
pdh = features.get("prior_session_high")   # float | None
pdl = features.get("prior_session_low")    # float | None
pdc = features.get("prior_session_close")  # float | None
# All are None outside session context — guard with isinstance check
```

### Timestamp Extraction for ORB (verified from session_context.py)
```python
# Source: src/intelligence/context/session_context.py _extract_ts()
from datetime import UTC
from zoneinfo import ZoneInfo
_ET_TZ = ZoneInfo("America/New_York")

if "timestamp" in df.columns:
    val = df["timestamp"].iloc[-1]
    if hasattr(val, "to_pydatetime"):
        ts = val.to_pydatetime()
    else:
        ts = val
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    et = ts.astimezone(_ET_TZ)
```

### frame_trade Integration (verified from trade_framer.py)
```python
# Source: src/intelligence/trading/trade_framer.py
from .trade_framer import frame_trade

frame = frame_trade(
    setup_type="second_leg_long",  # falls through to at_close in _resolve_entry
    direction=1,
    entry=fib_50_level,           # pre-computed by plugin
    features=features,
    atr=atr,
)
if not frame.viable:
    return self._no_signal()

targets = [t.price for t in frame.targets]
```

### _no_signal() return contract (verified — all I7 plugins)
```python
# Minimum required fields for no-signal return
{"signal_type": "none", "direction": 0, "confidence": 0.0}
```

### Unit Test Helper (verified from helpers.py)
```python
# Source: tests/unit/intelligence/helpers.py
from tests.unit.intelligence.helpers import make_ohlcv
import numpy as np

n = 60
close = np.full(n, 5000.0)
df = make_ohlcv(close)
frames = {"main": df, "features": {"atr_14": 10.0, "bos_detected": 1.0, ...}}
result = plugin.compute_full(frames)
```

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Per-plugin stop math (ATR multiples hardcoded) | `frame_trade()` centralized (Phase 32) | All Phase 33 plugins inherit GARCH-adaptive stops automatically |
| Shadow mode before production | Fire immediately as production signals | Maximizes labeled training data from day 1; `validate_alpha.py` is the promotion gate |
| Single ORB plugin | Two plugins (trad_ORB15, trad_ORB30) | Independent statistical tracking; weight updater promotes the better variant |

## Open Questions

1. **Does `df` contain a `timestamp` column in replay?**
   - What we know: `session_extremes_setup.py` accesses `session_ny` from features (not from df timestamps directly), and `session_context.py` extracts timestamp from `df["timestamp"]`
   - What's unclear: Whether the bar dataframe passed to I7 plugins always has a `timestamp` column — confirmed for the session_context plugin which uses it, but I7 plugins typically don't access it directly
   - Recommendation: ORB plugins should prefer `features.get("session_ny")` as the primary session gate (already populated by SessionContextPlugin), and use timestamp extraction only for the specific 09:30/09:45/10:00 ORB window boundaries. Verify `df.columns` in a replay run during Wave 0.

2. **`rel_volume` field availability**
   - What we know: CONTEXT.md says "proxy via `rel_volume` if available"; this field is not in I1Indicators schema's declared core fields but I1 uses `extra='allow'`
   - What's unclear: Whether `rel_volume` is actually populated by any I1 plugin currently
   - Recommendation: ORB and VCP volume gates should use `df["volume"]` directly with rolling window mean as the primary implementation, checking `rel_volume` as optional bonus. This matches how `momentum_breakout.py` computes volume expansion inline.

3. **FailedBreakout `bos_level` persistence**
   - What we know: `bos_detected` fires on the breakout bar; `bos_level` is available on that bar
   - What's unclear: Whether `bos_level` remains populated in features for subsequent bars (bars 2 and 3 of the reversal window) or is reset to 0/None
   - Recommendation: Store `bos_level` in `_state[key]` on the bar where `bos_detected==1.0`. Use the stored value for reversal window checks on subsequent bars, independent of the live features.

## Validation Architecture

`nyquist_validation` is not set in `.planning/config.json` — treat as enabled.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing) |
| Config file | `pyproject.toml` or `.venv/bin/pytest` default |
| Quick run command | `.venv/bin/pytest tests/unit/intelligence/trading/ -v -x` |
| Full suite command | `.venv/bin/pytest tests/unit/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PLUG-01 | FailedBreakout fires on BOS + close-back-through within 3 bars | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_failed_breakout.py -x` | ❌ Wave 0 |
| PLUG-01 | FailedBreakout returns no_signal when bos_detected==0 | unit | same | ❌ Wave 0 |
| PLUG-01 | FailedBreakout returns no_signal when reversal window > 3 bars | unit | same | ❌ Wave 0 |
| PLUG-02 | ORB15 accumulates range 09:30–09:45 ET and fires on breakout with volume | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_orb15.py -x` | ❌ Wave 0 |
| PLUG-02 | ORB30 accumulates range 09:30–10:00 ET and fires on breakout with volume | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_orb30.py -x` | ❌ Wave 0 |
| PLUG-02 | ORB15/30 return no_signal outside 09:30–11:30 ET window | unit | same | ❌ Wave 0 |
| PLUG-03 | PrevDayLevelTest fires fade variant near PDH/PDL/PDC with reversal momentum | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_prev_day_level_test.py -x` | ❌ Wave 0 |
| PLUG-03 | PrevDayLevelTest fires continuation variant on re-test after breakout | unit | same | ❌ Wave 0 |
| PLUG-03 | PrevDayLevelTest returns no_signal when no prior session data | unit | same | ❌ Wave 0 |
| PLUG-04 | SecondLeg fires when price in 38.2%–61.8% Fib zone with trend regime | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_second_leg_continuation.py -x` | ❌ Wave 0 |
| PLUG-04 | SecondLeg returns no_signal when Leg 1 amplitude < 1.0×ATR | unit | same | ❌ Wave 0 |
| PLUG-04 | SecondLeg returns no_signal in ranging regime | unit | same | ❌ Wave 0 |
| PLUG-05 | VCP fires after 3+ successive H-L contractions with declining volume + expansion bar | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_vcp.py -x` | ❌ Wave 0 |
| PLUG-05 | VCP returns no_signal when hmm_regime_prob < 0.60 | unit | same | ❌ Wave 0 |
| PLUG-05 | VCP state resets at session boundary | unit | same | ❌ Wave 0 |
| ALL | All 6 plugins registered in TIER_I7 and pass validate_tier() | integration | `.venv/bin/pytest tests/unit/intelligence/test_correctness_audit.py -x` | ✅ (existing) |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/intelligence/trading/ -v -x`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/intelligence/trading/test_failed_breakout.py` — covers PLUG-01
- [ ] `tests/unit/intelligence/trading/test_orb15.py` — covers PLUG-02 (ORB15)
- [ ] `tests/unit/intelligence/trading/test_orb30.py` — covers PLUG-02 (ORB30)
- [ ] `tests/unit/intelligence/trading/test_prev_day_level_test.py` — covers PLUG-03
- [ ] `tests/unit/intelligence/trading/test_second_leg_continuation.py` — covers PLUG-04
- [ ] `tests/unit/intelligence/trading/test_vcp.py` — covers PLUG-05

*(Framework and conftest already exist — `tests/unit/intelligence/helpers.py` provides `make_ohlcv()` for all tests)*

## Sources

### Primary (HIGH confidence)
- `src/intelligence/trading/choch_reversal.py` — reference minimal I7 plugin implementation
- `src/intelligence/trading/session_extremes_setup.py` — reference session-gated plugin
- `src/intelligence/trading/momentum_breakout.py` — reference BOS-consuming plugin
- `src/intelligence/trading/trend_following.py` — reference HMM regime gate pattern
- `src/intelligence/trading/trade_framer.py` — stop/target resolution, entry type resolution
- `src/intelligence/context/session_context.py` — ET timezone helpers, `_in_window()`
- `src/intelligence/register_plugins.py` — TIER_I7 list, registration pattern
- `src/intelligence/schemas.py` — all feature field names and types verified
- `src/intelligence/CLAUDE.md` — plugin protocol, `regime_type` requirement
- `src/intelligence/plugins.py` — `InputSpec`, `PluginRegistry.validate_tier()`
- `src/intelligence/trading/signal_schema.py` — required signal fields for `signal.v1`
- `src/intelligence/trading/aggregator.py` — `TREND_SETUPS`, regime gate mechanics
- `src/intelligence/trading/exhaustion_utils.py` — exhaustion guard helper

### Secondary (MEDIUM confidence)
- `.planning/phases/33-five-new-i7-signal-plugins/33-CONTEXT.md` — locked decisions
- `.planning/REQUIREMENTS.md` PLUG-01 through PLUG-05 — requirement specs

## Metadata

**Confidence breakdown:**
- Plugin protocol and field names: HIGH — directly verified from source code
- trade_framer behavior: HIGH — full source read, entry resolution logic understood
- Session timezone pattern: HIGH — directly verified from session_context.py
- Feature field availability (all consumed fields): HIGH — verified in schemas.py
- ORB range storage in `_state`: HIGH — pattern from existing stateful plugins
- VCP algorithm: MEDIUM — detection logic is Claude's discretion; specific implementation TBD

**Research date:** 2026-03-17
**Valid until:** 2026-04-17 (stable codebase; plugin protocol rarely changes)
