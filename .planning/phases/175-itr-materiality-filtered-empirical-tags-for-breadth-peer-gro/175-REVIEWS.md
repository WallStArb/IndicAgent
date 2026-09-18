---
phase: 175
reviewers: [codex, antigravity]
reviewed_at: 2026-09-18T14:00:57Z
plans_reviewed: [175-01-PLAN.md, 175-02-PLAN.md, 175-03-PLAN.md, 175-04-PLAN.md, 175-05-PLAN.md]
---

# Cross-AI Plan Review -- Phase 175

This is the D-07 / P175-08 pre-execution review gate. Claude CLI was skipped (this session's
own family, not independent). Two external reviewers ran: Codex (gpt-5.5, full prompt via
stdin) and AGY/Antigravity (pointer-prompt to files on disk, per CLAUDE.md's documented
workaround for `agy -p`'s broken stdin handling).

**Every concern below marked CONFIRMED or REFUTED was independently re-verified against the
live plan text and, where relevant, live `services/tag_calibrator.py` source -- not accepted
on either reviewer's word alone.** This is the part of the process that actually matters: two
AI opinions agreeing or disagreeing is not evidence by itself.

## Codex Review

Model: gpt-5.5 (`gpt-5.4-mini`, this project's configured default, is not supported on this
Codex account plan -- reran with `--model gpt-5.5` after the first attempt failed with a
400 error).

### Summary

The plan set is strong overall and matches the phase goal: add a centralized, shadow-mode
materiality measurement path for empirical `instrument_tags` without changing live consumer
behavior. The architecture is disciplined: schema first, pure kernels second, `TagCalibrator`
integration third, read-only diagnostic fourth, documentation/todo cleanup last. Not
execution-ready yet -- real gate-level issues remain, mainly around diagnostic coverage for
`breadth_vol.py`, a possible mismatch between D-01's "every empirical row" wording and Plan
03's "kept pairs only" implementation, and sign-stability/sample-size semantics accidentally
allowing "3 of 3" windows where the design says "3 of 4."

### Strengths

- Clear separation of measurement and admission: `passes_materiality` as statistical-only,
  with `discovery_state` and `valid_to` kept independent, is the right design.
- Pearson partial loading is a defensible choice given existing `loading` semantics.
- Null-arm design shifts the factor proxy, not the candidate -- preserves the
  candidate-to-market structure while breaking candidate-to-factor timing.
- Shadow-mode boundary is explicit and repeatedly asserted by file lists, grep checks, and
  diagnostic-only workflow.
- APR seeding is honest: thresholds marked `[initial_estimate]`, bounded, routed to the
  calibration backlog.
- Migration is additive, idempotency-conscious, correctly introduces `instrument_tags_active`.
- Avoids duplicating factor-series construction; pushes shared math into `factor_math.py`.
- Todo 125/126 fold-ins handled as first-class requirements, not documentation cleanup.

### Concerns (with independent verification result)

- **HIGH -- Diagnostic may not cover `breadth_vol.py`'s live membership path.** Plan 04
  reuses `cross_sectional_regime_model.py` but not `breadth_vol.py` directly; if the latter
  has independent tag-query logic, coverage could be incomplete.
  **VERDICT: REFUTED.** `grep -n "instrument_tags" src/intelligence/regime_signals/breadth_vol.py`
  returns zero matches. `breadth_vol.py` is a pure `def compute(...)` signal function that
  receives an already-resolved symbol list; it has no independent tag-resolution logic of its
  own. All `instrument_tags` peer-group resolution happens exactly once, in
  `cross_sectional_regime_model.py`'s `_resolve_group_symbols`/`_load_tags_by_symbol`, which
  is the same logic that feeds `breadth_vol.py` its universe (`tag_filter: ["eq_*", "intl_*"]`,
  `signal_type="breadth_vol"`). Plan 04's reuse of `cross_sectional_regime_model.py` already
  covers the equity-breadth universe. Codex's concern assumed an architecture (independent
  per-consumer tag resolution) this codebase does not have.

- **HIGH -- Plan 03 may violate D-01's "every `source='empirical'` row" measurement
  requirement.** Plan 03 computes Pass 4 only for currently "kept" Pass 1-3 measurements
  (`passes_fdr AND abs(loading) >= loading_threshold`), a smaller population than "every
  empirical row."
  **VERDICT: CONFIRMED.** `175-CONTEXT.md` D-01's locked text reads verbatim: "...for every
  `source='empirical'` row (unconditionally -- this is a measurement, not an admission
  decision)." `175-03-PLAN.md` consistently scopes Pass 4 to "every **kept** empirical
  (symbol, tag) pair" (lines 15, 45, 49, 274, 371, 385). A row that failed Pass 1-3's gate but
  hasn't hit expiry hysteresis (`consecutive_fails < expiry_consecutive_fails`) is still
  `source='empirical'` in the table and would NOT receive Pass 4 measurement under the plan's
  current scoping, contradicting D-01's literal wording. Real, unresolved ambiguity --
  requires an explicit decision (measure all empirical rows vs. amend D-01's text to say
  "kept"), not a judgment call left to the executor.

