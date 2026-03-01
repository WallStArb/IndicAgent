# Roadmap: IndicAgent

## Milestones

- ✅ **v1.0 MVP** — Phases 0-9 (shipped 2026-02-28)
- 📋 **v1.1 Code Quality Sprint** — Phases 10-14 (in progress)

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
<summary>📋 v1.1 Code Quality Sprint (Phases 10-14) — IN PROGRESS</summary>

- [ ] **Phase 10: Lint & Code Quality Cleanup** — Resolve all ruff errors (206 → 0) and fix algorithmic complexity issues
- [ ] **Phase 11: Critical Bug Fixes** — Fix plugin state isolation, consumer group recovery, and signal rewind bugs
- [ ] **Phase 12: Service Layer Refactoring** — Extract shared utilities and reduce code duplication across services
- [ ] **Phase 13: Configuration Improvements** — Fix service config issues and add type safety to dashboard
- [ ] **Phase 14: Performance Optimization** — Reduce startup time and optimize CPU-bound plugin execution

</details>

## Phase Details

### Phase 10: Lint & Code Quality Cleanup

**Goal:** Codebase passes all linting checks and algorithmic complexity is within healthy bounds

**Depends on:** Nothing (first phase)

**Requirements:** QUAL-01, QUAL-02, QUAL-03

**Success Criteria** (what must be TRUE):
1. Running `ruff check .` returns zero errors (206 → 0 fixed)
2. head_shoulders.py no longer contains O(N³) triple-nested loops
3. All 8 pattern files with O(N²) complexity have been refactored to pre-filter candidates before nested iteration
4. Test suite still passes after all refactorings (796 tests)

**Plans:** `.planning/milestones/v1.1-phases/10-lint-code-quality/PLAN.md`

---

### Phase 11: Critical Bug Fixes

**Goal:** All correctness bugs affecting data integrity and service behavior are resolved

**Depends on:** Phase 10

**Requirements:** QUAL-04, QUAL-05, QUAL-06

**Success Criteria** (what must be TRUE):
1. Plugin state is correctly isolated per (symbol, timeframe) — no data corruption when processing multiple symbols/timeframes sequentially
2. feature_writer_service correctly starts at "$" on restart (not old position) due to xgroup_setid recovery
3. signal_generator_service only rewinds warmup_bars when group_freshly_created is true (not on every startup)
4. All services handle consumer group creation errors gracefully with xgroup_setid fallback

**Plans:** TBD

---

### Phase 12: Service Layer Refactoring

**Goal:** Shared patterns extracted to utilities, reducing code duplication across 5-6 services

**Depends on:** Phase 11

**Requirements:** MAINT-01, MAINT-02, MAINT-03, MAINT-04, MAINT-05

**Success Criteria** (what must be TRUE):
1. fval() and clamp() utilities in src/intelligence/utils.py replace all duplicate implementations (20+ occurrences reduced to 1 each)
2. setup_consumer_group() in streams_mixins/_consuming.py replaces 5 services' duplicate consumer group initialization
3. read_multi_stream() in streams_mixins/_consuming.py replaces 5 services' duplicate xreadgroup patterns
4. health_monitor_loop() in base service class replaces 6 services' identical health monitoring loops
5. All services import shared utilities instead of duplicating code

**Plans:** TBD

---

### Phase 13: Configuration Improvements

**Goal:** Service configuration is correct and dashboard type safety is improved

**Depends on:** Phase 12

**Requirements:** CONF-01, CONF-02, CONF-03, MAINT-06

**Success Criteria** (what must be TRUE):
1. indicator_service.json contains active symbols (ES, NQ, RTY) — service processes data instead of running empty
2. Contract codes in symbol-config.ts are generated dynamically instead of hardcoded (won't break in March 2026)
3. Startup warmup is deduplicated — indicator_service and market_analysis_service share cache or eliminate double warmup
4. Sector enum in symbol-config.ts replaces string union (type-safe, validated)

**Plans:** TBD

---

### Phase 14: Performance Optimization

**Goal:** Service startup time and CPU-bound plugin execution are optimized for production performance

**Depends on:** Phase 13

**Requirements:** QUAL-07, PERF-01, PERF-02

**Success Criteria** (what must be TRUE):
1. Service startup time reduced from ~10s to ~2s via batched/parallelized Redis warmup reads
2. I3/I4/I5 plugins in market_analysis_service execute in parallel via asyncio.gather() or thread pool
3. indicator_service caches DataFrame reconstruction instead of creating new DataFrame on every bar
4. All performance improvements verified via metrics monitoring (no latency regressions)

**Plans:** TBD

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
| 10. Lint & Code Quality Cleanup | v1.1 | 0/3 | Not started | - |
| 11. Critical Bug Fixes | v1.1 | 0/3 | Not started | - |
| 12. Service Layer Refactoring | v1.1 | 0/5 | Not started | - |
| 13. Configuration Improvements | v1.1 | 0/4 | Not started | - |
| 14. Performance Optimization | v1.1 | 0/3 | Not started | - |

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
