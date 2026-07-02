# Ideas
Rough captures — no structure required, no commitment needed to add here.
When ready to flesh out: create `docs/ideas/<topic>.md` and link from here.
When actionable (clear problem + solution): create `.planning/todos/pending/<n>-<topic>.md`.
When ready to build: assign to a milestone in `ROADMAP.md` → `/gsd-plan-phase`.
Full planning system: `.planning/PLANNING-SYSTEM.md`.

---
- **TradeAgent — Autonomous trading app** — see `docs/ideas/tradeagent-vision.md`. Separate app consuming IndicAgent; multi-tenant; LLM lead + guardrails; broker-agnostic (MCP); trade linkage (groups, options+equities); learning/self-improvement; observability, HITL, security; agent dashboards. Vision/ideas only; not on IndicAgent roadmap.
- **Commercialization — Retail SaaS + Tiered API** — see `docs/ideas/commercialization-retail-saas.md` for full writeup. Free/Pro/API/Premium CIS tiers. Data vendor swap (Databento) is hard blocker. CIS > 0.70 as premium gate is moot.
- **Delta Divergence Setup** — price makes new high but delta (buy vol - sell vol) diverges → reversal signal. Requires orderflow integration first (reqTickByTickData with bid/ask flagging).
- **Imbalance Continuation Setup** — strong delta imbalance (>70% one-sided) → momentum continuation. Requires orderflow integration first.
- **Absorption Detection** — large volume at a level with no price movement → hidden supply/demand. Requires orderflow.
- **QualAgent** — fundamental/qualitative intelligence extension: macro, corporate (10-K/10-Q), transcripts, sentiment, news, alt data, event arbitrage; agent suite; quantamental bridge. Bus designed to accommodate; build deferred. See `docs/ideas/qualagent-vision.md`.
- **News Sentiment Integration** — fetch headlines per instrument via RSS/API, LLM classifies bullish/bearish/neutral, factor into signal confidence. Dependency: news API subscription.
- **Roll premium/discount feature** — spread between front and back month at roll time. IS: contango/backwardation signal. Informative for CL (storage stress) and equity index (dividend/rate expectations).
- **Continuous contract support in live pipeline** — live services use named contracts (correct for trading). At roll, there's a one-time price gap in stored bars. Could store a parallel continuous-adjusted series for indicator computation, while keeping named contract for signal price levels.
- **Cross-asset plugin inputs** — plugins that consume multiple symbols simultaneously (e.g., ES vs VIX correlation, CL vs XLE divergence, SPY vs IWM rotation). Currently all plugins are single-symbol; a DAG and InputSpec would need to support `symbol="*"` or named multi-symbol inputs. Data alignment (temporal join across symbols) is the hard part — bars don't arrive at exactly the same time.
- **I8 intelligence extensions** — Counterfactual Insight Generator, Regime Change Explainer, Anomaly Triage Assistant. All use existing LLM chain. See `docs/ideas/i8-intelligence-extensions.md`.
- **Agent orchestration patterns** — MoA, adversarial red team, dynamic leadership, semantic memory, specialist agents. See `docs/ideas/agent-orchestration-patterns.md`.
- **Service resilience patterns** — consumer proxy/circuit breaker, changelog streams, enhanced consumer lag metrics. See `docs/ideas/service-resilience-patterns.md`.
- **Granular Redpanda stream topology** — per-tier topics for selective subscription. Not worth building until a real consumer justifies it. See `docs/ideas/granular-stream-topology.md`.
- **Parallel DAG execution** — plugins within same tier that share no dependencies could run concurrently. Today execution is sequential within each tier. Benefit is mostly for I3-I5 which are `compute_full()` and most expensive.
- **YAML pipeline configuration** — declare plugin DAG in config rather than Python code. Low priority until plugin set stabilizes.
- **Backpressure & autoscaling** — stream queue depth monitoring with dynamic concurrency adjustment. Graceful degradation: drop 4h/1d processing under load to protect 1m/5m latency.
- **Plugin Performance Scoring System (Alpha Phase)** — extend CIS scorer to A/B test framework; evidence-based alpha selection.
- **HMM Multi-TF + Training Pipeline** — per-TF plugin instances with TF-appropriate lookbacks; Baum-Welch training on `intelligence_features`. v2.3 candidate. See `docs/ideas/hmm-multi-tf-and-training.md`.
- **Regime Transition Early Detection** — `regime_entropy` + `hmm_regime_velocity` to detect Phase B/D transition windows. See `docs/ideas/regime-transition-early-detection.md`.
- **Roll Detection Architecture Improvements** — dedicated `roll_events` table, signed `roll_gap` convention, `FUTURES_SPECS` per-symbol month cycles.
- **Qualitative Intelligence Layer** — non-price data integration (earnings, macro events, news sentiment). See `docs/ideas/qualitative-intelligence-layer.md` and implementation plan `docs/plans/2026-05-02-unified-intelligence-design.md`. Tracked as todos 012-016.
- **Unified Intelligence Fabric** — transition from linear quant-only TA engine to multi-domain intelligence fabric. See `docs/plans/2026-05-02-unified-intelligence-design.md`. Tracked as todo 017.
- **DerivAgent — Derivatives Intelligence** — volatility surface, GEX, VANNA/CHARM, VRP. Full options intelligence vision. See `docs/ideas/derivagent-vision.md`.
- **Macro & Cross-Asset Intelligence** — wire existing ftq_score/yield_curve_slope/corr_z into I4Context and intelligence_features; add thin I4 plugins; regime-segment setup_performance; extend with stock-bond correlation + VX term structure services. See `docs/ideas/macro-cross-asset-intelligence-improvements.md`. Tracked as todo 018.
- **Renaissance I7/I8 Refinement** — 105 ideas across 48 sections: alpha decay, hidden alpha, regime intelligence, adaptive learning, information theory, neural intelligence. See `docs/ideas/renaissance-i7-i8-refinement.md`.
- **Future Indicators Backlog** — Tracks B/C: I3 structure enhancements (SR zones, swing magnitude, trend structure), momentum composite (EMA stack score, golden/death cross, ADX qualification). See `docs/ideas/future-indicators-backlog.md`.
- **SR / Zone Engine Improvements** — Post-Phase-116 backlog: regression-fit default_strength weights (todo 019, gate n>=500), zone width output, per-TF source priors, multi-session levels, touch/test memory, adaptive cluster radius, proximity-weighted score, source diversity min, stale level decay. See `docs/ideas/sr-zone-engine-improvements.md`.
- **Timeframe Cascade Strategy** — multi-TF trade management: micro entry (1m) → momentum hold (5m) → trend capture (15m/30m) → swing hold (1h/4h) → position hold (1d). See `docs/ideas/timeframe-cascade-strategy.md`.
- **Momentum Acceleration (Second Derivative)** — f''(x) inflection points as earliest reversal signals; RSI/MACD/ROC acceleration. Core built in Phase 08, deeper ideas remain. See `docs/ideas/momentum-acceleration-second-derivative.md`.
- **Second Derivative Indicators — Current & Future** — expansion ideas beyond Phase 08 baseline. See `docs/ideas/second-derivative-indicators-current-and-future.md`.
- **Intelligence Confluence Patterns** — Renaissance-aligned confluence framework concepts beyond Phase 46 baseline. See `docs/ideas/intelligence-confluence-patterns.md`.
- **Renaissance Framing** — foundational philosophy from Simons/Medallion approach. See `docs/ideas/renaissance-framing.md`.

