# Signals Foundation — The Signal Ledger Architecture

**Version:** 3.0.0 | **Status:** current | **Last Updated:** 2026-06-16

---

## Purpose

The Signal Ledger Architecture (SLA) is the persistent record of every I7 trading setup detected by the intelligence pipeline, including its full lifecycle outcome. It solves three problems that ephemeral in-memory state cannot:

1. **Unbiased ML training data** — The ML scoring model needs feature vectors paired with real-world outcomes across all signal fires, not just the subset that were executed. The SLA provides this via `counterfactual_pnl_r` on every `trade_frames` row — populated by CounterfactualTracker regardless of whether the trade was ever selected, activated, or executed.
2. **Lifecycle recovery** — Service restarts, data gaps, and replay scenarios all need a durable record of which signals were pending or active. The `SignalTracker` bootstraps from `signal_ledger_full` on startup.
3. **Audit trail** — Every I7 plugin fire is recorded, including regime-suppressed signals. This creates an empirical feedback loop for gate calibration and shadow promotion.

**Who reads this doc:** Engineers building new signal types, debugging lifecycle issues, or writing ML training queries. Start here before touching any SLA table or lifecycle service.

---

## Design Principles

### Why the pipeline is DB-ignorant

The real-time pipeline (`SignalTracker`) is intentionally DB-ignorant — it holds all active signal state in memory and publishes `LifecycleTransition` events to Kafka. The `LifecycleWriter` consumes those events and writes to `signal_events`. This split exists because DB I/O is unpredictable and the hot path cannot block on it.

The SLA tables are the persistent projection of that in-memory state.

### Three-table architecture

Phase 128 replaced the legacy `signal_ledger` monolith with three tables, each owning exactly one semantic concern:

**`signal_events`** — *did the pattern fire?* Written once at I7 emit time. Carries intrinsic quality (`raw_confidence`, `factor_scores`) and extrinsic market context at fire time (ECL vectors: `ctf_score`, `ctf_confirmed`, `zone_friction_score`). The only mutable field after initial write is `status` (lifecycle transitions). TimescaleDB hypertable partitioned by `ts`.

**`trade_frames`** — *what trade was hypothesized?* One row per `entry_type` per signal fire. A plugin proposing both `at_close` and `at_pullback` entry types produces two rows. `counterfactual_pnl_r` lives here, populated for every row after TTL expiry regardless of whether the trade was executed. This column is the ML training target.

**`trade_executions`** — *what was actually traded?* One row per live execution. Most trade frames have zero rows here. `actual_pnl_r` is the realized outcome; meaningful relative to `counterfactual_pnl_r` only when measuring execution quality.

The monolith conflated all three concerns, making an unbiased ML training set impossible: filtering `WHERE pnl_r IS NOT NULL` silently excluded all signals that were never executed. The three-table design closes this survivorship bias (Bias Layer 2).

### Hypertable FK constraint

`signal_events` is a TimescaleDB hypertable. Its primary key is composite: `(signal_id, ts)`. Any foreign key pointing to it must include both columns. `trade_frames` carries `signal_ts` as a denormalized copy of `signal_events.ts` specifically for this FK:

```sql
FOREIGN KEY (signal_id, signal_ts) REFERENCES signal_events (signal_id, ts)
```

`signal_ts` always equals the `signal_events.ts` it references.
<!-- src: db/migrations/137_3table_schema.sql -->

### Join view

`signal_ledger_full` joins all three tables and is the canonical read surface. Direct table queries are permitted only when the query is strictly within one semantic layer (e.g., counting `signal_events` fires by plugin). Mixed-layer queries always go through the view.

The legacy `signal_ledger` monolith is read-only (migration 138) and will be dropped in Phase 130. Until then, `signal_ledger_full` is the correct query surface.
<!-- src: db/migrations/138_signal_ledger_readonly.sql -->

### was_selected and is_shadow

Both fields exist and serve orthogonal purposes:

