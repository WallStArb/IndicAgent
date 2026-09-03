---
phase: 142B
reviewers: [claude]
reviewed_at: 2026-07-09T19:49:14Z
plans_reviewed:
  - .planning/milestones/v3.1-phases/142B-frame-simulation-counterfactual-tracking/142B-01-PLAN.md
  - .planning/milestones/v3.1-phases/142B-frame-simulation-counterfactual-tracking/142B-02-PLAN.md
attempted_but_unavailable:
  - codex (usage limit, resets 2026-07-17)
  - antigravity (individual quota exhausted, resets ~2026-07-13)
  - coderabbit (browser auth required, could not complete headlessly)
---

# Cross-AI Plan Review — Phase 142B

## Claude Review (Fable 5)

ExitPlanMode isn't available in this headless invocation, so here is the review directly, as the request specified ("output your review in markdown format"). The full text is also saved at `/home/bg/.claude/plans/cross-ai-plan-federated-hamster.md`.

Before the detail: I re-verified the plans' load-bearing claims against the live DB and code rather than reviewing on paper alone. That verification surfaced **four HIGH findings**, one of which (short-direction handling) is a definite correctness bug that would silently corrupt the phase's entire output while passing every test the plans specify.

---

**Method:** Plans read in full; load-bearing claims re-verified against the live DB (TimescaleDB 2.27.1), the 2026-06-25 schema doc DDL, `alpha_publisher.py`, migrations 206-213, and referenced test files. Findings marked VERIFIED were checked directly, not inferred.

### 142B-01-PLAN.md (migration 214 + AlphaFrameWriter + SHADOW-REVIEW.md)

#### Summary

A disciplined, precedent-faithful plan whose infrastructure design (chunked anti-join writes, content_key idempotency, APR seeding, D-04 constraint correction, Kafka-topic deletion) is genuinely strong; the research behind it caught real gaps (missing `alpha.scoring.min_strategy_n`, the target_r naming conflict) that a shallower pass would have shipped broken. However, it inherits two unexamined defects from the 2026-06-25 schema doc that will fail at migration-apply time or at first corpus rebuild, and it silently depends on a raw ATR input that does not exist in `feature_vectors` - the research verified the sr_* columns' NULLness but never verified ATR availability.

#### Strengths

- Real empirical verification behind every major claim: sr_* 100% NULL, `alpha_frames` non-existence, APR key absence, migration numbering (214 correct; 213 latest on disk, VERIFIED).
- The D-04 lifecycle correction is carried consistently through DDL, tests, and acceptance criteria with grep-based guards, so regression to the stale schema doc is mechanically caught.
- `cost_r` copy-through from `alpha_events.cost_hurdle` rather than live APR re-derivation is exactly right; the column exists and is stamped per-row by `alpha_publisher.py` (`_cost_hurdle_for_tf`, line 98; VERIFIED). This prevents silent historical drift on recalibration - a subtle catch.
- Anti-join as the checkpoint mechanism (the target table IS the resume state) is the correct ruthless simplification.
- Idempotency is testable and specific: deterministic `content_key` + `ON CONFLICT DO NOTHING`, matching the `alpha_publisher.py` precedent.
- Pitfall 5 (no Kafka topic, no `_AGENT_ID_TO_UNIT` entry) correctly applies the delete-first mandate against the stale schema-doc checklist.
- SHADOW-REVIEW.md as a task with anti-weasel acceptance criteria (`grep -ci "placeholder|simplified"` = 0) operationalizes the pre-commitment discipline instead of just asserting it.

#### Concerns

