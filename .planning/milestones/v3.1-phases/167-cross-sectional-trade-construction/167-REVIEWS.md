---
phase: 167
reviewers: [codex]
reviewed_at: 2026-07-27T03:14:02Z
plans_reviewed:
  - 167-01-PLAN.md
  - 167-02-PLAN.md
  - 167-03-PLAN.md
  - 167-04-PLAN.md
  - 167-05-PLAN.md
  - 167-06-PLAN.md
---

# Cross-AI Plan Review — Phase 167

**Reviewer note:** only Codex was invoked this run. Antigravity and Claude CLIs were detected
available, but Claude was skipped for independence (this review was run from inside Claude Code,
`CLAUDE_CODE_ENTRYPOINT=cli`), and the project's configured `review.default_reviewers` is
`["codex"]` with no `--all`/individual-CLI flag passed, so Antigravity was not invoked. No
consensus synthesis is possible with a single reviewer; treat this as one independent read, not a
cross-AI agreement signal.

## Codex Review

**Summary**

The sequence is generally strong and mostly disciplined about the phase's core rule, "replicate exactly what was proven, then expand only where evidence exists." The best parts are the locked scope to one feature, one timeframe, flat equal-weight deciles, per-bar rebalance, separate read-only validation modes, and the decision to add a new hypertable rather than force this construction into `alpha_frames`. The main risks are not basic implementation, they are methodological: turnover continuity across run boundaries, exact leg selection semantics, and the honesty of Gate 1 and Gate 2. Those are all solvable, but they need tighter edge-case coverage than the plans currently spell out.

**Plan-by-Plan**

- `167-01-PLAN.md`: strong foundation. The new hypertable, scoped APR namespace, truncation registration, and glossary work are the right substrate. Main gap is that the migration and schema test spec is still a little too optimistic about "obvious" contracts, especially provenance-tagged APR descriptions, nullability, and the exact primary key plus hypertable partition alignment.
- `167-02-PLAN.md`: good separation of pure logic from I/O, and the explicit `None` turnover contract is the right defensive choice. Main risk is underspecified edge behavior for tiny universes, ties, and decile rounding, plus the fact that deterministic tie-breaking is a reproducibility change from the original script and should be explicitly justified in tests.
- `167-03-PLAN.md`: this is the right operational shape, especially the streaming cursor and watermarking. Main concern is boundary correctness, not throughput: the plan needs stronger guarantees about how the watermark is derived, how interrupted runs resume, and how the last persisted membership is seeded when the previous run ended mid-bar or after a truncate/rebuild.
- `167-04-PLAN.md`: conceptually sound and aligned with the existing `evaluate_frame_gate` contract in `counterfactual_tracker.py`. The main risk is statistical, not software: shuffled null design, shared draws across scales, and the conservative pass rule need to be framed carefully so the gate is not accidentally overconfident or underpowered.
- `167-05-PLAN.md`: this is the most fragile wave. The attribution gate is useful, but the static-tilt benchmark is retrospective by construction and can be misread as causal if the docs are not precise. The regression/residual definition is also easy to get subtly wrong, especially around intercept handling and mismatched series alignment.
- `167-06-PLAN.md`: correct end-state for a phase like this. The important improvement needed is to make the live-run recording absolutely explicit about failures, divergences from the original script, and what "equivalence" means versus what would count as a bug.

**Strengths**

