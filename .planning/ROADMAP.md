# Roadmap: IndicAgent

## Milestones

- ✅ **v1.0 MVP** — Phases 0-9 (shipped 2026-02-28)
- 📋 **v1.1** — TBD (`/gsd:new-milestone`)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 0-9) — SHIPPED 2026-02-28</summary>

- [x] Phase 0: GARCH/Kalman Quality Gates (3/3 plans) — completed 2026-02-22
- [x] Phase 1: Typed Event Schema (3/3 plans) — completed 2026-02-23
- [x] Phase 2: Feature Store (3/3 plans) — completed 2026-02-23
- [x] Phase 3: Historical Data (3/3 plans) — completed 2026-02-24
- [x] Phase 4: Query API (3/3 plans) — completed 2026-02-24
- [x] Phase 5: Live Pipeline (3/3 plans) — completed 2026-02-25
- [x] Phase 6: Dashboard Connected (4/4 plans) — completed 2026-02-28
- [x] Phase 7: Composite Intelligence Score (4/4 plans) — completed 2026-02-28
- [x] Phase 8: Integration Fix & Cleanup (3/3 plans) — completed 2026-02-28
- [x] Phase 9: Milestone Verification (3/3 plans) — completed 2026-02-28

Full details: `.planning/milestones/v1.0-ROADMAP.md`

</details>

## Progress

| Phase | Milestone | Plans | Status | Completed |
|-------|-----------|-------|--------|-----------|
| 0. GARCH/Kalman Quality Gates | v1.0 | 3/3 | Complete | 2026-02-22 |
| 1. Typed Event Schema | v1.0 | 3/3 | Complete | 2026-02-23 |
| 2. Feature Store | v1.0 | 3/3 | Complete | 2026-02-23 |
| 3. Historical Data | v1.0 | 3/3 | Complete | 2026-02-24 |
| 4. Query API | v1.0 | 3/3 | Complete | 2026-02-24 |
| 5. Live Pipeline | v1.0 | 3/3 | Complete | 2026-02-25 |
| 6. Dashboard Connected | v1.0 | 4/4 | Complete | 2026-02-28 |
| 7. Composite Intelligence Score (CIS) | v1.0 | 4/4 | Complete | 2026-02-28 |
| 8. Integration Fix & Cleanup | v1.0 | 3/3 | Complete | 2026-02-28 |
| 9. Milestone Verification | v1.0 | 3/3 | Complete | 2026-02-28 |

## Backlog

Items decided but not yet scheduled. Pull into a milestone when ready.

| Item | Notes | Analysis |
|------|-------|---------|
| Dashboard Complete | Timeframe matrix wired to live per-TF signal data; signal history view; final audit across all symbol profiles. | — |
| Add i7/i8 columns to intelligence_features | Add `i7 JSONB` (setups + scores) and `i8 JSONB` (narrative + metadata) to intelligence_features. Enrichment stream pattern. | `analysis/2026-02-24-feature-store-completeness.md` |
| ML Scoring Model | XGBoost/LightGBM on intelligence_features + signal_ledger outcomes. Needs ~90 days signal history. | — |
| Auth and External Access | JWT + API key via single Depends(verify_auth); Cloudflare Tunnel; authenticated SSE. | — |
| Gap-fill service | Detect + backfill gaps in market_data_ohlcv from TWS downtime. | — |
| Days-to-expiry feature | `(expiry_date - bar_ts).days` → intelligence_features. Roll proximity signal. | — |
| Roll premium/discount feature | Front/back month spread at roll = contango/backwardation signal. | — |
| Gap Analysis Setup (I7) | Opening gap fade/continuation. Best for ES/NQ at 9:30 ET. | — |
| Candlestick Pattern Setup (I7) | Doji/hammer/engulfing + confluence. | — |
| Session Extremes Setup (I7) | Asian session high/low fade during London/NY. | — |
| Orderflow Integration | reqTickByTickData; buy/sell delta metrics; delta divergence plugins. | — |
| Portfolio Management | Correlation matrix; sector exposure limits; symbol rotation. | — |
| Robinhood-Style Scaling | Consumer Proxy pattern; Changelog Streams for state recovery. | `analysis/2026-02-12-robinhood-scaling-patterns.md` |
