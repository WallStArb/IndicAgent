# Instrument Tag Auditor

**Version:** 1.4
**Status:** design history — Phase 146 (TAG-01) shipped complete 2026-07-17. For the current live architecture (schema, TagCalibrator's 3-pass engine, consumers, known gaps), see the canonical doc `docs/foundation/instrument-tag-registry.md`. This doc remains the record of the design reasoning (Simons-critique review rounds, F1-F9 findings) behind what shipped.
**Priority:** high
**Registered as ROADMAP Phase 146** (Empirical Instrument Tag Calibrator) — fully specced (TAG-01/02/03,
3 plans), **Depends on: Nothing upstream of Phase 141** — unblocked, ready to plan now regardless
of the in-progress 143.1-07 corpus rerun (TAG-01 runs OLS on `instruments`/`market_data_ohlcv`
daily returns vs. factor series, not on `feature_vectors`).
**Last Updated:** 2026-07-06 (Fable 5 first full review pass - see § Fable 5 Review at end)
**Tags:** instruments, tags, empirical, calibration, renaissance, factor-model

**Review note (2026-07-06, Fable 5):** first rigorous pass on this doc. Verdict: the problem
diagnosis is right and the layering is right, but the calibration loop as specced in v1.3
fails its own Simons critique on multiple-testing correction, tests the wrong null, and has
a `weight = |beta|` bug that violates the live CHECK constraint. All fixed concretely in the
review section; the revised loop there supersedes § Calibration loop below.

---

## Problem

The `instrument_tags` table holds human-asserted priors. "TLT is `rate_sensitive` with weight 1.0" is a belief, not a fact. It has no measurement procedure, no p-value, no lookback window, no expiry mechanism. A Renaissance-grade system cannot operate on beliefs — it needs falsifiable hypotheses and a falsification engine.

---

## Simons Critique

### The measurable primitives

> "You have 53 tags. I can measure 8 things precisely. The other 45 are either derivable from the 8 or they're noise. Delete them."

*(Count drift, noted 2026-07-06, Fable 5: the live vocabulary is 71 tags / 410 assignments as
of 2026-07-04, and the primitive tables below have grown to 19 entries since this quote was
drafted. The principle stands unchanged - a small measurable core, everything else derived or
deleted - read "8" as "the primitive set," not a literal count.)*

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

*(Superseded 2026-07-06, Fable 5 - this loop has three defects fixed in § Fable 5 Review:
no multiple-testing correction across ~1,600 simultaneous (symbol, tag) tests, `weight = |beta|`
violates the live `[0,1]` CHECK constraint, and single-run p>0.05 expiry causes sequential-test
flicker. Kept for history; the revised loop in the review section is the buildable spec. Also:
"nightly" here contradicts "weekly cadence, Sunday night" in § Architecture fit - weekly is
correct, weekly re-estimation of 252-day betas is already 97% window overlap run-over-run.)*

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

*(Resolved 2026-07-06, Fable 5 - finding F3 in the review section resolves this as a side
effect of fixing the `weight = |beta|` bug: `instrument_tags` gains a signed `loading` column
(standardized loading, `[-1, 1]`) and `weight` is defined as `|loading|`. Direction becomes a
first-class queryable column; `evidence->>'beta'` stays as raw-scale provenance only. The
paragraph below is kept as the original statement of the problem.)*

`weight` (`instrument_tags.weight`) is unsigned, `[0.0, 1.0]`, magnitude-only per the live
CHECK constraint. Sign isn't actually lost by this design — `evidence` already captures it
(`{beta: -8.3, ...}`, signed) — but sign is only reachable by parsing unstructured JSONB
(`evidence->>'beta'`), not as a first-class queryable column. Fine for the current
`ORDER BY weight DESC` use case above, which only needs magnitude. Becomes a real question for
any consumer that needs direction — e.g. a cross-group directional relationship (does group A
move *with* or *against* group B — see `docs/research/cross-group-lead-lag-ic.md`) would need
signed values as a first-class access pattern, not an ad hoc JSONB extraction scattered across
call sites. Not resolved here — flagging so it's a deliberate decision (add a signed column
alongside `weight`, or standardize the JSONB extraction pattern) rather than something that
gets worked around inconsistently once a consumer actually needs it.

---

## Open question: instrument-structural-state conditioning, distinct from market-regime conditioning (2026-07-02)

