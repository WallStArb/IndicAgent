# Instrument Tag Auditor

**Version:** 1.2
**Status:** draft
**Priority:** high
**Milestone:** post-v2.8
**Last Updated:** 2026-07-01
**Tags:** instruments, tags, empirical, calibration, renaissance, factor-model

---

## Problem

The `instrument_tags` table holds human-asserted priors. "TLT is `rate_sensitive` with weight 1.0" is a belief, not a fact. It has no measurement procedure, no p-value, no lookback window, no expiry mechanism. A Renaissance-grade system cannot operate on beliefs — it needs falsifiable hypotheses and a falsification engine.

---

## Simons Critique

### The measurable primitives

> "You have 53 tags. I can measure 8 things precisely. The other 45 are either derivable from the 8 or they're noise. Delete them."

Primitives that can be computed directly from market data, grouped by type:

**Linear factor betas** — OLS regression of instrument daily returns against a factor series:

| Primitive | Factor series | Notes |
|-----------|--------------|-------|
| `equity_beta` | SPY | Core market sensitivity |
| `rate_beta` | TLT | Duration / rate regime sensitivity |
| `gold_beta` | GLD | Safe haven / inflation hedge loading |
| `credit_beta` | HYG | Credit spread cycle sensitivity |
| `dollar_beta` | EURUSD (inverse) | USD strength sensitivity |
| `vol_beta` | VIX changes | Volatility regime sensitivity |
| `oil_beta` | CL front month | Energy / commodity cycle; distinct from dollar_beta |
| `china_beta` | KWEB | China demand; distinct from broad EM via EEM |
| `curve_beta` | IEF/SHY spread | Yield curve steepener/flattener sensitivity; rate_beta alone misses this |

**Information-theoretic:**

| Primitive | Measurement | Notes |
|-----------|-------------|-------|
| `lead_lag` | Cross-correlation vs SPY at lags 1-10 | Does instrument lead the market? |
| `regime_mutual_information` | Mutual information vs HMM regime state | How much does regime state explain this instrument? |

**Asymmetric betas** — unconditional beta misses regime-dependent behavior:

| Primitive | Measurement | Notes |
|-----------|-------------|-------|
| `upside_beta` | OLS beta vs SPY on days SPY > 0 | Risk participation in rallies |
| `downside_beta` | OLS beta vs SPY on days SPY < 0 | Behavior in selloffs — the number that matters for portfolio construction |
| `crisis_beta` | OLS beta vs SPY on days VIX > 30 | Tail behavior; gold's crisis_beta is negative while unconditional equity_beta is near zero — that difference is the signal |

The ratio `downside_beta / upside_beta` is the asymmetric risk fingerprint. A true hedge has low upside_beta and negative downside_beta. HYG has high upside_beta and very high downside_beta. These are fundamentally different instruments even when unconditional equity_beta is similar.

**Time series properties** — no factor required; derived from the return series itself:

| Primitive | Measurement | Notes |
|-----------|-------------|-------|
| `hurst_exponent` | R/S analysis over rolling window | H > 0.5 = trending, H < 0.5 = mean-reverting, H = 0.5 = random walk |
| `autocorrelation_lag1` | Lag-1 return autocorrelation | Positive = momentum persists; negative = mean-reverting at short horizon |
| `vol_of_vol` | Std dev of rolling 20d realized vol | Stable vol instruments are categorically different from vol-spiking ones |
| `skewness` | Return distribution skewness | Negative = crash risk (HYG, ARKK); positive = lottery-like (XBI) |

**Stability / meta-primitives** — measure how reliable the other primitives are:

| Primitive | Measurement | Notes |
|-----------|-------------|-------|
| `beta_stability` | Rolling std of `equity_beta` across 6-month windows | Low = relationship is reliable; high = factor loading shifts across regimes and any tag derived from it should be discounted between calibration runs |

`beta_stability` is a prerequisite for trusting the system's outputs. An instrument with high `beta_stability` variance means the calibrator's measurement from last quarter may not reflect today's relationship. This should feed directly into the half-life decay rate — unstable instruments get shorter half-lives.

Everything else is derivable from these — or it is noise.

### Factor vector derivability

Every instrument has a position in a high-dimensional factor space defined by the measurable primitives. The tag vocabulary is a compression of that space — a lossy but human-readable taxonomy that distills multivariate factor loadings into named regions for querying and communication. The tags are not the truth; the factor vector is. The vocabulary exists so that an AI agent or analyst can say "give me all risk-off instruments" without writing a multi-dimensional threshold query every time.

This is the same principle as dimensionality reduction in quantitative research: PCA distills hundreds of correlated return series into a small number of orthogonal factors. The TagAuditor distills a continuous factor space into a discrete, queryable taxonomy. The taxonomy is useful precisely because it is a simplification — and dangerous precisely for the same reason. Any tag that cannot be traced back to a threshold on the factor vector is a belief, not a measurement.

