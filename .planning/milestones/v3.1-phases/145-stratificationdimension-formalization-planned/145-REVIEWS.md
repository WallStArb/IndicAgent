---
phase: 145
reviewers: [codex]
reviewed_at: 2026-08-07T00:00:00Z
plans_reviewed: [145-01-PLAN.md, 145-02-PLAN.md, 145-03-PLAN.md, 145-04-PLAN.md, 145-05-PLAN.md, 145-06-PLAN.md]
---

# Cross-AI Plan Review — Phase 145

**Reviewers invoked:** codex (per `review.default_reviewers` config). antigravity and claude
CLIs were also detected available but not invoked — no `--all` flag or additional reviewer flags
were passed, and `review.default_reviewers` is scoped to `["codex"]`. claude would additionally
have been skipped for independence (this session runs inside Claude Code CLI) had it been in
scope.

## Codex Review

**Summary**
The phase plan is unusually well specified and mostly coherent: it cleanly separates contract, guards, provider, pilot, and documentation work; it respects the ring boundary; and it is explicit about the live-schema constraint that prevents premature writes. The main weakness is that it turns one narrow pilot into canonical thresholds and backlog decisions very quickly, with limited statistical cushion and a heavy dependence on a concurrently changing schema phase.

**Strengths**
- The dependency order is sensible: contract first, then guards and placebo gate, then the one pilot provider, then the pilot artifact, then threshold backfill and doc ratification.
- The plans are disciplined about Ring 1 vs Ring 2 boundaries and repeatedly prohibit importing from `services/` into `src/intelligence/`.
- The live-schema blocker is treated correctly: the plans do not pretend `concept_registry` can be written yet, and they route the pilot into standalone artifacts instead.
- The test strategy is strong for this kind of work: pure-function unit tests, explicit red states, source-level boundary checks, and deterministic RNG seeds.
- Provenance is handled well. The plan does not just add thresholds, it requires comments, artifact citations, and a calibration backlog entry so the exception does not vanish into tribal knowledge.
- The phase is internally staged in a way that supports review: the contract is validated before gates consume it, and the pilot is only attempted after the prerequisites exist.

**Concerns**
- **HIGH**: The pilot-derived constants in 145-05 and 145-06 are being promoted into code from a single candidate dimension, one regime group, and one timeframe. That is enough for a pilot, but it is thin evidence for hardening `max_correlation` and `effective_n_floor` into global defaults.
- **HIGH**: The FDR design says the family is a `regime_group`'s cumulative test history, but the plan does not define a durable runtime store for that history outside the temporary pilot artifact. If Phase 170 lands later without a replayable history source, the implementation can satisfy the unit tests but still leave the production decision path underspecified.
- **HIGH**: 145-05 depends on live corpus facts and a concurrent Phase 170 schema migration. The script is intentionally read-only, which is correct, but the precondition check means this phase can be invalidated midstream by another session. That is a real delivery risk, not just a cleanup issue.
- **MEDIUM**: Several safeguards are encoded as source-text assertions or docstring checks. Those are useful regressions, but they are weaker than behavior-based assertions and can miss semantically equivalent drift.
- **MEDIUM**: The plan relies on private internals from `services/` in tests, including `_build_regime_passes`, `_build_symbol_regime_class`, `_smooth_states`, and `_check_occupation_gate`. That is acceptable for validation, but it makes the tests more brittle to refactors that do not change behavior.
- **MEDIUM**: The placebo gate and orthogonality gate are both statistically sensitive. The plans are careful, but the combination of seeded shuffles, limited sample size, and a single pilot cohort means small implementation differences could produce unstable pass/fail behavior.
- **LOW**: The docs/backlog updates are thorough, but they increase the risk of "paper correctness" outpacing executable correctness if the summary artifacts are not kept in lockstep with the code.

**Suggestions**
- Treat the pilot-derived thresholds as provisional until at least one follow-up candidate or timeframe confirms they are not idiosyncratic to `volatility_pct` on `equity/1h`.
- Add a durable replay source or serialized family-history artifact for FDR decisions so the "cumulative regime_group history" requirement remains satisfiable after the pilot phase.
- Keep the source-level boundary tests, but back them with at least one behavior-level test that fails if a forbidden import is replaced with an equivalent helper copy.
- If Phase 170 is likely to land soon, add an explicit note in the pilot script and summary about how to re-run or invalidate the pilot artifacts when the schema finally admits `regime_model`.
- Consider one small cross-validation step for the pilot thresholds, even if only across adjacent symbols or a second timeframe, before those numbers are treated as normative defaults.
- Preserve the strict `None`-means-refuse behavior even after defaults are filled in. That guard is easy to lose once the code starts working.

**Risk Assessment**
**HIGH**

The plan is strong, but the phase is still high-risk because it combines:
- a new executable contract,
- three new statistical gates,
- a causal registration check,
- a live-corpus pilot,
- derived constants that become canonical,
- and doc/backlog updates that must stay synchronized.

The schema dependency on Phase 170 and the limited empirical base for the derived thresholds are the biggest reasons. The plans are well structured enough to succeed, but if anything slips it will most likely be in the pilot-to-default handoff or in keeping the cumulative FDR history coherent over time.

---

## Consensus Summary

Only one external reviewer (codex) was invoked this pass, so there is no cross-model agreement
to synthesize — this section records codex's findings as single-source input, not consensus.

### Codex's Top Concerns (for /gsd:plan-phase 145 --reviews to weigh)

1. **[HIGH] Single-pilot thresholds promoted to defaults.** `max_correlation` and
   `effective_n_floor` get baked into `gates.py` (145-06) off exactly one dimension × one
   `regime_group` × one timeframe (`volatility_pct` / `equity` / `1h`). This is a real
   generalization risk the plans don't currently flag as provisional.
2. **[HIGH] No durable FDR family-history store beyond the pilot artifact.** D-03's "cumulative
   test history per regime_group" requirement is satisfied for the pilot (one entry) but the
   plans don't specify where that history lives once a second candidate is tested — a real gap
   for whoever builds the next candidate dimension, not this phase's own scope, but worth a
   forward-pointer.
3. **[HIGH] 145-05 races Phase 170.** The precondition re-check (CHECK constraint + table
   existence, re-verified live immediately before running) is the right mitigation already in
   the plan, not a missing one — codex is naming the residual risk (a concurrent session landing
   Phase 170 mid-run), not a design flaw. Worth explicit acknowledgment as accepted residual risk
   given the concurrent-session reality this project already operates under.
4. **[MEDIUM] Source-text/docstring assertions are weaker than behavior tests** for the Ring
   boundary and D-07 comment-provenance checks — real, but consistent with how this codebase's
   existing Ring 0 boundary check (`git commit`'s pre-commit hook) already works, so not a novel
   weakness introduced by this phase.
5. **[MEDIUM] Tests import private `services/` internals** (`_build_regime_passes`,
   `_smooth_states`, etc.) for compatibility/pattern-fidelity checks — matches
   `test_ic_engine_routing.py`'s existing precedent (confirmed by the plan-checker), a known and
   accepted test-only exception to the Ring rule, not a production violation.

### Not Applicable / Already Mitigated

Points 3-5 above are largely already the plan's own explicit tradeoffs (confirmed by
plan-checker's independent verification) rather than novel gaps — codex is correctly naming real
residual risk, not finding something the plan missed. Points 1-2 are the actionable items.
