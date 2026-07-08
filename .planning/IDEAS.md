# Ideas
Rough captures — no structure required, no commitment needed to add here.
When ready to flesh out: create `docs/ideas/<topic>.md` and link from here.
When actionable (clear problem + solution): create `.planning/todos/pending/<n>-<topic>.md`.
When ready to build: assign to a milestone in `ROADMAP.md` → `/gsd-plan-phase`.
Full planning system: `.planning/PLANNING-SYSTEM.md`.

**Scope note (2026-07-05):** this file has drifted to pre-v3.0-era ideas only — nothing below
tracks the active v3.0 intelligence cluster (Feature Factory, stratification, IC, ensemble,
Concept Registry, etc.). For that cluster's current, maintained index, use
`docs/research/idea-catalog.md` instead — it's kept in sync with that work; this file isn't,
and backfilling 75 bullets here to match it would just be duplicate upkeep. New ideas outside
the v3.0 cluster still belong here as before.

**Cleanup pass (2026-07-05):** every `docs/research/` link below was broken — they predate the
2026-06/07 rename to `vision-0N-`/`intel-0N-`/`platform-0N-`/`ai-0N-`/`signal-0N-` prefixes
(the same rot that got `ai-index.md` archived in favor of `idea-catalog.md`). Links fixed to
current filenames. Deleted outright (not just flagged): bullets describing the archived I1-I7
plugin tier where the underlying idea is dead, already superseded by something real in v3.0, or
where the only live overlap is narrower than the bullet claimed — verified each individually,
not blanket-removed. Also deleted 2 bullets citing an already-archived plan doc and todo numbers
since recycled for unrelated work (todo numbers aren't stable identifiers across eras here —
don't cite them as pointers). Kept: still-valid-but-deprioritized vision docs (different endgame,
not wrong) and the large `signal-06` Renaissance-refinement doc (105 ideas, unread at this
altitude — too big to responsibly call dead without actually reading it).