Examples of tags that are fully derivable:

| Tag | Derivation from factor vector |
|-----|-------------------------------|
| `risk_off` | `equity_beta < -0.3 AND gold_beta > 0.3 AND rate_beta > 0.3` |
| `risk_on` | `equity_beta > 0.7 AND gold_beta < 0.1` |
| `rate_sensitive` | `abs(rate_beta) > 0.4`, p < 0.05 |
| `defensive` | `equity_beta < 0.5 AND vol_beta < 0` |
| `leading_indicator` | peak `lead_lag` cross-correlation at lag -1 to -5 |
| `regime_classifier` | `regime_mutual_information` above threshold |
| `breadth` | high correlation to RSP/SPY return differential |
| `inflation` | `gold_beta > 0.3 AND rate_beta < 0` (real rates falling) |
| `credit_risk` | high `credit_beta` magnitude, p < 0.05 |

The implication: the TagAuditor does not just validate tags — it can *discover* them. An instrument with `equity_beta < -0.3 AND gold_beta > 0.5` that has no `risk_off` tag is a gap the system should self-identify and flag for human review. Discovery flows from measurement, not from human enumeration.

This also means the 56-tag vocabulary can be compressed. Most tags in the `sensitivity` and `factor_regime` categories collapse to threshold queries on the 8 primitives. The vocabulary is a convenience layer, not the source of truth. The source of truth is the factor vector.

### The long-term architecture implication

The current design has the calibrator validating `(symbol, tag)` pairs that humans asserted. The Simons version runs in the other direction: compute the full 8-dimensional factor vector for every instrument on every calibration run, then derive which tags apply from the vector. Human assertions become priors that get overwritten, not hypotheses that get tested.

This inverts the workflow:

```
Current:  human asserts tag → calibrator tests → empirical confirms or expires
Simons:   calibrator computes factor vector → derives tags from thresholds → human labels the regions
```

The schema supports this already — `source='empirical'` rows can be written without a prior `source='human'` row. The calibration loop just needs to run unconditionally across all instruments, not just against existing `instrument_tags` rows. Research item for the planning phase.

### What Simons would keep

Four things in the current design are correct:

1. **Schema separation** — `tag_vocabulary / instrument_tags / instrument_annotations` is the right layering. Static structure, dynamic content, free-form discovery.
2. **Provenance tracking** — `source: human | empirical | ai` is exactly right. Human-asserted tags get lower prior weight than empirically derived ones.
3. **Temporal validity** — `valid_from / valid_to` is right because relationships are non-stationary. A tag from 2019 data may be wrong in 2024. The decay mechanism exists; it needs an engine to drive it.
4. **Annotation layer** — AI writing `ai_insight` annotations that humans can promote to formal tags is the correct discovery loop. Human researchers propose hypotheses; a statistical gatekeeping process handles promotion.

### What he would add (research items)

- **Statistical gatekeeping on the tag PK** — a tag shouldn't exist without `p < 0.05`. Tags are not permanent; they continuously earn their place. A tag that was valid 18 months ago under a different rate regime may not survive today's data.
- **Regime conditioning** — `(symbol, tag, regime)` PK instead of `(symbol, tag)`. XLU's `rate_sensitive` beta in high-vol is materially different from low-vol. Everything was regime-conditional at Renaissance. Unconditional betas are a first-order approximation that Phase 2 corrects.
- **Half-life on weights** — the `weight` field should decay exponentially. `effective_weight = weight * exp(-days_since_estimated / half_life_days)`. A beta estimated in a structurally different rate environment is stale; its effective weight should reflect that before the next calibration run overwrites it.
- **Derived tag elimination** — tags fully computable from the 8 primitives should not exist as permanent assertions. They are query-time threshold applications on the factor vector. Storing them as rows is redundant — and worse, it can go stale between calibration runs while appearing current.
- **Self-discovering gaps** — the calibrator should scan all instruments for factor vector positions that don't match any existing tag, and write `ai_insight` annotations flagging the gap. An instrument with `equity_beta < -0.4 AND gold_beta > 0.6` that has no `risk_off` tag is a system error, not a human omission. The engine should find it.

### On `cycle_position`

The correct implementation is to model the economic cycle as a latent variable — an HMM, which we already have — and compute each instrument's loading on the current regime state. That is Phase 2.

The `early_cycle / mid_cycle / late_cycle / recession` tags shipped in migration 121 as **definitional human seed priors** — `measurement_type = 'definitional'`, never empirically validated, never auto-expired. They give downstream consumers a query handle before Phase 2 ships. Phase 2 regime conditioning supersedes them.

---

## Design

### Philosophy

The orienting reframe from a Renaissance/Simons lens:

