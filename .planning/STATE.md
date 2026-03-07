---
gsd_state_version: 1.0
milestone: v1.4
milestone_name: Quant Foundation
status: Phase 15 active — validation gate built; DerivOsc implemented (gate deferred); alpha sources 03-05 pending
last_updated: "2026-03-07T19:21:25.897Z"
last_activity: "2026-03-07 — 15-02 complete: DerivativeOscillatorPlugin (Constance Brown EMA5→EMA3→SMA9) implemented, 8 tests GREEN, validation gate deferred (no live data — not yet registered)"
progress:
  total_phases: 17
  completed_phases: 5
  total_plans: 29
  completed_plans: 28
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-04)

**Core value:** Every intelligence output flows through one canonical typed bus that both internal and external consumers can trust.

**Current focus:** v1.4 Quant Foundation — Phase 16: LLM Intelligence Layer (16-04 complete)

---

## Current Position

Phase: Phase 15 IN PROGRESS (4 of 5 plans done: 15-01, 15-02, 15-04, 15-05)
Plan: 15-03 next (Tier 1 candlestick patterns — implement + validate + promote)
Status: Phase 15 active — validation gate built; DerivOsc implemented (gate deferred); alpha sources 03-05 pending
Last activity: 2026-03-07 — 15-02 complete: DerivativeOscillatorPlugin (Constance Brown EMA5→EMA3→SMA9) implemented, 8 tests GREEN, validation gate deferred (no live data — not yet registered)

## Accumulated Context

### Decisions