Phase 2 ("Regime conditioning" above) conditions beta on *market-wide* regime state — HMM
trend state or cross-sectional VIX/breadth. That's a real improvement over unconditional
betas, but it's not the same axis as an instrument whose factor loading is driven by its own
**structural state**, independent of what the market is doing. The clean example: a
convertible bond's delta to the underlying equity is a function of moneyness (how far the
stock price sits from the conversion price) — deep ITM, it trades like equity; deep OTM, it
trades like a straight bond. This is not slow drift (Phase 1's half-life decay doesn't capture
it — a convert can swing from equity-like to bond-like over weeks, not the 180-day default
half-life's timescale) and it is not conditioned on market regime (Phase 2 as scoped doesn't
capture it either — a convert's moneyness has nothing to do with whether the broader market is
in a high-vol or low-vol state; it's specific to that instrument's own conversion price vs.
current stock price).

**Not building this now.** No convertible-bond ETF (`CWB`, `ICVT`, or similar) exists in the
current 79-symbol universe (checked 2026-07-02) — the only hybrid-sensitivity example
currently live is `PFF` (preferred stock), whose equity/rates blend is comparatively stable
and reasonably served by Phase 1's rolling recalibration. Flagging this here specifically so
that if a convert-type or other option-embedded instrument (contingent convertibles, SPAC
warrant ETFs, etc.) ever enters the universe, Phase 2 doesn't get assumed to already handle
it. If it becomes real: the natural extension is a third conditioning axis alongside
`(symbol, tag)` and `(symbol, tag, regime)` — something like `(symbol, tag, instrument_state)`
where `instrument_state` is a per-instrument structural variable (for converts: moneyness
bucket) rather than a shared market regime. Needs its own measurement procedure per
instrument class; not a generalization of the existing regime-conditioning mechanism.

---

## Forward reference: hierarchical tags and basket factor series (2026-07-04)

`docs/research/stratification-security-classification-hierarchy.md` *(filename corrected 2026-07-06,
Fable 5 - the `platform-09-` prefix never existed on disk)* (individual-equities
classification design, unscheduled) touches this system in two ways, neither changing
anything built or planned here today:

1. **`tag_vocabulary` gains a nullable `parent_tag` self-FK** when the first custom
   sub-classification taxonomy (therapeutic area → indication → mechanism-of-action) is
   seeded. Existing flat tags stay `NULL`; `category` keeps its thematic-axis role.
   Strict GICS-style classification deliberately does NOT enter this table - it gets its
   own exclusive, effective-dated membership system; only the soft, hypothesis-shaped
   custom layer lives here, because `weight`/`source`/`evidence` is exactly the right
   membership model for it and this doc's calibration loop is its falsification engine.
2. **`factor_series` generalizes from a single symbol to a derived basket**: a
   hierarchical tag's factor series is the equal-weight return basket of its high-weight
   members, ideally residualized against the symbol's GICS industry basket so the tag
   must prove co-movement *incremental* to what sub-industry membership already explains.
   Same `beta_regression` machinery, one new way to construct the regressor.

---

## Prior art within this system

- **`shadow_registry`** — same gatekeeping logic: n >= threshold, CI clears zero → promote; EV drops → demote. TagAuditor applies this discipline to tags.
- **`roll_batch.py`** — same timer-triggered oneshot pattern
- **HMM regime classifier** — already produces regime state; `mutual_information` measurement plugs directly in
- **`market_data_ohlcv`** — daily return series already available for the full equity universe *(80 symbols since the ETF universe expansion; "58" was the pre-expansion count - corrected 2026-07-06, Fable 5)*
- **`ic_math.py` / `ic_engine.py`** *(added 2026-07-06, Fable 5)* — the statistical kernel this doc must reuse, not reimplement: Fisher z-transform CIs, correlation p-values, HAC machinery, and the BH-FDR run-level correction pattern. See review findings F1 and F4.

---

## Fable 5 Review (2026-07-06) — first full review pass

**Scope:** first rigorous review of this doc (no prior Fable pass, unlike its siblings).
Reviewed as a design for an unbuilt system - the question is whether the proposed
falsification engine actually delivers on the doc's own Simons critique, not whether it
matches live code. Cross-checked against `services/ic_engine.py`,
`src/intelligence/statistics/ic_math.py`, and
`docs/research/stratification-security-classification-hierarchy.md`.

