# Phase 137: Feature Factory - Research

**Researched:** 2026-06-20
**Domain:** Pure-function feature computation library, TimescaleDB hypertable, IBKR historical backfill, I5-I7 archival, IntelligencePipeline cutover
**Confidence:** HIGH (all findings from codebase inspection + canonical architecture docs)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** 35 primitives grouped into named intelligence vectors (trade theses). V1 Quant is the starting hypothesis. IC measures it, not the researcher.
- **D-02:** V1 Quant is the only vector at Phase 137. V2+ deferred until V1 IC is proven. V1 Quant members: `momentum_z_5, momentum_z_20, hma_slope_z, range_position, bar_close_pos, atr_z, vol_ratio, ctf_momentum`
- **D-03:** Vector membership APR-governed under `alpha.vector.v1_quant.members`. No hardcoded membership lists.
- **D-04:** `feature_vectors` stores raw primitives only. No vector column. No aggregation. Schema: `(symbol, tf, bar_ts)` -> 35 typed float columns.
- **D-05:** Phase 137 does not touch `intelligence_features`. Source of truth is `market_data_ohlcv` only.
- **D-06:** Full backfill (58 ETFs x 4 TFs within 5% of theoretical max) is a hard gate before Phase 138.
- **D-07:** `regime_label_source = 'filtered'` always. Forward Viterbi only. Backward smoother banned. DB constraint enforces this.
- **D-08:** `FeatureFactory.compute()` is a pure function. No DB reads. No Kafka. No state mutations. APR loaded once at init via `FeatureFactoryConfig` frozen dataclass.
- **D-09:** I5/I6/I7 archived atomically at end of Phase 137. No shadow period. I7 runs live until cutover. Archive to `src/intelligence/archive/` intact without modification.
- **D-10:** `alpha_events` downstream attribution loop (Phase 139) must not be blocked by Phase 137 schema decisions. `feature_vectors` is designed with downstream attribution in mind.
- **D-11:** Backfill is a single job with checkpoint/resume per `(symbol, tf)` pair. `backfill_status` table tracks `{pending, in_progress, complete, failed}`.
- **D-12:** Existing `feature_writer` service infrastructure is reused. Write target changes from `intelligence_features` to `feature_vectors`.
- **D-13:** No migration on `intelligence_features`. `feature_vectors` has `pipeline_version` in DDL natively.

### Claude's Discretion

None explicitly listed.

### Deferred Ideas (OUT OF SCOPE)

- IC measurement (Phase 138)
- V2, V3, and beyond vectors
- Vector score computation
- Attribution loop (Kafka return path)
- Alpha Decay Monitor
- Analog Engine
- Portfolio construction, Kelly sizing
- I7 alpha scorer transformation
- I5/I6/I7 deletion
</user_constraints>

---

## Summary

Phase 137 builds a pure-function feature library (`FeatureFactory`) producing a typed `FeatureVector` frozen dataclass from raw OHLCV bars, creates the `feature_vectors` TimescaleDB hypertable, runs historical backfill across 58 ETFs x 4 TFs, then cuts over the live pipeline from the 138-plugin registry to a single `FeatureFactory.compute()` call.

The codebase already contains working implementations for most of the 35 primitives scattered across `src/intelligence/features/`, `src/intelligence/context/`, and `src/intelligence/services/`. Phase 137 extracts the pure computational core of each, strips plugin scaffolding, and assembles them into a single stateless function library. The existing `feature_writer` service, `BaseWriter` infrastructure, `ConfigService` APR pattern, and `intelligence_pipeline.py` `_prewarm_threshold_config()` pattern are all reused without structural change.

The primary implementation risks are: (1) `vix_z`, `flight_quality`, and `yield_slope_z` currently require live injected frames from cross-asset services - these need redesign as pure functions over cached HTF bar history; (2) the backfill job is a new standalone script consuming `market_data_ohlcv` directly, not a replay of the old pipeline; (3) `alpha.` prefix is not in `OPS_PREFIXES` and must be added to `ConfigService` before any `alpha.*` APR keys can be written; (4) a new `topic_feature_vectors` Kafka topic key must be added to `stream_keys.py`.

**Primary recommendation:** Build in four sequential work streams - (A1) schema migration + `feature_vectors` hypertable; (A2) `FeatureFactory` + `FeatureCache` pure-function library with APR backing; (A3) backfill job with `backfill_status` checkpoint table; (A4) pipeline cutover + I5-I7 archival.

---

## Standard Stack

### Core (confirmed from codebase)

| Component | Location | Purpose | Notes |
|-----------|----------|---------|-------|
| `numpy` | already installed | All rolling window math | All existing plugins use it |
| `asyncpg` | already installed | TimescaleDB inserts | Pass `dict` not `json.dumps()` for JSONB |
| `dataclasses.dataclass(frozen=True)` | stdlib | `FeatureVector` contract | Frozen = immutable, thread-safe |
| `ConfigService` | `src/config/config_service.py` | APR key loading | `get_sync()` after prewarm |
| `BaseWriter` | `src/core/agent/base_writer.py` | Feature writer base | Batch/flush/DLQ pattern |
| `TimescaleDB hypertable` | existing infra | `feature_vectors` storage | 3-month chunk interval |

