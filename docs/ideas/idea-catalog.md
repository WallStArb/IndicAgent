# Idea Catalog — Full-Tree Index

**Version:** 1.0
**Status:** current
**Last Updated:** 2026-07-03
**Purpose:** single point of navigation across every live idea/plan doc in `docs/ideas/` and
`docs/plans/`. Supersedes `docs/ideas/ai-index.md` (narrower scope, broken links after files were
renamed — archived, see note at bottom).
**Maintenance rule:** when a doc is created, retitled, retired, or superseded, update its row here
in the same commit. Archived docs are not listed individually below — see `docs/ideas/archive/`
and `docs/plans/archive/` directly; a doc's row here should be deleted, not left dangling, once
archived.
**Fable-reviewed** column: ✅ = carries `Author: Fable 5` / `Informed by: Fable 5` provenance from
an actual review pass; blank = never reviewed. Don't confuse "draft" status with "unreviewed" —
they're independent axes.

---

## Cluster 1 — v3.0 Intelligence Lifecycle (the active build surface)

**Master priority doc for this whole cluster:**
[2026-07-01 Intelligence Lifecycle Backlog Matrix](2026-07-01-intelligence-lifecycle-backlog-matrix.md)
— HIGH/MEDIUM/LOW triage across everything below, refreshed against real code/DB state (not
assertion) as of 2026-07-02 evening. Read this first for "what's next," not this catalog.

| Doc | Status / Priority | Fable-reviewed | One-line |
|---|---|---|---|
| [intel-10: Confluence — a Governed Predictor Family](intel-10-confluence-detection-persistence-layer.md) | draft, high | ✅ (v3, 2026-07-03) | Confluences as governed predictors, not a second system; gates 1-6, mandatory shrinkage |
| [intel-12: StratificationDimension](intel-12-stratification-dimension.md) | draft, high | ✅ | Unified conditioning layer across regime/vol/session strata |
| [intel-13: AnalogEngine](intel-13-analog-engine.md) | draft, high | ✅ | Non-parametric K-NN retrieval as a predictor family; Score Object deleted, return-distribution primitive kept |
| [intel-14: IntegrityMonitor](intel-14-integrity-monitor.md) | draft, high | ✅ | Drift/decay/ensemble-health, reconciled from a 10-doc cluster |
| [intel-15: MeasurementEngine](intel-15-measurement-engine.md) | draft, high | ✅ | Where kernel unification actually stands; now carries the Cross-Sectional Rank IC (T3) addendum |
| [Concept Governance Registries](concept-governance-registries.md) | — | | Four-table MVP (concept_registry/gate/transition_log/annotation) for evidence-gated lifecycle across domains |
| [Feature Registry](feature-registry.md) | — | | DB-backed feature governance (todo 008, COMPLETE) |
| [Edge Source Thesis](edge-source-thesis.md) | draft, high | | T1-T4 falsifiable theses on where edge comes from; standing doc, revisit per thesis |
| [Canonical Simulator](canonical-simulator.md) | draft, **critical** | ✅ (v2, 2026-07-03) | One counterfactual ledger + cost kernel + run identity, not a replay engine; enforced via pre-commit Check 9 |
| [Trade Construction Layer](trade-construction-layer.md) | draft, high | | Forecast → position; v4.0 concern, gated on the T3 falsification result |
| [Instrument Tag Calibrator](instrument-tag-calibrator.md) | draft, high | | Todo 040/Phase 145 (renumbered 2026-07-04); routing currently ignores calibrated weight |
| [Cross-Group Lead-Lag IC](cross-group-lead-lag-ic.md) | idea, gated on Phase 144 | | 6 candidate cross-group pairs; needs `regime_group` first |
| [Comomentum Crowding Metric](comomentum-crowding-metric.md) | — | | Cross-sectional crowding metric for momentum regimes |
| [Interaction Factory](interaction-factory.md) | idea, no build trigger met | | Combinatorial-factory alternative rejected in favor of Phase 150's curated ≤50 interactions |
| [Controlled Vocabulary](controlled-vocabulary.md) | idea, unscheduled | | Ready to build whenever prioritized; prerequisite already satisfied |

**Superseded / legacy within this cluster (kept for reference, not active):**
[intel-04: I6 Confluence Patterns](intel-04-confluence-patterns.md) (superseded by intel-10) ·
[intel-05: I6 Confluence Architecture](intel-05-i6-confluence-architecture.md) (adopted, v2.x-era)

---

## Cluster 2 — Pre-v3.0 Intelligence Backlog (I1-I9 era, mixed relevance)

