# Phase 29: Renaissance Signal Quality - Research

**Researched:** 2026-03-12
**Domain:** Signal quality gates, CIS enhancement, I4 plugin development, drift detection service
**Confidence:** HIGH — entire domain is internal codebase. No external library gaps. Design docs are exhaustive.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Design Philosophy (applies to all decisions below):**
- Information preservation: soft gates over hard gates, continuous functions over step functions
- Instrument everything: capture data that cannot be reconstructed after scoring functions evolve
- Automate the feedback loop: detection without automated response is expensive logging

**T0: constituent_contributions — full audit trail, per-feature granularity**
- Per-feature contributions within each CIS bucket (not just per-setup totals)
- Each bucket method returns `(score, {feature: contribution})` instead of just `score`
- Lives in `intelligence_features.i7` via existing feature bus write path — NOT in `signal_ledger`
- Refactor all 6 `CISScorer._bucket()` methods to return `(float, dict[str, float])`

**T1-A/C: Alpha decay — soft multiplier, per-setup state**
- Soft confidence multiplier only, no hard cooldown
- `multiplier = 1.0 - (bars_since_last_fire / alpha_half_life)`; `confidence *= max(0.0, multiplier)`
- State: `_setup_last_fire: dict[tuple[str, str, str, int], dict]` keyed by `(symbol, tf, setup_plugin, direction)`
- Per-TF constants: `ALPHA_HALF_LIFE_BARS = {"1m": 10, "5m": 6, "15m": 4, "1h": 3}` (hardcoded, tune after 90d data)

**T1-B: Signal freshness decay — exponential, in lifecycle service**
- `freshness = exp(-λ * bars_since_fire)` where `λ = ln(2) / half_life_bars`
- Applied in `signal_lifecycle_service` per-bar; in-memory only, not written back to `signal_ledger`

**T1-D/E: rel_volume + killzone — CIS momentum/regime bucket wire-ins**
- `rel_volume > 1.5` → confidence boost in `_momentum()`, `rel_volume < 0.5` → suppress
- Active killzone open → regime bucket boost in `_regime()`, dead session → reduce
- Additive sub-terms within existing bucket methods, zero structural change to CIS

**T2: Hurst + Shannon — quality multipliers in `_build_all_ranked()`, not CIS buckets**
- Applied per-signal after CIS scoring in `_build_all_ranked()`
- `setup_class = "trend" if sig["plugin"] in TREND_SETUPS else "mean_reversion"`
- `sig["confidence"] *= hurst_q * entropy_q`
- `HurstExponentPlugin` (I4) outputs: `hurst_exponent`, `hurst_trend_quality`, `hurst_mr_quality`
- `ShannonEntropyPlugin` (I4) outputs: `shannon_entropy`, `entropy_quality`

**T3: Drift detection — automated feedback loops**
- Standalone `drift_monitor_service` (port `:9118`, `Restart=always`)
- Two internal asyncio tasks: `KSDriftMonitor.run_forever()` (4h) + `CUSUMMonitor.run_forever()` (1h)
- KS → Redis `drift:ks:{symbol}:{tf}` → CIS confidence modifier: warning=0.85, critical=0.70
- Recovery: gradual (50% reduction per clean cycle, full restoration after 2 consecutive clean checks)
- CUSUM → `perf_multiplier` via extending `weight_updater.py` (not drift service directly)
- `drift_monitor` hypertable (migration 026); `GET /api/drift` endpoint
- CUSUM multiplicative: `new_multiplier = current_multiplier * cusum_adjustment_factor`; floor=0.30

### Claude's Discretion
- Rolling window sizes for Hurst (64 vs 128 vs 256 bars)
- Shannon entropy normalization method
- Exact `hurst_trend_quality` / `hurst_mr_quality` mapping functions (linear vs sigmoid)
- `TREND_SETUPS` constant membership (which I7 plugins are "trend" vs "mean-reversion")
- CUSUM threshold starting values (μ₀, σ₀, detection threshold k)
- `drift_monitor` table schema details (schema is specified in design doc — discretion is minor tweaks only)

