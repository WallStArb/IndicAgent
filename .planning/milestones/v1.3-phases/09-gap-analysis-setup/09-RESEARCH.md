# Phase 09: GapAnalysisSetup - Research

**Researched:** 2026-03-02
**Domain:** I7 trading setup plugin — opening gap detection, fade/continuation classification, signal construction
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **Prior close data source:** Use `opening_gap_pct` and `prior_session_close` already computed by `SessionLevelsPlugin` (I3) from the `features` dict — do NOT re-derive from raw bars
- **Time window gating:** Plugin fires only when `bars_since_session_start` (from I4 SessionContextPlugin) is ≤ 30 bars (first 30 minutes after NY open). After 30 bars, no signal fires. If unavailable, fall back to `session_ny` flag as coarse check.
- **Gap thresholds:**
  - Minimum gap size: `0.3 × atr_14` — smaller gaps not worth trading
  - Continuation threshold: `1.0 × atr_14` — gaps ≥ this level with confirming volume classify as continuation
  - Fade territory: `0.3–1.0 × atr_14` — default bias is fade
  - Class-level params: `min_gap_atr_mult=0.3`, `continuation_atr_mult=1.0`
- **Fade vs continuation classification:**
  - Continuation: gap_size_atr >= `continuation_atr_mult` AND volume_ratio >= 1.5× recent average
  - Fade: gap in `[min_gap_atr_mult, continuation_atr_mult)` range OR large gap without volume confirmation
  - Volume from `volume_ratio` feature if available; fallback to compare current bar volume to mean of last 20 bars from df
- **Entry type logic:**
  - `at_limit`: fade setups — entered at current session open price
  - `at_pullback`: continuation setups — entered at open ± 0.25 * atr (pullback entry)
- **Stop levels:**
  - Stop: `1.5 × atr_14` beyond entry in adverse direction
  - Fade stops placed `1.0 × atr` beyond the open (different from plan 02 which says 1.0× for fade, 1.5× for cont)
- **Target levels:**
  - Fade target: prior session close level (gap fill)
  - Continuation target 1: `2.0 × atr_14` extension from open
  - Continuation target 2: `3.0 × atr_14` extension
  - Fade target 2: `0.5 × atr_14` beyond prior close (overshoot)
- **Symbol filtering:** InputSpec uses `symbol=".*"` — ES/NQ focus is operational only, not code-level

### Claude's Discretion

- Exact confidence scoring formula (base suggestion: normalize gap_size/ATR and volume_ratio into 0–1)
- Exact pullback entry offset (plan 02 suggests 0.25 × atr)
- Target array ordering and count
- How to handle `opening_gap_pct = None` → return no signal

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| GAP-01 | GapAnalysisSetup detects opening gaps by comparing prior close to current open price | SessionLevels already computes `prior_session_close`; plugin reads `open_[-1] - close[-2]` from df for detection; `opening_gap_pct` available as pre-computed percentage |
| GAP-02 | Plugin classifies gap direction (bullish/bearish) and bias (fade vs continuation) based on gap size relative to ATR and volume context | ATR from `features["atr_14"]` with np.mean fallback; volume ratio from `volume_ratio` feature or df["volume"] rolling mean; thresholds are class-level params |
| GAP-03 | Plugin produces a setup signal with confidence score, entry type (at_limit/at_pullback), stop, and target levels | Confidence: normalize gap_size/ATR + volume bonus; entry_type field; stop_loss float; targets list[float] — matches exact output schema in plan 09-01 |
</phase_requirements>

## Summary

Phase 09 adds `GapAnalysisSetupPlugin` — the 15th I7 trading setup plugin. The implementation is a new file at `src/intelligence/trading/gap_analysis_setup.py` following the exact dataclass pattern of `MeanReversionPlugin`. All design decisions are locked in CONTEXT.md and detailed further in 09-01-PLAN.md and 09-02-PLAN.md, which already exist. Two plans are written: Plan 01 creates the failing TDD test suite (RED phase), Plan 02 implements the plugin and wires the registry (GREEN phase).

