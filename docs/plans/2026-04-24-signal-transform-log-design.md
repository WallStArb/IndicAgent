# Signal Transform Log — Unified Alpha Modifier Architecture

**Date:** 2026-04-24
**Status:** Approved
**Phases affected:** 66 (swarm agents), future ML phases
**Tables added:** `signal_transform_log`, `transform_graduation`
**Tables deprecated:** `alpha_multiplier_shadow` (absorbed via view in Phase 3)
**New services:** `GraduationComputeAgent`, `GraduationWriterAgent`
**New Kafka topics:** `intelligence.transform.graduation`, `intelligence.transform.graduation.dlq`

---

## Problem

Nine transforms modify signal confidence between I7 plugin output and winner selection. Six of them (hurst quality, drift penalty, regime gate, TOD, isotonic calibration, performance weighting) mutate `confidence` in-place with no traceability. Three (swarm agents) write to a separate `alpha_multiplier_shadow` table.

You cannot answer: "Does the Hurst quality gate actually improve Sharpe?" or "What would happen if we removed TOD?" because intermediate values are destroyed by the next mutation step.

This violates three Renaissance principles:
- **Earn the right through proof** — no transform has statistically proven it adds alpha
- **Never drop data that could contain signal** — intermediate confidence values are lost forever
- **Segment relentlessly** — evaluation is global, not per-regime or per-timeframe

## Design Principles

1. **Every transform is an independent, evaluable hypothesis.** Each one must prove it adds alpha before affecting the live pipeline.
2. **The original signal is immutable.** `signal_ledger.confidence` stays as the raw I7 plugin output. All modifications are additive rows in a separate table.
3. **One table, one pattern.** Math transforms and LLM evaluators use the same storage model. `alpha_multiplier_shadow` is absorbed.
4. **Graduation is per-segment and temporary.** A transform that works in trending 5m might not work in ranging 1h. Graduation expires every 90 days — must re-prove.
5. **Validation is event-driven, not clock-driven.** The graduation evaluator fires when lifecycle transitions produce new resolved signals, not on a timer. Renaissance principle: compute only when there's new information.
6. **Renaissance-grade validation dimensions.** No binarization, no Pearson on fat tails. Six dimensions: Spearman rank, calibration, expected shortfall, per-segment power analysis, walk-forward, Sharpe value-add.

## Schema

### signal_transform_log

Every transform writes exactly one row per signal. Batch writes via asyncpg executemany, same pattern as existing ShadowRecorder.

```sql
CREATE TABLE signal_transform_log (
    ts                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    signal_id         UUID NOT NULL,
    transform_id      TEXT NOT NULL,
    transform_version TEXT NOT NULL DEFAULT 'v1',
    dag_order         SMALLINT NOT NULL,
    segment_key       TEXT NOT NULL DEFAULT '__global__',
    multiplier        FLOAT NOT NULL,
    metadata          JSONB,
    is_shadow         BOOLEAN NOT NULL DEFAULT TRUE
);

SELECT create_hypertable('signal_transform_log', 'ts');

CREATE UNIQUE INDEX idx_stl_identity
    ON signal_transform_log (signal_id, transform_id, transform_version);

CREATE INDEX idx_stl_eval
    ON signal_transform_log (transform_id, segment_key, ts);
```

### Column Rationale

| Column | Why first-class | Who uses it |
|--------|----------------|-------------|
| `ts` | Hypertable partitioning | TimescaleDB chunk management |
| `signal_id` | JOIN to signal_ledger for outcome matching | Every evaluation query |
| `transform_id` | Identifies which hypothesis | Graduation, composition, A/B |
| `transform_version` | Version coexistence for A/B comparison | Version transitions |
| `dag_order` | Execution order for replay and debugging | Pipeline reconstruction |
| `segment_key` | Per-segment graduation requires indexed grouping | Graduation queries |
| `multiplier` | The transform's alpha assessment | Composition and evaluation |
| `metadata` | Transform-specific context | Research queries |
| `is_shadow` | Write-time snapshot | Research queries |

### transform_graduation

Tracks statistical evidence for each transform per segment across 6 Renaissance-grade dimensions. Evaluated by the event-driven `GraduationComputeAgent`.