Legacy indicator/regime ideas from the archived I1-I7 plugin tier. Some content may still be
salvageable into v3.0's Feature Factory / Phase 150 — check before assuming dead.

| Doc | Status / Priority | One-line |
|---|---|---|
| [intel-01: Momentum Acceleration](intel-01-momentum-acceleration.md) | draft, medium | Second-derivative momentum features |
| [intel-02: Second Derivative Indicators](intel-02-second-derivative-indicators.md) | draft, medium | Current state + future additions |
| [intel-03: Future Indicators Backlog](intel-03-future-indicators.md) | draft, low | Grab-bag of candidate indicators |
| [intel-06: Regime Transition Detection](intel-06-regime-transition-detection.md) | draft, medium | Early detection of regime transitions |
| [intel-07: HMM Multi-TF Training](intel-07-hmm-multi-tf-training.md) | draft, high | Multi-timeframe HMM design; largely superseded by shipped HMM improvement plan — check against `project_hmm_improvement_decisions` memory before reading as current |
| [intel-08: Macro & Cross-Asset Intelligence](intel-08-macro-cross-asset.md) | draft, medium | Improvement backlog for macro/cross-asset features |
| [intel-09: Intelligence Stack Latency](intel-09-stack-latency.md) | under-review, medium | Latency reduction across the (now archived) I1-I7 stack — likely stale given v3.0's architecture |

---

## Cluster 3 — AI / ML / Agentic

**Was indexed by** `docs/ideas/ai-index.md` **(now archived — see bottom note).**