### Existing Primitive Implementations to Extract

| Primitive | Existing Location | Status |
|-----------|------------------|--------|
| `momentum_z_5`, `momentum_z_20` | `src/intelligence/context/momentum_context.py` | Extract log-return + z-score core |
| `hma_slope_z` | `src/intelligence/features/i1_indicators/hma.py` + slope computation | Extract WMA core, add z-score |
| `range_position` | Inline in various trading plugins | Pure arithmetic, trivial |
| `bar_close_pos` | Inline in trading plugins | Pure arithmetic: `(close - low) / (high - low)` |
| `gap_z` | Derived from `(open - prev_close) / ATR` | Trivial after ATR |
| `atr_z` | `src/intelligence/features/i1_indicators/atr.py` (ATR exists) | Add z-score normalization |
| `vol_ratio` | Exists in volatility regime context | Extract realized vol short/long ratio |
| `ofi_z` | `src/intelligence/features/i1_indicators/ofi.py` | Use proxy path (OHLCV-only), add z-score |
| `cvd_slope_z` | `src/intelligence/features/i1_indicators/cvd.py` | Use proxy path, add z-score |
| `cmf` | `src/intelligence/features/i1_indicators/cmf.py` | Extract CMF core directly |
| `volume_z` | `src/intelligence/features/i1_indicators/ofi.py` (volume history) | Simple rolling z-score |
| `rel_volume` | Inline - volume / 20-bar mean | Trivial arithmetic |
| `informed_flow` | `(close - open) / ATR` | Trivial after ATR |
| `vwap_dev_sigma` | `src/intelligence/context/anchored_vwap.py` | Session VWAP + std needed |
| `poc_dist_atr`, `va_position` | `src/intelligence/context/volume_profile.py` | Extract session VP core |
| `sr_support_dist`, `sr_resist_dist` | `src/intelligence/context/sr_consensus.py` | Extract zone distance logic |
| `hmm_regime_prob`, `hmm_entropy` | `src/intelligence/features/smc_context/hmm_regime.py` | Forward Viterbi only |
| `hurst` | `src/intelligence/context/hurst_exponent.py` | R/S analysis - extract directly |
| `shannon` | `src/intelligence/context/shannon_entropy.py` | Entropy of log-return dist - extract directly |
| `garch_ratio` | `src/intelligence/context/garch_volatility.py` | GARCH sigma / realized vol |
| `adx` | `src/intelligence/features/i1_indicators/adx.py` | ADX computation exists |
| `vix_z` | `src/intelligence/context/vix_context.py` | Needs redesign: currently frame-injected |
| `flight_quality` | `src/intelligence/context/macro_context.py` (ftq_score) | Needs redesign: currently cross-asset injected |
| `yield_slope_z` | `src/intelligence/context/macro_context.py` (yield_curve_slope) | Needs redesign: currently cross-asset injected |
| `in_ny_session`, `in_overlap` | `src/intelligence/context/session_context.py` | Pure timestamp arithmetic |
| `dow_sin`, `dow_cos`, `month_position` | New - trivial timestamp math | Pure arithmetic |
| `ctf_momentum`, `ctf_vwap_align`, `ctf_regime_align` | Exists in I6 confluence tier | Read from `FeatureCache` HTF state |

---

## Architecture Patterns

### FeatureFactory Module Structure

```
src/intelligence/
├── feature_factory.py      # FeatureFactory class + FeatureFactoryConfig + FeatureVector
├── feature_cache.py        # FeatureCache: regime-level (30-bar cadence) + HTF cached state
└── archive/                # I5, I6, I7 moved here at cutover (Phase 137 final step)

services/
├── feature_writer.py       # EXTENDED: write target changes to feature_vectors
└── backfill_feature_factory.py  # NEW oneshot: backfill job with checkpoint/resume

production/migrations/
└── 155_feature_vectors.sql # CREATE TABLE + hypertable + backfill_status
```

### Pattern 1: `FeatureVector` Frozen Dataclass

`FeatureVector` is a frozen dataclass with exactly 36 fields (35 feature + `pipeline_version` carried in the outer `FeatureVectorRecord` that wraps it for persistence). The dataclass has no defaults - every field must be provided. Cold-start values use `0.0` for continuous features and `math.nan` is never stored.

