# Signal Transform Log — Unified Alpha Modifier Architecture

**Date:** 2026-04-24
**Status:** Draft
**Phases affected:** 66 (swarm agents), future ML phases
**Tables added:** `signal_transform_log`, `transform_graduation`
**Tables deprecated:** `alpha_multiplier_shadow` (absorbed via view)

---

## Problem

Nine transforms modify signal confidence between I7 plugin output and winner selection. Six of them (hurst quality, drift penalty, regime gate, TOD, isotonic calibration, performance weighting) mutate `confidence` in-place with no traceability. Three (swarm agents) write to a separate `alpha_multiplier_shadow` table.

You cannot answer: "Does the Hurst quality gate actually improve Sharpe?" or "What would happen if we removed TOD?" because intermediate values are destroyed by the next mutation step.

This violates three Renaissance principles:
- **Earn the right through proof** — no transform has statistically proven it adds alpha
- **Never drop data that could contain signal** — intermediate confidence values are lost forever
- **Segment relentlessly** — evaluation is global, not per-regime or per-timeframe

## Design Principles

1. **Every transform is an independent, evaluable hypothesis.** Each one must prove it adds alpha (p < 0.05, N >= 30) before affecting the live pipeline.
2. **The original signal is immutable.** `signal_ledger.confidence` stays as the raw I7 plugin output. All modifications are additive rows in a separate table.
3. **One table, one pattern.** Math transforms and LLM evaluators use the same storage model. `alpha_multiplier_shadow` is absorbed.
4. **Graduation is per-segment and temporary.** A transform that works in trending 5m might not work in ranging 1h. Graduation expires every 90 days — must re-prove.
5. **Minimal schema, maximum flexibility.** Only first-class query dimensions are columns. Everything else goes in JSONB metadata.

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
    is_shadow         BOOLEAN NOT NULL DEFAULT TRUE  -- TRUE until graduation job promotes
);

SELECT create_hypertable('signal_transform_log', 'ts');

-- One row per transform per signal per version (idempotent on restart)
CREATE UNIQUE INDEX idx_stl_identity
    ON signal_transform_log (signal_id, transform_id, transform_version);

-- Graduation evaluation queries: correlation per transform per segment
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
| `multiplier` | The transform's alpha assessment — the core value | Composition and evaluation |
| `metadata` | Transform-specific context — varies per transform_id | Research queries |
| `is_shadow` | Write-time snapshot — TRUE until graduation promotes. Source of truth for composition is `transform_graduation.is_graduated` | Research queries |

### transform_graduation

Tracks statistical evidence for each transform per segment. Evaluated by a weekly scheduled job. Graduation expires — transforms must re-prove.

```sql
CREATE TABLE transform_graduation (
    transform_id      TEXT NOT NULL,
    transform_version TEXT NOT NULL,
    segment_key       TEXT NOT NULL,
    n                 INT NOT NULL,
    rho               FLOAT NOT NULL,
    p_value           FLOAT NOT NULL,
    sharpe_delta      FLOAT,
    is_graduated      BOOLEAN NOT NULL DEFAULT FALSE,
    evaluated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at        TIMESTAMPTZ NOT NULL,
    UNIQUE (transform_id, transform_version, segment_key)
);
```

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

Graduation is evaluated per `(transform_id, transform_version, segment_key)`. The segment_key captures the market regime context where the transform operates:

| Transform | segment_key pattern | Example |
|-----------|-------------------|---------|
| hurst_quality | `{regime_type}.{tf}` | `trend.5m`, `mean_reversion.1h` |
| drift_penalty | `{regime_type}.{tf}` | `trend.5m` |
| regime_gate | `{regime_type}` | `trend`, `mean_reversion` |
| tod | `{regime_type}.{tf}.{hour}` | `trend.5m.9`, `mean_reversion.1h.14` |
| isotonic | `{plugin}.{tf}` | `trad_TrendFollowing.5m` |
| perf_weight | `{plugin}.{tf}` | `trad_SqueezeExpansion.15m` |
| swarm_* | `{hmm_regime}.{tf}` | `trending_up.5m`, `ranging.1h` |

Global transforms that don't segment use `__global__`.

## Composition Protocol

