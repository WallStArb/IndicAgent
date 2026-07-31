---
phase: 168
reviewers: [codex, agy]
reviewed_at: 2026-07-31T11:37:52Z
plans_reviewed: [168-01-PLAN.md, 168-02-PLAN.md, 168-03-PLAN.md, 168-04-PLAN.md, 168-05-PLAN.md]
---

# Cross-AI Plan Review — Phase 168

**Note:** `gemini`, `coderabbit`, `opencode`, `qwen`, `cursor`, `ollama`, `lm_studio`, and
`llama_cpp` were not detected on this system. `claude` was skipped for independence (this
review was run from inside Claude Code). `codex` was available via the standard `/gsd:review`
detection list and invoked directly. `agy` (Antigravity CLI, the successor to the now-deprecated
Gemini CLI — installed under `~/.gemini/antigravity-cli/`, binary at `~/.local/bin/agy`) is not
in `/gsd:review`'s detection list at all and was invoked manually as a second independent
opinion. Two invocation issues were worked around for `agy`: (1) `agy -p -` does not read stdin
the way `gemini`/`codex` do — `-p`/`--print` requires its value as a literal argument; (2)
passing the full ~200KB prompt directly as that argument hit Linux's per-argument `MAX_ARG_STRLEN`
(128KB) — worked around by writing the prompt to a scratch file and pointing `agy` at it via
`--add-dir <scratchdir>` with a short instruction prompt, using `--dangerously-skip-permissions`
since headless/print mode cannot satisfy an interactive tool-permission prompt.

## Codex Review

**Summary**

The phase plan is structurally strong: it cleanly decomposes a risky construction change into calibration, pure logic, service wiring, gate evaluation, and live validation, while preserving the baseline partition and reusing existing bootstrap and verdict machinery. The main weakness is not the design itself but the number of subtle failure modes it has to survive at once: stateful leg hysteresis, cross-partition isolation, paired-delta statistics, and a live backfill/gate run with manual transcription into the canonical design doc.

**Strengths**

- The wave ordering is sensible: measure first, then add pure functions, then wire the service, then add the gate, then run the live backfill and record the verdict.
- D-02 is handled correctly by keeping a second `construction_name` in the same service rather than cloning the pipeline.
- The plans reuse existing primitives instead of inventing new ones: `frame_gate_passes`, `write_verdict_artifact`, `validate_construction_config`, and the existing batch-service patterns.
- The test strategy is strong. Each wave has focused unit or integration tests, and the "mutation-verified" isolation test is a good guard against regression.
- The plans are explicit about what is not being done: no new features, no execution/sizing changes, no per-symbol liquidity taxonomy, no in-place mutation of the baseline.
- The validation bar is appropriately strict for this phase, especially the separation of net improvement, gross non-degradation, turnover diagnostic, and null re-run.

**Concerns**

- **HIGH:** The plan chain depends on several hand-transcribed numeric values and derived outputs moving from script to migration to doc. That is a classic drift risk. One bad copy or rounding mismatch can invalidate the APR seed or the recorded verdict.
- **HIGH:** The stateful null in Plan 168-05 is the most failure-prone part of the phase. Even with good tests, it is easy to accidentally simulate the wrong prior-state history or to make eligible-bar invariance fail on real data.
- **HIGH:** Plan 168-03 and 168-04 rely on exact window identity between the baseline and cost-gated partitions. If backfill scope or watermark behavior is even slightly off, the paired comparison becomes biased or the gate will hard-fail. That is correct behavior, but operationally fragile.
- **MEDIUM:** The dependency metadata is sequential but not fully defensive. The wave structure implies order, but the plan files themselves do not always make all prerequisites explicit at the task level. That increases the chance of accidental out-of-order execution in a parallelized workflow.
- **MEDIUM:** The calibration formula in Plan 168-01 assumes the chosen `gross_spread_fast` / leg-gap relationship is stable enough to seed `bps_per_feature_unit`. If the unit interpretation is off, or if the in-sample/OOS drift is large, the derived margin can be badly miscalibrated.
- **MEDIUM:** Plan 168-04 intentionally ships an incomplete artifact first. That is defensible, but it also creates a temporary artifact shape that could be misread by a downstream operator or reviewer if the later completion step is delayed.
- **LOW:** The read-only gate mode and the write-mode construction variant coexist in the same CLI surface. That is fine, but the behavior of `--construction-variant` when used with read-only evaluation modes is not explicitly constrained.
- **LOW:** The plan has no explicit performance budget for the stateful null or the live backfill. It is probably fine at the stated default sizes, but the absence of a runtime expectation is a mild operational risk.

**Suggestions**