```python
# src/intelligence/feature_factory.py
# Source: docs/plans/2026-06-20-v30-ground-up-architecture.md (FeatureVector Contract)
@dataclass(frozen=True)
class FeatureVector:
    momentum_z_5:     float
    momentum_z_20:    float
    range_position:   float
    bar_close_pos:    float
    gap_z:            float
    informed_flow:    float
    volume_z:         float
    ofi_z:            float
    cvd_slope_z:      float
    cmf:              float
    rel_volume:       float
    vwap_dev_sigma:   float
    atr_z:            float
    vol_ratio:        float
    poc_dist_atr:     float
    va_position:      float
    sr_support_dist:  float
    sr_resist_dist:   float
    hmm_regime_prob:  float
    hmm_entropy:      float
    hurst:            float
    shannon:          float
    garch_ratio:      float
    hma_slope_z:      float
    adx:              float
    vix_z:            float
    flight_quality:   float
    yield_slope_z:    float
    in_ny_session:    float
    in_overlap:       float
    dow_sin:          float
    dow_cos:          float
    month_position:   float
    ctf_momentum:     float
    ctf_vwap_align:   float
    ctf_regime_align: float
```

### Pattern 2: APR Loading in FeatureFactory

The pure-function contract (D-08) requires that `FeatureFactory` never calls `ConfigService` at compute time. APR values are loaded once at pipeline init and passed as a frozen config object.

```python
# Source: docs/plans/2026-06-20-v30-ground-up-architecture.md (Loading pattern)
@dataclass(frozen=True)
class FeatureFactoryConfig:
    momentum_window_short: int    # feature.momentum.window_short
    momentum_window_long: int     # feature.momentum.window_long
    momentum_zscore_window: int   # feature.momentum.zscore_window
    volume_zscore_window: int     # feature.volume.zscore_window
    ofi_zscore_window: int        # feature.ofi.zscore_window
    cvd_slope_bars: int           # feature.cvd.slope_bars
    cmf_period: int               # feature.cmf.period
    vol_short_bars: int           # feature.vol.short_bars
    vol_long_bars: int            # feature.vol.long_bars
    hma_period: int               # feature.hma.period
    adx_period: int               # feature.adx.period
    hurst_window: int             # feature.hurst.window
    garch_window: int             # feature.garch.window
    vix_zscore_window: int        # feature.vix.zscore_window
    yield_curve_zscore_window: int  # feature.yield_curve.zscore_window
    regime_cache_refresh_bars: int  # feature.regime.cache_refresh_bars
```

### Pattern 3: FeatureCache for Regime-Level State

Regime-level features (HMM, Hurst, Shannon, GARCH) are expensive and change slowly. They recompute every `regime_cache_refresh_bars` (default 30). The `FeatureCache` dataclass holds this state and is updated by the caller (`IntelligencePipeline`), not by `FeatureFactory`.

```python
# src/intelligence/feature_cache.py
@dataclass
class FeatureCache:
    # Regime-level (refreshed every 30 bars)
    hmm_regime_prob: float = 0.0
    hmm_entropy: float = 0.0
    hurst: float = 0.5
    shannon: float = 1.0
    garch_ratio: float = 1.0
    hma_slope_z: float = 0.0
    adx: float = 0.0
    bars_since_regime_refresh: int = 0

    # Cross-asset cached from HTF bars (updated whenever HTF bar arrives)
    vix_z: float = 0.0
    flight_quality: float = 0.0
    yield_slope_z: float = 0.0

    # CTF from HTF cached state
    ctf_momentum: float = 0.0
    ctf_vwap_align: float = 0.0
    ctf_regime_align: float = 0.0

    # Session-level VP (reset at session open)
    poc_dist_atr: float = 0.0
    va_position: float = 0.5
    sr_support_dist: float = 0.0
    sr_resist_dist: float = 0.0
```

### Pattern 4: IntelligencePipeline Prewarm Registration

The `intelligence_pipeline.py` `_prewarm_threshold_config()` method loads APR keys and injects `ConfigService` into modules. `FeatureFactory` is registered here alongside existing modules.

```python
# services/intelligence_pipeline.py - extend _prewarm_threshold_config()
# Source: confirmed pattern from codebase inspection
from src.intelligence import feature_factory
feature_factory.set_config_service(self._config_service)

# Also add to _THRESHOLD_KEYS:
("feature.momentum.window_short", 5),
("feature.momentum.window_long", 20),
("feature.momentum.zscore_window", 252),
# ... all feature.* and alpha.vector.* keys
```

### Pattern 5: feature_writer Extension (D-12)

The existing `feature_writer.py` changes only its write target. The `_parse_payload()` method validates a `FeatureVectorRecord` instead of `BarIntelligenceRecord`. The `_INSERT_FEATURE_SQL` changes to target `feature_vectors`. All `BaseWriter` infrastructure (batch size, flush interval, DLQ, OTel metrics) is inherited unchanged.

### Pattern 6: Backfill Job Architecture (D-11)