- **`was_selected`** (`BOOLEAN`, on `trade_frames`) — `TRUE` for the frame that was the aggregator winner on that bar. The `SignalMetricsAnalyzer` gates on this (`WHERE was_selected = true`) — metrics are only computed for signals that were actually presented for potential execution. At most one `trade_frames` row per bar per symbol/timeframe can be `was_selected=TRUE`.
- **`is_shadow`** (`BOOLEAN`, on `signal_events`) — `TRUE` for signals from plugins not yet promoted in `shadow_registry`. Shadow signals traverse the full pipeline and accumulate outcome data but never enter the execution stream.

A signal can be `is_shadow=TRUE` and still get an outcome. A frame can be `was_selected=FALSE` and still have a counterfactual. The two flags are orthogonal.

### Why signal_schema_version is a canonical constant

`SIGNAL_SCHEMA_VERSION: int = 5` is defined in `src/intelligence/trading/signal_schema.py` and imported everywhere — no hardcoded integer literals.
<!-- src: src/intelligence/trading/signal_schema.py:25 -->

The version is an `int4` (not text). It was bumped to 5 at the Phase 129 SLA migration boundary. All ML training queries gate on this version constant. If schema issues are discovered again, the version bumps and all downstream queries are updated by changing the single constant.

### entry_type values — what each means

`entry_type` describes how the signal's entry price was resolved from market structure:

| Value | Meaning | When used |
|-------|---------|-----------|
| `at_close` | Entry at the current bar close | Default. Used by most setups where entry is immediate (momentum, candlestick, supply/demand) |
| `at_pullback` | Entry at a structural pullback level (nearest support/resistance) | Trend and MTF alignment setups — entry isn't here yet, wait for retrace |
| `at_limit` | Entry at a specific structural level (swing high/low, BB middle) | Momentum breakout, squeeze expansion, VWAP deviation — limit order approach |
| `at_reclaim` | Entry at the current close after a sweep/reclaim event | Liquidity sweep and liquidity hunt setups — confirmation that price reclaimed the level |
| `zone_proximal` | Entry at the proximal edge of a supply/demand zone | Supply/demand setups where the zone has geometric extent |

`entry_type` is stored in `trade_frames` and used by `SignalMetricsAnalyzer` to segment performance by entry style — `at_pullback` setups have structurally different activation rates than `at_close`.

---

## Architecture

### Signal flow: I7 to signal_events

```
I7 plugins (36 setups) + CISScorer aggregator
  → IntelligencePipelineAgent (_process_i7)
  → signal_processor.py (rank, regime gate, shadow gate, select winner)
  → intelligence.i7.signals Kafka topic  (full ranked list per bar)
  → SignalWriter
  → signal_events INSERT
  → trade_frames INSERT (one row per entry_type)
  → CounterfactualTracker (populates counterfactual_pnl_r after TTL expiry)
```

Missing `entry_zone_low` or `entry_zone_high` in the trade framer output routes the signal to the DLQ at write time — it never enters lifecycle tracking.

### What reads signal_ledger_full

`signal_ledger_full` is a hub, not a queue. Multiple services read it for different purposes:

| Service | What it reads | Why |
|---------|--------------|-----|
| `SignalTracker` | `pending`/`active` with `exit_at IS NULL` | Bootstrap on startup; populates in-memory active index |
| `SignalReplayAuditor` | `pending`/`active` with `expires_at < NOW()` | Recover outcomes for signals the live tracker missed |
| `SignalMetricsAnalyzer` | Resolved signals where `was_selected=true` and `counterfactual_pnl_r IS NOT NULL` | Compute per-setup performance metrics every 15 min |
| `GraduationAnalyzer` | Shadow signals with outcomes, `is_shadow=true` | Evaluate promotion gate for shadow plugins |
| ML training queries | All `signal_schema_version = 5` frames with `counterfactual_pnl_r IS NOT NULL` | Feature-label pairs for model training |

---

## Data Contracts

### signal_events (detection layer, immutable after emit)

<!-- src: db/migrations/137_3table_schema.sql -->