The plugin reads upstream I3/I4 outputs (`prior_session_close`, `opening_gap_pct`, `bars_since_session_start`, `session_ny`) from `frames["features"]`, computes gap size against ATR, classifies fade/continuation, and returns a fully-specified signal dict. No new dependencies are required — numpy and standard library are sufficient.

The primary risk is test fixture construction: `make_ohlcv()` generates synthetic opens from a random seed, so gap injection requires explicitly overwriting `df.at[df.index[-1], "open"]` after the helper call. This is the established pattern per plan 09-01.

**Primary recommendation:** Execute plan 09-01 first (write failing tests), then 09-02 (implement plugin + wire registry). The plans are complete and specify exact logic — no further design decisions needed before execution.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| numpy | project-installed | ATR fallback calculation, array slicing, volume mean | Already used by all I7 plugins; no new install |
| pandas | project-installed | DataFrame access in `compute_full()` | All plugins receive OHLCV as pd.DataFrame |
| dataclasses | stdlib | Plugin struct definition | Project-wide plugin protocol uses `@dataclass` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | project-installed | TDD RED/GREEN cycle | Plan 01 test file, Plan 02 verification |
| ruff | project-installed | Lint gate | Post-implementation quality check |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Raw df gap detection | opening_gap_pct from SessionLevels | SessionLevels already handles session boundary correctly; re-deriving wastes compute and risks subtle inconsistency |
| Custom volume ratio computation | volume_ratio from features | If `volume_ratio` is available upstream, use it; df fallback only when missing |

**Installation:** None required — all dependencies already present.

## Architecture Patterns

### Recommended Project Structure
```
src/intelligence/trading/
├── gap_analysis_setup.py    # NEW — GapAnalysisSetupPlugin
├── mean_reversion.py        # Reference pattern (closest match)
├── trend_following.py       # Reference for confidence scoring pattern
└── ...

tests/unit/intelligence/
├── test_gap_analysis_setup.py   # NEW — Plan 01 RED, Plan 02 GREEN
└── test_i7_registration.py      # UPDATE — count 85→86, add trad_GapAnalysisSetup
```

### Pattern 1: I7 Plugin Dataclass
**What:** All I7 plugins are `@dataclass` with exact field names, no inheritance, module-level `plugin` singleton.
**When to use:** Always for I7 plugins — the registry expects this shape.
**Example:**
```python
# Source: src/intelligence/trading/mean_reversion.py (verified)
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import numpy as np
from ..plugins import InputSpec

@dataclass
class GapAnalysisSetupPlugin:
    name: str = "trad_GapAnalysisSetup"
    outputs: frozenset[str] = frozenset({
        "signal_type", "direction", "bias", "gap_size_atr",
        "confidence", "entry_type", "entry_price", "stop_loss",
        "targets", "regime_context", "supporting_factors",
    })
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "gap"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    # class-level threshold params
    gap_min_atr: float = 0.3
    gap_continuation_atr: float = 1.0
    volume_confirm_ratio: float = 1.2
    stop_atr_fade: float = 1.0
    stop_atr_cont: float = 1.5
    target_atr_cont: float = 2.0
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]: ...
    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}

plugin = GapAnalysisSetupPlugin()
```

