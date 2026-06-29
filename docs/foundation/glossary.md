# Glossary

**Version:** 2.0
**Status:** active
**Last Updated:** 2026-06-20

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

A time-stamped, scored trade hypothesis with a defined entry, direction, and exit logic. Produced by I7 plugins. Persisted to `signal_events` (detection layer) with one or more corresponding `trade_frames` rows (hypothesis layer). Has a lifecycle: `pending` → `active` → `expired` / `regime_suppressed`.

**Not:** a Kafka message, an OTel metric, or a statistical signal-to-noise ratio. When "signal" appears in those contexts, use the domain-specific term instead: `message`, `metric`, `edge`.

**Banned:** (none)
**Status:** active

**Code surface:** `signal_events` table (Phase 128+), `SignalTracker`, `SignalWriter`. Legacy: `signal_ledger` monolith (read-only during v2.10 migration, dropped in Phase 130).

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

## Instrument Vocabulary Terms

### `vocabulary`

The controlled set of valid tags and their categorical structure. Defined in the `tag_vocabulary` table. A vocabulary entry specifies: the tag name, its category, its description, and its measurement contract (factor series, method, lookback).

**Not:** "ontology" or "classification scheme" — these introduce ambiguity. Also not "taxonomy" when used as a loose synonym for the tag system — the tag vocabulary is flat (no parent/child hierarchy); use `taxonomy` only when describing a genuine hierarchical structure.

**Banned:** ontology, classification scheme
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
**Status:** planned (Phase 130)

**Code surface:** `CounterfactualTracker` daemon; `counterfactual_pnl_r` column on `trade_frames`; `signal_ledger_full` / `signal_ledger` view (see SLA).

---

---

### `AlphaEngine`

The v3.0 prediction engine: FeatureFactory → IC Engine → Ensemble → alpha emission. The full Layer 1 of the three-layer architecture. Parametric — measures Spearman IC between each `FeatureVector` column and subsequent forward returns, derives Ledoit-Wolf ensemble weights, scores every bar, emits `alpha_events` when `|alpha_score| > threshold AND ci_lower > 0`.

Runs entirely in the cold batch layer (weekly IC Engine, nightly Ensemble Builder, nightly Alpha Emitter). FeatureFactory runs in-process on the hot path, writing to `feature_vectors` as a DB sink only.

**Distinction from AnalogEngine:** AlphaEngine is parametric (Spearman correlation across all observations on pre-specified features). AnalogEngine is non-parametric (k-NN retrieval of similar historical bar states). Gated: AnalogEngine does not start until AlphaEngine demonstrates IC > 0 with p < 0.05.

**Not:** an enrichment annotator on `signal_events`. AlphaEngine replaces the I5-I7 plugin stack as the primary alpha source. It does not annotate the old signal architecture — it supersedes it.

**Plain role noun.** Services prefixed `alpha-`. APR namespace: `alpha.*`.

**Status:** pre-implementation (v3.0 Phase A-C)

**Canonical doc:** `docs/plans/2026-06-20-alphaengine-architecture.md`

**Formerly called:** "Intelligence Vectors" (internal working name — avoid)

---

### `AnalogEngine`

The non-parametric pgvector retrieval substrate (v3.0, System 2). Embeds full I1-I7 bar states as L2-normalized vectors in pgvector. Finds K nearest historical neighbors via HNSW index. Returns what price did after each analog at T+5/10/20/60. Does not score — scoring is the Scoring Engine (analog-engine-03). The null result ("no close analogs exist") is a first-class output and drives the OOD monitor.

**Distinction from AlphaEngine:** AnalogEngine is non-parametric (retrieves historical instances). AlphaEngine is parametric (measures Spearman correlation across all observations). Both are independent and additive.

**Plain role noun** — added to `naming-system.md` plain_role_nouns. Services prefixed `analog-` (e.g. `indicagent-analog-bar-embedder`). APR namespace: `analog.*`.

**Status:** design (pre-implementation, v3.0)

