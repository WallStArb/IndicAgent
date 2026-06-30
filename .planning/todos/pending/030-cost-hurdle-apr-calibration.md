---
**Created:** 2026-06-30
**Area:** intelligence
**Type:** calibration
**Priority:** P2
**Effort:** 30 min (query + two APR writes, no code change)
**Benefit:** Eliminates arbitrarily zero cost hurdles that make the net-scoring gate meaningless at 5m/15m
**Risk:** none (APR write, fully reversible)
**Gate:** Corpus pipeline complete (regime_writer refit → ic_engine → ensemble_trainer → alpha_publisher)
---

# 030 — Cost Hurdle APR Calibration (post-corpus)

Spun off from todo 004 (cost-aware net scoring, shipped 2026-06-30). The code is live;
`alpha.quant.cost_hurdle.5m` and `.15m` are seeded at 0.0 — effectively no gate.

## What

After corpus pipeline completes and `alpha_events` is populated:

1. Query `alpha_ci_lower` distribution from `alpha_events` by `tf`:

```sql
SELECT
    tf,
    count(*),
    percentile_cont(0.10) WITHIN GROUP (ORDER BY alpha_ci_lower) AS p10,
    percentile_cont(0.25) WITHIN GROUP (ORDER BY alpha_ci_lower) AS p25,
    percentile_cont(0.50) WITHIN GROUP (ORDER BY alpha_ci_lower) AS p50,
    avg(alpha_ci_lower)   AS mean
FROM alpha_events
WHERE alpha_ci_lower IS NOT NULL
GROUP BY tf
ORDER BY tf;
```

2. Set `alpha.quant.cost_hurdle.5m` and `.15m` to a defensible empirical value —
   the P10 or P25 of the 5m/15m `alpha_ci_lower` distribution is a reasonable
   starting point (captures worst-decile events that are net-negative after cost).

3. Write via `ConfigService` or direct SQL update:

```sql
UPDATE config_state SET config_value = '<value>', updated_at = now()
WHERE config_key IN ('alpha.quant.cost_hurdle.5m', 'alpha.quant.cost_hurdle.15m');
```

No code change needed. Verify via `/config/parameters` dashboard.

## Current State

```
alpha.quant.cost_hurdle.5m   = 0.0  [seed — needs calibration]
alpha.quant.cost_hurdle.15m  = 0.0  [seed — needs calibration]
alpha.quant.cost_hurdle.1h   = 0.0  [leave at 0 for now — cost less material at 1h]
alpha.quant.cost_hurdle.1d   = 0.0  [leave at 0 for now]
```

## Dependencies

- `alpha_events` must be populated from a full corpus run
- Corpus pipeline: `production/scripts/corpus_pipeline_run.sh`
- Current status: alpha_events = 0 rows (as of 2026-06-30); corpus re-run needed after
  regime_writer refit completes