```sql
CREATE TABLE transform_graduation (
    transform_id      TEXT NOT NULL,
    transform_version TEXT NOT NULL,
    segment_key       TEXT NOT NULL,
    n                 INT NOT NULL,
    -- Dimension 1: Spearman rank correlation (robust to fat tails)
    spearman_rho      FLOAT,
    spearman_p        FLOAT,
    -- Dimension 2: Calibration (predicted vs actual across deciles)
    calibration_max_error FLOAT,
    -- Dimension 3: Expected Shortfall (CVaR at bottom decile)
    cvar_bottom_decile FLOAT,
    -- Dimension 4: Per-segment power analysis
    mde               FLOAT,
    -- Dimension 5: Walk-forward (temporal 70/30 split)
    val_rho           FLOAT,
    overfitting_risk  BOOLEAN,
    -- Dimension 6: Value-add (Sharpe improvement from filtering)
    sharpe_delta      FLOAT,
    -- Verdict
    is_graduated      BOOLEAN NOT NULL DEFAULT FALSE,
    evaluated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at        TIMESTAMPTZ NOT NULL,
    UNIQUE (transform_id, transform_version, segment_key)
);
```

All 6 dimensions as separate columns — queryable, no JSONB for graduation decisions.

### Graduation Gate Criteria

A transform graduates for a given `(transform_id, version, segment_key)` only when ALL of:

| Dimension | Gate | Why |
|-----------|------|-----|
| Spearman ρ | `rho >= 0.15` | Positive = high multiplier correlates with high pnl_r. Uses ranks, robust to fat tails. |
| Calibration | `max_error < 0.10` | Predicted failure rate within 10pp of actual across decile buckets. |
| Expected Shortfall | `cvar <= -0.5` | Bottom multiplier decile (worst-rated signals) must have negative avg pnl_r. |
| Per-segment power | `N >= 30 AND abs(rho) >= mde` | Sufficient sample AND effect size above minimum detectable effect. |
| Walk-forward | `val_rho` passes Spearman gate | Out-of-sample must hold — no overfitting tolerance. |
| Value-add | `sharpe_delta > 0` | Filtering on this transform must improve risk-adjusted returns. |

Gate constants defined in `src/intelligence/swarm/graduation.py` — single source of truth, importable by compute agent and CLI script.

## Transform Registry

Current transforms mapped to the unified model:

| dag_order | transform_id | Source | multiplier semantics | metadata contents |
|-----------|-------------|--------|---------------------|-------------------|
| 0 | `hurst_quality` | quality_gate.py | min(hurst_q, entropy_q) | `{"hurst_q": 0.72, "entropy_q": 0.81, "hurst_type": "trend"}` |
| 1 | `drift_penalty` | quality_gate.py | KS drift state | `{"drift_state": "none", "penalty": 1.0}` |
| 2 | `regime_gate` | aggregator.py | 1.0 (pass) or 0.0 (suppressed) | `{"hmm_regime": 1, "prob": 0.8, "reason": null}` |
| 3 | `tod` | tod_adjuster.py | Bayesian TOD multiplier | `{"tod_multiplier": 1.1, "hour_et": 9, "regime_type": "trend"}` |
| 4 | `isotonic` | calibrator.py | calibration ratio | `{"raw_confidence": 0.7, "calibrated_confidence": 0.58}` |
| 5 | `perf_weight` | ranker.py | setup_performance multiplier | `{"perf_multiplier": 0.85, "sample_size": 45}` |
| 6 | `swarm_skeptic` | skeptic_agent.py | (1 - failure_prob) * llm_conf | `{"failure_probability": 0.3, "llm_confidence": 0.8, "prompt_version": "skeptic_v1", "cost_tokens": 450}` |
| 7 | `swarm_correlation` | correlation_agent.py | (1 - failure_prob) * llm_conf | `{"failure_probability": 0.25, "llm_confidence": 0.7, "lead_symbol": "ES", "cost_tokens": 380}` |
| 8 | `swarm_volume` | volume_agent.py | (1 - failure_prob) * llm_conf | `{"failure_probability": 0.2, "llm_confidence": 0.85, "cost_tokens": 410}` |

Future transforms (ML scoring model, additional swarm agents) add new transform_id values — no schema changes.

## Segmentation

Graduation is evaluated per `(transform_id, transform_version, segment_key)`:

| Transform | segment_key pattern | Example |
|-----------|-------------------|---------|
| hurst_quality | `{regime_type}.{tf}` | `trend.5m`, `mean_reversion.1h` |
| drift_penalty | `{regime_type}.{tf}` | `trend.5m` |
| regime_gate | `{regime_type}` | `trend`, `mean_reversion` |
| tod | `{regime_type}.{tf}.{hour}` | `trend.5m.9`, `mean_reversion.1h.14` |
| isotonic | `{plugin}.{tf}` | `trad_TrendFollowing.5m` |
| perf_weight | `{plugin}.{tf}` | `trad_SqueezeExpansion.15m` |
| swarm_* | `{hmm_regime}.{tf}` | `trending_up.5m`, `ranging.1h` |