**Canonical doc:** `docs/plans/2026-06-20-analogengine-design.md` — also `docs/ideas/analog-engine-01` through `analog-engine-06` for per-layer detail.

**Formerly called:** "VIL" / "Vector Intelligence Layer" (internal shorthand still acceptable in code comments; canonical name is AnalogEngine)

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

The outcome that would have been realized if a trade frame hypothesis had been executed as specified, measured against actual subsequent price action. Computed by CounterfactualTracker for every `trade_frames` row regardless of execution status.

This is the ML training target for SignalRanker and all downstream ML models. Training on `actual_pnl_r` introduces survivorship bias (only executed signals have outcomes). Training on `counterfactual_pnl_r` eliminates it — every signal hypothesis has a measured outcome.

**Not:** a backtested result (which implies fitting to historical data). Counterfactual pnl_r is a forward measurement on live price action after signal emission.

**Banned:** "paper pnl," "simulated pnl"
**Status:** active (Phase 130+, populated by CounterfactualTracker)

---

### `CounterfactualTracker`

The daemon that measures `counterfactual_pnl_r` for every `trade_frames` row. Subscribes to `signal_events` Kafka topic. Maintains a per-symbol sliding window of price bars. For each signal event, registers the frame's entry/stop/target. On each new bar, checks all open counterfactual positions and closes them when stop hit, target hit, or TTL expired. Writes result to `trade_frames`.

**Architecture:** fully in-memory state; checkpointed to file on shutdown. No DB reads in the hot path — purely event-driven.

**Status:** planned (Phase 130)

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

Positive = composite features predict upward price movement. Negative = downward. Magnitude = strength relative to recent history. An `alpha_event` is emitted when `|alpha_score| > threshold[symbol][tf][regime]` AND `ci_lower > 0`.

**Not:** synonymous with `raw_confidence` (v2.x ICC, plugin-internal unsigned magnitude). Not the same as `counterfactual_pnl_r` (realized outcome). Not a per-feature score — `alpha_score` is the ensemble output, not any individual feature's contribution.
**Banned:** "plugin score," "direction score," "conviction score" (use `alpha_score`)
**Status:** design (v3.0 Phase C); stored in `ensemble_alpha` table

---

### `Information Coefficient (IC)`

The Spearman rank correlation between a predictor score observed at time `t` and the subsequent N-bar return. The primary empirical measure of a plugin's or vector's predictive power.

IC = 0.03-0.05 is meaningful in practice. IC = 0.10 is exceptional. IC is always measured with bootstrap confidence intervals — a plugin requires `IC_CI_lower > 0.0` at `n >= 100` observations to be considered predictive. IC is stratified by: timeframe, HMM regime, lookahead window (1/5/10/20 bars), and asset class.

IC is regime-conditional: the same plugin may have IC = 0.07 in trending regimes and IC = -0.01 in mean-reverting regimes. HMM regime conditions ensemble weights.

**Not:** mutual information (a different information-theoretic measure). Not `calibrated_confidence` (v2.x post-calibration output probability).
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

Generic names for the functional slots within Layer 1 (Prediction). Each slot has a
current implementation; the generic name survives if the implementation changes. Use
these terms in design docs, todos, and discussion -- not the specific formula name --
so that "we use HMM and a Hamilton switcher for regime classification" is a statement
about one slot, not two different things.

---

### `feature synthesis`

The functional slot that combines atomic primitives into higher-order composite features,
producing new FeatureVector columns that capture relationships between primitives that no
single primitive can express alone. Feature synthesis outputs are treated as first-class
features -- they flow through the same IC measurement, FDR correction, and ensemble
weighting as atomic features. The IC engine decides what survives; feature synthesis only
proposes candidates.

Distinct from feature computation (which produces atomic measurements from raw OHLCV)
and from the ensemble optimizer (which combines IC-validated features into a score).
Feature synthesis sits between them: it creates new features from existing ones, and
those new features are then independently evaluated by predictive measurement.

**Current implementations:**
- Hand-authored composites in `FeatureFactory` (e.g., `informed_flow` combining OFI and
  volume signals; `garch_ratio` combining realized vs implied vol)