**Verdict: right diagnosis, right layering, under-delivered engine - fixable in place.**
The problem statement ("beliefs with no measurement procedure") is exactly right, the
schema separation and provenance model are right, and the Simons-inversion instinct
(compute the factor vector, derive the tags) is the correct end-state. But the v1.3
calibration loop quietly reintroduces the belief problem it diagnoses: it runs ~1,600
simultaneous hypothesis tests per run with no multiple-testing correction, tests the wrong
null hypothesis, and writes a weight that violates the live schema. A falsification engine
whose own statistics are anticonservative is a belief generator with extra steps. Every
fix below stays inside the existing architecture; nothing structural changes.

### F1 — Multiple testing is the load-bearing gap (must fix before Phase 1 ships)

The loop tests every measurable `(symbol, tag)` pair at raw `p < 0.05`. With the 80-symbol
universe and ~20 measurable tags that is ~1,600 simultaneous hypotheses per run - roughly
80 expected false positives per run under the global null. The Simons-inversion / gap-discovery
mode makes it strictly worse: scanning the full factor matrix for any threshold crossing is
the garden of forking paths in its purest form. And weekly re-runs are uncorrected
sequential testing - a truly null `(symbol, tag)` pair will eventually pass by chance, get
written as `source='empirical'`, then flicker in and out on subsequent runs.

This is structurally the same problem `ic_engine.py` already solves for features
(module docstring: "BH-FDR multiple-testing correction"; `statsmodels multipletests` with
`alpha.ic.fdr_alpha`, storing `bh_adjusted_p` / `passes_fdr` per row). The calibrator must
apply the identical pattern:

- **Correct once per run, at run level:** collect the raw p-value for every measured pair
  into one vector, then `multipletests(p_vector, alpha=fdr_alpha, method='fdr_bh')`.
- **Store both:** `p_value` (raw, HAC-robust per F4) and `bh_adjusted_p` + `passes_fdr` on
  `instrument_tags` - mirroring `feature_ic_scores` columns, so downstream queries filter
  on `passes_fdr`, never on raw p.
- **BH validity:** instrument returns and factor series are positively cross-correlated;
  BH-FDR remains valid under positive regression dependence (PRDS) - the same argument
  `ic_engine` already relies on. If factor-series collinearity (TLT/IEF/SHY; VUG/VTV/MTUM)
  ever proves material, `ic_engine`'s cluster-representative refinement (one representative
  per correlated cluster enters `multipletests`) is the established in-house pattern to
  borrow. Not needed for v1.
- **Consequence for the schema:** the per-tag `p_value_threshold` column in
  `tag_vocabulary` is incoherent under run-level FDR (per-hypothesis alpha and run-level
  FDR control are competing regimes; keeping both invites silent misuse). Delete it
  (5-step: delete). The run-level knob is one APR key: `alpha.tag_auditor.fdr_alpha`
  (default 0.05, `[conventional]`, ML learning target: no).

### F2 — The loop tests the wrong null

Every derivation in this doc defines a tag by a *magnitude* claim (`rate_sensitive` =
`abs(rate_beta) > 0.4`), but the loop keeps a tag whenever `beta ≠ 0` is significant.
Those come apart in both directions: at n=252 a beta of 0.05 can be significant at
p<0.001 (trivially nonzero, economically meaningless - `min_r2` is a patch over exactly
this), and a marginal-sample beta of 0.6 can fail p<0.05 (economically large, expired
anyway). The hypothesis IS the threshold; test it. Revised keep condition, two gates:

1. **Existence:** `passes_fdr` on H0: loading = 0 (per F1, HAC SEs per F4).
2. **Relevance:** `|loading| >= tag_vocabulary.loading_threshold` - the derivation
   threshold, promoted from prose into a schema column. This replaces `min_r2`, which is
   redundant once loading is standardized (for univariate OLS, r² = loading²; two knobs
   encoding one quantity).

And expiry gets hysteresis: a single failing run must not expire a tag (sequential-test
flicker, F1). Expire only after `alpha.tag_auditor.expiry_consecutive_fails` (default 3,
`[initial_estimate]`) consecutive failing runs - the same promote-slow/demote-deliberate
discipline as `shadow_registry`, which this doc already cites as prior art but did not
actually apply.

### F3 — `weight = |beta|` is a bug against the live schema