```python
# services/backfill_feature_factory.py - new oneshot service
# Checkpoint/resume via backfill_status table
# For each (symbol, tf) in PENDING order:
#   1. Mark in_progress
#   2. Read bars from market_data_ohlcv in chunks (no full-table load)
#   3. Run FeatureFactory.compute() over rolling window
#   4. Batch INSERT into feature_vectors
#   5. Mark complete
#   6. Log row count vs theoretical max
```

### Pattern 7: `alpha.` Prefix Registration

`ConfigService.OPS_PREFIXES` in `src/config/config_service.py` does not include `"alpha."`. This MUST be added before any `alpha.*` key (including `alpha.vector.v1_quant.members`) can be written via `ConfigService.set()`.

One-line change: add `"alpha.",` to the `OPS_PREFIXES` tuple in `src/config/config_service.py`.

### Pattern 8: Kafka Topic for feature_vectors

A new topic function must be added to `src/core/stream_keys.py`:

```python
def topic_feature_vectors(env_name: str) -> str:
    """Kafka topic for FeatureVectorRecord per bar, consumed by feature_writer."""
    return f"{env_prefix(env_name)}intelligence.feature_vectors"
```

### Anti-Patterns to Avoid

- **Do not use tick data path** for OFI/CVD in FeatureFactory: the proxy path `(close - open) / ATR` for informed_flow and `(2*close - high - low) / (high - low) * volume` for OFI/CVD is correct for OHLCV-only backfill. The tick path requires live tick data not present in `market_data_ohlcv`.
- **Do not use backward smoother** in HMM computation: `_forward_step()` only, never `_smooth()`. The existing `hmm_regime.py` plugin has both paths - extract only the forward pass.
- **Do not call ConfigService.get() inside FeatureFactory.compute()**: APR loaded once at init via `FeatureFactoryConfig`. Inline DB calls in the hot path violate DAG Invariant 5.
- **Do not load full symbol history into memory for backfill**: chunk reads from `market_data_ohlcv` with a sliding window equal to the max lookback required (~500 bars warm-up).
- **Do not reuse `intelligence_features` as backfill source**: that table has `regime_label_source = 'smoothed'` (lookahead bias) and old commodity futures data. `market_data_ohlcv` is the only valid source.
- **Do not define vector membership in code**: `alpha.vector.v1_quant.members` is an APR key, not a frozenset constant.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| HMM forward algorithm | New HMM from scratch | Extract `_forward_step()` from `src/intelligence/features/smc_context/hmm_regime.py` |
| Hurst exponent R/S | New Hurst implementation | Extract `_hurst_rs()` from `src/intelligence/context/hurst_exponent.py` |
| Shannon entropy | New entropy calculator | Extract `_shannon_entropy()` from `src/intelligence/context/shannon_entropy.py` |
| GARCH(1,1) estimation | New GARCH | Extract `_compute_full_core()` from `src/intelligence/context/garch_volatility.py` |
| CMF computation | New CMF | Extract from `src/intelligence/features/i1_indicators/cmf.py` |
| ADX computation | New ADX | Extract from `src/intelligence/features/i1_indicators/adx.py` |
| Volume profile (POC/VAH/VAL) | New VP calculator | Extract session-track from `src/intelligence/context/volume_profile.py` |
| VIX z-score | New VIX computation | Extract from `src/intelligence/context/vix_context.py` |
| ATR calculation | New ATR | Extract from `src/intelligence/trading/atr_utils.py` (`get_atr()`) |
| TimescaleDB hypertable creation | Custom partitioning | `SELECT create_hypertable('feature_vectors', 'bar_ts', chunk_time_interval => INTERVAL '3 months')` |
| Writer batching/DLQ | New writer | `BaseWriter` in `src/core/agent/base_writer.py` |
| APR key loading | Custom config system | `ConfigService.get_sync()` after prewarm in `_prewarm_threshold_config()` |

---

## Common Pitfalls

### Pitfall 1: Cross-Asset Features Require Redesign

**What goes wrong:** `vix_z`, `flight_quality`, and `yield_slope_z` are currently computed from `frames["cross_asset"]` and `frames["vix"]` injected at pipeline runtime by `cross_asset_analyzer` and `macro_compute` services. There is no direct computation from OHLCV bars.

**Why it happens:** In the v2.x pipeline, cross-asset state is maintained as a separate Kafka topic and injected into bar frames. `FeatureFactory` cannot receive injected frames (D-08: pure function).

**How to avoid:** These three features are cached in `FeatureCache` and updated separately: `vix_z` is computed from VIX ETF (`VXX` or `VIXY` from `market_data_ohlcv`) bars arriving on the HTF topic. `flight_quality` is computed from TLT/SPY relative returns. `yield_slope_z` requires a yield curve proxy (2Y-10Y spread from Treasury ETF returns - e.g., `SHY`/`TLT` ratio). All are pre-cached and read by `FeatureFactory.compute()` from `FeatureCache` - no live cross-asset service dependency in the hot path.

