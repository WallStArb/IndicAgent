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

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 MVP | 10 | 29 | Established typed bus, feature store, dashboard |
| v1.1 | 1 | 1 | Code quality sprint; ruff 206→0 |
| v1.2 | 6 | ~18 | Intelligence expansion (I2/I5/I6); correctness audit pattern |
| v1.3 | 4 | ~10 | I7 plugin additions; Signal Lifecycle redesign |
| v1.4 | 6 | 29 | Regime gating, feedback loops, statistical validation, LLM audit |

### Cumulative Quality

| Milestone | Tests | Ruff | Plugins |
|-----------|-------|------|---------|
| v1.0 | 796 | 0 | 62 + 2 agg |
| v1.1 | 803 | 0 | 62 + 2 agg |
| v1.2 | 965 | 0 | 84 + 2 agg |
| v1.3 | 1083 | 0 | 88 + 2 agg |
| v1.4 | 1286 | 34 (E501 only) | 91 + 2 agg |

### Top Lessons (Verified Across Milestones)

1. **Integration wiring breaks evade unit tests** — v1.4 LLM-04/05 wiring, v1.3 consumer group stale position, v1.2 duplicate timestamps. Unit test pass ≠ production wiring correct. Always verify stream-to-stream contracts with an integration check.
2. **TDD RED phase is load-bearing** — Plans without a TDD RED phase produced more rework. RED tests encode behavioral contracts; catching them before implementation prevents subtle bugs in aggregation and stream contracts.
3. **Data capture over correctness** — Several v1.4 decisions (shadow signals, bootstrap policy, LLM call capture even on failure) follow the Jim Simons principle: capture everything, you can filter later. You cannot recover data you didn't capture.
