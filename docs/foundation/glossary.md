# Glossary

**Version:** 2.0
**Status:** active
**Last Updated:** 2026-06-20

---

## Purpose

This is the controlled vocabulary for IndicAgent. Every domain term has exactly one definition. When two terms could mean the same thing, one is canonical and the other is retired. Engineers, AI agents, and documentation use the canonical term — no synonyms, no loose usage.

A term is a mathematical claim. Using two terms for the same concept introduces two competing claims. One is wrong. Delete it.

This document feeds the naming system: `docs/foundation/naming-system.md` defines how to surface a concept across code layers; this document defines what the concept IS.

**Stage vs. mechanism:** `docs/intelligence/intelligence-layer-architecture.md` names
AlphaEngine's internal stages (Stage 0 Primitive Measurement, Stage 1 Stratification, Stage 2
Edge Measurement, Stage 3 Combination, Stage 4 Emission) generically, separate from the specific
statistical mechanism each stage currently uses (`FeatureFactory`, `HMM`, `IC`,
`Ensemble`/Ledoit-Wolf, threshold crossing). These are deliberately called "stages," not
"layers" — `Layer 1/2/3` already names the outer Prediction/Portfolio/Execution architecture
(see `AlphaEngine` below); the two numbering schemes are unrelated and must not be conflated.
Several entries below (`regime`, `Information Coefficient`, `AlphaEngine`) name a stage's
current mechanism; that doc is the canonical place the stage/mechanism distinction is made
explicit and should be consulted before assuming a mechanism name (e.g. "HMM") is the stage's
permanent identity.

---

## How to Use

When introducing a new concept:
1. Check this glossary first — it may already exist under a different name.
2. If new, add it here before naming it in code or docs.
3. If a term collision is found in existing code or docs, the glossary wins — update the code.

---

## Naming Convention

**Prefer industry-standard terms over project-specific names.**

When introducing a new concept:
1. Check if an industry-standard term exists (signal processing, feature engineering, ensemble, etc.)
2. Use the industry-standard term as the canonical glossary entry
3. Project-specific names (FeatureFactory, AlphaEngine) are implementation details, not the concept itself

**Rationale:** Industry terms are portable across teams, papers, and systems. Project-specific names should be reserved for truly unique inventions, not repackaged standard concepts. A new engineer should recognize the layer's purpose from its name, not learn project-specific jargon for standard concepts.

**Examples:**
- **Signal Processing Layer** (industry-standard) vs. "Feature Factory" (project-specific implementation)
- **Ensemble** (industry-standard) vs. "AlphaSwarm" (project-specific)
- **Feature Engineering** (industry-standard) vs. "Feature Factory" (project-specific)

When both exist, the industry-standard term is the concept; the project-specific name is the current mechanism. See `AlphaEngine` glossary entry for the stage/mechanism distinction.

---

## Core Trading Terms

### `signal`

A time-stamped, scored trade hypothesis with a defined entry, direction, and exit logic. Produced by I7 plugins. Persisted to `signal_events` (detection layer) with one or more corresponding `trade_frames` rows (hypothesis layer). Has a lifecycle: `pending` → `active` → `expired` / `regime_suppressed`.

**Not:** a Kafka message, an OTel metric, or a statistical signal-to-noise ratio. When "signal" appears in those contexts, use the domain-specific term instead: `message`, `metric`, `edge`.

**Banned:** (none)
**Status:** active

**Code surface:** `signal_events` table (Phase 128+), `SignalTracker`, `SignalWriter`. Legacy: `signal_ledger` monolith (read-only during v2.10 migration, dropped in Phase 130).

---

### `regime`

A discrete conditioning-state label that partitions bars into groups expected to behave differently downstream (IC stratification, ensemble weights, precedent retrieval). Produced by Stage 1 (Stratification) of the AlphaEngine internal layers — see that entry. Two coexisting mechanisms fill this contract today, each with its own sanctioned vocabulary (see `MEMORY.md` "Dual Regime System"):

- **Idiosyncratic regime** (aka **symbol regime**) — per-symbol `GaussianHMM` state (5 labels: `trending_down`, `transition_down`, `ranging`, `transition_up`, `trending_up`), fit per (symbol, timeframe) from log-return/vol-of-vol/relative-volume observations. Stored in `feature_vectors.regime`. "Idiosyncratic" is the standard factor-model term for a security-specific, non-market-wide component — parallels how `sensitivity`/`factor_regime` also operate at security scope.
- **Systematic regime** (aka **market regime**) — cross-sectional VIX×breadth state (9 labels: `{low/mid/high}_{bull/neutral/bear}`), one label per timeframe shared across the whole universe. Stored in `market_regimes`. "Systematic" is the standard factor-model term for the common, market-wide component every instrument shares exposure to.

**Not:** a synonym for "market condition" in general prose. Also not the HMM itself — `regime` is the Stage 1 *contract*; GaussianHMM (idiosyncratic) and the VIX×breadth model (systematic) are today's *mechanisms* filling it. (Not to be confused with the outer `Layer 1`/Prediction of the three-layer AlphaEngine/Portfolio/Execution architecture — different numbering, different scope.)

**Banned:** market condition, market state, market environment
**Status:** active

**Disambiguation:**
- `regime` (unqualified) — either regime system; qualify with `idiosyncratic`/`systematic` (or the informal `symbol`/`market`) when the distinction matters
- `idiosyncratic regime` / `symbol regime` — per-symbol HMM state (interchangeable synonyms)
- `systematic regime` / `market regime` — cross-sectional VIX×breadth state (interchangeable synonyms)
- `factor_regime` — a tag category describing conditional instrument performance: `risk_on`, `risk_off`, `defensive`, `growth`, `value`, `momentum`
- `volatility_regime` — a sub-classification of regime by realized vol level

**Code surface:** `feature_vectors.regime` (idiosyncratic/symbol, `regime_writer.py`), `market_regimes` (systematic/market, `equity_regime_model.py`), `factor_regime` category in `tag_vocabulary`.

---

### `regime_group`

A classification LABEL ON A SECURITY (which peer group it belongs to), not a regime itself. Analogous to `asset_class` but finer-grained and regime-signal-specific: TLT's `asset_class` is "equity" (its data-model type) but its `regime_group` is "rates" (the peer set relevant to its regime signal). Static per symbol — resolved once from `instrument_tags` via `tag_filter`, not recomputed per bar. Each group declares a `tag_filter` (resolves peer symbols at startup), a `signal_type` (`breadth_vol`, `curve_credit`, `commodity_momentum_ts`, `fx_dollar_carry`), and a `params_prefix` (APR namespace for that signal's thresholds). Defined in APR key `alpha.regime.groups`.

Contrast with `regime_label` — the actual STATE (e.g. `steep_tight`), one row per (`regime_group`, `tf`, `ts`), computed once for the whole peer group and joined onto every member's feature vector at query time (never materialized into `feature_vectors`).

Contrast with `feature_vectors.regime` — the per-symbol **idiosyncratic regime** (HMM trend label, see `regime` entry above), self-computed from that symbol's own price history, independent of `regime_group` entirely. `regime_group` instead names the peer set that feeds one **systematic regime** signal (also see `regime` entry above) — it answers "who counts as this market" so a group's cross-sectional composite (breadth×vol for equity, curve×credit for rates) can be computed at all.

Single-membership by design (`AmbiguousRegimeGroupError` — a symbol matching more than one enabled group fails loud) — scoped to defining the peer-set denominator for computing one group's aggregate signal. Does not attempt to capture instruments with genuine multi-group sensitivity (e.g. convertible bond ETFs, `PFF`-style preferreds, REIT-adjacent yield plays sensitive to both `equity` and `rates`) — that is a separate, deliberately deferred job (multi-label join driven by `instrument_tags.sensitivity`-category weights, todo 040/041), not this one.

**Banned:** (none)
**Status:** active

**Code surface:** `market_regimes.regime_group` column (migration 229, renamed from `asset_class`), `alpha.regime.groups` APR key, `src/intelligence/regime_signals/` signal modules.

---

### `conditioning layer` (aka `regime detection layer`)

The layer in the quant stack that detects market states and enables downstream processes to condition predictions on those states. **Internal project name** — emphasizes the stratification purpose (conditioning IC on regime). Takes primitive features (OHLCV-derived signals) as input, outputs categorical labels stamped onto each bar. Enables IC stratification, regime-conditioned ensemble weights, and precedent retrieval filtering.

**Industry-standard term:** `market state classification` — use that term for external communications, papers, and cross-system discussions. `conditioning layer` is used internally when emphasizing the statistical function (conditional prediction).

**Not:** synonymous with "HMM" — HMM is one implementation method for regime detection, not the layer itself. Other methods include percentile-rank bucketing, deterministic rules (session_position), threshold-based classifiers, change-point detection, and ML classifiers. See `StratificationDimension` protocol (`docs/research/intel-multi-regime-layer.md`) for the contract that all regime detection providers implement.

**See also:** `market state classification` (industry-standard equivalent)

**Synonyms:** `regime detection layer` — interchangeable; `conditioning layer` emphasizes the statistical function (stratified IC), `regime detection layer` emphasizes the operational function (detecting market states). Both refer to the same layer.