- The plans preserve the key empirical discipline from the research result: one feature, one tf, flat equal-weight long/short, per-bar rebalance, dollar-neutral, no vol-scaling in v1.
- The architecture choice to add a dedicated `construction_spreads` hypertable is sound. It avoids schema contortions and keeps the portfolio-level measurement separate from per-symbol frame machinery.
- The plans correctly keep the construction path and validation path separate. That matters because Gate 1 and Gate 2 are read-only consumers, not hidden producers of new state.
- Incremental watermarking in Wave 3 addresses the main operational failure mode of the one-off script, which would otherwise rescan an ever-growing corpus forever.
- Reusing existing primitives, especially the day-clustered bootstrap logic from `counterfactual_tracker.py` and the 2-tuple group-key contract already relied on in `alpha_scorer.py`, reduces implementation risk and keeps the statistical machinery consistent across services.
- The plans correctly identify the need to compute net-of-cost on actual measured turnover, not on a fake per-trade constant.
- The explicit note that `alpha.quant.cost_hurdle.<tf>` is a different mechanism from this phase's turnover-weighted cost treatment is important and well handled.
- The no-systemd, manual/on-demand decision is consistent with the rest of the batch-service precedent and avoids premature operationalization.

**Concerns**

- HIGH: Wave 3 does not fully specify crash recovery semantics. If a backfill or incremental run dies after partially writing a bar cluster, the next run must not double-count, skip, or mis-seed turnover from an incomplete last row.
- HIGH: Wave 4's shuffled-ranking null is methodologically plausible, but the plan does not spell out what happens with tied feature values, missing values, or bars with too few eligible symbols. Those edge cases can materially change the null distribution.
- HIGH: Wave 5's static-tilt attribution is easy to interpret too strongly. Time-averaged bucket membership is a retrospective benchmark, not a live causal decomposition, so the documentation must keep that distinction explicit.
- HIGH: The plans do not yet define a canonical failure policy for the validation gates. If the gate fails, the code path, the docs, and the phase outcome all need a single source of truth, otherwise later edits can silently soften the verdict.
- MEDIUM: Wave 1 seeds `null_shuffles` as APR, which is reasonable, but the plan should also say how the description will carry the required provenance tag and whether JSON-typed APR values are validated consistently in the migration and config loader.
- MEDIUM: Wave 2's deterministic tie-break by `(feature_value, symbol)` is fine, but it should be acknowledged as a reproducibility improvement over the original proof script. That is acceptable only if the team agrees that exact ties are effectively irrelevant.
- MEDIUM: Wave 2 does not explicitly cover the case where the universe size is too small for a meaningful decile split. That can happen in test fixtures, partial universes, or future scope changes.
- MEDIUM: Wave 3 should specify whether the service writes a completion metric or structured summary artifact for manual runs. The plan covers logs, but not enough observability for repeatable operator review.
- MEDIUM: Wave 4 reuses `evaluate_frame_gate` correctly, but the field renaming from `tf/regime` to `scale/cost_bps` is a semantic hack that could confuse future readers unless the wrapper is documented very clearly.
- LOW: Wave 6 should add an explicit "raw verdict artifact" path, for example persisted CLI output or a machine-readable summary, so the docs are not the only record of what actually happened.

**Suggestions**

- Add a wave-3 test that simulates a partial run interruption, then verifies the next incremental execution computes turnover against the last persisted membership, not against a fresh empty state.
- Add a wave-2 test suite for small universes, tied feature values, and missing feature values. This is the easiest place for rank-splitting bugs to hide.
- Add an explicit acceptance rule for the gating phases, such as "Gate 1 pass requires both scales to pass at the highest cost tier and the shuffled null to clear at the same tier," so the pass condition cannot drift later.
- In Wave 4, define the null universe carefully. State whether the within-bar permutation preserves universe size, decile fraction rounding, and symbol eligibility filters exactly, because those details matter more than the high-level idea.
- In Wave 5, require the regression to fail loudly on misaligned series lengths, duplicate timestamps, or non-unique bar keys. Silent alignment bugs would invalidate the attribution result.
- Add a dedicated integration test for the corpus truncation order, specifically `construction_spreads` before `alpha_frames`, since that ordering is part of the phase contract.
- Add a test that asserts the phase does not touch `alpha.quant.cost_hurdle.<tf>`, to prevent accidental reuse of the old flat per-tf cost mechanism.
- Consider making the validation wrappers return typed objects instead of raw dicts. That would reduce shape drift when Gate 1 and Gate 2 fields are renamed or repurposed.
- For Wave 6, capture a machine-readable JSON summary of the run, then transcribe the result into docs. That gives you a stable audit artifact if the prose gets edited later.
- Keep the phase docs explicit that Gate 2 is an attribution diagnostic, not a production sizing rule. That distinction matters for later roadmap steps.

