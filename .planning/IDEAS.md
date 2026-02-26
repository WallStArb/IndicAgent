# Ideas

Rough captures — no structure required, no commitment needed to add here.
When an idea is ready to flesh out, move it to `analysis/`. When ready to build, add to ROADMAP.md Backlog.

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