**Warning signs:** Any `FeatureFactory` code that references Kafka topics, injected frame dicts, or async operations.

### Pitfall 2: Regime Feature Recompute Cadence

**What goes wrong:** Computing HMM, Hurst, Shannon, and GARCH every bar for backfill would require ~500-bar lookback windows every bar, making backfill prohibitively slow across 58 symbols x 4 TFs x millions of bars.

**Why it happens:** These features don't change meaningfully bar-to-bar (HMM transitions are designed to be sticky at 94-95%).

**How to avoid:** `FeatureCache.bars_since_regime_refresh` counter. Recompute regime features every `feature.regime.cache_refresh_bars` (default 30) bars and serve from cache between refreshes. During backfill, the same counter logic applies.

**Warning signs:** Backfill taking hours per symbol at 5m granularity.

### Pitfall 3: OFI/CVD Tick Path in Backfill

**What goes wrong:** The existing OFI and CVD plugins have a "tick path" (primary) using `tick_buffer` from live market data, and a "proxy path" (fallback) using OHLCV. Historical bars in `market_data_ohlcv` have no tick data.

**Why it happens:** The `compute_full()` method of `OFIPlugin` checks `tick_buf = frames.get("tick_buffer") or []` and uses the proxy if empty. But when extracting for FeatureFactory, the caller must not accidentally pass a non-empty tick buffer.

**How to avoid:** `FeatureFactory` always uses the proxy path for `ofi_z` and `cvd_slope_z`. The computation is: OFI proxy = `(close - low) / (high - low + epsilon) * volume`, z-scored. CVD proxy = `(2*close - high - low) / (high - low + epsilon) * volume`, cumulative per session, slope over N bars, z-scored. Never reference `frames["tick_buffer"]`.

**Warning signs:** `ofi_variant = "tick"` in any `feature_vectors` row computed during backfill.

### Pitfall 4: `alpha.` Not in OPS_PREFIXES

**What goes wrong:** `ConfigService.set()` raises `ConfigValidationError` for any key not starting with a registered OPS prefix. `alpha.` is not in the current `OPS_PREFIXES` tuple.

**Why it happens:** The `alpha.*` namespace was defined in architecture docs but `config_service.py` was not updated.

**How to avoid:** Add `"alpha.",` to `OPS_PREFIXES` in `src/config/config_service.py` before inserting any `alpha.*` entries into `config_schema` or `config_state`. This is a one-line change.

**Warning signs:** `ConfigValidationError: Key 'alpha.vector.v1_quant.members' is not an OPS config key.`

### Pitfall 5: `market_data_ohlcv` Has No Rows Yet

**What goes wrong:** `market_data_ohlcv` currently has 0 rows (confirmed by DB query). All 58 ETFs need historical backfill fetched from IBKR before `FeatureFactory` backfill can run.

**Why it happens:** The v2.x pipeline used `market_data_5m` (a separate table) and `intelligence_features` for commodity futures. The new `market_data_ohlcv` table exists but is empty.

**How to avoid:** Phase 137 must include an IBKR fetch step that populates `market_data_ohlcv` at target depths before `FeatureFactory` backfill runs. The existing `run_historical_pipeline.py --fetch-only` handles IBKR fetch with `--client-id 40`. The `_TF_FETCH_CONFIG` already has correct depths (1d: 7300d, 1h: 5475d, 15m: 3650d, 5m: 1631d). The fetch script filters to `is_active = true` instruments which now returns 58 ETFs only.

**Warning signs:** Backfill job finds 0 rows in `market_data_ohlcv` for any symbol.

### Pitfall 6: `intelligence_features` Has Zero v3.0-Eligible Rows

**What goes wrong:** `intelligence_features` has 0 rows (empty). Even if it had rows, they would be from commodity futures with `regime_label_source = 'smoothed'` (confirmed from MEMORY.md: 151K rows of old data, deleted or empty now).

**How to avoid:** Do not attempt to use `intelligence_features` as any source. This is confirmed correct by D-05.

### Pitfall 7: Chunk Size for IBKR Fetch

**What goes wrong:** IBKR 7-day chunk limit is a per-request limit, not a retention limit. The historical pipeline script handles chunking via `_MAX_CHUNK_DAYS=364` for named contracts (ETFs use named-contract path, not continuous).

**How to avoid:** Use the existing `run_historical_pipeline.py --fetch-only` with `--client-id 40` (not 35=provider, not 56=exceeds max). ETFs fetch via the named-contract chunked path automatically. Do not attempt to bypass chunking.

### Pitfall 8: `feature_vectors` DDL Discrepancy

**What goes wrong:** The ground-up architecture doc DDL includes columns that are not in the 35-primitive list: `rsi_fast`, `rsi_mid`, `rsi_slow`, `cci_fast`, `cci_mid`, `cci_slow`, `aroon_fast`, `aroon_slow`, `ofi_div`, `hmm_duration`, `in_london_kz`, `power_hour`, `opening_range`, `above_wk_vwap`.