| Column | Type | Description |
|--------|------|-------------|
| `signal_id` | UUID | Signal identity — shared across signal_events + all trade_frames rows for this fire |
| `ts` | TIMESTAMPTZ | Bar timestamp at fire time. **Primary time column and hypertable partition dimension.** |
| `symbol` | TEXT | Instrument symbol (e.g. `ESM6`) |
| `tf` | TEXT | Bar timeframe (e.g. `1m`, `5m`, `15m`, `1h`). Canonical column; `timeframe` is a view alias. |
| `setup_plugin` | TEXT | I7 plugin that fired (e.g. `momentum_breakout_long`) |
| `direction` | TEXT | `long` or `short` (text, not integer) |
| `raw_confidence` | FLOAT8 NOT NULL | Intrinsic composite confidence; immutable after emit. ML training uses this field. |
| `calibrated_confidence` | FLOAT8 | Nullable; async-populated by calibration pipeline. |
| `cis_score` | FLOAT8 | CISScorer output (0–1). Immutable after emit. |
| `weights_version` | INT4 | CIS weight version at signal fire time. |
| `factor_scores` | JSONB | Per-plugin factor breakdown; ML weight optimization. |
| `context_features` | JSONB | Full `flat_features` snapshot at fire time; SignalRanker feature matrix. |
| `ctf_score` | FLOAT8 | CTF composite score (ECL vector). Annotation, not gate. |
| `ctf_confirmed` | BOOL | CTF boolean confirmation at fire time. |
| `zone_friction_score` | FLOAT8 | Zone friction score (ECL vector). Annotation, not gate. |
| `hmm_regime_at_fire` | INT4 | HMM regime state when signal fired (0=ranging, 1/2=trend). |
| `plugin_regime_type` | TEXT | Plugin's declared regime type (from plugin definition). |
| `garch_sigma_at_fire` | FLOAT8 | GARCH volatility estimate at fire time (staleness baseline). |
| `is_shadow` | BOOL NOT NULL DEFAULT false | `TRUE` if plugin is in shadow mode (not yet promoted). |
| `is_backfill` | BOOL NOT NULL DEFAULT false | `TRUE` if signal was generated from replay, not live. |
| `status` | TEXT NOT NULL DEFAULT 'pending' | Lifecycle state: `'pending'`, `'active'`, `'regime_suppressed'`, `'expired'` — raw string literals. |
| `signal_schema_version` | INT4 | Schema version integer. Current: 5 (set to `SIGNAL_SCHEMA_VERSION` constant). |
| `ttl_bars` | INT4 | How many bars until the signal expires if never activated. |
| `expires_at` | TIMESTAMPTZ | Pre-computed TTL timestamp. |
| `signal_computed_at` | TIMESTAMPTZ | Pipeline write wall-clock from payload; latency = `signal_computed_at - ts`. |
| `created_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | DB insertion time — distinct from `signal_computed_at`. |
| `feature_ts` | TIMESTAMPTZ | Anchor to `intelligence_features` row; JOIN on `(symbol, tf, ts = feature_ts)`. |
| `concurrent_signal_count` | INT4 | Count of other active signals at fire time; crowding indicator. |
| `concurrent_plugins` | TEXT[] | `setup_plugin` values of concurrent active signals; ML-queryable. |

### trade_frames (hypothesis layer, one per entry_type per signal)

<!-- src: db/migrations/137_3table_schema.sql -->

| Column | Type | Description |
|--------|------|-------------|
| `frame_id` | UUID PRIMARY KEY | Frame identity. |
| `signal_id` | UUID NOT NULL | FK to `signal_events.signal_id`. |
| `signal_ts` | TIMESTAMPTZ NOT NULL | Denormalized from `signal_events.ts`; required for FK to hypertable composite PK. Always equals `signal_events.ts`. |
| `entry_type` | TEXT NOT NULL | `at_close` / `at_pullback` / `at_limit` / `at_reclaim` / `zone_proximal`. |
| `direction` | TEXT NOT NULL | `long` or `short`. |
| `entry_price` | FLOAT8 | Resolved entry price from TradeFramer. |
| `stop_price` | FLOAT8 | Initial stop level. |
| `target_price` | FLOAT8 | Profit target price. |
| `r_multiple` | FLOAT8 | `(target - entry) / (entry - stop)`; standard R-multiple. |
| `ttl_bars` | INT4 | Frame-level TTL (may differ from signal TTL for pullback types). |
| `expires_at` | TIMESTAMPTZ | Frame expiry timestamp. |
| `counterfactual_pnl_r` | FLOAT8 | **ML training target.** Populated by CounterfactualTracker for every frame after TTL expiry. Always populated regardless of execution status. |
| `counterfactual_mfe` | FLOAT8 | Maximum favorable excursion during counterfactual window. |
| `counterfactual_mae` | FLOAT8 | Maximum adverse excursion during counterfactual window. |
| `counterfactual_bars` | INT4 | Bars elapsed during counterfactual measurement. |
| `counterfactual_exit_reason` | TEXT | `target_hit` / `stop_hit` / `ttl_expired`. |
| `counterfactual_measured_at` | TIMESTAMPTZ | When CounterfactualTracker populated the counterfactual fields. |
| `was_selected` | BOOL NOT NULL DEFAULT false | `TRUE` if this frame was the aggregator winner on this bar. |
| `frame_details` | JSONB | Stop architecture provenance: `stop_basis`, `stop_type_col`, `structural_stop_distance_atr`, `adaptive_buffer_mult`, `entry_zone_low`, `entry_zone_high`, chandelier stop state. |
| `regime_at_activation` | INT4 | HMM regime at entry condition trigger; NULL for `at_close` (fires immediately). |
| `created_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | |

### trade_executions (execution layer, one per live trade)

<!-- src: db/migrations/137_3table_schema.sql -->

| Column | Type | Description |
|--------|------|-------------|
| `execution_id` | UUID PRIMARY KEY | Execution identity. |
| `frame_id` | UUID NOT NULL | FK to `trade_frames.frame_id`. |
| `actual_fill_price` | FLOAT8 | Entry fill price. |
| `actual_exit_price` | FLOAT8 | Exit fill price. |
| `actual_pnl_r` | FLOAT8 | Realized P&L in R-multiples. Compare to `counterfactual_pnl_r` to measure execution quality. |
| `actual_mfe` | FLOAT8 | Maximum favorable excursion during live trade. |
| `actual_mae` | FLOAT8 | Maximum adverse excursion during live trade. |
| `actual_bars` | INT4 | Active bars from entry to exit. |
| `market_entry_price` | FLOAT8 | Parallel at-close market price at entry; reference baseline. |
| `market_entry_gap_bars` | INT4 | Bars between signal fire and execution. |
| `exit_reason` | TEXT | Exit classification. |
| `executed_at` | TIMESTAMPTZ | Entry execution timestamp. |
| `exited_at` | TIMESTAMPTZ | Exit timestamp. Canonical column; `exit_at` is a view alias. |
| `regime_at_exit` | INT4 | HMM regime at position exit; enables regime-transition analysis. |

### signal_ledger_full (canonical join view)

<!-- src: db/migrations/137_3table_schema.sql -->

`signal_ledger_full` is a LEFT JOIN across all three tables on `(signal_id, ts)`. It exposes legacy column aliases for backward compatibility: `timestamp` (→ `ts`), `timeframe` (→ `tf`), `stop_loss` (→ `stop_price`), `exit_at` (→ `exited_at`).

Always query through this view for mixed-layer queries. The view does not filter rows — if a signal has no trade frames, the frame columns are NULL; if a frame has no execution, the execution columns are NULL.

### JOIN pattern for ML training

```sql
-- Canonical unbiased training query (all signal fires with measured counterfactuals):
SELECT se.context_features, se.factor_scores,
       se.ctf_score, se.ctf_confirmed, se.hmm_regime_at_fire,
       tf.entry_type, tf.counterfactual_pnl_r
FROM signal_events se
JOIN trade_frames tf ON tf.signal_id = se.signal_id
                    AND tf.signal_ts = se.ts
WHERE tf.counterfactual_pnl_r IS NOT NULL
  AND se.signal_schema_version = 5;

-- ML JOIN to intelligence_features:
SELECT f.*, tf.counterfactual_pnl_r
FROM intelligence_features f
JOIN signal_events se ON f.symbol = se.symbol
                     AND f.ts     = se.feature_ts
                     AND f.timeframe = se.tf
JOIN trade_frames tf ON tf.signal_id = se.signal_id
                    AND tf.signal_ts = se.ts
WHERE tf.counterfactual_pnl_r IS NOT NULL
  AND se.signal_schema_version = 5;
```