The doc's own evidence example is `{beta: -8.3, ...}`; the doc's own open-question section
states the live CHECK constraint is `weight ∈ [0.0, 1.0]`. `weight = |beta|` = 8.3 fails
the CHECK - the loop as written crashes on its first strongly-loaded instrument (loud, at
least, but designed-in). Raw beta is also not comparable across instruments (a 3x levered
ETF has equity_beta ≈ 3 by construction; that is leverage, not signal strength). Fix by
standardizing:

- `loading = beta * σ_factor / σ_instrument` - the standardized loading, which for
  univariate OLS is exactly the return correlation, bounded `[-1, 1]`, comparable across
  instruments and across tags.
- `weight = |loading|` - satisfies the existing CHECK with no migration to `weight`.
- `loading` becomes a first-class signed column on `instrument_tags` - which resolves the
  "signed magnitude access pattern" open question above as a side effect (direction is
  queryable; `evidence->>'beta'` remains raw-scale provenance only).
- `loading_threshold` values in `tag_vocabulary` are then in correlation units, so one
  threshold semantics works for `beta_regression` and `correlation` measurement types
  alike - the factor-series mapping table's beta/correlation split becomes purely about
  estimation method, not about interpretation.

### F4 — Reuse the measurement kernel; do not grow a second one

The loop as specced implies bespoke OLS/correlation/CI/p-value code inside the service.
This repo already extracted shared IC math into `src/intelligence/statistics/ic_math.py`
precisely because three consumers were reimplementing the same statistics (todo 048). Hold
this design to that precedent from day one:

- **Reuse directly:** `_fisher_z_ci` (CIs for the `correlation` measurement type - loading
  IS a correlation after F3), `_p_values_from_ic` (correlation p-values), and the HAC
  pattern from `_hac_sharpe_nd`.
- **New math goes next to it:** `src/intelligence/statistics/factor_math.py` - pure
  functions, no DB, no config imports (duck-typed config protocol, same as
  `SharpeWindowConfig`). Contents: OLS loading with Newey-West (HAC) standard errors,
  lagged cross-correlation, mutual information vs a discrete state series.
- **HAC is not optional.** Daily-return volatility clustering makes plain OLS standard
  errors anticonservative - which compounds F1 (too-small p-values feeding an uncorrected
  multiple-testing procedure is the worst combination). `alpha.tag_auditor.hac_max_lag`
  (default 5, `[conventional]`).

### F5 — "Tests on next run" is not out-of-sample confirmation

The promotion path validates an AI-discovered tag "on the next run." With a 252-day
lookback and weekly cadence, the next run shares ~97% of its window with the run that
generated the hypothesis. That is the same data voting twice. Discovered (previously
unasserted) tags must be confirmed on data disjoint from the discovery window before the
row is treated as established: hold them in a `pending_oos` state (or simply
`source='empirical'` with `passes_fdr` but flagged in `evidence`) until they pass on
`alpha.tag_auditor.discovery_oos_days` (default 63 - one quarter, `[initial_estimate]`)
of post-discovery data. This mirrors `ic_engine`'s walk-forward embargo discipline: the
gate that separates measurement from confirmation is temporal disjointness, nothing less.

### F6 — Degenerate and contaminated regressions (silent-bias inventory)

1. **Self-regression tautology:** TLT carries `rate_sensitive`, whose factor series is
   TLT. The calibrator will regress TLT on itself, get loading = 1.0 / p ≈ 0, and
   "empirically confirm" a tautology forever. Skip `symbol == factor_series` pairs and
   write them as definitional-by-identity (annotation, not empirical row).
2. **Futures factor series:** CL front month has roll gaps; unadjusted returns put a
   spurious jump into every calibration window that spans a roll, contaminating every
   `oil_price` loading. Factor return series built from futures must be roll-adjusted
   (contract_metadata / roll_batch already knows the roll dates). Same applies if VIX
   futures ever replace the VIX-changes series for `vol_beta`.
3. **Phase 2 sample starvation:** conditioning on 9 cross-sectional regimes splits a
   252-day lookback into strata that can drop below 30 observations. Per-stratum gate:
   `alpha.tag_auditor.min_sample_n` (default 60, `[initial_estimate]`; the codebase
   precedent is `sample_size >= 30`, doubled here because HAC estimation needs headroom).
   And note: Phase 2 multiplies the hypothesis count by ~9 (→ ~14,000 tests/run), so F1's
   FDR correction is a hard prerequisite for Phase 2, not an enhancement.