### Pattern 2: Gap Detection Logic
**What:** `gap_size = open_[-1] - close[-2]` — compares current bar open to prior bar close.
**When to use:** Core detection step in `compute_full()`, after guard check.
**Example:**
```python
# Source: plan 09-02 interfaces (verified against session_levels.py outputs)
close = df["close"].to_numpy(dtype=float)
open_ = df["open"].to_numpy(dtype=float)
high = df["high"].to_numpy(dtype=float)
low = df["low"].to_numpy(dtype=float)

gap_size = open_[-1] - close[-2]  # prior close vs current open

# ATR guard (pattern from mean_reversion.py and trend_following.py)
atr = features.get("atr_14", 0.0)
if atr <= 0:
    atr = float(np.mean(high[-14:] - low[-14:]))
if atr <= 0:
    return self._no_signal()

# Gate on gap size
if abs(gap_size) < self.gap_min_atr * atr:
    return self._no_signal()

gap_size_atr = abs(gap_size) / atr
direction = 1 if gap_size > 0 else -1
```

### Pattern 3: Volume Ratio Check
**What:** Check if current bar volume is above threshold relative to recent mean.
**When to use:** Fade vs continuation classification step.
**Example:**
```python
# Source: plan 09-02 task 1 (verified against context decisions)
vol = df["volume"].to_numpy(dtype=float)
vol_mean = np.mean(vol[-21:-1]) if len(vol) > 21 else np.mean(vol[:-1])
vol_ratio = vol[-1] / vol_mean if vol_mean > 0 else 1.0
high_volume = vol_ratio >= self.volume_confirm_ratio
```

### Pattern 4: Registration in register_plugins.py
**What:** Import at top + `register_pattern()` call + append to `TIER_I7`.
**When to use:** All new I7 plugins must follow this exact sequence.
**Example:**
```python
# Source: src/intelligence/register_plugins.py (verified current state)
# 1. Import at top with other trading imports (alphabetical by alias):
from .trading.gap_analysis_setup import plugin as gap_analysis_setup_plugin

# 2. In register_all_plugins(), after regime_transition_plugin:
registry.register_pattern(gap_analysis_setup_plugin)

# 3. In TIER_I7 list, append:
gap_analysis_setup_plugin.name,
```

### Pattern 5: TDD Test Fixture with Gap Injection
**What:** Use `make_ohlcv()` then manually overwrite the last open price to simulate a gap.
**When to use:** Any test that needs a controlled gap size.
**Example:**
```python
# Source: plan 09-01 implementation notes (verified against helpers.py)
from tests.unit.intelligence.helpers import make_ohlcv
import numpy as np

close = np.linspace(5000, 5200, 100)
df = make_ohlcv(close)
atr = 10.0
# Inject bullish gap of 0.5 ATR
df.at[df.index[-1], "open"] = float(df["close"].iloc[-2]) + 0.5 * atr
features = {"atr_14": atr}
plugin = GapAnalysisSetupPlugin()
result = plugin.compute_full({"main": df, "features": features})
```

### Anti-Patterns to Avoid
- **Importing `opening_gap_pct` as the sole gap detector:** `opening_gap_pct` uses `session["open"].iloc[0]` (first bar of session), which differs from `open_[-1] - close[-2]` (bar-level gap). Use the raw open/close arrays for detection.
- **Hardcoding thresholds:** All ATR multipliers must be class-level fields so tests can override them.
- **Returning `_no_signal()` for `opening_gap_pct = None`:** Correct behavior. When SessionLevels has insufficient history, no `prior_session_close` means no signal.
- **Using `if value` for numeric feature checks:** Use `isinstance(val, (int, float))` or explicit `is not None` — MagicMock is truthy and `float(MagicMock())` returns 1.0 (CLAUDE.md gotcha).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Session boundary detection | Custom open/close derivation | `prior_session_close` from SessionLevels features | SessionLevels handles session boundary correctly; 390-bar windows, prior session block already computed |
| Time-of-day gating | Timestamp parsing and ET conversion | `bars_since_session_start` and `session_ny` from SessionContextPlugin features | SessionContextPlugin already does ET timezone conversion and 9:30 open detection |
| ATR calculation | Rolling ATR from scratch | `features["atr_14"]` with `np.mean(high[-14:] - low[-14:])` fallback | ATR plugin already computed upstream; fallback pattern is established in every existing I7 plugin |