> "Your taxonomy is a set of hypotheses. Every tag is a hypothesis about a relationship between an instrument and a factor. The system's job is to test hypotheses, not store beliefs. Tags that survive testing become facts. Facts that stop surviving get expired. The vocabulary defines the hypothesis space. The measurement system determines what's true within it."

We built a knowledge store. The TagAuditor turns it into a hypothesis testing engine that happens to store its survivors.

Human-asserted tags (`source='human'`) are seed priors — they initialize the system and are never auto-expired. The calibrator writes `source='empirical'` rows alongside them. When empirical contradicts human with high confidence, the empirical row takes precedence in downstream queries.

### Schema additions

**`tag_vocabulary`** gains measurement contracts:

```sql
ALTER TABLE tag_vocabulary
  ADD COLUMN factor_series     text,    -- canonical instrument to regress against ('TLT', 'HYG')
  ADD COLUMN measurement_type  text DEFAULT 'beta_regression'
      CHECK (measurement_type IN (
          'beta_regression',    -- OLS beta of instrument vs factor_series daily returns
          'correlation',        -- rolling Pearson correlation
          'cross_correlation',  -- cross-corr at lags 1-N (leading_indicator)
          'mutual_information', -- MI against HMM regime state (regime_classifier)
          'definitional'        -- never estimated; human-only (benchmark, spread_leg)
      )),
  ADD COLUMN lookback_days      int   DEFAULT 252,
  ADD COLUMN p_value_threshold  float DEFAULT 0.05,
  ADD COLUMN min_r2             float DEFAULT 0.05;
```

**`instrument_tags`** gains statistical metadata:

```sql
ALTER TABLE instrument_tags
  ADD COLUMN p_value      float,
  ADD COLUMN sample_n     int,
  ADD COLUMN estimated_at timestamptz;
```

The existing `evidence` JSONB holds full output including decay metadata: `{beta: -8.3, r2: 0.71, ci_lower: -9.1, ci_upper: -7.5, half_life_days: 180, last_estimated: "2026-06-01"}`.

**Half-life on weights:** A relationship measured 18 months ago is less reliable than one measured last week. The calibrator applies exponential decay — effective weight = `weight * exp(-days_since_estimated / half_life_days)`. Each tag in `tag_vocabulary` carries a configurable `half_life_days` (default 180). Downstream consumers use effective weight, not raw weight. Tags re-estimated on each calibration run reset their decay clock. Tags that go un-re-estimated long enough effectively zero out before formal expiry.

### Factor series mapping

| Tag | Factor series | Method | Rationale |
|-----|--------------|--------|-----------|
| `rate_sensitive` | TLT | beta_regression | TLT IS rates — cleanest proxy |
| `credit_risk` | HYG | beta_regression | HYG spread = credit risk |
| `inflation` | TIP | beta_regression | TIP = inflation expectations |
| `dollar_strength` | EURUSD | beta_regression | Inverse dollar proxy |
| `oil_price` | CL (front month) | beta_regression | Direct commodity |
| `gold_beta` | GLD | beta_regression | Direct commodity |
| `em_flows` | EEM | beta_regression | EM benchmark |
| `growth` | VUG | correlation | Pure growth factor |
| `value` | VTV | correlation | Pure value factor |
| `momentum` | MTUM | correlation | Momentum factor |
| `yield_curve` | IEF/SHY spread | beta_regression | Curve shape |
| `yen_carry` | USDJPY | beta_regression | Yen carry |
| `semi_cycle` | SMH | correlation | Chip cycle proxy |
| `housing_cycle` | XHB | correlation | Housing leading indicator |
| `china_demand` | KWEB | beta_regression | China tech = demand signal |
| `fed_policy` | SHY | beta_regression | Short-end = Fed anchor |
| `credit_cycle` | KRE | correlation | Regional banks = credit cycle |
| `leading_indicator` | SPY | cross_correlation (lags 1-10) | Does instrument lead market? |
| `regime_classifier` | HMM state | mutual_information | MI against regime output |
| `breadth` | RSP/SPY ratio | correlation | Participation width |
| `benchmark` | — | definitional | Never estimated |
| `spread_leg` | — | definitional | Never estimated |
| `sector_rotation` | — | definitional | Never estimated |
| `factor_rotation` | — | definitional | Never estimated |
| `sentiment` | — | definitional | Human-only judgment |
| `stress_indicator` | — | definitional | Human-only judgment |

### Calibration loop

