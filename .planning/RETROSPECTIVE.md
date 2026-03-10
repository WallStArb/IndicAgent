# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

---

## Milestone: v1.4 — Quant Foundation

**Shipped:** 2026-03-07
**Phases:** 6 (12-17) | **Plans:** 29 | **Timeline:** 4 days (2026-03-04 → 2026-03-07)

### What Was Built

- Regime-aware I7 gating: all 17 plugins enforce hmm_regime type, prob≥0.60 conviction gate, and duration≥5 stability gate before firing
- Shadow signals: regime-suppressed setups tracked in signal_ledger with full counterfactual MAE/MFE/8-class outcome for empirical gate tuning
- Complete ML training dataset: intelligence_features now carries i7 JSONB (all_ranked per bar), i8 JSONB (narrative metadata), days_to_expiry — no missing samples
- Adaptive aggregator: setup_performance table (rolling 30-day win rate, avg_pnl_r, Sharpe) feeds perf_multiplier as primary sort key; best Sharpe setups rank first
- validate_alpha.py statistical promotion gate (Pearson r>0, p<0.05, N≥30 + ADF stationarity); bootstrap policy for correct implementations without live data
- 4 new alpha sources live: DerivativeOscillatorPlugin (I2), 10 Candlestick Tier 1 patterns (I5/I7), MACD histogram acceleration (I2), ACOscillatorPlugin (I1)
- Full LLM audit log: llm_calls TimescaleDB hypertable — every call (success, failure, counterfactual) captured with outcome back-fill from signal lifecycle
- Adaptive LLM model routing: llm_model_scores + 15-min score recompute + per-regime _preferred_models routing (is_significant: n≥30, p<0.05)
- Phase 17 gap closure: signal_id UUID threaded through signals:aggregated → llm_calls (E2E Flows 3+4 restored); regime vocabulary standardized

### What Worked

- TDD RED/GREEN discipline on every plan — RED tests caught integration contracts before implementation diverged
- Milestone audit (v1.4-MILESTONE-AUDIT.md) run mid-milestone identified LLM-04/LLM-05 production wiring breaks that unit tests couldn't catch; resulted in Phase 17 being added
- Bootstrap policy for validate_alpha.py: solved the chicken-and-egg problem for new plugins without live data (verdict=BOOTSTRAP + audit trail) without blocking forward progress
- perf_multiplier as primary sort key: simple, clear fix for what was a subtle formula bug (composite_rank × multiplier where high-priority setup always got composite_rank=1)
- Phase GAP plans (15-GAP-01, 15-GAP-02) handled bootstrap promotion and I7 candlestick wiring cleanly without reopening earlier plans

### What Was Inefficient

- Audit ran mid-milestone (before Phase 14/15 started) and identified orphaned requirements — not wrong, but required a re-audit pass at completion; running audit after milestone is more efficient
- REQUIREMENTS.md traceability table diverged from audit file (showed Complete while audit showed orphaned) — single source of truth needed; the audit should be re-run at completion, not just mid-milestone
- Rate limit mid-plan (14-05) interrupted execution; minor, but plan continuations benefit from smaller atomic chunks
- State.md showed "Phase 15 active, 4 of 5 plans done" at session start but all 7 plans (incl. GAP-01/02) were complete — STATE.md wasn't updated after the final push; requires discipline on every session end

### Patterns Established

- **Bootstrap policy for data-absent plugins**: verdict=BOOTSTRAP not FAIL; audit trail in docs/validation/; re-run validate_alpha.py --promote after data accumulates
- **Milestone audit mid-milestone**: Identifies structural gaps early; Phase 17 was a direct result of the Phase 16 audit catch
- **GAP plans within a phase**: 15-GAP-01 and 15-GAP-02 handled retroactive gap closure without renumbering existing plans; clean extension pattern
- **perf_multiplier primary sort**: Performance rank is the primary key; SETUP_PRIORITY only as tiebreaker — simpler, correct, resistant to priority-inflation bugs
- **signal_id hot-tier-first pattern**: xadd fires before DB insert; xdel compensates on DB failure — prevents orphaned signal_id in Redis

### Key Lessons