**Key insight:** The upstream I3/I4 pipeline has already computed every value this plugin needs. The gap plugin is a consumer, not a producer, of session and ATR data.

## Common Pitfalls

### Pitfall 1: Gap Index Off-By-One
**What goes wrong:** Using `close[-1]` instead of `close[-2]` as prior close — computes within-bar distance not cross-bar gap.
**Why it happens:** `open_[-1]` and `close[-1]` are the same bar. The gap is prior bar's close to current bar's open.
**How to avoid:** `gap_size = open_[-1] - close[-2]` — always index back one further on close.
**Warning signs:** Tests for "no gap" with `open == close[-2]` fail, or gap size always comes out small.

### Pitfall 2: make_ohlcv Gap Injection Not Taking Effect
**What goes wrong:** Test builds a DataFrame then creates a gap, but `compute_full()` still sees no gap.
**Why it happens:** `make_ohlcv()` generates `open_` from a random seed offset of `close` — the last bar's open is near close[-1], not close[-2].
**How to avoid:** Always explicitly set `df.at[df.index[-1], "open"] = float(df["close"].iloc[-2]) + offset` after calling `make_ohlcv()`. Do not rely on the generated open.
**Warning signs:** "bullish gap" test returns signal_type="none".

### Pitfall 3: Volume Ratio Edge Case on Short Histories
**What goes wrong:** `np.mean(vol[-21:-1])` on a 50-bar DataFrame returns empty array if fewer than 22 bars.
**Why it happens:** Slicing `[-21:-1]` on a 50-bar DataFrame is fine, but on edge-case test fixtures with exactly 50 bars, it works. On 20-bar fixtures it may not.
**How to avoid:** Guard: `len(vol) > 21` before computing 21-bar mean; fallback to `np.mean(vol[:-1])` or treat as normal volume.
**Warning signs:** ZeroDivisionError or NaN in volume ratio.

### Pitfall 4: Misaligned stop_atr Multipliers Between CONTEXT.md and Plan 02
**What goes wrong:** CONTEXT.md says stop is `1.5 × atr_14`, but Plan 02 task 1 says fade stop = `1.0 × atr` and continuation stop = `1.5 × atr`. These are different.
**Why it happens:** CONTEXT.md describes the stop principle; Plan 02 specifies exact per-bias values.
**How to avoid:** Use Plan 02's specification (the more detailed, later document): `stop_atr_fade=1.0`, `stop_atr_cont=1.5`. The class-level fields make this configurable regardless.
**Warning signs:** Test `assert stop_loss < entry_price (for long fade)` fails because stop is too far.

### Pitfall 5: Registration Count Assertion in test_i7_registration.py
**What goes wrong:** After wiring the plugin, the registration test fails with `Expected 85, got 86`.
**Why it happens:** The test asserts `total == 85` — the pre-phase count.
**How to avoid:** In Plan 02 Task 2, update the test to `total == 86` and the docstring from "14 I7 plugins" to "15 I7 plugins". Add "trad_GapAnalysisSetup" to `expected_i7` set.
**Warning signs:** test_i7_registration.py fails after plugin registration but test_gap_analysis_setup.py passes.

### Pitfall 6: Session Context Dependency in Unit Tests
**What goes wrong:** Tests expect time-gating to be active, but unit tests don't inject `bars_since_session_start` — plugin silently falls through to no-signal.
**Why it happens:** If time gating is implemented as a hard gate on `bars_since_session_start <= 30`, unit tests that don't inject this feature will never fire a signal.
**How to avoid:** When `bars_since_session_start` is absent from features, the plugin should fire regardless of time gate (feature not present = not constrained). Only gate when the feature is present and > 30. This matches the fallback pattern: "if unavailable, fall back to session_ny flag as coarse check."
**Warning signs:** All classification tests return no signal despite valid gap injection.

## Code Examples