**Position in stack:** Between Primitive Feature / Signal Processing Layer (Feature Factory) and Alpha Generation / Execution Layer (IC Engine, Ensemble, AlphaEmitter).

**Banned:** (none)
**Status:** active

**Code surface:** `regime_writer.py` (per-symbol HMM), `equity_regime_model.py` (cross-sectional), future `StratificationDimension` providers.

---

### `market state classification`

Industry-standard term for the layer that detects and classifies market conditions (regime, volatility, trend). Also called **regime detection** or **market condition classification**. In this codebase, realized through `conditioning layer` and its `regime_classifier` implementations.

**Usage:** Use `market state classification` for external communications, papers, and cross-system discussions. This is the term other quants and researchers will recognize immediately.

**Internal name:** `conditioning layer` — used internally when emphasizing the statistical function (conditional prediction via stratified IC). See dedicated entry.

**Purpose:** Enable downstream processes to condition predictions on market context. Classification produces discrete labels per (symbol, tf, bar) that stratify IC measurements, ensemble weights, and precedent retrieval.

**Industry standard:** Quant systems universally stratify by market state — high/low vol, trending/mean-reverting, risk-on/risk-off. The classifier mechanism varies (HMM, threshold rules, ML, change-point detection) but the function is standard: context-aware prediction.

**See also:** `conditioning layer` (internal project name), `regime classifier`, `StratificationDimension` protocol (`docs/research/intel-multi-regime-layer.md`)

**Status:** active (multiple implementations)
**Banned:** "market detector," "state detector" (use `market state classification` or `regime detection`)

---

### `signal generation`

Industry-standard term for the process that converts predictive scores into actionable trade signals. A signal is a time-stamped, scored trade hypothesis with defined entry/exit logic. In this codebase, realized through `alpha emitter` functional slot.

**Industry standard:** Every quant system has a signal generation boundary — prediction produces a continuous score; signal generation applies thresholds, confidence gates, and risk filters to emit discrete actionable events. This is where "predictive model" becomes "trade decision."

**Our implementation:** `alpha emitter` (`alpha_publisher.py`) applies a four-gate stack —
`effective_n >= alpha.ensemble.effective_n_gate`, `|alpha_score| > alpha.quant.threshold.{tf}`
(per-timeframe only, not per-symbol/regime — see todo 065's EM-CAL calibration proposal for
whether per-regime granularity is ever earned), direction-aware CI + cost hurdle
(`(alpha_score>0 AND ci_lower>cost_hurdle) OR (alpha_score<0 AND ci_upper<-cost_hurdle)`), and
non-empty `top_features` — → `alpha_events` table.

**See also:** `alpha emitter`, `signal` (core trading term), `alpha_events`

**Status:** design (v3.0 Phase C)
**Banned:** "trade signaler," "emitter" as standalone (use `signal generation` or `alpha emitter`)

---

### `portfolio construction`

Industry-standard term for the layer that converts signals into positions. Takes emitted signals as input, applies position sizing, risk limits, and portfolio constraints, outputs trade frames. In this codebase, Layer 2 of the four-layer architecture.

**Industry standard:** Signal generation (Layer 1) and portfolio construction (Layer 2) are distinct concerns. A signal says "buy X"; portfolio construction says "buy N contracts of X given current portfolio, risk limits, and capital."

**Our implementation:** Planned as Layer 2 — reads `alpha_events`, applies Kelly-inspired sizing, regime-aware risk limits, correlation constraints, writes `trade_frames` (hypothesis layer) and eventually `trade_executions` (execution layer).

**See also:** `Signal Ledger Architecture`, `trade_frames`, `trade_executions`, `docs/signals/signal-trade-separation-ADR.md`

**Status:** design (v3.0, post-Phase C)
**Banned:** "position builder," "sizing layer" (use `portfolio construction`)

---

### `order management`

Industry-standard term for the layer that handles order routing, execution, and fill management. Takes trade frames from portfolio construction, routes orders to brokers/exchanges, tracks fills, records actual execution outcomes. In this codebase, Layer 3 (Execution) of the four-layer architecture.

**Industry standard:** Order Management System (OMS) is the industry term for the component that manages the lifecycle of an order from submission to fill. Key functions: order routing, split orders, partial fill handling, fill reconciliation, slippage measurement.

**Our implementation:** Layer 3 (Execution) — submits orders to IBKR, tracks fills via `trade_executions` table, records `actual_pnl_r` vs `counterfactual_pnl_r` for execution quality measurement.

**See also:** `trade_executions`, `counterfactual_pnl_r`, `execution layer` (SLA)

**Status:** design (v3.0, post-portfolio construction)
**Banned:** "execution engine," "trader" (use `order management` or `execution layer`)

---

### `signal processing layer`

The layer that transforms raw market data (OHLCV) into measurable features — deterministic, stateless transformations with no market theory embedded. These are primitives: different researchers with the same data compute identical numbers. Industry-standard term; see naming convention above.

**Current implementation:** `FeatureFactory` (54 features, I1-I4 cadence tiers)
**Output:** `FeatureVector` → `feature_vectors` table
**Not:** synonymous with "Feature Factory" — FeatureFactory is the mechanism; signal processing layer is the generic concept. Other implementations could exist (different feature sets, different computation strategies) without changing what this layer IS.

**Distinction from theory-laden features:** Primitives like `body_ratio` or `overnight_gap_z` encode no market theory. Theory-laden features like `poc_dist_atr` or `sr_support_dist` assume support/resistance has meaning — they may have IC but they are not primitives.

**Synonyms:** `feature engineering layer` (ML community), `feature extraction layer` (signal processing). All refer to the same concept: raw data in, measurable features out.

**Status:** active (mechanism live)
**Canonical doc:** `docs/intelligence/intelligence-layer-architecture.md` Stage 0

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

## Instrument Vocabulary Terms

### `vocabulary`

The controlled set of valid tags and their categorical structure. Defined in the `tag_vocabulary` table. A vocabulary entry specifies: the tag name, its category, its description, and its measurement contract (factor series, method, lookback).

**Not:** `classification scheme` (see below — an external, authoritative, single-parent hierarchy; a vocabulary is flat and internally hypothesized) or `taxonomy` (see below — the tag vocabulary itself has no parent/child structure; a `taxonomy` is what a subtree seeded under `parent_tag` becomes). "Ontology" remains banned outright — no referent in this system.

**Banned:** ontology
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

### `calendar primitive`