### Deferred Ideas (OUT OF SCOPE)
- Regime suppression virtual outcomes (Gap 4)
- A/B testing protocol (Gap 5)
- Momentum Exhaustion Entry (T2-C)
- Config/DB-driven `alpha_half_life`
- Graduated KS penalty (penalty scales with KS statistic magnitude)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| QUAL-01 | `cis_scorer.py` populates `constituent_contributions` JSONB with per-setup scores for each bucket — no longer always empty | CIS scorer analysis: `score()` method initializes to `{}` at line 162 with placeholder comment "populated in Task 13". All 6 bucket methods return `float` today — need `(float, dict)` refactor |
| QUAL-02 | Alpha decay multiplier applied in aggregator: repeated same-direction signals from the same setup within `alpha_half_life` bars are down-weighted | New `_setup_last_fire` dict in `signal_generator_service`; applied in `_build_all_ranked()` or just before publishing |
| QUAL-03 | Signal freshness exponential decay applied in `signal_lifecycle_service`: active signal confidence decays as `exp(-λ × bars_since_fire)` | `signal_lifecycle_service` already has `_bars_elapsed()` helper; freshness decay wraps around per-bar evaluation loop |
| QUAL-04 | Per-setup cooldown window prevents the same setup firing in the same direction within `_SIGNAL_COOLDOWN_BARS` (3 bars for 1m, 2 bars for 5m+) | `MIN_BARS_BETWEEN_SIGNALS` pattern already exists at service level; QUAL-04 is per-setup/direction cooldown on top of existing per-signal-condition gate |
| QUAL-05 | `rel_volume` (already in I1) wired into CIS momentum bucket: boost when `rel_volume > 1.5`, suppress when `< 0.5` | `rel_volume` exists in I1 schema; `_momentum()` bucket already reads RSI/MACD/ROC — add `rel_volume` sub-term |
| QUAL-06 | Killzone context wired as CIS time-of-day gate: confidence boosted during killzone opens (London/NY), reduced in dead sessions | `in_london_killzone` + `in_ny_killzone` from `ctx_SessionContext`; `in_london_killzone` + `in_ny_am_killzone` from `smc_ICTKillzones` — both flow through flattened features dict |
| QUAL-07 | `HurstExponentPlugin` (I4) computes rolling Hurst exponent; H > 0.65 suppresses mean-reversion setups; H < 0.45 suppresses trend setups | New I4 plugin following `GARCHVolatilityPlugin` pattern; outputs 3 fields; registered in `TIER_I4`; quality applied in `_build_all_ranked()` |
| QUAL-08 | `ShannonEntropyPlugin` (I4) computes rolling return entropy; high entropy reduces all signal confidence by 30–50% as a universal noise gate | New I4 plugin following same pattern; `entropy_quality` gate applied universally in `_build_all_ranked()` |
| QUAL-09 | KS distribution drift detection — periodic background job comparing current I1/I4 feature distributions to a baseline reference window; emits monitoring flag when KS p-value < 0.05 on key features | New `drift_monitor_service`; KS via `scipy.stats.ks_2samp` (already in venv); Redis drift key; `drift_monitor` hypertable; API endpoint |
| QUAL-10 | CUSUM performance drift detection — detects when per-setup win rates are degrading relative to historical baseline; alerts before losses accumulate | CUSUM monitor in same service; reads `signal_ledger`; extends `weight_updater.py` for auto-response |
</phase_requirements>

---

## Summary

Phase 29 closes 10 signal quality gaps across 4 implementation tiers: T0 (bug fix — populate `constituent_contributions`), T1 (5 wire-ins using existing data — alpha decay, freshness decay, cooldown, vol-gating, killzone-gating), T2 (2 new I4 plugins — Hurst exponent + Shannon entropy), and T3 (drift detection infrastructure — KS + CUSUM monitors with automated pipeline feedback).

All work is internal. No new external dependencies exist except `scipy` for KS tests (already installed — used by GARCH/Kalman). Every integration point has an exact match in the existing codebase: CIS scorer methods, aggregator `_build_all_ranked()`, lifecycle service per-bar loop, and `weight_updater.py`. The design documents are comprehensive — the research task is to identify exact file locations, field names, and gotchas the planner must account for.

**Primary recommendation:** Sequence plans as T0 → T1 (cooldown first, then alpha/freshness, then CIS wire-ins) → T2 (Hurst + Shannon as two separate plans) → T3 (migration, service, integration). Each tier can be tested independently. T3 is the largest chunk and should be its own wave of 2–3 plans.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `scipy.stats` | already installed | KS two-sample test for drift detection | Standard scientific Python; `ks_2samp` is the canonical implementation |
| `numpy` | already installed | Hurst/Shannon numerical computation | All existing plugins use numpy arrays |
| `asyncpg` | already installed | DB queries in drift service | Used by every other service |
| `prometheus_client` | already installed | Drift metrics port :9118 | Consistent with all service metrics |
| `structlog` | already installed | Service logging | Project standard |
| `redis.asyncio` | already installed | KS drift state cache writes | Used by all services |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `sklearn.linear_model.LogisticRegression` | already installed | `weight_updater.py` (pre-existing) | CUSUM response feeds the multiplier this module already writes |
| `math` (stdlib) | stdlib | `math.exp`, `math.log` | Freshness decay lambda |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| scipy KS test | Manual KS implementation | scipy is correct, battle-tested, already in venv |
| Hurst via R/S method | DFA or wavelet-based | R/S analysis is simpler to implement in 64-256 bar windows; DFA needs longer series |
| Per-setup Redis keys for drift | Single DB query per check | Redis key per symbol/TF for KS (one key covers all 8 features — coarser, per design decision) |

**No new package installs required.**

---

## Architecture Patterns

### Recommended Project Structure (new files only)

