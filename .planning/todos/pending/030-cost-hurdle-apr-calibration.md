---
**Created:** 2026-06-30
**Area:** intelligence
**Type:** calibration
**Priority:** P2
**Effort:** 1h (three queries + APR writes, no code change)
**Benefit:** Replaces four seeded-at-zero cost hurdles and four researcher-set emission thresholds with empirically grounded values; also validates whether gap contamination and IC decay hypotheses are real
**Risk:** none (APR writes, fully reversible)
**Gate:** Corpus pipeline complete (regime_writer refit → ic_engine → ensemble_trainer → alpha_publisher)
---

# 030 — Post-Corpus Empirical Calibration

Expanded from original cost-hurdle scope. The same corpus session answers three open
empirical questions at once. All are query + APR write — no code changes.

See hypothesis context: `docs/plans/2026-06-30-alphaengine-methodology-hypotheses.md`

---

## Step 1 — Cost Hurdle Calibration

Code is live; `alpha.quant.cost_hurdle.5m` and `.15m` are seeded at 0.0 — no gate.

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
GROUP BY tf ORDER BY tf;
```

Set `alpha.quant.cost_hurdle.5m` and `.15m` to P10 or P25 of their respective
distributions. Leave 1h/1d at 0.0 — cost is less material at longer horizons.

---

## Step 2 — Emission Threshold Validation

Current seeds: 5m=1.5, 15m=1.2, 1h=1.0, 1d=0.8. Unknown whether they are binding.

```sql
SELECT
    tf,
    count(*),
    percentile_cont(0.05) WITHIN GROUP (ORDER BY abs(alpha_score)) AS p05,
    percentile_cont(0.10) WITHIN GROUP (ORDER BY abs(alpha_score)) AS p10,
    percentile_cont(0.25) WITHIN GROUP (ORDER BY abs(alpha_score)) AS p25,
    min(abs(alpha_score)) AS min_score
FROM alpha_events
GROUP BY tf ORDER BY tf;
```

- Thresholds below P10 → seeds are not binding; leave as-is or lower slightly
- Thresholds above P50 → over-filtering; lower via APR write
- Update `alpha.quant.threshold.{tf}` only if the data shows a meaningful gap between
  the current seed and where the distribution actually sits

---

## Step 3 — Gap Contamination Check

Validates Hypothesis 1. `has_gap_before_entry` is already in `forward_returns`.

```sql
SELECT
    has_gap_before_entry,
    count(*) AS n,
    avg(return_fast)    AS mean_return_fast,
    stddev(return_fast) AS std_return_fast
FROM forward_returns
GROUP BY has_gap_before_entry;
```

Also check IC by tf — gap fraction is near-zero for 5m bars but meaningful for 1d:

```sql
SELECT
    fis.tf,
    count(*) AS n,
    avg(fis.ic_mean) AS avg_ic
FROM feature_ic_scores fis
GROUP BY fis.tf ORDER BY fis.tf;
```

- Gap fraction < 5% and return distribution similar → hypothesis not supported; no action
- Meaningful IC difference → add `WHERE has_gap_before_entry = false` to ic_engine
  forward_returns join (one-line change, no migration needed)

---

## APR keys to calibrate

```
alpha.quant.cost_hurdle.5m   [seed 0.0 → empirical P10/P25]
alpha.quant.cost_hurdle.15m  [seed 0.0 → empirical P10/P25]
alpha.quant.threshold.5m     [seed 1.5 → adjust if over/under-filtering]
alpha.quant.threshold.15m    [seed 1.2 → adjust if over/under-filtering]
alpha.quant.threshold.1h     [seed 1.0 → adjust if over/under-filtering]
alpha.quant.threshold.1d     [seed 0.8 → adjust if over/under-filtering]
```

Update via:
```sql
UPDATE config_state SET config_value = '<value>', updated_at = now()
WHERE config_key = '<key>';
```

Verify via `/config/parameters` dashboard.

---

## Dependencies

- `alpha_events` must be populated from a full corpus run
- `forward_returns` must be populated (always is — upstream of ic_engine)
- Corpus pipeline: `production/scripts/corpus_pipeline_run.sh`
