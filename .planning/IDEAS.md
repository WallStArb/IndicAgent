# Ideas

Rough captures — no structure required, no commitment needed to add here.
When ready to flesh out: create `docs/ideas/<topic>.md` with frontmatter (Status/Priority/Milestone) and link from here.
When ready to build: run `brainstorming` → `docs/plans/` → `/gsd:plan-phase`.

---

- **TradeAgent — Autonomous trading app** — see `docs/ideas/tradeagent-vision.md`. Separate app consuming IndicAgent; multi-tenant; LLM lead + guardrails; broker-agnostic (MCP); trade linkage (groups, options+equities); learning/self-improvement; observability, HITL, security; agent dashboards. Vision/ideas only; not on IndicAgent roadmap.

- **Commercialization — Retail SaaS + Tiered API** — see `docs/ideas/commercialization-retail-saas.md` for full writeup. Free/Pro/API/Premium CIS tiers. Data vendor swap (Databento) is the hard blocker. CIS > 0.70 as premium gate is the moat.

- **Gap-fill service** — detect + backfill gaps in `market_data_ohlcv` caused by service downtime or TWS disconnects. Query for gaps in the 1m series, fetch only the missing windows from IBKR, run Stage 2 replay for those windows. Distinct from the full historical backfill.

- **Delta Divergence Setup** — price makes new high but delta (buy vol - sell vol) diverges → reversal signal. Requires orderflow integration first (reqTickByTickData with bid/ask flagging).

- **Imbalance Continuation Setup** — strong delta imbalance (>70% one-sided) → momentum continuation. Requires orderflow integration first.

- **Absorption Detection** — large volume at a level with no price movement → hidden supply/demand. Requires orderflow.

- **QualAgent** — fundamental/qualitative intelligence extension: macro, corporate (10-K/10-Q, transcripts), sentiment, news, alt data, event arbitrage; agent suite; quantamental bridge. Bus designed to accommodate; build deferred. See `docs/ideas/qualagent-vision.md`.

- **News Sentiment Integration** — fetch headlines per instrument via RSS/API, LLM classifies bullish/bearish/neutral, factor into signal confidence. Dependency: news API subscription.

- **Trade Journal Auto-Documentation** — LLM generates daily trade summaries, identifies learning opportunities from losing trades, tracks performance by setup/regime/timeframe. Uses existing signal_ledger data.

- **Roll premium/discount feature** — spread between front and back month at roll time. IS the contango/backwardation signal. Informative for CL (storage stress) and equity index (dividend/rate expectations).

- **Continuous contract support in live pipeline** — live services use named contracts (correct for trading). At roll, there's a one-time price gap in stored bars. Could store a parallel continuous-adjusted series for indicator computation, while keeping named contract for signal price levels.

- **Cross-asset plugin inputs** — plugins that consume multiple symbols simultaneously (e.g., ES vs VIX correlation, CL vs XLE divergence, SPY vs IWM rotation). Currently all plugins are single-symbol; the DAG and InputSpec would need to support `symbol="*"` or named multi-symbol inputs. Data alignment (temporal join across symbols) is the hard part — bars don't arrive at exactly the same time.

- **I8 intelligence extensions** — Counterfactual Insight Generator ("what needs to be true to validate/invalidate this setup?"), Regime Change Explainer (LLM narrative on HMM transitions + daily brief), Anomaly Triage Assistant (ops LLM that reads metrics/logs and explains pipeline anomalies). All use existing LLM chain. See `docs/ideas/i8-intelligence-extensions.md`.

- **Agent orchestration patterns** — MoA (parallel proposer models + aggregator), adversarial red team (bull/bear debate for high-stakes signals), dynamic leadership (regime-aware leading agent), semantic memory (pgvector insight store), specialist agents: fractal multi-TF pattern matcher, session transition intelligence (Asia→EU→US handoff forecasting), behavioral sentiment capture (emotional state from price/volume without NLP), agent performance auditor. See `docs/ideas/agent-orchestration-patterns.md`.

- **Service resilience patterns** — consumer proxy/circuit breaker, changelog streams for fast state recovery on restart (replaces ~50 min signal generator warmup), enhanced consumer lag + processing duration Prometheus metrics. See `docs/ideas/service-resilience-patterns.md`.

- **Granular Redpanda stream topology** — publish each intelligence tier to its own topic (`intelligence.regime`, `intelligence.patterns`, `intelligence.smc`, `intelligence.composite`) in addition to the monolithic `intelligence` event. Enables selective subscription by future consumers (MLAgent training pipeline, cross-asset regime aggregator, AegisAgent risk overlay) without paying the cost of deserializing the full event. Not worth building until a real consumer justifies it. See `docs/ideas/granular-stream-topology.md`.

- **Parallel DAG execution** — plugins within the same tier that share no dependencies could run concurrently (async tasks). Today execution is sequential within each tier. Benefit is mostly for I3–I5 which are `compute_full()` and the most expensive. Distinct from the per-TF worker refactor (which is about service-level sharding, not intra-stage plugin parallelism).

- **YAML pipeline configuration** — declare the plugin DAG in config rather than Python code. Would enable hot-reload of plugin graphs without service restart, and make pipeline composition visible outside the codebase. Low priority until the plugin set stabilizes.

- **Backpressure & autoscaling** — stream queue depth monitoring with dynamic concurrency adjustment. If `intelligence:ES:1m` stream backlog grows beyond N seconds, automatically scale up processing workers or shed lower-priority timeframes first. Graceful degradation: drop 4h/1d processing under load to protect 1m/5m latency.

## Indicator Service Per-TF Worker Refactor (Option C)
Captured: 2026-02-25

Split indicator service into per-TF workers (1m, 5m, 15m, 1h, 4h, 1d), each with its own:
- Appropriate min_history_bars for that TF
- Consumer group and processing loop
- No cross-TF interference if one TF's stream has issues

Benefits: independent scaling, cleaner failure isolation, TF-appropriate warm-up
Trade-off: 6× service instances vs current monolith

Context: discovered while fixing the 5m/15m+ indicator silent-discard bug (2026-02-25).
Triggered when indicator service's sequential multi-TF loop + min_history_bars=120 caused all
non-1m indicators to silently stall after each restart.
