---
**Created:** 2026-06-30
**Area:** intelligence
**Type:** calibration
**Priority:** P2
**Effort:** 1h (three queries + APR writes, no code change)
**Benefit:** Replaces four seeded-at-zero cost hurdles and four researcher-set emission thresholds with empirically grounded values; also validates whether gap contamination and IC decay hypotheses are real
**Risk:** none (APR writes, fully reversible)
**Gate:** Corpus pipeline complete (regime_writer refit → ic_engine → ensemble_trainer → alpha_publisher). **Note (2026-07-01): also gated on todo 034 landing** — any regime-stratified calibration derived from this corpus run inherits the non-causal HMM fit bias todo 034 describes; re-run this calibration once 034 ships if it lands after this corpus pass.
---

# 030 — Post-Corpus Empirical Calibration

Expanded from original cost-hurdle scope. The same corpus session answers three open
empirical questions at once. All are query + APR write — no code changes.

See hypothesis context: `docs/plans/2026-06-30-alphaengine-methodology-hypotheses.md`

**Reframed 2026-07-01 — this todo is the cheapest falsification test in the backlog; run
Step 0 first.** Steps 1-3 calibrate against the *internal* score distribution; none compare
IC-implied returns against *external* costs (spread), which is the test that could kill an
entire timeframe. Gross IC of 0.02-0.08 at 5m on ETFs is plausibly eaten whole by
half-spread. If Step 0 shows 5m (and possibly 15m) net-negative across the board, concentrate
feature/compute budget on 1h/1d — a conclusion worth reaching BEFORE more 5m-heavy work
(backfill deepening, per-symbol regime IC runs) is invested. See
`docs/research/edge-source-thesis.md` — every edge thesis dies or survives at a different rate
once gross IC becomes net E[R] per tf.

---

## Step 0 — External Cost Floor vs IC-Implied Returns (run first)

Per tf, compare what qualifying features imply in return units against realistic round-trip
cost:

1. **IC-implied gross E[R] per trade:** for qualifying cells (`passes_ci_gate AND
   passes_fdr`), `E[R] ≈ ic_value × stddev(forward_return)` for that (tf, lookahead) — the
   standard IC-to-return conversion. Query `forward_returns` for return stddev per
   tf/lookahead; multiply by IC (haircut mentally for selection bias until shrinkage ships).
2. **Cost floor per round trip:** half-spread × 2 + slippage estimate. Liquid half of the
   universe ~1 tick spreads (SPY ~0.3bp, sector ETFs ~1-2bp, less-liquid internationals
   ~3-5bp half-spread); pull actual quotes from IBKR where uncertain.
3. **Verdict per tf:** median IC-implied E[R] of qualifying cells vs cost floor. Net-negative
   at the median → that tf's features are not tradeable as *directional* signals at current
   IC levels; record the verdict here and in `docs/research/edge-source-thesis.md`.
   (Cross-sectional spread portfolios have different cost dynamics — a 5m directional fail
   does not kill 5m for the PortfolioTrack; record as tf-directional-fail specifically.)

No APR write from Step 0 — it is a verdict, not a calibration. Steps 1-3 remain as below.

**VERDICT (run 2026-07-01):** Confirmed net-negative-to-marginal at short horizons on the two
highest-compute timeframes.

| tf / scale | Median-IC gross E[R] | vs cost floor |
|---|---|---|
| 5m fast (lookahead=1) | 0.26 bps | Dead — 4-40x below cheapest cost floor |
| 5m mid | 0.84 bps | Dead for most of universe |
| 5m slow | 4.33 bps | Survives liquid core only |
| 5m extended | 13.6 bps | Clears broadly |
| 15m fast | 0.55 bps | Dead |
| 15m mid | 1.72 bps | Marginal, cheapest names only |
| 15m slow | 8.9 bps | Clears broadly |
| 1h fast | 4.0 bps | Marginal-to-clears |
| 1d fast | 7.5 bps | Clears broadly |
| 1d mid/slow/extended | 27-161 bps | Clears comfortably |

Method: `median(ic_value) × stddev(forward_return)` per (tf, lookahead) over `POOLED`
qualifying cells (`passes_ci_gate AND passes_fdr`), vs. blended round-trip cost floor
(~1bp liquid core, ~2-4bp sector ETFs, ~6-10bp illiquid international). Uses raw (not
shrunk) IC — shrinkage isn't built yet (feature-scoring-beyond-ic §0b) — so every number
above is an upper bound; the real picture is worse, not better.

**Implication:** 5m fast/mid and 15m fast are not tradeable as directional signals at
current IC levels. This is the highest-compute, highest-row-count portion of the corpus
(5m alone is ~86K rows/symbol/tf). Recommendation: deprioritize further 5m-heavy
investment (backfill deepening, per-symbol regime IC runs) until shrinkage lands and this
verdict is re-run on shrunk IC; concentrate near-term validation effort (142A) on
1h/1d and the longer-lookahead 5m/15m cells, which clear comfortably even on
unshrunk, conservative numbers.

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