4. **Metric cardinality:** `tag_calibration_total{symbol, tag, outcome}` is ~1,600 label
   combinations today and ~16,000 at 10x - that fails the 10x gate for the metrics
   backend. Labels should be `{tag, outcome}` only; per-symbol detail lives in the DB
   rows, which are the queryable artifact anyway.

### F7 — The half-life story contradicts itself between critique and schema

The Simons critique says `beta_stability` should drive per-instrument half-lives
("unstable instruments get shorter half-lives"). The schema then puts a single static
`half_life_days` on `tag_vocabulary` - per tag, shared by every instrument carrying it.
The critique's version is right and the schema can't express it. Fix without a new
column: the calibrator computes an effective per-row half-life
`clamp(tag_default * (universe_median_stability / instrument_stability), 30, 365)` and
writes it into `instrument_tags.evidence.half_life_days` (the evidence example already
shows a per-row `half_life_days` - the doc was one step from this already). Tag-level
`half_life_days` stays as the prior/default. Clamp bounds as APR keys
(`alpha.tag_auditor.half_life_min_days` / `half_life_max_days`). Fine to defer the
coupling to Phase 1.5; not fine to leave the contradiction unstated.

### F8 — The Simons inversion should be Phase 1, not a research item

The doc treats "run the calibration unconditionally across all instruments, derive tags
from the vector" as a future research item. With F1 in place it is actually the *simpler*
design, and it should be the day-one loop:

- Measuring all `(symbol, measurable-tag)` pairs instead of only asserted rows costs
  nothing extra - it is the same regression loop over a fixed matrix (~1,600 cells of
  252-point OLS; trivial compute, embarrassingly parallel if it ever matters).
- It fixes a subtle selection bias in the v1.3 loop: testing only human-asserted pairs
  conditions the FDR denominator on human beliefs. The full matrix gives BH-FDR its
  honest denominator.