```
nightly TagAuditor (timer-triggered oneshot, same pattern as roll_batch.py)

for each (symbol, tag) in instrument_tags
  where tag.measurement_type != 'definitional'
  and instrument has >= lookback_days of daily bars in market_data_ohlcv:

  1. Fetch instrument daily returns (lookback_days window)
  2. Fetch factor_series daily returns (same window)
  3. Run OLS regression / correlation / cross-corr / MI as appropriate
  4. If p_value < p_value_threshold AND r2 > min_r2:
       UPSERT instrument_tags SET
         weight = |beta|,          -- magnitude as weight
         source = 'empirical',
         p_value = p,
         sample_n = n,
         estimated_at = now(),
         evidence = {beta, r2, ci_lower, ci_upper, lookback_days}
     Else:
       SET valid_to = now()         -- expire the tag
       INSERT instrument_annotations (
         symbol, annotation_type='ai_insight', source='ai',
         content='Tag {tag} expired: p={p:.3f} over {n}d lookback. Beta={beta:.3f}.'
       )

5. Emit OTel metric: tag_calibration_total{symbol, tag, outcome=kept|expired}
6. Emit job_completed_total{job='tag-auditor', status=success|failure}
```

### Promotion path for AI discoveries

```
AI agent notices pattern
  → writes instrument_annotations (source='ai', type='ai_insight')
  → TagAuditor tests on next run
  → If passes: becomes empirical instrument_tag
  → Human reviews empirical tags periodically
  → Human promotes to tag_vocabulary if stable across 60+ days
```

### Regime conditioning (Phase 2)

Phase 1 computes unconditional betas. Phase 2 adds regime conditioning — the `instrument_tags` PK gains a `regime` dimension: `(symbol, tag, regime)` instead of `(symbol, tag)`. XLU's `rate_sensitive` beta in a high-vol regime is materially different from low-vol. Renaissance modeled everything regime-conditionally — static unconditional betas are a simplification that Phase 2 corrects.

The `cycle_position` tags (`early_cycle`, `mid_cycle`, `late_cycle`, `recession`) shipped in migration 121 as definitional human seed priors. They give downstream consumers a query handle before Phase 2 ships. Phase 2 regime conditioning — connecting instrument betas to HMM state — is the correct long-term implementation and supersedes them.

---

## Architecture fit

- **Ring 2 batch service** — `services/tag_auditor.py` as `TagAuditor`, timer-triggered like `roll_batch.py`
- **Reads:** `market_data_ohlcv` (daily returns), `instrument_tags`, `tag_vocabulary`, HMM regime output
- **Writes:** `instrument_tags` (empirical rows), `instrument_annotations` (expired tag notices)
- **OTel:** `job_completed_total{job='tag-auditor'}`, `tag_calibration_total{symbol, tag, outcome}`
- **Systemd:** `indicagent-tag-auditor.timer` + `.service` (weekly cadence, Sunday night)
- **DAG invariant:** DB-writing service, not a pipeline stage — correct

---

## What this unlocks

Any downstream consumer — AI agents, the dashboard, signal scoring — can query:

```sql
-- All empirically validated rate-sensitive instruments, ordered by beta magnitude
SELECT it.symbol, it.weight, it.p_value, it.evidence
FROM instrument_tags it
JOIN tag_vocabulary tv ON tv.tag = it.tag
WHERE it.tag = 'rate_sensitive'
  AND it.source = 'empirical'
  AND it.valid_to IS NULL
  AND it.p_value < 0.01
ORDER BY it.weight DESC;
```

That is a live, statistically grounded answer — not a human guess from months ago.

The regime classifier can use tag vectors as features: "give me all instruments with empirically validated `risk_off` + `rate_sensitive` tags" defines the flight-to-quality basket dynamically rather than by hand.

---

## Open question: signed magnitude access pattern (2026-07-01 design review)

`weight` (`instrument_tags.weight`) is unsigned, `[0.0, 1.0]`, magnitude-only per the live
CHECK constraint. Sign isn't actually lost by this design — `evidence` already captures it
(`{beta: -8.3, ...}`, signed) — but sign is only reachable by parsing unstructured JSONB
(`evidence->>'beta'`), not as a first-class queryable column. Fine for the current
`ORDER BY weight DESC` use case above, which only needs magnitude. Becomes a real question for
any consumer that needs direction — e.g. a cross-group directional relationship (does group A
move *with* or *against* group B — see `docs/ideas/cross-group-lead-lag-ic.md`) would need
signed values as a first-class access pattern, not an ad hoc JSONB extraction scattered across
call sites. Not resolved here — flagging so it's a deliberate decision (add a signed column
alongside `weight`, or standardize the JSONB extraction pattern) rather than something that
gets worked around inconsistently once a consumer actually needs it.

---

## Prior art within this system

- **`shadow_registry`** — same gatekeeping logic: n >= threshold, CI clears zero → promote; EV drops → demote. TagAuditor applies this discipline to tags.
- **`roll_batch.py`** — same timer-triggered oneshot pattern
- **HMM regime classifier** — already produces regime state; `mutual_information` measurement plugs directly in
- **`market_data_ohlcv`** — daily return series already available for all 58 equity instruments
