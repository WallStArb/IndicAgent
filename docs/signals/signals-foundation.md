# Signals Foundation — Why signal_ledger exists and what it owns

**Version:** 2.8.0 | **Status:** Operational | **Last Updated:** 2026-05-29

---

## Purpose

`signal_ledger` is the persistent record of every I7 trading setup detected by the intelligence pipeline, including its full lifecycle outcome. It solves three problems that ephemeral in-memory state cannot:

1. **Labeled training data** — The ML scoring model (Phase 094+) needs feature vectors paired with real-world outcomes. `signal_ledger` is that dataset: every row links back to `intelligence_features` via `(symbol, feature_ts, feature_tf)` and carries the 8-class outcome label once the trade closes.
2. **Lifecycle recovery** — Service restarts, data gaps, and replay scenarios all need a durable record of which signals were pending or active. The `SignalTrackerComputeAgent` bootstraps from this table on startup.
3. **Audit trail** — Every I7 plugin fires, whether or not it eventually enters a zone. Every regime-suppressed signal is logged. This creates an empirical feedback loop for gate calibration (regime gates, shadow promotion, CIS weight tuning).

**Who reads this doc:** Engineers building new signal types, debugging lifecycle issues (why did signal X never activate?), or writing ML training queries. Start here before touching `signal_ledger` schema or any lifecycle service.

---

## Design Principles

### Why signal_ledger instead of ephemeral in-memory state?

The real-time pipeline (`SignalTrackerComputeAgent`) is intentionally DB-ignorant — it holds all active signal state in memory and publishes `LifecycleTransition` events to Kafka. The `LifecycleWriterAgent` consumes those events and writes to `signal_ledger`. This split exists because DB I/O is unpredictable and the hot path cannot block on it.

`signal_ledger` is the persistent projection of that in-memory state. It persists because:
- Service restarts would lose all pending signal state otherwise
- Historical outcomes are required for ML training (you cannot reconstruct them from bar data alone)
- The replay auditor (`SignalReplayAuditorAgent`) needs to find signals the live tracker missed

### Two-table design: signal_ledger + signal_outcomes

Originally one table; Phase 104 / migration 093 extracted mutable lifecycle state into a separate `signal_outcomes` table to reduce write amplification — every bar update to `status`, `mae`, `mfe` no longer rewrites the fire-time columns that never change.

Signal data splits into two tables joined via `signal_id`:

- **`signal_ledger`** — fire-time fields, written once at signal emission, never updated. These describe *what the signal was* at the moment I7 fired: `symbol`, `timeframe`, `direction`, `entry_price`, `stop_loss`, `targets`, `entry_zone_low`, `entry_zone_high`, `expires_at`, `signal_schema_version`.
- **`signal_outcomes`** — mutable lifecycle state: `status`, `activated_at`, `exit_at`, `outcome`, `pnl_r`, `mae`, `mfe`, `bars_in_trade`, and all exit fields. Written progressively: first seeded as `pending`, then updated on activation, then again on exit.

The `signal_ledger_full` view joins both tables and is the canonical query surface for all reads.

### Why is feature_ts part of the JOIN key?

`feature_ts` is the bar timestamp at which the intelligence pipeline computed the features that generated the signal. It is distinct from `timestamp` (signal fire time) because signals may be computed slightly after the bar closes due to pipeline latency. The JOIN `f.ts = s.feature_ts AND f.timeframe = s.feature_tf` is what allows you to retrieve the exact feature vector present at signal generation time — essential for ML training.

### was_selected vs is_shadow

Both fields exist and serve different purposes:

- **`was_selected`** (`BOOLEAN`) — `TRUE` for the single signal the aggregator picked as the winner on that bar (highest-ranked regime-eligible, non-shadow signal). Only one signal per bar per symbol/timeframe can be `was_selected=TRUE`. This flag gates the `SignalMetricsComputeAgent` query (`WHERE was_selected = true`) — metrics are only computed for signals that were actually presented for potential execution.
- **`is_shadow`** (`BOOLEAN`) — `TRUE` for signals from plugins that are in shadow mode (not yet promoted in `shadow_registry`). Shadow signals fire and are tracked in full (lifecycle, MAE/MFE, outcome) but never enter the execution stream. They accumulate outcome data toward the promotion gate (`n >= 100 AND bootstrap_ci_lower(pnl_r) > 0.0`).