- Planned: `Interaction Factory` (todo 019) -- systematic pairwise generation of all
  primitive combinations (products, ratios, rolling correlations), screened by IC engine

**In v2.x:** I5-I7 plugin stack performed a form of feature synthesis, combining I1-I4
measurements into pattern-level scores (ICC). The distinction: v2.x synthesis was
human-defined and the scores were traded directly. v3.0 synthesis is empirically screened
-- the IC engine validates every composite before it earns ensemble weight.

**Not:** the ensemble optimizer (which weights already-validated features). Feature
synthesis produces *candidates*; the ensemble optimizer weights *survivors*.

---

### `feature computation`

The functional slot that transforms raw OHLCV bars into a typed vector of observable
quantities for a single (symbol, tf, bar). Runs on the hot path on every bar.

**Current implementation:** `FeatureFactory` (54 features, I1-I4 cadence tiers)
**Output:** `FeatureVector` → `feature_vectors` table
**Not:** a storage or transport concern. Feature computation is pure transformation --
input is a bar, output is a vector. No DB reads, no Kafka.

---

### `regime classifier`

The functional slot that assigns each bar a discrete market context label used to
condition all downstream predictive measurement. A regime classifier consumes
`feature_vectors` (or raw OHLCV) and writes a label per (symbol, tf, bar_ts).

Multiple regime classifiers can coexist, each producing an independent stratification
dimension. The IC engine can be run stratified by any combination.

**Current implementations:**
- Per-symbol HMM (`regime_writer.py`) → `feature_vectors.regime` (5 labels)
- Cross-sectional equity model (`equity_regime_model.py`) → `market_regimes` (9 labels)

**Not:** a synonym for `regime` (the label output). The regime classifier is the
process; `regime` is the result.

---

### `predictive measurement`

The functional slot that measures whether each feature in the FeatureVector predicts
forward returns, across regimes, timeframes, and lookahead windows. Produces a scored
record per (feature, symbol, tf, regime, lookahead) that quantifies predictive strength
and statistical confidence.

Multiple predictive measurement methods can coexist, each capturing a different aspect
of the feature-return relationship.

**Current implementation:** Spearman IC (`ic_engine.py`) → `feature_ic_scores`
**Planned additions:** Mutual Information (`feature_mi_scores`), R²_OOS (column on
`feature_ic_scores`), IC decay curve (`feature_decay_profiles`) -- see todo 029
**Not:** a synonym for IC. IC is one predictive measurement method; the slot can hold
others. Say "the predictive measurement layer" when the statement applies regardless
of which method is used.

---

### `ensemble optimizer`

The functional slot that derives a weight vector from the history of predictive
measurement scores, producing a covariance-adjusted weight per feature that maximizes
expected portfolio IR subject to constraints. Runs on a batch schedule (weekly or
nightly) whenever new IC scores are available.

**Current implementation:** Ledoit-Wolf shrinkage on IC Sharpe time series
(`ensemble_builder` batch service) → `ensemble_weights`
**Not:** the scorer (which applies weights). The ensemble optimizer derives weights;
the alpha scorer applies them.

---

### `alpha scorer`

The functional slot that applies the current ensemble weight vector to each bar's
FeatureVector, producing a scalar score per (symbol, tf, bar_ts). Runs nightly on the
full `feature_vectors` history and in near-real-time on the hot path for live bars.

**Current implementation:** IC-weighted rank-normalized linear combination, z-scored
to standard deviation units → `ensemble_alpha.alpha_score`
**Not:** the emitter (which filters scores above a threshold). The alpha scorer scores
every bar; the alpha emitter selects which bars to act on.

---

### `alpha emitter`

The functional slot that filters alpha scorer output and emits actionable events when
the score crosses a threshold with sufficient statistical confidence. The boundary
between Layer 1 (Prediction) and Layer 2 (Portfolio). Every emitted event is a
hypothesis that a position should be opened.

**Current implementation:** `alpha_score > threshold[symbol][tf][regime] AND
ci_lower > 0` → `alpha_events` table
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
