---
phase: 168
reviewers: [codex]
reviewed_at: 2026-07-31T11:37:52Z
plans_reviewed: [168-01-PLAN.md, 168-02-PLAN.md, 168-03-PLAN.md, 168-04-PLAN.md, 168-05-PLAN.md]
---

# Cross-AI Plan Review — Phase 168

**Note:** `gemini`, `coderabbit`, `opencode`, `qwen`, `cursor`, `ollama`, `lm_studio`, and
`llama_cpp` were not detected on this system. `claude` was skipped for independence (this
review was run from inside Claude Code). Only `codex` was available and invoked.

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

## Consensus Summary

Only one independent reviewer (Codex) was available this session — no consensus/divergence
comparison is possible across multiple external AIs. Treat the findings below as a single
independent opinion, not a cross-validated consensus.

### Codex's Key Findings (single-reviewer, not consensus)
- Overall risk rated HIGH — not because the design is wrong, but because the phase concentrates
  several genuinely hard correctness surfaces (stateful hysteresis, cross-partition isolation,
  paired-delta statistics, a new sequential null, live verdict transcription) into one phase.
- Top concrete risk: hand-transcribed numeric values moving from calibration script → migration
  → canonical doc (168-01 → 168-05) is a drift vector with no automated cross-check.
- Second risk: the stateful null (168-05) is flagged as the single most failure-prone unit of
  work in the phase — correct on synthetic tests but easy to get subtly wrong on real state
  history.
- Third risk: exact window/watermark identity between the two `construction_name` partitions
  (168-03/168-04) is operationally fragile — already correctly hard-fails per the plans' own
  design, but worth flagging as fragile, not just "handled."

### Divergent Views
N/A — single reviewer.

