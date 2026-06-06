# Glossary

**Version:** 1.0
**Status:** draft
**Last Updated:** 2026-06-06

---

## Purpose

This is the controlled vocabulary for IndicAgent. Every domain term has exactly one definition. When two terms could mean the same thing, one is canonical and the other is retired. Engineers, AI agents, and documentation use the canonical term — no synonyms, no loose usage.

A term is a mathematical claim. Using two terms for the same concept introduces two competing claims. One is wrong. Delete it.

This document feeds the naming system: `docs/foundation/naming-system.md` defines how to surface a concept across code layers; this document defines what the concept IS.

---

## How to Use

When introducing a new concept:
1. Check this glossary first — it may already exist under a different name.
2. If new, add it here before naming it in code or docs.
3. If a term collision is found in existing code or docs, the glossary wins — update the code.

---

## Core Trading Terms

### `signal`

A time-stamped, scored trade hypothesis with a defined entry, direction, and exit logic. Produced by I7 plugins. Persisted to `signal_ledger`. Has a lifecycle: `pending` → `active` → `expired` / `regime_suppressed`.

**Not:** a Kafka message, an OTel metric, or a statistical signal-to-noise ratio. When "signal" appears in those contexts, use the domain-specific term instead: `message`, `metric`, `edge`.

**Banned:** (none)
**Status:** active

**Code surface:** `signal_ledger` table, `SignalTracker`, `SignalWriter`.

---

### `regime`

A discrete market state that conditions the behavior of indicators, signals, and factor relationships. Produced by the HMM classifier. Examples: trending, mean-reverting, high-volatility, low-volatility.

**Not:** a synonym for "market condition" in general prose. Regime is a specific technical term — it refers to a classified HMM state or a named factor performance state (see `factor_regime`).

**Banned:** market condition, market state, market environment
**Status:** active

**Disambiguation:**
- `regime` (unqualified) — the HMM-classified market state
- `factor_regime` — a tag category describing conditional instrument performance: `risk_on`, `risk_off`, `defensive`, `growth`, `value`, `momentum`
- `volatility_regime` — a sub-classification of regime by realized vol level

**Code surface:** `regime` column in `intelligence_features`, `RegimeClassifier`, `factor_regime` category in `tag_vocabulary`.

---

### `factor`

A measurable market force against which an instrument's sensitivity is computed. A factor has a canonical proxy instrument or index. Examples: equity factor (SPY), rate factor (TLT), credit factor (HYG).

**Not:** an intelligence pipeline tier (I1-I7), a risk factor in the colloquial sense, or a "factor ETF" (MTUM, QUAL). Those are instruments that express factor exposures, not factors themselves.

**Banned:** (none)
**Status:** active

**Disambiguation:**
- `factor` — a market force with a canonical measurement proxy
- `factor series` — the specific instrument used to proxy a factor (e.g. TLT for the rate factor)
- `factor loading` / `beta` — an instrument's measured sensitivity to a factor
- `factor ETF` — an instrument that tilts toward a factor; described by `eq_factor` exposure tag

---

### `alpha`

A statistically validated, repeatable edge — a pattern whose forward return expectation is non-zero after costs, measured with sufficient sample size and p < 0.05. Not performance. Not returns. Not an opinion.

**Not:** a synonym for "returns," "outperformance," or "good signal." Every use of "alpha" is a statistical claim, not a qualitative one.

**Banned:** outperformance
**Status:** active

**Code surface:** `AlphaSwarm`, `pnl_r` in `signal_ledger` (the measured alpha per signal).

---

### `edge`

The expected value of a signal or strategy per unit of risk, measured empirically. `edge > 0` means the pattern has positive expected value. `edge` is always quoted with a sample size and confidence interval.

**Not:** an intuition, a thesis, or a belief. Edge is a number. If you cannot state the p-value and sample size, you do not have an edge — you have a hypothesis.

**Banned:** (none)
**Status:** active

---

### `beta`

An OLS regression coefficient measuring an instrument's return sensitivity to a factor. Signed (direction) and scaled (magnitude). Computed over a defined lookback window with an associated p-value and r².

**Not:** the colloquial "market beta" alone. Every beta in this system names its factor: `equity_beta`, `rate_beta`, `gold_beta`. Unqualified `beta` is ambiguous and should not appear in code or docs.

**Banned:** (none)
**Status:** active

**Code surface:** `evidence` JSONB in `instrument_tags`, primitive names in `tag_vocabulary`.

---

### `weight`

A dimensionless scalar in [0.0, 1.0] expressing the strength or confidence of a relationship. Context always qualifies which weight:

**Disambiguation:**
- `instrument_tags.weight` — strength of an instrument's association with a tag; driven by beta magnitude after empirical calibration
- `cis_weight` / bucket weight — relative contribution of a CIS bucket to the overall confidence score
- `shadow_weight` — weight applied to a signal in shadow mode (does not affect live trading)

Unqualified `weight` in code is a naming violation. Always prefix with context.

**Banned:** (none)
**Status:** active

---

## Instrument Taxonomy Terms

### `vocabulary`

The controlled set of valid tags and their categorical structure. Defined in the `tag_vocabulary` table. A vocabulary entry specifies: the tag name, its category, its description, and its measurement contract (factor series, method, lookback).

**Not:** "taxonomy," "ontology," or "classification scheme" — these are synonyms that introduce ambiguity. The canonical term is **vocabulary**. The table is `tag_vocabulary`. The doc is this system.

**Banned:** taxonomy, ontology, classification scheme
**Status:** active

---

### `tag`

A named label applied to an instrument that describes a relationship between the instrument and a factor or role. A tag is a hypothesis — it asserts that a measurable relationship exists. Tags with `measurement_type != 'definitional'` are validated by the TagAuditor and expire if p > threshold.

**Not:** a metadata label, a category, or an attribute in the loose sense. Every tag is a falsifiable claim.

**Banned:** metadata label
**Status:** active

**Code surface:** `instrument_tags` table, `tag_vocabulary` table.

---

### `primitive`

A quantity directly computable from market data with no derivation from other primitives. The building blocks from which all tags are derived. Examples: `equity_beta`, `rate_beta`, `hurst_exponent`, `skewness`. A primitive has a defined measurement procedure, a factor series (or none, for time-series properties), and produces a scalar with a p-value.

**Not:** a tag. Tags are named regions derived from threshold queries on primitives. Primitives are the continuous underlying measurements.

**Banned:** (none)
**Status:** active

---

### `exposure`

A tag category describing what an instrument fundamentally IS — its asset class and market segment. Definitional — never empirically validated because the classification does not change with market conditions. Examples: `eq_broad`, `fi_treasury`, `crypto`.

**Not:** how an instrument behaves. Behavior is captured by `sensitivity`, `factor_regime`, and `macro_driver` tags.

**Banned:** (none)
**Status:** active

---

### `sensitivity`

A tag category describing how an instrument's price responds to factor moves. Empirically measured via beta regression. Examples: `rate_sensitive`, `credit_risk`, `inflation`. An instrument earns a sensitivity tag by having a statistically significant beta against the tag's factor series.

**Not:** exposure (what it is) or factor_regime (how it performs in a regime).

**Banned:** (none)
**Status:** active

---

### `factor_regime`

A tag category describing an instrument's conditional performance in a named market factor state. Examples: `risk_on`, `risk_off`, `defensive`, `growth`, `value`, `momentum`. Empirically measured via correlation or beta against factor proxies.

**Not:** sensitivity (which measures response to factor moves, not regime performance) or regime (the HMM state itself).

**Banned:** (none)
**Status:** active

---

### `cycle_position`

A tag category describing an instrument's historical outperformance relative to the economic cycle phase. Definitional human seed priors — `early_cycle`, `mid_cycle`, `late_cycle`, `recession`. Never empirically validated by the TagAuditor; superseded by HMM regime conditioning in Phase 2.

**Not:** a dynamic measurement. Cycle position tags are static institutional priors, not computed classifications.

**Banned:** (none)
**Status:** active

---

### `signal_role`

A tag category describing how an instrument functions within the portfolio and signal generation system. Examples: `benchmark`, `regime_classifier`, `leading_indicator`, `spread_leg`. Mostly definitional — the role is structural, not empirically derived.

**Not:** what the instrument IS (exposure) or how it behaves (sensitivity, factor_regime).

**Banned:** (none)
**Status:** active

---

### `macro_driver`

A tag category describing the primary macroeconomic force that drives an instrument's returns. Examples: `fed_policy`, `oil_price`, `china_demand`, `geopolitical`. Empirically measured via beta against a canonical macro proxy.

**Not:** sensitivity (which is a price-level response measurement). Macro driver identifies the causal force; sensitivity measures the magnitude of response.

**Banned:** (none)
**Status:** active

---

## Statistical Terms

### `p-value`

The probability of observing a result at least as extreme as the measured one, assuming the null hypothesis (no relationship) is true. A tag is retained if `p < p_value_threshold` (default 0.05). A tag with `p > threshold` is expired — the relationship is not statistically distinguishable from noise.

