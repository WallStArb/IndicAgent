# Glossary

**Version:** 2.0
**Status:** active
**Last Updated:** 2026-09-25

---

## Purpose

This is the controlled vocabulary for IndicAgent. Every domain term has exactly one definition. When two terms could mean the same thing, one is canonical and the other is retired. Engineers, AI agents, and documentation use the canonical term — no synonyms, no loose usage.

A term is a mathematical claim. Using two terms for the same concept introduces two competing claims. One is wrong. Delete it.

This document feeds the naming system: `docs/foundation/naming-system.md` defines how to surface a concept across code layers; this document defines what the concept IS.

**Stage vs. mechanism (historical):** `docs/intelligence/intelligence-layer-architecture.md`
named AlphaEngine's internal stages (Stage 0 Primitive Measurement through Stage 4 Emission)
generically, separate from the mechanism filling each stage (`FeatureFactory`, `HMM`, `IC`,
`Ensemble`/Ledoit-Wolf, threshold crossing); see the `AlphaEngine` and `Stage 0`-`Stage 4`
entries, all retired 2026-09-26. The distinction still matters: a mechanism name (e.g. "HMM")
is never a concept's permanent identity.

---

## How to Use

When introducing a new concept:
1. Check this glossary first — it may already exist under a different name.
2. If new, add it here before naming it in code or docs.
3. If a term collision is found in existing code or docs, the glossary wins — update the code.

---

**Rule fields (enforced by `tools/check_glossary.py`):** `**Banned:**` is a plain comma list of
exact terms, no quotes or notes, matched in prose and in identifiers (a multi-word term also
matches `CamelCase` and `snake_case` identifiers); a line the checker cannot parse fails the
check. `**Avoid:**` is contextual guidance, not enforced. `**Exempt:**` lists exact identifiers a
ban does not apply to, each needing a stated reason in the entry. `**Scope:**` (optional) limits
a ban to path globs. Two things are never violations: a term inside matching quotes or
backticks (a mention, as in this note), and a banned term inside a longer canonical term
(`market state classification` is not a use of a banned "market state"). Existing violations are held by `tools/glossary_baseline.json`: no file may
add a violation; cleanups lower the baseline.

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

A time-stamped, scored trade hypothesis with a defined entry, direction, and exit logic. **v2.x definition — the mechanism that produced it has no live consumer as of 2026-07-02** (see CLAUDE.md Architecture). Was produced by I7 plugins, persisted to `signal_events` (detection layer) with one or more corresponding `trade_frames` rows (hypothesis layer), with a lifecycle: `pending` → `active` → `expired` / `regime_suppressed`. `signal_events` is confirmed empty in production (verified 2026-09-04). The retired v3.0 analog was an `alpha_events` row (also deleted, phase 186); today the closest live concepts are the research layer's `attempt` and `book forecast` (E15), and `signal` itself is retired vocabulary in new code.

**Not:** a Kafka message, an OTel metric, or a statistical signal-to-noise ratio. When "signal" appears in those contexts, use the domain-specific term instead: `message`, `metric`, `edge`.

**Banned:** (none)
**Status:** retired (v2.x mechanism deleted; the v3.0 `alpha_events` chain was deleted in phase 186) — see `attempt` and `book` for the current research-layer equivalents

**Code surface:** `signal_events` table (Phase 128+, archived, 0 rows in production), `SignalTracker`, `SignalWriter` — `indicagent-signal-tracker-compute.service` and `indicagent-signal-writer.service` both `inactive (dead)` (verified 2026-09-04). Legacy: `signal_ledger` monolith (read-only during v2.10 migration, dropped in Phase 130).

---

### `regime`

A discrete conditioning-state label that partitions bars into groups expected to behave differently downstream (IC stratification, ensemble weights, precedent retrieval). Formerly produced by Stage 1 (Stratification) of the retired AlphaEngine internal layers (see that entry). Two coexisting mechanisms fill this contract today, each with its own sanctioned vocabulary (see `MEMORY.md` "Dual Regime System"):

- **Idiosyncratic regime** (aka **symbol regime**), per-symbol `GaussianHMM` state fit per (symbol, timeframe) from a 2-dimensional observation vector: realized volatility and volatility-of-volatility only. K (2 or 3 states) is configured by `alpha.hmm_volatility.n_components`; the live default is K=3 with labels `calm`, `elevated`, `turbulent`, ordered by realized volatility ascending. Fit walk-forward on an expanding window, so no parameter used to label a bar is ever estimated from data later than that bar. Stored in `feature_vectors.regime_volatility`. "Idiosyncratic" is the standard factor-model term for a security-specific, non-market-wide component, parallel to how `sensitivity`/`factor_regime` also operate at security scope.

  This design replaced an earlier 5-label composite (`trending_down`/`transition_down`/`ranging`/`transition_up`/`trending_up`, built from log-return, vol-of-vol, and relative-volume observations and stored in `feature_vectors.regime`) after a scrambled-data null-arm control found that only the volatility dimensions carried structure distinguishable from a `GaussianHMM`'s own tendency to split any sufficiently smooth series into artificial states: a real-vs-null margin of roughly +0.6 for realized volatility, versus a margin statistically indistinguishable from zero for the trend/log-return dimension at every window and timeframe tested. Trend and relative-volume were removed from the observation vector rather than deferred, because the null-arm result showed no signal to defer, not merely instability. The retired 5-label vocabulary had been naming directions the model was never actually separating on: the label-ranking column was the log-return dimension, and log-return carried no validated signal, so the composite regime had functioned as a volatility partition wearing trend-direction names since before this was discovered. `feature_vectors.regime` still exists and still carries that retired trend vocabulary during the phased cutover; it is no longer the stratification source for new measurement.

- **Systematic regime** (aka **market regime**), cross-sectional VIX×breadth state (9 labels: `{low/mid/high}_{bull/neutral/bear}`), one label per timeframe shared across the whole universe. Stored in `market_regimes`. "Systematic" is the standard factor-model term for the common, market-wide component every instrument shares exposure to.

**Not:** a synonym for "market condition" in general prose. Also not the HMM itself: `regime` is the Stage 1 *contract*; GaussianHMM (idiosyncratic) and the VIX×breadth model (systematic) are today's *mechanisms* filling it. (Not to be confused with the outer `Layer 1`/Prediction of the three-layer AlphaEngine/Portfolio/Execution architecture, different numbering, different scope.)

**Banned:** market condition, market state, market environment
**Status:** active

**Disambiguation:**
- `regime` (unqualified), either regime system; qualify with `idiosyncratic`/`systematic` (or the informal `symbol`/`market`) when the distinction matters
- `idiosyncratic regime` / `symbol regime`, per-symbol HMM state (interchangeable synonyms); today this means the volatility-only `calm`/`elevated`/`turbulent` labels above, not the retired trend composite
- `systematic regime` / `market regime`, cross-sectional VIX×breadth state (interchangeable synonyms)
- `factor_regime`, a tag category describing conditional instrument performance: `risk_on`, `risk_off`, `defensive`, `growth`, `value`, `momentum`
- `volatility_regime`, not a separate concept from the idiosyncratic regime above; this term should not be used to describe a second sub-classification. Use `idiosyncratic regime` (or the code name `regime_volatility`) instead.

**Code surface:** `feature_vectors.regime_volatility` (idiosyncratic/symbol, `regime_writer.py --regime-column regime_volatility`), `feature_vectors.regime` (retired trend vocabulary, phased cutover, no longer the stratification source), `market_regimes` (systematic/market, `cross_sectional_regime_model.py`), `factor_regime` category in `tag_vocabulary`.

---

### `regime_group`

A classification LABEL ON A SECURITY (which peer group it belongs to), not a regime itself. Analogous to `asset_class` but finer-grained and regime-signal-specific: TLT's `asset_class` is "equity" (its data-model type) but its `regime_group` is "rates" (the peer set relevant to its regime signal). Static per symbol — resolved once from `instrument_tags` via `tag_filter`, not recomputed per bar. Each group declares a `tag_filter` (resolves peer symbols at startup), a `signal_type` (`breadth_vol`, `curve_credit`, `commodity_momentum_ts`, `fx_dollar_carry`), and a `params_prefix` (APR namespace for that signal's thresholds). Defined in APR key `alpha.regime.groups`.

Contrast with `regime_label` — the actual STATE (e.g. `steep_tight`), one row per (`regime_group`, `tf`, `ts`), computed once for the whole peer group and joined onto every member's feature vector at query time (never materialized into `feature_vectors`).

Contrast with `feature_vectors.regime_volatility` - the per-symbol **idiosyncratic regime** (HMM volatility label, see `regime` entry above), self-computed from that symbol's own price history, independent of `regime_group` entirely. `regime_group` instead names the peer set that feeds one **systematic regime** signal (also see `regime` entry above); it answers "who counts as this market" so a group's cross-sectional composite (breadth×vol for equity, curve×credit for rates) can be computed at all.

Single-membership by design (`AmbiguousRegimeGroupError` — a symbol matching more than one enabled group fails loud) — scoped to defining the peer-set denominator for computing one group's aggregate signal. Does not attempt to capture instruments with genuine multi-group sensitivity (e.g. convertible bond ETFs, `PFF`-style preferreds, REIT-adjacent yield plays sensitive to both `equity` and `rates`) — that is a separate, deliberately deferred job (multi-label join driven by `instrument_tags.sensitivity`-category weights, todo 040/041), not this one.

**Banned:** (none)
**Status:** active

**Code surface:** `market_regimes.regime_group` column (migration 229, renamed from `asset_class`), `alpha.regime.groups` APR key, `src/intelligence/regime_signals/` signal modules.

---

### `conditioning layer` (aka `regime detection layer`)

The layer in the quant stack that detects market states and enables downstream processes to condition predictions on those states. **Internal project name** — emphasizes the stratification purpose (conditioning IC on regime). Takes primitive features (OHLCV-derived signals) as input, outputs categorical labels stamped onto each bar. Enables IC stratification, regime-conditioned ensemble weights, and precedent retrieval filtering.

**Industry-standard term:** `market state classification` — use that term for external communications, papers, and cross-system discussions. `conditioning layer` is used internally when emphasizing the statistical function (conditional prediction).

**Not:** synonymous with "HMM" — HMM is one implementation method for regime detection, not the layer itself. Other methods include percentile-rank bucketing, deterministic rules (session_position), threshold-based classifiers, change-point detection, and ML classifiers. See `StratificationDimension` protocol (`docs/research/stratification-dimension-unification.md`) for the contract that all regime detection providers implement.

**See also:** `market state classification` (industry-standard equivalent)

**Synonyms:** `regime detection layer` — interchangeable; `conditioning layer` emphasizes the statistical function (stratified IC), `regime detection layer` emphasizes the operational function (detecting market states). Both refer to the same layer.

**Position in stack:** Between Primitive Feature / Signal Processing Layer (Feature Factory) and Alpha Generation / Execution Layer (IC Engine, Ensemble, AlphaEmitter).

**Banned:** (none)
**Status:** active

**Code surface:** `regime_writer.py` (per-symbol HMM), `cross_sectional_regime_model.py` (cross-sectional), future `StratificationDimension` providers.

---

### `market state classification`

Industry-standard term for the layer that detects and classifies market conditions (regime, volatility, trend). Also called **regime detection** or **market condition classification**. In this codebase, realized through `conditioning layer` and its `regime_classifier` implementations.

**Usage:** Use `market state classification` for external communications, papers, and cross-system discussions. This is the term other quants and researchers will recognize immediately.

**Internal name:** `conditioning layer` — used internally when emphasizing the statistical function (conditional prediction via stratified IC). See dedicated entry.

**Purpose:** Enable downstream processes to condition predictions on market context. Classification produces discrete labels per (symbol, tf, bar) that stratify IC measurements, ensemble weights, and precedent retrieval.

**Industry standard:** Quant systems universally stratify by market state — high/low vol, trending/mean-reverting, risk-on/risk-off. The classifier mechanism varies (HMM, threshold rules, ML, change-point detection) but the function is standard: context-aware prediction.

**See also:** `conditioning layer` (internal project name), `regime classifier`, `StratificationDimension` protocol (`docs/research/stratification-dimension-unification.md`)

**Status:** active (multiple implementations)
**Banned:** market detector, state detector

---

### `signal generation`

Industry-standard term for the process that converts predictive scores into actionable trade signals. A signal is a time-stamped, scored trade hypothesis with defined entry/exit logic.

**Industry standard:** Every quant system has a signal generation boundary — prediction produces a continuous score; signal generation applies thresholds, confidence gates, and risk filters to emit discrete actionable events. This is where "predictive model" becomes "trade decision."

