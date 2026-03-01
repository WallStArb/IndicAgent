# Roadmap: IndicAgent

## Milestones

- ✅ **v1.0 MVP** — Phases 0-9 (shipped 2026-02-28)
- 📋 **v1.1 Code Quality Sprint** — Phase 01 (in progress: 6/13 tasks complete)

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

<details>
<summary>📋 v1.1 Code Quality Sprint — IN PROGRESS</summary>

- [ ] **Phase 01: Code Quality Sprint** — 6/13 tasks complete, ruff errors 206 → 76

</details>

## Phase Details

### Phase 01: Code Quality Sprint

**Goal:** Fix all code quality issues identified by ruff, complexity analysis, and manual review

**Plan location:** `.planning/milestones/v1.0-phases/01-code-quality-sprint/01-PLAN.md`

**Status:** 6/13 tasks complete (Wave 2 completed 2026-03-01)

**Tasks completed:**
- ✅ Task 01: Resolve ruff E/F/W/PLR errors (206 → 0 in `src/intelligence/`)
- ✅ Task 03: Fix O(N²) complexity in 3 of 8 pattern files
- ✅ Task 07: Parallelize warmup reads at service startup (78% time reduction)
- ✅ Task 09: Replace clamp() utility (27 instances across 6 files)
- ✅ Task 12: Add active symbols to indicator_service.json
- ✅ Task 13: Generate contract codes dynamically (dashboard)

**Tasks deferred (require architectural change):**
- ⏸️ Task 10/11: Extract shared utilities (added to ConsumingMixin but services don't inherit)

**Tasks already complete (verified during execution):**
- ✅ Task 02: head_shoulders O(N³) → O(N) (bounded neighbor window)
- ✅ Task 04: Plugin state isolation bug (theoretical only, `compute_next()` not called)
- ✅ Task 05: xgroup_setid recovery (already implemented)
- ✅ Task 06: Signal rewind bug (fixed with `group_freshly_created` flag)
- ✅ Task 08: fval() utility (pattern not found in codebase)

**Current ruff status:** 76 errors remaining (down from 206)

**Performance improvements:**
- Service startup: 9.2s → 1-2s (78% reduction)
- Pattern detection: 3 files O(N²) → O(N)
- Code readability: 27 clamp() replacements with explicit utility

---

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
| 01. Code Quality Sprint | v1.1 | 6/13 | In Progress | 2026-03-01 |

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