**Not:** a confidence level. p = 0.05 means 5% false positive rate, not 95% confidence that the relationship exists.

**Banned:** confidence level
**Status:** active

---

### `r²`

The coefficient of determination — the fraction of an instrument's return variance explained by the factor. Used as a secondary gate alongside p-value. A low r² tag may be statistically significant but practically irrelevant.

**Banned:** (none)
**Status:** active

**Code surface:** `min_r2` column in `tag_vocabulary`, `evidence` JSONB in `instrument_tags`.

---

### `mutual information`

An information-theoretic measure of statistical dependence between two variables that captures nonlinear relationships. Used to measure the `regime_classifier` tag — how much does the instrument's return distribution depend on HMM regime state?

**Not:** correlation, which only captures linear dependence. Mutual information detects any statistical dependency.

**Banned:** (none)
**Status:** active

**Code surface:** `measurement_type = 'mutual_information'` in `tag_vocabulary`.

---

### `cross-correlation`

Correlation computed at multiple time lags between two return series. Used to measure the `leading_indicator` tag — does the instrument's return at time t predict SPY's return at time t+k?

**Not:** contemporaneous correlation. Cross-correlation is a function of lag, not a single number.

**Banned:** (none)
**Status:** active

**Code surface:** `measurement_type = 'cross_correlation'` in `tag_vocabulary`.

---

### `half-life`

The time for a measured relationship's effective weight to decay to 50% of its estimated value. Applies exponential decay: `effective_weight = weight × exp(-days_since_estimated / half_life_days)`. Shorter half-lives for unstable instruments (high `beta_stability` variance); longer half-lives for stable relationships.

**Not:** the expiry date of a tag. A tag with decayed weight is not expired — it is discounted until re-estimated.

**Banned:** (none)
**Status:** active

**Code surface:** `half_life_days` (planned addition to `tag_vocabulary`), `evidence` JSONB field.

---

### `empirical`

Derived from statistical measurement on market data. An `source='empirical'` tag has been computed by the TagAuditor with p < threshold and r² > min_r2. Empirical rows take precedence over human rows for the same `(symbol, tag)` pair.

**Not:** "data-driven" in the loose sense. Empirical is a precision claim — it means the tag survived a defined statistical test on a defined lookback window.

**Banned:** (none)
**Status:** active

**Disambiguation:**
- `source='human'` — asserted by a human; seed prior; never auto-expired
- `source='empirical'` — computed and validated by the TagAuditor
- `source='ai'` — proposed by an AI agent; written to `instrument_annotations`; promoted to formal tag only after TagAuditor validation

---

## System Architecture Terms

### `daemon`

A Ring 2 runtime process that runs continuously, has a systemd unit, and connects to Kafka. Inherits `BaseDaemon`. Named by its mathematical role: `SignalTracker`, `BarAggregator`, `FeatureWriter`.

**Not:** any background process. Specifically: a `BaseDaemon` subclass in `services/` with a systemd unit.

**Banned:** (none)
**Status:** active

---

### `writer`

A daemon whose sole responsibility is persisting data from a Kafka stream to the database. Inherits `BaseWriter`. Performs no computation — computation happens upstream in the intelligence pipeline.

**Not:** any service that writes to the DB. A service that computes and writes is an `Analyzer` or `Tracker`, not a `Writer`.

**Banned:** (none)
**Status:** active

---

### `auditor`

A daemon that validates data integrity and self-heals. Reads from DB or streams, identifies violations, applies corrections. Examples: `SignalAuditor` (repairs signal lifecycle state), `TagAuditor` (validates tag statistical validity, expires failed tags).

**Not:** a logger or monitor. An auditor writes corrections, not just observations.

**Banned:** (none)
**Status:** active

---

### `tracker`

A daemon that maintains the state of a business object over time. Consumes events from Kafka, updates internal state, publishes derived events. Example: `SignalTracker` maintains signal lifecycle state.

**Not:** a monitor (which watches but does not maintain state) or a writer (which persists but does not compute state).

**Banned:** (none)
**Status:** active

---

### `plugin`

A stateless computation unit in the I1-I7 intelligence pipeline. Receives a data frame, returns a dict of computed features. Has no Kafka connection, no DB access, no side effects. Named `PascalCasePlugin`.

**Not:** an agent, a service, or a daemon. Plugins are called synchronously within `IntelligencePipeline`.

**Banned:** (none)
**Status:** active

---

## See Also

- `docs/foundation/naming-system.md` — mechanical derivation of code surfaces from concept names
- `docs/foundation/principles.md` — the governing principles that determine why terms are defined this way
- `tag_vocabulary` table — the live controlled vocabulary for instrument tags