1. **Audit before claiming complete**: The v1.4 audit ran before Phase 14/15 existed — it identified real gaps but created confusion because REQUIREMENTS.md showed them as Complete. Always re-run audit at completion, not just mid-milestone.
2. **Unit tests don't catch integration wiring**: LLM-04/LLM-05 had passing unit tests but broken production wiring (signal_id=NULL, regime vocab mismatch). Integration checks (or runtime observation) are required alongside unit tests for stream-to-stream contracts.
3. **Validate correctness early, defer data gate**: Bootstrap policy works — implementing a plugin correctly and promoting with BOOTSTRAP verdict is better than blocking development on the live-data chicken-and-egg. Re-run when data accumulates.
4. **STATE.md must be committed after every plan**: Stale STATE.md misleads the next session. Phase completion = commit STATE.md update is a hard rule.

### Cost Observations

- Model: claude-sonnet-4-6 (100% — balanced profile)
- Sessions: ~8-10 across 4 days
- Notable: Parallel wave execution in execute-phase kept each plan under 2 sessions; Phase 17 was the most focused (2 plans, surgical fixes)

---

## Milestone: v1.5 — Production Hardening

**Shipped:** 2026-03-10
**Phases:** 5 (18-22) | **Plans:** 25 | **Timeline:** 2 days (2026-03-07 → 2026-03-09)

### What Was Built

- Epsilon tolerance (1e-9) for all floating-point comparisons in trade_framer + CIS scorer; ATR multipliers, regime thresholds, RSI zero-loss guard all named constants
- Configurable ibkr_timeout_sec / llm_timeout_sec in Settings; IBKR and all 4 LLM providers use Settings values
- per-key asyncio.Lock() in market_analysis_service, indicator_service, ai_narrative_service — shared state protected from concurrent task access
- Characterization tests pinning RSI zero-loss (100.0), zero-ATR emergency fallback, and concurrent lock isolation
- retry_utils.py: exponential_backoff_with_jitter() + retry_with_backoff() async wrapper; PluginCircuitBreaker wired to all LLM providers and IBKR; Prometheus metrics on all circuit breaker state transitions
- DataFrame cache invalidated only on buffer overflow (not every bar); CIS scorer numpy/BLAS vectorized; plugin call metrics modulo sampling (PLUGIN_METRICS_SAMPLE_RATE=10)
- Three-tier I8 narrative: action_tag (deterministic, instant), narrative_short (~500ms), narrative_deep (~5-8s) as concurrent asyncio tasks; independent SSE routing; dashboard progressive disclosure; old single-call path retired

### What Worked

- Phase scope was tight and surgical — no phase needed a GAP plan or re-verification after gap closure
- Characterization tests (Phase 19) proved the right pattern for pinning numeric invariants: seed _state directly, assert behavioral ordering not exact floats, use `__new__` to bypass `__init__`
- Three-tier narrative (Phase 22) was the highest-complexity plan of the milestone and had zero rework — the concurrent task pattern was clean once the spread-merge SSE approach was chosen
- Audit at completion (not mid-milestone, per v1.4 lesson) worked well — `tech_debt` verdict didn't block completion, and the 3 partial items were correctly scoped as naming/tracking gaps not functional gaps
- 2-day execution for 5 phases is the fastest milestone yet — hardening work is well-suited to parallel waves

### What Was Inefficient

- Phase 18 required re-verification (score went 9/13 → 13/13) — plans 18-01 through 18-03 were executed before the epsilon tolerance scope was fully clear; plans 18-04 through 18-06 closed the gaps. Better upfront scoping of which files needed epsilon treatment would have avoided the re-verification pass.
- REQUIREMENTS.md checkboxes weren't updated during execution (3 "partial" API items in audit were actually tracking gaps, not implementation gaps) — the audit caught them as `tech_debt` but they should have been marked complete as each plan was committed
- ai_narrative_service._per_signal_timeout still bypasses Settings.llm_timeout_sec — discovered in audit. This was a wiring oversight in Phase 18 not caught until Phase 22 verification. A cross-file grep for hardcoded timeout values at the start of Phase 18 would have caught it.
- STATE.md `percent: 36` at milestone completion was stale — progress tracking wasn't updated after Phase 22 completed. Same issue as v1.4.