**Why it happens:** The DDL in `v30-ground-up-architecture.md` was written before the 35-primitive list was locked. The CONTEXT.md (D-04, `<specifics>` section) is the binding reference: 36 columns total (35 features + `pipeline_version` equivalent metadata). The `<specifics>` section in CONTEXT.md lists exactly which columns belong to each cadence group.

**How to avoid:** The planner must use CONTEXT.md `<specifics>` as the binding column list, not the DDL snippet in the architecture doc. The DDL snippet is illustrative, not normative.

### Pitfall 9: `feature_writer` Topic Change

**What goes wrong:** The existing `feature_writer.py` consumes `topic_intelligence_journal` (carrying `BarIntelligenceRecord`). The new writer must consume a different topic carrying `FeatureVectorRecord`. If the topic name is not added to `stream_keys.py`, it will be a hardcoded string (DAG Invariant 4 violation).

**How to avoid:** Add `topic_feature_vectors()` to `stream_keys.py` first. Use it in both `intelligence_pipeline.py` (publisher) and the updated `feature_writer.py` (consumer).

### Pitfall 10: Backfill IBKR Client ID

**What goes wrong:** Default client ID 56 exceeds `_MAX_CLIENT_ID=50`. Client ID 35 is reserved for the live provider. The CLAUDE.md specifies `--client-id 40` for historical backfill.

**How to avoid:** All IBKR fetch scripts must use `--client-id 40`.

---

## Code Examples

### feature_vectors DDL (binding from CONTEXT.md `<specifics>`)

```sql
-- Source: 137-CONTEXT.md <specifics> section + docs/plans/2026-06-20-v30-ground-up-architecture.md
-- migration: 155_feature_vectors.sql
CREATE TABLE feature_vectors (
    symbol              text             NOT NULL,
    tf                  text             NOT NULL,
    bar_ts              timestamptz      NOT NULL,
    pipeline_version    text             NOT NULL,
    regime              text,
    regime_label_source text             NOT NULL DEFAULT 'filtered'
                        CHECK (regime_label_source IN ('filtered', 'unknown')),
    -- Bar-level (14)
    momentum_z_5        double precision,
    momentum_z_20       double precision,
    range_position      double precision,
    bar_close_pos       double precision,
    gap_z               double precision,
    informed_flow       double precision,
    volume_z            double precision,
    ofi_z               double precision,
    cvd_slope_z         double precision,
    cmf                 double precision,
    rel_volume          double precision,
    vwap_dev_sigma      double precision,
    atr_z               double precision,
    vol_ratio           double precision,
    -- Session-level (4)
    poc_dist_atr        double precision,
    va_position         double precision,
    sr_support_dist     double precision,
    sr_resist_dist      double precision,
    -- Regime-level (7)
    hmm_regime_prob     double precision,
    hmm_entropy         double precision,
    hurst               double precision,
    shannon             double precision,
    garch_ratio         double precision,
    hma_slope_z         double precision,
    adx                 double precision,
    -- Cross-asset (3)
    vix_z               double precision,
    flight_quality      double precision,
    yield_slope_z       double precision,
    -- Calendar (5)
    in_ny_session       double precision,
    in_overlap          double precision,
    dow_sin             double precision,
    dow_cos             double precision,
    month_position      double precision,
    -- Cross-timeframe (3)
    ctf_momentum        double precision,
    ctf_vwap_align      double precision,
    ctf_regime_align    double precision,
    PRIMARY KEY (symbol, tf, bar_ts)
);
SELECT create_hypertable('feature_vectors', 'bar_ts', chunk_time_interval => INTERVAL '3 months');
SELECT add_compression_policy('feature_vectors', INTERVAL '6 months');

-- backfill_status checkpoint table (D-11)
CREATE TABLE backfill_status (
    symbol      text NOT NULL,
    tf          text NOT NULL,
    status      text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'in_progress', 'complete', 'failed')),
    rows_written bigint,
    theoretical_max bigint,
    started_at  timestamptz,
    completed_at timestamptz,
    error_msg   text,
    PRIMARY KEY (symbol, tf)
);
```

### APR Seeding Migration