---
- **TradeAgent — Autonomous trading app** — see `docs/research/vision-05-tradeagent.md`. Separate app consuming IndicAgent; multi-tenant; LLM lead + guardrails; broker-agnostic (MCP); trade linkage (groups, options+equities); learning/self-improvement; observability, HITL, security; agent dashboards. Vision/ideas only; not on IndicAgent roadmap. Note: `PROJECT.md`'s endgame (personal live trading, confirmed 2026-07-05) makes this a different-endgame doc except for its execution-vehicle framing — see todo 059.
- **Commercialization — Retail SaaS + Tiered API** — see `docs/research/commercialization-retail-saas.md` for full writeup. Free/Pro/API/Premium CIS tiers. Data vendor swap (Databento) is hard blocker. CIS > 0.70 as premium gate is moot. Different endgame than `PROJECT.md`'s confirmed personal-live-trading focus — zero urgency unless that changes.
- **Delta Divergence Setup** — price makes new high but delta (buy vol - sell vol) diverges → reversal signal. Requires orderflow integration first (reqTickByTickData with bid/ask flagging).
- **Imbalance Continuation Setup** — strong delta imbalance (>70% one-sided) → momentum continuation. Requires orderflow integration first.
- **Absorption Detection** — large volume at a level with no price movement → hidden supply/demand. Requires orderflow.
- **QualAgent** — fundamental/qualitative intelligence extension: macro, corporate (10-K/10-Q), transcripts, sentiment, news, alt data, event arbitrage; agent suite; quantamental bridge. Bus designed to accommodate; build deferred. See `docs/research/vision-04-qualagent.md`.
- **News Sentiment Integration** — fetch headlines per instrument via RSS/API, LLM classifies bullish/bearish/neutral, factor into signal confidence. Dependency: news API subscription.
- **Roll premium/discount feature** — spread between front and back month at roll time. IS: contango/backwardation signal. Informative for CL (storage stress) and equity index (dividend/rate expectations).
- **Continuous contract support in live pipeline** — live services use named contracts (correct for trading). At roll, there's a one-time price gap in stored bars. Could store a parallel continuous-adjusted series for indicator computation, while keeping named contract for signal price levels.
- **I8 intelligence extensions** — Counterfactual Insight Generator, Regime Change Explainer, Anomaly Triage Assistant. All use existing LLM chain. See `docs/research/ai-07-i8-intelligence-extensions.md`.
- **Agent orchestration patterns** — MoA, adversarial red team, dynamic leadership, semantic memory, specialist agents. See `docs/research/ai-09-agent-orchestration-patterns.md`.
- **Service resilience patterns** — consumer proxy/circuit breaker, changelog streams, enhanced consumer lag metrics. See `docs/research/platform-06-service-resilience.md`.
- **Granular Redpanda stream topology** — per-tier topics for selective subscription. Not worth building until a real consumer justifies it. See `docs/research/platform-05-stream-topology.md`.
- **Regime Transition Early Detection** — `regime_entropy` + `hmm_regime_velocity` to detect Phase B/D transition windows. See `docs/research/intel-06-regime-transition-detection.md`.
- **Roll Detection Architecture Improvements** — dedicated `roll_events` table, signed `roll_gap` convention, `FUTURES_SPECS` per-symbol month cycles.
- **DerivAgent — Derivatives Intelligence** — volatility surface, GEX, VANNA/CHARM, VRP. Full options intelligence vision. See `docs/research/vision-02-derivagent.md`.
- **Macro & Cross-Asset Intelligence** — wire existing ftq_score/yield_curve_slope/corr_z into I4Context and intelligence_features; add thin I4 plugins; regime-segment setup_performance; extend with stock-bond correlation + VX term structure services. See `docs/research/intel-08-macro-cross-asset.md`.
- **Renaissance I7/I8 Refinement** — 105 ideas across 48 sections: alpha decay, hidden alpha, regime intelligence, adaptive learning, information theory, neural intelligence. See `docs/research/signal-06-renaissance-refinements.md` — written against the now-archived I7/I8 plugin tier; check which sections still apply to v3.0's Feature Factory before treating any of it as current.
- **Future Indicators Backlog** — Tracks B/C: I3 structure enhancements (SR zones, swing magnitude, trend structure), momentum composite (EMA stack score, golden/death cross, ADX qualification). See `docs/research/intel-03-future-indicators.md`.
- **SR / Zone Engine Improvements** — Post-Phase-116 backlog: regression-fit default_strength weights (todo 019, gate n>=500), zone width output, per-TF source priors, multi-session levels, touch/test memory, adaptive cluster radius, proximity-weighted score, source diversity min, stale level decay. See `docs/research/sr-zone-engine-improvements.md`.
- **Timeframe Cascade Strategy** — multi-TF trade management: micro entry (1m) → momentum hold (5m) → trend capture (15m/30m) → swing hold (1h/4h) → position hold (1d). See `docs/research/signal-04-timeframe-cascade-strategy.md`.
- **Momentum Acceleration (Second Derivative)** — f''(x) inflection points as earliest reversal signals; RSI/MACD/ROC acceleration. Core built in Phase 08, deeper ideas remain. See `docs/research/intel-01-momentum-acceleration.md`.
- **Second Derivative Indicators — Current & Future** — expansion ideas beyond Phase 08 baseline. See `docs/research/intel-02-second-derivative-indicators.md`.
- **Renaissance Framing** — foundational philosophy from Simons/Medallion approach. See `docs/research/renaissance-02-framing.md`.
- **Architectural Weakness Assessment** — top 7 weak links: pipeline god class (1820 lines), settings god object, 64-field ledger tuple, dead AI foundations (LineageRecorder/graduation), silent queue drops, bare excepts, unprotected global state. See `docs/research/platform-08-architectural-weaknesses.md`.
- **Cross-Group Lead-Lag IC** — does one `regime_group`'s state predict another's forward returns (e.g. rates→precious metals, industrial metals→bonds)? Reuses `ic_engine`, new join pattern not new infra. Gated on Phase 151 (`regime_group`). See `docs/research/cross-group-lead-lag-ic.md`.
- **Generic orthogonality/redundancy gate** — intel-12's regime-dimension gate protocol (structural pre-filter → correlation/MI study → substitution test) generalizes to features and vectors; the statistical test inside it doesn't (scalar correlation vs. cross-vector needs CCA/leakage-regression). Feature-level already has a home (Feature Registry's promotion gate, once migrated to `concept_registry`); cross-vector doesn't yet. Not buildable now — no real caller exists (intel-12 and concept_registry both unbuilt, only one vector exists). See `docs/intelligence/intelligence-layer-architecture.md` "Sequencing note (2026-07-05)". Build trigger: Phase 144/145 or the Feature Registry → Concept Registry migration, whichever lands first.

## Ops ideas

- **Backpressure & autoscaling** — stream queue depth monitoring with dynamic concurrency adjustment. Graceful degradation: drop 4h/1d processing under load to protect 1m/5m latency. Applies to whatever's live today, not tier-specific.

## Vision Docs (Reference)
- **AegisAgent — Independent Risk Management** — real-time risk overlay, position sizing, portfolio-level constraints. See `docs/research/vision-01-aegisagent.md`. Note: flagged 2026-07-05 as worth a second read for personal-live-trading risk-management reuse, not as a commercial product — see todo 059.
- **PrimeAgent — Unified Portfolio Management** — portfolio construction, allocation, rebalancing, performance attribution. See `docs/research/vision-03-primeagent.md`.
- **Platform Architecture — Unified Intelligence & Execution Suite** — full product vision, component map, deployment topology. See `docs/research/platform-01-architecture.md`.
- **Intelligence Swarm Manifest** — "The Renaissance Loop" — core swarm architecture principles and agent interaction model. See `docs/research/ai-05-intelligence-swarm-manifest.md`.
- **Jim Simons / Renaissance Principles** — research notes distilled from external sources. Foundational reference. See `docs/research/renaissance-01-simons-principles.md`.
- **Regime-Adaptive Trading** — how regime classification should modulate signal gating, position sizing, and strategy selection. See `docs/research/signal-03-regime-adaptive-trading.md`.
- **Orderflow-Based Setups** — delta divergence, imbalance continuation, absorption detection. Requires orderflow integration. See `docs/research/signal-02-orderflow-setups.md`.

## Research & Design (Active)
- **AI Integration Paths** — LLM provider chain, prompt engineering patterns, cost/latency tradeoffs. See `docs/research/ai-01-integration-paths.md`.
- **BI Analytics Layer — Apache Superset** — SQL analytics against TimescaleDB read-only. Approved design, in progress. See `docs/research/bi-analytics-layer-design.md`.
- **Latency & Persistence Audit Design** — sub-ms signal latency via Kafka-first fire-and-forget. See `docs/research/latency-and-persistence-audit-design.md`.
- **MLAgent — Renaissance-Style Learning Machine** — architecture for the ML scoring/training layer. See `docs/research/ai-02-ml-agent-architecture.md`.
- **ML/AI Technology Palette** — research-backed analysis of ML/AI tech choices (PyTorch, scikit-learn, XGBoost, etc). See `docs/research/ml-ai-palette.md`.
- **ML Classification & Pattern Recognition** — applying ML to pattern recognition, regime classification, signal quality. See `docs/research/ai-08-ml-classification-pattern-recognition.md`.
- **Tech Stack — Decisions & Migration Path** — current and planned technology choices with rationale. See `docs/research/platform-02-tech-stack.md`.
