# V3 Top-Down Architecture — From the Core Value Downward

**Date:** 2026-07-02 · **Author:** Fable 5 (dispatched via Claude Code Agent tool) · **Type:** research/proposal, read-only · **Mandate:** clean-sheet conceptual architecture for v3, no sacred cows; sibling to an independent bottom-up review (not seen)
**Core value anchored on:** "Alpha must be demonstrated empirically before any ensemble weight is assigned. IC is measured on the full unbiased feature corpus, not on selection-biased signal events." (PROJECT.md)
**Method:** Musk 5-step applied in order — requirements interrogated first, deletion before optimization, nothing accelerated that hasn't earned its place.

---

## 1. Executive Summary

1. **The system has one measurement engine's worth of requirements and at least four planned implementations of it.** `ic_engine.py` (feature IC), Phase 142A's `EnsembleICEngine` (alpha_score IC), AnalogEngine's "IC Factory" (`feature_ic_stats`, embedding-feature IC), and the analog scoring engine's sub-score IC are all `IC(predictor, forward_return)` per stratum with the identical statistical hygiene (Spearman, subsampling, bootstrap CI, BH-FDR, walk-forward, OOS). Proposal: **one predictor-agnostic Measurement Engine** — a pure stats kernel library (`src/intelligence/measurement/`) plus one `BaseBatch` service — and a `predictor` abstraction. Everything that claims to predict (a feature column, an ensemble alpha_score by weight_version, an analog composite, a converted I7 output) is a registered predictor measured by the same machinery into one table. This is the single highest-leverage structural change available.
2. **AnalogEngine should not be a peer pipeline (System 2); it should be a substrate plus a family of predictors inside the existing pipeline.** The analog-engine doc set (May/June, pre-v3.0) duplicates the whole measurement stack: its own `forward_returns` table (conflicting with the v3.0 canonical one), its own IC Factory, its own scoring engine, its own combiner (analog-engine-05). Delete the duplicated layers. Keep: pgvector substrate over `feature_vectors`, the `retrieve()` primitive, the OOD monitor. The analog outputs (`analog_expected_r`, `analog_hit_rate`, `analog_dispersion`, `analog_nn_distance`) enter the system as **predictors** measured by the one Measurement Engine and weighted by the one Ensemble. This deletes roughly half of the planned v3.2 surface while keeping all of its alpha content.
3. **The "Regime Stratification Layer" should be named, unified at the contract level, and demoted from truth to hypothesis.** Today: two unrelated services (`regime_writer.py` per-symbol HMM, `equity_regime_model.py`/Phase 151 `regime_group` cross-sectional), plus eight designed percentile-rank dimensions, plus a multi-engine HMM idea doc. Top-down these are all instances of one concept: a **stratification dimension** — a causal per-bar label whose only job is to sharpen IC estimates, and which must *earn its cells* empirically (orthogonality gate + substitution test). Unify behind one `StratificationDimension` provider contract hosted by two writers (one per storage grain), register each dimension as a governed concept, and let the Measurement Engine learn which axis combination maximizes IC separation. The todo 026 finding (HMM label quality is asset-class-dependent) is direct evidence the per-symbol HMM is a hypothesis, not an architecture fixture.
4. **The registry proliferation collapses to exactly three systems, and the collapse does real work.** Keep the three-type taxonomy already identified in `concept-governance-registries.md`: APR (Type 1, value-mutable params), **Concept Registry** (Type 2, evidence-gated lifecycle), Vocabulary (Type 3, static taxonomy incl. tags). Then actually use it: `feature_registry` → `domain='feature'`; ensemble weighting variants E1-E4 → `domain='ensemble_strategy'` (Phase 142B.1 is the build trigger); stratification dimensions → `domain='regime_model'`; predictors map 1:1 to concept rows. Kill the separately-planned `embedding_feature_registry` (ANALOG-02) and the "entity/predictor registry" idea — both are Concept Registry domains. Archive `shadow_registry` (legacy, dead).
5. **Measurement and decision must be physically separated tables.** The analog-engine-ic-factory doc states the invariant perfectly: "a threshold is a decision; it never belongs in a measurement table." Yet `feature_ic_scores.is_decaying` is a lifecycle decision written into the measurement table (Phase 143 / 149B design). Move all lifecycle state to the registry (Concept Registry rows); measurement tables carry facts and per-run gate *evaluations* only. This makes the decay/shadow state machine auditable in one place and keeps `truncate_derived_tables.sh` semantics clean (measurement is rebuildable; governance state is not).
6. **Instrument identity becomes a first-class read contract, not a side table.** The exposure-vs-sensitivity tag split (todo 041) is a genuine architectural fact: *exposure* tags (what a security is) drive peer-set/universe resolution (regime_group routing, breadth universes, factor construction, future portfolio constraints); *sensitivity* tags (what it correlates with) drive features and risk only. Enforce that split in the resolution code path (routing filters on exposure category only) and `AmbiguousRegimeGroupError` disappears structurally rather than case-by-case. Tags stay a Type 3 vocabulary; Phase 148's calibrator adds empirical weights later.
7. **Resequence: conditioning-and-identity foundations before AnalogEngine; dissolve v3.3.** AnalogEngine's retrieval hard-filters on regime labels — it is *more* sensitive to bad stratification than the IC engine (a wrong label silently pollutes every neighbor set). Therefore Phase 151 (with the commodity-group merge and exclude-unrouted policy), todo 026 P1-P3, the tag category audit (todo 041), and the volatility_regime substitution test all belong in a "Conditioning Foundation" milestone between v3.1 and the analog work, batched into one ic_engine re-run. v3.3 as a standalone milestone dissolves: Phase 148 joins the conditioning milestone (evidence-gated), Phase 151 moves earlier, nothing else remains.
8. **Phase 143.5 should default to a two-line phase.** Its own conditional already says retirement is the rule and conversion the exception. Commit now to: retire every I7 plugin whose information is captured by `feature_vectors` (expected: nearly all per CORPUS-07 design), and route the rare exceptions through the predictor abstraction (an I7 plugin's continuous confidence is just another predictor — no adapter layer, no mixing weights, no per-plugin APR keys). This deletes I7-03's `alpha.i7.mixing_weight_<plugin>` machinery entirely.
9. **Phase 142B is the seed of the canonical simulator — name it that and let it grow, but don't generalize early.** Frames + counterfactual P&L + pre-committed SHADOW-REVIEW.md is exactly right. The only structural change: `alpha_frames`' counterfactual machinery is the same concept as v2.x `trade_frames.counterfactual_pnl_r`; when v2.x retires, one simulator concept remains. Keep 142B as planned.
10. **What is not broken: the epistemology.** Unconditional corpus, executable returns, OOS holdout, BH-FDR, walk-forward, two-gate retirement, pre-committed criteria, APR, content-keyed idempotency, Ring 0/1/2, canonical-writer-per-fact. These are the Renaissance-grade parts. Every proposal above is a consolidation *within* that epistemology, not a change to it.

---

## 2. Proposed Target Architecture

### 2.1 Derivation from the core value

The core value implies a factory with exactly one product: **statistically defensible statements of the form "X predicted forward returns, under conditions C, out of sample, net of multiple-testing."** Everything else is either an input to that statement, a combiner of such statements, or governance around who may claim what. Working downward:

- To make the statement you need **facts**: prices, feature values, outcome labels, conditioning labels. Facts must be causal, versioned, unconditional (every bar), and owned by exactly one writer.
- You need **one way to make the statement** (the measurement engine). Two ways to measure IC is one way to fool yourself — divergent methodology between the feature-IC path and the ensemble-IC path would make Gate 1 (Phase 144) incommensurable with the feature gates that fed it.
- You need a **combiner** whose weights are themselves an experiment (weight_version = governed concept), and an **emitter** that is deliberately dumb (threshold + publish).
- You need a **simulator** that converts predictions into counterfactual P&L under pre-committed rules, because IC alone is not demonstrable alpha.
- You need **governance** that makes promotion/demotion mechanical and makes it structurally impossible for a persuasive thesis (human or AI) to promote itself.

### 2.2 The layer stack

```
                        ┌──────────────────────────────────────────────────────────┐
                        │  X. GOVERNANCE (cross-cutting; three registries)         │
                        │  APR (params) · Concept Registry (lifecycle: feature,    │
                        │  predictor, ensemble_strategy, regime_model/dimension)   │
                        │  · Vocabulary (enums, instrument tags: exposure vs       │
                        │  sensitivity)                                            │
                        └──────────────────────────────────────────────────────────┘

L0  MARKET FACTS         market_data_ohlcv                      BarWriter (unchanged)
        │
L1  FEATURE FABRIC       feature_vectors (typed columns)        FeatureFactory batch + live
        │                  ├─ atomic primitives (54 → 147-expansion)
        │                  ├─ interaction features (gated, Interaction Factory)
        │                  └─ analog predictors (from L1a substrate)  ← AnalogEngine lands HERE
        │
L1a ANALOG SUBSTRATE     embeddings (pgvector) + retrieve()     embedding batch (BaseBatch)
        │                  outputs: analog_* predictor columns + OOD monitor gauge
        │
L2  CONDITIONING         feature_vectors.<dim> cols (per-symbol grain)
    (Stratification)     market_regimes rows      (cross-sectional grain)
        │                one StratificationDimension contract; providers:
        │                  hmm_price_vol (regime_writer), regime_group signals
        │                  (Phase 151), volatility_pct, dispersion, ... (each a
        │                  governed regime_model concept, orthogonality-gated)
        │
L3  OUTCOMES             forward_returns (executable, immutable) ForwardReturnWriter (unchanged)
        │
L4  MEASUREMENT          predictor_ic_scores                     MeasurementEngine (one service,
        │                (generalizes feature_ic_scores +        stats kernel library shared)
        │                 alpha_ensemble_ic; facts only,          measures ANY predictor:
        │                 no lifecycle flags)                     feature | ensemble | analog | legacy_i7
        │
L5  COMBINATION          ensemble_weights + ensemble_alpha       EnsembleTrainer
        │                (weight_version = ensemble_strategy concept; E1→E2→E3→E4)
        │
L6  EMISSION             alpha_events (DB + Kafka)               AlphaPublisher (thin: threshold+CI)
        │
L7  SIMULATION /         alpha_frames (counterfactual)           AlphaFrameWriter +
    VALIDATION           gate_evaluations audit log               CounterfactualTracker (142B)
                         two-gate model: L4 measures the ensemble's own alpha_score
                         (Gate 1) — no separate EnsembleICEngine; Gate 2 from frames
```

Data flows strictly downward. Governance reads everywhere, writes only its own tables. No layer writes another layer's canonical table (canonical-truth-registry extends to the new rows below).

### 2.3 L4 — the Measurement Engine (the load-bearing proposal)

**Concept:** `predictor` — anything claiming to forecast forward returns. Identity lives in `concept_registry` (`domain='feature'` for the 54+ columns; `domain='ensemble_strategy'` rows own their alpha_score-as-predictor via `weight_version`; analog predictors are `domain='feature'` rows with `parent_concept_id`/dependency to the substrate; a converted I7 plugin, if any survive CORPUS-07, is just a feature row with provenance).

**Implementation shape:**

- `src/intelligence/measurement/` — pure-function stats kernel (todo 032 already asks for exactly this extraction): rank transform, stride subsampling, Spearman, Fisher-z, HAC, circular block bootstrap, corpus-level BH-FDR, expanding-window walk-forward. Zero I/O, zero APR reads (frozen config dataclass in, per Phase A3 pattern).
- `services/measurement_engine.py` (evolution of `ic_engine.py`, keeps `BaseBatch` + ProcessPoolExecutor + compute-only-workers): orchestration, corpus loading, stratification joins, persistence. Takes `--predictor-kind {feature,ensemble,analog}` or measures all registered enabled predictors.
- **Table:** `predictor_ic_scores` — `feature_ic_scores`' columns plus `predictor_kind` and `predictor_ref` (feature_name | weight_version | analog score name). Natural key extends the current content_key. Because `alpha_ensemble_ic` (migration 187) has **not landed yet** and `feature_ic_scores` is a derived table rebuilt every corpus run, the unification window is open *now* and closes when 142A executes. If the migration friction is judged too high mid-milestone, the acceptable fallback is: shared kernel library + two tables — but the unified table is the honest top-down answer and it is cheap this week.
- **Gates move out.** `passes_fdr`, `ic_ci_lower`, fold stats etc. remain as computed facts per row. *Eligibility* rules (who enters the ensemble, who decays, who is shadowed) are evaluated by consumers (EnsembleTrainer's feature_selector; the lifecycle engine) against those facts, and lifecycle state lives only in `concept_registry.status` + `concept_gate` last-eval cache. Drop `feature_ic_scores.is_decaying` from the design (Phase 143/149B adjust: AlphaDecayMonitor writes registry state, not measurement rows). This also resolves the 149B rename (`is_decaying → is_shadowed`) by deletion: the state is `concept_registry.status='shadow_only'`.

**What this does to Phase 142A:** every EIC requirement survives — EIC-01 becomes "register alpha_score(weight_version=N) as a predictor and run the Measurement Engine over `alpha_events ⋈ forward_returns`"; EIC-02 (decay curve → hold_max_bars APR calibration), EIC-03 (fold stability), EIC-04 (gate), EIC-05 (diagnosis script) unchanged in substance. What is deleted is a second service reimplementing Fisher-z/FDR/bootstrap ("compose ic_engine math" in the current plan is an admission this is one engine). Phase 142B.1's judge is then automatically methodologically identical to the feature gates — a nontrivial rigor win: variants E1-E4 are compared by the same estimator that admitted their inputs.

### 2.4 L2 — Conditioning (Regime Stratification) as one system

**Canonical vocabulary (glossary additions):** *Conditioning Layer* (the layer), *stratification dimension* (one axis), *stratum* (a cell). `regime` remains the name of the HMM price/vol dimension only.

**Contract (Ring 1):**

```python
class StratificationDimension(Protocol):
    name: str                      # 'hmm_price_vol', 'cross_sectional_equity', 'volatility_pct', 'dispersion'
    grain: Literal['per_symbol', 'cross_sectional']
    labels: list[str]              # from Vocabulary
    def compute(...) -> labels     # causal by construction; provider proves it
```

**Hosting (respects the settled storage split):** per-symbol dimensions are columns on `feature_vectors`, written by `regime_writer.py` (renamed conceptually to the per-symbol dimension host; the HMM becomes provider #1 among peers); cross-sectional dimensions are rows in `market_regimes`, written by Phase 151's `regime_group` dispatcher (which is already exactly this pluggable-provider shape — keep it, merge the fragmented commodity sub-groups into one `commodity` group per the n=1/4/5 finding, and change unrouted-symbol policy to exclude-with-loud-logging per the 2026-07-01 review's Gap A).

**Governance:** each dimension is a `concept_registry` row (`domain='regime_model'`), whose gate is the **substitution test** (run the Measurement Engine stratified by the candidate *instead of* the incumbent; IC-separation delta is the metric) plus the **orthogonality study** (correlation vs existing dimensions below `alpha.regime_stratification.max_correlation`). This converts the regime-stratification-alternatives doc's informal implementation order into mechanical promotion. The multi-engine HMM doc's real contribution — the E0-E4 *domain taxonomy* — becomes the candidate list; its own 2026-07-01 verdict (percentile-rank first, HMM engines only on proven insufficiency) becomes each candidate's default mechanism.

**Axis selection is learned, not chosen.** The Measurement Engine records which dimension (or validated combination) each predictor's IC was conditioned on; the EnsembleTrainer keys weights on the stratification that produced the tightest CI per predictor (the regime-alternatives doc already states this; make it the design, with the N-budget guard: a combination that starves cells below `alpha.ic.min_obs_per_regime` is inadmissible regardless of separation).

**The two designed HMM↔regime_group bridges (IOHMM, factor-augmented) stay gated** on todo 026's empirical-deficiency proof and now have Phase 151 as a structural prerequisite — consistent with placing Phase 151 in the earlier Conditioning Foundation milestone (§3).

### 2.5 L1a — AnalogEngine, v3-native

Keep from the doc set: the embedding serialization law (per-feature rolling point-in-time z-score/percentile, categoricals as filters not dimensions, versioned contract, L2-normalize), pgvector HNSW, `retrieve()` returning `list[AnalogResult]` with distances and the null result as a first-class value, the OOD monitor.

Change:

- **Substrate reads `feature_vectors`, not `intelligence_features`** (the docs predate v3.0 and cite the v2.x tables; `intelligence_features` is look-ahead-contaminated and already excluded from the training path).
- **Outcome labels come from the existing canonical `forward_returns`.** The substrate doc's own `forward_returns` DDL is deleted — one canonical writer per fact.
- **The IC Factory, Scoring Engine, and Signal Combiner (analog-engine-05) are deleted as separate systems.** The scoring engine's sub-scores (directional hit rate over analogs, expected R, dispersion, distance-weighted composite) become **analog predictor columns** computed by a nightly `BaseBatch` (join retrieval to `forward_returns`, write `analog_expected_r`, `analog_hit_rate`, `analog_ret_dispersion`, `analog_nn_dist` per bar — either as `feature_vectors` columns or a sibling `analog_scores` table keyed identically). The Measurement Engine measures them; the EnsembleTrainer weights them; Ledoit-Wolf/mean-variance decorrelation handles their redundancy with parametric momentum features automatically. "System 2 as an independent complement" is preserved in the only sense that matters — a non-parametric information source — without a parallel measurement-and-combination stack that would need its own FDR discipline, its own decay monitoring, and its own retirement gates.
- **`embedding_feature_registry` (ANALOG-02) is not a new table.** Embedding membership/ordering is a versioned recipe: a `concept_registry` row per `embedding_version` with the ordered feature list in `metadata`, or a single `embedding_spec` table if the JSONB feels too loose. Either way it is governance, not a fourth registry system.
- **OOD distance doubles as a candidate stratification dimension** ("unprecedentedness" — low/mid/high nearest-neighbor distance), entering through the same L2 gate as every other dimension. Cheap, novel, and exactly the Renaissance reflex (reduce conviction out-of-distribution) expressed as conditioning rather than as a hand-coded override.
- **IC-weighted re-ranking (candidate_k + re-rank) is deferred** until plain-cosine analog predictors demonstrate IC. It is an optimization of a thing that hasn't yet earned existence (Musk step 3 before step 2 otherwise).

### 2.6 Governance — three registries, used hard

- **APR** — unchanged. Every new tunable above gets a key (`alpha.regime_stratification.max_correlation`, `analog.embedding.normalization_window_days`, `analog.retrieval.max_distance`, `alpha.ensemble.weight_method`, `alpha.ensemble.ic_input`, plus 142B.1's set).
- **Concept Registry (4-table MVP)** — build trigger fires at Phase 142B.1, against `ensemble_strategy` first (human-authored E1-E4, low proposer risk), exactly per the 2026-07-02 reassessment in `concept-governance-registries.md`. Then migrate `feature_registry` in as `domain='feature'`; register stratification dimensions (`regime_model`) as they are proposed; predictors resolve to concept rows. The six self-improvement invariants (engine-only status writes, no re-roll on same corpus build, proposal budgets, proposer track record, demotion symmetry, mandatory shadow for AI-sourced) ship with the MVP schema even though only invariants 1-2 bind initially.
- **Vocabulary (Type 3)** — tag vocabulary gains the explicit `exposure` vs `sensitivity` category attribute (todo 041); Controlled Vocabulary builds when Phase 151's label sets make enum drift a real risk (it seeds `regime_group` labels, the 9 cross-sectional labels, HMM labels). **`shadow_registry` is archived** — documented dead in the governance doc; drop with v2.x retirement (SCORE-05).
- **Canonical Truth Registry** stays a document, extended with the new rows: `embeddings` (writer: embedding batch), `analog_scores` (writer: analog scorer batch), `predictor_ic_scores` (writer: MeasurementEngine), `market_regimes` under `regime_group` (writer: cross-sectional dispatcher), `alpha_frames` (writers: AlphaFrameWriter/CounterfactualTracker), `gate_evaluations` (writer: gate scripts), `concept_*` (writer: evaluation engine + operator migrations).

### 2.7 Ring placement

Everything above respects Ring 0/1/2: measurement kernel and dimension contract are Ring 1 (`src/intelligence/measurement/`, `src/intelligence/stratification/`); `BaseBatch` stays Ring 0; services stay Ring 2; no service calls another service; batch layers never touch Kafka except the existing publisher; all new tables have one canonical writer; timestamps UTC.

---

## 3. Delta vs Current Structure

| # | Change | What it replaces | Why it is worth the disruption |
|---|--------|------------------|-------------------------------|
| D1 | **MeasurementEngine + `predictor_ic_scores`** (kernel extraction todo 032 elevated to structural) | `ic_engine.py` monolith + planned separate `EnsembleICEngine` + `alpha_ensemble_ic` (migration 187, not yet landed) + AnalogEngine's `feature_ic_stats` | One estimator = commensurable gates across features/ensemble/analogs; methodology fixes (like Phase A's) apply everywhere at once instead of drifting per engine. Window closes when 142A executes — decide now. |
| D2 | **Phase 142A re-scoped**: same EIC-01..05 requirements, implemented as predictor registration + Measurement Engine run | 142A-01's standalone EnsembleICEngine service build | Zero science lost; one fewer service; Gate 1 measured by the same code path as the feature gates it depends on. |
| D3 | **Lifecycle state out of measurement tables**: drop `is_decaying`/`decay_detected_at`/`recovery_eligible_at` from `feature_ic_scores` design; AlphaDecayMonitor (Phase 143) writes `concept_registry.status` via the evaluation engine | Phase 143 LIFECYCLE-03's write to `feature_ic_scores`; Phase 149B's `is_decaying → is_shadowed` rename | Measurement stays a rebuildable fact store; one auditable state machine; 149B's rename becomes unnecessary. |
| D4 | **AnalogEngine rescope (v3.2)**: substrate + analog predictors + OOD monitor; delete separate forward_returns/IC Factory/Scoring Engine/Combiner; no `embedding_feature_registry` table | Phases 145-146 as currently framed (System 2 with own scoring/enrichment stack); analog-engine-substrate/ic-factory/scoring/correlation doc-set as build spec | Halves v3.2 build surface; removes a second-source-of-truth `forward_returns`; analog alpha content is preserved and subjected to identical FDR/OOS discipline. analog-engine-correlation's effective-N job is already done for predictors by ensemble decorrelation. |
| D5 | **New milestone "v3.15 Conditioning & Identity Foundation"** (between v3.1 and analog work): Phase 151 (+ commodity merge + exclude-unrouted policy) + todo 026 P1-P3 + todo 041 tag category audit + volatility_regime substitution test — batched into ONE ic_engine re-run | Phase 151 parked in v3.3; tag calibrator in v3.3 after AnalogEngine; regime label validation scattered into Phase 143 Wave 0 | AnalogEngine hard-filters retrieval on these labels; building embeddings on known-suspect strata bakes bias into stored vectors (embedding_version bump = expensive re-embed later). Foundations before consumers. |
| D6 | **v3.3 dissolves.** Phase 148 (calibrator) joins v3.15 evidence-gated or trails it; nothing else remains | v3.3 "Foundational Hardening" (Phases 148-149, scope TBD) | A milestone whose scope is TBD and whose contents all belong earlier is a numbering artifact, not a plan. |
| D7 | **Phase 143.5 collapses to retirement-by-default now** (pre-commit the decision rather than the conditional); rare survivors become predictors via D1 — no adapter contract, no `alpha.i7.mixing_weight_*` keys, no I7-03 ensemble ingestion path | Phase 143.5's 3-plan conversion infrastructure | Its own gate already predicts ≥80% capture → retirement-only. Designing conversion infrastructure ahead of that evidence is Musk step 3 before step 2. I7-05's `i7_conversion_complete` prerequisite for retirement simplifies to "CORPUS-07 evaluated + survivors registered." |
| D8 | **Unified Conditioning Layer**: `StratificationDimension` contract; per-symbol host (`regime_writer`) + cross-sectional host (Phase 151 dispatcher); dimensions governed as `regime_model` concepts with substitution-test + orthogonality gates; axis choice learned by L4/L5 | Two unrelated regime services with no shared contract; regime-alternatives doc as informal backlog; multi-engine HMM as parallel idea | Makes "which conditioning is true" an empirical, mechanical question — the same epistemology the features get. Names the layer (glossary gap already flagged in the alternatives doc). |
| D9 | **Concept Registry MVP built at 142B.1** against `ensemble_strategy`; `feature_registry` migrates in; `shadow_registry` archived | Deferred-indefinitely status; Feature Registry as permanent bespoke sibling; dead shadow_registry lingering | 142B.1 produces 4+ governed variants with a defined judge — the doc's own build trigger fires. Building the weight_version lifecycle ad hoc inside ensemble_trainer would be bespoke governance #4. |
| D10 | **Tag category enforcement in routing**: peer-set/universe resolution reads exposure-category tags only; sensitivities never route | `AmbiguousRegimeGroupError` firing on OIH/XLE dual tags; per-symbol adjudication | Structural fix over case law; unblocks commodity group enablement permanently. |
| D11 | **Rename `feature_ic_scores` → `predictor_ic_scores`** (or add `predictor_kind` + `predictor_ref` and keep the name if the sweep is too broad) during the v3.15 re-run window | — | Derived table, rebuilt every corpus run; the rename is nearly free exactly once, now. |
| D12 | 149A/149B (drift + IC lifecycle monitors) unhooked from "v4.1" framing — they depend only on tables that exist and should be scheduled opportunistically after v3.15's re-run; 150 stays gated on ensemble IC (Gate 1 data) | v4.1 milestone framing implying execution-era timing | The roadmap note already admits the dependency claim; the milestone label is the only thing deferring cheap risk reduction. |

**Explicitly reconsidered and kept (not protected, but correct):** Phase 142B in full (frames, exit-trigger priority, no bar-level reversal exit, SHADOW-REVIEW pre-commitment); Phase 142B.1's E1→E2→E3→E4 order and its judge; Phase 144's two-gate retirement model; Phase 141's CORPUS gates; the v3.1-before-everything hard gate (OOS IC > 0 before diversification) — this is the Simons rule and nothing above weakens it.

---

## 4. What I'd Leave Alone and Why

- **The unconditional-corpus epistemology and the feature/signal vocabulary ban.** "The researcher produces features, the data discovers confluence, the IC engine arbitrates" is the correct core, and the retirement of the word "signal" did real work. Nothing above touches it.
- **`feature_vectors` as typed columns, `forward_returns` as immutable executable returns, gradient column naming, content-keyed idempotency, HMM_RANDOM_STATE in APR.** All load-bearing, all right.
- **Phase 142B and the SHADOW-REVIEW pre-commitment.** Pre-committing numeric promotion criteria before data collection is the single most Renaissance-grade discipline in the plan. Untouched.
- **The two-gate retirement model (Phase 144).** Signal proof and execution proof as independent gates with distinct failure diagnoses is exactly the falsifiability structure the project exists to practice.
- **BaseBatch / BaseWriter / BaseDaemon and the DAG invariants.** Every new component above slots into an existing base class; no new primitive is needed.
- **Phase B (corpus re-run) as the immediate next step.** Nothing in this document blocks or reorders it; D1/D11's decision window opens *after* B completes and before 142A executes.
- **APR.** The registry consolidation deliberately does not touch Type 1; APR's shape (value-mutable, validated, historied) is orthogonal to lifecycle governance and correct.
- **The interaction/primitives expansion (Phase 147) and Interaction Factory's evidence-based build trigger** (atomic-feature IC saturation). Correctly gated; the predictor abstraction makes their eventual intake cheaper but changes nothing about when.
- **Kelly/portfolio/execution deferred to v4.0.** Layer 2/3 absence is the plan, not a gap; the cost model belongs where fill data exists.

---

## 5. Open Questions (genuinely undecidable without a human call or more data)

1. **`predictor_ic_scores` unification vs shared-kernel/two-tables (D1/D11).** The unified table is cleaner and the window is open, but it renames a table referenced across ic_engine, ensemble_trainer, report generator, corpus scripts, and tests mid-milestone. Call: is one focused rename sweep during the v3.15 re-run acceptable, or does 142A ship on `alpha_ensemble_ic` with the kernel shared and the tables merged later (accepting the second table may never actually merge)?
2. **Pooled IC as shrinkage prior (E3)** still requires amending the "pooled is diagnostic only" load-bearing decision — unresolved from the 2026-07-01 review (its Q2). E3 is sequenced behind E1/E2 proving insufficient, so the decision can wait, but it is a human call, not an empirical one.
3. **Analog predictor storage grain**: columns on `feature_vectors` (simplest for the Measurement Engine; but couples the fabric's schema to substrate availability and embedding_version) vs a sibling `analog_scores` table keyed (symbol, tf, bar_ts, embedding_version) joined at measurement time (cleaner versioning; one more join). Leaning sibling-table for version hygiene; needs a schema decision at v3.2 planning.
4. **Where does the per-symbol HMM land if todo 026's baseline-separation query shows weak IC separation for non-equity asset classes** (the TLT finding)? Options: (a) per-asset-class HMM observation vectors, (b) demote HMM to shadow for those classes and stratify them on cross-sectional + volatility_pct only, (c) factor-augmented variant. This is exactly what the substitution-test machinery (D8) is for — but the *fallback default* if labels are weak (option b?) should be pre-committed before the query runs, in SHADOW-REVIEW spirit.
5. **Does the OOD/unprecedentedness dimension condition IC, cap conviction, or both?** Conditioning (a stratum) and conviction-capping (an emission-time multiplier) are different mechanisms with different failure modes; the substrate docs propose the latter, §2.5 proposes the former. Needs a small design note before v3.2; possibly both, gated separately.
6. **Concept Registry MVP timing risk**: building it at 142B.1 puts new governance infrastructure on the critical path of an alpha-proof milestone. Alternative: run 142B.1 on bare `weight_version` rows and backfill registry rows afterward. The doc's own discipline says infrastructure follows real candidates — 142B.1's candidates are real, but "governance can trail by one phase" is a defensible call either way.
7. **v2.x pipeline retirement pace.** The two-gate model gates retirement on v3 proof, but the v2.x fleet (121 plugins, ~13 services) is a running maintenance and cognitive cost through the entire proof period. Is there an intermediate step (freeze v2.x: no fixes, no tuning, dashboard-only) that reduces carry cost without touching the retirement gate? Human call on operational appetite.
