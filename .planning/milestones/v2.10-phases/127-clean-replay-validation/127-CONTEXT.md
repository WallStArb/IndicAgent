# Phase 127 CONTEXT.md

## Phase: Clean Replay + Validation

**Goal:** Run full historical replay on corrected pipeline (Phases 123-126 in place, 3-table schema from 128-130) with --warmup. Produce validation report using correct methodology. Retrain calibration curves on clean corpus.

**Depends on:** Phase 123, 124, 125, 126, 128, 129, 130 (all v2.10 phases complete)

**Type:** Execution + Validation

## Background

Phase 127 is the empirical validation that v2.10 architecture changes achieved their goals. It was deferred from Phase 121 → 126 → after 128-130 so that clean replay lands directly in the final 3-table schema with counterfactual_pnl_r ready for ML training.

**What Changed in v2.10:**
- Phase 123: ECL boundary - removed emission suppressors, now all extrinsic vectors are annotations
- Phase 124: Cold-start hardening - NULL context_features handled correctly
- Phase 125: APR migration - 51 constants externalized to config_state
- Phase 126: Confluence wiring - all signal-generation plugins emit CTF, zone mechanics fixed
- Phase 128: 3-table schema ADR - signal_events/trade_frames/trade_executions defined
- Phase 129: Database migration - new tables applied
- Phase 130: Script rewriting - all write paths migrated to 3-table

**Why Clean Replay Matters:**
- Produces ML training corpus with correct architecture from day one
- Validates that all changes work together end-to-end
- Measures signal quality improvement (before vs after)
- Provides empirical evidence for RCA Part VI

## Success Criteria (Adapted from ROADMAP)

**The actual definition of signal success is EDGE (predictive value / pnl). Phase 127 cannot measure edge because the replay corpus has no PnL outcome target.** Everything below is either a plumbing check, a structural check, or a descriptive measurement - none of it is a claim that signals are good. The report must say so plainly rather than substituting an arbitrary fire-rate percentage for the question we cannot yet answer.

1. **Clean replay completes without errors** - all historical data replayed successfully, deterministically, zero orphans
2. **`context_features` coverage > 99% for non-cold-start signals** - DATA COMPLETENESS gate (missing features = broken plumbing), not a signal-quality judgment. Valid as a hard gate.
3. **Emission fire rate is MEASURED and REPORTED, not gated.** `100 * COUNT(signal_events WHERE setup_plugin=X) / COUNT(intelligence_features bar-instances)` (D6 methodology from Phase 124-07). The single structural claim it supports: the Phase 124 onset_guard leak (pre-fix 15-30% of bars) is closed. Fire rate is NOT success - a valid signal at 10% fire rate with edge is good; a 0.5% signal without edge is not. Do NOT encode "< 3%" as a pass/fail verdict.
4. **Validation report uses correct methodology:**
   - Signal volume delta (before/after count reduction)
   - CTF coverage as feature (context_features coverage)
   - Emission fire rate distribution per setup (descriptive, not gated)
   - **NO Welch's t-test** (populations not exchangeable - see RESEARCH.md Issue 1)
   - **NO calibration correlation / bootstrap CI** - no PnL outcome target exists in the replay corpus (see RESEARCH.md Issue 4); reporting it would produce empty columns dressed up as evidence
   - **NO cross-population comparisons**
5. **Signal EDGE measurement DEFERRED to v2.11** - the real success criterion. Requires `counterfactual_pnl_r` (CounterfactualTracker) which is NULL this phase. The report and RCA Part VI must name this gap explicitly.
6. **Calibration retrain DEFERRED to v2.11** - same root cause (no target). Plan 03 surfaces the blocker; it does NOT run a retrain on empty/NULL targets.
7. **RCA Part VI updated with MEASURED values** (plumbing + structure + fire-rate distribution), with explicit acknowledgement that edge is unmeasured this phase

## Key Constraints

### Schema: 3-Table Architecture

All queries MUST target the new schema:
- `signal_events` (detection): raw_confidence, context_features, ctf_*, status, direction (TEXT)
- `trade_frames` (hypothesis): entry_price, stop_price, target_price, counterfactual_pnl_r (NULL v2.11), frame_details JSONB
- `trade_executions` (execution): actual_pnl_r, actual_fill_price, exit_reason. **Joined via `frame_id`, NOT `signal_id`** - this table has no `signal_id` column. Full chain: `signal_events.signal_id` -> `trade_frames.signal_id`, then `trade_frames.frame_id` -> `trade_executions.frame_id`.
- `signal_ledger` (JOIN view): legacy compatibility, use for queries

**Dropped items (DO NOT reference):**
- `signal_outcomes` table (dropped)
- `signal_ledger_full` view (renamed to signal_ledger)
- `signal_type`, `feature_tf`, `bucket_scores`, `staleness_score` columns (dropped)