Global transforms use `__global__`.

## Event-Driven Graduation Pipeline

### Architecture

```
SignalTracker publishes EXIT transitions → topic_lifecycle_transitions
    ↓ (existing, unchanged)
LifecycleWriterAgent persists to signal_ledger (existing, unchanged)
    ↓ (same topic, different consumer group)
GraduationComputeAgent consumes lifecycle transitions
    Maintains per-(transform_id, segment_key) counter of new resolved signals
    When any counter hits threshold (20 new resolutions):
        → Queries signal_transform_log JOIN signal_ledger (rolling 90d window)
        → Runs 6 Renaissance dimensions via src/intelligence/swarm/graduation.py
        → Publishes GraduationResult to topic_transform_graduation
    Counter resets for that (transform, segment) pair
    ↓
GraduationWriterAgent consumes topic_transform_graduation
    → Upserts into transform_graduation table
```

### Why Event-Driven (Not Timer)

Renaissance principle: compute only when there's new information. A model's quality doesn't change minute-to-minute — it changes when signals resolve with pnl_r outcomes. The lifecycle transitions topic already fires per resolved signal. The graduation agent fires when it accumulates enough new data to warrant re-evaluation.

### GraduationComputeAgent

**Service file:** `services/graduation_compute_agent.py`
**Systemd unit:** `indicagent-graduation-compute.service` (always-on)
**Consumer group:** `graduation_compute_group`
**Metrics port:** 9135
**DLQ:** `topic_transform_graduation_dlq`

**Internal logic:**

1. On startup: query `transform_graduation` to get last `evaluated_at` per `(transform_id, segment_key)`. Count how many signals have resolved since then. Sets initial counters.
2. On each consumed `EXIT` transition:
   - Parse `signal_id` from the transition payload
   - Query `signal_transform_log` for all transform rows matching that `signal_id`
   - For each `(transform_id, segment_key)`, increment in-memory counter
   - If any counter >= 20: trigger evaluation for that segment
3. Evaluation (per segment):
   - Query `signal_transform_log` JOIN `signal_ledger` for rolling 90d, filtered to this `(transform_id, segment_key)`
   - Run 6 Renaissance dimensions via pure functions in `graduation.py`
   - Publish `GraduationResult` dict to Kafka topic
   - Reset counter to 0
4. On teardown: flush any pending evaluations, drain producer

**State recovery on restart:** The agent re-counts from `transform_graduation.evaluated_at`. If no row exists for a (transform, segment), it counts from 90 days ago. In-memory counters are ephemeral — all durable state is in DB.

### GraduationWriterAgent

**Service file:** `services/graduation_writer_agent.py`
**Systemd unit:** `indicagent-graduation-writer.service` (always-on)
**Consumer group:** `graduation_writer_group`
**Metrics port:** 9136
**DLQ:** `topic_transform_graduation_dlq`

Follows `BaseWriterAgent` pattern exactly: consume → parse → buffer → batch upsert to `transform_graduation`. No compute — pure persistence.

### Kafka Topics

**New topics** (added to `src/core/stream_keys.py`):

```python
def topic_transform_graduation(env_name: str) -> str:
    """Graduation evaluation results from GraduationComputeAgent."""
    return f"{env_prefix(env_name)}intelligence.transform.graduation"

def topic_transform_graduation_dlq(env_name: str) -> str:
    """DLQ for graduation writer."""
    return f"{env_prefix(env_name)}intelligence.transform.graduation.dlq"
```

**Existing topic consumed** (no changes):

```python
def topic_lifecycle_transitions(env_name: str) -> str:
    """Signal lifecycle state transitions (activation, exit, mae/mfe updates)."""
    return f"{env_prefix(env_name)}lifecycle.transitions"
```

### GraduationResult Payload

```python
{
    "transform_id": "swarm_skeptic",
    "transform_version": "v1",
    "segment_key": "trending_up.5m",
    "n": 47,
    "spearman_rho": -0.32,
    "spearman_p": 0.028,
    "calibration_max_error": 0.08,
    "cvar_bottom_decile": -1.2,
    "mde": 0.29,
    "val_rho": -0.18,
    "overfitting_risk": false,
    "sharpe_delta": 0.14,
    "is_graduated": true,
    "evaluated_at": "2026-05-15T14:32:00Z",
    "expires_at": "2026-08-13T14:32:00Z"
}
```