---

## Signal Quality Pipeline

Every I7 signal passes through a deterministic sequence of transformations between plugin output and Kafka emission. Understanding this sequence is required before touching confidence values, training data, or the quality floor.

### Stage sequence

```
I7 plugin fires
  → compose_confidence()        clamp to [0.10, 0.95]
  → pre_quality_confidence stamp copy raw confidence before any decay or multipliers
  → alpha decay                 discount consecutive autocorrelated re-fires
  → CIS scoring                 add cis_score, bucket_scores, weights_version
  → apply_quality_gate()        Hurst × Entropy × drift-penalty multipliers; floor drop
  → apply_regime_gate()         suppress by hmm_regime vs plugin.regime_type
  → apply_tod_adjustment()      time-of-day confidence modifier
  → apply_calibration()         isotonic regression calibration curves
  → rank_signals()              assign adjusted_rank from setup_performance
  → select_winner()             pick highest-ranked regime-eligible signal
  → terminal completeness check verify REQUIRED_PIPELINE_FIELDS present; DLQ on miss
  → emit to intelligence.i7.signals Kafka topic
```

### compose_confidence

Every I7 plugin must route its raw confidence scalar through `compose_confidence()` in `confidence_utils.py` before returning a signal. This enforces `[CONF_FLOOR, CONF_CEIL] = [0.10, 0.95]` across all plugins with a single import. No inline `min()`/`max()` clamping is permitted in plugin bodies.

The floor (0.10) prevents a zero-confidence signal from persisting invisibly in lifecycle tracking. The ceiling (0.95) prevents any single plugin from claiming near-certainty regardless of evidence strength.

### pre_quality_confidence

Stamped immediately before alpha decay and all multiplier stages:

```python
sig["pre_quality_confidence"] = sig.get("confidence", 0.0)
```

This preserves the raw plugin output for ML training. `pre_quality_confidence` is what the model was actually trained to predict — it should never reflect post-processing adjustments. All ML training queries use this field, not `confidence`.

### Alpha decay (QUAL-02)

**Purpose:** Guard against autocorrelated consecutive fires. A plugin that fires 10 bars in a row is not 10 independent observations — each fire after the previous win is evidence of signal persistence, not additional independent confirmation. Without decay, high-frequency plugins systematically crowd out lower-frequency setups with stronger independent evidence.

**Formula:** `multiplier = 0.5 ** (bars_since / half_life)`

`confidence` is multiplied by this value in-place before any downstream stages see it.

**Half-life constants (empirical priors — not yet data-derived):**

| Timeframe | half_life (fires) |
|-----------|-------------------|
| `1m`      | 10                |
| `5m`      | 8                 |
| `15m`     | 8                 |
| `1h`      | 6                 |

**What `bars_since` counts:** fires since the last win, not elapsed bars. The counter increments only when the plugin fires on the current bar. A plugin that fires once, goes silent for 100 bars, and re-fires carries zero accumulated decay — it is treated as a new independent event. Silence does not penalize re-emergence.

**Reset:** `bars_since` resets to 0 when the plugin wins (is selected as the aggregator output for that bar/symbol/timeframe/direction).

**State persistence:** `_setup_last_fire` is in-memory and checkpointed to the intelligence pipeline's hot-state file on graceful shutdown. Service restarts restore it via `restore_setup_last_fire()`.

**Known empirical debt:** The half-life constants are tuned by intuition, not measured from data. The correct approach is to compute the autocorrelation function for each `(setup_plugin, timeframe)` fire series and derive half-life from the lag at which autocorrelation drops below significance (r < 0.3). `pre_quality_confidence` is now correctly stamped before decay, so the training data exists to do this analysis. Tracked as future work.

### Quality gate (apply_quality_gate)