```sql
-- migration: 155_feature_vectors.sql (continued)
-- Add alpha. prefix to OPS_PREFIXES is a code change, not a migration.
-- Feature Factory APR keys:
INSERT INTO config_schema (config_key, value_type, default_value, description) VALUES
    ('feature.momentum.window_short', 'int', '5', '[conventional] Short momentum lookback bars'),
    ('feature.momentum.window_long', 'int', '20', '[conventional] Long momentum lookback bars'),
    ('feature.momentum.zscore_window', 'int', '252', '[conventional] Rolling z-score window, ~1 trading year'),
    ('feature.volume.zscore_window', 'int', '20', '[conventional] Volume z-score rolling window'),
    ('feature.ofi.zscore_window', 'int', '20', '[conventional] OFI z-score rolling window'),
    ('feature.cvd.slope_bars', 'int', '5', '[conventional] CVD slope lookback bars'),
    ('feature.cmf.period', 'int', '20', '[conventional] Chaikin Money Flow period'),
    ('feature.vol.short_bars', 'int', '5', '[conventional] Short realized vol window'),
    ('feature.vol.long_bars', 'int', '20', '[conventional] Long realized vol window'),
    ('feature.hma.period', 'int', '20', '[conventional] HMA period for slope computation'),
    ('feature.adx.period', 'int', '14', '[conventional] ADX period'),
    ('feature.hurst.window', 'int', '252', '[conventional] Hurst R/S rolling window'),
    ('feature.garch.window', 'int', '100', '[initial_estimate] GARCH estimation window'),
    ('feature.vix.zscore_window', 'int', '252', '[conventional] VIX z-score rolling window'),
    ('feature.yield_curve.zscore_window', 'int', '252', '[conventional] Yield curve z-score window'),
    ('feature.regime.cache_refresh_bars', 'int', '30', '[initial_estimate] Regime feature recompute cadence')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('feature.momentum.window_short', '5', 1),
    ('feature.momentum.window_long', '20', 1),
    ('feature.momentum.zscore_window', '252', 1),
    ('feature.volume.zscore_window', '20', 1),
    ('feature.ofi.zscore_window', '20', 1),
    ('feature.cvd.slope_bars', '5', 1),
    ('feature.cmf.period', '20', 1),
    ('feature.vol.short_bars', '5', 1),
    ('feature.vol.long_bars', '20', 1),
    ('feature.hma.period', '20', 1),
    ('feature.adx.period', '14', 1),
    ('feature.hurst.window', '252', 1),
    ('feature.garch.window', '100', 1),
    ('feature.vix.zscore_window', '252', 1),
    ('feature.yield_curve.zscore_window', '252', 1),
    ('feature.regime.cache_refresh_bars', '30', 1)
ON CONFLICT (config_key) DO NOTHING;

-- V1 Quant vector membership (APR-governed, D-03)
-- Requires alpha. prefix in OPS_PREFIXES first.
INSERT INTO config_schema (config_key, value_type, default_value, description) VALUES
    ('alpha.vector.v1_quant.members', 'str',
     'momentum_z_5,momentum_z_20,hma_slope_z,range_position,bar_close_pos,atr_z,vol_ratio,ctf_momentum',
     '[initial_estimate] V1 Quant vector constituent primitives. Mutable via APR. IC discovery may prune members.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('alpha.vector.v1_quant.members',
     'momentum_z_5,momentum_z_20,hma_slope_z,range_position,bar_close_pos,atr_z,vol_ratio,ctf_momentum',
     1)
ON CONFLICT (config_key) DO NOTHING;
```

### z-score Rolling Window Pattern

```python
# Pattern used across multiple primitives - confirmed from existing implementations
# Source: src/intelligence/context/vix_context.py, src/intelligence/context/momentum_context.py
from collections import deque
import numpy as np

def _rolling_zscore(value: float, history: deque, window: int) -> float:
    """Compute z-score of value against rolling window history.
    Returns 0.0 when insufficient history or near-zero std."""
    history.append(value)
    if len(history) < window:
        return 0.0
    arr = np.array(list(history)[-window:])
    std = arr.std()
    if std < 1e-8:
        return 0.0
    return float((value - arr.mean()) / std)
```

### Backfill Row Count Verification Query (D-06)

```sql
-- Source: 137-CONTEXT.md D-06, IC spec §II
-- Run after backfill completes to verify within 5% of theoretical max
SELECT
    b.symbol,
    b.tf,
    b.rows_written,
    b.theoretical_max,
    round(b.rows_written::numeric / b.theoretical_max * 100, 1) as pct_coverage,
    CASE WHEN b.rows_written >= b.theoretical_max * 0.95 THEN 'PASS' ELSE 'FAIL' END as gate
FROM backfill_status b
WHERE b.status = 'complete'
ORDER BY pct_coverage ASC;
```

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| 138-plugin registry dispatch per bar | 1 `FeatureFactory.compute()` call per bar | Eliminates researcher-defined combination rules |
| Plugin-specific state management (IncrementalMixin) | Centralized `FeatureCache` owned by caller | Pure function contract, deterministic unit tests |
| `intelligence_features` JSONB blobs | `feature_vectors` typed columns | Direct SQL IC computation, no JSONB extraction |
| Backward-smoothing HMM labels (lookahead bias) | Forward Viterbi only (`regime_label_source='filtered'`) | Causally correct IC measurement |
| Futures/FX pipeline | ETF-only, 58 symbols | Universe locked before IC measurement |