Verified patterns from existing codebase:

### Full compute_full() Logic Skeleton (from plan 09-02 + verified patterns)
```python
# Source: plan 09-02 task 1 action block + mean_reversion.py pattern
def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
    df = frames.get("main")
    features = frames.get("features") or {}
    if df is None or len(df) < self.min_lookback:
        return {}

    # Time gate (I4 SessionContext)
    bars_since = features.get("bars_since_session_start")
    if bars_since is not None and float(bars_since) > 30:
        session_ny = features.get("session_ny", 1.0)
        if not session_ny:
            return self._no_signal()

    # Gap detection (GAP-01)
    close = df["close"].to_numpy(dtype=float)
    open_ = df["open"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    gap_size = open_[-1] - close[-2]
    direction = 1 if gap_size > 0 else (-1 if gap_size < 0 else 0)
    if direction == 0:
        return self._no_signal()

    # ATR
    atr = float(features.get("atr_14") or 0.0)
    if atr <= 0:
        atr = float(np.mean(high[-14:] - low[-14:]))
    if atr <= 0:
        return self._no_signal()

    # Minimum gap gate
    if abs(gap_size) < self.gap_min_atr * atr:
        return self._no_signal()

    gap_size_atr = abs(gap_size) / atr

    # Volume ratio (GAP-02)
    vol = df["volume"].to_numpy(dtype=float)
    vol_mean = np.mean(vol[-21:-1]) if len(vol) > 21 else (np.mean(vol[:-1]) if len(vol) > 1 else 1.0)
    vol_ratio = vol[-1] / vol_mean if vol_mean > 0 else 1.0
    high_volume = vol_ratio >= self.volume_confirm_ratio

    # Bias classification (GAP-02)
    if gap_size_atr >= self.gap_continuation_atr and high_volume:
        bias = "continuation"
    else:
        bias = "fade"

    # Entry (GAP-03)
    prior_close = float(close[-2])
    if bias == "fade":
        entry_type = "at_limit"
        entry = prior_close
    else:
        entry_type = "at_pullback"
        entry = open_[-1] + (-direction * 0.25 * atr)

    # Stop
    if bias == "fade":
        stop = open_[-1] - direction * self.stop_atr_fade * atr
    else:
        stop = open_[-1] - direction * self.stop_atr_cont * atr

    # Targets
    if bias == "fade":
        targets = [round(prior_close, 2), round(prior_close + direction * 0.5 * atr, 2)]
    else:
        targets = [
            round(open_[-1] + direction * self.target_atr_cont * atr, 2),
            round(open_[-1] + direction * 3.0 * atr, 2),
        ]

    # Confidence
    base = min(1.0, gap_size_atr / 2.0)
    if high_volume:
        base += 0.15
    confidence = round(min(0.95, max(0.05, base)), 4)

    # Supporting factors
    supporting: list[str] = []
    if gap_size_atr >= 1.0:
        supporting.append("large_gap")
    if high_volume:
        supporting.append("volume_confirm")
    supporting.append(f"{bias}_bias")

    signal_type = f"gap_{bias}_{'long' if direction == 1 else 'short'}"

    return {
        "signal_type": signal_type,
        "direction": direction,
        "bias": bias,
        "gap_size_atr": round(gap_size_atr, 4),
        "confidence": confidence,
        "entry_type": entry_type,
        "entry_price": round(float(entry), 2),
        "stop_loss": round(float(stop), 2),
        "targets": targets,
        "regime_context": "gap_open",
        "supporting_factors": supporting,
    }
```