Applies three independent multipliers to confidence after alpha decay:

- **Hurst × Entropy multiplier:** `min(hurst_quality, entropy_quality)` — `min()` not product because the two measures are correlated (both reflect regime predictability). Uses the stricter of the two rather than compounding them.
- **Drift penalty:** KS-test divergence between recent and historical feature distributions. Penalizes signals fired into a distribution-shifted market. Absent feature → neutral pass-through (1.0).
- **Empirical quality floor:** Signals below `SIGNAL_MIN_PUBLISHABLE_CONFIDENCE` (default 0.12, loaded from `.pipeline_quality_floor` written by `quality_floor_bootstrap.py`) are dropped entirely and counted by `intelligence_pipeline_quality_floor_rejections_total`. The floor is derived from the p10 confidence of historically profitable signals — not a hand-tuned constant.

### CIS scoring

`CISScorer` produces a composite intelligence score (`cis_score` 0–1) from the full feature vector across six buckets (trend, momentum, structure, volume, volatility, macro). Applied before the quality gate so the quality multipliers act on CIS-adjusted confidence.

`cis_score` and `factor_scores` are written to `signal_events` at fire time and are immutable — they reflect the regime at the moment of signal generation, not any later recalibration.

### Time-of-day adjustment (apply_tod_adjustment)

120-cell lookup table keyed by `(regime_type, timeframe, hour_et)`. Computed from rolling historical win rates per cell. A trend setup at RTH open has structurally different win characteristics than the same setup at 2pm ET — the TOD multiplier captures that without requiring the plugin to know about session context.

Cells with insufficient history default to a neutral multiplier (1.0) rather than penalizing.

### Calibration (apply_calibration)

Raw plugin confidence values are systematically biased upward — plugins tend to fire at high confidence when uncertain. Isotonic regression maps raw values to empirically calibrated probabilities. Both `confidence` and `calibrated_confidence` are set to the calibrated value; `pre_quality_confidence` (stamped before all multipliers) is the field that preserves the original plugin output for ML training.

Calibration curves are loaded from the DB at pipeline startup and refreshed periodically. Each curve is fit per `(setup_plugin, regime_type)` segment against historical outcomes — a plugin's calibration in a trending regime is distinct from its calibration in a ranging regime.

### Ranking and winner selection

`rank_signals()` assigns `adjusted_rank` from `setup_performance` data:

- **Validated setups** (`sample_size >= 30`): `adjusted_rank = perf_multiplier` derived from rolling Sharpe rank, range `[0.5, 1.5]`.
- **Warm-up setups** (`sample_size < 30`): `adjusted_rank = 0.5` (warm-up penalty, D-16). New or low-volume setups cannot outrank validated ones.

`select_winner()` picks the regime-eligible signal with the highest `adjusted_rank` (lowest numeric value under ascending sort). Tiebreaking: higher `confidence` wins. The winner produces a `trade_frames` row marked `was_selected=TRUE`. All other signals on that bar produce rows with `was_selected=FALSE`.

### Swarm overlay

After winner selection, the alpha swarm (`AlphaSwarm`) applies a `swarm_multiplier` derived from a mixture-of-agents (MoA) composite across 5 alpha swarm agents:

```
adjusted_confidence = calibrated_confidence × swarm_multiplier
```

The swarm evaluates the selected signal against additional dimensions (sentiment, macro context, agent disagreement) that individual I7 plugins do not see. This is a post-selection overlay — it can reduce confidence but cannot change which signal was selected as the winner.

### Feedback mechanisms (CUSUM + shadow gate)

The pipeline includes two adaptive feedback loops that operate over longer time horizons than the per-bar stage sequence.

**CUSUM Monitor** — Cumulative sum control charts track win rate per setup continuously. When a setup's win rate degrades beyond the CUSUM threshold, its `perf_multiplier` is automatically reduced; when win rate recovers, the multiplier is restored. This gives the ranking system a real-time quality signal without waiting for the 30-day rolling window to catch up.

**Shadow mode gate** — Every plugin is auto-enrolled in `shadow_registry` at startup. Shadow signals traverse the full pipeline and generate outcomes in `signal_events` (`is_shadow=TRUE`) but are excluded from `select_winner()` — they never reach the execution stream.

