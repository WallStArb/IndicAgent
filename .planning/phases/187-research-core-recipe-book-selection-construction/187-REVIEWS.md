---
phase: 187
reviewers: [codex, antigravity]
reviewed_at: 2026-10-27
code_reviewed: [c2d060c52, 4599ed3f0, f837a124f, 78acea146, 723f07e62, a23f78a49, 37181297f]
plans_reviewed: [187-08-PLAN.md, 187-09-PLAN.md, 187-10-PLAN.md, 187-11-PLAN.md, 187-12-PLAN.md, 187-13-PLAN.md, 187-14-PLAN.md, 187-15-PLAN.md, 187-16-PLAN.md, 187-17-PLAN.md, 187-18-PLAN.md]
---

# Cross-AI review: phase 187

Two passes, each by Codex (gpt-5.6-terra, read-only sandbox) and AGY, run headless on
2026-10-27: a code review of plans 03-07 as landed, and a plan review of plans 08-18 before
execution. Raw reviews follow the consensus.

## Consensus and disposition

### Code (plans 03-07)

Both reviewers agree the StepM mechanics (joint stationary bootstrap, per-draw HAC
studentization, centring, monotone step-down) match the design, and that the construction
refactor is R1-identical and pickles into workers. Both found that the selection system could not
yet support its FWER claim. Fixed:

| Finding | Reviewer | Fix |
|---|---|---|
| select_books selected over a universe missing charged runs (--disclose-missing) | Codex, AGY | 1e2d26419: a set is a result only with every series present; --diagnostic marks it unattested_set |
| a new vintage silently dropped prior attempts | Codex | 1e2d26419: charged runs on another vintage refuse |
| selection ran with no battery attestation; a partial battery printed FWER HOLDS | Codex, AGY | 1e2d26419: --battery record with complete flag and StepM code hash, checked against APR |
| adjusted p was k / reps | Codex | 1e2d26419: (k + 1) / (reps + 1) |
| synthetic mode on a real snapshot was an uncounted look | AGY | 7d8a14de2: refused except a replay of a recorded run |
| exploration then real let a searched spec take its one real run | AGY (and the internal review) | 7d8a14de2: real refused after any real-data run |
| a run failing after its statistic lost its series | AGY | 7d8a14de2: series kept |
| a draw with < 2 sessions of an attempt scored -inf (anti-conservative) | AGY | 7d8a14de2: scores +inf |
| R1 check skipped in synthetic mode; nested-book horizon recursion | AGY | 7d8a14de2 |

Open: the battery's universe is one family on one calendar with a one-session horizon; the real
universe mixes families, spans and horizons (AGY). Passing it is necessary, not sufficient; a
staggered-span cell is added with plan 08's battery work. The full 13-cell battery reruns on the
fixed code (started 2026-10-27).

### Plans 08-18

Codex rated the suite HIGH risk, AGY MEDIUM; every finding below was written into the plan's
"Review amendments" section (3c976af08 and the follow-up commit).

Agreed by both:
- Plan 13 must not publish a selection set before the gates hold, and its nightly git commit is
  a collision risk (Codex: commit through the scratch worktree with a content-hash check; AGY:
  do not commit from the timer at all). Taken: worktree commit with the hash check.
- Plan 14's subset refits need a defined recipe and lifecycle (Codex) and a bound on their
  number (AGY: 2^K). Taken: a recipe per subset through S6, failure keeps series, exact Shapley
  only under a spec-pinned cap; every refit that runs stays counted.
- Plans 16-17 cannot enforce single_writer while shared-writer exceptions exist (Codex) and the
  generated grants omit the base-class tables every service touches (AGY). Taken: no standing
  shared writers, CI write-target extraction, a generated service base role.
- Plan 18 renames break frozen-artifact loading unless class names remap too (AGY) and must
  wait for every resumable research job (Codex). Taken.

Codex only: pod inputs pinned by run_id and series hash (10); recipe code lineage read from the
attempt (11); in-transaction count check for the legacy delete (11); APR-read recording (11);
recipes seeded through S6 (12); kernel-registry feature universe (12); point-in-time sectors and
a runnable synthetic path (15); session-calendar refits (09); stricter battery tails (08).

AGY only: horizon smoothing must update has_position or partial adjustment is masked (08);
top-level optional fields need a root _drop_unset or every hash moves (08, 15); CombinerSpec's
validator rejects in-fold fields (09); ridge forecast shrinkage with missing members (09); pod
evidence must match ledger._headline (10); stage view precedence for reopened ideas (11).

### Divergent views and owner decision

- Plan 09's in-fold signs: Codex calls the trailing window an unauthorized change from design
  4.2's expanding IC. Design 4.5's memory rule makes an expanding fold's reach the whole history,
  so E17 could not score it; the two adopted sections conflict. Kept trailing, recorded in the
  methodology-change ledger, and flagged for the owner: if the owner rules for expanding, in-fold
  signs ship refused under E17.
- Plan 14's Shapley: AGY proposed making Shapley a non-counted diagnostic; the design counts
  diagnostic subset refits (E18), so the cap bounds the count instead.


## Codex: code review (plans 03-07)

1. **HIGH** — [select_books.py:112](/home/bg/dev/indicagent/scripts/research/select_books.py:112)  
   `--disclose-missing` explicitly permits StepM to run after removing charged attempts whose D_s series is absent. For example, a failed/interrupted run or unreplayable pre-515 attempt that was seen can be omitted by passing the flag; its potentially favorable result is then absent from the max-t distribution. The printed set looks valid but does not control FWER over the stated universe.  
   Suggested fix: never produce a selection set while any charged attempt lacks a series. Print the gaps and exit nonzero; require an explicit terminal disposition that is itself conservative, or complete/reproduce the series.

2. **HIGH** — [select_books.py:50](/home/bg/dev/indicagent/scripts/research/select_books.py:50)  
   The query filters strictly to `r.vintage = $1`. On a vintage extension, changing `alpha.research.vintage_id` and running new attempts yields a selection universe containing only those new rows, silently dropping every previous attempt. This directly contradicts design §8 / E18’s “re-evaluate prior attempts; count does not reset” requirement.  
   Suggested fix: model a vintage lineage and refuse selection until every prior charged attempt has been re-evaluated onto the extended vintage; query that complete re-evaluated universe rather than only rows initially stamped with the current ID.

3. **HIGH** — [select_books.py:108](/home/bg/dev/indicagent/scripts/research/select_books.py:108)  
   Selection is executable now despite the documented incomplete per-draw H0 battery. The battery document says the full 13-cell run must pass before selection is enabled, but `select_books.py` has no gate or evidence lookup; it will print a StepM selection set using the APR keys immediately. The battery driver’s success result is merely a local JSON output, and even a `--cells` subset can print “FWER HOLDS.”  
   Suggested fix: make selection refuse unless a complete, immutable battery attestation matches the StepM code hash, parameters, studentization, scenarios, and required gating cells. Have the battery driver reject partial runs as a passing attestation.

4. **LOW** — [stepm.py:125](/home/bg/dev/indicagent/src/intelligence/statistics/stepm.py:125)  
   Bootstrap adjusted p-values use `count / reps`, with no finite-resample correction. At 2,000 draws, a rejection can occur at an extra attainable Monte-Carlo rank compared with the conservative `(count + 1) / (reps + 1)` calculation. Thus the strict “FWER at 0.05” claim is slightly anti-conservative even if the bootstrap model is otherwise correct.  
   Suggested fix: use the plus-one correction before monotonic step-down adjustment and rerun the battery under the exact production calculation.

