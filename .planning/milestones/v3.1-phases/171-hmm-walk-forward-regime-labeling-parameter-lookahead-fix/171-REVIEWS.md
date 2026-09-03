---
phase: 171
reviewers: [codex]
reviewed_at: 2026-08-08T00:00:00Z
plans_reviewed: [171-01-PLAN.md, 171-02-PLAN.md, 171-03-PLAN.md, 171-04-PLAN.md, 171-05-PLAN.md, 171-06-PLAN.md, 171-07-PLAN.md]
---

# Cross-AI Plan Review — Phase 171

Note: only `codex` was invoked, per `review.default_reviewers: ["codex"]` (config-driven reviewer
selection precedence: explicit flags > `--all` > `review.default_reviewers` > all detected). No
flags were passed to this `/gsd-review 171` invocation. `antigravity` and the running-in-session
`claude` CLI were both detected but not in the configured default set, so were not invoked.

## Codex Review

**Summary**

The plan set is strong on empirical discipline and operational sequencing, but it is also very complex and fragile. The biggest positive is that it does not treat the regime-label change as a simple code swap: it explicitly separates pilot diagnostics, destructive data migration, production config flip, downstream recompute, and todo cleanup. The biggest risk is coordination failure across those stages, especially around the pre-null baseline, the partial-rollout failure modes, and the repeated reliance on live process checks and manual evidence copying. Overall, the plans are directionally correct and unusually rigorous, but they need a bit more simplification and a few tighter failure/rollback paths.

**Strengths**

- The phase is decomposed cleanly into a pilot, a proven null-out tool, a gated rollout, and post-rollout reconciliation.
- The plans correctly identify the real hazard: mixed-method regime labels in one column, not just code correctness.
- `171-03` is well designed around resumability and per-cell provenance, which is the right level of granularity for a compressed hypertable.
- `171-04` and `171-05` correctly keep the D-03 comparison out of live writes and preserve the retired baseline before destructive relabeling.
- `171-06` properly requires a hard precondition gate and uses `ConfigService.set()` instead of a raw SQL config flip.
- `171-07` is appropriately scoped as verification/reconciliation work, not a new model change.
- The plans consistently distinguish evidence collection from decision-making, especially for IC-related measurements.
- They explicitly guard against a known bad pattern in this repo: silent mixed-provenance data.

**Concerns**

- **HIGH**: `171-05` and `171-06` are operationally brittle because they depend on a long chain of manually coordinated steps, live process checks, and evidence file copying. A missed step can leave the corpus partially migrated or the baseline lost without an obvious immediate failure.
- **HIGH**: The rollout path in `171-06` can still leave a half-migrated corpus if the run fails after the config flip but before all cells are relabeled. The manifest helps resumability, but the plan does not define a crisp, automated "safe paused state" beyond rerun discipline.
- **HIGH**: `171-04` and `171-05` compare against live production labels before null-out, which is correct, but the plan assumes the evidence JSON files are preserved and merged correctly across stages. That is easy to get wrong and would invalidate the D-03 verdict.
- **MEDIUM**: `171-01`'s negative test guidance, which suggests temporarily mutating the branch to prove failure, is a little too risky for a production-adjacent service file. A branch-inversion unit test would be safer than manual mutation-and-revert verification.
- **MEDIUM**: `171-03`'s verification logic is strong, but it is still keyed on a warmup-prefix count rather than a deeper structural check of single-method provenance across all rows. It proves the intended condition, but only for the chosen predicate.
- **MEDIUM**: The plan set relies heavily on string-matching/log parsing acceptance criteria. That is fine for this repo style, but it is brittle and can fail on formatting changes unrelated to semantics.
- **MEDIUM**: `171-06` uses a generated operational script under `cache/`. That is acceptable for a one-shot action, but it reduces auditability compared with a checked-in helper or a reusable maintenance command.
- **LOW**: `171-07` is well scoped, but if todo 167 remains blocked it may still require a follow-up scoped `ic_engine` run. The plan acknowledges this, but the decision boundary could be a bit more explicit.
- **LOW**: The pilot scope is detailed and defensible, but it is still fairly large for a "staged pilot." If runtime is worse than expected, Stage B of `171-05` may be expensive to the point of diminishing returns.

**Suggestions**

- Add an explicit rollback/restore procedure for `171-06` if the rollout fails after the config flip but before full relabel completion.
- Replace the temporary branch mutation idea in `171-01` with a pure unit test that asserts the branch behavior without mutating source files.
- Make the quarantine path from `171-05` machine-readable and feed it directly into `171-06`, rather than relying on the gate document being manually copied forward.
- Consider persisting the pilot evidence copies and the rollout evidence in a more structured, script-generated artifact format to reduce handoff errors.
- Tighten `171-06`'s safe-state definition so it is explicit what state the corpus is allowed to remain in if the task is interrupted mid-run.
- If possible, reduce the amount of manual log inspection by having the scripts emit structured JSON summaries alongside human-readable logs.
- For `171-03`, consider a small integration test that runs the null-out and verification cycle against a tiny controlled fixture, to prove the script semantics end to end.
- For `171-07`, predefine the contingency branch more concretely if todo 167 is still blocked after the full recompute, so the task cannot drift into another unplanned scan.

**Risk Assessment**

**HIGH**

This is a high-risk plan set because it performs a corpus-wide methodology migration on a live dataset, flips a production behavior flag, and recomputes downstream IC artifacts. The plans are thoughtful and the sequencing is mostly correct, but the failure modes are operational rather than algorithmic: partial rollout, stale baseline loss, evidence mismatch, or a misordered step can leave the system in an incoherent mixed state. The work is justified, but it needs disciplined execution and careful verification at every boundary.

---

## Consensus Summary

Single reviewer this run — no cross-reviewer consensus to synthesize. Codex's own findings stand
on their own merits and should be triaged directly.

### Highest-priority items for a `--reviews` replan pass

1. **HIGH — 171-06 partial-rollout / no defined safe-paused-state.** The manifest gives
   resumability but not an explicit "what state is the corpus allowed to be in mid-run" contract.
   Worth tightening before execution given the blast radius (full corpus, config flip already
   live).
2. **HIGH — 171-01's branch-mutation verification step.** Legitimate concern: temporarily
   inverting a production-adjacent conditional to prove a test catches it, then reverting, is a
   real (if narrow) footgun class for a plan this size. A pure unit test with a monkeypatched
   sentinel (which 171-01 Task 2 already does for the dispatch test itself) is strictly safer and
   achieves the same proof without ever mutating the file under test.
3. **HIGH — evidence-file handoff across 171-04/171-05/171-06.** Codex is right that the
   plan chain leans on JSON files surviving intact across three plan boundaries with no checksum
   or schema-validation step. A missing/corrupt evidence file at 171-06 time would silently
   invalidate the D-03 attribution the whole multi-restart decision rests on.

### Divergent from the earlier gsd-plan-checker pass

The gsd-plan-checker verification (same day) found 0 blockers and 3 non-blocking documentation-sync
warnings — all since closed. Codex's review operates at a different altitude: it does not dispute
requirement coverage, dependency ordering, or threat-model presence (all of which plan-checker
already confirmed), but raises operational-robustness concerns plan-checker's dimensions don't
score for (rollback paths, evidence-integrity across plan boundaries, brittleness of
manual-process-checking). Both reviews are valid and complementary, not contradictory.