The live pipeline reads `transform_graduation` at startup and caches the set of graduated `(transform_id, segment_key)` pairs. Transforms still compute multipliers in-memory (they're pure functions). The log is write-only — never read at composition time.

Source of truth for "is this transform active?" is `transform_graduation.is_graduated`, NOT the log's `is_shadow` column. The log's `is_shadow` is a write-time snapshot for research queries only.

```python
import math

def compose_confidence(
    raw_confidence: float,
    in_memory_multipliers: dict[str, float],
    graduation_cache: set[tuple[str, str]],  # (transform_id, segment_key) of graduated transforms
    segment_key: str,
) -> float:
    graduated = {
        tid: mult for tid, mult in in_memory_multipliers.items()
        if (tid, segment_key) in graduation_cache
    }
    # Gate suppression: any 0.0 multiplier kills the signal
    if any(m == 0.0 for m in graduated.values()):
        return 0.0
    return raw_confidence * math.prod(graduated.values())
```

Rules:
- Only transforms present in `graduation_cache` affect the live pipeline
- Any gate returning 0.0 kills the signal immediately (regime suppression)
- All other graduated transforms compose as a product of multipliers
- `raw_confidence` is the I7 plugin's original value — never modified
- Shadow transforms are invisible — they compute and persist to the log, but are excluded from composition

## Graduation Protocol

Weekly scheduled evaluation. For each `(transform_id, transform_version, segment_key)`:

```sql
-- Graduation evaluation query (run by scheduled Python job)
-- PostgreSQL corr() gives Pearson rho; p-value computed in Python via scipy.stats.pearsonr
-- The job fetches (multiplier, outcome) pairs per segment, then evaluates the gate in Python.
SELECT
    stl.multiplier,
    CASE WHEN sl.outcome IN ('target_1','target_1_2','target_full')
         THEN 1.0 ELSE 0.0 END AS won
FROM signal_transform_log stl
JOIN signal_ledger sl ON stl.signal_id = sl.signal_id
WHERE stl.transform_id = :transform_id
  AND stl.segment_key = :segment_key
  AND sl.outcome IS NOT NULL
  AND stl.ts > now() - interval '90 days';
```

The Python graduation job computes `scipy.stats.pearsonr(multipliers, wins)` for each segment, getting both rho and p-value. Results are upserted into `transform_graduation`.

Gate criteria (per Renaissance principles):
- `rho >= 0.2` (correlation with outcomes)
- `p_value < 0.05` (statistically significant)
- `n >= 30` (sufficient sample)
- `sharpe_delta > 0` (positive Sharpe contribution)

Graduation lifecycle:
1. Transform writes rows with `is_shadow = TRUE` from day one
2. After N >= 30, graduation job evaluates
3. If gate passes: `is_graduated = TRUE`, `expires_at = now() + 90 days`
4. If gate fails: stays shadow, re-evaluated next week
5. At expiry: drops back to shadow until re-proven

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

**What if we removed TOD?** — Replay historical signals computing confidence without `tod` rows. Measure P&L impact. This is a SQL query, not a code change.

**Which transforms are carrying the system?**
```sql
SELECT tg.transform_id, tg.segment_key, tg.rho, tg.sharpe_delta
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
    tg.rho,
    tg.sharpe_delta
FROM signal_transform_log stl
JOIN transform_graduation tg USING (transform_id, segment_key)
WHERE stl.transform_id = 'swarm_skeptic'
GROUP BY 1, 4, 5;
```

### Version A/B Testing

New prompt version ships in shadow alongside old version. Same signals, same segments. Graduation table has both rows. Comparison:

```sql
SELECT transform_version, segment_key, rho, p_value, sharpe_delta
FROM transform_graduation
WHERE transform_id = 'swarm_skeptic'
  AND segment_key = 'trending_up.5m'
ORDER BY transform_version;
```

Numbers decide. If v2 doesn't beat v1, v2 doesn't graduate.

## Migration Plan

### Phase 1: Add tables, dual-write (zero risk)

1. Create `signal_transform_log` and `transform_graduation` tables
2. Add a `TransformRecorder` (same batch pattern as `ShadowRecorder`)
3. Each existing pipeline stage gets a one-line call to `recorder.record()` after its existing logic
4. Existing behavior unchanged — transforms still mutate confidence in-place for the live pipeline
5. Transform log is write-only, no reads

### Phase 2: Wire composition (after 30 days of dual-write data)

1. Replace in-place confidence mutation with `compose_confidence()`
2. `signal_ledger.confidence` becomes truly immutable (raw I7 value)
3. Add `signal_ledger.final_confidence` column for composed value
4. Existing columns (`calibrated_confidence`, `tod_multiplier`, etc.) kept for backward compatibility
5. Graduation job starts evaluating transforms against 30+ days of data

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
3. Existing swarm services, validation scripts, and dashboard queries continue working unchanged

### Phase 4: Deprecate old columns (after all transforms graduated)

1. Drop `calibrated_confidence`, `raw_cis_score`, `filtered_cis_score` from signal_ledger
2. Drop `alpha_multiplier_shadow` table (view is sufficient)
3. All transform state lives in `signal_transform_log`

## Compute and Storage Impact

**Writes per bar per symbol:** 9 transform rows (6 math + 3 swarm). At 55 symbols, ~495 rows per bar cycle. Batching makes this one `executemany` call per service flush interval.

**Storage:** ~495 rows/min × 390 min/session × 252 trading days ≈ 48M rows/year. At ~200 bytes/row ≈ 10 GB/year. TimescaleDB compression reduces this 10-20x. Storage is the cheapest thing we own.

**Latency:** Zero impact on hot path. Transforms already compute the same values — we're just persisting them instead of discarding. Write is batched async.

**Graduation job:** Weekly SQL query per (transform_id, segment_key). ~20 segments × 9 transforms = 180 queries. Runs in under 30 seconds.