**Deprecated/outdated in Phase 137 context:**
- `BarIntelligenceRecord` schema: not used for `feature_vectors` writes
- `PluginRegistry.process_bar()`: replaced by `FeatureFactory.compute()` at cutover
- `topic_intelligence_journal` as feature persistence topic: replaced by `topic_feature_vectors`

---

## Open Questions

1. **VIX/TLT/SHY as cross-asset proxies for ETF universe**
   - What we know: `vix_z` needs a VIX proxy instrument. For ETF universe, VXX and VIXY are available ETFs tracking VIX futures. TLT is available for `flight_quality`. `SHY` can proxy 2Y Treasuries for yield slope.
   - What's unclear: VXX tracks VIX futures (with roll decay), not spot VIX. The z-score will be different from spot VIX z-score.
   - Recommendation: Use VXX for `vix_z` computation (it is already in the 58-ETF universe: confirm). For `yield_slope_z`, use `TLT/SHY` return ratio as a yield curve proxy. For `flight_quality`, use `TLT/SPY` divergence (both in universe). All three are OHLCV-computable from `market_data_ohlcv`. LOW confidence - verify VXX is in the 58 active ETFs.

2. **Warm-up window for rolling features at backfill start**
   - What we know: Hurst exponent needs 252-bar window, momentum z-score needs 252-bar window, GARCH needs 100-bar window. The first `feature_vectors` row per symbol cannot have valid z-scores until the warm-up window is satisfied.
   - What's unclear: Whether to (a) skip the first N rows from `feature_vectors` during backfill, (b) write `0.0` cold-start values for the warm-up period, or (c) write `NULL`.
   - Recommendation: Write `0.0` for features not yet warmed up (consistent with `_nullable_float()` design: None=cold-start issue, but for IC measurement, `0.0` != signal). The IC engine (Phase 138) excludes warm-up rows by requiring `pipeline_version` consistency and minimum N. Document the warm-up period per TF in `backfill_status.rows_written` vs `theoretical_max` accounting.

3. **Session-level VP reset mechanism in backfill**
   - What we know: `poc_dist_atr`, `va_position` use a session track that resets at 09:30 ET. During backfill of daily bars (1d TF), there is no intraday session concept.
   - What's unclear: What values to use for session-level features at 1d timeframe.
   - Recommendation: For 1d TF, set `poc_dist_atr = 0.0`, `va_position = 0.5`, `sr_support_dist = 0.0`, `sr_resist_dist = 0.0` as these concepts are intraday-specific. IC engine will measure whether these features carry signal at 1d granularity and likely discover they do not.

---

## Sources

### Primary (HIGH confidence)

- Codebase inspection: `src/intelligence/features/`, `src/intelligence/context/`, `src/intelligence/pipeline/`, `services/intelligence_pipeline.py`, `services/feature_writer.py`, `src/config/config_service.py`, `src/core/stream_keys.py`, `services/service_auditor.py`
- `docs/plans/2026-06-20-v30-ground-up-architecture.md` — FeatureVector contract, APR namespaces, file locations
- `.planning/phases/137-feature-factory/137-CONTEXT.md` — all 13 locked decisions
- `docs/plans/2026-06-20-v30-alphaengine-ic-spec.md` §II, §III, §IV.1 — data requirements, backfill gate
- Database inspection: `market_data_ohlcv` (0 rows), `instruments` (58 active ETFs), `config_state` (existing `feature.*` keys), `feature_vectors` (does not exist yet)

### Secondary (MEDIUM confidence)

- `production/scripts/run_historical_pipeline.py` `_TF_FETCH_CONFIG` — confirmed fetch depths and ETF handling
- `docs/plans/2026-06-20-v30-i7-transition.md` — archival approach confirmed
- MEMORY.md `project_v30_phase_a_scope.md` — `market_data_ohlcv` empty confirmed, `intelligence_features` old data context

### Tertiary (LOW confidence)

- VXX as VIX proxy for ETF universe: requires confirmation VXX is in the 58 active ETF list

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - confirmed from codebase inspection
- Architecture patterns: HIGH - directly derived from existing IntelligencePipeline + BaseWriter patterns
- Don't hand-roll: HIGH - all existing implementations located and verified
- Pitfalls: HIGH for database/APR issues (verified), MEDIUM for cross-asset proxy design (inferred from current architecture)
- DDL column list: HIGH - binding from CONTEXT.md `<specifics>` section

**Research date:** 2026-06-20
**Valid until:** 2026-07-20 (stable architecture; no external library changes expected)

**Critical pre-planning checks:**
1. Confirm VXX is in the 58 active ETFs: `SELECT symbol FROM instruments WHERE symbol = 'VXX' AND is_active = true`
2. Confirm migration numbering: next migration after `154_instrument_metadata.sql` is `155_*`
3. `alpha.` prefix must be added to `OPS_PREFIXES` before any `alpha.*` APR writes
4. `market_data_ohlcv` IBKR fetch must be planned as Phase 137's first step (table is empty)