### Test Pattern: Gap Injection
```python
# Source: plan 09-01 + helpers.py (verified)
import numpy as np
from tests.unit.intelligence.helpers import make_ohlcv
from src.intelligence.trading.gap_analysis_setup import GapAnalysisSetupPlugin

def make_gap_df(gap_atr_mult: float, atr: float = 10.0, n: int = 100, bullish: bool = True):
    close = np.linspace(5000, 5200, n)
    df = make_ohlcv(close)
    direction = 1 if bullish else -1
    df.at[df.index[-1], "open"] = float(df["close"].iloc[-2]) + direction * gap_atr_mult * atr
    return df

def test_bullish_fade_gap():
    df = make_gap_df(gap_atr_mult=0.5)
    plugin = GapAnalysisSetupPlugin()
    result = plugin.compute_full({"main": df, "features": {"atr_14": 10.0}})
    assert result["direction"] == 1
    assert result["bias"] == "fade"
    assert result["signal_type"] == "gap_fade_long"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hardcode ATR fallback | Class-level `gap_min_atr` param with `np.mean` fallback | Established pattern in existing plugins | Testable, configurable thresholds |
| Local string tier lists in each service | Single `TIER_I7` in `register_plugins.py` | Phase 0 | Services import from one source; `validate_tier()` at startup prevents drift |

## Open Questions

1. **Stop direction for fade signals**
   - What we know: Plan 02 says "fade long: stop = open_[-1] - stop_atr_fade * atr" (below the gap open)
   - What's unclear: CONTEXT.md says stop is "1.5 × atr_14 beyond entry in adverse direction" — but Plan 02 uses 1.0× for fade
   - Recommendation: Follow Plan 02 (more specific): `stop_atr_fade=1.0`, `stop_atr_cont=1.5`. The CONTEXT.md multiplier of 1.5 applies to continuation. This matches TrendFollowing's multiplier for its stops.

2. **Time gate behavior when `bars_since_session_start` is absent**
   - What we know: Feature is only populated when df has a `timestamp` column; pure unit tests won't have it
   - What's unclear: Should gate be "absent → block signal" or "absent → allow signal"?
   - Recommendation: Absent → allow signal (feature not present = not constrained). This matches how other plugins treat missing features (fall through to next check). Tests that don't inject a timestamp will still work.

## Validation Architecture

Skipped — `nyquist_validation` not enabled in `.planning/config.json`.

(Test mapping is documented inline in plan files 09-01-PLAN.md and 09-02-PLAN.md.)

## Sources

### Primary (HIGH confidence)
- `src/intelligence/trading/mean_reversion.py` — verified plugin dataclass pattern, ATR fallback, _no_signal(), confidence scoring
- `src/intelligence/trading/trend_following.py` — verified confidence formula structure and supporting_factors pattern
- `src/intelligence/register_plugins.py` — verified current TIER_I7 (14 plugins), registration call site, import style
- `src/intelligence/structure/session_levels.py` — verified `prior_session_close`, `opening_gap_pct` are computed outputs
- `src/intelligence/context/session_context.py` — verified `bars_since_session_start`, `session_ny` are computed outputs
- `src/intelligence/plugins.py` — verified `InputSpec` dataclass signature
- `tests/unit/intelligence/helpers.py` — verified `make_ohlcv(close, volume=None)` signature and random-seed open generation
- `tests/unit/intelligence/test_i7_registration.py` — verified current counts: 14 I7 plugins, total 85 plugins
- `.planning/milestones/v1.3-phases/09-gap-analysis-setup/09-01-PLAN.md` — verified test contracts and output schema
- `.planning/milestones/v1.3-phases/09-gap-analysis-setup/09-02-PLAN.md` — verified implementation logic and registration steps

### Secondary (MEDIUM confidence)
- N/A — all findings verified against live codebase

### Tertiary (LOW confidence)
- N/A

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified in existing plugins, no new dependencies
- Architecture: HIGH — all patterns verified against 14 existing I7 plugins in the codebase
- Pitfalls: HIGH — gap index off-by-one and fixture injection issues verified against helpers.py source; registration count from test file source

**Research date:** 2026-03-02
**Valid until:** 2026-04-01 (stable domain — no external API changes possible)