Promotion to live: `n >= 100` AND `bootstrap_ci_lower(pnl_r) > 0.0` (statistically positive expected value at 95% confidence). Demotion back to shadow: `EV[R] < -0.05` for 3 consecutive evaluation cycles. The gate enforces that every live plugin has demonstrated edge under real market conditions, not just backtested conditions.

---

## Trade Geometry: How stop_loss and targets Are Computed

`stop_price` and `target_price` are computed by `src/intelligence/trading/trade_framer.py` via `frame_trade()`, called by every I7 plugin before it emits a signal. Once written to `trade_frames`, these values are immutable — they represent the trade geometry at the moment of signal fire.

### Stop resolution

Stop levels are resolved from a structural hierarchy — each level is tried in order; the first valid level wins:

```
FVG gap edge → demand/supply zone proximal → sweep level → order block → swing high/low → EMA → S/R level → ATR fallback
```

The ATR fallback (`entry ± atr * 0.50`) is the last resort. Every stop above it is a structural level with market meaning.

### Adaptive ATR buffer (`_adaptive_buffer`)

All ATR-based buffer distances — for both stops and targets — are scaled through `_adaptive_buffer(features, base_mult, regime_type)` rather than using raw ATR multiples.

```
base_mult × garch_mult × hurst_tighten × shock_floor, capped at ADAPTIVE_BUFFER_HARD_CAP (1.40)
```

**GARCH scaling (continuous):** `garch_vol_ratio` (ratio of current GARCH sigma to historical baseline) is clipped to `[0.70, 1.50]` and mapped piecewise-linearly through three calibrated anchors:

| vol_ratio | garch_mult |
|-----------|------------|
| 0.70 | 0.80 |
| 1.00 | 1.00 |
| 1.50 | 1.35 |

Transitions between anchors are linear — no discrete regime cliff.

**Hurst tightening (confirmation only):** When the Hurst exponent confirms the signal's regime type, structural levels are more reliable and the buffer narrows by up to 8%. Hurst never widens — it is already upstream in the regime gate, so widening would double-count.

- Trend signal + H ≥ 0.55 → tighten by up to `(H - 0.55) × 0.16`
- Mean-reversion signal + H ≤ 0.45 → tighten by up to `(0.45 - H) × 0.16`
- Conflict (e.g. trend signal in low-Hurst market) → no adjustment

**Shock floor:** A single extreme bar (`garch_shock > 3.0`) forces the buffer to at least `base_mult × 1.35` (regime-2 anchor), regardless of the sustained regime classification. Guards against GARCH regime lag on shock bars.

**Fallback:** If `garch_vol_ratio` is missing (GARCH not yet warmed up), `garch_mult` defaults to 1.00.

### Target candidates

Target candidates are gathered by `_collect_target_candidates()` and filtered through an ATR range gate (`entry + atr×0.5 < candidate < entry + atr×max_mult`). All of the following are considered:

| Source | Fields | Gate |
|--------|--------|------|
| Volume Profile | `poc_price`, `vah`, `val` (session VP); rolling variants | VP proximity logic |
| Nearest structure | `nearest_resistance` / `nearest_support` | Direction-aware |
| VWAP bands | `vwap_upper_band` / `vwap_lower_band` | Direction-aware |
| **Weekly pivots** | `weekly_r1`, `weekly_r2` (long); `weekly_s1`, `weekly_s2` (short) | ATR range only |
| **Fibonacci cluster** | `nearest_fib_level` | `fib_cluster_strength >= 0.5` (lone levels excluded) |
| **Asian session H/L** | `asian_session_high` / `asian_session_low` | Direction-aware + ATR range |
| **AVWAP bands** | `avwap_upper_band` / `avwap_lower_band` | Direction-aware |

**Bold** rows are institutional levels — all computed upstream in I3/I4 and fed in via `features`. The ATR range filter prevents a distant weekly pivot from appearing as T1 on a small daily range.

`_pick_targets()` selects T1/T2/T3 from the candidate list by RR threshold.

