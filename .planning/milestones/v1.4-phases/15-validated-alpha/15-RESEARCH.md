# Phase 15: Validated Alpha - Research

**Researched:** 2026-03-08
**Domain:** Statistical validation infrastructure + technical indicator implementation (I1/I2/I5 plugin tier)
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Validation Gate Thresholds (ALPHA-01)**
- Minimum N gate: 30 signal bars with forward return data — matches FEED-02 promotion gate
- Correlation gate (hard): Pearson r > 0, p < 0.05 between indicator signal direction and N-bar forward close-to-close returns
- Forward return window: TF-appropriate — 5 bars for 1m, 3 bars for 5m/15m/1h
- ADF stationarity: Informational only — not a hard gate; momentum indicators expected non-stationary
- False-positive rate: Informational only — no hard threshold until baselines exist

**Validation Script Design (ALPHA-01)**
- Interface: `python production/scripts/validate_alpha.py --plugin <name> --days <N> [--symbol-filter <SYM>] [--promote]`
- Data sufficiency check: Script queries `intelligence_features` for row count; auto-triggers `historical_backfill.py --replay-only --days N` internally if insufficient data
- Correlation source: Forward N-bar close-to-close returns from `intelligence_features` OHLCV — does NOT depend on `signal_ledger.pnl_r`
- Output: Writes `docs/validation/YYYY-MM-DD-<plugin>.json` + terminal summary on every run
- Promotion flag (`--promote`): Without = evidence-only mode; With = gates must pass (hard block) + auto-patches `register_plugins.py` + writes validation report
- Hard block: `--promote` only executes if all hard gates pass; exits non-zero on failure

**Candlestick Tier 1 Extension (ALPHA-03)**
- Extend existing `CandlestickPatternsPlugin` — raise `min_lookback=3`, add all 10 patterns to single plugin
- I7 gating: `CandlestickPatternSetupPlugin` uses explicit named reads — new I5 fields exist but NOT read by I7 until `--promote` patches the I7 plugin
- `--promote` patches both `register_plugins.py` AND `CandlestickPatternSetupPlugin` named reads
- Validation priority order: Three White Soldiers/Three Black Crows first (0.72), then Morning/Evening Star/Three Inside Up-Down (0.65), then Harami Cross/Dark Cloud Cover/Piercing Line (0.55–0.58)

**Delivery Sequencing**
- 5 plans: Plan 1 = validate_alpha.py script; Plan 2 = Derivative Oscillator I2; Plan 3 = Candlestick Tier 1 x10; Plan 4 = MACD hist acceleration; Plan 5 = AC Oscillator I1
- Each of Plans 2–5 ends with: `validate_alpha.py --plugin X --days 90 --promote`
- Independent failure isolation: a plan failing does not block the others

### Claude's Discretion
- Exact format for validation report files (JSON structure, field names)
- How to handle fewer than 30 bars at validation time (report N, exit with informative message)
- Column names and index choices on `intelligence_features` / `market_data_ohlcv` queries
- Exact `--symbol-filter` implementation (comma-separated values)
- DerivOsc formula implementation (Patrick Mulloy triple-smoothed RSI derivative)

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| ALPHA-01 | Historical validation script — ADF stationarity, correlation with forward returns, signal frequency, false-positive rate; promotion gate for all new alpha sources | CLI pattern from existing scripts; scipy.stats for Pearson + p-value; statsmodels for ADF; psycopg2 for DB queries; argparse patterns confirmed in historical_backfill.py |
| ALPHA-02 | Derivative Oscillator I2 plugin — `deriv_osc`, `deriv_osc_signal`, `deriv_osc_cross_bullish`, `deriv_osc_cross_bearish`; reads `rsi_14` from features dict | I2 composite pattern fully established in macd_events.py; RSI-14 confirmed available in features dict from RsiPlugin; crossover_detect utility in composites/common.py |
| ALPHA-03 | Candlestick Tier 1 x10 at I5 + I7 wiring for validated patterns | CandlestickPatternsPlugin extension path confirmed; min_lookback raise to 3; I7 explicit named-read whitelist mechanism already in candlestick_pattern_setup.py |
| ALPHA-04 | MACD histogram acceleration — `macd_hist_accel` (float) and `macd_hist_contracting` (bool) added to MACDEventsPlugin | `macd_histogram_12_26_9` available in features dict; prev_hist already read by MACDEventsPlugin; extension is additive, 2 new output fields only |
| ALPHA-05 | AC Oscillator I1 plugin — `ao` (Awesome Oscillator) and `ac` (Acceleration/Deceleration); pure midpoint SMA; registered in TIER_I1 | I1 indicator pattern established in rsi.py and macd.py; frames["main"] OHLCV access confirmed; SMA computation via pandas rolling() |
</phase_requirements>

---

## Summary

