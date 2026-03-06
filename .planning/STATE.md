---
gsd_state_version: 1.0
milestone: v1.4
milestone_name: Quant Foundation
status: completed
last_updated: "2026-03-06T00:08:32.986Z"
last_activity: "2026-03-05 — 16-03 complete: ai_narrative_service instrumented with xadd on 3 call paths (counterfactual/per_signal/group_synthesis) + _score_refresh_loop + adaptive model routing, 25 tests GREEN"
progress:
  total_phases: 16
  completed_phases: 2
  total_plans: 13
  completed_plans: 11
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-04)

**Core value:** Every intelligence output flows through one canonical typed bus that both internal and external consumers can trust.

**Current focus:** v1.4 Quant Foundation — Phase 16: LLM Intelligence Layer (16-03 complete)

---

## Current Position

Phase: Phase 16 IN PROGRESS (3 of 5 plans done: 16-01, 16-02, 16-03)
Plan: 16-03 complete → 16-04 next (signal_lifecycle_service emission — publish llm_outcomes:stream on signal exit)
Status: Phase 16 active — schema done, writer service done, ai_narrative instrumented, lifecycle emission next
Last activity: 2026-03-05 — 16-02 complete: LLMWriterService dual-stream consumer, binomtest significance gate, 15-min score recompute, Redis HSET cache, 12 tests GREEN

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

### Pending Todos

- 5 O(N²) pattern files still unoptimized (non-blocking, low priority)
- 25 todos total in .planning/todos/pending/ (see directory for full list)

---

## Ready to Proceed

Roadmap created — 4 phases, 17 requirements. Start with Phase 12: Signal Integrity.