## Composition Protocol

The live pipeline reads `transform_graduation` at startup and caches the set of graduated `(transform_id, segment_key)` pairs. Transforms still compute multipliers in-memory (they're pure functions). The log is write-only — never read at composition time.

Source of truth for "is this transform active?" is `transform_graduation.is_graduated`, NOT the log's `is_shadow` column.

```python
import math

def compose_confidence(
    raw_confidence: float,
    in_memory_multipliers: dict[str, float],
    graduation_cache: set[tuple[str, str]],
    segment_key: str,
) -> float:
    graduated = {
        tid: mult for tid, mult in in_memory_multipliers.items()
        if (tid, segment_key) in graduation_cache
    }
    if any(m == 0.0 for m in graduated.values()):
        return 0.0
    return raw_confidence * math.prod(graduated.values())
```

Rules:
- Only transforms present in `graduation_cache` affect the live pipeline
- Any gate returning 0.0 kills the signal immediately (regime suppression)
- All other graduated transforms compose as a product of multipliers
- `raw_confidence` is the I7 plugin's original value — never modified
- Shadow transforms are invisible — they compute and persist to the log, but excluded from composition

## Validation Compute Module

**File:** `src/intelligence/swarm/graduation.py`

Pure functions — DB-ignorant, testable, reusable by both `GraduationComputeAgent` and `scripts/validate_skeptic.py`.

### Gate Constants

```python
GATE_SPEARMAN_RHO = 0.15  # positive: high multiplier → high pnl_r
GATE_CALIBRATION_MAX_ERROR = 0.10
GATE_CVAR_BOTTOM_DECILE = -0.5
GATE_SEGMENT_MIN_N = 30
GATE_SEGMENT_RHO = 0.15
GATE_SEGMENT_POWER = 0.80
EVAL_RESOLUTION_THRESHOLD = 20  # new resolved signals before re-evaluation
EVAL_ROLLING_WINDOW_DAYS = 90
EVAL_EXPIRY_DAYS = 90
EVAL_WALK_FORWARD_FRACTION = 0.7
```

### Functions

```python
def compute_spearman(df: pd.DataFrame) -> dict
def compute_calibration(df: pd.DataFrame) -> pd.DataFrame
def compute_expected_shortfall(df: pd.DataFrame) -> dict
def compute_segment_power(n: int, alpha: float = 0.05, power: float = 0.80) -> float
def compute_walk_forward(df: pd.DataFrame, train_fraction: float = 0.7) -> dict
def compute_value_add(df: pd.DataFrame) -> dict
def evaluate_all(df: pd.DataFrame) -> dict  # orchestrates all 6 dimensions
```

Each function takes a DataFrame with columns `multiplier` and `pnl_r` (continuous, never binarized). `evaluate_all()` returns a `GraduationResult` dict matching the Kafka payload schema.

### CLI Wrapper

`scripts/validate_skeptic.py` becomes a thin CLI wrapper:

```python
from src.intelligence.swarm.graduation import evaluate_all
# Fetch data from DB, call evaluate_all(), print results
```

No duplicated logic — script and agent share the same module.

## What This Enables

### Research Queries

**Does the quality gate actually help?**
```sql
SELECT
    CASE WHEN stl.multiplier > 0.9 THEN 'high_quality' ELSE 'low_quality' END,
    avg(sl.pnl_r),
    count(*),
    round(avg(sl.pnl_r) / nullif(stddev(sl.pnl_r), 0) * sqrt(count(*)), 2) AS sharpe
FROM signal_transform_log stl
JOIN signal_ledger sl ON stl.signal_id = sl.signal_id
WHERE stl.transform_id = 'hurst_quality'
  AND sl.pnl_r IS NOT NULL
GROUP BY 1;
```

**Which transforms are carrying the system?**
```sql
SELECT tg.transform_id, tg.segment_key, tg.spearman_rho, tg.sharpe_delta
FROM transform_graduation tg
WHERE tg.is_graduated
ORDER BY tg.sharpe_delta DESC;
```

**Is the LLM skeptic worth its tokens?**
```sql
SELECT
    stl.segment_key,
    count(*) as predictions,
    sum((stl.metadata->>'cost_tokens')::int) as total_tokens,
    tg.spearman_rho,
    tg.sharpe_delta
FROM signal_transform_log stl
JOIN transform_graduation tg USING (transform_id, segment_key)
WHERE stl.transform_id = 'swarm_skeptic'
GROUP BY 1, 4, 5;
```

### Version A/B Testing

New prompt version ships in shadow alongside old version. Same signals, same segments. Graduation table has both rows:
```sql
SELECT transform_version, segment_key, spearman_rho, sharpe_delta
FROM transform_graduation
WHERE transform_id = 'swarm_skeptic'
  AND segment_key = 'trending_up.5m'
ORDER BY transform_version;
```

Numbers decide. If v2 doesn't beat v1, v2 doesn't graduate.

## Migration Plan

### Phase 1: Add tables + TransformRecorder + graduation pipeline (this build)

1. Create `signal_transform_log` and `transform_graduation` tables via migration
2. Add `TransformRecorder` to `src/core/ml/` (same batch pattern as `ShadowRecorder`)
3. Each existing pipeline stage gets a one-line call to `recorder.record()` after its existing logic
4. Build `graduation.py` validation module (extract from `validate_skeptic.py`)
5. Build `GraduationComputeAgent` + `GraduationWriterAgent` services
6. Add new Kafka topics to `stream_keys.py` and `kafka_init_topics.py`
7. Existing behavior unchanged — transforms still mutate confidence in-place
8. Transform log is write-only (for now), graduation pipeline runs in shadow

### Phase 2: Wire composition (after 30 days of dual-write data)

1. Replace in-place confidence mutation with `compose_confidence()`
2. `signal_ledger.confidence` becomes truly immutable (raw I7 value)
3. Add `signal_ledger.final_confidence` column for composed value
4. Graduation cache loaded at pipeline startup from `transform_graduation`
5. Only graduated transforms affect live signals

### Phase 3: Absorb alpha_multiplier_shadow (after graduation gates pass)

1. Swarm agents write to `signal_transform_log` instead of `alpha_multiplier_shadow`
2. Create backward-compatible view:
```sql
CREATE VIEW alpha_multiplier_shadow AS
SELECT
    stl.ts, stl.signal_id,
    stl.transform_id AS agent_id,
    sl.symbol, sl.timeframe AS tf,
    stl.metadata->>'hmm_regime' AS hmm_regime,
    stl.metadata->>'path' AS path,
    stl.multiplier AS predicted_multiplier,
    (stl.metadata->>'llm_confidence')::float AS confidence,
    stl.metadata AS features
FROM signal_transform_log stl
JOIN signal_ledger sl ON stl.signal_id = sl.signal_id
WHERE stl.transform_id IN ('swarm_skeptic', 'swarm_correlation', 'swarm_volume');
```
3. Existing services and scripts continue working unchanged via the view

### Phase 4: Deprecate old columns (after all transforms graduated)

1. Drop `calibrated_confidence`, `raw_cis_score`, `filtered_cis_score` from signal_ledger
2. Drop `alpha_multiplier_shadow` table (view is sufficient)
3. All transform state lives in `signal_transform_log`

## Compute and Storage Impact

**Writes per bar per symbol:** 9 transform rows (6 math + 3 swarm). At 55 symbols, ~495 rows per bar cycle. Batching makes this one `executemany` call per service flush interval.

**Storage:** ~495 rows/min x 390 min/session x 252 trading days = ~48M rows/year. At ~200 bytes/row = ~10 GB/year. TimescaleDB compression reduces this 10-20x. Storage is the cheapest thing we own.

**Latency:** Zero impact on hot path. Transforms already compute the same values — we're just persisting them instead of discarding. Write is batched async.

**Graduation compute:** Fires every ~20 resolved signals per (transform, segment). At steady state, maybe 2-3 evaluations per day per active transform. Each evaluation queries 90d of data for one segment — fast with the index on `(transform_id, segment_key, ts)`.

## File Manifest

### New files
- `src/intelligence/swarm/graduation.py` — 6 Renaissance validation dimensions (pure functions)
- `src/core/ml/transform_recorder.py` — batch writer for signal_transform_log
- `services/graduation_compute_agent.py` — event-driven graduation evaluator
- `services/graduation_writer_agent.py` — Kafka→DB writer for graduation results
- `production/migrations/073_signal_transform_log.sql` — table creation
- `production/migrations/074_transform_graduation.sql` — table creation
- `services/graduation-compute.service` — systemd unit
- `services/graduation-writer.service` — systemd unit

### Modified files
- `src/core/stream_keys.py` — add `topic_transform_graduation()`, `topic_transform_graduation_dlq()`
- `production/scripts/kafka_init_topics.py` — add new topics with retention config
- `scripts/validate_skeptic.py` — refactor to use `graduation.py` module