Phase 15 delivers two things: a validation infrastructure (ALPHA-01) that closes the "earn the right through proof" discipline, and four new alpha sources (ALPHA-02 through ALPHA-05) that are the first to be gated by it. The validation script is the load-bearing piece — it must be built first and the four indicator plans each terminate by running it.

All four indicators slot into established plugin tiers using well-understood patterns. The Derivative Oscillator (I2) reads RSI-14 from the features dict exactly as MACDEventsPlugin reads MACD. The AC Oscillator (I1) is a pure midpoint SMA computation on raw OHLCV, identical in structure to existing I1 indicators. The MACD acceleration enhancement is additive — two new output fields on an existing plugin with prev_hist already available. The Candlestick extension raises min_lookback by one bar and adds three-bar pattern detection; the promotion gate mechanism (explicit named reads in I7) is already implemented and just needs patching.

The principal risk is data sufficiency: the validation script auto-triggers `historical_backfill.py --replay-only` when fewer than 30 qualifying bars exist, making this zero-friction from the user's perspective. The promotion flow (hard block on gate failure, auto-patch of `register_plugins.py`, `registry.validate_tier()` crash-check at startup) creates a verifiable audit trail that any candlestick pattern or indicator has cleared the statistical bar before touching live signals.

**Primary recommendation:** Build validate_alpha.py first (Plan 1), run it against existing I5 candlestick outputs to verify the gate works before building new plugins, then proceed Plans 2–5 in sequence with each terminating in a validated promotion.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `scipy.stats` | bundled with scipy | Pearson correlation + p-value (`pearsonr`), ADF supplementary | Already in .venv; statsmodels dependency brings scipy |
| `statsmodels` | present in .venv | ADF stationarity test (`adfuller`) | Standard for ADF in Python quant work |
| `psycopg2` | present in .venv | DB queries against `intelligence_features` + `market_data_ohlcv` | Same driver used by existing scripts (historical_backfill.py uses psycopg2 directly) |
| `pandas` | present | OHLCV DataFrame manipulation, rolling SMA, EMA | Already the codebase standard |
| `numpy` | present | Numeric arrays, SMA computation | Plugin standard |
| `argparse` | stdlib | CLI flag parsing | Established pattern in historical_backfill.py and pipeline_reset.py |
| `json` + `pathlib` | stdlib | Writing validation report files to `docs/validation/` | Consistent with codebase stdlib preference |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `subprocess` | stdlib | Invoke `historical_backfill.py --replay-only` from validate_alpha.py when data is sparse | Only when row count check finds N < 30 qualifying bars |
| `datetime` | stdlib | UTC timestamps in validation reports | All timestamps in this codebase use UTC |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| scipy.stats.pearsonr | numpy.corrcoef | pearsonr returns p-value directly; corrcoef requires manual t-stat computation |
| psycopg2 direct | asyncpg | validate_alpha.py is a sync CLI script; asyncpg adds unnecessary complexity |
| subprocess for backfill | importlib direct call | subprocess isolates the backfill environment; importlib path manipulation is fragile |

**Installation:** No new dependencies — all libraries already present in `.venv`.

---

## Architecture Patterns

### Plugin Tier Placement

```
I1 (indicators/):    AC Oscillator → reads frames["main"] OHLCV directly
I2 (composites/):    Derivative Oscillator → reads features dict (I1 outputs already computed)
                     MACD Acceleration → additive fields on existing MACDEventsPlugin
I5 (patterns/):      CandlestickPatternsPlugin → extend in-place, raise min_lookback to 3
I7 (trading/):       CandlestickPatternSetupPlugin → explicit named-read whitelist
```

### Pattern 1: I1 Indicator Plugin (AC Oscillator)

**What:** Pure OHLCV computation, no upstream features dependency. Incremental state via rolling averages.
**When to use:** Any indicator requiring only raw price/volume data.

```python
# Source: mirrors src/intelligence/indicators/rsi.py and macd.py patterns
@dataclass
class ACOscillatorPlugin:
    name: str = "ind_ACOscillator"
    outputs: frozenset[str] = frozenset({"ao", "ac"})
    min_lookback: int = 40          # 34 for SMA34 + warmup
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"momentum"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}
        midpoint = (df["high"] + df["low"]) / 2
        ao = midpoint.rolling(5).mean() - midpoint.rolling(34).mean()
        ac = ao - ao.rolling(5).mean()
        return {"ao": float(ao.iloc[-1]), "ac": float(ac.iloc[-1])}

plugin = ACOscillatorPlugin()
```

### Pattern 2: I2 Composite Plugin (Derivative Oscillator)

**What:** Reads from features dict (I1 already computed), no raw OHLCV access needed.
**When to use:** Any composite that derives from I1 output fields.