- Discovery stops being a separate scanning mode: a "discovered tag" is simply a pair
  that passes F1+F2 gates where no row existed (then held for F5's OOS confirmation),
  and a "gap annotation" is a pair that passes with no human assertion. One uniform
  measurement pass; assertion, validation, and discovery become three read-outs of the
  same matrix.

This deletes the Phase-1-vs-discovery split entirely. Human-asserted rows keep exactly the
role § Philosophy already gives them - seed priors, never auto-expired - but the engine
never special-cases them in measurement.

### F9 — Naming and housekeeping

- **`TagAuditor` overloads "auditor."** In this codebase auditors are health-check daemons
  (`BarAuditor`, `service_auditor.py`); this service estimates parameters, which is
  calibration. The filename already says `tag-calibrator`. Recommend concept name
  `tag_calibrator` → `TagCalibrator` → `indicagent-tag-calibrator.timer/.service` →
  `job='tag-calibrator'` (glossary one-term rule; naming-system derivation). Doc title
  left as-is pending the rename decision at planning time.
- **Extend `BaseBatch`** (`src/core/agent/base_batch.py`) - the "timer-triggered like
  roll_batch.py" framing predates it; BaseBatch is the house pattern for Phase 138+ batch
  services and gives D-06 `job_completed_total` for free.
- Count drift, cadence contradiction (nightly vs weekly), and the broken
  `platform-09-` forward-reference filename: corrected inline above, marked.

### Revised schema (supersedes § Schema additions)

```sql
ALTER TABLE tag_vocabulary
  ADD COLUMN factor_series      text,     -- canonical regressor ('TLT', 'HYG'); NULL for definitional
  ADD COLUMN measurement_type   text DEFAULT 'beta_regression'
      CHECK (measurement_type IN (
          'beta_regression', 'correlation', 'cross_correlation',
          'mutual_information', 'definitional')),
  ADD COLUMN lookback_days      int   DEFAULT 252,
  ADD COLUMN loading_threshold  float,    -- F2: the magnitude hypothesis, in correlation units
  ADD COLUMN half_life_days     int   DEFAULT 180;
  -- p_value_threshold: deleted (F1 - run-level FDR replaces per-hypothesis alpha)
  -- min_r2:            deleted (F2/F3 - redundant with loading_threshold; r² = loading²)

ALTER TABLE instrument_tags
  ADD COLUMN loading           float,    -- F3: signed standardized loading, [-1, 1]
  ADD COLUMN p_value           float,    -- raw, HAC-robust (F4)
  ADD COLUMN bh_adjusted_p     float,    -- F1
  ADD COLUMN passes_fdr        boolean,  -- F1
  ADD COLUMN consecutive_fails int DEFAULT 0,  -- F2 hysteresis
  ADD COLUMN sample_n          int,
  ADD COLUMN estimated_at      timestamptz;
-- weight (existing, CHECK [0,1]) := |loading|. No change to the column.
```

### Revised calibration loop (supersedes § Calibration loop)

```
weekly TagCalibrator (BaseBatch oneshot, indicagent-tag-calibrator.timer, Sunday night)

pass 1 - measure the full matrix (F8):
  for each (symbol, tag) in instruments x measurable tag_vocabulary rows
      where measurement_type != 'definitional'
        and symbol != tag.factor_series            -- F6.1
        and symbol has >= lookback_days daily bars:
    compute loading, raw HAC p-value, sample_n     -- factor_math.py (F4)
    collect (pair, p) into the run-level p-vector

pass 2 - correct once (F1):
  bh_adjusted_p, passes_fdr = multipletests(p_vector, alpha=fdr_alpha, method='fdr_bh')

pass 3 - decide per pair (F2):
  keep = passes_fdr AND |loading| >= loading_threshold
  keep, row exists:      UPSERT empirical row; consecutive_fails = 0
  keep, no row:          INSERT empirical row flagged pending-OOS until
                         discovery_oos_days of disjoint data confirm (F5);
                         if no human assertion either: gap annotation (ai_insight)
  fail, empirical row:   consecutive_fails += 1;
                         if >= expiry_consecutive_fails: valid_to = now() + annotation
  fail, human-only row:  never expired (seed prior, per § Philosophy); annotation notes
                         the measured contradiction so humans see it

OTel: tag_calibration_total{tag, outcome=kept|expired|discovered|pending} (F6.4)
      job_completed_total{job='tag-calibrator', status}
```

### APR keys introduced by this review

| Key | Default | Provenance |
|-----|---------|------------|
| `alpha.tag_auditor.fdr_alpha` | 0.05 | `[conventional]` |
| `alpha.tag_auditor.expiry_consecutive_fails` | 3 | `[initial_estimate]` |
| `alpha.tag_auditor.discovery_oos_days` | 63 | `[initial_estimate]` |
| `alpha.tag_auditor.min_sample_n` | 60 | `[initial_estimate]` |
| `alpha.tag_auditor.hac_max_lag` | 5 | `[conventional]` |
| `alpha.tag_auditor.half_life_min_days` | 30 | `[initial_estimate]` |
| `alpha.tag_auditor.half_life_max_days` | 365 | `[initial_estimate]` |

(Namespace note: `alpha.*` because this is measurement-stack machinery alongside
`alpha.ic.*`; per-tag knobs - lookback, loading_threshold, half-life default - correctly
live as `tag_vocabulary` columns, which is this system's data-driven analog of APR.
Swap the prefix to `tag_calibrator` if F9's rename lands.)

### CLAUDE.md 4-question gate

1. **10x volume?** Yes - 16,000 cells of 252-point univariate OLS is trivial compute, and
   run-level FDR is O(n log n) in the pair count. The one 10x failure was metric label
   cardinality; fixed in F6.4.
2. **Silent failures / hidden bias?** The v1.3 spec had five: uncorrected multiple testing
   (F1), anticonservative OLS SEs (F4), self-regression tautologies (F6.1), futures roll
   contamination (F6.2), and overlapping-window "confirmation" (F5). Plus one loud one:
   the weight CHECK violation (F3). All addressed above.
3. **DAG holds?** Yes - Ring 2 batch measurement oneshot (same exemption class as
   `ic_engine`), sole empirical writer to `instrument_tags`, no Kafka inter-stage pipe,
   reads regime state from the DB. Extending `BaseBatch` (F9) keeps it on the paved road.
4. **Manual step eliminated?** Hand-maintained tag weights and hand-enumerated tag
   discovery - and with F8, also the manual decision of *which* pairs to test.

### Sequencing

Phase 1 = F8's full-matrix loop with F1-F4 and F6.1-F6.2 built in (they are cheap at
design time and expensive to retrofit); F5's OOS confirmation gate in the same phase since
discovery is now day-one behavior. F7's stability-driven half-life is Phase 1.5. Phase 2
(regime conditioning) unchanged in intent, but gated on F1 by construction and on F6.3's
per-stratum sample gate.

## Open question: is the live 6-category `tag_vocabulary` taxonomy itself sound? (folded in from todo 041, 2026-07-13)

Before this calibrator builds empirical validation machinery *against* the 6 live
`tag_vocabulary.category` values (`exposure`, `sensitivity`, `factor_regime`, `cycle_position`,
`signal_role`, `macro_driver` — all precisely defined in `docs/foundation/glossary.md`), a real
scrutiny pass (not just glossary-consistency checking) surfaced three concrete problems and one
gap, not yet resolved:

1. **`signal_role` is a relational fact miscast as a unary attribute.** Live example: `SDOG`
   tagged `spread_leg` with evidence "VYM/SDOG broad vs sector-equal-weight yield spread." That
   tag only means anything in relation to `VYM` — not a property of `SDOG` alone. Likely wants
   its own table describing instrument *pairs*, or shouldn't be a persisted classification at
   all (a parameter on whichever analysis needs the spread, not a tag).
2. **`cycle_position`'s provisional status contradicts its `active` marking.** The glossary
   itself says these are "static institutional priors... never empirically validated... superseded
   by HMM regime conditioning in Phase 2" (see "On `cycle_position`" above) — a hardcoded belief
   standing in for a measurement this project's own principles (empirical over theoretical,
   segment by regime) say should replace it, yet it's marked `active` as if a stable peer of the
   empirically-measured categories.
