# Ideas

Rough captures — no structure required, no commitment needed to add here.
When an idea is ready to flesh out, move it to `analysis/`. When ready to build, add to ROADMAP.md Backlog.

---

- **Gap-fill service** — detect + backfill gaps in `market_data_ohlcv` caused by service downtime or TWS disconnects. Query for gaps in the 1m series, fetch only the missing windows from IBKR, run Stage 2 replay for those windows. Distinct from the full historical backfill.

- **Days-to-expiry feature** — compute `(expiry_date - bar_timestamp).days` and store in `intelligence_features`. Behavior near contract expiry is different (liquidity shifts, basis widening); useful ML signal.

- **Roll premium/discount feature** — spread between front and back month at roll time. IS the contango/backwardation signal. Informative for CL (storage stress) and equity index (dividend/rate expectations).

- **Continuous contract support in live pipeline** — live services use named contracts (correct for trading). At roll, there's a one-time price gap in stored bars. Could store a parallel continuous-adjusted series for indicator computation, while keeping named contract for signal price levels.