A signal can be `is_shadow=TRUE` and still get an outcome. A signal can be `was_selected=FALSE` and still be live (it fired but wasn't the winner). The two flags are orthogonal.

### Why signal_schema_version as a canonical constant?

`SIGNAL_SCHEMA_VERSION = "v1"` is defined in `src/intelligence/trading/signal_schema.py` and imported everywhere — no hardcoded strings. Before Phase 79 (v0 signals), entry zone geometry was incorrect: zones were zero-width or had wrong `entry_price` for pullback/limit entry types. The Phase 83 migration truncated all v0 data.

All ML training queries gate on `signal_schema_version = 'v1'`. If schema issues are discovered again, the version bumps and all downstream queries can be updated by changing a single constant. This is why it must never be a raw string literal in query code.

### entry_type values — what each means

`entry_type` describes how the signal's entry price was resolved from market structure:

| Value | Meaning | When used |
|-------|---------|-----------|
| `at_close` | Entry at the current bar close | Default. Used by most setups where entry is immediate (momentum, candlestick, supply/demand) |
| `at_pullback` | Entry at a structural pullback level (nearest support/resistance) | Trend and MTF alignment setups — entry isn't here yet, wait for retrace |
| `at_limit` | Entry at a specific structural level (swing high/low, BB middle) | Momentum breakout, squeeze expansion, VWAP deviation — limit order approach |
| `at_reclaim` | Entry at the current close after a sweep/reclaim event | Liquidity sweep and liquidity hunt setups — confirmation that price reclaimed the level |
| `zone_proximal` | Entry at the proximal edge of a supply/demand zone | Supply/demand setups where the zone has geometric extent |

`entry_type` is stored in `signal_ledger` (restored by migration 095) and used by `SignalMetricsComputeAgent` to segment performance by entry style — `at_pullback` setups have structurally different activation rates than `at_close`.

---

## Architecture

### Signal flow: I7 to signal_ledger

```
I7 plugins (36 setups) + CISScorer aggregator
  → IntelligencePipelineAgent (_process_i7)
  → signal_processor.py (rank, regime gate, shadow gate, select winner)
  → intelligence.i7.signals Kafka topic  (full ranked list per bar)
  → SignalWriterAgent
  → signal_ledger INSERT + signal_outcomes seed (status='pending')
```

NULL `entry_zone_low` or `entry_zone_high` routes the signal to the DLQ at write time — it never enters lifecycle tracking.

### What reads signal_ledger

`signal_ledger` is a hub, not a queue. Multiple services read it for different purposes:

| Service | What it reads | Why |
|---------|--------------|-----|
| `SignalTrackerComputeAgent` | `pending`/`active` signals with `exit_at IS NULL` | Bootstrap on startup; populates in-memory active index |
| `SignalReplayAuditorAgent` | `pending`/`active` with `expires_at < NOW()` | Recover outcomes for signals the live tracker missed |
| `SignalMetricsComputeAgent` | Resolved signals (`outcome IS NOT NULL`) where `was_selected=true` | Compute per-setup performance metrics every 15 min |
| `GraduationComputeAgent` | Shadow signals with `outcome IS NOT NULL`, `is_shadow=true` | Evaluate promotion gate for shadow plugins |
| ML training queries | All `v1` signals with `outcome IS NOT NULL` | Feature-label pairs for model training |

---

## Data Contracts

### signal_ledger (fire-time, immutable)

| Column | Type | Description |
|--------|------|-------------|
| `signal_id` | UUID | Primary key |
| `timestamp` | TIMESTAMPTZ | Signal fire time (bar_ts at I7 computation). **Primary time column.** |
| `symbol` | TEXT | Instrument symbol (e.g. `ESM6`) |
| `timeframe` | TEXT | Bar timeframe (e.g. `1m`, `5m`, `15m`, `1h`) |
| `setup_plugin` | TEXT | I7 plugin that fired (e.g. `momentum_breakout_long`) |
| `signal_type` | TEXT | Human-readable type string |
| `direction` | INTEGER | `1` = long, `-1` = short |
| `was_selected` | BOOLEAN | `TRUE` if this was the aggregator winner on this bar |
| `is_shadow` | BOOLEAN | `TRUE` if plugin is in shadow mode (not yet promoted) |
| `is_backfill` | BOOLEAN | `TRUE` if signal was generated from replay, not live |
| `signal_schema_version` | TEXT | Schema version tag. `'v1'` = post-Phase-79 quality signals |
| `feature_ts` | TIMESTAMPTZ | Bar timestamp in `intelligence_features` for ML JOIN |
| `feature_tf` | TEXT | Timeframe in `intelligence_features` for ML JOIN |
| `hmm_regime_at_fire` | INTEGER | HMM regime state when signal fired (0=ranging, 1/2=trend) |
| `garch_sigma_at_fire` | FLOAT | GARCH volatility estimate at fire time (staleness baseline) |
| `ttl_bars` | INTEGER NOT NULL DEFAULT 10 | How many bars until the signal expires if never activated |
| `expires_at` | TIMESTAMPTZ | Pre-computed TTL timestamp: `signal_ts + ttl_bars * tf_seconds` |
| `entry_price` | NUMERIC | Resolved entry price (post-TradeFramer) |
| `stop_loss` | NUMERIC | Initial stop level |
| `targets` | JSONB | List of profit target prices |
| `entry_zone_low` | NUMERIC | Lower bound of zone; NULL routes to DLQ at write time |
| `entry_zone_high` | NUMERIC | Upper bound of zone; NULL routes to DLQ at write time |
| `market_entry_price` | NUMERIC | At-close bar price for parallel market-entry track |
| `cis_score` | FLOAT | CISScorer output (0-1) |
| `bucket_scores` | JSONB | Per-bucket CIS score breakdown (`{"trend": 0.7, "momentum": 0.5, ...}`) |
| `weights_version` | INTEGER | CIS weight version at signal fire time (tracks which weight set produced the score) |
| `pipeline_lag_ms` | FLOAT | Time from bar close to signal emission (observability) |
| `signal_computed_at` | TIMESTAMPTZ | When the pipeline computed this signal |

### signal_outcomes (lifecycle state, mutable)

| Column | Type | Description |
|--------|------|-------------|
| `signal_id` | UUID | FK to signal_ledger |
| `status` | TEXT | `'pending'`, `'active'`, `'regime_suppressed'`, `'expired'` — raw strings |
| `activated_at` | TIMESTAMPTZ | When price entered the entry zone (NULL until activation) |
| `activation_price` | FLOAT | Actual activation price within zone |
| `zone_entry_pct` | FLOAT | Where in zone price entered: `0.0` = proximal, `1.0` = distal |
| `bars_to_activation` | INTEGER | Bars elapsed from signal fire to activation |
| `exit_at` | TIMESTAMPTZ | When the signal exited. **Column is `exit_at`, NOT `exit_ts`.** |
| `exit_price` | FLOAT | Exit price |
| `exit_reason` | TEXT | `stop_loss`, `target_1`, `target_2`, `ttl_expired`, `chandelier_stop`, `condition_expired` |
| `outcome` | TEXT | 8-class outcome label (see Lifecycle doc) |
| `pnl_r` | FLOAT | P&L in risk units (1R = 1x the initial stop distance) |
| `mae` | FLOAT | Maximum adverse excursion in pnl_r units |
| `mfe` | FLOAT | Maximum favorable excursion in pnl_r units |
| `bars_in_trade` | INTEGER | Active bars from activation to exit |
| `trailing_stop_price` | JSONB | Chandelier trailing stop state history |
| `staleness_score` | FLOAT | Composite staleness score on last bar (0.0-1.0) |

### Primary key and JOIN pattern

```sql
-- signal_ledger PK: (signal_id, timestamp)
-- signal_outcomes PK: signal_id

-- Canonical JOIN for ML training:
SELECT f.*, s.outcome, s.pnl_r, s.mae, s.mfe, s.bars_in_trade
FROM intelligence_features f
JOIN signal_ledger_full s
  ON f.symbol = s.symbol
 AND f.ts     = s.feature_ts
 AND f.timeframe = s.feature_tf
WHERE s.outcome IS NOT NULL
  AND s.signal_schema_version = 'v1';
```

`signal_ledger_full` is a view that joins `signal_ledger` and `signal_outcomes`. Always query through the view, not the raw tables. The view DDL is defined in `production/migrations/095_signal_ledger_split.sql`.

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

`cis_score` and `bucket_scores` are written to `signal_ledger` at fire time and are immutable — they reflect the market state at the moment of signal generation, not any later recalibration.

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

`select_winner()` picks the regime-eligible signal with the highest `adjusted_rank` (lowest numeric value under ascending sort). Tiebreaking: higher `confidence` wins. The winner is the single signal marked `was_selected=TRUE` in `signal_ledger`. All other signals on that bar are written with `was_selected=FALSE`.

### Swarm overlay

After winner selection, the alpha swarm (`AlphaSwarm`) applies a `swarm_multiplier` derived from a mixture-of-agents (MoA) composite across 5 alpha swarm agents:

```
adjusted_confidence = calibrated_confidence × swarm_multiplier
```

The swarm evaluates the selected signal against additional dimensions (sentiment, macro context, agent disagreement) that individual I7 plugins do not see. This is a post-selection overlay — it can reduce confidence but cannot change which signal was selected as the winner.

### Feedback mechanisms (CUSUM + shadow gate)

The pipeline includes two adaptive feedback loops that operate over longer time horizons than the per-bar stage sequence. These are not per-signal transformations — they update the weights and eligibility state that the per-bar stages consume.

**CUSUM Monitor** — Cumulative sum control charts track win rate per setup continuously. When a setup's win rate degrades beyond the CUSUM threshold, its `perf_multiplier` is automatically reduced; when win rate recovers, the multiplier is restored. This gives the ranking system a real-time quality signal without waiting for the 30-day rolling window to catch up.

**Shadow mode gate** — Every plugin is auto-enrolled in `shadow_registry` at startup. Shadow signals traverse the full pipeline and generate outcomes in `signal_ledger` (`is_shadow=TRUE`) but are excluded from `select_winner()` — they never reach the execution stream.

Promotion to live: `n >= 100` AND `bootstrap_ci_lower(pnl_r) > 0.0` (statistically positive expected value at 95% confidence). Demotion back to shadow: `EV[R] < -0.05` for 3 consecutive evaluation cycles. The gate enforces that every live plugin has demonstrated edge under real market conditions, not just backtested conditions.

---

## How To Extend

### Adding a new entry_type

1. Add the value string to the trade framer (`src/intelligence/trading/trade_framer.py`) where entry logic is resolved.
2. Update `make_signal()` in `signal_schema.py` if it needs default handling.
3. Update this doc and `signals-lifecycle.md`.
4. No schema migration needed — `entry_type` is TEXT.

### Adding a new outcome field to signal_outcomes

1. Write a migration: `db/migrations/NNN_add_signal_outcome_field.sql`.
2. Update `_BATCH_EXIT_SQL` and the `batch_execute("exit", ...)` params in `signal_ledger_repository.py`.
3. Update the `Transition` dataclass in `lifecycle_tracker.py` if the field must flow through the transition object.
4. Update `_transition_to_lifecycle()` in `signal_tracker_compute_agent.py` to populate the field.
5. If the field is relevant for ML training, verify the query in `signal_metrics_compute_agent.py` selects it.

### Schema migration protocol (signal_schema_version bump)

When signal geometry or required fields change in a backward-incompatible way:

1. Update `SIGNAL_SCHEMA_VERSION` in `src/intelligence/trading/signal_schema.py` (e.g., `'v1'` → `'v2'`).
2. Write a migration that handles existing rows (truncate contaminated data if necessary — see Phase 83 precedent).
3. Update all queries that gate on `signal_schema_version` — search for `signal_schema_version` across the codebase.
4. The replay auditor query already gates on `SIGNAL_SCHEMA_VERSION` via the Python constant, so it picks up the new version automatically.
5. Document what changed and why v_old data is excluded in the migration file header.

---

## Failure Modes & Operations

### Signals stuck in pending — diagnostic queries

```sql
-- All pending signals older than 1 hour that have not expired
SELECT signal_id, symbol, timeframe, setup_plugin, timestamp,
       expires_at, entry_zone_low, entry_zone_high, status
FROM signal_ledger_full
WHERE status = 'pending'
  AND exit_at IS NULL
  AND timestamp < NOW() - INTERVAL '1 hour'
  AND expires_at > NOW()
ORDER BY timestamp ASC;
```

Common causes: price never entered the entry zone (normal for `at_pullback`/`at_limit` types), the entry zone was set too far from current price. Check `entry_zone_low`/`entry_zone_high` vs the current bar's price range.

### Signals activated but no exit

```sql
-- Active signals with activation but no exit
SELECT signal_id, symbol, timeframe, activated_at, mae, mfe, bars_in_trade
FROM signal_ledger_full
WHERE status = 'active'
  AND exit_at IS NULL
  AND activated_at IS NOT NULL
  AND activated_at < NOW() - INTERVAL '2 hours'
ORDER BY activated_at ASC;
```

If `expires_at` is in the past, the replay auditor should resolve these within its next 5-minute cycle. If not, check `signal_replay_unresolved_gauge` in Grafana and run the replay auditor manually.

### NULL expires_at (data integrity alert D-17)

```sql
SELECT COUNT(*) FROM signal_ledger_full
WHERE expires_at IS NULL AND status IN ('pending', 'active') AND exit_at IS NULL;
```

`expires_at IS NULL` signals cannot be TTL-expired by the replay auditor (it filters `expires_at IS NOT NULL`). These are data-integrity bugs from backfill or pre-Phase-107.5 rows. The OTel metric `signal_lifecycle_null_expires_at_total` fires for each bar where a NULL `expires_at` signal is evaluated.

---

## See Also

- `docs/signals/signals-lifecycle.md` — full signal state machine and transition logic
- `docs/signals/signals-operations.md` — operating and debugging the three lifecycle services
- `docs/intelligence/intelligence-foundation.md` — I7 signal generation and aggregator logic
- `docs/data/data-streaming.md` — Signal Kafka topics — see Data Streaming
- `src/intelligence/trading/signal_schema.py` — `make_signal_from_frame()`, `validate_signal()`, `REQUIRED_SIGNAL_FIELDS`
- `src/persistence/repository/signal_ledger_repository.py` — `LedgerEntry`, all SQL
- `src/intelligence/pipeline/signal_processor.py` — `was_selected`, `is_shadow` stamping logic