3. **`macro_driver` may be redundant with `sensitivity`, not independent.** Both are described as
   "empirically measured via beta regression" against a proxy — same procedure, two names. Needs
   verification that e.g. `oil_price` (`macro_driver`) and `oil_beta` (`sensitivity`) aren't the
   same regression under different tags before this calibrator builds separate machinery for
   both.
4. **Sector granularity does not exist today** (verified live DB, 2026-07-12): of 80 active
   equity instruments, exactly one sector-adjacent tag exists (`sector_rotation`, 11 symbols) — a
   flat flag, not a GICS-sector-level taxonomy. Any future ask for finer-than-equity/rates
   `regime_group`s is blocked on this producing real sector tags first.

`exposure` and `sensitivity` are solid, map cleanly onto standard factor-model practice (loadings
vs. measured betas), and don't need re-litigating. Resolve the four items above before or
alongside this calibrator's Phase 1 build — building the empirical machinery first bakes any
confusion here into a real system rather than fixing it beforehand. Whatever this resolves to,
update `docs/foundation/glossary.md` to match — the glossary isn't immutable; a category that
fails scrutiny should be corrected there, not preserved because it's already documented.

**Resolved 2026-07-16** (see `docs/research/fable-2026-07-16-tag-calibrator-taxonomy-review.md`,
findings T2/T4/T5/T7, and `.planning/milestones/v3.1-phases/146-empirical-instrument-tag-calibrator/146-CONTEXT.md`):
item 1 (`spread_leg`) is salvageable via a data migration + boundary test, not a new table (T5).
Item 2 (`cycle_position`) closes via TAG-03's existing `measurement_type='definitional'`
annotation rule — no further action. Item 3 (`macro_driver`/`sensitivity` redundancy) is real but
confined to one pair: `credit_cycle`/`credit_risk` merge into `credit_risk` (T2); the categories
otherwise stay separate labels over one shared measurement contract (T7). Item 4 (sector
granularity) re-confirmed still absent and correctly out of this phase's scope. The review also
found a bigger blocker this open question didn't anticipate — 3 of the original 8 factor series
(VIX, USO, DXY) have zero usable live data — which forces a Wave 0 ahead of Phase 1's build; see
the review and the 146-CONTEXT.md for the full factor-series resolution (concept-over-specific-
proxy substitutions: UUP for dollar, FXI for china, HYG-IEF for credit, TIP-IEF for inflation,
IEF-SHY for curve, the existing `breadth_vol.py` SPY-realized-vol proxy for `vol_beta` instead of
VIX ingestion, and XLE-SPY long-short for `oil_beta` instead of the unavailable USO/CL — all 8
original betas end up measurable, none need deferral).