- **MEDIUM/HIGH -- Sign-stability gate weaker than "3 of 4 windows."** `decide_materiality`
  allows `sign_stable_windows >= 3` AND `sign_stable_windows_total >= 3` -- a symbol can pass
  with 3 evaluable windows out of 4 possible, not requiring all 4 to be evaluable.
  **VERDICT: CONFIRMED** (live source read of `175-03-PLAN.md` line 259's exact gate
  definition). A candidate with only 3 evaluable windows (e.g. insufficient history for the
  4th), all sign-stable, satisfies `3 >= 3` AND `3 >= 3` -- passing at "3 of 3," not the
  design-intended "3 of 4." **AGY's review explicitly disagrees**, calling this formulation
  "sound" and crediting the `n_evaluable`-based denominator with preventing a "1-of-1" spurious
  pass -- true, but does not address whether "3 of 3" specifically is an intended relaxation
  or a gap. This is a genuine divergence between reviewers, not a case where one is simply
  wrong; both cite the same mechanism and reach different conclusions about whether it's
  sufficient. Flagged for the planner's explicit decision, not resolved here.

- **MEDIUM -- Migration constraint guard should scope by table (`conrelid`, not just
  `conname`).** **VERDICT: CONFIRMED.** `175-01-PLAN.md` line 165's `DO $$` block guards only
  on `conname = 'instrument_tags_discovery_state_check'`, with no `conrelid` scoping -- a
  same-named constraint on an unrelated table would cause this guard to silently skip creating
  the intended constraint. Real, cheap fix.

- **MEDIUM -- Inline null arm cost asserted but not estimated; MEDIUM --
  `control_factor_series` parsing should accept decoded lists, not just JSON strings; MEDIUM --
  gate attribution omits temporal/expiry blockers; LOW/MEDIUM -- some grep-based acceptance
  criteria are fragile; LOW -- Plan 04's read-only grep may be too broad or narrow.** Not
  independently re-verified line-by-line (lower severity, time-boxed); each is plausible on
  its face and worth the planner's attention during revision, but none blocks a decision the
  way the three items above do.

### Suggestions

