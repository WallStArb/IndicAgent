# Requirements: IndicAgent

**Defined:** 2026-03-01

**Current Milestone:** v1.1 Code Quality Sprint
**Core Value:** Production-grade code with zero blocking defects

---

## v1.1 Requirements

### Category: Code Quality

- [ ] **QUAL-01**: Resolve all ruff E/F/W/PLR errors (206 → 0)
  - Fix 5 line-too-long issues (E501)
  - Fix 2 ambiguous variable names (E741)
  - Resolve code duplication patterns (30+ PLR2004 magic numbers)
  - Fix too-many-branches issues (PLR0912)
  - Fix too-many-statements issues (PLR0915)
  - Fix elif-else-if anti-patterns (PLR5501)
  - Ensure all imports are at module level, not nested

- [ ] **QUAL-02**: Fix O(N³) complexity in head_shoulders.py
  - Refactor triple-nested loops to single-pass or two-pass algorithm
  - Target: Reduce from O(N³) to O(N²) or better
  - File: src/intelligence/patterns/head_shoulders.py lines 66-94, 121-139

- [ ] **QUAL-03**: Fix O(N²) complexity issues across 8 pattern files
  - Pre-filter candidates before nested iteration
  - Use numpy vectorization where applicable
  - Files: rsi_divergence, volume_divergence, double_top_bottom, fair_value_gap,
           liquidity_pools, supply_demand_zones, liquidity_sweeps, bos_choch
  - Target: Reduce per-bar iteration count

- [ ] **QUAL-04**: Fix plugin state isolation correctness bug
  - Implement state keyed by (symbol, timeframe) instead of shared singleton
  - Option A: Refactor compute_full signature to accept symbol/timeframe params
  - Option C (short-term): Add guard preventing compute_next until isolation fixed
  - File: All 62 plugins in src/intelligence/{indicators,context,patterns,smart_money,trading}
  - Prevents data corruption when multiple symbols/timeframes processed sequentially

- [ ] **QUAL-05**: Add xgroup_setid recovery to feature_writer_service.py
  - Follow pattern used in other services (try/except with xgroup_setid("$"))
  - Ensures consumer starts at "$" (latest) on restart, not old position
  - File: src/services/feature_writer_service.py around line 274

- [ ] **QUAL-06**: Fix unconditional signal rewind in signal_generator_service.py
  - Only rewind warmup_bars when group_freshly_created flag is true
  - Current code rewinds unconditionally on every startup
  - File: src/services/signal_generator_service.py lines 351-366

- [ ] **QUAL-07**: Reduce sequential warmup reads at startup
  - Batch or parallelize Redis xrevrange calls across 92 streams (24 contracts × 4 timeframes)
  - Current: 100 calls per stream sequentially = 9,200+ round trips
  - Target: Reduce startup time from ~10s to ~2s
  - Files: src/services/indicator_service.py, src/services/market_analysis_service.py

### Category: Maintainability

- [ ] **MAINT-01**: Extract shared fval() utility to src/intelligence/utils.py
  - Replace 2+ duplicate implementations in cis_scorer.py and trade_framer.py
  - Pattern: safe float extraction from features dict with default

- [ ] **MAINT-02**: Extract shared clamp() utility to src/intelligence/utils.py
  - Replace 20+ instances of max(-1.0, min(1.0, value) pattern
  - Pattern: value constrained to [min_val, max_val] range

- [ ] **MAINT-03**: Extract setup_consumer_group() to streams_mixins/_consuming.py
  - Replace 5 services' duplicate consumer group initialization code
  - Pattern: xgroup_create with xgroup_setid("$") fallback

- [ ] **MAINT-04**: Extract read_multi_stream() to streams_mixins/_consuming.py
  - Replace 5 services' duplicate multi-stream xreadgroup pattern
  - Pattern: single xreadgroup call with dict of {stream: ">"}

- [ ] **MAINT-05**: Extract health_monitor_loop() to base service class
  - Replace 6 services' identical health monitoring loops
  - Create BaseService template in src/core/service_base.py

- [ ] **MAINT-06**: Define sector enum for symbol-config.ts
  - Replace string union "equity_index" | "energy" | "metals" | ...
  - Type-safe, enables validation, prevents typos

### Category: Configuration

- [ ] **CONF-01**: Add active symbols to indicator_service.json
  - Current symbols list is empty: []
  - Service runs but processes nothing — misleading state
  - Add at least ES, NQ, RTY for functional deployment

- [ ] **CONF-02**: Generate contract codes dynamically instead of hardcoding
  - Replace 17 hardcoded H6/J6/M6 codes (ESH6, NQH6, etc.)
  - Will break March 2026 when H6 contracts expire
  - Use IBKR API or derive from symbol + expiry month
  - File: dashboard/src/lib/symbol-config.ts

- [ ] **CONF-03**: Resolve duplicate warmup between services
  - indicator_service and market_analysis_service both warmup from Redis independently
  - Share warmup cache or deduplicate to reduce startup time
  - Target: Eliminate double warmup overhead

### Category: Performance

- [ ] **PERF-01**: Parallelize CPU-bound plugin execution in market_analysis_service.py
  - I3/I4/I5 plugins are independent per tier
  - Use asyncio.gather() or thread pool instead of sequential loop
  - GARCH and Kalman filter are computationally heavy

- [ ] **PERF-02**: Cache DataFrame reconstruction in indicator_service.py
  - _get_df() creates DataFrame on every bar when cache None
  - Cache or reuse DataFrame across bars
  - Target: Reduce 230+ field accesses per bar

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| Real-time SLA targets | HFT system, not applicable |
| Portfolio management | Out of scope for intelligence layer |
| Multi-platform build | No other consumers yet |
| Auth layer | No external consumers, adds complexity |

---

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| QUAL-01 | Phase 01 | Complete |
| QUAL-02 | Phase 01 | Complete |
| QUAL-03 | Phase 01 | Partial (3 of 8 files) |
| QUAL-04 | Phase 01 | Deferred (theoretical) |
| QUAL-05 | Phase 01 | Complete (already fixed) |
| QUAL-06 | Phase 01 | Complete (already fixed) |
| QUAL-07 | Phase 01 | Complete |
| MAINT-01 | Phase 01 | Deferred (pattern not found) |
| MAINT-02 | Phase 01 | Complete |
| MAINT-03 | Phase 01 | Partial (utility added but not used by services) |
| MAINT-04 | Phase 01 | Partial (utility added but not used by services) |
| MAINT-05 | Phase 01 | Not started |
| MAINT-06 | Phase 01 | Complete |
| CONF-01 | Phase 01 | Complete |
| CONF-02 | Phase 01 | Complete |
| CONF-03 | Phase 01 | Not started |
| PERF-01 | Phase 01 | Not started |
| PERF-02 | Phase 01 | Not started |

---

## Coverage

- v1.0 requirements: 22 total
- v1.1 requirements: 20 total

| Category | v1.0 | v1.1 |
|----------|--------|--------|
| Code Quality | 0 | 20 |
| Configuration | 0 | 3 |
| Maintainability | 0 | 6 |
| Performance | 0 | 2 |

**v1.1 Coverage: 20/20 requirements mapped ✓**

---

**Last updated:** 2026-03-01
