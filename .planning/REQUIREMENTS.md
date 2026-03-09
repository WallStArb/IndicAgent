# Requirements: IndicAgent

**Defined:** 2026-03-08
**Core Value:** Every intelligence output flows through one canonical typed bus that both internal and external consumers can trust.

## v1.5 Requirements

Requirements for production hardening — financial safety, concurrency protection, API resilience, and efficiency. Each maps to roadmap phases.

### Financial Math Safety (FIN)

**P0 — Epsilon tolerance prevents floating-point comparison edge cases.**

- [x] **FIN-01**: System uses epsilon tolerance (1e-9) for all floating-point comparisons in trade_framer.py
- [x] **FIN-02**: CIS scorer uses epsilon tolerance for slope/MACD/ROC direction comparisons
- [x] **FIN-03**: All magic numbers documented as named constants with inline comments
- [x] **FIN-04**: ATR multipliers documented (0.25, 0.30, 0.20, 0.25, 0.50, 2.0, 0.001)
- [x] **FIN-05**: Regime thresholds documented (0.35, 3, 0.1)
- [x] **FIN-06**: RSI zero-loss guard behavior documented in rsi.py
- [x] **FIN-07**: Characterization test for RSI zero-loss behavior (returns 100.0)
- [x] **FIN-08**: Characterization test for trade_framer zero ATR emergency fallback

### API Resilience & Concurrency (API)

**P0-P1 — External API timeouts and shared state protection.**

- [ ] **API-01**: Settings class exposes ibkr_timeout_sec (default 20.0s)
- [ ] **API-02**: Settings class exposes llm_timeout_sec (default 60.0s)
- [x] **API-03**: IBKR provider uses configurable timeout from Settings
- [x] **API-04**: All LLM providers use configurable timeout from Settings
- [x] **API-05**: market_analysis_service has per-key asyncio.Lock() for _plugin_states access
- [x] **API-06**: indicator_service has per-key asyncio.Lock() for _i1_plugin_states access
- [x] **API-07**: ai_narrative_service has asyncio.Lock() for _latest_signals access
- [x] **API-08**: Characterization test for lock acquisition and release
- [x] **API-09**: IBKR provider uses PluginCircuitBreaker for connection failures

### Circuit Breakers (CB)

**P2 — Circuit breaker integration for external dependencies.**

- [x] **CB-01**: retry_utils.py created with exponential_backoff_with_jitter()
- [x] **CB-02**: retry_with_backoff() async wrapper with configurable max_attempts
- [x] **CB-03**: All LLM providers use PluginCircuitBreaker for generate() calls
- [x] **CB-04**: Circuit breaker metrics exposed on Prometheus endpoint

### Efficiency Optimizations (EFF)

**P3-P4 — Performance improvements for high-throughput services.**

- [ ] **EFF-01**: indicator_service tracks buffer length, only invalidates DataFrame cache when capacity exceeded
- [x] **EFF-02**: market_analysis_service tracks buffer length, only invalidates DataFrame cache when capacity exceeded
- [x] **EFF-03**: CIS scorer uses numpy vectorization for bucket score computation
- [x] **EFF-04**: Plugin call metrics use modulo sampling (record every N calls, not every call)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

| Feature | Reason |
|---------|--------|
| Real-time latency SLAs | Not a HFT system; seconds target is sufficient |
| Full external auth layer | No external consumers yet |

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Order execution / trade management | Intelligence platform only — no execution engine |
| Portfolio management / position sizing | Out of scope for intelligence layer |
| Full multi-platform build (fundamentals, sentiment, news) | Future milestone — bus designed to accommodate it |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FIN-01 | Phase 18 | Complete |
| FIN-02 | Phase 18 | Complete |
| FIN-03 | Phase 18 | Complete |
| FIN-04 | Phase 18 | Complete |
| FIN-05 | Phase 18 | Complete |
| FIN-06 | Phase 18 | Complete |
| FIN-07 | Phase 19 | Complete |
| FIN-08 | Phase 19 | Complete |
| API-01 | Phase 18 | Pending |
| API-02 | Phase 18 | Pending |
| API-03 | Phase 18 | Complete |
| API-04 | Phase 18 | Complete |
| API-05 | Phase 18 | Complete |
| API-06 | Phase 18 | Complete |
| API-07 | Phase 18 | Complete |
| API-08 | Phase 19 | Complete |
| API-09 | Phase 20 | Complete |
| CB-01 | Phase 20 | Complete |
| CB-02 | Phase 20 | Complete |
| CB-03 | Phase 20 | Complete |
| CB-04 | Phase 20 | Complete |
| EFF-01 | Phase 21 | Pending |
| EFF-02 | Phase 21 | Complete |
| EFF-03 | Phase 21 | Complete |
| EFF-04 | Phase 21 | Complete |

**Coverage:**
- v1.5 requirements: 28 total
- Mapped to phases: 28
- Unmapped: 0

---
*Requirements defined: 2026-03-08*
*Last updated: 2026-03-08 after roadmap creation*