### Methodology: No Cross-Population Statistics, No Outcome-Based Calibration

**CRITICAL:** Do NOT use Welch's t-test for before/after pnl_r comparison. The before and after populations are NOT exchangeable (different sample composition). ROADMAP SC-04 explicitly forbids it.

**Correct validation measures (all outcome-free):**
- Signal volume delta (objective count difference, before-snapshot vs post-replay)
- CTF coverage (context_features JSONB not NULL/empty, non-cold-start subset)
- Emission fire rate distribution (signals per bar-instance in `intelligence_features`, per setup_plugin) - DESCRIPTIVE ONLY, not a pass/fail gate; the one structural claim it supports is that the Phase 124 onset_guard leak (15-30%/bar) is closed
- Null distribution (plugins firing at sane structural rates, not at the every-bar leak rate)

**Calibration correlation is NOT measured this phase.** It requires a PnL outcome variable. Neither candidate exists in the replay corpus (see RESEARCH.md Issue 4):
- `counterfactual_pnl_r` (trade_frames): NULL by design - CounterfactualTracker lands in v2.11
- `actual_pnl_r` (trade_executions): table is unpopulated - replay emits signals and frames but never executes trades

### `stopped_at_entry` Is Not Measurable In Replay

`stopped_at_entry` is an execution-layer outcome (`trade_executions.exit_reason`). Replay does not populate `trade_executions`, so this count is structurally 0 and carries no information about whether Phase 126's zone mechanics suppress stopped-at-entry leaks. Reporting "0 stopped_at_entry" as evidence of success would be a false positive. Plan 02 records this explicitly rather than emitting a misleading zero column. It becomes measurable once executions exist (live trading or an execution-simulating replay path).

### Data Integrity Requirements

- **No orphaned records:** Every signal_events has matching trade_frames
- **Context features coverage:** > 99% for non-cold-start signals
- **Deterministic replay:** Same inputs -> identical outputs (uuid5 frame_id)

## Deliverables

1. **Before-snapshot baseline** (regenerated for 3-table schema compatibility)
2. **Clean replay execution** (full historical corpus with --warmup)
3. **Validation report** (`docs/plans/phase-127-validation-report.md`) - outcome-free measures only
4. **RCA Part VI update** (with MEASURED values)
5. **Calibration deferral record** (`docs/plans/phase-127-calibration-retrain-log.md`) - documents the v2.11 blocker; does NOT retrain on empty/NULL targets

## Planning Guidance

**Task structure:** Follow 121-02-PLAN.md structure BUT with these critical adaptations:

1. **Regenerate before-snapshot** - Old baseline incompatible with 3-table schema
2. **Adapt all queries to 3-table** - signal_events/trade_frames/trade_executions, with the correct `frame_id` join chain for execution-layer data
3. **Remove Welch's t-test** - Replace with null distribution validation
4. **Remove calibration correlation / bootstrap CI** - No outcome target exists in the replay corpus (defer to v2.11)
5. **Fire rate = emission frequency, reported not gated** - `signals / intelligence_features bar-instances` (D6 methodology). Report the distribution; do NOT encode "< 3%" as a verdict. A hard fire-rate gate is a proxy that hides the real question (edge).
6. **Use signal_ledger view** for legacy query compatibility where possible
7. **Document counterfactual_pnl_r NULL AND trade_executions empty** - calibration deferred to v2.11

**Execution order:**
1. Regenerate before-snapshot (pre-replay baseline)
2. Run clean replay with --clean (wipe existing, replay fresh)
3. Verify replay integrity (no orphans, coverage metrics)
4. Generate validation report (outcome-free measures only)
5. Update RCA Part VI
6. Record calibration deferral (ml-training pre-flight blocks on NULL/empty target; surface as v2.11 dependency)

## Risks & Mitigations

| Risk | Impact | Mitigation |
|-------|--------|------------|
| Replay fails mid-corpus | High | Use checkpoint/resume from run_historical_pipeline.py |
| Orphaned signal_events | High | Verify G0 grouping integrity post-replay |
| Context features low coverage | Medium | Investigate cold-start handling, Phase 123 ECL |
| Before-snapshot incompatibility | Medium | Regenerate baseline per 3-table schema |
| Silent vacuous calibration | High | Calibration removed from report entirely; v2.11 dependency documented (do NOT emit empty bootstrap columns as if they were evidence) |
| False-positive stopped_at_entry=0 | Medium | Recorded as "not measurable in replay" rather than reported as a pass |

## References

- ROADMAP.md Phase 127 definition
- 121-02-PLAN.md (adapted for 3-table schema)
- 127-RESEARCH.md (methodology resolution)
- Phase 128-130 artifacts (3-table schema)
- Phase 123-126 artifacts (ECL, APR, confluence)