- Add an explicit "final verification checklist" in the wave summaries for the numeric seed, migration number, margin, and artifact filename. That reduces transcription error risk.
- Make the dependency chain more explicit in the task metadata, especially for the gate and live-run steps, so future automation cannot run them out of order.
- Consider adding one unit test or assertion that the stateful null's eligible-bar count is stable on a known-good real panel, not just on synthetic test cases.
- In Plan 168-01, record the units assumption for `gross_spread_fast` very clearly in the script output and summary. If there is any ambiguity about whether the value is already in bps, resolve that before seeding APR.
- In Plan 168-04, include skipped-bar counts in the artifact payload if they are available. That would make it easier to debug mismatches between raw panel data and persisted construction rows.
- Decide explicitly whether `--construction-variant` should be ignored, accepted, or rejected in read-only gate modes. Right now it is underspecified.
- Add a brief runtime note to the live gate step stating the expected backfill duration or at least that the stateful null may be the slowest part of the run.

**Risk Assessment**

**HIGH**

The plan is well-designed, but it is high risk because it combines several subtle correctness problems in one phase: empirical calibration, a stateful hysteresis rule, partition-isolated persistence, paired-delta inference, a new sequential null, and a live verdict transcription. The tests and wave structure reduce the risk materially, but the residual failure modes are still the kind that can produce plausible-looking wrong answers rather than obvious crashes.

---

## Agy (Antigravity) Review

**1. Summary**

The implementation plan for Phase 168 is a highly rigorous, well-structured framework designed to transition the platform's descriptive cost-hurdle measurements into a prescriptive, leg-level hysteresis rebalancing rule. Spanning five plans across four sequential waves, it properly prioritizes parallel execution to keep the validated baseline unmutated, avoids scope creep (e.g., deferring a per-symbol liquidity taxonomy to a future phase), and establishes a strict, multi-stage validation gate. Most notably, the plan addresses critical methodological challenges — such as the transition from a memoryless shuffled null to a stateful sequential simulation — with a high level of mathematical and architectural discipline. However, some minor enhancements around database query performance under TimescaleDB, boundary conditions for the calibration script, and explicit handling of backfill synchronization are needed to guarantee flawless execution.

**2. Strengths**

- **Stateful Null Hypothesis Realism (D-04.4):** Recognizing that the memoryless permutation null (`shuffled_ranking_null_p`) is mathematically incompatible with a stateful hysteresis rule is a major strength. The introduction of `stateful_hysteresis_null_p` to simulate the sequential leg history per draw prevents a severe validation anti-pattern.
- **Strict Parallel Isolation (D-02):** Parameterizing `CrossSectionalSpreadTracker` rather than duplicating the class or mutating the baseline in-place maintains strict system hygiene. The integration test (`test_backfill_second_construction_name_isolated`) ensures that logical partition leaks are caught at the CI/CD level.
- **Preservation of Statistical Rigor (D-04.1 / D-04.2):** Computing a bootstrap confidence interval on the *paired delta* series rather than subtracting separately-overlapping point estimates is statistically correct. Additionally, wrapping the non-degradation check in a scale-free tolerance test (`gross_spread_not_degraded`) prevents cost savings from masking underlying decay in signal quality.
- **Fail-Loud Architecture (ASVS V5):** Reusing the `validate_construction_config` pattern and introducing `validate_hysteresis_config` to raise explicit `ValueError`s instead of silently clamping out-of-bounds config values preserves the platform's defensive programming paradigm.

**3. Concerns**

- **TimescaleDB Cross-Hypertable Join Performance (Plan 01, Task 1)**
  - **Severity:** MEDIUM
  - **Detail:** The calibration query joins `construction_spreads` and `feature_vectors` on `tf` and `bar_ts`. Since `feature_vectors` contains 54 features for 58 symbols, it is a very large table. If the database does not have an index starting with `(tf, bar_ts)` on `feature_vectors` (e.g., if the primary key is `(symbol, tf, bar_ts)`), this join may result in a full table scan or high CPU utilization on the live database.
- **Zero or Degenerate Universe in Calibration (Plan 01, Task 1)**
  - **Severity:** LOW
  - **Detail:** If the calibration script encounters a database state where the sum of `leg_value_gap` is zero or there are no valid bars after dropping non-positive gaps, the calculation of `bps_per_feature_unit = 10000.0 * mean(gross_spread_fast) / mean(leg_value_gap)` will raise a `ZeroDivisionError` or return `NaN` without a clear, operator-friendly error message.
- **Backfill End-Date Synchronization (Plan 05, Task 3)**
  - **Severity:** LOW
  - **Detail:** In Step 2 of Plan 05, the operator backfills the cost-gated variant. If the live ingestion pipeline has written new bars to the database since the baseline was last backfilled, the cost-gated backfill will run up to the latest available bar, making its max timestamp newer than the baseline's. This will cause `_build_delta_series` to raise a `RuntimeError` due to unmatched bars, halting the evaluation gate.