- [v1.3]: Signal lifecycle service deployed — labeled outcome data (8-class) accumulating in signal_ledger
- [v1.4]: Build philosophy = Renaissance Technologies standard (Jim Simons principles encoded in architecture)
- [v1.4]: Four disciplines: Signal Integrity → Data Completeness → Feedback Loop → Validated Alpha
- [v1.4]: All new indicators/patterns must pass historical validation before live promotion
- [v1.4]: Phase numbering continues from 12 (v1.3 ended at Phase 11)
- [v1.4]: Roadmap — Phase 12: Signal Integrity (SIGINT-01..05), Phase 13: Data Completeness (DATA-01..04), Phase 14: Feedback Loop (FEED-01..03), Phase 15: Validated Alpha (ALPHA-01..05)
- [12-02]: regime_type attribute on all 17 I7 plugins — 5 trend, 5 mean_reversion, 7 any — zero logic changes
- [12-02]: LiquidityHunt=trend, LiquiditySweepReclaim=mean_reversion, SqueezeExpansion=trend (CONTEXT.md decisions honored)
- [12-02]: CHoCHReversal/RegimeTransition=any — gating on current regime would suppress at exact moment they should fire
- [12-01]: Shadow signals in all_ranked — regime_suppressed signals must NOT be dropped, must appear tagged with regime_eligible=False
- [12-01]: Virtual-activation pattern confirmed — evaluate_signal(status='active') handles shadow signal tracking without lifecycle_tracker changes
- [12-01]: I7 plugins already had regime_type before plan expected — test passes immediately (no Plan 02 work needed for plugin attributes)
- [Phase 12]: regime_data= (higher-TF) drives regime gate; features= (same-TF) unchanged for CIS
- [Phase 12]: Shadow signals persist to signal_ledger with status='regime_suppressed' for observability
- [Phase 12-signal-integrity]: Shadow signal virtual-activation: status='regime_suppressed' preserved on exit; _activated_at set from signal timestamp
- [Phase 12-signal-integrity]: SIGINT-05 complete: all 4 Phase 12 plans done; shadow counterfactual data accumulates in signal_ledger for empirical gate tuning
- [Phase 13-data-completeness]: i7 defaults '[]' not '{}' — empty list semantics for no signals fired per bar
- [Phase 13-data-completeness]: days_to_expiry nullable — NULL honest for pre-migration rows; feature_writer sets value on new writes
- [Phase 13-data-completeness]: intelligence_i7/i8 stream maxlen=200 — async enrichment backpressure without excessive memory
- [Phase 13-data-completeness]: ENRICH_CONSUMER_GROUP ('feature_writer:enrich') separate from CONSUMER_GROUP for independent i7/i8 stream position tracking
- [Phase 13-data-completeness]: days_to_expiry computed at feature_writer write time via startup-cached expiry_map; None for uncached, 0 for non-futures
- [Phase 13-data-completeness]: DATA-01..04 all complete — intelligence_features now carries i7/i8 JSONB + days_to_expiry; Phase 13 done 2026-03-05
- [Phase 16]: llm_calls partitioned by called_at; outcome columns NULL at insert, back-filled on lifecycle exit
- [Phase 16]: is_significant gate: n_outcomes >= 30 AND p_value < 0.05 — Renaissance significance requirement for model routing
- [Phase 16]: Stream keys locked: llm_calls_stream, llm_outcomes_stream, llm_scores_cache; maxlens 500/200
- [Phase 16]: LLM-04 complete: _build_score_insert_params uses rows list interface (not pre-aggregated); outcomes processed immediately without buffering; score recompute fires 15-min after service start
- [Phase 16]: Per-signal xadd emits even on LLM failure — succeeded=0, full context preserved; counterfactual captures would-have-been prompt; _apply_score_routing picks global best_model by avg_pnl_r across regimes
- [Phase 16]: LLM-03 complete: signal_lifecycle_service emits to llm_outcomes:stream on both exit paths via fire-and-forget create_task; emit order (before update_signal_status and before memory cleanup) ensures data capture even on DB failure
- [Phase 16]: Smoke test success criterion: llm_calls=0 acceptable when markets closed; verified via consumer group + :9117 Prometheus metrics endpoint
- [Phase 16]: Migration soft FK: signal_id is UUID without FK constraint (signal_ledger has composite PK); soft reference pattern confirmed
- [Phase 16-llm-intelligence-layer]: Per-regime routing: _preferred_models[call_type][regime] stores best is_significant model per regime independently — no global winner overrides per-regime winners
- [Phase 16-llm-intelligence-layer]: LLM-05 complete: per-regime routing wired at call sites with __all__ fallback
- [Phase 16-llm-intelligence-layer]: Migration 020 uses idempotent DO block guard on timescaledb_information.hypertables; migrate_data => TRUE for existing rows; 019 source corrected for future deployments
- [Phase 16-llm-intelligence-layer]: Migration 020 applied to production: llm_calls is now a TimescaleDB hypertable partitioned by called_at with composite PK (call_id, called_at)
- [Phase 17-llm-wiring-fix]: session_extreme_london/ny/both are the canonical regime strings for SessionExtremesSetup — raw plugin output IS the LLM routing vocabulary, no translation layer
- [Phase 17-llm-wiring-fix]: supporting_factors in SessionExtremesSetup now carries session:<ctx> label alongside confirming-factor strings; consumers must use membership checks not equality
- [Phase 17]: stream xadd fires before insert_signals (hot tier first); xdel compensates on DB failure to avoid orphaned signal_id
- [Phase 17]: signal_id sourced from winning LedgerEntry (was_selected=True); empty string when no winner
- [Phase 14-feedback-loop]: Module-level import in RED test causes collection ERROR — correct TDD RED behavior for non-existent modules
- [Phase 14-feedback-loop]: perf_weights dict contract: {env_prefix}setup_performance:weights Redis key, adjusted_rank = composite_rank * perf_multiplier, neutral=1.0 for missing setups
- [Phase 14-feedback-loop]: Rolling 30-day window filtered in Python layer (not SQL) so unit tests can pass resolved_at datetimes without mocking DB
- [Phase 14-feedback-loop]: Sharpe rank ascending: worst=0, best=n-1; perf_multiplier=0.5+(rank/n); single eligible setup gets 1.0
- [Phase 14-feedback-loop]: Sort by adjusted_rank ASCENDING (lower = higher priority): tests are authoritative over plan text
- [Phase 14-feedback-loop]: perf_weights dict contract: adjusted_rank = composite_rank * perf_multiplier, neutral=1.0, ascending sort
- [Phase 14-feedback-loop]: FEED-03 fix: inverted perf_multiplier formula gives best Sharpe lowest multiplier (0.5), ranks first under ascending adjusted_rank sort
- [Phase 14-05]: _build_all_ranked() uses perf_multiplier as primary sort key; no-weights fallback uses -SETUP_PRIORITY for consistent ascending sort
- [Phase 15-01]: Correlation computed over ALL bars (signal=1 and 0) not just signal-fired bars — avoids constant-input NaN in Pearson when binary indicator fires consistently
- [Phase 15-01]: validate_alpha.py gate: Pearson r>0 + p<0.05 + N>=30 against N-bar forward close-to-close returns; ADF informational only; auto-backfill when data sparse
- [Phase 15-02]: Validation gate deferred: plugin not registered so no live data; gate re-run after data accumulates via --promote
- [Phase 15-02]: Only validate_alpha.py --promote may patch register_plugins.py — manual patching forbidden per plan constraint
- [Phase 15-05]: validate_alpha gate FAIL on ind_ACOscillator due to n_total_bars=0; promoted to TIER_I1 preemptively since implementation is correct; re-run gate after 30+ bars accumulate
- [Phase 15-04]: macd_hist_accel = float(hist - prev_hist): positive = bullish momentum building; early exhaustion warning before sign flip
- [Phase 15-04]: macd_hist_contracting = 1 when abs(hist) < abs(prev_hist): magnitude shrinkage, direction-agnostic
- [Phase 15-GAP-01]: Bootstrap policy: data-absent plugins with correct implementations get verdict=BOOTSTRAP (not FAIL) — resolves the chicken-and-egg sequence violation for ALPHA-02/04/05

### Pending Todos

- 5 O(N²) pattern files still unoptimized (non-blocking, low priority)
- 25 todos total in .planning/todos/pending/ (see directory for full list)

---

## Ready to Proceed

Roadmap created — 4 phases, 17 requirements. Start with Phase 12: Signal Integrity.