**Risk Assessment**

Overall risk: **MEDIUM-HIGH**

The engineering scope is controlled, and the plans reuse the repo's existing batch-service and bootstrap patterns well. The risk is concentrated in correctness under edge conditions and in statistical interpretation. A bad schema migration is recoverable. A subtle turnover or attribution bug is much worse, because it could produce a clean-looking but false "pass" and push a capital-allocation decision downstream on invalid evidence. The plan set is solid enough to proceed, but only if the edge-case tests above are added before the live run.

---

## Editor's Note (cross-check against the actual plan text, added when compiling this file)

Several of Codex's concerns are already addressed in the plan text it was given, worth flagging so a re-plan pass doesn't waste effort re-solving what already exists:

- **Crash recovery / mid-run interruption (HIGH):** 167-03's Task 1 step 3 already seeds prior-run
  leg membership from the single most recently *persisted* row (not from anything held in the
  crashed run's memory), and Task 1 step 5 chunks writes inside `ON CONFLICT DO NOTHING`, so a
  crash mid-chunk loses at most one unflushed chunk's rows, not correctness — the next run's
  watermark (`MAX(bar_ts)`) and prior-leg seed both derive from what actually committed. This is
  the same recovery model `counterfactual_tracker.py` already uses in production. Worth adding an
  explicit crash-simulation test per Codex's suggestion, but the underlying mechanism is not
  missing.
- **Small/degenerate universe handling (MEDIUM):** 167-02's `decile_legs` already returns `None`
  when `n < 2 * n_leg`, and 167-03 Task 1 step 4 explicitly increments a skip counter and omits
  the row rather than writing a degenerate split. 167-02's unit test plan already covers the
  1-symbol and boundary `n_leg` cases. Codex's suggestion to add tied/missing-value coverage is
  still fair and not yet explicit in the test list.
- **Gate 1 pass-rule ambiguity (MEDIUM→addressed):** 167-04 design decision 3 already states the
  binding rule Codex asks for verbatim ("most conservative cost tier... at BOTH scales... AND both
  scales' null_p below 0.05"), so the rule exists; it's a documentation/prominence gap in
  `trade-construction-layer.md` (167-06 Task 3) rather than a missing decision.
- **`tf`/`regime` field rename "hack" (MEDIUM):** this is a real pre-existing pattern
  (`alpha_scorer.py` does the identical rename against the same reused function), not novel to
  this phase, but Codex's point about it confusing a future reader stands — it would be worth a
  one-line note in the module docstring beyond what 167-04 already specifies.

**Genuinely open, worth acting on:**

- Tied/missing-feature-value coverage in the shuffled null (Wave 4) and in `decile_legs` (Wave 2)
  is not explicit in either plan's test list — add it.
- A machine-readable verdict artifact (Wave 6) beyond the log lines and doc prose is not currently
  planned — worth adding given this project's own "docs become the durable record" risk, echoed in
  167-06's own threat register (T-167-17).
- The retrospective-vs-causal framing caution for Gate 2 (Wave 5) is good documentation advice for
  167-06 Task 3's write-up, not a code change.

## Consensus Summary

Single-reviewer run; no cross-AI agreement to synthesize. Treat all findings above as one
independent read, weighted accordingly.

### Agreed Strengths
N/A (single reviewer).

### Agreed Concerns
N/A (single reviewer) — see Codex's Concerns section above, filtered by the Editor's Note.

### Divergent Views
N/A (single reviewer).