```
src/
├── intelligence/
│   ├── context/
│   │   ├── hurst_exponent.py         # New I4 plugin (QUAL-07)
│   │   └── shannon_entropy.py        # New I4 plugin (QUAL-08)
│   └── trading/
│       └── cis_scorer.py             # Modify: bucket methods return (float, dict)
├── monitoring/
│   ├── __init__.py                   # New module
│   ├── ks_drift_monitor.py           # KSDriftMonitor class
│   └── cusum_monitor.py              # CUSUMMonitor class
└── api/
    └── routes/
        └── drift.py                  # GET /api/drift endpoint

services/
├── drift_monitor_service.py          # New service entrypoint
└── indicagent-drift-monitor.service  # systemd unit

production/
├── migrations/
│   └── 026_drift_monitor.sql         # drift_monitor hypertable
└── scripts/
    └── reset_cusum.py                # Manual CUSUM reset tool

tests/unit/
├── intelligence/
│   └── context/
│       ├── test_hurst_exponent.py
│       └── test_shannon_entropy.py
└── monitoring/
    ├── __init__.py
    ├── test_ks_drift_monitor.py
    └── test_cusum_monitor.py
```

### Pattern 1: I4 Plugin Structure

New I4 plugins (`HurstExponentPlugin`, `ShannonEntropyPlugin`) follow the `GARCHVolatilityPlugin` pattern exactly.

**What:** Stateful `@dataclass` plugin with `compute_full()`, registered in `register_all_plugins()` and added to `TIER_I4`.

**When to use:** Any new I4 context plugin.

**Example (based on existing GARCHVolatilityPlugin):**
```python
@dataclass
class HurstExponentPlugin:
    name: str = "ctx_HurstExponent"
    outputs: frozenset[str] = frozenset({
        "hurst_exponent", "hurst_trend_quality", "hurst_mr_quality"
    })
    min_lookback: int = 64
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"context", "regime"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=256),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}
        close = df["close"].to_numpy(dtype=float)
        # R/S analysis for Hurst exponent...
```

### Pattern 2: CIS Bucket Method Refactor (QUAL-01)

**What:** Change all 6 bucket methods from returning `float` to returning `(float, dict[str, float])`, then assemble contributions in `score()`.

**Critical detail:** The `score()` method currently has a TODO comment at line 162: `constituent_contributions={b: {} for b in BUCKET_NAMES},  # populated in Task 13`. This is the exact insertion point.

**The 6 methods to refactor:**
- `_trend(f)` — currently reads 5 named features; contributions are the per-feature weighted contributions
- `_momentum(f, po)` — reads RSI, MACD, ROC, momentum_bias, DivergenceStack
- `_structure(f, po)` — reads swing_pattern, bos_detected, choch_detected, CHoCHReversal
- `_pattern(f, po)` — reads dt_db_pattern, hs_pattern, tri_breakout_bias, PatternCompletion
- `_institutional(f, po)` — reads ob_type/strength, fvg_type, zones, FVGFill, SupplyDemandSetup
- `_regime(f, po)` — reads hmm probs, cp_probability, ctf_regime_agreement, vol_regime, RegimeTransition

### Pattern 3: `_build_all_ranked()` Extension (QUAL-02, QUAL-07, QUAL-08)

**What:** Alpha decay + Hurst/Shannon quality multipliers applied in `aggregator._build_all_ranked()` after `adjusted_rank` is assigned.

**Current location:** `src/intelligence/trading/aggregator.py`, function `_build_all_ranked()` (line 351).

**Current flow:**
1. Sort by `SETUP_PRIORITY` descending → assign `composite_rank`
2. Assign `adjusted_rank` from `perf_weights`
3. Sort ascending by `(adjusted_rank, -priority)`

**Extended flow (Phase 29):**
1. Sort by `SETUP_PRIORITY` descending → assign `composite_rank`
2. Apply alpha decay multiplier to `confidence` (reads `_setup_last_fire` state passed in)
3. Apply Hurst/Shannon quality multipliers to `confidence`
4. Assign `adjusted_rank` from `perf_weights`
5. Sort ascending by `(adjusted_rank, -priority)`