| Doc | Status / Priority | One-line |
|---|---|---|
| [ai-01: AI Integration Paths](ai-01-integration-paths.md) | draft, high | Where LLM/agent integration points fit in the pipeline |
| [ai-02: MLAgent — Renaissance-Style Learning Machine](ai-02-ml-agent-architecture.md) | under-review, high | Check against `ensemble_trainer.py` — may already be partially subsumed (flagged unverified in the 2026-07-01 backlog matrix) |
| [ai-03: Evolvable AI Agents](ai-03-evolvable-ai-agents.md) | draft, low | eAI for alpha generation; no evidence current single-model approach is insufficient (backlog matrix LOW tier) |
| [ai-05: Intelligence Swarm Manifest](ai-05-intelligence-swarm-manifest.md) | under-review, high | "The Renaissance Loop" — swarm-level orchestration vision |
| [ai-06: MCP Intelligence Server](ai-06-mcp-intelligence-server.md) | under-review, medium | Agent tool-use via MCP |
| [ai-07: I8 Intelligence Extensions](ai-07-i8-intelligence-extensions.md) | draft, medium | Near-term POCs for the I8 AI layer |
| [ai-08: ML Classification / Pattern Recognition](ai-08-ml-classification-pattern-recognition.md) | draft, medium | Supervised classification for pattern recognition |
| [ai-09: Agent Orchestration Patterns](ai-09-agent-orchestration-patterns.md) | draft, low | Specialist intelligence orchestration patterns |
| [ai-10: Qualitative Intelligence Layer](ai-10-qualitative-intelligence-layer.md) | draft, medium | Architecture for qualitative (non-numeric) intelligence |
| [ai-11: Self-Directed Alpha Search](ai-11-alpha-search-orchestration.md) | draft, medium | Population-based orchestration for alpha search |
| [Occam's Razor Evaluator](ai-occam-razor.md) | proposed, high | Complexity-aware model selection; backlog matrix: "nothing complex to gate yet" |
| [AI Swarm Performance Analysis (2026-05-27)](ai-swarm-performance-analysis-2026-05-27.md) | draft, high | Dated performance analysis — check currency before relying on it |
| [ML/AI Palette](ml-ai-palette.md) | under-review, medium | Research/rationale/decisions across the ML/AI tech landscape |

---

## Cluster 4 — Platform / Infrastructure

| Doc | Status / Priority | One-line |
|---|---|---|
| [platform-01: Architecture (Vision)](platform-01-architecture.md) | draft, high | Unified intelligence & execution suite — long-horizon vision |
| [platform-02: Tech Stack](platform-02-tech-stack.md) | draft, medium | Decisions/reasoning/migration path |
| [platform-03: AI/ML Tech Stack](platform-03-tech-stack-intelligence.md) | under-review, high | Consolidated AI/ML stack reference |
| [platform-04: Kubernetes](platform-04-kubernetes.md) | draft, low | **Check against CLAUDE.md's explicit "no Kubernetes HPA" rule before relying on this — likely stale** |
| [platform-05: Redpanda Stream Topology](platform-05-stream-topology.md) | draft, low | Granular stream topology proposal |
| [platform-06: Service Resilience Patterns](platform-06-service-resilience.md) | draft, low (Pattern 1 shipped) | Circuit breaker (Pattern 1) already elevated to Phase 084 |
| [platform-07: Persistence Fragility](platform-07-persistence-fragility.md) | draft, high | Assessment of persistence-layer weak points |
| [platform-08: Architectural Weaknesses](platform-08-architectural-weaknesses.md) | under-review, high | General weakness assessment — cross-check against `docs/ideas/2026-07-01-intelligence-lifecycle-backlog-matrix.md` and the 2026-07-02 topdown/bottomup reviews, which supersede parts of this for the v3.0 layer specifically |

---

## Cluster 5 — Signal / Trade Layer

| Doc | Status / Priority | One-line |
|---|---|---|
| [2026-06-08: Signal/Trade Separation Architecture](2026-06-08-signal-trade-separation-architecture.md) | — | Renaissance-grade data normalization between signal and trade concerns |
| [signal-01: Signal Measurement Quality](signal-01-observability.md) | draft, medium | Observability for signal quality |
| [signal-02: Orderflow-Based Setups (Research)](signal-02-orderflow-setups.md) | draft, low | Order-flow research setups |
| [signal-03: Regime-Adaptive Trading (Research)](signal-03-regime-adaptive-trading.md) | draft, medium | Adapting trade logic per regime |
| [signal-04: Timeframe Cascade Strategy](signal-04-timeframe-cascade-strategy.md) | draft, low | Structured strategy for TF-cascade execution |
| [signal-05: Control Loop Separation](signal-05-control-loop-separation.md) | draft, medium | Separating signal generation from control loops |
| [signal-06: Renaissance-Style Refinements](signal-06-renaissance-refinements.md) | draft, medium | Intelligence refinement ideas in the Renaissance style |
| [signal-07: Signal-Ranker](signal-07-signal-ranker.md) | draft | Ranking mechanism across concurrent signals |
| [signal-08: Intelligence Vectors / Signal Layer Refactor](signal-08-intelligence-refactor.md) | working draft | **Flagged in the 2026-07-01 backlog matrix as possibly the actual v3.0 Feature Factory precursor — read directly before assuming stale** |
| [SR / Zone Engine Improvements](sr-zone-engine-improvements.md) | ideas, medium | Support/resistance and zone-engine improvement ideas |

---

## Cluster 6 — Product Vision (long-horizon, out of current scope)

| Doc | Status / Priority | One-line |
|---|---|---|
| [vision-01: AegisAgent](vision-01-aegisagent.md) | draft, low | Independent risk-management platform |
| [vision-02: DerivAgent](vision-02-derivagent.md) | draft, low | Derivatives intelligence + autonomous options execution |
| [vision-03: PrimeAgent](vision-03-primeagent.md) | draft, low | Unified portfolio management platform |
| [vision-04: QualAgent](vision-04-qualagent.md) | draft, low | Qualitative intelligence platform |
| [vision-05: TradeAgent](vision-05-tradeagent.md) | draft, low | Autonomous trading application |
| [vision-06: FlowAgent](vision-06-flowagent.md) | draft, low | (title only — read before relying on) |
| [vision-07: FundAgent](vision-07-fundagent.md) | draft, low | (title only — read before relying on) |
| [Commercialization — Retail SaaS](commercialization-retail-saas.md) | draft, low | Tiered API / retail SaaS commercialization path |

---

## Cluster 7 — Renaissance Philosophy / Research

| Doc | Status / Priority | One-line |
|---|---|---|
| [renaissance-01: Jim Simons / Renaissance Principles](renaissance-01-simons-principles.md) | draft, high | Source research behind `docs/foundation/principles.md` |
| [renaissance-02: The Renaissance Framing](renaissance-02-framing.md) | draft, high | "How Simons would build this" applied to IndicAgent |
| [renaissance-03: Plugin State Management Bug Analysis](renaissance-03-state-management.md) | draft, high | Renaissance-style root-cause analysis of a specific bug |
| [Renaissance Primitives — OHLCV Expansion](renaissance-primitives-ohlcv.md) | idea, not planned | Candidate OHLCV-derived primitives |

---

## Cluster 8 — Ops / Misc

| Doc | Status / Priority | One-line |
|---|---|---|
| [BI Analytics Layer — Superset](bi-analytics-layer-design.md) | adopted, medium | Apache Superset as the BI layer (todo 022) |
| [Futures Roll Simplification](futures-roll-simplification.md) | adopted, medium | Architectural simplification of roll detection |
| [Latency & Persistence Audit](latency-and-persistence-audit-design.md) | draft, high | Architectural latency/persistence improvements |
| [Phase 142 Redesign — Musk 5-Step + Renaissance Audit](phase142-redesign-musk5step-audit.md) | — | Historical audit doc for Phase 142's redesign |
| [eAI Foundation Gaps and Phase Recommendations](eai-phase-recommendations.md) | draft, medium | Gap analysis feeding eAI-related phase recommendations |
| [AlphaEngine — Alternative Data Extension](alphaengine-alt-data-extension.md) | idea | Extending AlphaEngine to alt-data sources |

---

## docs/plans/ — Approved / Active Plans (distinct from `docs/ideas/` — these carry more commitment)

| Doc | Status | One-line |
|---|---|---|
| [2026-06-20: v3.0 Ground-Up Architecture](../plans/2026-06-20-alphaengine-architecture.md) | Approved design | The v3.0 rebuild's foundational architecture doc |
| [2026-06-25: v3.0 Alpha Lifecycle Schema](../plans/2026-06-25-v30-alpha-lifecycle-schema.md) | APPROVED | Referenced by Phases 142A/142B/147 (renumbered 2026-07-04) |
| [2026-06-19: HMM/GARCH/Kalman APR Migration](../plans/2026-06-19-hmm-garch-kalman-apr-migration.md) | — | APR migration plan for HMM/GARCH/Kalman params |
| [2026-06-26: Renaissance Optimization Roadmap](../plans/2026-06-26-renaissance-optimization-roadmap.md) | SUPERSEDED 2026-06-27 | Historical only |
| [2026-06-26: Salvageable AI & Intelligence Concepts from v2.x](../plans/2026-06-26-salvageable-ai-concepts.md) | EXTRACTED | What survived the v2.x → v3.0 transition |
| [2026-06-27: ETF Universe Expansion](../plans/2026-06-27-etf-universe-expansion.md) | in progress | 58→80 instrument expansion; backfill currently running (see session state) |
| [2026-06-28: HMM Regime Audit & Optimization](../plans/2026-06-28-hmm-regime-audit-optimization.md) | — | Companion to todo 026 |
| [2026-06-28: Renaissance Obstacle Map v3.1+](../plans/2026-06-28-renaissance-obstacle-map.md) | Planned, unblocked after V1 corpus rerun | Obstacle map for the v3.1+ path |
| [2026-06-30: AlphaEngine V1 — Methodology Hypotheses](../plans/2026-06-30-alphaengine-methodology-hypotheses.md) | Active | Three hypotheses requiring empirical validation |
| [2026-06-30: AlphaEngine V1 — Execution Plan](../plans/2026-06-30-alphaengine-v1-execution-plan.md) | Phase A COMPLETE, Phase B next | The concrete work-plan tracking Phase A/B execution |
| [2026-07-01: Cross-Sectional Regime Model Implementation](../plans/2026-07-01-cross-sectional-regime-model.md) | — | Implementation plan for the `market_regimes` cross-sectional system |
| [Methodology Change Ledger](../plans/methodology-change-ledger.md) | STANDING, append-only | Every methodology change, forever — read before trusting any historical IC number |
| [OOS Evaluation Protocol](../plans/OOS-EVAL-PROTOCOL.md) | — | Pre-commit OOS evaluation protocol |

---

## Archived (pointer only — do not list rows here, browse directly)

- `docs/ideas/archive/` — superseded idea docs, including `intel-10-v2-confluence-persistence.md`,
  `intel-11-dual-system-discrete-vs-portfolio.md`, and the pre-consolidation AnalogEngine/
  IntegrityMonitor/StratificationDimension doc sets that fed intel-12/13/14.
- `docs/plans/archive/` — superseded plan docs, including the pre-142A IC-engine-improvements and
  feature-scoring-beyond-ic plans (content now carried in `intel-15`).
- `docs/ideas/ai-index.md` — **archived by this catalog 2026-07-03.** Its own links were stale
  (referenced `qualagent-vision.md`-style filenames that no longer match the current
  `vision-0N-*.md` naming). Cluster 3 above replaces it.

## References

- `.planning/research/2026-07-02-v3-topdown-architecture.md`, `2026-07-02-v3-bottomup-audit.md`,
  `2026-07-03-intel10-11-fable-review.md`, `2026-07-03-canonical-simulator-fable-review.md`
  (when complete) — the Fable review passes this catalog's "Fable-reviewed" column tracks
- `docs/ideas/2026-07-01-intelligence-lifecycle-backlog-matrix.md` — the priority triage for
  Cluster 1; this catalog is navigation, that doc is sequencing