```python
# Source: mirrors src/intelligence/composites/macd_events.py pattern
# DerivOsc = EMA3(EMA5(RSI14)) - SMA9(EMA3(EMA5(RSI14)))
# Requires _state for EMA rolling — use compute_full with pandas ewm on synthetic series
@dataclass
class DerivativeOscillatorPlugin:
    name: str = "cmp_DerivativeOscillator"
    outputs: frozenset[str] = frozenset({
        "deriv_osc", "deriv_osc_signal",
        "deriv_osc_cross_bullish", "deriv_osc_cross_bearish"
    })
    min_lookback: int = 1           # features dict only; actual warmup is handled by RSI plugin
    supports_incremental: bool = False
    inputs: tuple[InputSpec, ...] = ()   # reads features, no raw frames
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        rsi = features.get("rsi_14")
        if not isinstance(rsi, (int, float)):
            return {}
        # EMA smoothing requires series history — must use _state to track
        # EMA5 of RSI: alpha = 2/(5+1)
        # EMA3 of EMA5: alpha = 2/(3+1)
        ...
```

**Implementation note (Claude's Discretion):** The Derivative Oscillator requires at least a short window of RSI-14 history to compute EMA5→EMA3 chain. The two approaches are:
1. Track running EMA state in `_state` (alpha-update per bar) — matches how MACDPlugin handles incremental EMA.
2. Read a windowed RSI series from frames["main"] recomputed — unnecessarily duplicates RSI work.

Use approach 1: maintain `_state["ema5"]`, `_state["ema3"]`, `_state["sma9_buffer"]` (deque of last 9 ema3 values). Warmup: return `{}` until `len(_state["sma9_buffer"]) >= 9`. The SMA9 signal line is a simple rolling mean of the 9 most recent ema3 values.

**Crossover detection:** Use `crossover_detect()` from `composites/common.py` — exactly as MACDEventsPlugin does for MACD line vs signal line.

### Pattern 3: Additive I2 Fields (MACD Acceleration)

**What:** Add outputs to an existing plugin without changing existing outputs or state.
**When to use:** Enhancement to a plugin where prev value is already tracked.

```python
# Source: src/intelligence/composites/macd_events.py — prev_hist already read from prev_features
# macd_hist_accel = hist - prev_hist  (rate of change, float)
# macd_hist_contracting = abs(hist) < abs(prev_hist)  (bool, trend losing momentum)
out["macd_hist_accel"] = float(hist - prev_hist) if is_num(prev_hist) else 0.0
out["macd_hist_contracting"] = 1 if (is_num(prev_hist) and abs(hist) < abs(prev_hist)) else 0
```

`outputs` frozenset must be updated to include both new fields. The `default_factory=lambda: frozenset({...})` pattern in MACDEventsPlugin must have both new keys added.

### Pattern 4: Three-Bar Candlestick Detection (I5)

**What:** Extend `CandlestickPatternsPlugin` with patterns requiring 3 bars (c=current, p=prior, pp=two bars ago).
**When to use:** Any pattern that needs three-bar context.

```python
# Source: src/intelligence/patterns/candlestick_patterns.py
# Raise min_lookback from 2 to 3; add to compute_full after existing 2-bar patterns:
pp = df.iloc[-3]  # two bars ago
pp_o, pp_h, pp_l, pp_c = float(pp["open"]), float(pp["high"]), float(pp["low"]), float(pp["close"])
```

**Three White Soldiers (bullish, 0.72):** Three consecutive bullish bars, each closing near high, each opening within prior body. `pp_c > pp_o and p_c > p_o and c_c > c_o` + each body > 0.5 × range + each open within prior body.

**Three Black Crows (bearish, 0.72):** Mirror of Three White Soldiers.

**Morning Star (bullish, 0.65):** pp=large bearish, p=small body (star), c=large bullish closing above pp midpoint.

**Evening Star (bearish, 0.65):** Mirror of Morning Star.

**Three Inside Up (bullish, 0.65):** pp=large bearish, p=bullish inside pp (harami), c=bullish close above pp open.

**Three Inside Down (bearish, 0.65):** Mirror of Three Inside Up.

**Harami Cross (neutral→reversal, 0.58):** pp=large body, p=doji inside pp body.

**Dark Cloud Cover (bearish, 0.55):** pp=bullish, c=opens above pp high, closes below pp midpoint (bearish engulf of upper half).

**Piercing Line (bullish, 0.55):** pp=bearish, c=opens below pp low, closes above pp midpoint (bullish engulf of lower half).

All 10 patterns added to `outputs` frozenset. `min_lookback` raised from 2 to 3.

### Pattern 5: Validation Script Architecture

```
production/scripts/validate_alpha.py
├── argparse: --plugin, --days, --symbols-filter, --promote
├── DB connection: psycopg2 (same pattern as historical_backfill.py)
├── Data sufficiency check: SELECT count(*) WHERE <plugin_field> IS NOT NULL AND <timeframe>
│   └── If N < 30: subprocess.run(["python", "historical_backfill.py", "--replay-only", "--days", str(days)])
├── Forward return computation: close[t+N] / close[t] - 1 from intelligence_features OHLCV columns
├── Signal extraction: plugin output field > threshold (e.g., field == 1.0 for binary patterns)
├── Statistics:
│   ├── N (qualifying bars)
│   ├── ADF: statsmodels.tsa.stattools.adfuller → informational
│   ├── Pearson r + p-value: scipy.stats.pearsonr(signal_direction_series, forward_returns)
│   ├── Signal frequency: count / total bars
│   └── False-positive rate: count(signal=1, fwd_return < 0) / count(signal=1)
├── Gate evaluation: r > 0 AND p < 0.05 AND N >= 30
├── Report: docs/validation/YYYY-MM-DD-<plugin>.json (always written)
└── --promote (if gates pass):
    ├── Patch register_plugins.py: add import + tier list entry
    ├── For candlestick patterns: also patch candlestick_pattern_setup.py named reads
    └── Exit 0; print: "Service restart required"
```

### Recommended Project Structure

New files:
```
production/scripts/
└── validate_alpha.py              # ALPHA-01 — new script

src/intelligence/indicators/
└── ac_oscillator.py               # ALPHA-05 — new I1 plugin

src/intelligence/composites/
└── derivative_oscillator.py       # ALPHA-02 — new I2 plugin

src/intelligence/patterns/
└── candlestick_patterns.py        # ALPHA-03 — extend in-place (no new file)

src/intelligence/composites/
└── macd_events.py                 # ALPHA-04 — extend in-place (no new file)

docs/validation/                   # New directory — audit trail
└── YYYY-MM-DD-<plugin>.json       # Generated by --promote runs

tests/unit/scripts/
└── test_validate_alpha.py         # ALPHA-01 unit tests

tests/unit/intelligence/
└── test_ac_oscillator.py          # ALPHA-05 unit tests

tests/unit/intelligence/composites/
└── test_derivative_oscillator.py  # ALPHA-02 unit tests

tests/unit/intelligence/
└── test_macd_accel.py             # ALPHA-04 unit tests (add to existing MACDEvents test file)

tests/unit/intelligence/
└── test_candlestick_tier1.py      # ALPHA-03 unit tests
```

### Anti-Patterns to Avoid

- **Re-detecting raw OHLCV in I2 plugins:** DerivOsc must read `rsi_14` from features dict, NOT recompute RSI. I2 tier depends on I1 outputs.
- **Promoting before validating:** The `--promote` flag must hard-block if gates fail. Never patch `register_plugins.py` manually for new indicators in this phase.
- **Non-frozenset outputs:** Use `frozenset[str]` for `outputs` and `capability_tags`. `MACDEventsPlugin` currently uses `set` via `default_factory` — when extending, convert to `frozenset` to match the plugin protocol (or keep consistent with existing pattern — see Don't Hand-Roll section).
- **validate_tier() misses:** Any plugin added to a TIER_* list but not registered via `registry.register_indicator/register_pattern` causes a hard crash at startup. Always add both the import and the registration call AND the tier list entry.
- **Patching register_plugins.py incorrectly:** The `--promote` auto-patch must insert the import at the top (with existing imports), call `registry.register_*()` in `register_all_plugins()`, and add to the correct TIER_* list. AST-based patching or targeted string insertion is safer than line-number insertion.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Pearson correlation + p-value | Manual t-statistic formula | `scipy.stats.pearsonr(x, y)` → returns `(r, p_value)` directly | One-liner, handles edge cases (zero variance, NaN propagation) |
| ADF stationarity | Custom unit root test | `statsmodels.tsa.stattools.adfuller(series)` | Standard implementation, returns test stat, p-value, critical values |
| EMA computation | Manual alpha-update loop | `pandas.Series.ewm(span=N, adjust=False).mean()` for warmup; `alpha * x + (1-alpha) * prev` for incremental | Pandas EWM is correct and tested; manual loop matches it exactly |
| Rolling SMA | Manual sum/window | `pandas.Series.rolling(N).mean()` | Standard, handles NaN automatically |
| JSON report writing | Custom serialization | `json.dumps(report, indent=2, default=str)` | `default=str` handles datetime and numpy floats cleanly |
| Forward return series | Complex lag indexing | `df["close"].pct_change(periods=N).shift(-N)` (align returns with signal bar) | Shift-based alignment is the correct pandas pattern; manual indexing is error-prone |

**Key insight:** The statistical machinery for this phase is shallow — two scipy/statsmodels calls. The complexity is in the data pipeline (sufficiency check → auto-backfill → query → align returns), not the statistics.

---

## Common Pitfalls

### Pitfall 1: Signal Alignment for Forward Returns
**What goes wrong:** Forward return at time t must be the N-bar return STARTING at t, not ending at t. A naive `pct_change(N)` gives the return of the PAST N bars.
**Why it happens:** `pct_change(N)` computes `close[t]/close[t-N] - 1`. For forward returns, we need `close[t+N]/close[t] - 1`.
**How to avoid:** Use `df["close"].pct_change(N).shift(-N)` — this shifts the past-N-bar return backward so it aligns with the bar where the signal fired.
**Warning signs:** Correlation appears negative when it should be positive, or FPR is oddly high.

### Pitfall 2: Promote Patches `register_plugins.py` Incorrectly
**What goes wrong:** String-based patching of `register_plugins.py` inserts at wrong line, breaks syntax, or causes duplicate registration.
**Why it happens:** `register_plugins.py` has specific import section, registration calls inside `register_all_plugins()`, and tier list constants — three separate insertion points.
**How to avoid:** Use targeted regex or sentinel comment markers. Test the patch by importing the module after patching in a subprocess. If import fails, restore from backup.
**Warning signs:** `validate_tier()` raises ValueError on startup after promotion.

### Pitfall 3: DerivOsc EMA Warmup Returns Empty Too Long
**What goes wrong:** `_state["sma9_buffer"]` never fills because early bars return `{}` without updating state.
**Why it happens:** Guard `if not is_num(rsi): return {}` correctly skips invalid RSI, but the EMA state must still be seeded on the first valid RSI bar even if the SMA9 isn't ready yet.
**How to avoid:** Separate the EMA update (always run when RSI is valid) from the output gate (only emit when SMA9 buffer has 9 entries).
**Warning signs:** Plugin never emits values even with 100+ bars of RSI history.

### Pitfall 4: Three-Bar Patterns with min_lookback=2
**What goes wrong:** Adding three-bar patterns to `CandlestickPatternsPlugin` but forgetting to raise `min_lookback` from 2 to 3 causes `df.iloc[-3]` to raise IndexError on the very first bars.
**Why it happens:** `compute_full` guard checks `len(df) < self.min_lookback` — with `min_lookback=2`, a 2-bar df passes the guard but has no `iloc[-3]`.
**How to avoid:** Raise `min_lookback=3` as the first change before adding any three-bar pattern logic.
**Warning signs:** `IndexError: single positional indexer is out-of-bounds` in pattern tests.

### Pitfall 5: MACDEventsPlugin `outputs` is a `set` not `frozenset`
**What goes wrong:** `macd_events.py` uses `default_factory=lambda: frozenset({...})` for `outputs` — this is correctly a frozenset. However the `capability_tags` uses the same pattern. When adding `macd_hist_accel` and `macd_hist_contracting`, both the frozenset literal AND the field's default_factory must be updated.
**Why it happens:** The `outputs` field in `MACDEventsPlugin` is declared as `set[str]` in the type annotation but initialized to a `frozenset` — updating one without the other causes a type inconsistency.
**How to avoid:** Update both the type annotation and the `default_factory` when adding new outputs.

### Pitfall 6: Candlestick I7 Reads New Patterns Before Validation
**What goes wrong:** New pattern flags appear in `intelligence_features` immediately after replay, and `CandlestickPatternSetupPlugin` reads from features dict — if the new field names accidentally match something the I7 plugin reads generically, unvalidated patterns could influence signals.
**Why it happens:** The existing I7 plugin uses explicit named reads (`features.get("engulfing_bull", 0.0)`) — new pattern field names (e.g., `three_white_soldiers`) will NOT be read unless explicitly added.
**How to avoid:** Verify that `CandlestickPatternSetupPlugin.compute_full` has no wildcard dict iteration that would pick up new fields. It does not — all reads are explicit `features.get(...)` calls.
**Warning signs:** Would appear as unexplained signal activity for new patterns before promotion.

### Pitfall 7: N < 30 Path Not Tested
**What goes wrong:** The auto-backfill path in `validate_alpha.py` (triggered when fewer than 30 qualifying bars exist) is never exercised in CI because tests use mocked DB data.
**Why it happens:** Unit tests mock the DB query to return sufficient N; the subprocess invocation of `historical_backfill.py` is never triggered.
**How to avoid:** Add a dedicated unit test that mocks the row count query to return N=10 and asserts `subprocess.run` was called with `--replay-only`. Use `unittest.mock.patch`.

---

## Code Examples

Verified patterns from existing source:

### ADF Test (informational)
```python
# Source: statsmodels docs, confirmed available in .venv
from statsmodels.tsa.stattools import adfuller
result = adfuller(series.dropna(), autolag="AIC")
adf_stat, adf_pvalue = result[0], result[1]
# adf_pvalue < 0.05 → stationary; informational only in this phase
```

### Pearson Correlation Gate
```python
# Source: scipy.stats.pearsonr signature
from scipy.stats import pearsonr
r, p_value = pearsonr(signal_direction_series, forward_return_series)
passes = (r > 0) and (p_value < 0.05) and (len(signal_direction_series) >= 30)
```

### Forward Return Computation
```python
# Source: pandas shift pattern — validated alignment logic
# signal_col: 1.0 when indicator fired, 0.0 otherwise (or directional: +1/-1)
# N_bars: TF-appropriate look-ahead (5 for 1m, 3 for 5m/15m/1h)
fwd_return = df["close"].pct_change(N_bars).shift(-N_bars)
# Align: fwd_return.iloc[t] = (close[t+N] - close[t]) / close[t]
valid_mask = df[signal_col].notna() & fwd_return.notna() & (df[signal_col] != 0)
signal_series = df.loc[valid_mask, signal_col]
return_series = fwd_return.loc[valid_mask]
```

### DB Query for Intelligence Features
```python
# Source: matches historical_backfill.py psycopg2 pattern
import psycopg2
from src.config.settings import Settings
settings = Settings()
conn = psycopg2.connect(settings.database_url)
cur = conn.cursor()
cur.execute("""
    SELECT symbol, timeframe, feature_ts, close, i1
    FROM intelligence_features
    WHERE feature_ts >= NOW() - INTERVAL '%s days'
    AND i1 ? %s
    ORDER BY symbol, timeframe, feature_ts
""", (days, plugin_field_name))
rows = cur.fetchall()
```

### Register Plugin (canonical pattern)
```python
# Source: src/intelligence/register_plugins.py — three insertion points for --promote:
# 1. Import at top of file:
from .indicators.ac_oscillator import plugin as ac_osc_plugin
# 2. In register_all_plugins():
registry.register_indicator(ac_osc_plugin)
# 3. In TIER_I1 list:
TIER_I1: list[str] = [..., ac_osc_plugin.name]
```

### Crossover Detection (reuse from common.py)
```python
# Source: src/intelligence/composites/common.py
from .common import crossover_detect, is_num
cross_bull, cross_bear = crossover_detect(prev_ema3, ema3, prev_signal, signal_line)
out["deriv_osc_cross_bullish"] = cross_bull
out["deriv_osc_cross_bearish"] = cross_bear
```

### Validation Report JSON Structure (Claude's Discretion)
```json
{
  "plugin": "ind_ACOscillator",
  "field": "ac",
  "run_at": "2026-03-08T14:23:00Z",
  "days": 90,
  "symbols": ["ESH6", "NQH6"],
  "n_signal_bars": 142,
  "n_total_bars": 8640,
  "signal_frequency": 0.0164,
  "adf_stat": -4.21,
  "adf_pvalue": 0.0008,
  "adf_stationary": true,
  "pearson_r": 0.18,
  "pearson_pvalue": 0.032,
  "false_positive_rate": 0.44,
  "gates": {
    "n_min_30": true,
    "pearson_r_positive": true,
    "pearson_p_lt_05": true
  },
  "verdict": "PASS",
  "promoted": false
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual promotion (edit files, restart) | `--promote` flag auto-patches `register_plugins.py` | Phase 15 | Removes error-prone manual file hunting; retains human decision checkpoint |
| No gate on new indicators | Statistical validation before live promotion | Phase 15 | Renaissance discipline: "earn the right through proof" |
| `pnl_r` as correlation target | Forward close-to-close returns from OHLCV | Phase 15 | Works immediately on replay data; independent of I7 signal entry/exit rules |
| ADF gating (common in quant literature) | ADF informational only | Phase 15 decision | Avoids penalizing valid momentum signals for non-stationarity |

**Deprecated/outdated:**
- Manual editing of `register_plugins.py` for new plugins: valid for development, not for validated promotion from Phase 15 onward.

---

## Open Questions

1. **DerivOsc warmup period for SMA9 buffer**
   - What we know: EMA5→EMA3 chain needs ~8-10 bars of RSI history before both EMAs stabilize; SMA9 of EMA3 needs 9 more bars.
   - What's unclear: Should `min_lookback` reflect this full warmup (~18 bars) or remain at 1 (since features dict is already computed)?
   - Recommendation: Set `min_lookback=1` (the features dict has RSI already; the plugin returns `{}` until its own EMA state is warm). Document the ~18-bar warmup in the class docstring.

2. **`--promote` patch strategy for `register_plugins.py`**
   - What we know: Three insertion points (import, registration call, tier list). String-based patching is fragile if formatting changes.
   - What's unclear: Whether regex with sentinel comments or AST manipulation is safer for a one-off script.
   - Recommendation: Use regex with unique anchor strings (e.g., `# I1: end` comments added as sentinels, or match on the last entry of each TIER_* list). Keep backup of original file before patching; restore on failure.

3. **`intelligence_features` JSONB field for I1 outputs**
   - What we know: `intelligence_features` stores I1 outputs in JSONB `i1` column (per Phase 13). New plugins (AC Oscillator, DerivOsc) must produce values that the feature_writer includes in that JSONB.
   - What's unclear: Whether the feature_writer automatically picks up new plugin outputs or requires explicit configuration.
   - Recommendation: Check `feature_writer_service.py` to confirm all I1 outputs are captured in the `i1` JSONB blob without per-field whitelisting. If it serializes the full features dict, new outputs are captured automatically after registration.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (`.venv/bin/pytest`) |
| Config file | `pytest.ini` or inline markers |
| Quick run command | `.venv/bin/pytest tests/unit/scripts/test_validate_alpha.py tests/unit/intelligence/test_ac_oscillator.py tests/unit/intelligence/composites/test_derivative_oscillator.py tests/unit/intelligence/test_candlestick_tier1.py -v -x` |
| Full suite command | `.venv/bin/pytest tests/unit/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ALPHA-01 | validate_alpha.py produces ADF + Pearson stats from DB rows | unit (mock DB) | `.venv/bin/pytest tests/unit/scripts/test_validate_alpha.py -x` | ❌ Wave 0 |
| ALPHA-01 | Hard gate: exits non-zero when r <= 0 or p >= 0.05 or N < 30 | unit | `.venv/bin/pytest tests/unit/scripts/test_validate_alpha.py::test_gate_fails_low_n -x` | ❌ Wave 0 |
| ALPHA-01 | `--promote` patches register_plugins.py only on gate pass | unit (mock subprocess) | `.venv/bin/pytest tests/unit/scripts/test_validate_alpha.py::test_promote_blocked_on_fail -x` | ❌ Wave 0 |
| ALPHA-01 | Auto-backfill triggered when N < 30 qualifying bars | unit (mock subprocess) | `.venv/bin/pytest tests/unit/scripts/test_validate_alpha.py::test_auto_backfill_triggered -x` | ❌ Wave 0 |
| ALPHA-01 | Validation report JSON written to `docs/validation/` | unit | `.venv/bin/pytest tests/unit/scripts/test_validate_alpha.py::test_report_written -x` | ❌ Wave 0 |
| ALPHA-01 | Forward return alignment: signal at t correlates with return[t+N], not [t-N] | unit | `.venv/bin/pytest tests/unit/scripts/test_validate_alpha.py::test_forward_return_alignment -x` | ❌ Wave 0 |
| ALPHA-02 | DerivOsc outputs `deriv_osc`, `deriv_osc_signal` on every bar after warmup | unit | `.venv/bin/pytest tests/unit/intelligence/composites/test_derivative_oscillator.py::test_outputs_present -x` | ❌ Wave 0 |
| ALPHA-02 | DerivOsc returns `{}` when `rsi_14` missing from features | unit | `.venv/bin/pytest tests/unit/intelligence/composites/test_derivative_oscillator.py::test_missing_rsi -x` | ❌ Wave 0 |
| ALPHA-02 | `deriv_osc_cross_bullish=1` when DerivOsc crosses above signal line | unit | `.venv/bin/pytest tests/unit/intelligence/composites/test_derivative_oscillator.py::test_bullish_cross -x` | ❌ Wave 0 |
| ALPHA-02 | Plugin registered in TIER_I2 (post-promote) | unit | `.venv/bin/pytest tests/unit/intelligence/test_i2_registration.py -x` | ✅ (extend) |
| ALPHA-03 | Three White Soldiers detected on canonical 3-bar setup | unit | `.venv/bin/pytest tests/unit/intelligence/test_candlestick_tier1.py::test_three_white_soldiers -x` | ❌ Wave 0 |
| ALPHA-03 | Three Black Crows detected on canonical 3-bar setup | unit | `.venv/bin/pytest tests/unit/intelligence/test_candlestick_tier1.py::test_three_black_crows -x` | ❌ Wave 0 |
| ALPHA-03 | Morning Star / Evening Star detection | unit | `.venv/bin/pytest tests/unit/intelligence/test_candlestick_tier1.py::test_morning_star -x` | ❌ Wave 0 |
| ALPHA-03 | Three Inside Up / Down detection | unit | `.venv/bin/pytest tests/unit/intelligence/test_candlestick_tier1.py::test_three_inside_up -x` | ❌ Wave 0 |
| ALPHA-03 | Harami Cross, Dark Cloud Cover, Piercing Line detection | unit | `.venv/bin/pytest tests/unit/intelligence/test_candlestick_tier1.py::test_harami_cross -x` | ❌ Wave 0 |
| ALPHA-03 | min_lookback=3 guard prevents IndexError on 2-bar DataFrame | unit | `.venv/bin/pytest tests/unit/intelligence/test_candlestick_tier1.py::test_min_lookback_guard -x` | ❌ Wave 0 |
| ALPHA-03 | New pattern fields NOT read by I7 CandlestickPatternSetupPlugin before promotion | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_candlestick_pattern_setup.py::test_no_new_pattern_reads -x` | ✅ (extend) |
| ALPHA-04 | `macd_hist_accel` = hist - prev_hist (float) | unit | `.venv/bin/pytest tests/unit/intelligence/test_i2_plugins.py::TestMACDEvents -x` | ✅ (extend) |
| ALPHA-04 | `macd_hist_contracting=1` when abs(hist) < abs(prev_hist) | unit | `.venv/bin/pytest tests/unit/intelligence/test_i2_plugins.py::TestMACDEvents::test_hist_contracting -x` | ✅ (extend) |
| ALPHA-04 | Both new fields in MACDEventsPlugin.outputs frozenset | unit | `.venv/bin/pytest tests/unit/intelligence/test_i2_schema.py -x` | ✅ (extend) |
| ALPHA-05 | AC Oscillator outputs `ao` and `ac` floats on sufficient bars | unit | `.venv/bin/pytest tests/unit/intelligence/test_ac_oscillator.py::test_outputs_present -x` | ❌ Wave 0 |
| ALPHA-05 | `ao` = SMA5(midpoint) - SMA34(midpoint); `ac` = AO - SMA5(AO) | unit | `.venv/bin/pytest tests/unit/intelligence/test_ac_oscillator.py::test_formula_correctness -x` | ❌ Wave 0 |
| ALPHA-05 | Returns `{}` when fewer than 40 bars | unit | `.venv/bin/pytest tests/unit/intelligence/test_ac_oscillator.py::test_insufficient_bars -x` | ❌ Wave 0 |
| ALPHA-05 | Plugin registered in TIER_I1 (post-promote) | unit | `.venv/bin/pytest tests/unit/intelligence/test_plugin_registry.py -x` | ✅ (extend) |

### Sampling Rate
- **Per task commit:** Quick run command covering that task's test file
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/unit/scripts/test_validate_alpha.py` — covers ALPHA-01 (gate logic, report writing, forward return alignment, auto-backfill trigger, promote block)
- [ ] `tests/unit/intelligence/composites/test_derivative_oscillator.py` — covers ALPHA-02 (outputs, missing RSI guard, crossover detection, EMA warmup)
- [ ] `tests/unit/intelligence/test_candlestick_tier1.py` — covers ALPHA-03 (all 10 patterns, min_lookback guard, no-pattern baseline)
- [ ] `tests/unit/intelligence/test_ac_oscillator.py` — covers ALPHA-05 (formula correctness, insufficient bars guard, output types)
- [ ] `docs/validation/` directory — must exist before first `--promote` run; create in Wave 0 (Plan 1)

Existing test files requiring extension (not new files):
- `tests/unit/intelligence/test_i2_plugins.py` — add TestMACDEvents tests for `macd_hist_accel` and `macd_hist_contracting`
- `tests/unit/intelligence/test_i2_schema.py` — verify new fields in outputs frozenset
- `tests/unit/intelligence/trading/test_candlestick_pattern_setup.py` — verify no unintended new pattern reads
- `tests/unit/intelligence/test_i2_registration.py` — after DerivOsc promote, verify TIER_I2 membership

---

## Sources

### Primary (HIGH confidence)
- Direct code inspection: `src/intelligence/patterns/candlestick_patterns.py` — current 9-output structure, min_lookback=2
- Direct code inspection: `src/intelligence/composites/macd_events.py` — I2 composite pattern, prev_features pattern, frozenset outputs
- Direct code inspection: `src/intelligence/trading/candlestick_pattern_setup.py` — explicit named-read whitelist mechanism confirmed
- Direct code inspection: `src/intelligence/register_plugins.py` — TIER_* list structure, three-point insertion pattern
- Direct code inspection: `src/intelligence/composites/common.py` — `crossover_detect`, `is_num`, `track_bars_ago` utilities
- Direct code inspection: `production/scripts/historical_backfill.py` — CLI argparse pattern, psycopg2 usage
- Direct code inspection: `tests/unit/intelligence/helpers.py` — `make_ohlcv` test helper pattern

### Secondary (MEDIUM confidence)
- Bill Williams AC Oscillator definition: AO = SMA(5, midpoint) - SMA(34, midpoint); AC = AO - SMA(5, AO) — well-documented, consistent across sources
- Constance Brown Derivative Oscillator: EMA5(EMA3(RSI)) minus SMA9 signal line — established formula in Brown's "Technical Analysis for the Trading Professional"
- Three-bar candlestick pattern definitions (Three White Soldiers, Morning Star, etc.) — standard definitions consistent across multiple technical analysis references

### Tertiary (LOW confidence — flag for validation)
- Confidence scores (0.72, 0.65, 0.58, 0.55) for candlestick patterns from REQUIREMENTS.md — sourced from prior design decisions, not independently verified against backtests on this data

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries confirmed present in .venv via import usage in existing scripts
- Architecture: HIGH — all patterns verified by direct code inspection of existing plugins and tests
- Pitfalls: HIGH — derived from actual code structure and known codebase gotchas (documented in CLAUDE.md and MEMORY.md)
- Validation gate logic: HIGH — Pearson + p-value + N≥30 are locked decisions from CONTEXT.md

**Research date:** 2026-03-08
**Valid until:** 2026-04-08 (stable codebase, no external dependencies changing)