**Our implementation:** was the `alpha emitter` slot (`alpha_publisher.py`'s four-gate stack writing `alpha_events`), deleted in phase 186. The live successor concept is the `forward runner` (phase 188); the emission gating idea survives as E15's counted, pre-registered tests.

**Status:** design (v3.0 Phase C, never shipped); the v3.0 implementation was retired with the old chain
**Banned:** trade signaler
**Avoid:** "emitter" as a standalone name (use `signal generation`)

---

### `portfolio construction`

Industry-standard term for the layer that converts signals into positions. Takes emitted signals as input, applies position sizing, risk limits, and portfolio constraints, outputs positions.

**Industry standard:** Signal generation and portfolio construction are distinct concerns. A signal says "buy X"; portfolio construction says "buy N contracts of X given current portfolio, risk limits, and capital."

**Our implementation:** was planned as Layer 2 over `alpha_events`; never built, and the tables it would have read were deleted in phase 186. The live successor concept is the capital tier (`portfolio_state`, sizing, phase 188 of the unified design).

**Status:** design (v3.0, post-Phase C, never built); successor is the unified design's capital tier
**Banned:** position builder, sizing layer

---

### `order management`

Industry-standard term for the layer that handles order routing, execution, and fill management. Takes trade frames from portfolio construction, routes orders to brokers/exchanges, tracks fills, records actual execution outcomes. In this codebase, Layer 3 (Execution) of the four-layer architecture.

**Industry standard:** Order Management System (OMS) is the industry term for the component that manages the lifecycle of an order from submission to fill. Key functions: order routing, split orders, partial fill handling, fill reconciliation, slippage measurement.

**Our implementation:** never built; the Layer 3 sketch (IBKR order submission, `trade_executions`, execution-quality measurement) predates the unified design. The live successor concept is the unified design's execution tier (phase 188).

**Status:** design (v3.0, post-portfolio construction, never built); successor is the unified design's execution tier
**Banned:** execution engine
**Avoid:** "trader" as a system component name (use `order management` or `execution layer`)

---

### `signal processing layer`

The layer that transforms raw market data (OHLCV) into measurable features — deterministic, stateless transformations with no market theory embedded. These are primitives: different researchers with the same data compute identical numbers. Industry-standard term; see naming convention above.

**Current implementation:** `FeatureFactory` (I1-I4 cadence tiers; the "54 features" count is historical)
**Output:** `FeatureVector` → `feature_vectors` table
**Rebuilt table:** `feature_vectors_v2` (312 columns, PK `symbol, tf, bar_ts`, 1-year chunks) is written only by the rebuild writer through `bulk_load`, and takes the `feature_vectors` name at the swap in phase 186-27.
**Not:** synonymous with "Feature Factory" — FeatureFactory is the mechanism; signal processing layer is the generic concept. Other implementations could exist (different feature sets, different computation strategies) without changing what this layer IS.

**Distinction from theory-laden features:** Primitives like `body_ratio` or `overnight_gap_z` encode no market theory. Theory-laden features like `poc_dist_atr` or `sr_support_dist` assume support/resistance has meaning — they may have IC but they are not primitives.

**Synonyms:** `feature engineering layer` (ML community), `feature extraction layer` (signal processing). All refer to the same concept: raw data in, measurable features out.

**Status:** active (mechanism live; the "54 features" count and the Stage 0 framing above are historical - the current rebuild table is `feature_vectors_v2` becoming `feature_vectors` in phase 186-27)
**Canonical doc:** `docs/intelligence/intelligence-layer-architecture.md` (historical; Stage 0 is retired)

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
Two other uses of the letter are not this term: the significance level of a test (written "alpha / M" or "test level"), and the research code's `alpha[row, symbol]` arrays, which hold `predictor` scores.

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

A base feature computed as a deterministic, stateless, O(1) function of the bar timestamp alone - no OHLCV input, no cross-bar state, no external event data. Cyclical calendar primitives ship as `_sin`/`_cos` pairs (the pair spans every phase of the cycle's first harmonic, so no turning point is assumed); linear ones as `[0, 1]` fractions with the `_position` suffix. The atomic calendar set encodes coordinates on natural calendar cycles (day, week, month, quarter, year, session); it never encodes event conjunctions or fitted boundaries - those are interaction features with a stated hypothesis. Full doctrine: `docs/research/signal-temporal-atomic-primitives.md`.

**Not:** the tag-system sense of `primitive` above (known naming collision, unresolved - see that entry); not any feature merely correlated with time; not `above_wk_vwap` (price-dependent and stateful, grouped `calendar` in `concept_registry` for legacy reasons only, see todo 116).

**Banned:** temporal coordinate primitive, temporal primitive, time feature, seasonality feature
**Status:** active

**Code surface:** `concept_registry` rows with `metadata->>'composition' = 'base'` and `group_name = 'calendar'` (domain='feature'; `feature_registry`, the table this used to live in, was retired by migration 311, Phase 170); calendar helpers in `src/intelligence/feature_factory.py`.

---

### Tag category taxonomy (`exposure`, `sensitivity`, `factor_regime`, `cycle_position`, `signal_role`, `macro_driver`)

**Note (Phase 146, statistical_factor_residual):** `tag_vocabulary.category` is a display/organizational label only — it groups tags for narrative and dashboard purposes. The TagCalibrator (Phase 146's empirical calibration engine) never reads `category` for measurement logic; the measurement contract for a tag lives entirely in its `factor_series` and `measurement_type` columns. A tag's category does not determine whether or how it is measured.

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
**Status:** built (Phase 182, 2026-09-25; canonical doc `docs/foundation/security-classification-hierarchy.md`, design record `docs/research/stratification-security-classification-hierarchy.md`)

**Code surface:** `classification_scheme`, `classification_node`, `instrument_classification` tables; `ClassificationService` (`src/config/classification_service.py`); the `indicagent_v1` scheme.

**Note:** `indicagent_v1` is IndicAgent's own scheme (authority `IndicAgent`), not GICS: its equity levels reuse the public GICS names, but every assignment is IndicAgent's decision, recorded with a `source_ref`.

---

### `taxonomy`

A hierarchical subtree of `tag_vocabulary`, formed via the self-referencing `parent_tag` column (e.g. `therapeutic_area` → `indication` → `mechanism_of_action`). Unlike a `classification scheme`, a taxonomy is IndicAgent's own soft, hypothesis-shaped classification — membership lives in `instrument_tags` unchanged (weighted, multi-valued, `source ∈ human/empirical/ai`), and a taxonomy node is subject to the same TagAuditor falsification loop as any flat tag. A taxonomy never nests under a `classification scheme` node — custom sub-classifications (e.g. mechanism-of-action) cross scheme boundaries (a shared mechanism can span two different GICS sub-industries) and correlate with the scheme rather than extend it.

**Not:** the flat tag `vocabulary` itself (which has no parent/child structure) or a `classification scheme` (external, strict, single-parent, non-falsifiable).

**Banned:** (none)
**Status:** design (`docs/research/stratification-security-classification-hierarchy.md`; unscheduled, gated on a concrete custom-classification research question)

**Code surface (planned):** `tag_vocabulary.parent_tag`.

---

## Statistical Terms

### `p-value`

The probability of observing a result at least as extreme as the measured one, assuming the null hypothesis (no relationship) is true. A tag is retained if `p < p_value_threshold` (default 0.05). A tag with `p > threshold` is expired — the relationship is not statistically distinguishable from noise.

**Not:** a confidence level. p = 0.05 means 5% false positive rate, not 95% confidence that the relationship exists.

**Banned:** (none)
**Avoid:** "confidence level" as a synonym for a p-value (an interval's confidence level, such as
`confidence_level=0.95`, is a different and valid concept)
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
The same definition covers a research smoothing half-life (an exponential moving average of a `predictor` whose weights halve every half-life rows), chosen from the fixed menu in the multi-timeframe design (D3).

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

### `high-low spread` (`high_low_spread`)

The Corwin-Schultz (2012) bid-ask spread estimate from bar highs and lows, as a fraction of price. A bar's high-low range holds both volatility and the spread; the range over two bars holds twice the volatility but the spread once, so the two separate. Each two-bar estimate is overnight-adjusted, negative estimates are set to 0 (the paper's convention), and the stored value is the mean over `feature.high_low_spread.window` pairs. The window is counted in bars at every timeframe (one key for 5m, 15m, 1h and 1d); its monthly rationale holds only on 1d, levels are comparable only within one timeframe, and flat bars (high == low, about 1.7% of 15m bars since 2024) floor their pairs toward 0.

**Not:** `cross-sectional spread construction` (a portfolio-level long-short return), or a quoted spread (no quotes are read).

**Banned:** (none)
**Status:** active (todo 553, kernel `src/intelligence/features/kernels/liquidity.py`)

**Code surface:** feature column `high_low_spread` (feature_vectors_v2); APR `feature.high_low_spread.window`.

**Reach of a large move:** any large real price move, or a vendor step that survives arbitration, enters every Roll window holding its return (up to `window` rows) and up to 21 Corwin-Schultz window means. Vendor seams and bad prints are settled in the bar layer (D-191-Q arbitration, quarantine list), never in the kernel.

---

### `Roll spread` (`roll_spread`)

The Roll (1984) implied bid-ask spread, `2 sqrt(-cov)`, where `cov` is the serial covariance of consecutive log close changes over `feature.roll_spread.window` pairs, as a fraction of price. Bid-ask bounce makes consecutive price changes negatively correlated; a covariance of 0 or above implies no spread and the value is missing (NaN), never 0. Coverage is partial: about 40% of 1d rows after warmup are NaN (per-name median 0.41, p95 0.63 over 145 names), about 15% even on a simulated clean 1% spread. The missingness is informative (a non-negative serial covariance tracks trending regimes), so research must never treat a missing `roll_spread` as missing at random. The window is counted in bars at every timeframe; its yearly rationale holds only on 1d, levels are comparable only within one timeframe, and an intraday window spans overnight returns.

**Not:** `cross-sectional spread construction`, or Amihud illiquidity (`amihud_illiq_z`, price impact per dollar traded).

**Banned:** (none)
**Status:** active (todo 553, kernel `src/intelligence/features/kernels/liquidity.py`)

**Code surface:** feature column `roll_spread` (feature_vectors_v2); APR `feature.roll_spread.window`.

**Reach of a large move:** see `high-low spread`; the same holds for every Roll window that holds the move's return.

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
**Status:** archived — the entire I1-I7 plugin system (v2.x and the I5-I7 remainder carried into
v3.0) has no live consumer as of 2026-07-02; `indicagent-intelligence-pipeline.service` is
`failed` with its `ExecStart` pointing at a deleted file. Root `CLAUDE.md` marks I5-I7 archived
outright, not just dormant. See `src/intelligence/CLAUDE.md` top banner.

---

### `taxonomy`

**See the canonical `taxonomy` entry under Instrument Vocabulary Terms above** — this was a
duplicate definition of the same term, a direct violation of this glossary's own "exactly one
definition" rule; consolidated here rather than left as a second, driftable copy.

Short form: a hierarchical classification system with explicit parent/child relationships
between categories — use only when describing a genuine tree structure. Not a synonym for
`vocabulary`: the tag system (`tag_vocabulary`) is flat today (no `parent_tag` column exists in
the live schema, verified 2026-09-04); a taxonomy would be a self-referencing subtree of it, and
is currently `design`/unscheduled — see the canonical entry for the full distinction from
`classification scheme`.

---

### `Intrinsic Confidence Composite (ICC)`

The 4-factor weighted score computed inside each I7 plugin from pattern-internal evidence only — price structure, volume confirmation, momentum alignment, and microstructure. Factor weights sum to 1.0. The output is `raw_confidence` on `signal_events`.

ICC is strictly pattern-internal. ECL vectors (CTF score, HMM weight, zone friction) are never inputs to it. Any extrinsic term in the ICC corrupts `raw_confidence` into a value the ML model cannot decompose — it cannot learn whether the extrinsic context helped or hurt.

**Not:** the CIS score (which aggregates across 6 evidence buckets from all tiers). ICC is computed at the plugin level, before CIS adjudication.

**Banned:** intrinsic composite, intrinsic score, plugin confidence
**Status:** archived — computed inside the I7 plugin tier, which has no live consumer as of 2026-07-02 (see CLAUDE.md Architecture note and the `plugin` entry above).

**Code surface:** `raw_confidence` field on `signal_events`; `compose_confidence()` in `confidence_utils.py`; `factor_scores` JSONB; `docs/signals/signals-confidence-patterns.md`.

---

### `Shadow Governance (SG)`

**Legacy (retired 2026-09-26, unified design section 15.2):** the statistical lifecycle that was to govern promotion and demotion of I7 plugins and AI agents (auto-enrollment, shadow observation, gate at `n >= 100` resolved signals with `bootstrap_ci_lower(pnl_r) > 0.0`, demotion at `EV[R] < -0.05` for 3 consecutive cycles). Never shipped; the `shadow_registry` code surface does not exist.

**Not:** a logging mechanism or monitoring dashboard.

**Banned:** (none)
**Avoid:** "shadow mode" as the name of a whole system (shadow mode is one phase; as a practice, "shadow mode first", it is fine)
**Replacement:** the sealed shadow around frozen books (`BookTracker`, phase 188, unified design 7.3.6); the statistical gate idea survives in E15-E18.

---

### `Signal Ledger Architecture (SLA)`

The 3-table schema that captures the complete signal lifecycle: `signal_events` (detection layer) + `trade_frames` (hypothesis layer) + `trade_executions` (execution layer), with a join view that queries across all three.

The design separates three concerns that the legacy `signal_ledger` monolith conflated: the fact that a pattern fired (detection), what trade was hypothesized (hypothesis), and what was actually executed (execution). Each table is immutable after write and has its own retention contract.

**Join view naming:** Phase 128 creates `signal_ledger_full` joining all three tables. Phase 130 drops the legacy `signal_ledger` monolith and `signal_outcomes` table, then renames `signal_ledger_full` → `signal_ledger`. After Phase 130, `signal_ledger` is the canonical query surface for the SLA.

**Not:** the legacy `signal_ledger` monolith (read-only during SLA migration, dropped Phase 130). `signal_ledger_v2` is a banned name — version-suffixed names violate the naming system.

**Banned:** 3-table architecture, v2.10 schema, new signal schema, signal_ledger_v2
**Status:** archived — this v2.x schema has no live consumer as of 2026-07-02 (see CLAUDE.md
Architecture note). `signal_events` is confirmed empty in production (2026-09-04); the writer
daemons (`indicagent-signal-writer.service`, `indicagent-signal-tracker-compute.service`) are
`inactive (dead)`. Superseded by the v3.0 `alpha_frames`/`alpha_events` pipeline — see
`counterfactual_pnl_r` and `CounterfactualTracker` entries below for the v2.x/v3.0 split.

**Code surface:** `signal_events`, `trade_frames`, `trade_executions` tables; `signal_ledger` view (renamed from `signal_ledger_full` in Phase 130); `docs/foundation/glossary.md` detection/hypothesis/execution layer entries.

---

### `Counterfactual Feedback Loop (CFL)`

The system that measures `counterfactual_pnl_r` for every `trade_frames` row regardless of execution status. Comprises the `CounterfactualTracker` daemon (which runs the simulation) and the `counterfactual_pnl_r` column on `trade_frames` (which records the result).

CFL closes Bias Layer 2: before CFL, ML models could only train on signals that were executed (those with `actual_pnl_r`). CFL ensures every signal hypothesis — including regime-suppressed and unadjudicated signals — has a measured outcome. This makes `counterfactual_pnl_r` the primary ML training target, replacing `actual_pnl_r`.

**Not:** a backtesting system (CFL measures forward outcomes on live price action, not historical fits). Not "counterfactual recording" (which names only the write step, not the full loop).

**Banned:** counterfactual recording, counterfactual tracking, paper pnl system
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

**Legacy (retired 2026-09-26, unified design section 15.2):** belongs to the deleted ensemble chain; frozen tables and verdicts still use it. Replacement: the unified research-to-production pipeline (no single system name); IC measurement is `ic_measure`, combination is the research layer's combiner.

The v3.0 prediction engine: FeatureFactory → IC Engine → Ensemble → alpha emission, the full Layer 1 (Prediction) of the retired four-layer architecture (Data → Prediction → Portfolio → Execution). Parametric — measured Spearman IC between each `FeatureVector` column and subsequent forward returns, derived Ledoit-Wolf ensemble weights, scored every bar, emitted `alpha_events` when `|alpha_score| > threshold AND ci_lower > 0`. Ran as cold batch jobs (weekly IC Engine, nightly Ensemble Builder, nightly Alpha Emitter).

**Status:** retired — the whole chain (ensemble_trainer, ensemble_ic_engine, alpha_publisher, alpha_scorer, the `ensemble_alpha`/`ensemble_weights`/`alpha_events`/`alpha_frames` tables) was deleted in phase 186; `feature_vectors` and FeatureFactory remain live.

**Canonical doc:** `docs/plans/archive/2026-06-20-alphaengine-architecture.md`; replacement: `docs/plans/2026-09-26-unified-research-to-production-design.md`.

**Formerly called:** "Intelligence Vectors" (internal working name — avoid)

---

### `Stage 0` (Primitive Measurement)

**Legacy (retired 2026-09-26, unified design section 15.1):** AlphaEngine stage numbering is not used; pipeline stages are named (ingest, feature, measure, research, book, forward, capital, execution) and S0-S9 are research-layer sub-steps only.

AlphaEngine's first internal stage: raw OHLCV bar in, a fixed-width vector of scalar measurements out, mechanism `FeatureFactory` producing `FeatureVector`.

**Banned:** (none)
**Avoid:** "measurement layer" or "I1-I4" as a stage name (I1-I4 names the legacy plugin-tier
sub-structure *within* Stage 0's mechanism, not the stage itself)
**Status:** retired (2026-09-26). The feature tier taxonomy (`0_atomic`, `1_interaction`,
`2_theory`) is retired separately (migration 533, 2026-10-28): the `2_theory` split was not a real
distinction. A feature row carries `concept_registry.metadata->>'composition'`, `base` (computed
from a name's own bars or the timestamp) or `interaction` (built from other features); the two
codes are CVR namespace `composition` and `vocabulary_drift.py` audits it.
**Canonical doc:** `docs/intelligence/intelligence-layer-architecture.md` (historical)

---

### `Stage 1` (Stratification)

**Legacy (retired 2026-09-26, unified design section 15.1):** AlphaEngine stage numbering is not used; pipeline stages are named (ingest, feature, measure, research, book, forward, capital, execution) and S0-S9 are research-layer sub-steps only.

AlphaEngine's second internal stage: the `FeatureVector` corpus in, a discrete conditioning-state label per bar out, mechanism `regime` (dual regime system, see the `regime` entry).

**Banned:** (none)
**Avoid:** "HMM layer" or "regime layer" as if regime IS the layer rather than its current output
**Status:** retired (2026-09-26); the regime mechanisms themselves are live. Alternative stratification dimensions (Volume Regime,
Skew/Tail Regime) proposed and archived pending an orthogonality proof mechanism that does not
yet exist (see intelligence-layer-architecture.md's "gaps" section)
**Canonical doc:** `docs/intelligence/intelligence-layer-architecture.md` (historical)

---

### `Stage 2` (Edge Measurement)

**Legacy (retired 2026-09-26, unified design section 15.1):** AlphaEngine stage numbering is not used; pipeline stages are named (ingest, feature, measure, research, book, forward, capital, execution) and S0-S9 are research-layer sub-steps only.

AlphaEngine's third internal stage: a `FeatureVector` column (optionally stratified by a Stage 1 label) plus forward returns in, a predictive statistic with a confidence interval out, mechanism IC measurement (Spearman `Information Coefficient`).

**Banned:** (none)
**Avoid:** "IC layer" as if IC IS the layer rather than its current statistic
**Status:** retired (2026-09-26); IC measurement itself is live (`ic_measure`, see that entry)
**Canonical doc:** `docs/intelligence/intelligence-layer-architecture.md` (historical)

---

### `Stage 3` (Combination)

**Legacy (retired 2026-09-26, unified design section 15.1):** AlphaEngine stage numbering is not used; pipeline stages are named (ingest, feature, measure, research, book, forward, capital, execution) and S0-S9 are research-layer sub-steps only.

AlphaEngine's fourth internal stage: many Stage-2-scored features in, one scalar composite score per bar out, mechanism `Ensemble` (IC-Sharpe-weighted with Ledoit-Wolf covariance shrinkage, `alpha_score` output).

**Banned:** (none)
**Avoid:** "ensemble layer" as a mechanism-specific name (fine as a stage description, not as if
Ledoit-Wolf were the only possible weighting method)
**Status:** retired (2026-09-26); combination is now the research layer's `combiner`
**Canonical doc:** `docs/intelligence/intelligence-layer-architecture.md` (historical)

---

### `Stage 4` (Emission)

**Legacy (retired 2026-09-26, unified design section 15.1):** AlphaEngine stage numbering is not used; pipeline stages are named (ingest, feature, measure, research, book, forward, capital, execution) and S0-S9 are research-layer sub-steps only.

AlphaEngine's fifth and final internal stage: a per-bar composite score in, a discrete timestamped tradeable event out, mechanism `alpha_publisher.py`'s four-gate stack writing `alpha_events`.

**Status:** retired (2026-09-26); the closest live concept is the `forward runner` (phase 188)
**Canonical doc:** `docs/intelligence/intelligence-layer-architecture.md` (historical)

---

### `PrecedentEngine`

The non-parametric pgvector retrieval substrate (v3.0). Embeds `FeatureVector` states as L2-normalized vectors in pgvector. Finds K nearest historical neighbors via HNSW index (cosine similarity). Returns what price did after each retrieved precedent at the canonical gradient horizons (fast/mid/slow/extended), joined from forward returns (the `forward_returns` table at design time; deleted 2026-10 by phase 186 plan 23 — a revival computes them with the `panel.forward_returns` kernel). The null result ("no close precedents exist") is a first-class output and drives the OOD monitor.

A nightly `BaseBatch` job turns retrieved neighbor sets into ordinary predictor columns (`precedent_expected_r`, `precedent_hit_rate`, `precedent_ret_dispersion`, `precedent_nn_dist`, plus a conviction envelope and horizon-profile label) — there is no separate scoring/combiner system; this replaced the pre-rescope design's standalone Scoring Engine.

**Distinction from AlphaEngine — read this carefully, it was wrong before 2026-07-09:** PrecedentEngine is non-parametric (retrieves historical instances via k-NN); AlphaEngine is parametric (measures Spearman correlation on pre-specified features). But PrecedentEngine is **not** a second, independent system — its precedent-derived predictors register into and are measured/weighted by AlphaEngine's own IC machinery and ensemble, exactly like any parametric feature (D4 rescope, `docs/foundation/principles.md`'s "one model, one book" invariant). PrecedentEngine is a second *evidence source* feeding the one book, not a second book. An earlier version of this entry said "both are independent and additive" — that was a real error, since corrected; do not repeat it.

**Plain role noun** — `naming-system.md` plain_role_nouns. Services prefixed `precedent-` (e.g. `indicagent-precedent-bar-embedder`). APR namespace: `precedent.*`.

**Status:** design (pre-implementation, v3.0) — gated behind v3.15 (Phase 144/145) completing; retrieval hard-filters on regime labels, so the regime-model unification must land first.

**Canonical doc:** `docs/research/intel-precedent-engine.md` (the current, correct design — the D4 rescope). `docs/plans/archive/2026-06-20-analogengine-design.md` is the original pre-rescope design doc, superseded, kept for history only.

**Formerly called:** "CaseSubstrate" (renamed 2026-07-13 — "Substrate" was a generic materials/infra metaphor that didn't itself pass the Whiteboard Test; "Precedent" states the question the system answers in plain English and avoids collisions "Pattern"/"History" alternatives would have hit). Before that: "AnalogEngine" (renamed 2026-07-09 — "analog" collided with the electronics/signal-processing sense of the word in a codebase already dense with that vocabulary, see `naming-system.md` §1 Whiteboard Test). Before that: "VIL" / "Vector Intelligence Layer" (internal shorthand still acceptable in code comments).

---

### `MeasurementEngine`

**Status: a resolved question, not a pending build — correcting an earlier draft of this entry that called it "proposed, not built."** `intel-12` (`stratification-dimension-unification.md`) and `intel-13` (`intel-precedent-engine.md`) both build on "the Measurement Engine" as a settled arrival without either one defining it. It sounds like an unbuilt future concept; it is actually the *name for a question that was asked and answered* in `docs/research/measurement-ic-engine.md`, whose own header states **"D1's fallback is the landed state"** — not "D1 is pending."

**The question `MeasurementEngine` names:** should feature-level measurement (`ic_engine.py`, deleted 186-23; `ic_measure.py` now), ensemble-level measurement (`ensemble_ic_engine.py`, deleted 186-19), and any future precedent-level measurement merge into *one* service/table, rather than staying separate? D1 (`.planning/research/2026-07-02-v3-topdown-architecture.md`) proposed this. The answer, re-verified twice (2026-07-03, 2026-07-06): **no — kernel-sharing is the permanent design, not an interim one.** `ic_math.py` already holds the shared stats primitives (Fisher-z/bootstrap CI, vectorized Spearman IC, HAC-corrected Sharpe); the two services stay separate on purpose (their walk-forward fold-stability gates deliberately differ per D-142A-R1 — that's divergence by decision, not drift waiting to be fixed). Full service/table unification remains available if a new argument justifies it, but nothing is currently driving toward it.

**Naming implication:** `ICEngine` is correctly named for what it does today — it computes IC (Information Coefficient, Spearman correlation), specifically, not a generalized measurement abstraction. `IC` is genuine, whiteboard-testable quant vocabulary (Grinold & Kahn), not a placeholder. Do not rename it to `MeasurementEngine`, and do not build a `MeasurementEngine` class on the strength of the name being used loosely elsewhere — the doc that would justify it already said no.

**Relationship to `predictive measurement` (below) — related but not the same question, and the two docs that define them never cross-reference each other.** `predictive measurement` is a real, built, named *slot* in the AlphaEngine Functional Layer Vocabulary — one stage of the Layer 1 pipeline, implemented today by `ic_measure.py` (by `ic_engine.py` until phase 186 plan 23 deleted it). Its own definition is already generic over *method* (IC is one of several it can hold); it recurs a second time at ensemble grain (Phase 142A's EIC, `ensemble_ic_engine.py` → `alpha_ensemble_ic`, measuring whether the ensemble's own combined `alpha_score` predicts returns) — same slot, same operation, different input and pipeline position, not a second slot needing its own name (see todo 114). `MeasurementEngine` is neither of these — it's the now-answered question of whether the *services implementing* recurrences of this slot should be one thing instead of several.

**Canonical doc:** `docs/research/measurement-ic-engine.md`. See also `predictive measurement` below (AlphaEngine Functional Layer Vocabulary).

---

### `Extrinsic Confidence Layer (ECL)`

The system of extrinsic confidence vectors that annotate an emitted signal as observable metadata about external market context. Current vectors: CTF score (I6 cross-timeframe alignment), HMM regime weight, zone friction, exhaustion state.

**ECL boundary invariant:** If a setup meets its intrinsic detection criteria, it fires. Always. Extrinsic vectors travel on the emitted signal as observable fields (`ctf_score`, `ctf_confirmed`, `zone_friction_score`) or in `context_features`. They are the inputs the ML model uses to learn which market contexts produce better outcomes. An extrinsic gate is a prior masquerading as a model — it removes training data from the ledger permanently and makes the model unauditable.

**Regime gate exception:** HMM regime weight suppresses signal *activation* (pending → regime_suppressed), not *emission*. The signal is written to `signal_events` before the regime gate is applied. This is correct: the ML model sees regime-suppressed signals and, once `counterfactual_pnl_r` is populated by the CounterfactualTracker, can learn whether the regime gate adds value empirically.

**Distinction from intrinsic confidence composite:** The intrinsic composite is a weighted sum of pattern-internal factors (price/volume/microstructure). Weights sum to 1.0. ECL vectors inform the ML attribution layer — they are features against which `counterfactual_pnl_r` is regressed, not combined into the composite.

**Individual components:** referred to as **extrinsic confidence vectors** (not "modifiers," not "multipliers," not "gates").

**Banned:** zone friction gate, extrinsic modifier, extrinsic multiplier
**Avoid:** "CTF gate" as a name for the pattern of suppressing signals on CTF absence
**Status:** archived — annotates `signal_events`, the v2.x SLA detection table, which has no live consumer as of 2026-07-02 (see CLAUDE.md Architecture note and `Signal Ledger Architecture (SLA)` entry above).

**Code surface:** `ctf_score`, `ctf_confirmed`, `zone_friction_score` fields in `signal_events`; `capture_signal_features()` in `confidence_utils.py`; `docs/signals/signals-confidence-patterns.md`.

---

### `Adaptive Parameter Registry (APR)`

The system-wide registry of all tunable numeric values — detection thresholds, confidence weights, indicator periods, governance gates. Four tables (`config_schema`, `config_state`, `config_history`, `config_outbox`) and one service (`ConfigService`).

"Adaptive" is precise: APR parameters are not static config. They start as `[initial_estimate]` or `[conventional]` human opinions and evolve through evidence — ML discovery writes calibrated values after p < 0.05 and sufficient N. The `config_history` table is a first-class audit record of every parameter's evolution.

**Informal alias:** "param store" — acceptable in conversation, not in architecture docs or code comments.

**APR parameter lifecycle:** `seed → operator_tuning → ml_learned → user_override → ml_learned again`

**Banned:** param store, config store, config system
**Status:** active

**Code surface:** `config_schema`, `config_state`, `config_history`, `config_outbox` tables; `ConfigService`; `docs/foundation/adaptive-parameter-registry.md`.

---

### `detection layer`

The layer of the 3-table signal architecture that records the raw fact of a pattern firing — when a plugin's intrinsic detection criteria were satisfied. One row per signal fire event. Carries the intrinsic quality signal (`raw_confidence`, `factor_scores`) and the extrinsic market context at fire time (`ctf_score`, `zone_friction_score`, `context_features`). Immutable after write (status excepted).

**Not:** a trade record. The detection layer records that a pattern was detected, not that anything was done about it.

**Table:** `signal_events`
**Banned:** (none)
**Avoid:** "signal ledger" as the name for this concept (legacy monolith term; the `signal_ledger` view keeps its name)
**Status:** archived — part of the v2.x SLA, no live consumer as of 2026-07-02; see `Signal Ledger Architecture (SLA)` entry above.

---

### `hypothesis layer`

The layer of the 3-table signal architecture that represents trade specifications derived from a detection event. One row per entry_type per signal — e.g. a single OFI divergence detection might produce an `at_close` frame and an `at_pullback` frame. Each frame is a falsifiable hypothesis: given this entry/stop/target, what would have happened?

`counterfactual_pnl_r` is the hypothesis layer's primary output — the measured outcome of each frame against actual subsequent price action, regardless of execution. This is the ML training target.

**Not:** an execution record. A hypothesis can exist without ever being executed.

**Table:** `trade_frames`
**Status:** archived — part of the v2.x SLA, no live consumer as of 2026-07-02; see `Signal Ledger Architecture (SLA)` entry above. The v3.0 equivalent concept lives on `alpha_frames`.

---

### `execution layer`

The layer of the 3-table signal architecture that records live trade executions. One row per actual trade placed. Most hypothesis layer rows have zero corresponding execution rows — the vast majority of signal hypotheses are never executed. Contains actual fill prices, actual pnl_r, and exit details.

The gap between `counterfactual_pnl_r` (hypothesis layer) and `actual_pnl_r` (execution layer) is execution quality — slippage, timing, and selection bias from the aggregator.

**Table:** `trade_executions`
**Status:** archived — part of the v2.x SLA, no live consumer as of 2026-07-02; see `Signal Ledger Architecture (SLA)` entry above.

---

### `counterfactual_pnl_r`

**Overloaded across two unrelated implementations — check the table column, not just the name.**

- **v2.x (archived):** on `trade_frames` — the outcome that would have been realized if a
  trade frame hypothesis had been executed as specified. Computed by the archived
  `CounterfactualTracker` daemon. No live consumer as of 2026-07-02 (see CLAUDE.md
  Architecture; SLA is archived).
- **v3.0 (live):** on `alpha_frames` — the realized R-multiple of a hypothetical trade design
  (entry/stop/target/hold-horizon) against actual subsequent price action, computed by `CounterfactualTracker(BaseBatch)`
  (deleted in phase 186 plan 19; read with `git show 2d4c2e4e13980202ad2e06e0cb44dfd049aa41c4:services/counterfactual_tracker.py`). Full
  mechanics: `docs/intelligence/intelligence-alpha-frames-and-feature-lifecycle.md`. This is
  the current meaning of the term going forward.

Both share the same underlying idea (measure the outcome of every hypothesis, not just
executed ones, to avoid survivorship bias) but are separate code paths on separate tables.

**Not:** a backtested result (which implies fitting to historical data). Counterfactual pnl_r is a forward measurement on price action after the hypothesis.

**Banned:** paper pnl, simulated pnl
**Status:** retired — both implementations are gone (v2.x `trade_frames` archived 2026-07; v3.0 `alpha_frames` and the tracker deleted in phase 186 plan 19). The survivorship-bias principle it carried is now E15's counted-evidence rule; the forward runner (phase 188) measures book outcomes.

**See also:** `cross-sectional spread construction` (`construction_spreads`) — a parallel
measurement path, also retired with the old chain (phase 186).

---

### `CounterfactualTracker`

**Overloaded class name — two unrelated implementations across two milestones.**

- **v2.x (archived):** a daemon that measured `counterfactual_pnl_r` for every `trade_frames`
  row. Subscribed to the `signal_events` Kafka topic, held fully in-memory state
  (checkpointed to file on shutdown), no DB reads in the hot path. Never shipped past
  "planned" (Phase 130); the whole v2.x SLA it belonged to has no live consumer as of
  2026-07-02.
- **v3.0 (deleted in phase 186 plan 19; read with `git show 2d4c2e4e13980202ad2e06e0cb44dfd049aa41c4:services/counterfactual_tracker.py`):** a `BaseBatch` oneshot (not a daemon,
  no Kafka) that fills `alpha_frames` entry/stop/target geometry at T+1 open and runs a
  bar-by-bar exit state machine (stop/target/max-hold/IC-decay) to close frames and compute
  realized R. Full mechanics: `docs/intelligence/intelligence-alpha-frames-and-feature-lifecycle.md`.

**Status:** retired — both implementations are gone (v2.x daemon never shipped; the v3.0 `BaseBatch` was deleted in phase 186 plan 19, see the git-show pointer above)

**See also:** `cross-sectional spread construction` (`CrossSectionalSpreadTracker`) — a parallel
measurement path, also retired with the old chain.

---

### `cross-sectional spread construction`

**Legacy (retired 2026-09-26, unified design section 15.2):** belongs to the deleted ensemble chain. A dollar-neutral portfolio formed at each bar by ranking the active equity cross-section on a single qualifying feature (`ctf_momentum` in v1) and taking the top decile long against the bottom decile short, measured at portfolio level - one spread return per bar, never per symbol. Phase 167's productionization of the cross_sectional_relative_value falsification result, deliberately bypassing the linear IC-weighted combiner whose Gate 2 already failed in Phase 148.

**Naming-system derivation chain** (`docs/foundation/naming-system.md`): concept
`cross_sectional_spread` → class `CrossSectionalSpreadTracker` → module
`services/cross_sectional_spread_tracker.py` (deleted in phase 186 plan 19; read with `git show 2d4c2e4e13980202ad2e06e0cb44dfd049aa41c4:services/cross_sectional_spread_tracker.py`) → table `construction_spreads` (dropped later in phase 186, rows summarized first).

**Banned:** decile portfolio, long-short frame, spread signal
**Avoid:** retired synonyms of this concept

**Source:** `docs/research/trade-construction-layer.md` (full v1 construction design);
`.planning/ROADMAP.md` Phase 167 entry

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

**Banned:** (none)
**Avoid:** "decision record," "design record," or "architecture doc" for a locked decision (use ADR)
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

**Not:** a synonym for "tier." I1-I4 are measurement layers within V1, not vectors themselves. Not a `family`: a family is one pre-registered mechanism inside a vector. Not a synonym for "signal" — a vector produces a score every bar; a signal is emitted only when the score crosses a threshold.

**Banned:** intelligence channel, signal source, alpha source
**Exempt:** SignalSource
**Avoid:** naming new code after the exempt identifier: `SignalSource` (research layer) predates this
rule and is exempt only until its rename to `Predictor` (see `predictor`, todo 430)
**Status:** V1 active — live (`feature_vectors` and FeatureFactory); V3+ gated on measured IC

---

### `alpha score`

**Legacy (retired 2026-09-26, unified design section 15.2):** belongs to the deleted ensemble chain; frozen tables and verdicts still use it. Replacement: `book forecast`.

The z-scored ensemble prediction for a given bar — the IC-weighted linear combination of rank-normalized `FeatureVector` columns, normalized to standard deviation units within a rolling 20-day window. Was stored in `ensemble_alpha.alpha_score` (table dropped in phase 186); emission ran through `alpha_publisher.py`'s four-gate stack.

**Not:** synonymous with `raw_confidence` (v2.x ICC, plugin-internal unsigned magnitude). Not the same as `counterfactual_pnl_r` (realized outcome). Not a per-feature score — `alpha_score` was the ensemble output, not any individual feature's contribution.
**Banned:** plugin score, direction score, conviction score
**Status:** retired (2026-09-26); the `ensemble_alpha` and `alpha_events` tables were dropped in phase 186

---

### `Information Coefficient (IC)`

The Spearman rank correlation between a predictor score observed at time `t` and the subsequent N-bar return. The primary empirical measure of a plugin's or vector's predictive power.

IC = 0.03-0.05 is meaningful in practice. IC = 0.10 is exceptional. IC is always measured with bootstrap confidence intervals — a plugin requires `IC_CI_lower > 0.0` at `n >= 100` observations to be considered predictive. IC is stratified by: timeframe, HMM regime, lookahead window (1/5/10/20 bars), and asset class.

IC is regime-conditional: the same plugin may have IC = 0.07 in trending regimes and IC = -0.01 in mean-reverting regimes. HMM regime conditions ensemble weights.

**Not:** mutual information (a different information-theoretic measure — though a candidate for a future *additional* Stage 2 mechanism; see `docs/intelligence/intelligence-layer-architecture.md` Stage 2). Not `calibrated_confidence` (v2.x post-calibration output probability). Not the Edge Measurement stage itself — IC is today's mechanism for that stage's contract, not a synonym for it.
**Banned:** predictive power score, signal quality score
**Status:** active — live (v3.0 Phase B shipped); `feature_ic_scores` table holds 1.9M+ rows (verified 2026-09-04), computed by the old `services/ic_engine.py` (deleted, phase 186 plan 23); the table is frozen and dropped whole by plan 186-28 (fresh rows go to `feature_ic_scores_v2`)

---

### `ensemble alpha`

**Legacy (retired 2026-09-26, unified design section 15.2):** belongs to the deleted ensemble chain; frozen tables and verdicts still use it. Replacement: `book forecast`.

The per-bar table that stored `alpha_raw` and `alpha_score` for every (symbol, tf, bar_ts) once ensemble weights exist: the unconditional output of the AlphaEngine, populated by the nightly Ensemble Builder, and the input to the Alpha Emitter.

**Not:** a hand-crafted composite (weights come from IC Sharpe via Ledoit-Wolf, not human judgment). Not `raw_confidence` (v2.x plugin ICC). Not `alpha_events` — `ensemble_alpha` scored every bar; `alpha_events` recorded only threshold-crossing bars.
**Banned:** combined score, aggregate signal, signal composite
**Status:** retired — the table was dropped in phase 186 (summarized into legacy summary cards first)

---

### `IC discovery`

**Legacy (retired 2026-09-26, unified design section 15.2):** belongs to the deleted ensemble chain; frozen tables and verdicts still use it. Replacement: `ic_proposal` (disclosure and proposal, never admission).

The empirical process of measuring Information Coefficient for each `FeatureVector` column against subsequent forward returns, across regimes, timeframes, and lookahead windows. The mechanism by which edges are found rather than assumed. It ran on `feature_vectors` against the `forward_returns` table; output went to `feature_ic_scores`. The feature universe is fully pre-specified before any IC is measured - adding features after observing results is p-hacking, a rule that survives in E15.

**Not:** shadow mode (shadow measures P&L after emission; IC discovery measures raw feature predictiveness before any threshold is applied). Not backtesting (IC is measured on a held-out walk-forward window, not the training window).

**Banned:** signal discovery, edge discovery, alpha discovery
**Status:** retired (2026-09-26); the live successor is `ic_measure` (disclosure and proposal, never admission)

---

---

## v3.0 Primitive Measurements (I1-I4)

I1-I4 are not plugins. They are pure measurement functions — they measure real, observable market phenomena. They carry no theory about what the measurements mean. Theory belongs to I5-I7 (patterns, confluence, signals). The distinction matters: a measurement that returns wrong data is a bug to fix; a theory that doesn't pan out is evidence to record.

Rewritten in v3.0 as stateless functions inside `FeatureFactory`. No side effects, no Kafka, no DB access. Same input always produces the same output.

### `I1 — price dynamics`

Measurements of what price did: return magnitude, direction, position within bar, gap behavior. These are not predictions. They are factual descriptions of recent price action, normalized to be comparable across instruments and timeframes.

**What I1 measures:** momentum (5-bar and 20-bar log return z-scores), intrabar position (`range_position`, `bar_close_pos`), and overnight gap magnitude (`gap_z`).

**Why pure functions:** The same OHLCV bar always produces the same momentum_z_5. There is no state, no model, no judgment. If momentum_z_5 for SPY at 09:35 on 2026-06-20 is -0.8, it is always -0.8 regardless of when the function runs.

**Code surface:** `src/intelligence/features/kernels/price.py`. Output columns include `momentum_z_5`, `momentum_z_20`, `range_position`, `bar_close_pos`, `gap_z`.

---

### `I2 — volume and order flow`

Measurements of who participated and with what conviction. Volume tells you how many contracts traded; order flow tells you the directional intent behind that volume. These are observable facts from the tape — not inferences.

**What I2 measures:** volume intensity (`volume_z`, `rel_volume`), directional flow (`ofi_z`, `ofi_div`, `cvd_slope_z`), flow persistence (`cmf`), and the composite informed-trader signal (`informed_flow`).

**Why this is measurement, not theory:** `ofi_z` measures the imbalance between buyer-initiated and seller-initiated volume, z-scored. This is a fact about what happened in the order book. Whether that imbalance predicts future price is a theory — tested by IC measurement, not assumed.

**Code surface:** `src/intelligence/features/kernels/volume.py`. Output columns include `informed_flow`, `volume_z`, `ofi_z`, `ofi_div`, `cvd_slope_z`, `cmf`, `rel_volume`.

---

### `I3 — market structure geometry`

Measurements of where price is relative to the market's structural reference points: VWAP, value area, support/resistance, volatility envelope. These describe the geometry of the current bar's context within the larger price distribution.

**What I3 measures:** position relative to VWAP (`vwap_dev_sigma`), position within volume-based value area (`va_position`, `poc_dist_atr`), distance to nearest structural levels (`sr_support_dist`, `sr_resist_dist`), volatility context (`atr_z`, `vol_ratio`), and market character signals (`hurst`, `shannon`, `garch_ratio`).

**Why geometry, not pattern:** I3 describes where price is, not what it will do. `poc_dist_atr = 2.3` means price is 2.3 ATR units above the Point of Control. This is a measurement. Whether that distance predicts mean-reversion is an IC question.

**Code surface:** `src/intelligence/features/kernels/vp_sr.py` and `smc.py`. Output columns include `vwap_dev_sigma`, `atr_z`, `vol_ratio`, `poc_dist_atr`, `va_position`, `hurst`, `shannon`.

---

### `I4 — regime state`

Measurements of what market regime the HMM classifier believes we are in, and with what confidence. Also includes macro context (VIX, yield curve, flight-to-quality) and temporal structure (session, calendar).

**What I4 measures:** HMM regime quality (`hmm_regime_prob`, `hmm_entropy`, `hmm_duration`), trend direction and strength (`hma_slope_z`, `adx`), macro context (`vix_z`, `flight_quality`, `yield_slope_z`), session state (`in_ny_session`, `in_london_kz`, `in_overlap`, `power_hour`, `opening_range`, `above_wk_vwap`), calendar cyclicals (`dow_sin`, `dow_cos`, `month_position`), and cross-timeframe alignment (`ctf_momentum`, `ctf_vwap_align`, `ctf_regime_align`).

**Why these survive:** Regime state is a real thing — the HMM is a model, but its output (`hmm_regime_prob = 0.87`) is a measurement of that model's certainty. Whether a high-confidence trending regime predicts IC in momentum features is an empirical question, not an assumption. Same for macro context: `vix_z` is a fact. Whether high `vix_z` conditions feature IC is discovered by stratified measurement.

**Oscillators (APR-backed periods):** RSI and CCI measurements live in I4 at three scales (`rsi_fast/mid/slow`, `cci_fast/mid/slow`). Periods stored in APR (`feature.period.rsi.*`) — not baked into column names. Aroon freshness (`aroon_fast`, `aroon_slow`) similarly. See `docs/foundation/adaptive-parameter-registry.md §Feature Indicator Periods`.

**Code surface:** `src/intelligence/features/kernels/regime.py`, `macro.py`, `calendar.py`, `cross_tf.py` (oscillator primitives in `_primitives.py`). Output columns: the HMM, macro, session, calendar, CTF and oscillator columns.

---

## v3.0 Data Primitives

### `FeatureVector`

The typed struct of measurements produced by FeatureFactory for a single (symbol, tf, bar). One row in `feature_vectors` (the "50 columns" of the original design grew to hundreds; the exact set is the schema's). Contains exactly one value per I1-I4 measurement column — no JSONB, no nesting, no null-means-unknown ambiguity (null means the measurement was not computable for that bar, e.g. insufficient history).

The FeatureVector is the atomic unit of v3.0. Everything downstream — IC measurement, ensemble weighting, alpha scoring — operates on FeatureVectors. The feature universe is pre-specified in the `feature_vectors` schema; adding a new measurement requires a schema migration, which is the intentional gate that prevents feature proliferation.

**Not:** a plugin output (plugins receive FeatureVectors as input in I5-I7). Not a signal (signals are emitted when ensemble alpha crosses a threshold). Not a row in `intelligence_features` (v2.x JSONB table, superseded).

**Canonical doc:** `docs/plans/archive/2026-06-20-alphaengine-architecture.md §FeatureVector Contract`
**Status:** active — live

---

### `FeatureFactory`

The in-process computation unit that produces `FeatureVector` from raw OHLCV bars. Replaced the I1-I4 plugin registry and runs in the same DAG position. Writes to the `feature_vectors` table via a dedicated writer (cold sink; never blocks the hot path).

FeatureFactory is organized into cadence-matched tiers: bar-level (I1, I2, most of I3), session-level (intraday accumulators), regime-level (HMM, computed on a slower cadence and cached), cross-asset (reads HTF cached state), calendar (pre-computed daily). The cadence matching eliminates recomputing slow signals at bar frequency.

**Not:** a service. FeatureFactory has no systemd unit, no Kafka subscription, no independent lifecycle. It is a library called by the feature pipeline.

**Code location:** `src/intelligence/feature_factory.py`
**Status:** active — live; runs inside `indicagent-feature-vector-pipeline.service`

---

### `forward_returns`

**Retired (phase 186 plan 23, migration 430):** the table and its writer (`forward_return_writer.py`) are deleted; the bar-describing flags it used to originate live in bar flags (`src/intelligence/bars/scrub_rules.py`), and measurement targets come from the `panel.forward_returns` kernel (`src/intelligence/research/panel.py`) computed by `services/ic_measure.py`.

The table held executable forward returns computed from `market_data_ohlcv` via LEAD() window functions. One row per (symbol, tf, bar_ts). Stored log returns at four lookahead windows (1/5/20/60 bars), completeness flags (was the return window complete or did we hit end-of-data?), and gap flags (was there a market-hours gap before the entry bar?).

The return formula is executable and survives in the kernel: `ln(open[T+N+1] / open[T+1])` — entry at open of T+1 (first executable bar), exit at open of T+N+1. Not `close[T] to close[T+N]`, which includes the unexecutable observation price as the entry.

**Not:** a backtest. Labels are computed on actual historical prices, not simulated fills.

---

### `IC Sharpe`

The primary ensemble weighting signal. Computed as `mean(IC_t) / std(IC_t)` over a time series of IC values, each measured on non-overlapping windows of 2,000 independent observations. Measures not just whether a feature has IC, but whether it has *consistent* IC — a feature that is predictive in some windows and noise in others has low IC Sharpe even with high mean IC.

IC Sharpe requires at least 10 IC windows (20,000 independent observations minimum). Features below this threshold are not eligible for ensemble weighting regardless of their IC point estimate.

Ledoit-Wolf ensemble optimization uses the IC Sharpe time series (not raw IC) to build the covariance-adjusted weight vector. Features with high IC Sharpe and low cross-feature IC correlation earn the most weight.

**Annualized for cross-TF comparison:** `IC_Sharpe_annualized = IC_Sharpe_bar × sqrt(bars_per_year)`. The annualized form is for comparison only — ensemble weights use bar-unit IC Sharpe.

**Not:** a backtest Sharpe ratio (which measures P&L consistency). IC Sharpe measures predictive consistency, one step upstream.
**Status:** active — computed by `ic_measure.py` (with HAC and stride-bias corrections) into `feature_ic_scores_v2`; the frozen `feature_ic_scores` rows and `ensemble_weights.ic_sharpe` were retired with the old chain in phase 186

---

### `alpha decay`

**Legacy (retired 2026-09-26, unified design section 15.2):** belongs to the deleted ensemble chain. The concept: a feature whose rolling IC bootstrap CI lower bound crosses zero has predictive power no longer distinguishable from noise in the current regime, and triggers automatic weight zeroing in APR with a two-window recovery hysteresis. The `alpha-decay-monitor` batch service this entry named never shipped; no live implementation existed.

**Not:** feature removal. A decayed feature remained in `feature_vectors` and kept accumulating IC observations.

**Replacement:** the `decay alarm` (phase 188) and the feature lifecycle's consecutive-window demotion rules.

---

### `alpha_events`

**Legacy (retired 2026-09-26, unified design section 15.2):** belongs to the deleted ensemble chain. The table held the v3.0 emitted alpha signals - one row per (symbol, tf, bar_ts) where `|alpha_score| > threshold`, written by `alpha_publisher.py` - and was the v3.0 equivalent of v2.x `signal_events`. Dropped in phase 186 after its rows were summarized into legacy summary cards.

**Not:** `ensemble_alpha` (which scored every bar). `alpha_events` recorded only the bars where the score crossed the emission threshold.

---

### `weight_version`

**Legacy (retired 2026-09-26, unified design section 15.2):** belongs to the deleted ensemble chain; frozen tables and verdicts still use it. Replacement: `recipe version` of a book.

A monotonically increasing integer that identified a specific set of ensemble weights in `ensemble_weights`; `ensemble_alpha` recorded the `weight_version` used to score each bar, so any historical `alpha_score` could be reproduced from the corresponding weight set.

**Not:** a schema version or pipeline version. `weight_version` tracked ensemble calibration; `pipeline_version` tracks feature computation.
**Status:** retired (2026-09-26); `ensemble_weights` was dropped in phase 186

---

### `economic series`

A published time series about the market or the economy as a whole (a rate, a spread, a funding
statistic, a release, a schedule) from an external source (FRED, the NY Fed), stored append-only in
`economic_series_observation` with a declared unit. It belongs to no symbol and joins every symbol as
of a date.

**Not:** `macro_features`, which is computed from our own bars, and not a feature: a derived measure
computed from economic series by a kernel is a feature.
**Banned:** (none)
**Status:** active (todo 480)
**Code surface:** `economic_series_observation`, `services/economic_series_writer.py`,
`src/providers/fred.py`, `src/providers/nyfed.py`

---

### `availability time`

The earliest moment a value could have been known: a row's `available_at`. A read for t uses only rows
whose availability time is at or before t (`temporal_integrity`). Each row records its basis:
`release_record` (the publisher's dated record), `declared_rule` (a declared publication time where no
record exists) or `fetch` (when we fetched a new or changed value, an upper bound).

**Not:** the observation date (what the value is about) or the fetch time (when we stored it).
**Banned:** (none)
**Status:** active; basis values today are `assumed_lag` and `fetch`, and todo 482 replaces
`assumed_lag` with `release_record` and `declared_rule`
**Code surface:** `economic_series_observation.available_at`, `availability_basis`

---

### `release record`

A publisher's dated record of the value published for an observation and when it was published, and
of each later revision: FRED's ALFRED archive. The source of availability times and revision rows for
FRED series.

**Not:** `vintage`. ALFRED calls these vintages; in this project `vintage` is a research data span.
**Banned:** (none)
**Status:** design (todo 482)

---

### `knowledge cutoff`

The availability-time bound K of a research snapshot: the snapshot reads economic series rows whose
availability time is at or before K, so a snapshot of an append-only store reproduces bit for bit.

**Banned:** (none)
**Status:** design (`docs/ideas/signal-macro-context-layer.md`, S0 economic block)

---

### `shift test`

A robustness check every result that uses economic series must pass: re-run it with every availability
time moved one session later. A result that changes materially depended on timing at the edge of
knowability and is not trusted.

**Banned:** (none)
**Status:** design (`docs/ideas/signal-macro-context-layer.md`)

---

### `schedule series`

An economic series that records scheduled days (an FOMC meeting, a release date): observation date =
the scheduled day, availability time = when the schedule was published, value 1, and value 0 in a
later row when the day is cancelled or moved. Market-wide events are stored this way; there is no
separate event table.

**Banned:** (none)
**Status:** design (`docs/ideas/signal-macro-context-layer.md`)

---

## Functional Layer Vocabulary (formerly the AlphaEngine Layer 1 slots)

Generic names for the functional slots of a feature-to-decision pipeline, in pipeline order.
The generic name survives if the implementation changes; use these terms in design docs,
todos, and discussion rather than naming specific formulas -- "the regime classifier now has
two implementations" is a statement about one slot, not two different things.

The three AlphaEngine-only slots (`ensemble optimizer`, `alpha scorer`, `alpha emitter`) are
retired with the old chain (phase 186); their entries below carry the Legacy line and the
replacements. The pipeline shape today: `feature measurement`, `feature synthesis`, `regime
classifier`, then `predictive measurement` at feature grain (`ic_measure`); the research
layer's combiner and books take the place of the retired scoring chain.

---

### `feature measurement`

The functional slot that transforms raw OHLCV bars into a typed vector of observable
quantities for a single (symbol, tf, bar). These are measurements -- factual descriptions
of what price, volume, and structure did -- not inferences or predictions. Runs on the
hot path on every bar.

**Current implementation:** `FeatureFactory` (I1-I4 cadence tiers; the "54 features" count is historical)
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
- Per-symbol HMM (`regime_writer.py`) → `feature_vectors.regime_volatility` (3 labels: `calm`/`elevated`/`turbulent`, see `regime` entry). `feature_vectors.regime` (5 labels) still exists during the phased cutover but carries the retired trend vocabulary.
- Cross-sectional model (`cross_sectional_regime_model.py`) → `market_regimes` (9 labels)

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
  **Current implementation:** Spearman IC (`ic_measure.py`, kernel forward returns) → `feature_ic_scores_v2` (the deleted `ic_engine.py` wrote the frozen `feature_ic_scores`)
- **Ensemble grain** (post-scoring, after `alpha scorer`): the same operation applied to
  the ensemble's own combined `alpha_score` instead of a single feature column -- does the
  *ensemble's* prediction predict returns, not just its inputs.
  **Current implementation:** Phase 142A's EIC, `ensemble_ic_engine.py` (deleted 186-19) → `alpha_ensemble_ic`

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

**Legacy (retired 2026-09-26, unified design section 15.2):** belongs to the deleted ensemble chain; frozen tables and verdicts still use it. Replacement: a `combiner` (research layer).

The functional slot that derives a weight vector from the history of predictive
measurement scores, producing a covariance-adjusted weight per feature that maximizes
expected portfolio IR subject to constraints. Ran on a batch schedule (the `ensemble_builder` batch service, Ledoit-Wolf shrinkage on IC Sharpe time series into `ensemble_weights`, all deleted in phase 186).

**Not:** the alpha scorer (which applied weights). The ensemble optimizer derived weights;
the alpha scorer applied them.

---

### `alpha scorer`

**Legacy (retired 2026-09-26, unified design section 15.2):** belongs to the deleted ensemble chain; frozen tables and verdicts still use it. Replacement: a `combiner` (research layer).

The functional slot that applied the current ensemble weight vector to each bar's
FeatureVector, producing a scalar score per (symbol, tf, bar_ts): an IC-weighted rank-normalized linear combination, z-scored to standard deviation units into `ensemble_alpha.alpha_score` (deleted in phase 186).

**Not:** the alpha emitter (which filtered scores above a threshold). The alpha scorer
scored every bar; the alpha emitter selected which bars to act on.

---

### `alpha emitter`

**Legacy (retired 2026-09-26, unified design section 15.2):** belongs to the deleted ensemble chain; frozen tables and verdicts still use it. Replacement: `forward runner`.

The functional slot that filtered alpha scorer output and emitted actionable events when
the score crossed a threshold with sufficient statistical confidence. Ran as
`alpha_publisher.py`'s four-gate stack (`effective_n` floor, per-timeframe
`|alpha_score| > alpha.quant.threshold.{tf}`, direction-aware CI + cost hurdle, non-empty
`top_features`) writing `alpha_events` - all deleted in phase 186.

**Not:** a trading decision. The alpha emitter said "a score crossed threshold"; the
Portfolio layer (Layer 2) decided whether and how much to trade.

---

## Research Layer and Evidence Terms (E15)

Added 2026-09-25. The vocabulary of the research layer (`src/intelligence/research/`) and the
evidence framework (`docs/plans/2026-09-24-evidence-framework.md`, methodology-change-ledger
E15). Three older entries collide with how research code and the E15 docs use their words; the
resolutions are in `predictor`, `horizon` and `IC term structure` below, and in the notes added to
`alpha`, `intelligence vector` and `half-life`.

### `book`

The one portfolio a test evaluates, four frozen parts plus a spec hash: its members (registered
families and their pinned members), a combiner that sets `member weight`s walk-forward, a
`construction rule` that turns the `book forecast` into `position weight`s, and a `horizon rule`.
S8 tests the construction that will trade. The book, not an idea or a predictor, is what earns
capital. Families on different clocks combine only at the P&L level, as a pod book.

**Not:** a sleeve (retired: a fixed symbol subset used by legacy phase 179 tests), a strategy, or
a family. A family contributes predictors to a book; it is never tested alone on the forward span.
**Banned:** (none)
**Status:** active; `docs/plans/2026-09-26-unified-research-to-production-design.md` section 4

---

### `book version`

Any change to a book's members, combiner, construction rule or horizon rule makes a new book
version, and running it on the vintage makes a new `attempt`. There is no fixed budget of
versions: every attempt is counted and priced by the `selection test` (E18).

**Banned:** (none)
**Status:** active (E18)

---

### `pod book`

Books on different clocks (for example 15m intraday and session-level) combined at the P&L
level: the pod's series is the session-level sum of its member books' recorded E17 D_s series on
the sessions every member tested, never recomputed and never filled. Each member is pinned by
run_id and the series' content hash, so rerunning a member book never changes a pod. A pod is
its own spec kind (`pod_book`) and its own counted attempt, tested with E17's HAC statistic on
the summed series; its power is inherited from the members' passing power blocks.

**Not:** a `book version` with several families. One book's families share a panel and horizon;
a pod is how books that cannot share them combine.
**Banned:** (none)
**Status:** active, phase 187 (plan 187-10); `src/intelligence/research/pod.py`

---

### `family`

A group of 3 to 8 `family member`s sharing one pre-registered mechanism and prior (a paper or a
stated economic cause), for example intraday same-slot periodicity. Families enter a book by
pre-registration and mechanical guards only, never by an outcome screen, and every member stays
in; the combiner sets weights.

**Not:** an `intelligence vector`. A vector is an information domain (V1 quant, V3 macro, V5
flow); a family is one mechanism inside a domain, and a vector holds many families.
**Banned:** (none)
**Status:** active; queue and status in the generated `docs/research/research-ledger.md` (the frozen `construction-verdict-ledger.md` section 1 is its hand-edited predecessor)

---

### `family member`

One `predictor` registered in a family's spec with its parameters pinned (windows, direction,
declared memory, and any smoothing from the fixed half-life menu). The same predictor with a
different window is a different member.

**Banned:** (none)
**Status:** active
**Code surface:** `members` in `research/specs/*.yaml` (phase 183)

---

### `predictor`

A pure, registered computation from a panel to a continuous score per (row, symbol), using only
data through its row, with a declared memory and a pre-registered direction. It has no fitted
parameters. What the research code calls a "signal" is a predictor.

**Not:** a `signal` (the archived v2.x trade hypothesis with entry, direction and exit), an
`alpha` (a validated edge), or an `alpha score` (the production ensemble's output).
**Banned:** (none)
**Avoid:** "signal" for this concept in new research prose ("signal" is the archived v2.x term and
"signal source" is banned under `intelligence vector`)
**Status:** active
**Code surface:** `SignalSource` in `src/intelligence/research/signals.py`, whose name predates
this entry and uses a banned term; rename to `Predictor` coordinated with phase 183, which is
building on it. Research arrays named `alpha` hold predictor scores (legacy naming).

---

### `clock`

The row grid a book trades on and is scored on: the daily clock (one row per session) or an
intraday clock (a fixed slot grid per session). A book has exactly one clock and one target.
Predictors computed on another timeframe enter through the causal alignment node (S2b), never
directly.

**Not:** a timeframe. A timeframe is a property of an input; a clock is a property of a book.
**Banned:** (none)
**Status:** active (design, `docs/plans/2026-09-25-multi-timeframe-horizon-design.md`)

---

### `horizon`

The number of rows between entry and exit of a forward return, both at opens (Invariant 1). On
the daily clock a book's target has horizon 1.

**Not:** `lookahead`, which new text reserves for lookahead bias (using data not yet available at
decision time). The legacy ic_engine column `lookahead_bars` means horizon; it keeps its name.
**Banned:** (none)
**Status:** active
**Code surface:** `horizon` and `fwd_span()` in `src/intelligence/research/panel.py`

---

### `vintage`

A dated span of data whose attempts are counted together for the `selection test`. Vintage 1 is all data before
`alpha.validation.oos_start` (2025-12-24). The span after it is the `forward span`, reserved for
`confirmation`.

**Banned:** (none)
**Status:** active

---

### `screen`

Legacy (E15, replaced by E18 on 2026-09-26): a test of a book version at alpha / M against a fixed
budget of M = 30. Under E18 an attempt has no per-run bar; the `selection test` prices every
attempt at once. Use `attempt` and `selection test`.

**Banned:** (none)
**Status:** legacy

---

### `confirmation`

The single test of a promoted book on its own forward span, alpha 0.05 one-sided, on a date fixed
at freeze by a power calculation (at most 3 years out). The span must be data no one looked at while
shaping the book: books with `feature_vectors` or `ctf_momentum`-like members confirm only on data
after their freeze date and never before 2026-08-08 (E18). The only gate to capital.

**Banned:** (none)
**Status:** active (E18)

---

### `evidence record`

A result recorded by the research runner for a family, member or book version: what ran (spec,
snapshot and code hashes), what it measured, and its refusals. A record is evidence, not a
verdict and not a test token.

**Banned:** (none)
**Status:** active; sole writer is the S6 ledger writer (phase 183)

---

### `shift null`

The book test's null distribution: the whole signal stack shifted against returns by whole
sessions (every symbol by the same shift), keeping cross-sectional structure and persistence and
breaking only the alignment. Shifts within `min_shift` or the declared memory are excluded.

**Not:** valid at its nominal tail for persistent predictors on its own: with an
`autocorrelation time` above about 40 sessions on about 4,700 sessions, its rejection rate at
p 0.00167 runs 2 to 6 times nominal (simulated 2026-09-25). The calibration fix is E16.
**Banned:** (none)
**Status:** active
**Code surface:** `src/intelligence/statistics/panel_null.py`

---

### `autocorrelation time`

tau = 1 + 2 x (sum of a predictor's lag autocorrelations), in rows of its clock: roughly how
many rows it takes the predictor to forget itself. A w-session moving average has tau of about w.
A book's shift null has about (admissible sessions / tau) independent draws. Measured from
predictors alone, so measuring it spends nothing.

**Not:** `half-life` (a decay parameter chosen for a weight or smoothing) or declared memory (how
far back a predictor reads).
**Banned:** (none)
**Status:** active (step 0 of the evidence framework)

---

### `IC term structure`

The correlation of a predictor at row t with the one-row residual return k rows later, for
k = 1 .. K, read as a whole curve against a joint shift-null band. A record of how long a
predictor's information lasts, produced by every recorded run and fed into nothing.

**Not:** `alpha decay` (a feature's rolling IC losing significance over calendar time) or the
legacy cumulative-horizon IC ladder (overlapping targets).
**Banned:** (none)
**Status:** design (`docs/plans/2026-09-25-multi-timeframe-horizon-design.md` D2)

---

## Unified design vocabulary (2026-09-26)

Added with `docs/plans/2026-09-26-unified-research-to-production-design.md` (adopted, E18),
section 15. Collisions it resolves: invariants are named, not numbered (I1-I4 are intelligence
tiers); discovery methods are named, not D-numbered (phase 185 and 183 use D codes); `member
weight` and `position weight` separate the two meanings of `weight`.

### `member weight`

The weight a combiner gives a family member when forming the `book forecast`, fitted on training
folds only. **Not:** `position weight`.
**Banned:** (none)
**Status:** active

---

### `book forecast`

The combiner's output per (row, symbol): the sum of member scores times member weights.
**Not:** `alpha score` or `ensemble alpha` (legacy production outputs).
**Banned:** (none)
**Status:** active

---

### `position weight`

A holding per (row, symbol) produced by a `construction rule` from the book forecast.
**Banned:** (none)
**Status:** active

---

### `construction rule`

The rule that turns a book forecast into position weights: R1 (rank, inverse vol, market
neutral), `vol_normalized`, `ic_proportional`, `mean_variance` or `fixed_sign`, behind the
`ConstructionRule` protocol. Part of the frozen book.
**Banned:** (none)
**Status:** active (phase 187)

---

### `horizon rule`

Partial adjustment toward target positions, `w_t = w_(t-1) + kappa (w*_t - w_(t-1))`. Kappa is a
cost device (Garleanu and Pedersen): derived from the cost model and the signal's own
autocorrelation, pinned before the attempt; kappa = 1 when uncosted.
**Banned:** (none)
**Status:** active (phase 187)

---

### `attempt`

One recorded evaluation of a series on the real vintage that a person can see: a book run in any
runner mode, a member evidence run, or a diagnostic subset refit. Every attempt joins the
selection universe; nothing on the vintage is uncounted.
**Banned:** (none)
**Status:** active (E18)

---

### `selection test`

Romano-Wolf StepM over every attempt on a vintage at family-wise 0.05, returning the set of books
that beat zero given everything tried. Promotion then chooses within that set by net expectation.
**Not:** `confirmation` (the one forward test) or the legacy `screen`.
**Banned:** (none)
**Status:** active (E18; built in phase 187)

---

### `frozen book`

A book whose four parts and spec hash are recorded in UCR and never edited; a change is a new book
version. **Banned:** (none)
**Status:** active

---

### `forward runner`

The stage that runs frozen books forward on the same research code (`BookTracker` computes,
`BookPositionWriter` persists), in sealed shadow until each book's test date.
**Not:** `alpha emitter` (legacy). **Banned:** (none)
**Status:** design (phase 188)

---

### `champion` / `challenger` (books)

The deployed book (champion) and a new version run beside it in sealed shadow (challenger);
capital moves only after a pre-declared paired test passes.
**Banned:** (none)
**Status:** design (phase 188)

---

### `recipe` / `recipe version`

A concept's exact definition in UCR: code pointer and commit, pinned parameters with their APR
values, inputs, universe selector, vocabulary codes, mechanism and sources. Versions are
append-only (`concept_recipe`). **Banned:** (none)
**Status:** design (phase 187)

---

### `research stage`

How far a concept has got in research (idea, specified, registered, tested, refused, frozen,
confirmed), derived from recipes and attempts, never stored. **Not:** `status` (the production
lifecycle). **Banned:** (none)
**Status:** design (phase 187)

---

### `decay alarm`

A frozen book's member leaving its control band of realized contribution in forward monitoring;
it triggers review, not removal. **Banned:** (none)
**Status:** design (phase 188)

---

### `contribution`

What a member or family adds to a book. Attribution (who earned the return: additive, forecast
level exact always, P&L level exact for linear constructions) differs from marginal contribution
(who is necessary: leave-one-family-out, Shapley). **Banned:** (none)
**Status:** active (design section 13)

---

### `state variable`

A continuous macro regime input (vol z, breadth, curve z, dollar z) used to condition members as
`s` and `s x z_t`, instead of regime buckets. **Banned:** (none)
**Status:** active (design section 5.2)

---

### `regime disclosure`

The fixed per-regime table (P&L share, mean, HAC t, IC, hit rate, effective observations) and
regime-explained share reported on every book test; never gating. **Banned:** (none)
**Status:** active

---

### `rebuild unit`

One (symbol chunk, tf, time range) slice of the feature_vectors_v2 rebuild
(services/backfill_feature_factory.py run_rebuild_stage), keyed by a provenance batch record so
a kill-and-resume skips completed units and recomputes the rest. **Banned:** (none)
**Status:** active (phase 186)

---

### `provenance batch`

The record of one write batch to a bulk table (writer, per-kernel code key, APR snapshot, input
content digest, symbol x tf x time range); the lineage record and the idempotency key.
**Banned:** (none)
**Status:** active (phase 186, table provenance_batch, written only by
services/_batch_utils.py bulk_load)

---

### `ic_measure`

The one writer of the fresh IC table (`services/ic_measure.py`, oneshot, phase 186 D-17). It runs
the pure measure jobs (proposer with term structure, `regime_volatility` disclosure, monitoring)
and writes `feature_ic_scores_v2` only through `bulk_load()`, one provenance batch per unit
(job, tf); a unit owns every row of its scope in that tf, and feature blocking is memory only.
**Banned:** (none)
**Status:** active (phase 186 plan 14)

---

### `feature_ic_scores_v2`

The fresh IC hypertable (migration 413): `regime_scope` is in the primary key from creation, and
`training_window_end` has one meaning, the latest target exit bar used by the cell, always before
`alpha.validation.oos_start`. Sole writer `ic_measure`. The legacy `feature_ic_scores` table is
frozen and dropped whole by plan 186-28. **Banned:** (none)
**Status:** active (phase 186 plan 14)

---

### `fresh regime_scope values`

The three values `feature_ic_scores_v2.regime_scope` allows: `unstratified` (proposer cells,
regime `_all`), `regime_volatility` (disclosure, regime = the label) and `member_window`
(monitoring, one row per window, regime `_all`). The legacy values (`cross_sectional`,
`symbol_hmm`, `pooled`, `earnings_season`) cannot enter the v2 table. **Banned:** (none)
**Status:** active (phase 186 plan 14)

---

### `summary card`

A UCR `legacy_verdict` attempt that records what an old verdict or dead process tried and found:
idea, recipe pointer (spec path, git commit), result numbers, known defects, spans looked at, and
why it is closed or reopened. Written before the derived data behind it is dropped (raw data is
permanent, derived data is cache, conclusions are records). **Banned:** (none)
**Status:** design (phase 186)

---

### `generated_family`

A family whose members are enumerated by a registered grammar over primitives, with no idea behind
any single member; selection and weighting happen only inside training folds.
**Banned:** (none)
**Status:** design (design section 6.1)

---

### `research kernel`

A `Kernel` under the phase 186 registry contract (declared inputs, declared memory, pure
compute, the same causality probe and memory check) that lives in
`src/intelligence/features/research_kernels/`, outside `kernels/`: `default_registry()` never
discovers it and no stored column holds its output. Research computes it at spec-pinned
windows, and only for a (statistic, window) no stored column carries (184-REVIEWS row 10). Each
family has a pending todo to move it into the 186 registry once the rebuild's import closure
unfreezes. **Banned:** (none)
**Status:** active (phase 184 plan 02)

---

### `kernel_source`

The research S2 node (`src/intelligence/research/kernel_source.py`) that runs registry and
research kernels on an S0 panel, per symbol over its present rows, at pinned windows under the
provenance config. Output is float32 on the panel grid, NaN until the declared memory and NaN
where the trailing window spans more than the pinned `max_gap_rows` absent grid rows. It refuses
expanding (path-dependent) outputs and a research window equal to a stored column's.
**Banned:** (none)
**Status:** active (phase 184 plan 02)

---

### `synthetic fill`

A stored bar the backfill fabricates for an interval slot the provider returned nothing for:
open, high, low and close equal to the previous close, volume 0, `source = 'synthetic_fill'`. It
is not an observation, and it makes a missing bar look handled. **Not:** a derived bar (`source = 'derived_5m'`).
**Banned:** (none)
**Avoid:** "placeholder bar", an informal name for the same thing
**Status:** retired (todo 462; plans 185-12 and 185-18 stopped writing it, and plan 185-25 rebuilt
`market_data_ohlcv` from real rows on 2026-10-06, so the table holds none)
**Code surface:** `src/core/bar_normalizer.py` (`SOURCE_SYNTHETIC_FILL`, the refused label; plan 185-42 deleted the `normalize_bars` fill path)

---

### `fetch coverage`

For one (symbol, timeframe), the union of provider answers that cover a slot: request windows
answered with bars (and those bars stored) or with no data, read from `ohlcv_request`, and --
5m, todo 565/567 -- the requested range of an applied Alpaca load (`ohlcv_load`, where a
no-trade slot is the SIP answer) and the Alpaca nightly's SIP 5Min windows. Route pairs with
its own what_to_show (`gap_plan.COVERAGE_EVIDENCE`); the IEX route never covers. A slot inside
a covered window with no stored bar is a no-trade, not a gap. A timeout or failed request, and
a request whose own load the contract refused, never cover. One definition for the fetcher's
planner (`_d1_gaps.py`) and the bar reconciliation audit (`bar_reconciliation_audit.py`).
**Not:** stored row count, which a synthetic fill inflates.
**Banned:** (none)
**Status:** design (todo 462; `gap_plan.py` in plan 185-18; loads and Alpaca windows 2026-10-31)
**Code surface:** `ohlcv_request`; `ohlcv_load`; `src/intelligence/bars/gap_plan.py`

---

### `provider hole`

A slot the provider answered without a bar although trades occurred, found by reconciling a
coarser timeframe or the daily bar against finer bars (a coarse bar missing, or with less volume
than its constituents). A defect, unlike a no-trade slot, which is a real observation.
**Banned:** (none)
**Status:** design (todo 462; check in plan 185-23)

---

### `bar completeness`

Per (symbol, timeframe, year), the share of expected session slots that hold a real bar or fall
inside fetch coverage. Reported by the daily audit with the threshold in APR.
**Not:** row count.
**Banned:** (none)
**Status:** design (todo 462; plan 185-23)

---

## Bar data layer terms (phase 185)

The bar data foundation: every vendor answer is kept in `ohlcv_raw` (last-wins, with a revision
log), canonical bars are a rebuildable selection from it by `bar_source_policy` (the daily rule
for 1d, the selection writer for 5m, 1m and 4h, the grid for 15m and 1h), and side tables
record what is wrong with a bar or why it moved, never by editing the bar itself. Operations
view: `docs/operations/operations-database.md`; owners: `docs/foundation/canonical-truth-registry.md`.
The phase 185 stores (`ohlcv_observation`, called D1, and `ohlcv_intraday_raw_archive`) were
dropped 2026-10-17 by plan 191-16, their rows folded into `ohlcv_raw` and kept on disk as the
backup in `data/backups/191/` to 2026-11-12. Entries below that name them describe history.

### `observation`

One daily bar exactly as a provider answered it: a row of the retired `ohlcv_observation` store
(D1), keyed by the request that fetched it (`ohlcv_request`, which also logs no_data, timeout and
failed answers), with its route (`SMART`, a venue such as `NYSE`, `TRADIER`) and what_to_show.
The same date could hold several observations; the latest per route was what the derivation
read. Daily only; intraday answers were stored as bars directly. The word survives in the fetch
pipeline's route-evidence mapping (`observation_kind`) and the writer role name. **Not:** a
sample in a statistic ("n observations"), and not a canonical bar. **Banned:** (none)
**Status:** retired 2026-10-17, plan 191-16 (migration 499 dropped the table; its rows live in
`ohlcv_raw`, backup in `data/backups/191/` to 2026-11-12; migration 380, phase 185 D1, mutable
since migration 438)
**Code surface:** `ohlcv_request`; writer role `ohlcv_observation_writer` (the role stays; the
writer module went with the table)

### `canonical bar`

The one bar per (symbol, timeframe, timestamp) that research reads, stored in
`market_data_ohlcv` and read through `market_data_ohlcv_tradeable`. A daily canonical bar is
selected by the one 1d rule (d2-v3 in the stored canonical) from the `ohlcv_raw` answers of the
name's `daily source` for that date, with its lineage in the `canonical_bar_lineage` view. 15m
and 1h canonical bars are the derived grid; 5m, 1m and 4h are a selection from `ohlcv_raw` by
policy, each session whole from one vendor (`services/bar_selection.py`). Canonical is
rebuildable from raw plus policy; `scripts/ops/bars/ops_selection_gate.py --compare` is the
standing proof. **Not:** a raw answer (a row of `ohlcv_raw`) or a quarantined bar (stored,
hidden from readers). **Banned:** (none)
**Status:** active (phase 185 plans 17, 18, 25, 26; one 1d rule since 185-38; d2-v3 since 185-52;
selection from raw since phase 191)
**Code surface:** `services/bar_derivation.py --stage daily`, `src/intelligence/bars/daily_rule.py`,
`services/bar_selection.py`, `src/intelligence/bars/selection.py`

### `daily source`

The vendor whose raw answers make a name's canonical 1d bar on one date, chosen per date by the
`bar_source_policy_current` row that covers it (a symbol row beats the timeframe default).
Today: Tradier before D = 2026-10-07 (the closed default row, IBKR fallback; Tradier's answers
end at 2026-10-06), IBKR SMART TRADES from D (the open default row, no fallback), and per-symbol
exception rows (185-38 IBKR-primary rows, 185-37 bounded rows, 185-49 head rows, the 185-47 hold
rows that keep MOD and QRVO on Tradier primary). Decided, lands with plan 191-20 (todo 545):
D-191-Q makes Alpaca SIP (`(alpaca, sip_rth)`, split-adjusted) the daily source from 2016-01-04
with IBKR fallback only where Alpaca has no tradeable bar, and IBKR alone before 2016, the same
seam as 5m (D-191-P). Without Tradier, IBKR alone would leave canonical 1d on a
non-consolidated volume basis and short of sessions Alpaca holds. Under rule d2-v4 a zero-volume
bar never serves, from either vendor. Exceptions (spin-off-adjusted history, ticker reuse) are
dated per-name policy rows decided by a one-time three-vendor arbitration (Alpaca, IBKR,
Tradier) run before plan 191-20 deletes Tradier; spans where all three disagree go to the
owner. After a split recorded once Tradier stopped
answering, a date whose Tradier answer is on the stale scale takes IBKR's re-fetched answer as
`ibkr_fallback` when the basis over the nearest common sessions (the stale Tradier close divided
by the split factor, a measurement only) is within the interior fallback tolerance; otherwise the
stale bar stays, flagged `pre_split_unrefetched` and quarantined (d2-v3, plan 185-52). A frozen name is one whose canonical 1d series
stops at its last Tradier bar because the source its open row names does not answer it after D
(IBKR cannot qualify the contract, or the fallback is refused); it fails `freshness_1d` once it
is more than the allowed sessions behind, and it stays active. **Not:** the provider of a request (an observation's route), a held name (a rewrite
waiting on a decision), or a name's listing venue. **Banned:** (none)
**Avoid:** "Tradier-owned" for a name (the open-policy predicate of 185-38, deleted in 185-48; say
which dates Tradier is the daily source for)
**Status:** active (migration 438 Tradier default; migration 456 IBKR default from D, plan 185-47;
row retirement, migration 520; D-191-Q decided 2026-10-27, not yet in the policy)
**Code surface:** `bar_source_policy`, `bar_source_policy_current`, `scripts/ops/bars/ops_source_policy.py`, `src/intelligence/bars/daily_rule.py`

### `derived grid`

The 15m and 1h bars rebuilt from a name's tradeable 5m bars on session-anchored edges (a 1h bar
of a 16:00 close ends at 15:30-16:00), vendor `derived` and kind `5m_grid` (the retired
`source` label was `derived_5m`). The IBKR 15m/1h answers they
replaced were kept in `ohlcv_intraday_raw_archive` until plan 191-16 dropped it (2026-10-17);
those answers live in `ohlcv_raw`. A derived bar with an unanswered constituent
slot carries a `partial_constituents` flag. **Not:** a provider 15m/1h bar, and not a synthetic
fill. **Banned:** (none)
**Status:** active (D2b, phase 185 plans 11 and 12)
**Code surface:** `services/bar_derivation.py --stage grid`

### `scrub flag`

A row of `bar_quality_flag` naming one rule (D2a: `ohlc_invariant`, `price_sanity`, `stale_print`,
`vol_scaled_jump` and the rest of `scrub_rules.py`) that fired on one stored bar, with the rule version and the batch that
wrote it. A flag describes the bar; it never edits or deletes it. Most flags are informational;
the ones on the quarantine rule list also hide the bar. **Not:** a quarantine, which is a flag
with `quarantine = true`. **Banned:** (none)
**Status:** active (migration 381, phase 185 plans 05 and 10)
**Code surface:** `src/intelligence/bars/scrub_rules.py`, `services/bar_scrub.py`

### `quarantine`

A scrub flag whose rule is on the APR quarantine list
(`threshold.bar_scrub.quarantine_rules`): the bar stays in `market_data_ohlcv` but
`market_data_ohlcv_tradeable` anti-joins it out, so no research read sees it. The scrub stage
itself reads `market_data_ohlcv_scrub_input`, which keeps quarantined bars. Clearing a
quarantine is a new scrub run, not an edit. **Not:** a deletion, and not a missing bar (a no-trade
slot). **Banned:** (none)
**Status:** active (D-09 flag-never-delete, migration 381; `pre_split_unrefetched` added by 402)
**Code surface:** `bar_quality_flag.quarantine`, `market_data_ohlcv_tradeable`

### `corporate action`

A split or reverse split recorded in `corporate_action` with its factor (stored / fresh close on
the old scale), its effective date (the last day on the old scale) and the requests that evidence
it; inferred by the seam audit, the nightly overlap, an operator correction, or (until 185-48
deleted its loader) a Tradier refetch. Append-only: a
correction is a new row that supersedes the old one, read through `corporate_action_current`.
Dividends are not corporate actions here; they live in `dividend_events`. **Not:** a dividend, a
symbol change or a listing-venue move. **Banned:** (none)
**Status:** active (migration 400; `tradier_refetch` admitted by 440; void rows and `operator`
corrections by 461: a void row supersedes and retracts a row, the current view hides both)
**Code surface:** `scripts/ops/bars/ops_split_detect.py` (the plan 15 seam audit script was deleted in 185-42; its `seam_audit` rows stay)

### `held name`

A name whose canonical bars of a timeframe stay as they are until a decision releases it: it has
a row in `bar_hold_current`. The daily stage skips it whatever the scope (no rewrite is applied),
the overlap judge does not hold the same rescale twice, and D7 reports it (`held_names`,
`held_1d`). The one reason today is `unclassified_rescale`: a constant vendor rescale whose
factor is no recognised split ratio (APR `infra.backfill.split_ratio_*`), such as CTVA's 39/7
after a spin-off; it is never written to `corporate_action`. Append-only; a release is a new
row. **Not:** a bar_source_policy hold row (a source decision for a name, 185-47 class C), a
quarantine (a flag on one bar), or a name outside compute_1d. **Banned:** (none)
**Status:** active (migration 461, plan 185-51)
**Code surface:** `services/bar_hold.py` (the one writer and reader), `bar_hold`, `bar_hold_current`

### `listing venue`

The exchange a name was listed on over a date range, in IBKR primary-exchange codes (`NYSE`,
`NASDAQ`, `ARCA`, `AMEX`, `BATS`), stored point in time in `listing_venue` with
`[valid_from, valid_to)` spans that never overlap. From the SMART head on it is SMART's current
primary exchange; before a move it is inferred from the former-venue observations (the venue
whose close is most often the nearest to the official close, then volume). Reconstructed history:
past dates are allowed on insert, and the only update closes an open span. It explains why a
moved name's SMART history starts late (todo 433). **Not:** a route (`ISLAND` is the route,
`NASDAQ` the venue) or the `SMART` router. **Banned:** (none)
**Status:** active (D6, migration 408, phase 185 plan 24)
**Code surface:** `services/listing_venue_writer.py`

### `listing end`

A name's recorded last listed session after a merger, buyout or delisting, with its reason
(`acquired`, `merged`, `taken_private`, `delisted`) and evidence (the exchange's Form 25 or the
issuer's Form 15, and each vendor's last bar), in `listing_end` (append-only; a correction
supersedes; read through `listing_end_current`). The name stays active and in every panel
(onboarding SOP rule 6); its bars stop, `freshness_1d` judges it up to the last session, and the
plan 191-19 readiness gate flags it instead of gating on it. **Not:** a listing-venue move (the
name keeps trading elsewhere), a symbol change (a spelling in `provider_meta`), or a held name.
**Banned:** (none)
**Status:** active (migration 518, todo 519)
**Code surface:** `production/migrations/518_listing_end.sql` (the one writer),
`services/bar_reconciliation_audit.py`, `scripts/ops/bars/ops_tradier_residue.py`

### `bar content digest`

A checksum of a (symbol, timeframe, calendar month) slice of canonical bars, with the rule
version beside it, in `bar_content_digest` (append-only; `bar_content_digest_current` is the
latest per slice). `--changed-only` derivation runs skip a symbol whose month digests are all
unchanged, and phase 186 reads the digests to know which feature units must be recomputed. **Not:** the provenance batch's input
digest (a feature-side record). **Banned:** (none)
**Status:** active (migration 383, phase 185 plans 11 and 17)
**Code surface:** `services/bar_derivation.py`

---

### `backfill`

Fetching history a provider already has and storing it in `ohlcv_raw`, whether the full
depth for a timeframe or the nightly update slice. Named for what arrives (history), not for
any effect on the system; nothing is drained, emptied, or reduced.
**Not:** a queue drain (emptying a dead-letter queue or flushing Kafka offsets on shutdown);
that sense of "drain" is a different concept and keeps its name (`indicagent-dlq-drain`).
**Avoid:** "drain" as a name for a history fetch (owner direction 2026-10-10; the full-depth
5m IBKR fetch was informally "the drain")
**Banned:** drain, the drain, draining
**Status:** active (owner direction 2026-10-10)
**Code surface:** `scripts/infrastructure/backfill/`, `ohlcv_request` lanes (`backfill`,
`gap_fill`, `update`)

### `ohlcv_history_fetcher` / `OHLCVHistoryFetcher`

The unified multi-provider OHLCV history fetcher: one BaseBatch oneshot process
(`scripts/infrastructure/backfill/ohlcv_history_fetcher.py`), one ledger-ranked queue, one
writer connection, one advisory-lock singleton; backfill/gap_fill/update/parity are lanes
(priorities) inside the loop, and each vendor is a `ProviderEntry` in the fetcher's registry
whose `leaf_factory` builds a `HistoryProvider` leaf. **Not:** the retired per-campaign
scripts it replaced (one fetch CLI per vendor), and not the nightly capture runner
(`ops_bar_nightly`, the T4 tail-capture shell; its lanes join this loop when the Alpaca
ProviderEntry lands). **Banned:** naming any new fetch path after one vendor.
**Status:** active (phase 190 cutover, 2026-10-10); the parity lane as a separate store-path
retired 2026-10-17 with plan 191-16 (parity rows are ordinary `ohlcv_raw` rows keyed by
vendor; the lane survives only as the fetcher's sampling priority)
**Code surface:** `scripts/infrastructure/backfill/ohlcv_history_fetcher.py`; external
identities intentionally keep the ibkr name (`FETCHER_LOCK_NAME`, JOB label
`ibkr-history-fetcher`, `indicagent-ibkr-history-fetcher.*` units,
`logs/ibkr_history_fetcher_status.json`) — renaming any of them means moving every consumer
in one commit.

### `HistoryProvider`

The Ring 0/1 batch history protocol (`src/providers/base.py`) a vendor leaf satisfies so the
fetcher dispatches the protocol, never a concrete leaf (CI fence:
`tests/unit/test_provider_leaf_boundary.py`). A leaf owns its vendor's credentials,
pagination, native pacing, and symbology, and reports every request as a
`RequestRecord`; policy never enters a leaf. Sibling of the streaming `DataProvider`; the
per-domain pattern matches `EconomicSource`. **Not:** a plugin or a discovered class — a
vendor is one leaf module plus one `history_leaf` registry entry, deliberately.
**Avoid:** importing a concrete leaf outside `src/providers/` (the boundary fence enforces it).
**Banned:** (none)
**Status:** active (phase 190 plan 01; leaves: `IBKRProvider`, `AlpacaProvider`)
**Code surface:** `src/providers/base.py`, `src/providers/{ibkr,alpaca}.py`,
`history_leaf()` in `src/providers/__init__.py`

### `per-provider tier`

The planning source of record for the fetch queue: `ohlcv_provider_head`, keyed
(symbol, provider, timeframe) with that provider's measured floor, plus the per-provider
failure state on `ohlcv_coverage`. The planner reads this tier only; a provider's own floor
answers "how deep can this vendor go" so one vendor's ceiling never masquerades as missing
data for another. **Not:** the canonical tier (stored-state rollups), and not a provenance
claim. **Banned:** (none)
**Status:** active (migration 465, phase 190 plan 02/03)
**Code surface:** `ohlcv_provider_head`; `scripts/infrastructure/backfill/_fetch_queue.py`

### `canonical tier`

`ohlcv_coverage` as the stored-state ledger written in the same transaction as the bars it
describes, provider-labeled since migration 465 (PK symbol, timeframe, provider). Its rows
are rollups of what is stored, not claims about which vendor's answer is truer — truth at
the capture layer lives in `bar_source_policy`/D7. **Not:** the per-provider tier.
**Banned:** (none)
**Status:** active (migration 432 + 465)
**Code surface:** `ohlcv_coverage`; `services/ohlcv_coverage_writer.py`

### `no-data verdict`

The evidence-carrying answer that a vendor definitively has nothing for a span:
`NoDataVerdict` (IBKR contributes chunk-count evidence, a REST leaf sets
`authoritative_empty`), recorded in `ohlcv_empty_history`. A verdict tombstones the span so
gap planning stops re-asking; timeouts and failures never count as verdicts. **Not:** an
error, and not an empty page (a page can be empty because the window is pending).
**Avoid:** calling an empty page "no data" without the verdict.
**Banned:** (none)
**Status:** active (phase 190 plan 01)
**Code surface:** `src/providers/base.py` `NoDataVerdict`; `ohlcv_empty_history`

### `raw archive`

The retired per-supplier observation store: `ohlcv_intraday_raw_archive`, keyed
(timestamp, symbol, timeframe, source) since migration 468. It held every bar a vendor
served that canonical authoring did not store — another source's span, extended-hours rows —
plus the 15m/1h stored-segment archive, so any two suppliers' tapes stayed comparable
row-for-row and vendor-agreement audits never depended on a tape the pipeline deleted. The
compute path never read it (boundary fence). **Not:** scratch (staging, disposable after
reconciliation), and not a second canonical store. **Banned:** dropping non-authored served
rows (todo 528 R1; every served row survives in `ohlcv_raw`); a vendor re-archiving its own
canonical answer.
**Status:** retired 2026-10-17, plan 191-16 (migration 499 dropped the table; its rows live in
`ohlcv_raw`, backup in `data/backups/191/` to 2026-11-12; migration 383 + 468, no-drop engine
since todo 528)
**Code surface:** none live (`services/intraday_raw_archive.py` was deleted with the read side
by plan 191-08; the loader and the fetcher write `ohlcv_raw`)

### `source` (bar provenance) / `provider`

Every stored bar is labeled with the supplier that answered it: formerly the `source` column
on `market_data_ohlcv` (retired by the phase 191 swap, migration 497; the labels live on there
as `vendor` and `kind`) and the raw archive (`ibkr_named`, `alpaca`, `derived_5m`; the
archive dropped 2026-10-17, plan 191-16, its labels live on in `ohlcv_raw` as vendor/kind), and
`provider` on the ledgers (`ohlcv_coverage`, `ohlcv_provider_head`). The labels name the
same supplier; `ibkr_named` is the historical span-ownership label on stored IBKR rows and
stays as-is (stored rows are permanent history), while new code says `provider` and, on
canonical, `vendor`/`kind` with the vendor's registry name. Derived bars are labeled
`derived_5m` (kind on canonical since the swap): their provenance is
the 5m grid one level down, where each constituent row carries its own supplier — which
means a derived bucket straddling a span boundary is a blend of two vendors' tapes, and
vendor-agreement audits compare per source, never inside a blended bucket.
**Not:** the ingest `caller` (which program asked), and not `route` (which feed answered).
**Banned:** joining provider-labeled tables to source-labeled tables on the label alone.
**Status:** active (labels date to migrations 383/446/464/465/468; ruling 2026-10-10; the
canonical `source` column itself retired by migration 497, phase 191)
**Code surface:** `bar_source_policy`; `ohlcv_coverage.provider`

### `ohlcv_raw`

The one table of vendor answers: every bar a vendor served, at the timeframe it served, keyed
(timestamp, symbol, timeframe, `vendor`, `kind`) and last-wins (a refetch replaces the earlier
answer; an unchanged re-offer writes nothing). Canonical `market_data_ohlcv` is a selection
from it by `bar_source_policy`, so canonical is rebuildable. `served_at`, `request_id` and
`load_id` are nullable only for rows migrated from stores that never captured them. No CHECK
on vendor or kind: the writer validates against the CVR namespaces. **Not:** the canonical
table, an append log of every request, or a store of derived bars. **Banned:** dummy ids or
`now()` stamps for the nullable lineage columns.
**Status:** active (migration 472, phase 191 plan 01; the one store of vendor answers since plan
191-05)
**Code surface:** `ohlcv_raw`; `services/ohlcv_raw_writer.py` (the one writer, reached through
`services/ohlcv_ingress_contract.py`); `src/intelligence/bars/vendor_kind.py`

### `bar_vendor`

The CVR namespace of who served a bar: `ibkr`, `alpaca`, `tradier` (stored history only) and
`derived` (the 15m/1h grid, never served by a vendor). A new vendor is a CVR row, a
`history_leaf`, a `VendorIngress` row and APR seeds, never a migration. **Not:** the bar
`source` label (which mixes vendor and kind) or `ohlcv_load.source`.
**Status:** active (migration 472)
**Code surface:** `controlled_vocabulary` namespace `bar_vendor`; `VocabularyService`;
`BAR_VENDORS` in `src/intelligence/bars/vendor_kind.py`

### `bar_kind`

The CVR namespace of what a vendor served, within one vendor: `named`, `venue` and the per-venue
`venue_nyse`, `venue_arca`, `venue_island`, `venue_amex`, `venue_bats`, `continuous`,
`official`, `generic`, `smart_trades`, `smart_adjusted`, `consolidated`, `sip_rth` (Alpaca SIP,
regular hours, split-adjusted), `5m_grid`, `fallback`, and `iex_rth` (Alpaca feed=iex, kept in
raw and never selected: IEX prints are a few percent of consolidated volume). A raw kind is what the vendor served, so `fallback` is a canonical-only kind: a
selection outcome the daily rule assigns, never written to `ohlcv_raw`. Its `sort_order` is the
within-vendor selection precedence. **Not:** a timeframe or a vendor.
**Status:** active (migration 472)
**Code surface:** `controlled_vocabulary` namespace `bar_kind`; `BAR_KINDS` in
`src/intelligence/bars/vendor_kind.py`

### `revision` / `disagreement`

A `revision` is one vendor changing its own answer for a slot; the old value is logged in
`ohlcv_revision` and the raw row is replaced. A `disagreement` is two vendors answering one slot
differently; both rows stay in `ohlcv_raw` and selection resolves it by policy, never as an
error and never as a refusal. **Not:** interchangeable: a cross-vendor difference is never a
revision, and a revision ratio is measured against the same vendor's own stored rows.
**Status:** active (phase 191; nothing is refused or held, owner decision 2026-10-14, D-191-N)
**Code surface:** `ohlcv_revision`, `ohlcv_raw`

---

## Volume guard terms (todo 560)

How the feature kernels treat a bar whose volume is missing and a change of volume basis. Code:
`src/intelligence/features/contract/registry.py` (`_guard_volume`, `_guard_downstream`,
`_masked_until_reset`) and `contract/dropped_volume.py`; history and measurements:
`.planning/todos/pending/560-volume-kernels-span-the-volume-basis-seam.md`.

### `dropped bar`

A bar whose volume is NULL, so non-finite in the kernels (the canonical view NULLs volume for the
ibkr `venue` and `fallback` kinds; 125,174 such 1d rows on 145 names on 2026-10-29). Industry term:
a missing volume observation. The volume guard enters its volume as 0.0 so a cumulative statistic
stays finite, then masks the rows that bar corrupts. **Not:** a bar removed from the table (raw bars
are permanent), and not a zero-volume bar, which is a real observation.

### `volume basis`

Which venue population a bar's volume counts: consolidated (Alpaca SIP) or IBKR SMART, about 0.75 of
consolidated. A window that holds both carries a level shift, so the guard runs each basis segment
alone for kernels that read the volume level. Field `volume_basis`; table in `bars/vendor_kind.py`.

### `volume reset anchor`

The calendar boundary at which a path-dependent volume kernel's accumulator restarts: `week` (ISO
week of the bar timestamp) or `session` (the ET session day). Kernel field `Kernel.volume_reset`. A
dropped bar masks that kernel's rows from the bar to the next anchor. A kernel with no anchor
(`vwap_dev_sigma`, `ctf_source`, the higher-timeframe `ctf_vwap_align`) is masked past a share of
dropped bars instead.

### `dropped share`

The share of dropped bars among the bars accumulated since the first bar with volume. A
cumulative-VWAP row is NaN while it exceeds the APR value `feature.volume.dropped_max_fraction`
(default 0.05, `FeatureFactoryConfig.dropped_volume_max_fraction`). Leading dropped bars carry no
weight and do not count, though their own rows are NaN. Function `dropped_share_mask`.

### `input gap` (regime status)

`segment_status` 5 (`STATUS_INPUT_GAP`): a regime family that reads volume saw a non-finite volume
followed by finite rows, so its whole series is unlabeled (code NaN, label None) while the other
kernels of the series still compute. Distinct from 0 (no model yet). **Not:** a failure; the
marginalizing walk-forward that would label across the gap is a later item (todo 563).

---

## See Also

- `docs/foundation/naming-system.md` — mechanical derivation of code surfaces from concept names
- `docs/foundation/principles.md` — the governing principles that determine why terms are defined this way
- `docs/foundation/adaptive-parameter-registry.md` — Adaptive Parameter Registry (APR) full specification
- `docs/signals/signals-confidence-patterns.md` — ECL definition and boundary invariant
- `docs/signals/signal-trade-separation-ADR.md` — 3-table architecture decision record (Phase 127+)
- `tag_vocabulary` table — the live controlled vocabulary for instrument tags
- `docs/research/stratification-security-classification-hierarchy.md` — `classification scheme` vs. `taxonomy` design (GICS vs. custom sub-classification), unscheduled
- `docs/research/stratification-dimension-unification.md` — StratificationDimension protocol for unified conditioning layer