### Patterns Established

- **Characterization tests over exact-value assertions**: Pin behavioral invariants (directional ordering, fallback presence, lock isolation) not exact floats — tests are robust to implementation changes while still encoding the contract
- **`__new__` pattern for lock tests**: Bypass `__init__` entirely and set only the specific attribute being tested — isolates the asyncio.Lock test from all service startup complexity
- **spread-merge SSE state for async arrivals**: `{...existing, ...newFields}` merges independent async stream messages into the same state key without coupling tier arrivals — clean pattern for any multi-message per-event SSE design
- **Overflow detection via `len_before == history.maxlen`**: Deque semantics guarantee eviction only when at capacity; flag-based cache invalidation avoids rebuilding DataFrame on every bar
- **Prometheus state snapshot pattern**: Capture `previous_state` before the operation, compare after — detects actual state transitions for metric emission without false positives

### Key Lessons

1. **Hardcoded values need a grep sweep at phase start**: Phase 18 targeted configurable timeouts but missed `_per_signal_timeout` in ai_narrative_service. A `grep -r "timeout" services/` at the start of the phase would have included it in scope before plans were written.
2. **Audit as `tech_debt` is a valid completion gate**: Not every gap needs to be closed before shipping. The 3 partial items were naming and tracking gaps, not broken behavior — accepting them as tech debt and noting in MILESTONES.md is the right call.
3. **Concurrent task patterns need SSE-side counterparts**: Phase 22 fired two independent LLM tasks correctly but the SSE handler needed a matching spread-merge pattern. The async task change and the SSE handler change must be designed together — one is incomplete without the other.
4. **STATE.md progress percent is unreliable** — it gets set at phase start and not updated. Either remove percent tracking or enforce update-on-completion. Currently it's noise.

### Cost Observations

- Model: claude-sonnet-4-6 (100% — balanced profile)
- Sessions: ~6-8 across 2 days
- Notable: Fastest milestone execution yet — surgical hardening phases fit well into short focused sessions; Phase 22 (most complex) completed in one session

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 MVP | 10 | 29 | Established typed bus, feature store, dashboard |
| v1.1 | 1 | 1 | Code quality sprint; ruff 206→0 |
| v1.2 | 6 | ~18 | Intelligence expansion (I2/I5/I6); correctness audit pattern |
| v1.3 | 4 | ~10 | I7 plugin additions; Signal Lifecycle redesign |
| v1.4 | 6 | 29 | Regime gating, feedback loops, statistical validation, LLM audit |
| v1.5 | 5 | 25 | Production hardening: float safety, locks, circuit breakers, efficiency, three-tier I8 |

### Cumulative Quality

| Milestone | Tests | Ruff | Plugins |
|-----------|-------|------|---------|
| v1.0 | 796 | 0 | 62 + 2 agg |
| v1.1 | 803 | 0 | 62 + 2 agg |
| v1.2 | 965 | 0 | 84 + 2 agg |
| v1.3 | 1083 | 0 | 88 + 2 agg |
| v1.4 | 1286 | 34 (E501 only) | 91 + 2 agg |
| v1.5 | 1318 | 74 (E501 only) | 91 + 2 agg |

### Top Lessons (Verified Across Milestones)

1. **Integration wiring breaks evade unit tests** — v1.4 LLM-04/05 wiring, v1.3 consumer group stale position, v1.2 duplicate timestamps. Unit test pass ≠ production wiring correct. Always verify stream-to-stream contracts with an integration check.
2. **TDD RED phase is load-bearing** — Plans without a TDD RED phase produced more rework. RED tests encode behavioral contracts; catching them before implementation prevents subtle bugs in aggregation and stream contracts.
3. **Data capture over correctness** — Several v1.4 decisions (shadow signals, bootstrap policy, LLM call capture even on failure) follow the Jim Simons principle: capture everything, you can filter later. You cannot recover data you didn't capture.
4. **Grep sweep before writing plans** — v1.5 taught that hardcoded values (timeouts, constants) need a cross-codebase grep at phase start, not discovered during audit. Scope definition belongs in research, not verification.