A tier-0 atomic feature computed as a deterministic, stateless, O(1) function of the bar timestamp alone - no OHLCV input, no cross-bar state, no external event data. Cyclical calendar primitives ship as `_sin`/`_cos` pairs (the pair spans every phase of the cycle's first harmonic, so no turning point is assumed); linear ones as `[0, 1]` fractions with the `_position` suffix. The atomic calendar set encodes coordinates on natural calendar cycles (day, week, month, quarter, year, session); it never encodes event conjunctions or fitted boundaries - those are tier-1 interaction features with a stated hypothesis. Full doctrine: `docs/research/signal-temporal-atomic-primitives.md`.

**Not:** the tag-system sense of `primitive` above (known naming collision, unresolved - see that entry); not any feature merely correlated with time; not `above_wk_vwap` (price-dependent and stateful, grouped `calendar` in `feature_registry` for legacy reasons only, see todo 116).

**Banned:** temporal coordinate primitive, temporal primitive, time feature, seasonality feature
**Status:** active

**Code surface:** `feature_registry` rows with `tier='0_atomic'` and `group_name='calendar'`; calendar helpers in `src/intelligence/feature_factory.py`.

---

### Tag category taxonomy (`exposure`, `sensitivity`, `factor_regime`, `cycle_position`, `signal_role`, `macro_driver`)

**Note (Phase 146, T7):** `tag_vocabulary.category` is a display/organizational label only — it groups tags for narrative and dashboard purposes. The TagCalibrator (Phase 146's empirical calibration engine) never reads `category` for measurement logic; the measurement contract for a tag lives entirely in its `factor_series` and `measurement_type` columns. A tag's category does not determine whether or how it is measured.

**Collision rule:** two tags must not share the same `factor_series` value. `factor_series` identifies the one measurable factor-loading concept a tag represents (per the "concept over specific proxy" principle — the registered thing is a factor loading, not a specific proxy ticker); if two tags pointed at the same `factor_series`, they would be redundant measurements of the same underlying quantity under different names (the exact defect `credit_cycle`/`credit_risk` had before their Phase 146 merge — see the banned-alias note after `macro_driver` below).

The six categories below are the full CHECK-constrained set (migration 228, 2026-07's ETF expansion); the split from the original four (`exposure`, `regime`, `signal_role`, `macro_driver`) predates Phase 146 and is unaffected by this note.

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

### Banned aliases (tag taxonomy)

Tags retired from `tag_vocabulary` because they duplicated or invalidated another tag's measurement. Reintroducing a banned alias re-creates the exact defect its removal fixed — check this list before naming a new tag.

- **`credit_cycle`** — merged into `credit_risk` in Phase 146 (migration 237, 2026-07-17). Verified live: `HYG` and `LQD` each carried both tags at near-identical weights (HYG 0.9/1.0, LQD 0.8/0.8) — a genuine duplicate, not just a similarly-named tag, since both tags shared the same underlying `credit_risk` factor-loading concept. The other 6 `credit_cycle` holders (`IWM`, `PFF`, `XHB`, `XLF`, `XLY`, `XRT`) had their assignment migrated into a new `credit_risk` row at the same weight, not dropped. Do not reintroduce `credit_cycle` — use `credit_risk`.
- **`housing_cycle`** — deleted in Phase 146 (migration 237, 2026-07-17), not merged. Its sole holder (`XHB`) was also its own factor series — a self-regression tautology (the "measurement" was `XHB` regressed against `XHB`), a broken-concept deletion distinct from the `credit_cycle` merge above. If housing-sector sensitivity is needed again, it must be re-derived against a real, non-self factor series (e.g. a rates/housing-starts proxy), not resurrected under the old name.

---

### `classification scheme`

An external, authoritative, single-parent classification hierarchy for securities — e.g. GICS (Sector → Industry Group → Industry → Sub-Industry), ICB, or SIC. A security belongs to exactly one node per scheme; membership is a fact to sync from the scheme's authority (S&P/MSCI for GICS), not a hypothesis to test, and carries no `weight`/`source`/`evidence` — those columns would be meaningless for an authoritative assignment. Membership is effective-dated (`valid_from`/`valid_to`), since schemes reclassify securities over time (e.g. GICS's 2018 creation of Communication Services) and a backtest joining on today's membership leaks future information into the past.

**Not:** a `tag` or `vocabulary` entry — those are internally hypothesized and falsifiable; classification scheme membership is externally authoritative and not falsifiable by this system. Not a `taxonomy` — a taxonomy (below) is IndicAgent's own soft, weighted sub-classification; a classification scheme is a strict external one.

**Banned:** (none)
**Status:** design (`docs/research/platform-09-security-classification-hierarchy.md`; unscheduled, gated on individual-equities onboarding)

**Code surface (planned):** `classification_scheme`, `classification_node`, `instrument_classification` tables.

---

### `taxonomy`

A hierarchical subtree of `tag_vocabulary`, formed via the self-referencing `parent_tag` column (e.g. `therapeutic_area` → `indication` → `mechanism_of_action`). Unlike a `classification scheme`, a taxonomy is IndicAgent's own soft, hypothesis-shaped classification — membership lives in `instrument_tags` unchanged (weighted, multi-valued, `source ∈ human/empirical/ai`), and a taxonomy node is subject to the same TagAuditor falsification loop as any flat tag. A taxonomy never nests under a `classification scheme` node — custom sub-classifications (e.g. mechanism-of-action) cross scheme boundaries (a shared mechanism can span two different GICS sub-industries) and correlate with the scheme rather than extend it.

**Not:** the flat tag `vocabulary` itself (which has no parent/child structure) or a `classification scheme` (external, strict, single-parent, non-falsifiable).

**Banned:** (none)
**Status:** design (`docs/research/platform-09-security-classification-hierarchy.md`; unscheduled, gated on a concrete custom-classification research question)

**Code surface (planned):** `tag_vocabulary.parent_tag`.

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

A stateless computation unit in the I5-I7 intelligence pipeline (v3.0+). Receives a `FeatureVector`, returns derived signals or pattern detections. Has no Kafka connection, no DB access, no side effects.

**Not:** an agent, a service, or a daemon. Not a synonym for an I1-I4 measurement function — those are pure functions in the FeatureFactory, not plugins. Plugins operate on already-computed features; they apply theories about what combinations of features mean. Measurements do not have theories.

**v2.x note:** In v2.x, I1-I7 were all called plugins. In v3.0, I1-I4 were rewritten as pure measurement functions inside FeatureFactory. The term `plugin` now refers strictly to I5-I7 pattern and signal logic.

**Banned:** (none)
**Status:** active (v2.x I1-I7); v3.0 I5-I7 only

---

### `taxonomy`

A hierarchical classification system with explicit parent/child relationships between categories. Use only when describing a genuine tree structure — a system where categories contain sub-categories with inherited properties.

**Not:** a synonym for `vocabulary`. The tag system is a `vocabulary` — a flat controlled set of terms with measurement contracts. No tag inherits from another. If there is no hierarchy, use `vocabulary`.

**Banned:** (none)
**Status:** active

---

### `Intrinsic Confidence Composite (ICC)`

The 4-factor weighted score computed inside each I7 plugin from pattern-internal evidence only — price structure, volume confirmation, momentum alignment, and microstructure. Factor weights sum to 1.0. The output is `raw_confidence` on `signal_events`.

ICC is strictly pattern-internal. ECL vectors (CTF score, HMM weight, zone friction) are never inputs to it. Any extrinsic term in the ICC corrupts `raw_confidence` into a value the ML model cannot decompose — it cannot learn whether the extrinsic context helped or hurt.

**Not:** the CIS score (which aggregates across 6 evidence buckets from all tiers). ICC is computed at the plugin level, before CIS adjudication.

**Banned:** "intrinsic composite," "intrinsic score," "plugin confidence" (all replaced by ICC)
**Status:** active

**Code surface:** `raw_confidence` field on `signal_events`; `compose_confidence()` in `confidence_utils.py`; `factor_scores` JSONB; `docs/signals/signals-confidence-patterns.md`.

---

### `Shadow Governance (SG)`

The statistical lifecycle that governs promotion and demotion of all I7 plugins and AI agents. Auto-enrollment at startup → shadow observation (live data, zero production impact) → statistical evaluation → gate → promotion → continuous monitoring → automatic demotion.

**Gate:** `n >= 100` resolved signals AND `bootstrap_ci_lower(pnl_r) > 0.0` at 95% CI. Both conditions required. Sample size alone is not sufficient.

**Demotion:** `EV[R] < -0.05` for 3 consecutive evaluation cycles. Automatic and inviolable — cannot be overridden by configuration or manual DB edit.

**Not:** a logging mechanism or monitoring dashboard. SG is the statistical control loop that determines whether a component earns production influence.

**Banned:** "shadow mode" as a standalone system name (shadow mode is one phase of SG, not the whole system)
**Status:** active

**Code surface:** `shadow_registry` table; `shadow_registry_ensure()` at service startup; `ShadowTransitionEvent` on Kafka; `bootstrap_ci_lower()` in `src/core/stats_utils.py`.

---

### `Signal Ledger Architecture (SLA)`

The 3-table schema that captures the complete signal lifecycle: `signal_events` (detection layer) + `trade_frames` (hypothesis layer) + `trade_executions` (execution layer), with a join view that queries across all three.

The design separates three concerns that the legacy `signal_ledger` monolith conflated: the fact that a pattern fired (detection), what trade was hypothesized (hypothesis), and what was actually executed (execution). Each table is immutable after write and has its own retention contract.

**Join view naming:** Phase 128 creates `signal_ledger_full` joining all three tables. Phase 130 drops the legacy `signal_ledger` monolith and `signal_outcomes` table, then renames `signal_ledger_full` → `signal_ledger`. After Phase 130, `signal_ledger` is the canonical query surface for the SLA.

**Not:** the legacy `signal_ledger` monolith (read-only during SLA migration, dropped Phase 130). `signal_ledger_v2` is a banned name — version-suffixed names violate the naming system.

**Banned:** "3-table architecture," "v2.10 schema," "new signal schema," "signal_ledger_v2" (all replaced by SLA)
**Status:** active (Phase 128+)

**Code surface:** `signal_events`, `trade_frames`, `trade_executions` tables; `signal_ledger` view (renamed from `signal_ledger_full` in Phase 130); `docs/foundation/glossary.md` detection/hypothesis/execution layer entries.

---

### `Counterfactual Feedback Loop (CFL)`

The system that measures `counterfactual_pnl_r` for every `trade_frames` row regardless of execution status. Comprises the `CounterfactualTracker` daemon (which runs the simulation) and the `counterfactual_pnl_r` column on `trade_frames` (which records the result).

CFL closes Bias Layer 2: before CFL, ML models could only train on signals that were executed (those with `actual_pnl_r`). CFL ensures every signal hypothesis — including regime-suppressed and unadjudicated signals — has a measured outcome. This makes `counterfactual_pnl_r` the primary ML training target, replacing `actual_pnl_r`.

**Not:** a backtesting system (CFL measures forward outcomes on live price action, not historical fits). Not "counterfactual recording" (which names only the write step, not the full loop).

**Banned:** "counterfactual recording," "counterfactual tracking," "paper pnl system"
**Status:** archived — this v2.x SLA daemon never shipped past "planned" and the whole SLA
(`signal_events`/`trade_frames`/`trade_executions`) has no live consumer as of 2026-07-02
(see CLAUDE.md Architecture). The name `CounterfactualTracker` and the concept "measure the
outcome of a hypothesis regardless of execution" were both reused for a live v3.0
implementation over `alpha_frames` in Phase 142B+143 — see
`docs/intelligence/intelligence-alpha-frames-and-feature-lifecycle.md`. Same idea, unrelated
code; do not conflate the two when reading history.

**Code surface:** `CounterfactualTracker` daemon (archived); `counterfactual_pnl_r` column on `trade_frames` (archived); `signal_ledger_full` / `signal_ledger` view (see SLA). Live v3.0 equivalent: `alpha_frames.counterfactual_pnl_r`, written by `services/counterfactual_tracker.py`.

---

---

### `AlphaEngine`

The v3.0 prediction engine: FeatureFactory → IC Engine → Ensemble → alpha emission. The full Layer 1 (Prediction) of the four-layer architecture — Layer 0 (Data) → Layer 1 (Prediction) → Layer 2 (Portfolio) → Layer 3 (Execution); see `docs/intelligence/intelligence-alphaengine.md` "Three-Layer Architecture" (name kept for continuity, now describes four layers with Layer 0 made explicit). Parametric — measures Spearman IC between each `FeatureVector` column and subsequent forward returns, derives Ledoit-Wolf ensemble weights, scores every bar, emits `alpha_events` when `|alpha_score| > threshold AND ci_lower > 0`.

Runs entirely in the cold batch layer (weekly IC Engine, nightly Ensemble Builder, nightly Alpha Emitter). FeatureFactory runs in-process on the hot path, writing to `feature_vectors` as a DB sink only.

**Distinction from PrecedentEngine:** AlphaEngine is parametric (Spearman correlation across all observations on pre-specified features). PrecedentEngine is non-parametric (k-NN retrieval of similar historical bar states). PrecedentEngine is not a second AlphaEngine — its precedent-derived predictors register into and are weighted by this same engine, per the `PrecedentEngine` entry below. Gated: PrecedentEngine does not start until AlphaEngine demonstrates IC > 0 with p < 0.05.

**Not:** an enrichment annotator on `signal_events`. AlphaEngine replaces the I5-I7 plugin stack as the primary alpha source. It does not annotate the old signal architecture — it supersedes it.

**Plain role noun.** Services prefixed `alpha-`. APR namespace: `alpha.*`.

**Status:** pre-implementation (v3.0 Phase A-C)

**Canonical doc:** `docs/plans/2026-06-20-alphaengine-architecture.md`

**Internal stages:** `docs/intelligence/intelligence-layer-architecture.md` breaks this Layer 1
down further into Stage 0-4 (Primitive Measurement → Stratification → Edge Measurement →
Combination → Emission), naming each stage's contract separately from its current mechanism.
"Stage" is used there specifically to avoid colliding with this entry's `Layer 1`.

**Formerly called:** "Intelligence Vectors" (internal working name — avoid)

---

### `Stage 0` (Primitive Measurement)

AlphaEngine's first internal stage. Contract: raw OHLCV bar in, a fixed-width vector of scalar
measurements out. No theory, no conditioning on state. Current mechanism: `FeatureFactory`
producing `FeatureVector`.

**Not:** a synonym for `FeatureFactory` — `FeatureFactory` is the mechanism; Stage 0 is the
contract it fills. Not `Layer 1`/`Layer 2`/`Layer 3` (the outer Prediction/Portfolio/Execution
architecture) — unrelated numbering scheme, see `AlphaEngine`.
**Banned:** "measurement layer," "I1-I4" as a stage name (I1-I4 names the legacy plugin-tier
sub-structure *within* Stage 0's mechanism, not the stage itself)
**Status:** active (mechanism live); sub-tier taxonomy (`docs/research/feature-registry.md`'s
`0_atomic`/`1_interaction`/`2_theory`) proposed, not built
**Canonical doc:** `docs/intelligence/intelligence-layer-architecture.md`

---

### `Stage 1` (Stratification)

AlphaEngine's second internal stage. Contract: the `FeatureVector` corpus in, a discrete
conditioning-state label per bar out. Current mechanism: `regime`, produced by two coexisting
implementations — per-symbol `GaussianHMM` (**idiosyncratic**/**symbol** regime) and a
cross-sectional VIX×breadth model (**systematic**/**market** regime) — see `MEMORY.md` "Dual
Regime System" and the `regime` glossary entry for the sanctioned vocabulary distinguishing them.

**Not:** a synonym for `HMM` or `GaussianHMM` — those are the mechanism; `regime`/Stage 1 is the
contract. A different classifier (IOHMM, factor-augmented HMM, threshold rules) could fill this
slot without changing what downstream stages expect from it.
**Banned:** "HMM layer," "regime layer" as if regime IS the layer rather than its current output
**Status:** active (mechanism live); alternative stratification dimensions (Volume Regime,
Skew/Tail Regime) proposed and archived pending an orthogonality proof mechanism that does not
yet exist (see intelligence-layer-architecture.md's "gaps" section)
**Canonical doc:** `docs/intelligence/intelligence-layer-architecture.md`

---

### `Stage 2` (Edge Measurement)

AlphaEngine's third internal stage. Contract: a `FeatureVector` column (optionally stratified by
a Stage 1 label) plus forward returns in, a predictive statistic with a confidence interval out.
Current mechanism: `IC Engine`, using Spearman `Information Coefficient`.

**Not:** a synonym for `IC` or `Information Coefficient` — IC is the mechanism; Stage 2 is the
contract. Mutual information or other nonlinear-dependence measures are real, not-yet-built
candidates for an additional or alternative mechanism at this stage.
**Banned:** "IC layer" as if IC IS the layer rather than its current statistic
**Status:** active (mechanism live)
**Canonical doc:** `docs/intelligence/intelligence-layer-architecture.md`

---

### `Stage 3` (Combination)

AlphaEngine's fourth internal stage. Contract: many Stage-2-scored features in, one scalar
composite score per bar out. Current mechanism: `Ensemble`, IC-Sharpe-weighted with Ledoit-Wolf
covariance shrinkage, `alpha_score` output.

**Not:** a synonym for `Ledoit-Wolf` or any single `weight_method` — those are mechanisms; Stage 3
is the contract. This is the one stage where multiple mechanisms already coexist by design:
`weight_method ∈ {ic_proportional, v1_shrunk, mean_variance}` (142A/142B.1), A/B-judged per
(timeframe, regime) stratum.
**Banned:** "ensemble layer" as a mechanism-specific name (fine as a stage description, not as if
Ledoit-Wolf were the only possible weighting method)
**Status:** active, multi-mechanism (142A/142B.1 shipped `v1_shrunk`/`mean_variance` as code
paths; `ensemble_weights` currently holds only `weight_version='v1'` rows — see todo 058)
**Canonical doc:** `docs/intelligence/intelligence-layer-architecture.md`

---

### `Stage 4` (Emission)

AlphaEngine's fifth and final internal stage. Contract: a per-bar composite score in, a discrete
timestamped tradeable event out, gated on magnitude and confidence. Current mechanism: a
four-gate stack in `alpha_publisher.py` — `effective_n` floor, per-timeframe `|alpha_score| >
alpha.quant.threshold.{tf}` (not per-symbol/regime), direction-aware CI + cost hurdle, and
non-empty `top_features` — writing `alpha_events`.

**Not:** a synonym for "alpha emitter" as a service name — Stage 4 is the contract; the Alpha
Emitter component is one mechanism fulfilling it.
**Status:** active (mechanism live)
**Canonical doc:** `docs/intelligence/intelligence-layer-architecture.md`

---

### `PrecedentEngine`

The non-parametric pgvector retrieval substrate (v3.0). Embeds `FeatureVector` states as L2-normalized vectors in pgvector. Finds K nearest historical neighbors via HNSW index (cosine similarity). Returns what price did after each retrieved precedent at the canonical gradient horizons (fast/mid/slow/extended), joined from the existing `forward_returns` table. The null result ("no close precedents exist") is a first-class output and drives the OOD monitor.

A nightly `BaseBatch` job turns retrieved neighbor sets into ordinary predictor columns (`precedent_expected_r`, `precedent_hit_rate`, `precedent_ret_dispersion`, `precedent_nn_dist`, plus a conviction envelope and horizon-profile label) — there is no separate scoring/combiner system; this replaced the pre-rescope design's standalone Scoring Engine.

**Distinction from AlphaEngine — read this carefully, it was wrong before 2026-07-09:** PrecedentEngine is non-parametric (retrieves historical instances via k-NN); AlphaEngine is parametric (measures Spearman correlation on pre-specified features). But PrecedentEngine is **not** a second, independent system — its precedent-derived predictors register into and are measured/weighted by AlphaEngine's own IC machinery and ensemble, exactly like any parametric feature (D4 rescope, `docs/foundation/principles.md`'s "one model, one book" invariant). PrecedentEngine is a second *evidence source* feeding the one book, not a second book. An earlier version of this entry said "both are independent and additive" — that was a real error, since corrected; do not repeat it.

**Plain role noun** — `naming-system.md` plain_role_nouns. Services prefixed `precedent-` (e.g. `indicagent-precedent-bar-embedder`). APR namespace: `precedent.*`.

**Status:** design (pre-implementation, v3.0) — gated behind v3.15 (Phase 144/145) completing; retrieval hard-filters on regime labels, so the regime-model unification must land first.

**Canonical doc:** `docs/research/intel-precedent-engine.md` (the current, correct design — the D4 rescope). `docs/plans/archive/2026-06-20-analogengine-design.md` is the original pre-rescope design doc, superseded, kept for history only.

**Formerly called:** "CaseSubstrate" (renamed 2026-07-13 — "Substrate" was a generic materials/infra metaphor that didn't itself pass the Whiteboard Test; "Precedent" states the question the system answers in plain English and avoids collisions "Pattern"/"History" alternatives would have hit). Before that: "AnalogEngine" (renamed 2026-07-09 — "analog" collided with the electronics/signal-processing sense of the word in a codebase already dense with that vocabulary, see `naming-system.md` §1 Whiteboard Test). Before that: "VIL" / "Vector Intelligence Layer" (internal shorthand still acceptable in code comments).

---

### `MeasurementEngine`

**Status: a resolved question, not a pending build — correcting an earlier draft of this entry that called it "proposed, not built."** `intel-12` (`stratification-dimension-unification.md`) and `intel-13` (`intel-precedent-engine.md`) both build on "the Measurement Engine" as a settled arrival without either one defining it. It sounds like an unbuilt future concept; it is actually the *name for a question that was asked and answered* in `docs/research/measurement-ic-engine.md`, whose own header states **"D1's fallback is the landed state"** — not "D1 is pending."

**The question `MeasurementEngine` names:** should feature-level measurement (`ic_engine.py`), ensemble-level measurement (`ensemble_ic_engine.py`), and any future precedent-level measurement merge into *one* service/table, rather than staying separate? D1 (`.planning/research/2026-07-02-v3-topdown-architecture.md`) proposed this. The answer, re-verified twice (2026-07-03, 2026-07-06): **no — kernel-sharing is the permanent design, not an interim one.** `ic_math.py` already holds the shared stats primitives (Fisher-z/bootstrap CI, vectorized Spearman IC, HAC-corrected Sharpe); the two services stay separate on purpose (their walk-forward fold-stability gates deliberately differ per D-142A-R1 — that's divergence by decision, not drift waiting to be fixed). Full service/table unification remains available if a new argument justifies it, but nothing is currently driving toward it.

**Naming implication:** `ICEngine` is correctly named for what it does today — it computes IC (Information Coefficient, Spearman correlation), specifically, not a generalized measurement abstraction. `IC` is genuine, whiteboard-testable quant vocabulary (Grinold & Kahn), not a placeholder. Do not rename it to `MeasurementEngine`, and do not build a `MeasurementEngine` class on the strength of the name being used loosely elsewhere — the doc that would justify it already said no.

**Relationship to `predictive measurement` (below) — related but not the same question, and the two docs that define them never cross-reference each other.** `predictive measurement` is a real, built, named *slot* in the AlphaEngine Functional Layer Vocabulary — one stage of the Layer 1 pipeline, implemented today by `ic_engine.py`. Its own definition is already generic over *method* (IC is one of several it can hold); it recurs a second time at ensemble grain (Phase 142A's EIC, `ensemble_ic_engine.py` → `alpha_ensemble_ic`, measuring whether the ensemble's own combined `alpha_score` predicts returns) — same slot, same operation, different input and pipeline position, not a second slot needing its own name (see todo 114). `MeasurementEngine` is neither of these — it's the now-answered question of whether the *services implementing* recurrences of this slot should be one thing instead of several.

**Canonical doc:** `docs/research/measurement-ic-engine.md`. See also `predictive measurement` below (AlphaEngine Functional Layer Vocabulary).

---

### `Extrinsic Confidence Layer (ECL)`

The system of extrinsic confidence vectors that annotate an emitted signal as observable metadata about external market context. Current vectors: CTF score (I6 cross-timeframe alignment), HMM regime weight, zone friction, exhaustion state.

**ECL boundary invariant:** If a setup meets its intrinsic detection criteria, it fires. Always. Extrinsic vectors travel on the emitted signal as observable fields (`ctf_score`, `ctf_confirmed`, `zone_friction_score`) or in `context_features`. They are the inputs the ML model uses to learn which market contexts produce better outcomes. An extrinsic gate is a prior masquerading as a model — it removes training data from the ledger permanently and makes the model unauditable.

**Regime gate exception:** HMM regime weight suppresses signal *activation* (pending → regime_suppressed), not *emission*. The signal is written to `signal_events` before the regime gate is applied. This is correct: the ML model sees regime-suppressed signals and, once `counterfactual_pnl_r` is populated by the CounterfactualTracker, can learn whether the regime gate adds value empirically.

**Distinction from intrinsic confidence composite:** The intrinsic composite is a weighted sum of pattern-internal factors (price/volume/microstructure). Weights sum to 1.0. ECL vectors inform the ML attribution layer — they are features against which `counterfactual_pnl_r` is regressed, not combined into the composite.

**Individual components:** referred to as **extrinsic confidence vectors** (not "modifiers," not "multipliers," not "gates").

**Banned:** "CTF gate" (as a name for the pattern of suppressing signals on CTF absence), "zone friction gate," "extrinsic modifier," "extrinsic multiplier"
**Status:** active

**Code surface:** `ctf_score`, `ctf_confirmed`, `zone_friction_score` fields in `signal_events`; `capture_signal_features()` in `confidence_utils.py`; `docs/signals/signals-confidence-patterns.md`.

---

### `Adaptive Parameter Registry (APR)`

The system-wide registry of all tunable numeric values — detection thresholds, confidence weights, indicator periods, governance gates. Four tables (`config_schema`, `config_state`, `config_history`, `config_outbox`) and one service (`ConfigService`).

"Adaptive" is precise: APR parameters are not static config. They start as `[initial_estimate]` or `[conventional]` human opinions and evolve through evidence — ML discovery writes calibrated values after p < 0.05 and sufficient N. The `config_history` table is a first-class audit record of every parameter's evolution.

**Informal alias:** "param store" — acceptable in conversation, not in architecture docs or code comments.

**APR parameter lifecycle:** `seed → operator_tuning → ml_learned → user_override → ml_learned again`

**Banned:** "param store" in architecture docs or code comments, "config store," "config system"
**Status:** active

**Code surface:** `config_schema`, `config_state`, `config_history`, `config_outbox` tables; `ConfigService`; `docs/foundation/adaptive-parameter-registry.md`.

---

### `detection layer`

The layer of the 3-table signal architecture that records the raw fact of a pattern firing — when a plugin's intrinsic detection criteria were satisfied. One row per signal fire event. Carries the intrinsic quality signal (`raw_confidence`, `factor_scores`) and the extrinsic market context at fire time (`ctf_score`, `zone_friction_score`, `context_features`). Immutable after write (status excepted).

**Not:** a trade record. The detection layer records that a pattern was detected, not that anything was done about it.

**Table:** `signal_events`
**Banned:** "signal ledger" as the name for this concept (legacy monolith term).
**Status:** active (Phase 128+)

---

### `hypothesis layer`

The layer of the 3-table signal architecture that represents trade specifications derived from a detection event. One row per entry_type per signal — e.g. a single OFI divergence detection might produce an `at_close` frame and an `at_pullback` frame. Each frame is a falsifiable hypothesis: given this entry/stop/target, what would have happened?

`counterfactual_pnl_r` is the hypothesis layer's primary output — the measured outcome of each frame against actual subsequent price action, regardless of execution. This is the ML training target.

**Not:** an execution record. A hypothesis can exist without ever being executed.

**Table:** `trade_frames`
**Status:** active (Phase 128+)

---

### `execution layer`

The layer of the 3-table signal architecture that records live trade executions. One row per actual trade placed. Most hypothesis layer rows have zero corresponding execution rows — the vast majority of signal hypotheses are never executed. Contains actual fill prices, actual pnl_r, and exit details.

The gap between `counterfactual_pnl_r` (hypothesis layer) and `actual_pnl_r` (execution layer) is execution quality — slippage, timing, and selection bias from the aggregator.

**Table:** `trade_executions`
**Status:** active (Phase 128+)

---

### `counterfactual_pnl_r`

**Overloaded across two unrelated implementations — check the table column, not just the name.**

- **v2.x (archived):** on `trade_frames` — the outcome that would have been realized if a
  trade frame hypothesis had been executed as specified. Computed by the archived
  `CounterfactualTracker` daemon. No live consumer as of 2026-07-02 (see CLAUDE.md
  Architecture; SLA is archived).
- **v3.0 (live):** on `alpha_frames` — the realized R-multiple of a hypothetical trade design
  (entry/stop/target/hold-horizon) against actual subsequent price action, computed by the
  live `services/counterfactual_tracker.py` (`CounterfactualTracker(BaseBatch)`). Full
  mechanics: `docs/intelligence/intelligence-alpha-frames-and-feature-lifecycle.md`. This is
  the current meaning of the term going forward.

Both share the same underlying idea (measure the outcome of every hypothesis, not just
executed ones, to avoid survivorship bias) but are separate code paths on separate tables.

This is the ML training target for SignalRanker and all downstream ML models. Training on `actual_pnl_r` introduces survivorship bias (only executed signals have outcomes). Training on `counterfactual_pnl_r` eliminates it — every signal hypothesis has a measured outcome.

**Not:** a backtested result (which implies fitting to historical data). Counterfactual pnl_r is a forward measurement on live price action after signal emission.

**Banned:** "paper pnl," "simulated pnl"
**Status:** v2.x (`trade_frames`) archived; v3.0 (`alpha_frames`) active (Phase 142B+143, live)

---

### `CounterfactualTracker`

**Overloaded class name — two unrelated implementations across two milestones.**

- **v2.x (archived):** a daemon that measured `counterfactual_pnl_r` for every `trade_frames`
  row. Subscribed to the `signal_events` Kafka topic, held fully in-memory state
  (checkpointed to file on shutdown), no DB reads in the hot path. Never shipped past
  "planned" (Phase 130); the whole v2.x SLA it belonged to has no live consumer as of
  2026-07-02.
- **v3.0 (live):** `services/counterfactual_tracker.py`, a `BaseBatch` oneshot (not a daemon,
  no Kafka) that fills `alpha_frames` entry/stop/target geometry at T+1 open and runs a
  bar-by-bar exit state machine (stop/target/max-hold/IC-decay) to close frames and compute
  realized R. Full mechanics: `docs/intelligence/intelligence-alpha-frames-and-feature-lifecycle.md`.

**Status:** v2.x archived; v3.0 active (Phase 142B+143, live)

---

### `survivorship bias` (signal corpus)

The corruption of the ML training set caused by systematically excluding certain signal outcomes. IndicAgent has two distinct survivorship bias layers, each with a different mechanism and fix:

**Bias Layer 1 — emission suppression:** Extrinsic gates (CTF gate, zone friction gate, exhaustion guard) calling `no_signal()` before the signal is written to the ledger. The ML model never sees the suppressed cases — it cannot learn whether those setups were actually bad. The biased training set inflates the apparent quality of surviving signals. Fixed in Phase 123 (ECL boundary restoration).

**Bias Layer 2 — null outcome variable:** `pnl_r = NULL` for all regime-suppressed and unfilled signals because no trade was executed. ML models trained on `WHERE pnl_r IS NOT NULL` exclude all suppressed signals — the model has never measured what a high-quality pattern firing in a poor regime actually produces. Fixed by `counterfactual_pnl_r` on `trade_frames` (Phase 127-129) + CounterfactualTracker daemon (Phase 130).

**Banned:** (none)
**Status:** Layer 1 fixed Phase 123; Layer 2 addressed Phase 127-130.

---

### `Architecture Decision Record (ADR)`

A document that captures a significant architectural decision: the context that forced the choice, the decision itself, the alternatives considered and why they were rejected, and the consequences. ADRs are institutional memory - they exist so future maintainers understand *why* a design is the way it is, not just what it is.

ADRs in IndicAgent live at `docs/architecture/` and are named `<concept>-ADR.md`. Each ADR is written once the decision is locked (typically during a schema-design or architecture-hardening phase) and is not revised after the fact - it records what was decided and why at the time of decision.

**Not:** a spec (which describes what to build, not why it was chosen). Not a design doc (which may still be exploring options). An ADR records a closed decision.

**Banned:** "decision record," "design record," "architecture doc" (use ADR when the decision is locked)
**Status:** active

**Code surface:** `docs/signals/*-ADR.md`; first instance: `docs/signals/signal-trade-separation-ADR.md` (Phase 128).

---

---

### `intelligence vector`

An orthogonal source of alpha — a family of features derived from a distinct information domain, measured through IC, and combined into the ensemble. Vectors are statistically independent by design: combining them multiplies information rather than amplifying the same noise twice.

v3.0 vectors (V1 built first; V2+ gated on V1 demonstrating IC > 0):
- **V1 Quant:** FeatureFactory measurements from price, volume, market structure, and regime state. The 50-column `FeatureVector`. Built in Phase A.
- **V3 Macro:** Cross-asset signals — VIX z-score, yield curve slope, flight-to-quality. Regime-speed (slow-moving). Some columns already in V1 FeatureVector as macro context features; full vector adds breadth.
- **V5 Flow / V7 Qual:** (future) Order flow microstructure; qualitative AI sentiment.

**Not:** a synonym for "tier." I1-I4 are measurement layers within V1, not vectors themselves. Not a synonym for "signal" — a vector produces a score every bar; a signal is emitted only when the score crosses a threshold.

**Banned:** "intelligence channel," "signal source," "alpha source" (use `intelligence vector`)
**Status:** V1 design (v3.0 Phase A); V3+ gated

---

### `alpha score`

The z-scored ensemble prediction for a given bar — the IC-weighted linear combination of rank-normalized `FeatureVector` columns, normalized to standard deviation units within a rolling 20-day window. Stored in `ensemble_alpha.alpha_score`.

```
alpha_raw   = Σ sign(ic[f]) × centered_rank(feature[f]) × weight[f]
alpha_score = (alpha_raw - rolling_mean) / rolling_std   # z-scored, ~N(0,1)
```

Positive = composite features predict upward price movement. Negative = downward. Magnitude = strength relative to recent history. An `alpha_event` is emitted when `alpha_score` clears `alpha_publisher.py`'s four-gate stack: `effective_n` floor, `|alpha_score| > alpha.quant.threshold.{tf}` (per-timeframe, not per-symbol/regime), direction-aware CI + cost hurdle, and non-empty `top_features`.

**Not:** synonymous with `raw_confidence` (v2.x ICC, plugin-internal unsigned magnitude). Not the same as `counterfactual_pnl_r` (realized outcome). Not a per-feature score — `alpha_score` is the ensemble output, not any individual feature's contribution.
**Banned:** "plugin score," "direction score," "conviction score" (use `alpha_score`)
**Status:** design (v3.0 Phase C); stored in `ensemble_alpha` table

---

### `Information Coefficient (IC)`

The Spearman rank correlation between a predictor score observed at time `t` and the subsequent N-bar return. The primary empirical measure of a plugin's or vector's predictive power.

IC = 0.03-0.05 is meaningful in practice. IC = 0.10 is exceptional. IC is always measured with bootstrap confidence intervals — a plugin requires `IC_CI_lower > 0.0` at `n >= 100` observations to be considered predictive. IC is stratified by: timeframe, HMM regime, lookahead window (1/5/10/20 bars), and asset class.

IC is regime-conditional: the same plugin may have IC = 0.07 in trending regimes and IC = -0.01 in mean-reverting regimes. HMM regime conditions ensemble weights.

**Not:** mutual information (a different information-theoretic measure — though a candidate for a future *additional* Stage 2 mechanism; see `docs/intelligence/intelligence-layer-architecture.md` Stage 2). Not `calibrated_confidence` (v2.x post-calibration output probability). Not the Edge Measurement stage itself — IC is today's mechanism for that stage's contract, not a synonym for it.
**Banned:** "predictive power score," "signal quality score" (use `IC` or `information coefficient`)
**Status:** design (v3.0 Phase B); stored in `feature_ic_scores` table

---

### `ensemble alpha`

The per-bar table that stores `alpha_raw` and `alpha_score` for every (symbol, tf, bar_ts) once ensemble weights exist. The unconditional output of the AlphaEngine — every bar is scored regardless of whether it will trigger an emission. Populated by the nightly Ensemble Builder.

`ensemble_alpha` is the input to the Alpha Emitter, which filters for `|alpha_score| > threshold` and writes `alpha_events`. It is also the rolling window used by the Alpha Decay Monitor to recompute IC on recent data.

**Table:** `ensemble_alpha`

**Not:** a hand-crafted composite (weights come from IC Sharpe via Ledoit-Wolf, not human judgment). Not `raw_confidence` (v2.x plugin ICC). Not `alpha_events` — `ensemble_alpha` scores every bar; `alpha_events` only records threshold-crossing bars.
**Banned:** "combined score," "aggregate signal," "signal composite" (use `ensemble alpha`)
**Status:** design (v3.0 Phase C)

---

### `IC discovery`

The empirical process of measuring Information Coefficient for each `FeatureVector` column against subsequent forward returns, across regimes, timeframes, and lookahead windows. The mechanism by which edges are found rather than assumed.

IC discovery runs on `feature_vectors` × `forward_returns`. Output is persisted to `feature_ic_scores`. Features with `ic_ci_lower <= 0.0` at sufficient N are down-weighted to zero in the ensemble — they contribute nothing regardless of how theoretically compelling they seem.

The feature universe is fully pre-specified before any IC is measured. Adding features after observing results is p-hacking.

**Not:** shadow mode (shadow measures P&L after signal emission; IC discovery measures raw feature predictiveness before any emission threshold is applied). Not backtesting (IC is measured on a held-out walk-forward window, not the training window).

**Banned:** "signal discovery," "edge discovery," "alpha discovery" (use `IC discovery`)
**Status:** design (v3.0 Phase B); input: `feature_vectors` + `forward_returns`; output: `feature_ic_scores`

---

---

## v3.0 Primitive Measurements (I1-I4)

I1-I4 are not plugins. They are pure measurement functions — they measure real, observable market phenomena. They carry no theory about what the measurements mean. Theory belongs to I5-I7 (patterns, confluence, signals). The distinction matters: a measurement that returns wrong data is a bug to fix; a theory that doesn't pan out is evidence to record.

Rewritten in v3.0 as stateless functions inside `FeatureFactory`. No side effects, no Kafka, no DB access. Same input always produces the same output.

### `I1 — price dynamics`

Measurements of what price did: return magnitude, direction, position within bar, gap behavior. These are not predictions. They are factual descriptions of recent price action, normalized to be comparable across instruments and timeframes.

**What I1 measures:** momentum (5-bar and 20-bar log return z-scores), intrabar position (`range_position`, `bar_close_pos`), and overnight gap magnitude (`gap_z`).

**Why pure functions:** The same OHLCV bar always produces the same momentum_z_5. There is no state, no model, no judgment. If momentum_z_5 for SPY at 09:35 on 2026-06-20 is -0.8, it is always -0.8 regardless of when the function runs.

**Code surface:** `FeatureFactory._compute_price_dynamics()`. Output columns: `momentum_z_5`, `momentum_z_20`, `range_position`, `bar_close_pos`, `gap_z`.

---

### `I2 — volume and order flow`

Measurements of who participated and with what conviction. Volume tells you how many contracts traded; order flow tells you the directional intent behind that volume. These are observable facts from the tape — not inferences.

**What I2 measures:** volume intensity (`volume_z`, `rel_volume`), directional flow (`ofi_z`, `ofi_div`, `cvd_slope_z`), flow persistence (`cmf`), and the composite informed-trader signal (`informed_flow`).

**Why this is measurement, not theory:** `ofi_z` measures the imbalance between buyer-initiated and seller-initiated volume, z-scored. This is a fact about what happened in the order book. Whether that imbalance predicts future price is a theory — tested by IC measurement, not assumed.

**Code surface:** `FeatureFactory._compute_volume_flow()`. Output columns: `informed_flow`, `volume_z`, `ofi_z`, `ofi_div`, `cvd_slope_z`, `cmf`, `rel_volume`.

---

### `I3 — market structure geometry`

Measurements of where price is relative to the market's structural reference points: VWAP, value area, support/resistance, volatility envelope. These describe the geometry of the current bar's context within the larger price distribution.

**What I3 measures:** position relative to VWAP (`vwap_dev_sigma`), position within volume-based value area (`va_position`, `poc_dist_atr`), distance to nearest structural levels (`sr_support_dist`, `sr_resist_dist`), volatility context (`atr_z`, `vol_ratio`), and market character signals (`hurst`, `shannon`, `garch_ratio`).

**Why geometry, not pattern:** I3 describes where price is, not what it will do. `poc_dist_atr = 2.3` means price is 2.3 ATR units above the Point of Control. This is a measurement. Whether that distance predicts mean-reversion is an IC question.

**Code surface:** `FeatureFactory._compute_structure()`. Output columns: `vwap_dev_sigma`, `atr_z`, `vol_ratio`, `poc_dist_atr`, `va_position`, `sr_support_dist`, `sr_resist_dist`, `hurst`, `shannon`, `garch_ratio`.

---

### `I4 — regime state`

Measurements of what market regime the HMM classifier believes we are in, and with what confidence. Also includes macro context (VIX, yield curve, flight-to-quality) and temporal structure (session, calendar).

**What I4 measures:** HMM regime quality (`hmm_regime_prob`, `hmm_entropy`, `hmm_duration`), trend direction and strength (`hma_slope_z`, `adx`), macro context (`vix_z`, `flight_quality`, `yield_slope_z`), session state (`in_ny_session`, `in_london_kz`, `in_overlap`, `power_hour`, `opening_range`, `above_wk_vwap`), calendar cyclicals (`dow_sin`, `dow_cos`, `month_position`), and cross-timeframe alignment (`ctf_momentum`, `ctf_vwap_align`, `ctf_regime_align`).

**Why these survive:** Regime state is a real thing — the HMM is a model, but its output (`hmm_regime_prob = 0.87`) is a measurement of that model's certainty. Whether a high-confidence trending regime predicts IC in momentum features is an empirical question, not an assumption. Same for macro context: `vix_z` is a fact. Whether high `vix_z` conditions feature IC is discovered by stratified measurement.

**Oscillators (APR-backed periods):** RSI and CCI measurements live in I4 at three scales (`rsi_fast/mid/slow`, `cci_fast/mid/slow`). Periods stored in APR (`feature.period.rsi.*`) — not baked into column names. Aroon freshness (`aroon_fast`, `aroon_slow`) similarly. See `docs/foundation/adaptive-parameter-registry.md §Feature Indicator Periods`.

**Code surface:** `FeatureFactory._compute_regime()`. Output columns: all HMM, macro, session, calendar, CTF, oscillator columns.

---

## v3.0 Data Primitives

### `FeatureVector`

The typed struct of 50 measurements produced by FeatureFactory for a single (symbol, tf, bar). One row in `feature_vectors`. Contains exactly one value per I1-I4 measurement column — no JSONB, no nesting, no null-means-unknown ambiguity (null means the measurement was not computable for that bar, e.g. insufficient history).

The FeatureVector is the atomic unit of v3.0. Everything downstream — IC measurement, ensemble weighting, alpha scoring — operates on FeatureVectors. The feature universe is pre-specified in the `feature_vectors` schema; adding a new measurement requires a schema migration, which is the intentional gate that prevents feature proliferation.

**Not:** a plugin output (plugins receive FeatureVectors as input in I5-I7). Not a signal (signals are emitted when ensemble alpha crosses a threshold). Not a row in `intelligence_features` (v2.x JSONB table, superseded).

**Canonical doc:** `docs/plans/2026-06-20-alphaengine-architecture.md §FeatureVector Contract`
**Status:** design (v3.0 Phase A)

---

### `FeatureFactory`

The in-process computation unit that produces `FeatureVector` from raw OHLCV bars. Replaces the I1-I4 plugin registry. Runs on every bar inside `IntelligencePipeline` — same DAG position as the old plugin stack, same latency budget. Writes to `feature_vectors` table via `FeatureWriter` (cold sink; never blocks the hot path).

FeatureFactory is organized into cadence-matched tiers: bar-level (I1, I2, most of I3), session-level (intraday accumulators), regime-level (HMM, computed every 30 bars and cached), cross-asset (reads HTF cached state), calendar (pre-computed daily). The cadence matching eliminates recomputing slow signals at bar frequency.

**Not:** a service. FeatureFactory has no systemd unit, no Kafka subscription, no independent lifecycle. It is a library called by `IntelligencePipeline`.

**Code location:** `src/intelligence/feature_factory.py`
**Status:** design (v3.0 Phase A)

---

### `forward_returns`

The table of executable forward returns computed from `market_data_ohlcv` via LEAD() window functions. One row per (symbol, tf, bar_ts). Stores log returns at four lookahead windows (1/5/20/60 bars), completeness flags (was the return window complete or did we hit end-of-data?), and gap flags (was there a market-hours gap before the entry bar?).

The return formula is executable: `ln(open[T+N+1] / open[T+1])` — entry at open of T+1 (first executable bar), exit at open of T+N+1. Not `close[T] to close[T+N]`, which includes the unexecutable observation price as the entry.

**Table:** `forward_returns`
**Populated by:** Outcome Labeler batch job (reads `market_data_ohlcv`)
**Not:** a backtest. Labels are computed on actual historical prices, not simulated fills.
**Status:** design (v3.0 Phase B)

---

### `IC Sharpe`

The primary ensemble weighting signal. Computed as `mean(IC_t) / std(IC_t)` over a time series of IC values, each measured on non-overlapping windows of 2,000 independent observations. Measures not just whether a feature has IC, but whether it has *consistent* IC — a feature that is predictive in some windows and noise in others has low IC Sharpe even with high mean IC.

IC Sharpe requires at least 10 IC windows (20,000 independent observations minimum). Features below this threshold are not eligible for ensemble weighting regardless of their IC point estimate.

Ledoit-Wolf ensemble optimization uses the IC Sharpe time series (not raw IC) to build the covariance-adjusted weight vector. Features with high IC Sharpe and low cross-feature IC correlation earn the most weight.

**Annualized for cross-TF comparison:** `IC_Sharpe_annualized = IC_Sharpe_bar × sqrt(bars_per_year)`. The annualized form is for comparison only — ensemble weights use bar-unit IC Sharpe.

**Not:** a backtest Sharpe ratio (which measures P&L consistency). IC Sharpe measures predictive consistency, one step upstream.
**Status:** design (v3.0 Phase B); stored in `feature_ic_scores.ic_sharpe`

---

### `alpha decay`

The condition in which a feature's rolling IC bootstrap CI lower bound crosses zero, indicating its predictive power may no longer be distinguishable from noise in the current market regime. Triggers automatic weight zeroing in APR.

Alpha decay is a first-class system event, not a failure state. Features decay as market regimes shift and return when regimes become favorable again. The two-window recovery hysteresis (`ci_lower > 0` for 2 consecutive rolling windows before partial restoration) prevents toggling.

**Automated response:** `ensemble_weights.is_active = false` → APR `alpha.weights.<feature>.*  = 0.0` → logged to `config_history` with `changed_by = 'alpha_decay_monitor'`.

**Not:** feature removal. A decayed feature remains in `feature_vectors` and continues accumulating IC observations. It is re-evaluated on each weekly IC Engine run.

**Status:** design (v3.0 Phase E); monitored by `alpha-decay-monitor` batch service

---

### `alpha_events`

The table of emitted alpha signals in v3.0 — one row per (symbol, tf, bar_ts) where `|alpha_score| > threshold`. The v3.0 equivalent of v2.x `signal_events`. Carries direction (`long`/`short`), alpha_score, threshold used, weight_version, regime, top contributing features, and lifecycle status (`pending` → `labeled` → `expired`).

`alpha_events` is the boundary between prediction (Layer 1) and portfolio construction (Layer 2). The Portfolio layer reads `alpha_events` to construct trade frames; it does not read `ensemble_alpha` directly.

**Table:** `alpha_events`
**Not:** `ensemble_alpha` (which scores every bar). `alpha_events` is the filtered subset where the score crossed the emission threshold.
**Replaces:** `signal_events` in v3.0 (v2.x `signal_events` is archived, not migrated)
**Status:** design (v3.0 Phase C)

---

### `weight_version`

A monotonically increasing integer that identifies a specific set of ensemble weights in `ensemble_weights`. Incremented on every run of the Ensemble Builder that produces any weight change. All rows in `ensemble_weights` with the same `weight_version` form a complete, consistent weight set.

`ensemble_alpha` records the `weight_version` used to score each bar, creating a full audit trail: any historical `alpha_score` can be reproduced by finding the corresponding weight set.

**Not:** a schema version or pipeline version. `weight_version` tracks ensemble calibration; `pipeline_version` tracks feature computation.
**Status:** design (v3.0 Phase C)

---

## AlphaEngine Functional Layer Vocabulary

Generic names for the functional slots within Layer 1 (Prediction), ordered by pipeline
position. Each slot has a current implementation; the generic name survives if the
implementation changes. Use these terms in design docs, todos, and discussion rather than
naming specific formulas -- "the regime classifier now has two implementations" is a
statement about one slot, not two different things.

```
feature measurement  →  feature synthesis  →  regime classifier  →  predictive measurement
       →  ensemble optimizer  →  alpha scorer  →  predictive measurement (ensemble grain)  →  alpha emitter
```

`predictive measurement` recurs a second time after `alpha scorer` -- same slot, same
operation (does this predictor predict returns), different input (the ensemble's combined
`alpha_score` instead of a single feature column) and different grain. Not a second slot.

---

### `feature measurement`

The functional slot that transforms raw OHLCV bars into a typed vector of observable
quantities for a single (symbol, tf, bar). These are measurements -- factual descriptions
of what price, volume, and structure did -- not inferences or predictions. Runs on the
hot path on every bar.

**Current implementation:** `FeatureFactory` (54 features, I1-I4 cadence tiers)
**Output:** `FeatureVector` → `feature_vectors` table
**Not:** a storage or transport concern. Feature measurement is pure transformation --
input is a bar, output is a vector. No DB reads, no Kafka. Not `feature computation`
(retired) -- "computation" names mechanism; "measurement" names the mathematical role.

---

### `feature synthesis`

The functional slot that combines atomic measurements into higher-order composite
features, producing new FeatureVector columns that capture relationships between
primitives that no single measurement can express alone. Feature synthesis outputs are
treated as first-class features -- they flow through the same predictive measurement,
FDR correction, and ensemble weighting as atomic features. The predictive measurement
layer decides what survives; feature synthesis only proposes candidates.

Sits between feature measurement (atomic inputs) and predictive measurement (IC
validation). Creates new features from existing ones; those new features are then
independently evaluated.

**Current implementations:**
- Hand-authored composites in `FeatureFactory` (e.g., `informed_flow` combining OFI and
  volume signals; `garch_ratio` combining realized vs implied vol)
- 8 already-live interaction primitives (`vol_body_product`, `price_vol_corr_fast`, etc.)
  empirically confirmed (todo 037, 2026-07-10) to carry genuine incremental IC beyond
  their parent atomics -- 22.2% of tested cells passed
- Planned: Phase 150's curated Theory-Motivated Interaction Layer (≤50 features, each with
  a stated finance-theory hypothesis) -- NOT the systematic pairwise combinatorial generator
  once scoped as "Interaction Factory" (todo 019, deferred/superseded -- ROADMAP.md's Phase
  150 rejected the ~30K-candidate combinatorial approach on BH-FDR power grounds, a decision
  independent of todo 037's result)

**In v2.x:** I5-I7 plugin stack performed a form of feature synthesis, combining I1-I4
measurements into pattern-level scores (ICC). Distinction: v2.x synthesis was
human-defined and scores were traded directly. v3.0 synthesis is empirically screened --
predictive measurement validates every composite before it earns ensemble weight.

**Not:** the ensemble optimizer (which weights already-validated features). Feature
synthesis produces *candidates*; the ensemble optimizer weights *survivors*.

---

### `regime classifier`

The functional slot that assigns each bar a discrete label describing the current market
context, used to condition all downstream predictive measurement. A regime classifier
consumes `feature_vectors` (or raw OHLCV) and writes a label per (symbol, tf, bar_ts).

Aligns with the taxonomy `Classifier` type: assigns inputs to mutually exclusive
categories. Multiple regime classifiers can coexist, each producing an independent
stratification dimension. The predictive measurement layer is run stratified by any
combination.

**Current implementations:**
- Per-symbol HMM (`regime_writer.py`) → `feature_vectors.regime` (5 labels)
- Cross-sectional equity model (`equity_regime_model.py`) → `market_regimes` (9 labels)

**Not:** a synonym for `regime` (the label output). The regime classifier is the
process; `regime` is the result.

---

### `predictive measurement`

The functional slot that measures whether a predictor column predicts forward returns,
across regimes, timeframes, and lookahead windows. Produces a scored record per
(predictor, symbol, tf, regime, lookahead) that quantifies predictive strength and
statistical confidence.

Multiple predictive measurement methods can coexist, each capturing a different aspect
of the predictor-return relationship. The slot also recurs at two pipeline positions on
different grains, not just once:

- **Feature grain** (pre-weighting, between `regime classifier` and `ensemble optimizer`):
  measures whether each individual feature in the `FeatureVector` predicts forward returns.
  **Current implementation:** Spearman IC (`ic_engine.py`) → `feature_ic_scores`
- **Ensemble grain** (post-scoring, after `alpha scorer`): the same operation applied to
  the ensemble's own combined `alpha_score` instead of a single feature column -- does the
  *ensemble's* prediction predict returns, not just its inputs.
  **Current implementation:** Phase 142A's EIC, `ensemble_ic_engine.py` → `alpha_ensemble_ic`

Both recurrences are the same slot doing the same job at a different point in the
pipeline -- not two separate slots each needing their own name (see todo 114, which
corrected this entry's original feature-grain-only wording).

**Planned additions:** Mutual Information (`feature_mi_scores`), R²_OOS (column on
`feature_ic_scores`), IC decay curve (`feature_decay_profiles`) -- see todo 029
**Not:** a synonym for IC. IC is one predictive measurement method; the slot can hold
others. Say "the predictive measurement layer" when the statement applies regardless
of which method or grain is used.

---

### `ensemble optimizer`

The functional slot that derives a weight vector from the history of predictive
measurement scores, producing a covariance-adjusted weight per feature that maximizes
expected portfolio IR subject to constraints. Runs on a batch schedule (weekly or
nightly) whenever new IC scores are available.

**Current implementation:** Ledoit-Wolf shrinkage on IC Sharpe time series
(`ensemble_builder` batch service) → `ensemble_weights`
**Not:** the alpha scorer (which applies weights). The ensemble optimizer derives weights;
the alpha scorer applies them.

---

### `alpha scorer`

The functional slot that applies the current ensemble weight vector to each bar's
FeatureVector, producing a scalar score per (symbol, tf, bar_ts). Runs nightly on the
full `feature_vectors` history and in near-real-time on the hot path for live bars.

**Current implementation:** IC-weighted rank-normalized linear combination, z-scored
to standard deviation units → `ensemble_alpha.alpha_score`
**Not:** the alpha emitter (which filters scores above a threshold). The alpha scorer
scores every bar; the alpha emitter selects which bars to act on.

---

### `alpha emitter`

The functional slot that filters alpha scorer output and emits actionable events when
the score crosses a threshold with sufficient statistical confidence. The boundary
between Layer 1 (Prediction) and Layer 2 (Portfolio). Every emitted event is a
hypothesis that a position should be opened.

**Current implementation:** `alpha_publisher.py`'s four-gate stack (`effective_n` floor,
per-timeframe `|alpha_score| > alpha.quant.threshold.{tf}`, direction-aware CI + cost hurdle,
non-empty `top_features`) → `alpha_events` table
**Not:** a trading decision. The alpha emitter says "a score crossed threshold"; the
Portfolio layer (Layer 2) decides whether and how much to trade.

---

## See Also

- `docs/foundation/naming-system.md` — mechanical derivation of code surfaces from concept names
- `docs/foundation/principles.md` — the governing principles that determine why terms are defined this way
- `docs/foundation/adaptive-parameter-registry.md` — Adaptive Parameter Registry (APR) full specification
- `docs/signals/signals-confidence-patterns.md` — ECL definition and boundary invariant
- `docs/signals/signal-trade-separation-ADR.md` — 3-table architecture decision record (Phase 127+)
- `tag_vocabulary` table — the live controlled vocabulary for instrument tags
- `docs/research/platform-09-security-classification-hierarchy.md` — `classification scheme` vs. `taxonomy` design (GICS vs. custom sub-classification), unscheduled
- `docs/research/intel-multi-regime-layer.md` — StratificationDimension protocol for unified conditioning layer