- **HIGH - Migration will fail: `frame_id uuid PRIMARY KEY` is incompatible with `create_hypertable('alpha_frames','bar_ts')`.** The schema doc DDL (which the plan keeps "except the status CHECK") declares `frame_id` as sole PK, then converts to a hypertable partitioned on `bar_ts`. TimescaleDB requires every unique index, including the PK, to contain the partitioning column; `create_hypertable` will error. VERIFIED: the doc's literal DDL has this shape, and `alpha_events`/`feature_vectors`/`market_data_ohlcv` are all hypertables in this DB. The plan's three-deviation list has no PK fix, so the executor hits an apply-time failure (best case) or silently drops the hypertable conversion (worse). Specify the identity strategy explicitly: PK `(frame_id, bar_ts)`, or use `uq_alpha_frames_variant (event_id, bar_ts, frame_variant)` as the identity with `frame_id` as a plain indexed column.
- **HIGH - The frame geometry's ATR input does not exist.** Both plans say "ATR read from feature_vectors for the frame's (symbol, tf, bar_ts) cell." VERIFIED: `feature_vectors` has no price-unit ATR column; everything ATR-adjacent is normalized (`atr_z`, `range_vs_atr`, `true_range_pct`, `poc_dist_atr`). The schema doc's `ATR_from_feature_vectors` was never a real column - the exact "assumption drift" failure mode the research's own Pitfall 1 warns about, applied one column over. Stop distance in price units cannot be computed from what the plan names. Resolve explicitly: compute ATR from `market_data_ohlcv` (the tracker already reads bars), or reconstruct approximate ATR as `true_range_pct × price` (single-bar TR, not smoothed - changes the geometry's meaning). Plan blocker as written.
- **MEDIUM-HIGH - FK to a hypertable + corpus-rebuild truncation coupling.** `alpha_events` is a hypertable; FKs referencing hypertables need TimescaleDB ≥ 2.16 (2.27.1 installed, so likely fine mechanically, but hypertable→hypertable FK should be smoke-tested at apply time). The bigger issue is operational: `truncate_derived_tables.sh` truncates `alpha_events` on every corpus rebuild, and `alpha_publisher` derives `event_id` from `weight_version` - so the next rebuild either fails the TRUNCATE (FK blocks it) or, with CASCADE, silently wipes all frames, and a new `weight_version` orphans every old frame's parentage regardless. The plan needs a stated position now: no FK (provenance via `corpus_run_id` is arguably sufficient), or FK + documented CASCADE semantics + truncate-script update.
- **MEDIUM - `gross_expected_r = abs(alpha_score) × target_r_multiple` mixes incompatible units, then subtracts `cost_r`.** `alpha_score` is an IC-weighted ensemble score, not a probability or R payoff; `cost_hurdle` is calibrated in return-space. The resulting `net_expected_r` has incoherent units - a diagnostic column nobody can interpret is silent-wrong-answer surface. The formula was invented by the planner, not taken from the schema doc. Document its intended interpretation in the migration's column comments and SHADOW-REVIEW.md, or pick a units-coherent definition before freezing it into 12.2M rows.
- **MEDIUM - SHADOW-REVIEW.md freezes two criteria that are not numerically evaluable.** "Max drawdown < 25%" (25% of what base? cumulative R is not a percentage) and "IC Sharpe stable, no cliff in last 20 days" (no numeric definition of cliff). Ambiguous frozen criteria re-open exactly the post-hoc negotiation the document exists to forbid; the freeze moment is the one chance to make them operational.
- **LOW - Long-running read transaction during backfill.** The asyncpg cursor streaming 12.2M rows holds one read transaction open for the whole pass (asyncpg cursors require an open transaction), pinning vacuum/compression on TimescaleDB. Consider chunking the read by (symbol, tf) or bar_ts windows.

#### Suggestions