**TREND_SETUPS constant** (Claude's discretion — recommend this set based on `regime_type` attributes):
```python
TREND_SETUPS: frozenset[str] = frozenset({
    "trad_TrendFollowing",
    "trad_LiquiditySweepReclaim",
    "trad_MTFAlignment",
    "trad_MomentumBreakout",
    "trad_SqueezeExpansion",
    "trad_LiquidityHunt",
    "trad_RegimeTransition",
    "trad_GapAnalysisSetup",
})
```
Mean-reversion setups: `trad_MeanReversion`, `trad_VWAPDeviation`, `trad_CHoCHReversal`, `trad_FVGFill`, `trad_SupplyDemandSetup`, `trad_DivergenceStack`, `trad_PatternCompletion`, `trad_CandlestickPatternSetup`, `trad_SessionExtremesSetup`.

### Pattern 4: Signal Lifecycle Per-Bar Extension (QUAL-03)

**What:** Freshness decay applied in `signal_lifecycle_service` on each bar evaluation for active signals.

**Integration point:** The lifecycle service evaluates active signals on each 1m bar. Freshness multiplier is computed from `_bars_elapsed()` (already exists in service). Applied in-memory — modifies evaluation copy, not the DB record.

```python
lambda_decay = math.log(2) / FRESHNESS_HALF_LIFE_BARS[timeframe]
bars_since = _bars_elapsed(signal_timestamp, current_bar_time, timeframe)
freshness = math.exp(-lambda_decay * bars_since)
effective_confidence = stored_confidence * freshness
```

### Pattern 5: Drift Monitor Service Structure

**What:** Standalone asyncio service with two long-running tasks, following the established service pattern.

**Port allocation:** `:9118` (next available after feature-writer :9116, llm-writer :9117)

**Prometheus metric registration note (CRITICAL):** Drift metrics use `labelnames=` → cannot use `src/observability/metrics.py` helpers (`metrics.counter()` / `metrics.gauge()` do not accept `labelnames`). Register directly as module-level constants using `prometheus_client.Gauge(...)` and `prometheus_client.Counter(...)` — exactly like `PLUGIN_EXECUTION_TOTAL` in `metrics.py`.

### Anti-Patterns to Avoid

- **Hard cooldown that discards signals:** QUAL-04 is a per-setup cooldown (separate from `MIN_BARS_BETWEEN_SIGNALS` which operates at bar publication level). Hard-filtering means the signal exists but is thrown away — use soft decay (QUAL-02/QUAL-03) instead. QUAL-04 is a separate, lighter cooldown gate for dedup.
- **Writing freshness back to `signal_ledger`:** Freshness decay is in-memory in the lifecycle service. Never write decayed confidence back to DB — the original confidence at fire time is ground truth for ML training.
- **`active` derived from raw `signals`:** Always derive `active = [s for s in all_ranked if s.get("regime_eligible", True)]`. If derived from raw `signals`, `perf_weights` and new alpha/quality multipliers have zero effect on winner selection.
- **Two writers to `setup_performance.perf_multiplier`:** CUSUM response must extend `weight_updater.py` — do not have `drift_monitor_service` write to this column directly. Race conditions.
- **Hardcoded Redis keys for drift state:** Must use `stream_keys.drift_ks(symbol, tf)` — add new key constructor to `src/core/stream_keys.py` following existing pattern.
- **`CREATE INDEX CONCURRENTLY` on hypertable:** Not supported. Omit `CONCURRENTLY` in migration 026.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| KS two-sample test | Manual CDF comparison | `scipy.stats.ks_2samp` | Already in venv; handles edge cases, returns both statistic and p-value |
| Hurst R/S analysis | Custom fractal dimension code | Numpy-based R/S on rolling window | Standard financial time series method; scipy not needed |
| CUSUM accumulator | Home-built sequential test | Simple Python accumulator with the Page's CUSUM formula | CUSUM is simple enough to implement correctly inline — no library needed |
| DB migration execution | `docker exec ... -f /dev/stdin <<'EOF'` heredoc | `docker cp file.sql timescaledb:/tmp/file.sql` then `docker exec timescaledb psql ... -f /tmp/file.sql` | Heredoc via stdin does NOT work on this TimescaleDB container |
| Prometheus labeled metrics | `metrics.gauge()` helper | Direct `prometheus_client.Gauge("name", "desc", ["label1", "label2"])` | `metrics.py` helpers don't accept `labelnames` |

**Key insight:** The heaviest complexity in this phase is architectural (correct wiring, state management) not algorithmic. The math is simple once the integration pattern is clear.

---

## Common Pitfalls

### Pitfall 1: CIS Bucket Signature Change Breaks Score() Accumulation

**What goes wrong:** Changing bucket methods to return `(float, dict)` without updating the `score()` call site breaks the `bucket_scores` dict construction.

**Why it happens:** `score()` currently does `"trend": self._trend(features)` — after refactor this receives a tuple.

**How to avoid:** Update `score()` to unpack: `trend_score, trend_contrib = self._trend(features)`. Then `bucket_scores["trend"] = trend_score` and `contributions["trend"] = trend_contrib`. Tests in `test_cis_scorer.py` catch this immediately — run them after each bucket method refactor.

**Warning signs:** `bucket_scores` values are tuples instead of floats in test output.

### Pitfall 2: Alpha Decay State Not Passed Through Aggregator Boundary

**What goes wrong:** `_setup_last_fire` lives in `signal_generator_service` but `_build_all_ranked()` is in `aggregator.py`. The state must be passed as a parameter or accessed via closure.

**Why it happens:** The aggregator is a standalone function, not a class with state. `_build_all_ranked()` receives `fired` + `perf_weights` — no path for per-setup fire history.

**How to avoid:** Either (a) apply alpha decay to `confidence` in the signal dict before calling `aggregate()` in the service, or (b) add a `setup_last_fire` parameter to `_build_all_ranked()`. Option (a) is cleaner — mutate confidence in the service, pass already-decayed signals to aggregator.

### Pitfall 3: QUAL-04 Cooldown vs Existing `MIN_BARS_BETWEEN_SIGNALS`

**What goes wrong:** Confusing the existing per-symbol/TF onset gate (`_signal_gate`) with the new per-setup/direction cooldown.

**Why it happens:** `_signal_gate[(symbol, tf)]` in `signal_generator_service` prevents the same condition from re-firing on consecutive bars regardless of setup. QUAL-04 is finer-grained: prevent the same setup in the same direction within N bars, but allow other setups to still fire.

**How to avoid:** Add `_setup_cooldown: dict[tuple[str, str, str, int], int]` keyed by `(symbol, tf, setup_plugin, direction)` — value is `bars_until_eligible`. Decrement each bar. Both gates coexist without conflict.

### Pitfall 4: I4 Plugin Registration Order

**What goes wrong:** New Hurst/Shannon plugins added to `register_all_plugins()` but not to `TIER_I4` list — `validate_tier()` hard-crashes at service startup.

**Why it happens:** `register_all_plugins()` and `TIER_I4` are separate lists that must stay in sync.

**How to avoid:** Add to both in the same commit. Test with `registry.validate_tier(TIER_I4)` in a unit test.

### Pitfall 5: KS Query Spans Compressed Chunks

**What goes wrong:** The 37-day KS reference window spans ~5 compressed TimescaleDB chunks. On first deployment with a full history, the query may be slow.

**Why it happens:** TimescaleDB decompresses on-the-fly for SELECT. 23 symbols × 4 TFs × 2 windows = 184 queries hitting compressed data every 4h.

**How to avoid:** Monitor `drift_monitor_check_duration_seconds` Prometheus metric. If a 4h cycle exceeds 20 minutes, add `source = 'live'` filter to skip backfill rows. Design doc notes this explicitly. First deployment: time a single check cycle manually before enabling.

### Pitfall 6: CUSUM Baseline Estimation With Insufficient N

**What goes wrong:** CUSUM starts with N=0 outcomes, baseline μ₀/σ₀ are computed from first 20. If the first 20 outcomes are all winners (common in a favorable regime), baseline is overoptimistic and CUSUM triggers on subsequent normal variance.

**Why it happens:** Baseline is fixed after first 20. If market conditions change after those 20 trades, the "normal" becomes stale.

**How to avoid:** Document that baseline requires manual reset via `reset_cusum.py` after significant market regime changes. This is intentional per design — never auto-reset. The minimum N=20 guard is the primary protection.

### Pitfall 7: Drift Monitor Prometheus Labels — Registration Conflict

**What goes wrong:** Using `metrics.counter()` / `metrics.gauge()` helpers for labeled metrics silently fails or raises `ValueError: Duplicated timeseries`.

**Why it happens:** `src/observability/metrics.py` helpers don't accept `labelnames`. Direct `prometheus_client.Counter("name", "desc", ["label"])` must be module-level constants.

**How to avoid:** Register all drift metrics as module-level constants in `src/monitoring/ks_drift_monitor.py` and `src/monitoring/cusum_monitor.py`. Do not use the `metrics.py` helper functions for any metric that needs labels.

---

## Code Examples

### Hurst Exponent — R/S Analysis

```python
# Hurst exponent via R/S analysis on rolling window
# Source: Standard financial time series method (no external library)
def _hurst_rs(close: np.ndarray, min_window: int = 16) -> float:
    """Compute Hurst exponent via R/S analysis. Returns 0.5 (random walk) on failure."""
    n = len(close)
    if n < min_window:
        return 0.5
    log_returns = np.diff(np.log(close))
    if len(log_returns) < min_window:
        return 0.5
    # Single-window R/S for speed (full multi-scale is overkill for 64-256 bar signals)
    mean_r = np.mean(log_returns)
    deviations = np.cumsum(log_returns - mean_r)
    r = np.max(deviations) - np.min(deviations)
    s = np.std(log_returns, ddof=1)
    if s == 0 or r == 0:
        return 0.5
    rs = r / s
    if rs <= 0:
        return 0.5
    return min(1.0, max(0.0, np.log(rs) / np.log(n)))
```

### Shannon Entropy — Normalized on Return Distribution

```python
# Shannon entropy on discretized return distribution
# Source: Information theory — normalized to [0, 1]
def _shannon_entropy(close: np.ndarray, n_bins: int = 10) -> float:
    """Normalized Shannon entropy of return distribution. Returns 1.0 on failure (max noise)."""
    log_returns = np.diff(np.log(close))
    if len(log_returns) < 10:
        return 1.0
    counts, _ = np.histogram(log_returns, bins=n_bins)
    probs = counts / counts.sum()
    probs = probs[probs > 0]
    if len(probs) == 0:
        return 1.0
    raw_entropy = -np.sum(probs * np.log2(probs))
    max_entropy = np.log2(n_bins)
    return float(raw_entropy / max_entropy) if max_entropy > 0 else 1.0
```

### Hurst Quality Mapping (linear, Claude's discretion)

```python
# Linear mapping: H in [0,1] → quality score in [0,1]
def _hurst_trend_quality(h: float) -> float:
    """Quality for trend setups: high when H > 0.5 (trending market)."""
    # Clamp: below 0.45 = penalize trend (market is mean-reverting)
    # Above 0.65 = full quality; between = linear ramp
    if h >= 0.65:
        return 1.0
    if h <= 0.45:
        return 0.3  # partial, not zero — preserve signal flow
    return 0.3 + 0.7 * ((h - 0.45) / 0.20)

def _hurst_mr_quality(h: float) -> float:
    """Quality for mean-reversion setups: high when H < 0.5."""
    if h <= 0.35:
        return 1.0
    if h >= 0.55:
        return 0.3
    return 0.3 + 0.7 * ((0.55 - h) / 0.20)
```

### Entropy Quality Gate (Claude's discretion)

```python
def _entropy_quality(normalized_entropy: float) -> float:
    """Universal gate: penalize high-entropy (noisy) markets. Returns [0.5, 1.0]."""
    # Below 0.4 = structured market, full quality
    # Above 0.8 = chaotic market, max penalty (50% reduction)
    if normalized_entropy <= 0.4:
        return 1.0
    if normalized_entropy >= 0.8:
        return 0.5
    return 1.0 - 0.5 * ((normalized_entropy - 0.4) / 0.4)
```

### KS Drift State Redis Write

```python
# Source: docs/plans/2026-03-11-signal-drift-detection-design.md
DRIFT_PENALTIES = {"none": 1.0, "warning": 0.85, "critical": 0.70}

# Write after KS cycle:
drift_key = f"{env_prefix}drift:ks:{symbol}:{tf}"
await redis.set(drift_key, severity, ex=8*3600)  # TTL=8h

# Read in _build_all_ranked() / signal_generator:
drift_state = await redis.get(drift_key) or b"none"
penalty = DRIFT_PENALTIES[drift_state.decode()]
sig["confidence"] = round(sig.get("confidence", 0.0) * penalty, 4)
```

### stream_keys.py Addition

```python
def drift_ks(env_prefix: str, symbol: str, tf: str) -> str:
    """Redis key for KS drift state per symbol/TF. Written by drift_monitor_service."""
    return f"{env_prefix}drift:ks:{symbol}:{tf}"
```

### CUSUM Algorithm

```python
# Source: docs/plans/2026-03-11-signal-drift-detection-design.md (Page's CUSUM)
# k=0.5 (allowance), h=4.0 (warning threshold), h_critical=8.0
def _compute_cusum(pnl_r_series: list[float], mu0: float, sigma0: float,
                   k: float = 0.5, h: float = 4.0) -> tuple[float, float, str]:
    """Returns (S_pos, S_neg, severity)."""
    s_pos, s_neg = 0.0, 0.0
    for pnl in pnl_r_series[20:]:  # skip baseline window
        x_n = (pnl - mu0) / max(sigma0, 0.5)
        s_pos = max(0.0, s_pos + x_n - k)
        s_neg = max(0.0, s_neg + (-x_n) - k)
    if s_neg >= 2 * h:
        return s_pos, s_neg, "critical"
    if s_neg >= h:
        return s_pos, s_neg, "warning"
    if s_pos >= h:
        return s_pos, s_neg, "info"
    return s_pos, s_neg, "none"
```

### Migration 026 Skeleton

```sql
-- Source: docs/plans/2026-03-11-signal-drift-detection-design.md
CREATE TABLE IF NOT EXISTS drift_monitor (
    id              BIGSERIAL       PRIMARY KEY,
    check_type      TEXT            NOT NULL,
    symbol          TEXT            NOT NULL,
    timeframe       TEXT,
    setup_plugin    TEXT,
    feature_name    TEXT,
    checked_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    ks_statistic    FLOAT,
    ks_pvalue       FLOAT,
    reference_n     INTEGER,
    current_n       INTEGER,
    cusum_pos       FLOAT,
    cusum_neg       FLOAT,
    cusum_threshold FLOAT,
    baseline_mean   FLOAT,
    baseline_std    FLOAT,
    total_outcomes  INTEGER,
    alert_triggered BOOLEAN         NOT NULL DEFAULT FALSE,
    alert_severity  TEXT,
    alert_message   TEXT
);
SELECT create_hypertable('drift_monitor', 'checked_at',
    chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE);
-- No CONCURRENTLY on hypertable indexes
CREATE INDEX IF NOT EXISTS idx_drift_monitor_sym_type
    ON drift_monitor (symbol, check_type, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_drift_monitor_alerts
    ON drift_monitor (alert_triggered, checked_at DESC)
    WHERE alert_triggered = TRUE;
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `constituent_contributions` always `{}` | Per-feature breakdown populated | Phase 29 T0 | Enables counterfactual analysis |
| No alpha decay | Per-setup `_setup_last_fire` decay | Phase 29 T1-A | Repeated setups compete at reduced confidence |
| Signal confidence static after fire | Exponential freshness decay | Phase 29 T1-B | Stale active signals auto-demote |
| No per-setup cooldown | `_setup_cooldown` dict gate | Phase 29 T1-C (QUAL-04) | Same setup can't recycle within N bars |
| `rel_volume` display-only | CIS momentum bucket sub-term | Phase 29 T1-D | Volume confirmation wired into scoring |
| Killzone context display-only | CIS regime bucket sub-term | Phase 29 T1-E | Session timing wired into scoring |
| 7 I4 plugins | 9 I4 plugins (Hurst + Shannon) | Phase 29 T2 | Market quality gates on signal confidence |
| No drift detection | KS + CUSUM with auto-response | Phase 29 T3 | Self-correcting pipeline |

**Deprecated/outdated:**
- `constituent_contributions={b: {} for b in BUCKET_NAMES}` placeholder comment "populated in Task 13" — this IS Task 13 (in planner terms, QUAL-01's task)

---

## Open Questions

1. **Hurst rolling window — 64 vs 128 vs 256 bars**
   - What we know: design doc says 64-256; GARCH uses 200; min_lookback=30 for GARCH
   - What's unclear: which window gives the most stable Hurst estimates for 1m bars in ES/NQ futures
   - Recommendation: use 64-bar window as primary (min_lookback=64), with 256 as full lookback in `InputSpec`. Run compute on last 64 bars regardless. This matches the 50-bar warmup the signal_generator already requires.

2. **Freshness decay half-life per TF**
   - What we know: CONTEXT.md specifies the formula but not the half-life values
   - What's unclear: how many bars until a signal is considered "stale" for each TF
   - Recommendation: use `{"1m": 20, "5m": 10, "15m": 6, "1h": 4}` — signal is 50% decayed after those bars. Comment in code: "Tune after 90 days outcome data."

3. **QUAL-04 cooldown interaction with QUAL-02 alpha decay**
   - What we know: both are per-setup/direction state; QUAL-04 is a hard gate (don't fire), QUAL-02 is soft (fire with reduced confidence)
   - What's unclear: do they interfere?
   - Recommendation: QUAL-04 runs first (skip signal insertion entirely if within cooldown). QUAL-02 runs on surviving signals. Independent, no conflict.

4. **Weight_updater CUSUM integration — when does it run?**
   - What we know: `weight_updater.py` runs via `run_setup_performance_update()` — need to check invocation schedule
   - What's unclear: is this a daily cron, or triggered by signal_generator on a timer?
   - Recommendation: planner should check `services/signal_generator_service.py` for the timer pattern and follow the same pattern for CUSUM-extended weight updater.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (`.venv/bin/pytest`) |
| Config file | `pytest.ini` or `pyproject.toml` — standard discovery |
| Quick run command | `.venv/bin/pytest tests/unit/intelligence/ tests/unit/monitoring/ -x -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| QUAL-01 | `constituent_contributions` populated with per-feature breakdown | unit | `.venv/bin/pytest tests/unit/intelligence/test_cis_scorer.py -x` | ✅ exists — extend |
| QUAL-02 | Alpha decay reduces confidence for repeated same-direction signals | unit | `.venv/bin/pytest tests/unit/intelligence/test_aggregator.py -x` | ✅ exists — extend |
| QUAL-03 | Freshness decay applies to active signal confidence | unit | `.venv/bin/pytest tests/unit/service_tests/ -x -k lifecycle` | ❌ Wave 0 gap |
| QUAL-04 | Cooldown prevents same setup/direction within N bars | unit | `.venv/bin/pytest tests/unit/intelligence/test_aggregator.py -x` | ✅ exists — extend |
| QUAL-05 | rel_volume wired into CIS momentum bucket | unit | `.venv/bin/pytest tests/unit/intelligence/test_cis_scorer.py -x` | ✅ exists — extend |
| QUAL-06 | Killzone wired into CIS regime bucket | unit | `.venv/bin/pytest tests/unit/intelligence/test_cis_scorer.py -x` | ✅ exists — extend |
| QUAL-07 | HurstExponentPlugin outputs correct fields + quality scores | unit | `.venv/bin/pytest tests/unit/intelligence/context/test_hurst_exponent.py -x` | ❌ Wave 0 gap |
| QUAL-08 | ShannonEntropyPlugin outputs correct fields + quality scores | unit | `.venv/bin/pytest tests/unit/intelligence/context/test_shannon_entropy.py -x` | ❌ Wave 0 gap |
| QUAL-09 | KS monitor: alert fires at p<0.05 on shifted distribution, Redis key written | unit | `.venv/bin/pytest tests/unit/monitoring/test_ks_drift_monitor.py -x` | ❌ Wave 0 gap |
| QUAL-10 | CUSUM monitor: warning fires on degraded pnl_r series; weight_updater applies adjustment | unit | `.venv/bin/pytest tests/unit/monitoring/test_cusum_monitor.py -x` | ❌ Wave 0 gap |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/intelligence/ -x -q`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/unit/intelligence/context/test_hurst_exponent.py` — covers QUAL-07
- [ ] `tests/unit/intelligence/context/test_shannon_entropy.py` — covers QUAL-08
- [ ] `tests/unit/monitoring/__init__.py` — package init for new module
- [ ] `tests/unit/monitoring/test_ks_drift_monitor.py` — covers QUAL-09
- [ ] `tests/unit/monitoring/test_cusum_monitor.py` — covers QUAL-10
- [ ] `tests/unit/service_tests/test_lifecycle_freshness.py` — covers QUAL-03

---

## Key Integration Points (Exact File Locations)

| What | File | Line/Function | Notes |
|------|------|---------------|-------|
| CIS bucket methods to refactor | `src/intelligence/trading/cis_scorer.py` | `_trend`, `_momentum`, `_structure`, `_pattern`, `_institutional`, `_regime` | Return signature: `float` → `(float, dict[str, float])` |
| CIS contributions assembly | `src/intelligence/trading/cis_scorer.py` | `score()` line ~156 | Comment says "populated in Task 13" |
| `_build_all_ranked()` extension | `src/intelligence/trading/aggregator.py` | line 351 | Alpha decay + Hurst/Shannon + TREND_SETUPS constant |
| `MIN_BARS_BETWEEN_SIGNALS` pattern | `services/signal_generator_service.py` | line 68 | Follow same dict pattern for `ALPHA_HALF_LIFE_BARS`, `_SIGNAL_COOLDOWN_BARS` |
| `_signal_gate` existing state | `services/signal_generator_service.py` | search `_signal_gate` | New `_setup_last_fire` and `_setup_cooldown` dicts alongside |
| Lifecycle per-bar loop | `services/signal_lifecycle_service.py` | active signal evaluation loop | Insert freshness decay here |
| `_bars_elapsed()` helper | `services/signal_lifecycle_service.py` | line 43 | Reuse directly for freshness decay |
| Weight updater CUSUM extension | `src/intelligence/weight_updater.py` | `compute_new_weights()` / caller | Add CUSUM query + adjustment after base multiplier |
| stream_keys.py addition | `src/core/stream_keys.py` | end of file | `drift_ks(env_prefix, symbol, tf)` |
| Killzone fields available | `src/intelligence/context/session_context.py` | outputs frozenset | `in_london_killzone`, `in_ny_killzone` — already in features dict |
| I7 plugin names for TREND_SETUPS | `src/intelligence/register_plugins.py` | `TIER_I7` | All 17 plugin names with their `regime_type` attribute |
| Plugin registration | `src/intelligence/register_plugins.py` | `register_all_plugins()` + `TIER_I4` | Both must be updated for Hurst/Shannon |
| API router registration | `src/api/main.py` | router includes | Add `drift` router alongside `signals`, `features` |
| Migration numbering | `production/migrations/` | last is `025_drop_unused_gin_indexes.sql` | Next migration: `026_drift_monitor.sql` |

---

## Sources

### Primary (HIGH confidence)
- Direct code reading — `src/intelligence/trading/cis_scorer.py` — exact bucket methods and CISResult dataclass
- Direct code reading — `src/intelligence/trading/aggregator.py` — `_build_all_ranked()` and `aggregate()` exact signatures
- Direct code reading — `services/signal_generator_service.py` — `MIN_BARS_BETWEEN_SIGNALS`, service patterns
- Direct code reading — `services/signal_lifecycle_service.py` — `_bars_elapsed()`, per-bar loop structure
- Direct code reading — `src/intelligence/register_plugins.py` — `TIER_I4`, `TIER_I7` canonical lists
- Direct code reading — `src/intelligence/context/garch_volatility.py` — I4 plugin pattern
- Direct code reading — `src/core/stream_keys.py` — key constructor patterns
- Direct code reading — `src/observability/metrics.py` — metrics registration gotcha (no labelnames)
- `docs/plans/2026-03-11-signal-drift-detection-design.md` — authoritative T3 design (DB schema, KS algo, CUSUM algo, Prometheus metrics, API response format)
- `docs/ideas/renaissance-gap-analysis.md` — T0–T3 overview, implementation rationale
- `.planning/phases/29-renaissance-signal-quality/29-CONTEXT.md` — locked decisions for all 10 requirements

### Secondary (MEDIUM confidence)
- `src/intelligence/CLAUDE.md` — `regime_type` attribute convention on I7 plugins (used for TREND_SETUPS determination)
- `CLAUDE.md` — Prometheus metric registration pattern (`PLUGIN_EXECUTION_TOTAL` as module-level constant)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; all libraries already installed
- Architecture: HIGH — design docs are exhaustive; exact code locations verified by direct file reading
- Pitfalls: HIGH — identified from direct code inspection of integration points
- CUSUM starting parameters: MEDIUM — explicitly labeled as "starting values, tune empirically" in design doc
- Hurst quality mapping functions: MEDIUM — Claude's discretion; linear is a reasonable starting point

**Research date:** 2026-03-12
**Valid until:** 2026-04-12 (stable codebase; no external dependencies change)