I found no additional construction-refactor finding: R1 delegates to the prior R1 functions, the rule objects are ordinary top-level frozen dataclasses and pickle safely, and the runner refuses every non-R1 construction before ledger/data work ([runner.py:297](/home/bg/dev/indicagent/src/intelligence/research/runner.py:297)). Exploration is counted when its series persists; it does not itself provide a book-test confirmation route.

Overall verdict: the StepM implementation’s core resampling/studentization mechanics are aligned with the design, but the selection system currently cannot support the claimed FWER guarantee because it can knowingly exclude counted attempts, reset the universe at a vintage roll, and run before its required validation battery passes. These are release-blocking correctness issues for E18 selection.

---

## AGY: code review (plans 03-07)

### Phase 187 Codebase Review

**Scope of Review:** Commits `c2d060c52` (187-04), `4599ed3f0` (187-05), `f837a124f` and `78acea146` (187-03, 187-07), `723f07e62` (187-06), `a23f78a49` and `37181297f` (187-07), evaluated against `CLAUDE.md`, `docs/plans/2026-09-26-unified-research-to-production-design.md` (§7.1–§7.4), and methodology ledger entries E17 & E18.

---

### Numbered Findings

#### 1. Uncounted Look on Real Vintage Data via Price-Only Synthetic Mode
- **Severity:** HIGH
- **Location:** [src/intelligence/research/runner.py:370-375](file:///home/bg/dev/indicagent/src/intelligence/research/runner.py#L370-L375)
- **Concrete Failure Scenario:** A researcher can execute an uncounted look on real vintage market data without generating a ledger entry or recording an attempt. In [`_analysis_panel`](file:///home/bg/dev/indicagent/src/intelligence/research/runner.py#L360-L376), the safety check verifying that a real S0 snapshot is not fed into synthetic mode (`if panel.manifest.get("source") == snapshot.PRICE_SOURCE: raise ValueError(...)`) is nested inside `if spec.panel.total_return is not None:`. For price-only specs (such as Family 1 intraday periodicity, where `total_return` is `None`), this guard is bypassed. Running `scripts/research/run_spec.py --mode synthetic --spec research/specs/family1_h26.yaml --panel logs/research/snapshots/panel_<hash>` executes the full pipeline on real data and prints statistics to stdout, completely uncounted by the ledger.
- **Suggested Fix:** Unconditionally check for real snapshots in synthetic mode regardless of `total_return`:
  ```python
  if panel.manifest.get("source") == snapshot.PRICE_SOURCE:
      raise ValueError("a real S0 snapshot cannot run in synthetic mode")
  ```

---

#### 2. Re-running an Explored Spec in "Real" Mode Allows Confirmation on an Already-Searched Spec
- **Severity:** HIGH
- **Location:** [src/intelligence/research/ledger.py:203-210](file:///home/bg/dev/indicagent/src/intelligence/research/ledger.py#L203-L210) and [src/intelligence/research/runner.py:292](file:///home/bg/dev/indicagent/src/intelligence/research/runner.py#L292)
- **Concrete Failure Scenario:** In [`start_runs`](file:///home/bg/dev/indicagent/src/intelligence/research/ledger.py#L184-L265) and [`_gate`](file:///home/bg/dev/indicagent/src/intelligence/research/runner.py#L280-L295), duplicate check queries explicitly filter on `WHERE spec_hash = $1 AND mode = 'real'`. When a researcher runs a spec in `--mode exploration`, the run is executed on real data, recorded in `research_run` with `mode = 'exploration'`, and stored in `research_run_series`. If the outcome is favorable, the researcher can re-run the identical spec under `--mode real`. Because no row with `mode = 'real'` exists yet, the runner accepts it, allowing a spec searched during exploration to masquerade as an un-looked "run-once" commitment. Both rows are then stored in the DB, duplicating identical return series in `select_books.py`.
- **Suggested Fix:** In [`ledger.py`](file:///home/bg/dev/indicagent/src/intelligence/research/ledger.py#L203-L210) and [`has_real_run`](file:///home/bg/dev/indicagent/src/intelligence/research/ledger.py#L152-L162), refuse `mode = 'real'` if the spec hash has been executed in any real-data mode:
  ```sql
  SELECT EXISTS (SELECT 1 FROM research_run WHERE spec_hash = $1 AND mode IN ('real', 'exploration'))
  ```

---

#### 3. Failed Runs That Computed Statistics Discard Their Return Series
- **Severity:** HIGH
- **Location:** [src/intelligence/research/runner.py:657-666](file:///home/bg/dev/indicagent/src/intelligence/research/runner.py#L657-L666) and [src/intelligence/research/runner.py:1014-1022](file:///home/bg/dev/indicagent/src/intelligence/research/runner.py#L1014-L1022)
- **Concrete Failure Scenario:** Unified design §7.1 dictates: *"A run that computed a statistic and then ended failed still counts."* Migration 515 and `ledger.py` added `SERIES_STATUSES = ("completed", "failed")` specifically to store series for failed runs. However, in both [`run_family`](file:///home/bg/dev/indicagent/src/intelligence/research/runner.py#L500-L667) and [`run_book`](file:///home/bg/dev/indicagent/src/intelligence/research/runner.py#L792-L1022), the `except Exception:` handlers call `finish_all("failed", ...)` and `finish("failed", ...)` without passing `series`. If an exception occurs after `timing_test` or `book_timing` has already completed (e.g. during `_shift_diagnostic`, `evidence_record`, serialization, or disk writes), the run is updated to `status = 'failed'`, but no series is written to `research_run_series`. In `select_books.py`, this run is charged but has `sessions IS NULL`, permanently failing the completeness gate or being omitted in diagnostic mode, introducing hidden search bias.
- **Suggested Fix:** Retain the computed `AttemptSeries` across the timing block and pass `series=series` to `finish`/`finish_all` inside the exception handler if it is non-null.

---

#### 4. The Null Battery Does Not Empirically or Structurally Prove Selection FWER Control Over the Stated Universe
- **Severity:** HIGH
- **Location:** [.planning/phases/187-research-core-recipe-book-selection-construction/187-05-BATTERY.md:40-45](file:///home/bg/dev/indicagent/.planning/phases/187-research-core-recipe-book-selection-construction/187-05-BATTERY.md#L40-L45) and [scripts/research/stepm_null_battery.py:86-90](file:///home/bg/dev/indicagent/scripts/research/stepm_null_battery.py#L86-L90)
- **Concrete Failure Scenario:** 
  1. *Incomplete Battery Execution:* As documented in `187-05-BATTERY.md`, the full 13-cell battery under the adopted `studentize="draw"` default has never completed (only 3 of 10 gating cells were run in `logs/research/stepm_null_battery_draw_probe_20261026.json`). Pass 1 (`studentize="sample"`) failed in `slot_effects` (74/67 rejections). Selection FWER $\le 0.05$ across all gating cells remains unproven.
  2. *Universe Mismatch:* The battery tests an idealized universe of 5 arms from a single family sharing identical session dates ($S=1250$, no missing sessions, no late listings across arms) and a 1-session holding horizon. In reality, the selection universe contains multiple families, varying session spans (e.g. 2006 vs 2010 starts with interspersed NaNs), different holding horizons, and causal walk-forward ridge combiners.
- **Suggested Fix:** Run and record the complete 13-cell battery under `studentize="draw"`, and add a benchmark scenario in `null_battery.py` containing staggered session spans and walk-forward ridge books.

---

#### 5. Short or Sparse Session Spans Deflate StepM Adjusted P-Values via `-inf` Draws
- **Severity:** MEDIUM
- **Location:** [src/intelligence/statistics/stepm.py:106-116](file:///home/bg/dev/indicagent/src/intelligence/statistics/stepm.py#L106-L116)
- **Concrete Failure Scenario:** In `_draw_t`, when a stationary bootstrap draw contains fewer than 2 finite observations for an attempt (`len(finite) < 2`), or when `hac_mean_test` encounters non-positive variance, it returns `-np.inf`. If an attempt in the universe was tested on very few sessions relative to the calendar length $S$ (e.g. fewer than 60 sessions), a non-trivial fraction of bootstrap draws will sample $< 2$ finite sessions. Those draws are forced to $-\infty$, depressing the bootstrap distribution of the active maximum. Consequently, $P(\max t^* \ge t_{obs})$ is deflated by the probability of drawing $< 2$ points, artificially lowering the adjusted p-value and creating an anti-conservative bias for short-lived attempts.
- **Suggested Fix:** In [`select_books.py`](file:///home/bg/dev/indicagent/scripts/research/select_books.py) and [`stepm.py`](file:///home/bg/dev/indicagent/src/intelligence/statistics/stepm.py), enforce a minimum finite session threshold (e.g. $N_k \ge 60$ sessions, matching the E17 memory threshold) before an attempt is admitted into the StepM selection matrix.

---

#### 6. `--diagnostic` Flag Emits Selection Set While Completeness Gate Fails
- **Severity:** MEDIUM
- **Location:** [scripts/research/select_books.py:168-172](file:///home/bg/dev/indicagent/scripts/research/select_books.py#L168-L172)
- **Concrete Failure Scenario:** In commit `723f07e62`, `--disclose-missing` silently excluded charged runs with missing series from the StepM test matrix. While commit `1e2d26419` replaced this with `--diagnostic` and an exit code of 3, the script still prints the full JSON payload containing `"selection_set": [...]` alongside `"result": false`. Any automated consumer, dashboard, or pipeline parsing stdout without checking exit codes or `"result": true` will consume an invalid selection set computed over an incomplete universe.
- **Suggested Fix:** In `select_books.py`, when `refusals` is non-empty under `--diagnostic`, either set `"selection_set": []` or rename the key to `"unattested_diagnostic_set"`.

---

#### 7. Synthetic Mode Bypasses Construction Rule Discovery Check
- **Severity:** LOW
- **Location:** [src/intelligence/research/runner.py:539](file:///home/bg/dev/indicagent/src/intelligence/research/runner.py#L539) and [src/intelligence/research/runner.py:835](file:///home/bg/dev/indicagent/src/intelligence/research/runner.py#L835)
- **Concrete Failure Scenario:** [`_check_spec_tree`](file:///home/bg/dev/indicagent/src/intelligence/research/runner.py#L297-L317) enforces that only R1 (`rank_vol_neutral`) is permitted during discovery. However, `_check_spec_tree` is only called inside `_gate` (real and exploration modes). In synthetic mode (`run_family` line 539 and `run_book` line 835), `_gate` is skipped and only `_check_spec` is called. If a spec declares a non-R1 rule (e.g. `mean_variance` or `fixed_sign`), synthetic mode starts executing S1 and S2 computation before loudly failing with `ValueError: construction <name> sizes from a covariance plan; none was given` in `_require_plan`.
- **Suggested Fix:** Invoke `_check_spec_tree(loaded)` in synthetic mode in both `run_family` and `run_book` prior to panel preparation and residual computation.

---

#### 8. Recursive Horizon Calculation Crashes on Nested Book Specs
- **Severity:** LOW
- **Location:** [scripts/research/select_books.py:75-80](file:///home/bg/dev/indicagent/scripts/research/select_books.py#L75-L80)
- **Concrete Failure Scenario:** In [`horizon_sessions`](file:///home/bg/dev/indicagent/scripts/research/select_books.py#L126-L132), when `model` is a `BookSpec`, it recurses over `model.families`:
  ```python
  return max(horizon_sessions(family_text_at(path), None) for path in model.families)
  ```
  It passes `None` as the `family_text_at` callable. If a book references another book spec (such as future pod books or composite books), the recursive call attempts `family_text_at(path)` when `family_text_at` is `None`, raising `TypeError: 'NoneType' object is not callable`.
- **Suggested Fix:** Forward `family_text_at` in the recursive call:
  ```python
  return max(horizon_sessions(family_text_at(path), family_text_at) for path in model.families)
  ```

---

### Overall Verdict

The statistical engine of Romano-Wolf StepM (`stepm.py`) is mathematically rigorous: the joint stationary bootstrap preserves cross-sectional correlations, per-draw HAC studentization corrects the sample-scaling distortion observed under H0 in `slot_effects`, centring around sample means is unbiased despite varying session calendars, and step-down p-values are strictly monotonic. The ConstructionRule protocol preserves R1 bit-identical determinism and pickles cleanly into worker processes. However, the selection framework currently carries structural integrity vulnerabilities: price-only specs can be evaluated uncounted in synthetic mode on real S0 snapshots, specs evaluated in exploration mode can be re-run under real mode without gate refusal, runs failing after the timing stage lose their return series, and empirical FWER control over the full 13-cell battery remains incomplete and unproven on staggered session calendars. Addressing the prior-run gate, exception series handling, and completing the battery are necessary before selection sets can be relied upon as valid research results.

---

## Codex: plan review (08-18)

## Overall assessment

The plans are unusually rigorous about parity, spec-hash preservation, S6 ownership, and E17 validation. They build logically on 01–07: migration 515 exists, S6 already writes terminal series, E18 is code-complete but gated by the unfinished battery/backfill, and 07 added no spec fields while `resolve_rule` requires `bars_per_session`. However, several plans can still create unreproducible or silently changing attempts, and the platform plans weaken rather than enforce single-writer ownership through exceptions. Overall risk: **HIGH** until the issues below are corrected.

### 187-08 — Horizon rule and book memory

**Summary:** Strong plan with the right causal structure and explicit identity/parity requirements. It correctly treats kappa as part of the tested construction, but its battery gate is under-specified.

**Strengths**

- Preserves existing hashes through an optional book field.
- Centralizes memory in `book_memory()` and routes runner/power/diagnostic use through it.
- Treats the `1e-3` reach threshold as a definition rather than a tunable.
- Requires a behavior-change ledger entry for ridge-memory correction.

**Concerns**

- **MEDIUM — Task 2:** The acceptance criterion only gates size at 0.05. E17 has decision bars below that, including the historical 0.00167 screen/power context. A kappa/ridge cell can pass 0.05 yet be materially oversized at the tail actually used for evidence.
- **MEDIUM — Task 3:** Validated-combination status is encoded as a source constant based on a markdown report. That can drift from the report or be bypassed by a new combination without a structured, machine-checked battery verdict.
- **LOW — Task 1:** `HorizonRule(1.0).apply` returning the input object makes identity fast, but callers must not mutate the returned target weights later; otherwise aliasing becomes a silent behavior difference.

**Suggestions**

- Require pass/fail limits at every decision alpha used by E17, with a machine-readable battery artifact keyed by combiner/kappa settings.
- Make the loader validate against that artifact, not a handwritten allow-list.
- Test that horizon smoothing resets or carries positions exactly as intended across missing rows, symbol exits, and panel boundaries.

**Risk assessment:** **MEDIUM.** The core approach is sound, but the H0 gate needs to be as strict as the statistic it enables.

### 187-09 — Missing members, signs, calendar refits

**Summary:** Missing-member handling is well-scoped, but the proposed sign rule materially departs from the adopted design, and the calendar rule is not tied to the actual trading calendar.

**Strengths**

- Correctly distinguishes combining available observations from filling missing inputs.
- Keeps unset fields byte-identical.
- Adds coverage evidence only when the new rule is active.
- Separates behavior changes into commits.

**Concerns**

- **HIGH — Task 3 / objective:** The governing design requires an **expanding** training-fold IC for prior-less-family equal weighting. The plan substitutes a trailing window because expanding memory is inconvenient for E17. A methodology-ledger note is not authorization to change the adopted rule; it changes the estimator and can change measured results.
- **HIGH — Task 2:** `np.busday_count` is a weekday calendar, not the instrument/session calendar. It will schedule refits on exchange holidays and does not establish a single canonical calendar across asset classes or special sessions. “Map to next panel session” changes the declared cadence and can differ by panel.
- **MEDIUM — Task 2 tests:** The expectation that two truncated panels yield identical overlapping ridge predictions is generally false: their available training histories differ. This risks validating a property the implementation cannot honestly provide.
- **MEDIUM — Task 3:** In-fold-sign training reach is described in sessions but interfaces are largely row based. The plan needs an explicit conversion and embargo policy for intraday panels, missing sessions, and nonuniform bars.

**Suggestions**

- Obtain an explicit design/owner decision before replacing expanding signs with trailing signs; otherwise implement expanding signs with an E17-compatible declared reach/refusal rule.
- Use the panel’s canonical session-date sequence or exchange calendar, not NumPy business days.
- Replace the overlap-equality test with a calendar-grid test: equal refit dates when comparable history is available, and explicit divergence when history differs.

**Risk assessment:** **HIGH.** This plan currently changes a pinned methodological rule without a governing-design amendment.

### 187-10 — Pod books

**Summary:** Correctly avoids cross-clock forecast combination and preserves no-fill behavior, but it does not pin the member attempts that form the pod.

**Strengths**

- Uses stored E17 `D_s`, not recomputed component results.
- Intersects finite sessions and refuses an empty intersection.
- Records a separate `pod_book` attempt through S6.
- Avoids authoring or running an unregistered real-vintage pod.

**Concerns**

- **HIGH — Task 2:** `completed_series(spec_hash, vintage)` selects the “latest completed” run. A later exploration rerun with the same spec hash can silently change a pod’s inputs while leaving the pod spec hash unchanged. This breaks determinism, lineage, and can enable outcome-driven member-run selection.
- **HIGH — Task 2:** The pod’s member run IDs/snapshot hashes are placed only in evidence after selection, not frozen in its recipe/spec before `start_runs`. `informed_by` is also not used to capture the parent attempts.
- **MEDIUM — Task 2:** “Power inherited” needs an explicit check that each referenced member attempt passed the applicable pre-statistic/power gate; merely being completed is insufficient.

**Suggestions**

- Require pod specs or the pod recipe to pin exact member `run_id`, `snapshot_hash`, and member-series hash; reject a pod if any pin is absent or terminal status is unsuitable.
- Set `informed_by` to the declared member attempts where the schema permits, or add a normalized parent-attempt relation rather than relying on evidence JSON.
- Treat rerunning the same member definition as a distinct selectable input unless explicitly pinned.

**Risk assessment:** **HIGH.** “Latest completed” makes a supposedly frozen attempt mutable.

### 187-11 — Typed UCR domains, recipes, stages

**Summary:** This is central to the phase and has a good S6 direction, but recipe hashing and destructive migration handling need revision.

**Strengths**

- Converts identity domains to the required typed model.
- Uses transactional S6 insertion under the ledger lock.
- Preserves old runs by leaving their `recipe_hash` NULL.
- Makes research stage derived rather than stored.
- Adds FK-index verification.

**Concerns**

- **HIGH — Task 2:** `recipe_hash` excludes `code_commit`, yet `concept_recipe` stores one code commit and attempts only reference the hash. A definition rerun at a later commit reuses the old recipe row and falsely claims the earlier code lineage. This violates the requirement that an output trace to its recipe and code.
- **HIGH — Task 1:** The migration deletes `ensemble_strategy` rows and dependent history after a separate pre-check/dump. That is non-atomic on a shared live DB; state can change between the dump/count and deletion. It also conflicts with the UCR principle that historical concepts are records unless the governing design explicitly authorizes a retained tombstone/archive representation.
- **MEDIUM — Task 1:** Applying to `indicagent_test` is assumed reliable despite 01’s documented migration-harness history. The plan should include a fallback contract/live rolled-back proof rather than treating it as unconditional.
- **MEDIUM — Task 2:** Recipe contents include “APR keys the run reads,” but there is no explicit fail-closed inventory proving all runtime APR reads were captured at run start. An omitted key yields a plausible but incomplete recipe.

**Suggestions**

- Include a code-content key/commit in the recipe identity, or add an immutable per-run code key column and populate it at insert; do not let a later execution inherit an older recipe’s commit.
- Make deletion a separately approved, locked archival migration: transactionally copy all rows to retained archive/tombstone tables, assert exact counts/foreign-key closure, then retire active rows.
- Require a tested, declared APR-read manifest from the execution context and fail if an observed lookup lacks a pinned value.

**Risk assessment:** **HIGH.** Current recipe identity can misstate the code that generated a recorded attempt.

### 187-12 — Registry service, composition, HMM recipes

**Summary:** The identity/idea workflow is sensible, but the migration proposes an ungoverned exception to S6 recipe ownership and has broad feature-registration scope.

**Strengths**

- Keeps status transitions in `ConceptRegistryService`.
- Gives ideas a concrete, early registration path.
- Replaces stale tier taxonomy with the simpler composition distinction.
- Explicitly avoids touching feature-writing code.

**Concerns**

- **HIGH — Task 2:** The migration inserts `concept_recipe` rows directly while the phase’s sole-writer rule and existing writer test designate S6 as the recipe writer. Calling this a seed exception needs an explicit, tested policy; otherwise single-writer enforcement has a hole precisely in the recipe table.
- **MEDIUM — Task 2:** “Every numeric `feature_vectors` column” is broader than “feature” and relies on an executor-maintained exclusion list. Derived targets, flags, keys, or implementation columns can be silently misclassified as research concepts.
- **MEDIUM — Task 2:** The HMM recipe’s code pointer is decided at execution from a function name, and the commit is read dynamically. The migration must pin exact literals and assert the expected column set, not construct lineage from a changing working tree.

**Suggestions**

- Either route HMM recipe creation through a one-shot S6 seed command, or amend the sole-writer contract to permit explicitly named migrations and test that exception.
- Define the feature-column universe from the kernel registry/feature schema, not generic numeric SQL types.
- Require pre/post assertions for the exact expected missing HMM columns and exact seeded recipe hashes.

**Risk assessment:** **MEDIUM.** It is recoverable, but recipe ownership and column classification must be made fail-closed.

### 187-13 — Legacy import and generated ledger

**Summary:** The records/import direction is good, but the renderer must not publish an apparent selection result before the StepM and series gates are complete.

**Strengths**

- Imports cards through S6 and makes import idempotent.
- Keeps legacy verdicts excluded from selection and unrecomputed.
- Preserves the hand ledger for anchor stability.
- Makes generated output deterministic and narrowly scoped to one file.

**Concerns**

- **HIGH — Task 3:** The renderer computes a selection set from `select_books`, while 05’s full battery and 03’s full backfill remain incomplete. Unless it explicitly renders “selection disabled/not a result,” it can create a visible, misleading selection set from an unvalidated test or missing series.
- **MEDIUM — Task 3:** A nightly systemd job committing into the shared working tree can collide with active work or commit an unexpected version of `research-ledger.md`. A one-path `git commit` limits staging but does not provide repository locking or a clean-tree policy.
- **LOW — Task 2:** Automatically logging ambiguous hand-ledger text as ideas avoids loss, but should mark the provenance/parse confidence so an opaque raw bullet is not mistaken for a well-specified idea.

**Suggestions**

- Make renderer selection status a hard gate: battery PASS and no undisclosed missing charged series, otherwise render only a refusal/disclosure block.
- Use a repo lock and require the target file’s expected content/hash immediately before commit; skip and alert on conflicts.
- Add `import_confidence`/raw-anchor metadata for ambiguous ideas.

**Risk assessment:** **HIGH.** Publishing a premature selection set would undermine E18’s central safeguard.

### 187-14 — Contribution accounting

**Summary:** It covers the roadmap’s contribution requirements well, but its counted subset-refit design is not compatible with the post-11 recipe schema as written.

**Strengths**

- Separates additive attribution from marginal necessity.
- Requires exact accounting identities and pure kernels.
- Correctly keeps diagnostics from changing admission or weights.
- Counts visible subset refits and includes them in selection.
- Uses typed terminal headline fields.

**Concerns**

- **HIGH — Task 2/3:** Subset refits receive `spec_hash = sha256(book spec_hash + subset)`, but after 11 every `research_run.recipe_hash` must reference an actual immutable `concept_recipe`. The plan does not create a subset concept/recipe or specify which recipe hash is inserted. This is either an FK failure or an untracked lineage gap.
- **MEDIUM — Task 3:** It does not specify failure semantics for a subset computation. A worker exception must create a terminal failed counted attempt if a statistic was produced, and must not leave a started row that later becomes silently omitted.
- **MEDIUM — Task 1:** Accounting groups based on a recipe code-pointer module are too coarse for generated-family primitive/operator branches, despite the governing design naming those branches as the primary grouping.

**Suggestions**

- Create immutable subset-refit recipe records before child attempts, keyed by parent recipe plus canonical subset and accounting method; link them to a dedicated method/book-child concept.
- Specify transactional parent/child lifecycle behavior and explicit failure recording.
- Add a first-class generated-member origin field to recipe content and use it for group construction.

**Risk assessment:** **HIGH.** The plan conflicts with its own recipe/attempt lineage model.

### 187-15 — `generated_family` grammar

**Summary:** The pure grammar and optional S0 fields are well conceived, but the plan stops short of making a generated family runnable, and PIT sector inputs need stronger guarantees.

**Strengths**

- Uses deterministic canonical enumeration and block-wise computation.
- Derives memory and requires causality checks.
- Preserves existing snapshots and hashes with optional fields.
- Explicitly avoids materializing the full candidate library.

**Concerns**

- **HIGH — Task 3:** The plan says runner wiring is outside scope, yet its success criterion says a generated-family spec “loads, enumerates, and records as one recipe.” A spec that cannot pass through the runner cannot be recorded as an attempt or satisfy R-187-20 in practice.
- **HIGH — Task 2:** The sector lookup must use classification as known/valid at each session, with an immutable code mapping saved in the snapshot. Referring generically to `current_level_name_sql()`/a service does not prove availability-time point-in-time behavior.
- **MEDIUM — Task 1:** The memory formula for nested rolling operators is asserted rather than specified recursively. Underestimating it creates an uncounted E17 coupling and is worse than a loud refusal.

**Suggestions**

- Include a minimal synthetic runner path that executes a generated-family block stream, runs S3 sample checks, and records a synthetic attempt/recipe without adding the later in-fold selector.
- Define and test the exact classification as-of query, snapshot the sector-code dictionary, and refuse absent or ambiguous historical classifications.
- Make memory derivation structural over the expression tree and validate it against `memory_check_array` across generated random expressions.

**Risk assessment:** **HIGH.** As planned, the feature is mostly a parser/library rather than supported research functionality.

### 187-16 — DAG manifest

**Summary:** A manifest is the right consolidation, but exceptions and incomplete writer discovery make its single-writer guarantee unreliable.

**Strengths**

- Moves ordering and unit metadata into a single checked-in source.
- Keeps the loader in Ring 0.
- Checks cycles, timers, auditor ownership, and migration-time equivalence.
- Sensibly avoids editing the corpus script during a running corpus job.

**Concerns**

- **HIGH — Task 1:** `shared_writer_exceptions` directly weakens the stated invariant that one writer owns each table. It can convert current violations into permanent manifest allowances, then plan 17 grants both writers. This does not “enforce” single writer.
- **HIGH — Task 1:** CI validates the manifest against itself but does not prove that every actual SQL/COPY writer is declared. A grep used to create the initial file is not a durable boundary check; new undeclared writes can pass CI.
- **MEDIUM — Task 1:** Table-level edges alone may not reflect external/state dependencies (Kafka, local checkpoints, timers, or DB functions), so acyclicity claims need to be scoped explicitly as table-DAG claims.
- **MEDIUM — Task 3:** `batch-order` needs deterministic tie-breaking and a declared dependency edge model. Restart priority is not a topological dependency relation.

**Suggestions**

- Treat multiple writers as a blocking remediation item, not an allowed steady-state exception. If a transitional exception is unavoidable, make it time-bounded, deny simultaneous operation, and prevent plan 17 from granting concurrent writes.
- Add CI extraction/fencing for SQL write targets and require an exact manifest declaration for each target.
- Separate restart priority from DAG edges and require stable lexical tie-breaking for independent batch nodes.

**Risk assessment:** **HIGH.** This plan is foundational to both the DAG and database-role guarantees.

### 187-17 — Per-writer database roles

**Summary:** The staged rollout is prudent, but it inherits the manifest’s ownership weakness and needs stronger privilege/reconciliation controls.

**Strengths**

- Uses generated grants, a pre-apply diff, and incremental health-gated rollout.
- Keeps credentials outside git.
- Provides a simple per-unit rollback.
- Defers fingerprinted/active lanes rather than restarting them casually.

**Concerns**

- **HIGH — Task 1/2:** Manifest shared-writer exceptions give multiple login roles write grants to the same table, so this cannot enforce the required single-writer boundary.
- **MEDIUM — Task 1:** The diff must account for privileges inherited through role membership, PUBLIC, function execution, sequences, schemas, and default privileges. Comparing only table/column/sequence grants can falsely report least privilege while effective access remains broader.
- **MEDIUM — Task 3:** “Every service” is not operationally achievable under the stated defer-if-active policy without a durable rollout ledger and a required completion gate. A summary/todo alone risks leaving `postgres` as a long-lived service identity.
- **LOW — Task 2:** Dropping a role after a point-in-time check for ownership/sessions needs a lock/recheck immediately before `DROP ROLE`.

**Suggestions**

- Block rollout until plan 16 has no concurrent shared writers.
- Make effective privilege evaluation part of `--diff`, including inherited/PUBLIC grants and executable functions.
- Persist deferred nodes in a checked status artifact and fail phase completion until all have migrated or an explicitly approved exception exists.

**Risk assessment:** **HIGH.** The intended enforcement cannot hold while shared table writers remain.

### 187-18 — Research split and Predictor rename

**Summary:** The sequencing intent is right and the frozen-artifact compatibility thought is good, but its declared dependencies do not capture the active/restart-sensitive research work.

**Strengths**

- Keeps YAML `signal` fields stable, preventing recorded spec-hash movement.
- Separates structural split from semantic rename.
- Preserves old import surface.
- Requires frozen replay, parity, and glossary ratchet checks.

**Concerns**

- **HIGH — Task 1/2:** `depends_on: [14, 15]` omits plan 10’s pod path and, more importantly, the external family-2 evidence, pending backfill 03, and pending StepM battery 05. The text mentions family 2/battery, but the plan must be blocked until all fingerprinted or resumable research jobs are finished or intentionally discarded.
- **MEDIUM — Task 1:** Moving `runner.py` to a package changes module paths used by monkeypatches, frozen pickles, imports, and potentially code-content keys. A module-renaming map only in `repro_frozen` is insufficient if other operational loaders import recorded paths.
- **LOW — Task 2:** The design calls the protocol `PredictorSource` while the plan chooses `Predictor`. That may be a valid glossary decision, but it should be resolved explicitly rather than silently diverging from the governing text.

**Suggestions**

- Make all active/restart-sensitive research jobs explicit hard dependencies, with a preflight proving none is live or resumable.
- Add a repository-wide import and serialized-artifact compatibility test beyond `repro_frozen`.
- Record the final glossary/design naming decision for `Predictor` versus `PredictorSource`.

**Risk assessment:** **MEDIUM.** It is a refactor, but only safe after the pending evidence work has conclusively ended.

## Do the plans achieve the roadmap goal?

**Not yet.** Plans 08–15 cover most research-core requirements in principle, and 16–18 address platform enforcement/refactoring. But the phase goal is not achieved unless the plans are amended to:

1. Pin pod and subset-refit inputs/recipes immutably.
2. Preserve correct code/APR lineage per attempt.
3. Keep StepM selection unpublished until the full H0 battery and all counted-series disclosures are complete.
4. Enforce one writer rather than institutionalize shared-writer exceptions.
5. Make generated families executable through a controlled runner path.
6. Resolve the expanding-versus-trailing in-fold-sign design conflict through an explicit governing decision.

---

## AGY: plan review (08-18)

# Cross-AI Plan Review: Phase 187 (Research Core: Plans 08–18)

## 1. Summary

Plans 187-08 through 187-18 complete Track C of the Unified Research-to-Production Design by delivering the four-part book specification (construction rule, horizon rule, combining rules), pod books across disparate clocks, the clean UCR recipe book and research-stage tracking, contribution accounting, hypothesis-free grammar generation, a Ring 0 YAML DAG manifest with single-writer CI enforcement, and per-writer database roles. The design exhibits outstanding statistical discipline—adhering strictly to pre-registration invariants, bit-identical determinism (`repro_frozen`), and error control via Romano-Wolf StepM under E18 without outcome-snooped threshold adjustments. However, the plan suite carries three critical implementation risks: (1) an architectural mismatch between `HorizonRule.apply` and `timing_series` where decaying positions on un-targeted rows will be silently zeroed out by `has_position`; (2) spec-hash instability where adding top-level optional fields (`horizon_rule`, `generated`) to `BookSpec` and `FamilySpec` bypasses section-scoped `_drop_unset` and moves recorded spec hashes; and (3) an explosive combinatorial explosion in Plan 14 where exact Shapley subset refits write up to $2^K$ ($4{,}096$) series to `research_run_series`, threatening to choke Romano-Wolf StepM and flood TimescaleDB. Addressing these specific traps before execution will make the phase robust, scalable, and safe for live capital research.

---

## 2. Strengths

- **Strict Adherence to E17/E18 Invariants:** Plans preserve the core evidence framework established in E15–E18. Uncapped exploration is paired with Romano-Wolf StepM selection over all observed series, while promotion is strictly gated on net expectation without contaminating the gross test statistic.
- **Spec Hash Immobility:** Plans 08, 09, 10, 15, and 18 explicitly guard canonical spec hashes against mutation by leveraging optional fields, keeping historical keys (`MemberSpec.signal`), and verifying immutability against `tests/unit/research/test_spec_hashes_pinned.py` and `--compare-all`.
- **Clean Component Isolation (Musk Step 2/3):** Plan 11 eliminates the deprecated `ensemble_strategy` domain and cleans up legacy UCR residues; Plan 12 retires the arbitrary 3-tier taxonomy (`0_atomic`, `1_interaction`, `2_theory`) in favor of a clean binary `composition` (`base` vs. `interaction`), cataloging all 11 unmapped HMM columns; Plan 16 deletes hand-maintained topology dicts (`_DAG_ORDER`, `_AGENT_ID_TO_UNIT`) in favor of a single YAML manifest.
- **Principled Multi-Clock Pod Books (Plan 10):** Restricts cross-timeframe aggregation strictly to the P&L level on session intersections, preventing synthetic-fill leakage across incompatible clocks (e.g., 15m intraday vs. session legs).
- **Comprehensive Defense-in-Depth for `single_writer` (Plans 16 & 17):** Transitions single-writer verification from passive code audits to static CI DAG checks, and ultimately to PostgreSQL role-level privilege boundaries where daemons physically lack write grants on foreign tables.
- **Fail-Loud Architectural Gates:** Plan 08 requires H0 battery cells to hold empirical size before allowing book specs with ridge or $\kappa < 1$ to load in real/exploration mode, ensuring unproven combinations fail loudly at startup.

---

## 3. Concerns

### HIGH Severity

1. **`has_position` Contract Mismatch Silently Wipes Decaying Horizon Positions**
   - **Plan & Task:** [187-08 Task 1 & Task 3](file:///home/bg/dev/indicagent/.planning/phases/187-research-core-recipe-book-selection-construction/187-08-PLAN.md#L72-L106)
   - **Risk:** Silent wrong calculation. In `src/intelligence/research/timing.py:66`, the timing series enforces:
     ```python
     w = np.where(has_position[:, None], weights, 0.0).reshape(shape)
     ```
     `rule.weights(...)` returns `(weights, has_position)` where `has_position` is `False` on rows below coverage floor, untraded rows, or when target is flat ($w^* = 0$). When `HorizonRule(\kappa).apply` smooths weights across rows, a non-zero decaying position ($w_t = (1-\kappa) w_{t-1}$) enters a row where $w^*_t = 0$. If `HorizonRule.apply` returns only smoothed weights and leaves `has_position` unchanged, `timing_series` immediately sets $w$ to `0.0`. The partial adjustment mechanism is silently extinguished whenever the strategy attempts to decay to flat.

2. **Top-Level Optional Fields in `BookSpec` and `FamilySpec` Bypass `_drop_unset` and Mutate Pinned Hashes**
   - **Plan & Task:** [187-08 Task 1](file:///home/bg/dev/indicagent/.planning/phases/187-research-core-recipe-book-selection-construction/187-08-PLAN.md#L72-L86), [187-15 Task 3](file:///home/bg/dev/indicagent/.planning/phases/187-research-core-recipe-book-selection-construction/187-15-PLAN.md#L95-L106)
   - **Risk:** Research integrity / moving recorded spec hashes. In `src/intelligence/research/spec.py:374-391`, `_drop_unset` takes `(data, section, keys)` and deletes keys inside a sub-dictionary (`data[section][key]`). When `horizon_rule` is added directly to `BookSpec` or `generated` is added directly to `FamilySpec`, they reside at the root of `data`, not within a section. Calling `_drop_unset` as currently written will either raise a `KeyError` or leave `"horizon_rule": null` / `"generated": null` at the top level of canonical JSON, permanently altering the SHA-256 hashes of all existing family and book specs.

3. **Combinatorial Explosion of Shapley Subset Refits in Database and StepM Selection**
   - **Plan & Task:** [187-14 Task 2 & Task 3](file:///home/bg/dev/indicagent/.planning/phases/187-research-core-recipe-book-selection-construction/187-14-PLAN.md#L86-L111)
   - **Risk:** Database bloat, OOM crash, statistical pollution. Plan 14 stipulates that every Shapley subset refit on the vintage is recorded as a counted attempt (`kind = 'subset_refit'`) with its return series stored in `research_run_series` and included in `select_books.py`. For a book with $K$ families, exact Shapley enumerates $2^K$ subsets. At the plan's cap of $K = 12$, one single book test generates $4{,}096$ database attempts and $4{,}096$ series ($1.6 \times 10^7$ doubles). Running Romano-Wolf StepM over a selection universe inflated with thousands of collinear family subsets will trigger severe memory exhaustion during bootstrap studentization ($2{,}000 \times 4{,}000+$ HAC calculations) and distort FWER control.

4. **Pickle Deserialization Failure on Renamed `SignalSource` in `repro_frozen.py`**
   - **Plan & Task:** [187-18 Task 2](file:///home/bg/dev/indicagent/.planning/phases/187-research-core-recipe-book-selection-construction/187-18-PLAN.md#L72-L79)
   - **Risk:** Determinism failure / broken reproducibility test. In `scripts/research/determinism/repro_frozen.py:51-53`:
     ```python
     class _RemappingUnpickler(pickle.Unpickler):
         def find_class(self, module, name):
             return super().find_class(_RENAMED_MODULES.get(module, module), name)
     ```
     `_RemappingUnpickler` only remaps the `module` string; it does not remap the class `name`. Renaming `SignalSource` to `Predictor` means any legacy pickled object referencing class name `SignalSource` will crash with `AttributeError: Can't get attribute 'SignalSource' on <module 'src.intelligence.research.predictors'>`.

5. **Omission of Shared Infrastructure Grants in Generated DB Roles**
   - **Plan & Task:** [187-17 Task 1 & Task 2](file:///home/bg/dev/indicagent/.planning/phases/187-research-core-recipe-book-selection-construction/187-17-PLAN.md#L57-L77)
   - **Risk:** Operational denial of service across all daemons. The generator awards `SELECT` on declared input tables and `SELECT/INSERT/UPDATE/DELETE` on declared output tables. In IndicAgent, every `BaseDaemon` and `BaseBatch` service executes mandatory startup and health routines that read `config_state`, `config_schema`, and `controlled_vocabulary`, and write to `service_heartbeats` or `service_health_audit`. Restricting grants purely to manifest domain tables will cause every rolled daemon to crash on restart with `permission denied`.

### MEDIUM Severity

1. **Pod Book Headline Schema Mismatch in `ledger.py`**
   - **Plan & Task:** [187-10 Task 2](file:///home/bg/dev/indicagent/.planning/phases/187-research-core-recipe-book-selection-construction/187-10-PLAN.md#L78-L90)
   - **Risk:** Data corruption / silent NULLs in database. In `src/intelligence/research/ledger.py:104-121`, `_headline` extracts:
     `decision.get("t")`, `decision.get("annualized_sharpe")`, `decision.get("mean_session_pnl")`, and `payload.get("turnover_per_session")`.
     Plan 10 Task 2 specifies evidence as: `decision (HAC t, p, n), sharpe, members {...}`. If `run_pod` places `sharpe` at the top level of evidence instead of nesting it as `decision["annualized_sharpe"]`, or omits `turnover_per_session`, `gross_sharpe` and `turnover` on `research_run` will silently record as `NULL`.

2. **Research Stage View Misclassifies Reopened Concepts as Refused**
   - **Plan & Task:** [187-11 Task 1](file:///home/bg/dev/indicagent/.planning/phases/187-research-core-recipe-book-selection-construction/187-11-PLAN.md#L83-L94)
   - **Risk:** Erroneous stage reporting. The view definition specifies: `refused` if `status deprecated, or every terminal attempt is refused or guard_failed, or its only attempts are legacy_verdict`. Reopened legacy ideas (e.g., from hand ledger section 2) that possess a newly specified `concept_recipe` or an active `started` attempt will be evaluated as `refused` if `refused` takes precedence over `specified` or `registered`.

3. **Validation Collision in `CombinerSpec` When Adding In-Fold Fields**
   - **Plan & Task:** [187-09 Task 3](file:///home/bg/dev/indicagent/.planning/phases/187-research-core-recipe-book-selection-construction/187-09-PLAN.md#L91-L103)
   - **Risk:** Loud validation crashes on valid specs. `CombinerSpec._fields_match_kind` (`spec.py:266-274`) strictly rejects any non-ridge field when `kind == 'equal_weight'` and requires `self.signs` to be a dictionary of $\{\pm 1\}$. Adding `sign_window_sessions`, `sign_refit_sessions`, and widening `signs` to include `"in_fold"` will fail Pydantic model validation unless `_fields_match_kind` is explicitly refactored.

4. **Resource Exhaustion During Ridge and Kappa Battery Simulations**
   - **Plan & Task:** [187-08 Task 2](file:///home/bg/dev/indicagent/.planning/phases/187-research-core-recipe-book-selection-construction/187-08-PLAN.md#L88-L96)
   - **Risk:** Background process termination. Plan 05's battery run was terminated by the host memory reaper. Plan 08 introduces Ridge combiner refitting across 1,000 simulations per cell. Repeated walk-forward Ridge inversions over $4{,}000$ sessions without per-simulation garbage collection or process pooling memory limits will trigger another OOM kill.

5. **Ridge Forecast Compression with Missing Members**
   - **Plan & Task:** [187-09 Task 1](file:///home/bg/dev/indicagent/.planning/phases/187-research-core-recipe-book-selection-construction/187-09-PLAN.md#L63-L75)
   - **Risk:** Statistical distortion in cross-sectional ranking. `EqualWeight` averages available standardized members ($\frac{1}{|K|} \sum z_k$), maintaining uniform variance. Plan 09 specifies that Ridge simply evaluates $\sum_{k \in \text{present}} b_k z_k$. On rows where some members are missing, the variance of the raw sum is artificially attenuated, compressing the ranks of those symbols toward the median in R1 construction.

6. **Automated `git commit` Inside Systemd Ledger Render Service**
   - **Plan & Task:** [187-13 Task 3](file:///home/bg/dev/indicagent/.planning/phases/187-research-core-recipe-book-selection-construction/187-13-PLAN.md#L104-L116)
   - **Risk:** Operational git collision. A systemd service committing directly to `main` on a live shared development tree can collide with interactive commits, fail on un-staged pre-commit hook checks (such as repo-wide glossary or formatting checks), or hit `index.lock` contention.

### LOW Severity

1. **Negative Busday Arithmetic on Historical Anchors**
   - **Plan & Task:** [187-09 Task 2](file:///home/bg/dev/indicagent/.planning/phases/187-research-core-recipe-book-selection-construction/187-09-PLAN.md#L77-L89)
   - **Risk:** Potential date offset bugs if `refit_anchor` is placed after the panel start date (`np.busday_count` returns negative values).
2. **Missing Constraints on HMM Seed Recipes in Migration**
   - **Plan & Task:** [187-12 Task 2](file:///home/bg/dev/indicagent/.planning/phases/187-research-core-recipe-book-selection-construction/187-12-PLAN.md#L81-L92)
   - **Risk:** Seed rows inserted via SQL migration must conform to migration 515 triggers (`recipe_hash` 64-hex regex, `code_pointer` regex).

---

## 4. Suggestions

- **Plan 08 (Horizon Rule):**
  - Redefine `HorizonRule.apply` to accept and return `(weights, has_position)`:
    ```python
    def apply(self, weights: np.ndarray, has_position: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        ...
        new_has_position = has_position | (np.abs(smoothed_weights).max(axis=1) > REACH_CUTOFF)
        return smoothed_weights, new_has_position
    ```
  - Generalize `_drop_unset` in [spec.py](file:///home/bg/dev/indicagent/src/intelligence/research/spec.py#L374) to support root-level models:
    ```python
    def _drop_unset(data: dict, keys: tuple[str, ...], section: str | None = None) -> None:
        target = data[section] if section else data
        for key in keys:
            if target.get(key) is None and key in target:
                del target[key]
    ```

- **Plan 09 (Combiners):**
  - Update `CombinerSpec._fields_match_kind` to explicitly validate that when `kind == 'equal_weight'`, `sign_window_sessions` and `sign_refit_sessions` are provided if and only if `"in_fold"` is present in `signs.values()`.
  - For Ridge prediction with missing members, normalize the applied sum by the relative in-sample variance share of the active members, or document the rank-shrinkage behavior in `construction.py`.

- **Plan 10 (Pod Books):**
  - In `run_pod`, structure the evidence dictionary to mirror `_headline` requirements exactly:
    ```python
    evidence = {
        "decision": {
            "t": float(hac.t),
            "p": float(hac.p),
            "annualized_sharpe": float(sharpe),
            "mean_session_pnl": float(np.mean(pod_series)),
            "n_sessions": int(len(pod_series)),
        },
        "turnover_per_session": float(sum(m.turnover for m in member_results)),
        "members": member_manifest,
        "power": "inherited",
    }
    ```
  - Warn or reject if the intersection of sessions drops more than 5% of any member's scored days.

- **Plan 11 (Recipe Book & Stage View):**
  - In `CREATE VIEW concept_research_stage`, ensure `specified` and `registered` take precedence over legacy `refused`:
    ```sql
    CASE
        WHEN cr.domain = 'book' AND cr.status = 'active' THEN 'confirmed'
        WHEN cr.domain = 'book' AND cr.status = 'shadow_only' THEN 'frozen'
        WHEN cr.status = 'deprecated' THEN 'refused'
        WHEN EXISTS (SELECT 1 FROM research_run rr WHERE rr.concept_id = cr.concept_id AND rr.status = 'started') THEN 'registered'
        WHEN EXISTS (SELECT 1 FROM research_run rr WHERE rr.concept_id = cr.concept_id AND rr.status IN ('completed', 'failed') AND rr.kind != 'legacy_verdict') THEN 'tested'
        WHEN EXISTS (SELECT 1 FROM concept_recipe cp WHERE cp.concept_id = cr.concept_id) THEN 'specified'
        WHEN EXISTS (SELECT 1 FROM research_run rr WHERE rr.concept_id = cr.concept_id AND rr.kind = 'legacy_verdict') THEN 'refused'
        ELSE 'idea'
    END
    ```

- **Plan 13 (Ledger Render):**
  - Do not invoke `git commit` from within `render_research_ledger.py` or systemd. Let the nightly timer write `docs/research/research-ledger.md` atomically. Use a pre-push or CI check to verify that `research-ledger.md` is up-to-date with the database.

- **Plan 14 (Contribution Accounting):**
  - **Decouple Diagnostic Shapley from Counted Attempt Universe:** Do not store all $2^K$ permutation refits as counted attempt rows in `research_run_series`. Only store the top-level book and the $K$ Leave-One-Family-Out (LOFO) runs as counted attempts. Compute Shapley values purely as an in-memory diagnostic recorded in the parent book's `evidence["contribution"]["shapley"]`. This completely eliminates the exponential explosion ($4{,}096 \to 12$) while providing identical economic insight.
  - Formulate the forecast attribution identity around standardized signals ($z_k$) where applied weights are strictly linear without intercept distortion.

- **Plan 16 & 17 (DAG & DB Roles):**
  - In `generate_role_grants.py`, define an explicit `indicagent_base_daemon` role granted to all service roles, providing `SELECT` on `config_state`, `config_schema`, and `controlled_vocabulary`, and `INSERT, UPDATE` on `service_heartbeats` and `service_health_audit`.

- **Plan 18 (Research Package Refactor):**
  - In `scripts/research/determinism/repro_frozen.py`, update `_RemappingUnpickler.find_class` to handle class renames:
    ```python
    _RENAMED_CLASSES = {
        ("src.intelligence.research.signals", "SignalSource"): ("src.intelligence.research.predictors", "Predictor"),
    }
    def find_class(self, module, name):
        module, name = _RENAMED_CLASSES.get((module, name), (_RENAMED_MODULES.get(module, module), name))
        return super().find_class(module, name)
    ```

---

## 5. Risk Assessment: MEDIUM

### Justification

The phase risk is assessed as **MEDIUM**. 

The core research foundation is exceptionally strong: the plans strictly uphold the Renaissance-style empirical measurement ethos, adhere to the Musk 5-step simplification mandate, enforce single-writer isolation, and maintain bit-identical determinism. None of the designs leak future information or compromise temporal integrity.

The rating is elevated to **MEDIUM** (rather than LOW) due to concrete mechanical risks:
1. **Statistical/Execution Trap:** The `has_position` masking behavior in Plan 08 will silently nullify partial adjustment on flat target rows unless explicitly patched.
2. **Spec Hash Fragility:** Pydantic model serialization in Plans 08 and 15 threatens to inadvertently invalidate pinned spec hashes.
3. **Scalability Threat:** Plan 14's design of recording all $2^K$ Shapley refits as counted database series will cripple StepM selection performance unless pruned to LOFO.
4. **Daemon Availability:** Plan 17 risks bringing down live daemons if baseline configuration and heartbeat tables are omitted from generated PostgreSQL grants.

All identified concerns have straightforward, localized engineering mitigations detailed above. Once these adjustments are incorporated into the plan files, execution can proceed safely and decisively.