- **Architectural Weakness Assessment** — top 7 weak links: pipeline god class (1820 lines), settings god object, 64-field ledger tuple, dead AI foundations (LineageRecorder/graduation), silent queue drops, bare excepts, unprotected global state. See `docs/ideas/architectural-weakness-assessment.md`.
- **Cross-Group Lead-Lag IC** — does one `regime_group`'s state predict another's forward returns (e.g. rates→precious metals, industrial metals→bonds)? Reuses `ic_engine`, new join pattern not new infra. Gated on Phase 151 (`regime_group`). See `docs/ideas/cross-group-lead-lag-ic.md`.

## Vision Docs (Reference)
- **AegisAgent — Independent Risk Management** — real-time risk overlay, position sizing, portfolio-level constraints. See `docs/ideas/aegisagent-vision.md`.
- **PrimeAgent — Unified Portfolio Management** — portfolio construction, allocation, rebalancing, performance attribution. See `docs/ideas/primeagent-vision.md`.
- **Platform Architecture — Unified Intelligence & Execution Suite** — full product vision, component map, deployment topology. See `docs/ideas/platform-architecture.md`.
- **Intelligence Swarm Manifest** — "The Renaissance Loop" — core swarm architecture principles and agent interaction model. See `docs/ideas/intelligence-swarm-manifest.md`.
- **Jim Simons / Renaissance Principles** — research notes distilled from external sources. Foundational reference. See `docs/ideas/jim-simons-renaissance-principles.md`.
- **Regime-Adaptive Trading** — how regime classification should modulate signal gating, position sizing, and strategy selection. See `docs/ideas/regime-adaptive-trading.md`.
- **Orderflow-Based Setups** — delta divergence, imbalance continuation, absorption detection. Requires orderflow integration. See `docs/ideas/orderflow-based-setups.md`.

## Research & Design (Active)
- **AI Integration Paths** — LLM provider chain, prompt engineering patterns, cost/latency tradeoffs. See `docs/ideas/ai-integration-paths.md`.
- **BI Analytics Layer — Apache Superset** — SQL analytics against TimescaleDB read-only. Approved design, in progress. See `docs/ideas/bi-analytics-layer-design.md`.
- **Intelligence Stack Latency Reduction** — hot/cold path separation, plugin optimization, throughput targets. See `docs/ideas/intelligence-stack-latency-reduction.md`.
- **Kubernetes Evaluation** — pros/cons analysis for IndicAgent deployment. Current verdict: systemd is correct for now. See `docs/ideas/kubernetes-evaluation.md`.
- **Latency & Persistence Audit Design** — sub-ms signal latency via Kafka-first fire-and-forget. See `docs/ideas/latency-and-persistence-audit-design.md`.
- **MLAgent — Renaissance-Style Learning Machine** — architecture for the ML scoring/training layer. See `docs/ideas/ml-agent-architecture.md`.
- **ML/AI Technology Palette** — research-backed analysis of ML/AI tech choices (PyTorch, scikit-learn, XGBoost, etc). See `docs/ideas/ml-ai-palette.md`.
- **ML Classification & Pattern Recognition** — applying ML to pattern recognition, regime classification, signal quality. See `docs/ideas/ml-classification-pattern-recognition.md`.
- **Tech Stack — Decisions & Migration Path** — current and planned technology choices with rationale. See `docs/ideas/tech-stack.md`.
