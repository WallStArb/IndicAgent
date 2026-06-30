# AlphaEngine V1 — Methodology Hypotheses

**Date:** 2026-06-30
**Status:** Active — three hypotheses requiring empirical validation before any code is written
**Methodology reference:** `docs/intelligence/intelligence-alphaengine-methodology.md`
**Tracking:** todo 030 (post-corpus empirical calibration — covers all three)

These were framed as "correctness gaps" in the original draft. That framing was wrong.
They are hypotheses derived from theoretical methodology. The corpus now exists. Measure
first; build only what the data shows is necessary.

Musk rule: don't automate what isn't proven. Don't optimize what should be deleted.

---

## Hypothesis 1 — Gap Observations Contaminate IC

**Claim:** Overnight/holiday gap observations have a structurally different return
distribution from intraday observations, and mixing them understates IC for both
populations.

**Why it might be wrong:** Gap observations may be a small fraction of the corpus with
negligible IC difference. The contamination effect is unknown until measured.

**How to validate (no code — data already exists):**

```sql
SELECT
    has_gap_before_entry,
    count(*) AS n,
    avg(return_fast)    AS mean_return_fast,
    stddev(return_fast) AS std_return_fast
FROM forward_returns
GROUP BY has_gap_before_entry;
```

Then compare `ic_mean` in `feature_ic_scores` across tfs — 1d bars will have many gaps;
5m bars almost none. If 1d IC is systematically different in a way that gap fraction
explains, the contamination is real.

**Decision rule:**
- Gap fraction < 5% of corpus OR IC difference < 0.01 across tfs → do nothing
- IC difference >= 0.01 → simplest fix is `WHERE has_gap_before_entry = false` in the
  ic_engine forward_returns join. No schema change. No new columns. No stratification.
  Add separate gap IC measurement only if diagnostic value is proven downstream.

---

## Hypothesis 2 — Emission Thresholds Are Materially Wrong

**Claim:** Current thresholds (5m=1.5, 15m=1.2, 1h=1.0, 1d=0.8) are researcher seeds
with no empirical grounding and are causing material mis-filtering of alpha_events.

**Why it might be wrong:** The seeds may be reasonable priors. The alpha_events
distribution may cluster well above the thresholds, meaning they are not binding at all.

**How to validate (no code — same session as todo 030):**

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

**Decision rule:**
- Thresholds sit below P10 of the distribution → not binding; seeds are defensible; adjust
  manually via APR write if needed
- Thresholds sit above P50 → over-filtering; adjust seeds down via APR write
- Automated derivation in `ensemble_trainer.py` is premature. Manual calibration after each
  re-solve is sufficient until we observe that thresholds drift materially between solves.

---

## Hypothesis 3 — IC Decays Fast Enough to Require Daily Monitoring

**Claim:** Ensemble weights go stale quickly enough that a daily decay monitor service
is necessary for correctness.

**Why it is almost certainly premature:** The corpus has run for weeks. We have no time
series of IC to show decay velocity. A daily service built on theoretical decay assumptions
would trigger false re-solves on a corpus where IC is stable.

**How to validate (no code — ongoing practice):**

Run `ic_engine` on the full corpus at monthly intervals for 3 months. After each run,
compare `ic_mean` for the same (feature, symbol, tf, regime) cells. If IC shifts
meaningfully (> 0.02 per month on average), the hypothesis is supported. If IC is stable,
the service is net-harmful — it introduces re-solve churn on a stable ensemble.

**Decision rule:**
- No measurable IC drift after 3 months → do not build the service
- Drift detected → design the service from the observed decay timescale, not from theory
- The schema columns (`is_decaying`, `decay_detected_at`, `recovery_eligible_at`) are
  already present; they cost nothing to leave unused until the hypothesis is proven

---

## Summary

| Hypothesis | Validation | Premature action avoided |
|---|---|---|
| Gap contamination | SQL query on existing corpus | Schema changes + stratification logic |
| Threshold mis-calibration | Query alpha_events distribution (in todo 030) | Automated sweep in ensemble_trainer |
| IC decay velocity | Monthly ic_engine re-runs over 3 months | Daily decay monitor service |
