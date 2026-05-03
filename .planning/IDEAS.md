# Ideas
Rough captures — no structure required, no commitment needed to add here.
When ready to flesh out: create `docs/ideas/<topic>.md` with frontmatter (Status/Priority/Milestone) and link from here.
When ready to build: run `brainstorming` → `docs/plans/` → `/gsd:plan-phase`.

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
