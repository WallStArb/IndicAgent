---
phase: 166
reviewers: [codex]
reviewed_at: 2026-07-23T10:55:18Z
plans_reviewed: [166-01-PLAN.md, 166-02-PLAN.md, 166-03-PLAN.md, 166-04-PLAN.md, 166-05-PLAN.md, 166-06-PLAN.md]
---

# Cross-AI Plan Review — Phase 166

## Codex Review

**Summary**
The phase plan is well structured, strongly empirical, and uses existing code patterns in the right places. The decomposition into diagnosis, scalar calibration, structural candidate, gate, writer wiring, and verdicting is coherent. The main weakness is that the structural arm still depends on Phase 163 being live, but this phase does not actually satisfy that dependency itself, so end-to-end completion can stall even if the new code and unit tests all pass.

**Strengths**
- The plan is tightly traceable to D-01 through D-06, which makes scope and acceptance criteria easy to audit.
- It reuses proven patterns instead of inventing new machinery, especially for APR calibration, confluence clustering, and one-shot gate writes.
- The scalar candidate is grounded in a defensible empirical method and explicitly avoids the bad "IC decay walk" analogy.
- The structural candidate is correctly narrowed to what is actually buildable in v3, with the broader v2.x reuse pushed into an explicit follow-on.
- Holdout discipline is called out repeatedly, including single dry-run cadence, OOS-only gate execution, and snapshot-at-scan-time behavior.
- The plans correctly anticipate bias traps, especially right-censoring, same-timestamp aggregation, and namespace drift.

**Concerns**
- **HIGH:** The structural path still depends on Phase 163 being live, but the phase does not execute Phase 163 itself. That means 166-03-PLAN.md, 166-05-PLAN.md, and 166-06-PLAN.md can all succeed syntactically while the phase still cannot complete its promised structural comparison if `sr_support_dist` remains NULL.
- **HIGH:** The phase objective says it will compare baseline, scalar, and structural and produce a verdict, but the plans allow the structural arm to halt if Phase 163 is not live. That is a valid contingency, but the phase does not define a clean completion criterion for the "structural unavailable" case, so success could become ambiguous.
- **MEDIUM:** 166-02-PLAN.md allows partial per-cell updates when only one side of the stop/target pair is available. That can create mixed geometry states where one key is calibrated and the other silently falls back to global defaults. If that is intended, it should be stated explicitly in the verdict logic and writer behavior.
- **MEDIUM:** The gate plan focuses on pooled criteria, regime companion, and structural non-fallback fraction, but it does not require explicit reporting of frame counts, eligible-cell counts, or population coverage deltas for each candidate. Without those, a smaller or sparser candidate could look better for reasons unrelated to true edge.
- **MEDIUM:** The "one dry-run per candidate" rule is procedural, not enforced by code or state. That leaves room for accidental repeated OOS dry-runs during debugging, which is exactly the leak the plan is trying to avoid.
- **LOW:** The phase intentionally defers SMC, swing/fib, and anchored VWAP, which is justified, but it means the user's broader request to reuse v2 trade-lifecycle logic is only partially answered here. The verdict doc should be explicit about that limitation to avoid overclaiming.

**Suggestions**
- Make Phase 163 a hard pre-flight gate in 166-01-PLAN.md, with a blocking status if `sr_support_dist` is still NULL, rather than only recording the prerequisite.
- Add an explicit success/failure branch for the structural arm in 166-06-PLAN.md, so the phase has a clear completion rule even if Phase 163 is not live.
- Require the verdict doc to report frame counts, eligible-cell counts, and coverage deltas for all three arms, not just pooled criteria and regime companion.
- Decide whether scalar calibration should write stop and target atomically as a pair, or document the mixed global/per-cell fallback case as an accepted intermediate state.
- Add one integration-level smoke test that wires writer, structural confluence, and frame snapshotting together with synthetic Phase 163 fields, not just isolated unit tests.
- Consider a simple run-state sentinel for dry-runs, so repeated OOS dry-runs are harder to do accidentally.

**Risk Assessment**
High. The architecture is good, but the phase's end-to-end success still depends on an external prerequisite being live, and the most important structural branch can degrade into a halt or a degenerate fallback path if that prerequisite is missing. The code-level design is solid; the operational risk is in dependency ordering and comparability, not in the core implementation approach.

---

## Consensus Summary

Only one reviewer (codex) was invoked this run (per `review.default_reviewers = ["codex"]`), so there is no cross-model agreement/divergence to synthesize. Findings below are Codex's alone.

### Key Concerns (Codex, single-reviewer)
1. **Phase 163 pre-flight is a recorded check, not a hard gate.** 166-01's Task 0 checks `sr_support_dist IS NOT NULL` and records the result, but the actual halt-on-missing-data behavior lives in 166-06 Task 2, not as an upfront phase-level gate. Codex reads this as leaving room for 166-02 through 166-05 to "complete" while the structural comparison itself cannot.
2. **No explicit success criterion for the "Phase 163 still not live" case.** The plans correctly halt rather than force a degenerate run, but don't define what "phase complete" means if that halt occurs — the verdict doc could plausibly ship with only 2 of 3 arms scored.
3. **Gate evidence lacks frame/coverage-count reporting.** The gate plan reports pooled + regime-companion criteria and non-fallback fraction, but not raw frame counts per candidate, which could let a sparser population look artificially favorable.
4. **Dry-run discipline (Pitfall 5) is procedural, not enforced.** Correctly identified as a real gap — nothing currently stops a second `--dry-run` invocation against OOS data during debugging.

### Assessment of these concerns
Concerns 1 and 2 are legitimate but were an explicit, deliberate design choice (RESEARCH.md's Pitfall 2 + Open Question 1): Phase 163 execution is treated as an external cross-phase prerequisite, checked at runtime rather than force-executed inside Phase 166's own plan, specifically so Phase 166 doesn't silently absorb Phase 163 as an undeclared sub-task. The "ambiguous success" critique is fair as stated, though — 166-06 should be explicit that a Phase-163-not-live halt is a valid, informative stopping point (not a failure), and the verdict doc should say so plainly if it happens. Concern 3 (frame/coverage counts) and concern 4 (dry-run sentinel) are both cheap, concrete improvements worth folding into 166-04/166-06 before execution.

### Divergent Views
N/A — single reviewer.
