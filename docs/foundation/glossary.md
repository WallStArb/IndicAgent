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

A time-stamped, scored trade hypothesis with a defined entry, direction, and exit logic. Produced by I7 plugins. Persisted to `signal_events` (detection layer) with one or more corresponding `trade_frames` rows (hypothesis layer). Has a lifecycle: `pending` → `active` → `expired` / `regime_suppressed`.

**Not:** a Kafka message, an OTel metric, or a statistical signal-to-noise ratio. When "signal" appears in those contexts, use the domain-specific term instead: `message`, `metric`, `edge`.

**Banned:** (none)
**Status:** active

**Code surface:** `signal_events` table (Phase 128+), `SignalTracker`, `SignalWriter`. Legacy: `signal_ledger` (read-only during v2.10 migration, dropped in Phase 129).

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

A stateless computation unit in the I1-I7 intelligence pipeline. Receives a data frame, returns a dict of computed features. Has no Kafka connection, no DB access, no side effects. Named `PascalCasePlugin`.

**Not:** an agent, a service, or a daemon. Plugins are called synchronously within `IntelligencePipeline`.

**Banned:** (none)
**Status:** active

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

**Join view naming:** Phase 128 creates `signal_ledger_full` joining all three tables. Phase 129 drops the legacy `signal_ledger` monolith and renames `signal_ledger_full` → `signal_ledger`. After Phase 129, `signal_ledger` is the canonical query surface for the SLA.

**Not:** the `signal_ledger` table (legacy monolith, read-only during SLA migration, dropped Phase 129). `signal_ledger_v2` is a banned name — version-suffixed names violate the naming system.

**Banned:** "3-table architecture," "v2.10 schema," "new signal schema," "signal_ledger_v2" (all replaced by SLA)
**Status:** active (Phase 128+)

**Code surface:** `signal_events`, `trade_frames`, `trade_executions` tables; `signal_ledger_full` view (Phase 128) / `signal_ledger` view (Phase 129+); `docs/foundation/glossary.md` detection/hypothesis/execution layer entries.

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

**Code surface:** `config_schema`, `config_state`, `config_history`, `config_outbox` tables; `ConfigService`; `docs/foundation/parameter-store.md`.

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

## See Also

- `docs/foundation/naming-system.md` — mechanical derivation of code surfaces from concept names
- `docs/foundation/principles.md` — the governing principles that determine why terms are defined this way
- `docs/foundation/parameter-store.md` — Adaptive Parameter Registry (APR) full specification
- `docs/signals/signals-confidence-patterns.md` — ECL definition and boundary invariant
- `docs/signals/signal-trade-separation-ADR.md` — 3-table architecture decision record (Phase 127+)
- `tag_vocabulary` table — the live controlled vocabulary for instrument tags