**4. Suggestions**

- **Optimize the Join on `feature_vectors`:** In `phase168_margin_calibration.py`, verify the indexing strategy on `feature_vectors`. If query performance is slow, consider modifying the SQL query to filter explicitly on the active symbol universe or add a query hint/sequential scan bypass.
- **Add Guardrails to Calibration Division:** In `phase168_margin_calibration.py`, add an explicit guard check before calculating `bps_per_feature_unit`. If `mean(leg_value_gap) == 0` or no valid bars remain, raise a descriptive `RuntimeError` stating that the feature gap is degenerate and cannot be calibrated.
- **Provide an End-Timestamp Parameter for Backfill:** Introduce an optional `--until-ts` or `--max-bar-ts` argument to the `CrossSectionalSpreadTracker` CLI. This allows the operator to bound the cost-gated backfill exactly to the baseline's max timestamp if the live database has progressed, avoiding manual database truncation to align the windows.
- **Explicitly Re-evaluate Weakest Member in Hysteresis Loop:** In Plan 02, Task 1, Step 8, explicitly specify in the pseudo-code that when a challenger displaces a leg member, the `leg` list is mutated, and the "weakest current leg member" must be re-determined (e.g., by re-sorting or updating a tracker index) before comparing it to the next challenger.

**5. Risk Assessment**

**LOW**

The plans are extremely comprehensive, highly localized, and reuse proven statistical and database access primitives (e.g., `frame_gate_passes`, `write_verdict_artifact`). There are no new external package dependencies, zero schema changes, and the baseline execution path is kept strictly separated. The identified risks are minor operational and performance details rather than structural flaws, making the overall risk profile low.

---

## Consensus Summary

Two independent reviewers (Codex, Agy/Antigravity). No reviewer saw the plans or each other's
output — genuinely independent.

### Agreed Strengths
- Both reviewers independently called out the same three architectural strengths: D-02's
  parallel-partition isolation (never mutating the baseline), D-04.1/D-04.2's paired-delta
  bootstrap-CI rigor (not two overlapping point estimates), and reuse of existing primitives
  (`frame_gate_passes`, `write_verdict_artifact`, `validate_construction_config`) over inventing
  new machinery.
- Both flagged the stateful null (D-04.4, Plan 05) as the phase's single hardest correctness
  surface — Codex calls it "the most failure-prone part of the phase"; Agy calls recognizing the
  memoryless-null incompatibility "a major strength" of the design while still flagging it as the
  place requiring the most care.

### Agreed Concerns
- **Window/backfill synchronization fragility** — both reviewers independently identified the
  same failure mode from different angles: Codex frames it as "exact window identity between
  partitions is operationally fragile" (168-03/168-04); Agy pinpoints the exact mechanism —
  if live ingestion advances between the baseline and cost-gated backfills, `_build_delta_series`
  hard-fails on a `RuntimeError` from unmatched bars (168-05, Task 3). Agy's version is more
  actionable: it names the exact function and proposes a concrete fix (`--until-ts`/`--max-bar-ts`
  CLI bound). **Worth considering before Plan 05 executes.**
- Neither reviewer found a phase-goal miss, a dropped D-0x decision, or a scope violation —
  both independently converge on "the design is right, the risk is in execution precision."

### Divergent Views
- **Overall risk rating diverges sharply: Codex says HIGH, Agy says LOW.** Both are reacting to
  the same underlying facts (several subtle statistical/stateful correctness surfaces stacked in
  one phase) but weight them oppositely — Codex treats "many hard-but-individually-mitigated
  problems concentrated in one phase" as compounding risk; Agy treats the same list as
  "comprehensive, localized, zero new dependencies, zero schema changes" and reads it as low risk.
  Read this as: the mitigations (tests, wave structure, fail-loud validation) are real and both
  reviewers credit them — the disagreement is about how much residual risk survives after
  mitigation, not about whether the mitigations exist. Given this phase's own D-04 posture (a
  flat-or-worse result is a legitimate outcome, not a failure), the more relevant question during
  execution is not the aggregate risk label but whether the two reviewers' concrete concerns
  (transcription drift, backfill sync, calibration division-by-zero, join indexing) get caught by
  Plan 168-05's own tests — none of which require replanning, only attentiveness during execution.
- Codex focused on process/operational risk (hand-transcription, dependency-metadata looseness,
  CLI-surface underspecification); Agy focused on concrete implementation bugs (DB join
  performance, division-by-zero, timestamp desync). The two lists barely overlap in specifics,
  which is exactly the value of running both — neither alone would have surfaced the other's
  findings.