---

## How To Extend

### Adding a new entry_type

1. Add the value string to the trade framer (`src/intelligence/trading/trade_framer.py`) where entry logic is resolved.
2. Update `make_signal()` in `signal_schema.py` if it needs default handling.
3. Update this doc and `signals-lifecycle.md`.
4. No schema migration needed — `entry_type` is TEXT.

### Adding a new field to trade_frames

1. Write a migration: `db/migrations/NNN_add_trade_frame_field.sql`.
2. Update the `TradeFrame` dataclass in the relevant persistence module.
3. Update `SignalWriter` to populate the field at write time.
4. If the field is relevant for ML training, verify the training query in `signal_metrics_compute_agent.py` selects it.

### Adding a new field to trade_executions

1. Write a migration: `db/migrations/NNN_add_execution_field.sql`.
2. Update `_EXECUTION_INSERT_SQL` in `signal_ledger_repository.py`.
3. Update the `Execution` dataclass in `lifecycle_tracker.py` if the field flows through the transition object.
4. Update `_transition_to_lifecycle()` in `signal_tracker_compute_agent.py` to populate the field.

### Schema migration protocol (signal_schema_version bump)

When signal geometry or required fields change in a backward-incompatible way:

1. Increment `SIGNAL_SCHEMA_VERSION` in `src/intelligence/trading/signal_schema.py`.
2. Write a migration that handles existing rows.
3. Update all queries that gate on `signal_schema_version` — search for `SIGNAL_SCHEMA_VERSION` across the codebase.
4. Document what changed and why old-version data is excluded in the migration file header.

---

## Failure Modes & Operations

### Signals stuck in pending — diagnostic queries

```sql
-- Pending signal_events older than 1 hour that have not expired
SELECT se.signal_id, se.symbol, se.tf, se.setup_plugin, se.ts,
       se.expires_at, se.status
FROM signal_events se
WHERE se.status = 'pending'
  AND se.ts < NOW() - INTERVAL '1 hour'
  AND se.expires_at > NOW()
ORDER BY se.ts ASC;
```

Common causes: price never entered the entry zone (normal for `at_pullback`/`at_limit` types). Check `frame_details` on `trade_frames` for `entry_zone_low`/`entry_zone_high` vs. current price.

### Frames missing counterfactual_pnl_r

```sql
-- trade_frames past their expiry with no counterfactual measured
SELECT tf.frame_id, tf.signal_id, tf.entry_type, tf.expires_at,
       tf.counterfactual_pnl_r
FROM trade_frames tf
WHERE tf.counterfactual_pnl_r IS NULL
  AND tf.expires_at < NOW() - INTERVAL '1 hour'
ORDER BY tf.expires_at ASC;
```

If CounterfactualTracker is running but this query has results, check `counterfactual_tracker.log` for errors. Each frame should have counterfactual data within one evaluation cycle after `expires_at`.

### NULL expires_at (data integrity)

```sql
SELECT COUNT(*)
FROM signal_events
WHERE expires_at IS NULL
  AND status IN ('pending', 'active');
```

`expires_at IS NULL` signals cannot be TTL-expired by the replay auditor. These are data-integrity bugs from backfill or pre-SLA rows. The OTel metric `signal_lifecycle_null_expires_at_total` fires for each bar where a NULL `expires_at` signal is evaluated.

---

## See Also

- `docs/concepts/signal-ledger-architecture.md` — WHY the three-table design; the survivorship bias problem it solves
- `docs/signals/signals-lifecycle.md` — full signal state machine and transition logic
- `docs/signals/signals-operations.md` — operating and debugging the lifecycle services
- `docs/intelligence/intelligence-foundation.md` — I7 signal generation and aggregator logic
- `db/migrations/137_3table_schema.sql` — complete DDL for all three tables and signal_ledger_full view
- `src/intelligence/trading/signal_schema.py` — `SIGNAL_SCHEMA_VERSION`, `make_signal_from_frame()`, `REQUIRED_SIGNAL_FIELDS`
- `src/intelligence/pipeline/signal_processor.py` — `was_selected`, `is_shadow` stamping logic