- Add an explicit Plan 04 task proving `breadth_vol.py`'s universe is represented by the
  cross-sectional group config being reported (documentation clarity, given the REFUTED
  verdict above -- the underlying architecture is fine, but the plan text could say this more
  explicitly so a future reader doesn't raise the same false alarm).
- Resolve the D-01 measurement-universe ambiguity before Wave 1 (see CONFIRMED item above).
- Make sign-stability semantics explicit: either require
  `sign_stable_windows_total == sign_stability_window_count` (true "3 of 4"), or document "3
  of 3" as a deliberate relaxation.
- Add a Plan 03 performance acceptance criterion for null-arm cost (kept-pair count, draws,
  elapsed seconds).
- Harden `MaterialityConfig.from_apr`'s `control_factor_series` parsing for `str`/`list`/`tuple`.
- Extend diagnostic gate attribution with `pending_oos`/`expired` categories.
- Guard the migration 346 CHECK constraint with `conrelid` in addition to `conname`.

### Risk Assessment

**Codex: MEDIUM.** Architecture sound; main risk is an incomplete/mis-specified shadow
report from the confirmed gaps above, not that the statistical idea is wrong. Codex's own
words: "I would approve the architecture but block Wave 1 until the diagnostic coverage and
Pass 4 measurement-universe ambiguity are fixed" -- note this cites the REFUTED
`breadth_vol.py` concern alongside the CONFIRMED D-01 one; only the latter should actually
gate Wave 1.

---

## AGY (Antigravity) Review

### Summary

Phase 175 planning suite is exceptionally rigorous, statistically disciplined, and
architecturally sound. Cleanly executes D-01/D-02 (measurement centralized in TagCalibrator's
4th pass, consumers stay dumb read-time evaluators). D-03 shadow-mode boundary is airtight.
Resolution of statistical open questions R-01 through R-07 reflects institutional-grade
reasoning. Approved to proceed, subject to noted edge-case adjustments.

### Strengths

- Airtight shadow-mode isolation across all 5 plans, enforced by negative assertions
  (`source = 'human'` query count invariant, `git diff --name-only` excludes consumer files,
  `market_regimes` row count/`max(ts)` invariant before/after the diagnostic).
- Pearson partial loading correctly aligns Pass 4 with Pass 1's existing `standardized_loading`
  convention and the 0.2 `loading_threshold` calibration.
- Factor-only circular shift (D-06) is methodologically correct: preserves the candidate's
  true macro structure and the factor's own autocorrelation while breaking the
  candidate-to-factor timing link.
- `select_control_factor_series` correctly prunes tautological/self-regression controls
  (e.g. dropping `HYG-IEF` when testing `HYG` or `IEF`).
- Decoupled governance (R-04): `passes_materiality` stays purely statistical;
  `discovery_state`/`valid_to` unified at read-time via `is_materiality_eligible()`, closing
  todos 125/126 without merging the temporal and statistical gates.

### Concerns (with independent verification result)

- **MEDIUM -- Missing `None` checks in `build_control_return_matrix`.** `175-03-PLAN.md`'s
  spec returns `None` only if `control_series_list` is empty or contains `None`; a missing
  `instrument_ret`/`factor_ret` (e.g. a gap in `price_cache`) would reach `pd.concat([...])`
  unchecked, raising `TypeError` instead of returning `None`.
  **VERDICT: CONFIRMED.** Direct read of `175-03-PLAN.md` lines 212-217: the `None`-check
  list covers `control_series_list` only, not `instrument_ret`/`factor_ret`. Real gap.

- **MEDIUM -- Orchestration ordering of `factor_series_cache` in `TagCalibrator.execute()`.**
  `measure_partial_loadings` requires `factor_series_cache` as an input; the plan's step (e)
  wiring instructions build `control_series_by_name` and `instrument_full_ret` before the
  decision loop but never build or assign `factor_series_cache` itself before that point.
  **VERDICT: CONFIRMED, and more serious than "risking a NameError" -- this IS a NameError as
  specified.** Live source check: `services/tag_calibrator.py` has exactly two
  `build_factor_series_cache` call sites today (line 451, inside `_write_factor_correlations`;
  line 844, inside `execute()` but AFTER the `_apply_decision` loop, feeding only that later
  correlation-write call). `175-03-PLAN.md`'s own step (e), lines 306-329, explicitly places
  the `measure_partial_loadings(...)` call "after the existing `apply_run_level_fdr(...)` call
  and BEFORE the per-pair `_apply_decision` loop" -- i.e., before line 844 in the current file
  -- and step (e)'s own bullet list builds `control_series_by_name` and `instrument_full_ret`
  but never builds `factor_series_cache`. As written, this plan calls
  `measure_partial_loadings(kept_measurements, factor_series_by_tag, factor_series_cache, ...)`
  with `factor_series_cache` undefined at that point in the function. This blocks Wave 2
  outright if not fixed -- not a stylistic nitpick.

- **LOW -- FWL closed-form identity for incremental R^2.** `r2_full` is computed via a second
  `lstsq` solve in `175-02-PLAN.md`; by Frisch-Waugh-Lovell, `incremental_r2 ==
  partial_loading^2 * (1 - R^2_controls)`, avoiding a second solve and potential
  multicollinearity in the combined `[controls, factor]` matrix.
  **VERDICT: Plausible, not independently re-derived (would require re-deriving the FWL
  identity against this exact kernel's centering/scaling convention to confirm equivalence
  rather than just asserting it) -- a real efficiency suggestion worth the planner's
  attention, not confirmed as strictly correct or blocking.**

- **LOW -- RNG base seed absent from APR.** Plan 03 seeds the null-arm generator via
  `hash_key_to_int(f"tag_calibrator_materiality_null_{symbol}_{tag}")` with no APR-backed base
  seed component.
  **VERDICT: CONFIRMED as a real APR-mandate gap.** CLAUDE.md's APR mandate category 1 states
  explicitly: "Seeds that affect algorithm output -> APR." The per-pair seed formula is
  hardcoded with no APR key mixed in, meaning an operator cannot force re-randomization or
  test seed sensitivity without a code edit. Cheap fix (one more APR key, migration 346
  already adds ten).

### Suggestions

1. Harden `build_control_return_matrix`'s input guard (matches CONFIRMED concern above).
2. Pre-build and share `factor_series_cache` across Pass 4 and the correlation-matrix call
   (matches CONFIRMED concern above -- this is the actual fix, not optional).
3. Register `alpha.tag_calibrator.materiality.null_arm_seed` (int, default 42) and mix it into
   the per-pair seed.
4. Seed `config_history` in migration 346 for all 10 new APR keys, following migration 230's
   precedent. **VERDICT: CONFIRMED as a real gap** -- `175-01-PLAN.md`'s own `<read_first>`
   (line 132) cites migration 230's "config_schema/config_state/config_history" 3-table
   pattern as the reference, but the plan's actual Block 4 action text only instructs writing
   2 of the 3 tables. Inconsistent with the precedent the plan itself names.
5. Document that `CREATE OR REPLACE VIEW instrument_tags_active` freezes its column list at
   creation time -- a future migration adding columns to `instrument_tags` must explicitly
   recreate the view. Not independently re-verified (standard PostgreSQL behavior, no reason
   to doubt it), but a reasonable documentation addition.

### Detailed Review Criteria (AGY's own structure, condensed)

- **Statistical soundness:** Pearson convention, factor-only circular shift, and the
  sign-stability formulation are all assessed as sound (see the sign-stability divergence
  with Codex noted above).
- **APR thresholds (D-05):** `min_sample_n=756` exactly provides 3 full non-overlapping
  252-day windows to satisfy `min_sign_stable_windows=3`; the other four numeric thresholds
  are assessed as a "substantial hurdle" against common-beta noise.
- **Wave dependency topology:** assessed as clean and deterministic, matching this session's
  own independently-verified wave graph from the planning phase.

### Risk Assessment

**AGY: LOW**, citing zero consumer impact, safe/idempotent DDL, robust numerical guards
(NaN-return discipline, condition-number checks), and the pre-cutover diagnostic gate. Note
this LOW rating was given without AGY flagging its own MEDIUM concerns as blocking -- but the
factor_series_cache ordering issue, independently confirmed above to be an actual NameError
as specified, contradicts a LOW overall rating. The plan cannot execute Wave 2 as currently
written.

---

## Consensus Summary

### Agreed Strengths (both reviewers)

- Shadow-mode boundary (D-02/D-03) is airtight across all 5 plans -- independently confirmed
  by this session as well (no plan's `files_modified` touches `breadth_vol.py` or
  `cross_sectional_regime_model.py`, and both plans 03/04 carry grep-based negative
  assertions).
- Pearson convention for `partial_loading` (R-01) and the factor-only circular shift for the
  null arm (D-06) are both statistically sound design choices.
- APR threshold seeding (D-05) is honest about being `[initial_estimate]`, not corpus-derived.
- Wave/dependency topology is clean.

### Agreed Concerns

- Both reviewers independently flagged real gaps in Plan 03's `TagCalibrator` integration
  (Codex: D-01 measurement-universe scoping; AGY: `factor_series_cache` build-ordering and
  `None`-handling). Different specific findings, same plan, same severity class -- Plan 03 is
  the plan that most needs revision before execution.

### Divergent Views

- **Sign-stability window semantics.** Codex flags `decide_materiality`'s actual gate ("3 of
  3 evaluable" satisfies the condition, not strictly "3 of 4") as a real deviation from the
  design's stated intent. AGY assessed the same mechanism as sound, crediting the
  `n_evaluable`-based denominator with preventing spurious 1-of-1 passes without addressing
  whether 3-of-3 specifically is acceptable. Both are reading the same confirmed source
  behavior; the disagreement is normative (is this an intended relaxation or a gap), not
  factual. Requires an explicit planner decision, not automatic resolution.
- **Overall risk rating.** Codex: MEDIUM. AGY: LOW. Given the independently-confirmed
  `factor_series_cache` NameError-as-specified, LOW is not defensible as written -- MEDIUM
  (or HIGH specifically for Wave 2 readiness) is the accurate rating until that's fixed.

### This Session's Independent Verification Pass (beyond both reviewers)

- Codex's `breadth_vol.py` coverage concern was checked directly against source and REFUTED:
  the file has zero `instrument_tags` references and receives its universe from
  `cross_sectional_regime_model.py`'s single shared resolution path, which Plan 04 already
  reuses.
- The `factor_series_cache` ordering issue (AGY) was checked beyond "risking a NameError" to
  confirm it IS one as specified: Plan 03 step (e) never builds this variable before the point
  it's needed, and the only two existing call sites in `tag_calibrator.py` are both wrong for
  this purpose (one is inside a separate async function, the other runs after the point Pass 4
  needs the cache).
- The `config_history` gap (AGY suggestion 4) was confirmed real: Plan 01's own `<read_first>`
  names the 3-table pattern it should follow but the action text only implements 2 of 3.

## Recommendation

**Do not execute as-is.** Two CONFIRMED blocking issues in Plan 03 (D-01 measurement-universe
ambiguity; `factor_series_cache` undefined at the point it's used) and one CONFIRMED-real
lower-severity gap each in Plans 01 (`config_history`) and 03 (`None`-handling, RNG seed APR
key) need a revision pass before Wave 1 starts. The sign-stability semantics question needs an
explicit decision (not silent resolution either way).

Route back through `/gsd:plan-phase 175 --reviews` to apply these fixes, then re-run the
plan-checker before clearing the D-07 gate for real.
