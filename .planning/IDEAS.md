# Ideas

Rough captures — no structure required, no commitment needed to add here.
When an idea is ready to flesh out, move it to `analysis/`. When ready to build, add to ROADMAP.md Backlog.

---

## Commercialization — Retail SaaS + Tiered API
Captured: 2026-02-28

**Vision:** Retail SaaS platform with three subscription tiers, monetizing the intelligence pipeline we've built.

### Product Tiers
- **Free** — dashboard access, 15-min delayed data, 5 symbols. Acquisition funnel.
- **Pro (~$49-99/mo)** — real-time dashboard, all 23 contracts, full I1-I7 intelligence panel.
- **API (~$149-299/mo)** — SSE stream or webhooks delivering signals + intelligence JSON. For algo traders building on top of our layer.
- **Premium CIS (~$299-499/mo)** — API access gated to CIS > 0.70 signals only (regime-eligible, GARCH/Kalman quality-gated). Fewer signals, much higher quality. **This is the moat.**

### Why CIS as Premium Gate Works
- Self-improving: WeightUpdater runs on real outcome data from signal_ledger
- Verifiable: can show win rate by CIS bucket from signal_ledger outcomes — a marketing asset competitors can't claim
- Triple-filtered: GARCH/Kalman quality gates + HMM regime + CIS threshold
- Difficult to replicate: represents 9 phases of pipeline work

### What's Already Built (surprisingly little to add commercially)
Dashboard UI, SSE stream, REST API, CIS scoring, signal ledger + outcomes, intelligence feature store. Missing: auth, Stripe, tier middleware, webhook delivery.

### Critical Path (sequenced)
1. **Data licensing blocker** — IBKR prohibits redistribution. Switch to commercial vendor (Databento for futures-native CME/CBOT coverage, or Rithmic). TWS daemon → Databento feed adapter. Rest of pipeline is data-source agnostic.
2. **Auth + subscription gating** — Clerk (Next.js native) + Stripe. FastAPI middleware reads tier from JWT, gates endpoints.
3. **Webhook delivery** — async worker POSTs CIS-filtered signals to registered endpoints on fire. Retry logic.
4. **Performance transparency page** — public stats from signal_ledger: "CIS > 0.70: 68% accuracy, 90-day window." Sells premium tier better than any copy.
5. **LLM scaling** — qwen3:8b at 90s/narrative won't scale. Options: GPU (RTX 4090 → ~5s), or cloud API (Claude/OpenAI pay-per-token). Pre-generate on schedule rather than per-request.

### Unit Economics Advantage
Shared-brain model: pay for 23 symbols once regardless of subscriber count. Excellent margin expansion as user base grows.

### Related Todo
See `.planning/todos/pending/2026-02-27-productionize-dashboard-and-api-for-multi-user-access.md` for the technical infrastructure side (SSE fan-out, uvicorn workers, nginx, auth scaffolding).

---

- **Gap-fill service** — detect + backfill gaps in `market_data_ohlcv` caused by service downtime or TWS disconnects. Query for gaps in the 1m series, fetch only the missing windows from IBKR, run Stage 2 replay for those windows. Distinct from the full historical backfill.

- **Delta Divergence Setup** — price makes new high but delta (buy vol - sell vol) diverges → reversal signal. Requires orderflow integration first (reqTickByTickData with bid/ask flagging).

- **Imbalance Continuation Setup** — strong delta imbalance (>70% one-sided) → momentum continuation. Requires orderflow integration first.

- **Absorption Detection** — large volume at a level with no price movement → hidden supply/demand. Requires orderflow.

- **News Sentiment Integration** — fetch headlines per instrument via RSS/API, LLM classifies bullish/bearish/neutral, factor into signal confidence. Dependency: news API subscription.

- **Trade Journal Auto-Documentation** — LLM generates daily trade summaries, identifies learning opportunities from losing trades, tracks performance by setup/regime/timeframe. Uses existing signal_ledger data.

- **Signal quality analytics SQL** — useful queries to monitor signal health:
  ```sql
  -- Win rate by plugin
  SELECT setup_plugin, COUNT(*), AVG(CASE WHEN pnl_r > 0 THEN 1.0 ELSE 0.0 END) as win_rate, AVG(pnl_r) as avg_r
  FROM signal_ledger WHERE pnl_r IS NOT NULL GROUP BY setup_plugin;
  -- Runner-up: what if we'd taken #2?
  SELECT AVG(pnl_r) as avg_r_if_selected FROM signal_ledger WHERE composite_rank = 2 AND pnl_r IS NOT NULL;
  ```

- **Days-to-expiry feature** — compute `(expiry_date - bar_timestamp).days` and store in `intelligence_features`. Behavior near contract expiry is different (liquidity shifts, basis widening); useful ML signal.

- **Roll premium/discount feature** — spread between front and back month at roll time. IS the contango/backwardation signal. Informative for CL (storage stress) and equity index (dividend/rate expectations).

- **Continuous contract support in live pipeline** — live services use named contracts (correct for trading). At roll, there's a one-time price gap in stored bars. Could store a parallel continuous-adjusted series for indicator computation, while keeping named contract for signal price levels.

- **MomentumAcceleration plugin (second-derivative analysis)** — new I1 plugin that computes the second derivative of RSI, MACD line, and ROC. Outputs `rsi_accel`, `macd_accel`, `roc_accel`, plus an `inflection_flag` when any crosses zero. Detects momentum exhaustion and trend changes *before* they show in price. RSI decelerating toward 50 is earlier signal than RSI crossing 50. Inflection points map directly onto I5 pattern exhaustion detection. See `docs/plans/2026-02-25-momentum-acceleration-analysis.md`.

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