- Add a fourth explicit deviation to Task 1: the PK/identity strategy, co-decided with whether `frame_id` gets a non-unique index (Plan 02's UPDATE path needs one - see below).
- Resolve the ATR source in Task 2's action text before execution; do not leave it to executor discretion.
- The schema unit test only greps SQL text and cannot catch the PK/hypertable incompatibility; add an apply-time assertion (DO block or scratch-schema apply) to the verification steps.
- Make SHADOW-REVIEW criteria 4 and 5 numeric (drawdown in R units against a stated base; "no cliff" as last-20-day IC Sharpe ≥ X% of full-period).

#### Risk: MEDIUM-HIGH

The write path is low-risk (faithful to a proven sibling), but the plan currently fails at migration apply and has an unbound core input. Both are cheap to fix at plan level and expensive to discover at execution.

### 142B-02-PLAN.md (CounterfactualTracker + FRAME-04 gate)

#### Summary

The anti-OOM discipline is exemplary - it internalizes both recent production OOM incidents on the read side (named cursors) and the write side (per-symbol incremental flush, with a mock test proving the cadence). But the plan's core pure function, `determine_exit`, is specified long-only: applied to the `direction='short'` half of `alpha_events`, it closes every short frame as an instant false stop-out, corrupting the counterfactual corpus and the FRAME-04 verdict built on it. Combined with an unbatched Wave A at 12.2M scale and a BCa bootstrap that is computationally infeasible at million-row cells, the plan is right on infrastructure and under-specified on the simulation itself - the part this phase exists to get right.

#### Strengths

- Named-cursor and worker-write-discipline requirements enforced by grep/inspect-based unit tests copied from an existing proven idiom (`test_ic_engine_compute_split.py`, VERIFIED exists).
- Per-symbol incremental flush with the 3-batches-3-executemany mock test is genuinely good anti-OOM design, correctly framed as the write-side twin of the cursor bug.
- Immutability guard (`status = 'open'` in every UPDATE) makes re-runs safe by construction.
- D-08/D-09/D-10 carried through cleanly: no freshness gate, correct OTel point-gauge semantics, deferred-cadence todo filed with the right references.
- `--evaluate-gate` as a CLI mode respects the 2-service scope; gate filters in-sample (`alpha.validation.oos_start` VERIFIED present in config_state) and gross-only per D-01 with grep enforcement.
- The `<post_execution>` section names the manual ops runs needed for the actual verdict, preventing the "machinery complete = gate passed" confusion that bit Phase 142A.

#### Concerns

- **HIGH - `determine_exit` has no `direction` parameter; shorts are simulated wrong.** The triggers are `bar.low <= stop_price → closed_stop` and `bar.high >= target_price → closed_target`. For a short frame the stop sits ABOVE entry and the target BELOW (Plan 01's own geometry: short stop = entry + 1.5×ATR). Under long-only comparisons, `low <= stop_price` is true on essentially the first bar of every short frame, so every short closes as an immediate false `closed_stop` and short targets can never fire. `alpha_events.direction` includes `'short'` (CHECK constraint, VERIFIED). This poisons roughly half the corpus and everything downstream: pnl_r signs, MFE/MAE, the FRAME-04 verdict, SHADOW-REVIEW accumulation. The bug is inherited verbatim from RESEARCH.md's code example and PATTERNS.md, and the specified test matrix has no short case - RED-GREEN passes while the function is wrong. `determine_exit` must take `direction` (invert stop/target comparisons and pnl sign) and the acceptance criteria must include explicit short-frame tests.
- **HIGH - FRAME-04's BCa bootstrap is computationally infeasible at this N.** Per (tf, regime) cells over ~12.2M in-sample frames hold 10⁵-10⁶+ values. `scipy.stats.bootstrap(method="BCa")` runs a jackknife (N leave-one-out evaluations) plus 9,999 resamples; at N=10⁶ that is ~10⁶ statistic calls for the jackknife alone plus ~80 GB of resample matrix if unbatched. The plan passes neither `batch=` nor caps `n_resamples` nor picks a cheaper method for large N - as written, `--evaluate-gate` hangs or OOMs, ironically the exact threat class (T-142B-04/08) the plan mitigates hardest elsewhere. Use percentile with explicit `batch=` for large cells, or an analytic CLT interval above an N threshold where bootstrap adds nothing.
- **MEDIUM-HIGH - The gate's i.i.d. bootstrap ignores frame overlap.** Frames opened on nearly every bar with hold horizons up to 60 bars share price paths almost entirely within a (symbol, tf); resampling per-frame pnl as independent produces a drastically too-tight CI, making the gate anticonservative - a gate that can pass on noise defeats the phase. Inherited from ROADMAP's FRAME-04 wording, but the plan is the last checkpoint before it freezes into SHADOW-REVIEW.md. Minimal fix: block bootstrap over time or cluster pnl by day before resampling; at minimum pre-commit the effective-N caveat.
- **MEDIUM-HIGH - Wave A geometry fill is unbatched at 12.2M scale.** "For each open frame, fetch the T+1 open bar" in the main process is a per-frame round-trip - the per-row query shape FRAME-02 forbids for the scan, applied one step earlier. Needs a set-based formulation (chunked JOIN from open frames to next-bar opens) or fold entry fill into the Wave B worker, which already streams the needed bars.
- **MEDIUM - Per-frame vs per-cell scan ambiguity; UPDATE index gap.** "For each frame scans... using a NAMED cursor" reads as one cursor per frame (12.2M cursor executions, each cell's bars re-read up to hold_max times). The cursor name `cf_scan_{symbol}_{tf}` implies the correct design - one streaming pass per (symbol, tf) evaluating all its open frames - but the text doesn't require it; make the single-sweep-per-cell design explicit. Relatedly, `UPDATE ... WHERE frame_id = $1` has no supporting index once Plan 01's PK is fixed (none of the schema doc's three indexes cover `frame_id`); key the UPDATE on `(event_id, bar_ts, frame_variant)` or add a `frame_id` index in migration 214. Co-decide with Plan 01's PK fix.
- **LOW-MEDIUM - Stop/target fills ignore gap-through opens.** Filling at exactly `stop_price` when a bar opens through the stop credits an unattainable fill and overstates pnl in precisely the direction that makes the gate easier to pass - the same theoretical-vs-executable distinction Invariant 1 exists for on the returns side. Minimal fix: exit at `min(open, stop_price)` for longs (mirrored for shorts/targets). Worth deciding consciously even if declined.
- **LOW - `closed_ic_decay` edge cases.** (a) In backfill, today's `ic_ci_lower` closes 2007-2026 frames with future information; practical impact is small (historical frames almost always resolve via stop/target/max_hold first) but should be acknowledged. (b) The research example returns `exit_price=None` on an empty bar list with negative IC, which would write a closed frame with NULL pnl; guard that a frame with no observed bars stays open. (c) Convert the scan range by bar count (`ORDER BY timestamp LIMIT hold_max`), not wall-clock arithmetic - sessions and gaps make time-range math wrong on intraday TFs.

#### Risk: HIGH

The infrastructure patterns are the safest part of this plan; the simulation semantics are the riskiest, and the short-direction bug alone would invalidate the phase's output while passing every specified test. All findings are fixable at plan level.

### Overall Assessment

**Do the plans achieve the phase goal?** Structurally yes: two BaseBatch services, D-01..D-10 faithfully carried through, the pre-commitment doc, the gate, and the ops-run epilogue are all present and correctly scoped. But as written, execution would produce (1) a migration that fails to apply (PK vs hypertable), (2) a geometry function with a nonexistent input (raw ATR), (3) a counterfactual corpus wrong for every short signal, and (4) a gate that is both computationally infeasible (BCa at N=10⁶) and statistically anticonservative (overlap-blind bootstrap). None of these is architectural; all are specification-level fixes of a few paragraphs each.

**Overall risk: HIGH** until the four HIGH findings are addressed; MEDIUM-LOW after, given how much of both plans is verified pattern replication. Recommend one replan iteration (direction handling + gate feasibility in Plan 02; PK/identity + ATR source in Plan 01, with the FK/truncation position decided alongside) before execution.

---

## Attempted but Unavailable

- **Codex** — `ERROR: You've hit your usage limit. Upgrade to Plus to continue using Codex... or try again at Jul 17th, 2026 6:25 PM.`
- **Antigravity (agy)** — `RESOURCE_EXHAUSTED (code 429): Individual quota reached... Resets in 96h15m31s` (~2026-07-13).
- **CodeRabbit** — requires interactive browser authentication (`automatic_login_failed` / `automatic_login_timed_out`); cannot complete in this headless session.

---

## Consensus Summary

Only one reviewer completed (Claude/Fable 5); no cross-model consensus is possible this round. Treat all findings as single-source pending a second opinion once codex or antigravity quota resets.

### Agreed Strengths
N/A — single reviewer.

### Agreed Concerns
N/A — single reviewer.

### Divergent Views
N/A — single reviewer.

### Notable: This Reviewer Found What the Internal Plan-Checker Missed

The gsd-plan-checker pass (Sonnet 5, same session, 2 revision iterations) verified requirement coverage, task completeness, dependency graph, CLAUDE.md compliance, and CONTEXT.md decision coverage exhaustively, but did not catch:
1. The `frame_id`/hypertable PK incompatibility (would fail at migration-apply time).
2. That "ATR from feature_vectors" names a column that does not exist.
3. The short-direction bug in `determine_exit` — a same-model blind spot: the RESEARCH.md code example and PATTERNS.md analog were both long-only, and every downstream check (planner, checker) inherited that framing without testing it against `direction='short'`.
4. BCa bootstrap's computational infeasibility at 10⁶-row cells, and the overlap-blind resampling assumption.

This is exactly the value case for cross-AI review: a different model family, independently re-verifying claims against the live DB/code rather than trusting the plan's own assertions, caught defects invisible to same-family reviewers reasoning about the same artifacts.
