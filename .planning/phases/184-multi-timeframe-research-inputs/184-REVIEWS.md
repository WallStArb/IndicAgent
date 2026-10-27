---
phase: 184
reviewers: [codex]
reviewed_at: 2026-10-27T15:59:00Z
plans_reviewed: [184-01-PLAN.md,184-02-PLAN.md,184-03-PLAN.md,184-04-PLAN.md,184-05-PLAN.md,184-06-PLAN.md,184-07-PLAN.md,184-08-PLAN.md,184-09-PLAN.md,184-10-PLAN.md,184-11-PLAN.md,184-12-PLAN.md,184-13-PLAN.md,184-14-PLAN.md]
---

# Cross-AI plan review: phase 184

**Informed by:** Codex (gpt-5.6-terra, read-only sandbox), 2026-10-27, reading the plans, context, research, validation, design revision 3 and the research code by path. AGY was out of quota (429, resets about 2026-11-03), so this is a single-reviewer record; AGY reviews the wiring plans (06-11) before they execute.

## Dispositions (orchestrator, 2026-10-27)

| # | Codex finding | Severity | Disposition |
|---|---|---|---|
| 1 | Cross-clock probe trusts declared `src_avail`; a falsely early timestamp or a copied future value passes (01, 10) | HIGH | Accepted. `src_avail` is never read from stored metadata: it is always `clock.closes_at` on the source bar grid. Kernel members get an end-to-end probe that perturbs raw source bars after a book decision row and recomputes kernel, alignment and member. Stored feature values rely on phase 186's truncation probe for their own causality; 184 proves the alignment only. |
| 2 | Align inside S0 breaks design's "S2b is the only two-clock node" and leaves only a probe slice (08, 10) | HIGH | Accepted. Overrides my earlier W4 call. One align implementation, executed in S2b. For finer sources, S0 persists the compact source evidence plus a per-book-row source row index (int32 [t, i]) produced by the same align function; S2b replays the mapping and S3 checks every scored row: `src_closes_at[idx] <= dst_avail` and age <= max_age. No probe-slice-only proof. |
| 3 | Route key omits material dimensions (memory/window, max_age, gap, horizon, combiner, horizon rule) (05, 09) | HIGH | Accepted. Validation keys on a structured battery certificate (dataclass), not a string: identity with window, smoothing, source tf, book tf, horizon, combiner, max_age_rows, max_gap_rows, and a source-memory upper bound. A member is admitted only if a passing cell matches every discrete field and its memory is within the cell's tested bound. Input members are equal-weight only until a ridge or kappa cell exists. |
| 4 | Battery covers a small subset of what the spec admits; "any timeframe" overstated | HIGH | Accepted. The phase states its supported subset explicitly: daily books with 1d, 1h, 15m and 5m sources; 1h books with 1d sources; horizon 1. Everything else is refused at spec load, and the goal text in ROADMAP says the subset grows by adding battery cells. |
| 5 | 1,000 sims cannot gate 0.00167 (05) | MEDIUM | Accepted. Gate at 0.05 and 0.01 (187 amendment precedent); 0.00167 reported as descriptive. |
| 6 | Smoothing renormalizes around NaNs, which is a fill (03) | MEDIUM | Accepted. No renormalization: the smoothed value is NaN if any input in its window is NaN. |
| 7 | Economic age and the one-session shift not defined on the exchange calendar (13, 14) | MEDIUM | Accepted. Age counts from the first book row whose `closes_at >= available_at`; the shift maps each value to the first eligible close of the next NYSE session. Tests cover weekend, holiday, half day, DST and after-close releases. |
| 8 | Knowledge cutoff not pinned (13) | MEDIUM | Accepted. The spec pins the cutoff; a supplied snapshot must match it exactly. |
| 9 | B8 reads as delivered while admission-refused (14) | MEDIUM | Accepted. B8 is recorded as "implemented, admission-refused pending the economic battery cell (todo filed in 184-14)". |
| 10 | Research kernels risk a second implementation (02) | MEDIUM | Accepted with a rule: a research kernel may exist only if no stored column computes the same concept; each carries a promotion todo into phase 186's registry once the rebuild's import closure unfreezes. |
| 11 | S3 memory declaration is a partial hand formula (10) | MEDIUM | Accepted. The guard declaration comes from the same member-memory object used for warmup and E17 L. |
| 12 | `book_memory` wrapping `e17_memory` is an assumption | MEDIUM | Accepted. An integration test asserts L equals `e17_memory` over member memory on 1d and intraday panels. |
| 13 | Age across invalid/NaT source rows undefined (01) | MEDIUM | Accepted. Age counts source-grid rows, including invalid ones; tested with a missing final source bar. |
| 14 | Chunk-size APR key could be a memory budget (08) | MEDIUM | Rejected. A symbol-count key is simpler and already seeded by the plan; a derived budget adds a policy for no measured gain. |
| 15 | `apr_hash` name collides with `provenance_batch.apr_hash` (06) | LOW | Accepted. Renamed `config_projection_hash`. |
| 16 | Warmup prefix tested on daily only (07) | LOW | Accepted. Add a 1h prefix test across a half day. |
| 17 | Snapshot match checks the declared prefix count only (09) | LOW | Accepted. Verify `fetch_start` gives the required session count per source clock. |
| 18 | Legacy allow-list entries in the read boundary (04) | LOW | Accepted. Entries carry a removal todo; new scripts fail closed. |
| 19 | Record-only enforcement by grep; insufficient shifts (11) | LOW | Accepted. A typed evidence namespace not passed to selection, and an explicit "insufficient shifts" payload. |
| 20 | Dry build sample too benign (12) | LOW | Accepted. Add pre-registered adversarial symbols (late listing, missing bars, half-day activity) and one high-memory column. |
| 21 | `slot_history_sessions` meaning for input members (03) | LOW | Accepted. Documented as additional member-transform reach. |

---

## Codex review

# Phase 184 plan review

Overall risk: **HIGH**. The plan is unusually strong on provenance, frozen-hash compatibility, and execution ordering, but it has two unresolved structural temporal-integrity problems: its cross-clock “causality proof” cannot detect falsely early availability metadata, and it moves finer-clock alignment into S0 despite the design making S2b the sole two-clock node. The E17 route battery also does not license the full set of routes/configurations the runner can admit.

## Per-plan review

### 184-01: Clock, align, fixtures

**Summary:** Adds `closes_at`, causal `align`, and calendar fixtures.

**Strengths:**

- Correctly treats the short final 1h bucket, half days, DST, NaT destination rows, and `<=` availability as causal because entry is at the next open.
- Keeps wave 1 file-disjoint from shared research files.
- Uses source-row age rather than calendar elapsed time.

**Concerns:**

- **HIGH, Task 2:** `align_causality_probe` only sees `src_avail`. If a future source value is stamped with an artificially early `src_avail`, the probe regards it as already available and will not perturb it. Failure scenario: an S0 scatter/indexing bug copies a future daily feature value into Friday’s row while retaining a Friday close timestamp. The proposed probe passes although Monday information is used Friday.
- **MEDIUM, Task 2:** The plan must make explicit whether invalid/NaT source grid rows count toward `max_age_rows`. Compressing them during the candidate search can silently extend a stale value across missing source bars.

**Suggestions:**

- Make the probe end-to-end and provenance-aware: perturb the true source bars or source feature inputs after a book-clock decision row, recompute the source value and alignment, then assert earlier book rows are unchanged. Do not attempt to infer truth from mutable availability metadata alone.
- Define age against the original source-grid row index and test a missing final source bar.

**Risk:** HIGH.

### 184-02: Research kernels and `kernel_source`

**Summary:** Creates bounded, vectorized research kernels and an adapter using the feature-kernel contract.

**Strengths:**

- Correctly avoids editing the phase 186 rebuild import closure during a live/resumable rebuild.
- Explicitly addresses expanding VWAP and bounded-memory probes.
- Separates research from `measure`, avoiding an import cycle.

**Concerns:**

- **MEDIUM, overall design:** The plan creates research-only vectorized equivalents of existing stored kernels in a package the default registry does not discover. Failure scenario: a feature table column and a `kernel_source` member represent the same concept but evolve independently, violating the “no second implementation of a feature” goal. This also does not literally deliver B2’s requested registry entries.

**Suggestions:**

- Treat these as temporary named research kernels only if they are semantically distinct from stored columns.
- Otherwise make phase 186 own the registry entry and table output after its import freeze, and let research only read that output. Add an explicit ownership and promotion/removal condition.

**Risk:** MEDIUM.

### 184-03: Smoothing, member memory, lag term structure

**Summary:** Adds the fixed smoothing menu, feature-member memory calculation, and pure lag IC term structure.

**Strengths:**

- The amendment correctly binds E17 L to `timing.e17_memory`, rather than reimplementing daily target reach.
- Uses the correct lag-IC object rather than `measure.term_structure`’s cumulative-horizon ladder.
- Memory is centralized rather than duplicated across warmup and runner logic.

**Concerns:**

- **MEDIUM, Task 1:** Renormalizing a smoothing window around internal NaNs creates a value across missing observations. Failure scenario: after a missing source row, the next row receives a rescaled historical signal rather than NaN, which conflicts with the no-fill invariant and can make gaps appear tradeable.
- **LOW, Task 2:** The formula adds `slot_history_sessions` to source memory without defining what it means for an input member. A pre-registration can overstate memory safely, but this is confusing and makes the actual dependency reach harder to audit.

**Suggestions:**

- Specify and test a gap rule for smoothing: either propagate NaN across a declared gap reach or explicitly pin a maximum gap and refuse/NaN beyond it.
- Rename or document `slot_history_sessions` as an additional member-transform reach, not an independently chosen duplicate of source feature memory.

**Risk:** MEDIUM.

### 184-04: Feature-read decisions and read boundary

**Summary:** Adds provenance, config reconstruction, warmup masking, coverage, HMM gating, and a `feature_vectors` reader boundary.

**Strengths:**

- Strongest plan in the set for APR provenance: hash-only projection pin, complete-projection equality, mixed-code-key refusal, and `FeatureFactoryConfig` reconstruction from `apr_snapshot`.
- Correctly refuses path-dependent and pre-rebuild regime columns.
- The CI read boundary prevents uncounted feature-table readers.

**Concerns:**

- **LOW, Task 2:** The boundary test explicitly allow-lists legacy research scripts. Failure scenario: a legacy script remains runnable and can still produce an uncounted result despite the boundary test passing.

**Suggestions:**

- Make legacy research-script allow-list entries time-bounded, fail closed for new scripts, and add a follow-up deletion or migration date.

**Risk:** LOW.

### 184-05: Persistent E17 battery and route admission

**Summary:** Builds persistent-predictor E17 null cells, produces a committed report, and gates input routes through `VALIDATED_ROUTES`.

**Strengths:**

- The amendment correctly requires `e17_memory` through `book_memory`, including the daily overnight component.
- Records tested-session counts, Monte Carlo uncertainty, and failing gate cells rather than silently downgrading them to diagnostic.
- Uses composed route keys rather than claiming generic feature evidence transfers automatically.

**Concerns:**

- **HIGH, Tasks 1-2:** The composed route key omits material determinants of the admitted statistic: source-memory length/window, `max_age_rows`, `max_gap_rows`, horizon, combiner training reach, horizon rule, and most source-to-book clock combinations. Failure scenario: `feature|none|1d->1d` validates a short-memory equal-weight horizon-1 member, then admits a 252-bar feature with a large staleness allowance, ridge training reach, or longer daily horizon under the same key.
- **HIGH, Tasks 1-2:** The stated cells cover only a small subset of routes the spec surface permits. Examples include 5m-to-5m, 15m-to-15m, 1h-to-1h, 5m-to-1h, 15m-to-1h, most kernel timeframes/windows, and smoothing combinations other than the listed ones. Failure scenario: either the runner wrongly admits an untested configuration because its coarse key matches, or the declared phase goal is silently narrowed to a small daily-book subset.
- **MEDIUM, Task 2:** A 1,000-simulation battery cannot meaningfully establish size at 0.00167. Reporting it is useful, but it must not be called a passing tail gate.

**Suggestions:**

- Define the exact admission domain first. Either expand the battery matrix to every supported route/configuration or make the spec validator reject every unrepresented dimension.
- Key validation by an explicit battery scenario schema, not a string that omits memory and construction state.
- Gate only 0.05 and 0.01 at 1,000 simulations, matching the Phase 187 amendment. Label 0.00167 descriptive until an adequately powered run exists.

**Risk:** HIGH.

### 184-06: Input-member spec surface and `Panel.closes_at`

**Summary:** Adds optional spec fields and optional panel serialization.

**Strengths:**

- Correctly sequences after the Phase 187 canonical-form work.
- Uses `_OPTIONAL_MEMBER_FIELDS` and optional panel arrays to preserve recorded hashes and old snapshot bytes.
- Requires `closes_at` before input members can be declared.

**Concerns:**

- **LOW, Task 1:** It accepts a single `apr_hash` per source type as a projection hash but calls it `apr_hash`, which is easily confused with `provenance_batch.apr_hash`. Failure scenario: an implementer compares the spec pin to the batch’s full APR snapshot hash rather than the defined projection hash.

**Suggestions:**

- Rename the field to `config_projection_hash`, or add a strict docstring and error text stating it must never be compared to `provenance_batch.apr_hash`.

**Risk:** LOW.

### 184-07: S0 bar side

**Summary:** Wires `closes_at`, warmup prefix, and derived-vendor checks into S0.

**Strengths:**

- Correctly keeps default snapshot bytes and SQL unchanged.
- Vendor/kind refusal makes the derived 15m/1h grid enforceable.
- Tests OOS refusal before fetch and prefix metadata.

**Concerns:**

- **LOW, Task 2:** The warmup-prefix test is daily-focused. Failure scenario: intraday prefix session boundaries or a half-day prefix are fetched incorrectly while daily tests remain green.

**Suggestions:**

- Add one 5m or 1h warmup-prefix test crossing a half day and verify the first scored session has the intended complete preceding-session history.

**Risk:** LOW.

### 184-08: S0 feature reads and finer-source handling

**Summary:** Reads verified feature columns, persists source arrays or finer-source book-clock inputs, and adds chunked 5m reads.

**Strengths:**

- Excellent provenance and config handling when combined with plan 04.
- The 5m chunking design directly addresses scale and avoids persisting full intraday arrays in daily-book snapshots.
- Requires a minimal probe slice and hashes child artifacts.

**Concerns:**

- **HIGH, Task 3:** It performs `align` inside S0 for finer sources. This conflicts with the phase design, which declares S2b as the only node seeing two clocks. Failure scenario: the snapshot contains already-aligned values, the runner cannot reconstruct or fully guard the source-to-book transformation, and a causal alignment defect becomes part of an opaque S0 artifact.
- **HIGH, Task 3:** The proposed probe slice cannot prove the complete historical route for a 5m source. Failure scenario: a bug outside the last `probe_sessions` window or a malformed source availability series affects the persisted book-clock input; S3 only sees a narrow sample and the full source data has been discarded.
- **MEDIUM, Task 1:** This plan introduces a new live APR migration although the chunk size is an operational allocation choice. It is defensible, but adds migration and coordination cost for a value that could be derived from a documented memory budget.

**Suggestions:**

- Preserve the architectural boundary: S0 may chunk, hash, and store compact source evidence, but the actual alignment should remain an explicit S2b operation or a separately named, fully replayable and guarded alignment artifact.
- If compaction is mandatory, store enough deterministic source checkpoints and alignment mapping to replay every scored row, not only a final probe slice.
- Consider a derived chunk-size policy from an APR memory budget rather than a symbol-count key.

**Risk:** HIGH.

### 184-09: Runner preflight, memory, snapshot matching

**Summary:** Adds spec-time refusals, source requests, warmup masking, and snapshot/spec verification.

**Strengths:**

- Correctly uses the binding amendment: E17 L comes from `e17_memory`, or Phase 187’s wrapper, never a duplicate `fwd_span` calculation.
- Rejects unknown/path-dependent columns before data reads.
- Requires source provenance/config/prefix match for supplied snapshots.

**Concerns:**

- **MEDIUM, Tasks 1-2:** The plan relies on `VALIDATED_ROUTES` whose key is too coarse, so its route refusal gives a false sense of E17 coverage. Failure scenario: an admitted member has materially different reach/construction from every corresponding battery cell.
- **LOW, Task 2:** The snapshot match only requires `warmup_prefix.sessions >= required`; it does not state that the recorded `fetch_start` actually corresponds to that many valid exchange sessions for every source clock.

**Suggestions:**

- Consume a structured battery certificate with all material parameters, as suggested for plan 05.
- Validate `fetch_start`, `scored_start`, calendar session count, and source-specific prefix coverage, not merely the declared count.

**Risk:** MEDIUM.

### 184-10: Member dispatch and S3

**Summary:** Computes feature/kernel members on the book clock and adds S3 probes.

**Strengths:**

- Preserves the residual-bar member path.
- Correctly adds kernel truncation/memory probes and provenance code-key evidence.
- Defensively checks source availability and float32 handling.

**Concerns:**

- **HIGH, Task 2:** The planted lookahead test still cannot prove a stored value was computed from future data. `align_causality_probe` observes only stored values and their declared close times. Failure scenario: a future feature value is copied into an earlier source row while timestamps remain plausible; alignment and both array probes pass.
- **HIGH, Tasks 1-2:** The plan depends on plan 08’s pre-aligned finer inputs, so the runner sometimes does not execute the claimed S2b node at all. This contradicts its own goal that S3 covers the transform.
- **MEDIUM, Task 2:** `declared = slot_history + smoothing` for the array guard does not clearly cover source kernel/feature memory and staleness reach. The E17 memory may be larger, but the S3 local memory assertion can still understate the actual composed transform.

**Suggestions:**

- Add an end-to-end perturbation test through raw source bars or registry inputs, S0 feature creation/read, and alignment.
- Keep one executable alignment implementation and make its full route inspectable at S3.
- Derive the guard declaration from the same full member-memory object used for warmup and E17, rather than a partial hand formula.

**Risk:** HIGH.

### 184-11: Lag IC evidence record

**Summary:** Records lag IC curves, joint bands, and book kappa as inert evidence.

**Strengths:**

- Uses the correct lag target and an evidence-only field.
- Uses run-specific shifts and book memory.
- Explicitly tests that the primary statistic does not change.

**Concerns:**

- **LOW, Task 1:** The “no reader” grep is not a robust non-consumption guarantee. Failure scenario: a future reader accesses a renamed or nested field and bypasses the literal-pattern search.
- **LOW, Task 1:** The plan does not state behavior when long memory leaves too few admissible shifts. Failure scenario: a 63-session smoothed daily member yields no joint band and fails a run after statistics are computed.

**Suggestions:**

- Put the term structure under a dedicated evidence namespace/type not passed to selection code, plus a typed selection-input allow-list.
- Define an explicit record-only “insufficient shifts” payload rather than a late failure.

**Risk:** LOW.

### 184-12: Real dry S0 build

**Summary:** Runs a gated real-data integration read after Phase 186-27.

**Strengths:**

- Correctly separates a dry S0 build from a counted research run.
- Tests actual provenance, 5m scale, APR mismatch, and HMM refusal.
- Does not tune pins/floors after observing a refusal.

**Concerns:**

- **LOW, Task 2:** The test uses a first-50-symbol slice and one chosen column per timeframe. Failure scenario: the chosen sample misses sparse-symbol, partial-session, or high-memory behavior present in the intended universe.

**Suggestions:**

- Predefine a small adversarial symbol set too: late listings, missing bars, half-day activity, and a high-memory column. Keep it a dry build.

**Risk:** LOW.

### 184-13: Economic S0 block

**Summary:** Adds release-record-gated economic input reads, knowledge cutoff, and decision-time alignment.

**Strengths:**

- Correctly blocks on todo 482 and rejects assumed-lag data.
- Hashes the knowledge cutoff and filters at SQL read time.
- Keeps economic data separate from feature provenance/APR logic.

**Concerns:**

- **MEDIUM, Task 2:** Economic age is underspecified for releases on weekends, holidays, and after a market close. Failure scenario: a Saturday release is assigned a calendar-date age rather than age zero at its first usable Monday row, or a post-close release is treated as same-session information.
- **MEDIUM, Task 2:** The knowledge cutoff is described as a runtime/build-time value, not a spec-pinned or otherwise reproducibly selected vintage. Failure scenario: rebuilding the same committed spec at different dates produces different economic snapshots before the OOS cap takes effect.

**Suggestions:**

- Compute age from the first destination session whose `closes_at >= available_at`, not from calendar dates.
- Pin a named economic vintage/cutoff in the spec or freeze it before the run begins and require supplied snapshots to match it exactly.

**Risk:** MEDIUM.

### 184-14: Economic members and shift test

**Summary:** Dispatches economic inputs and records a one-session-later robustness rerun.

**Strengths:**

- Keeps economic routes refused in real/exploration mode until a dedicated battery exists.
- Explicitly prevents generic feature battery evidence from transferring to economic members.
- Records the shift test as attempt evidence rather than a second selection attempt.

**Concerns:**

- **MEDIUM, Tasks 1-2:** The phase does not enable economic members because the necessary E17 battery is deferred to a todo. Failure scenario: B8 is marked implemented even though no real or exploration book can use it.
- **MEDIUM, Task 2:** “Move availability one session later” is not specified as an exact exchange-calendar mapping for intraday timestamps, holidays, and early closes. Failure scenario: the robustness test shifts a 13:00 half-day release by the wrong duration and fails to test the intended edge-of-knowability sensitivity.

**Suggestions:**

- State B8’s delivered status as “implemented but admission-refused pending battery,” not complete support.
- Define the transform as mapping each value to the first eligible close of the next NYSE session and test half-day, DST, holiday, and after-close releases.

**Risk:** MEDIUM.

## Dependency and scope assessment

The sequencing safeguards are mostly good:

- Wave 1 is new files only and does not edit shared research files.
- Plans 06 through 11 correctly name the Phase 187 spec/runner dependencies and account for the Phase 187-18 rename.
- Plan 12 properly waits for 186-27.
- Plans 13 and 14 properly block on todo 482.

However, plan 05 depends on Phase 187-08’s `book_memory`, while plans 09 and 10 admit routes based on plan 05’s evidence. That chain is safe only if Phase 187-08’s final `book_memory` actually wraps `timing.e17_memory` exactly once. Make that an executable integration assertion, not an implementation assumption.

## Consolidated changes required before execution

1. **HIGH:** Redesign plans 01 and 10’s cross-clock causality proof. It must perturb true source inputs or raw bars end-to-end, not rely on declared `src_avail`, which cannot expose falsely early timestamps or future-value copies.

2. **HIGH:** Change plan 08 so finer-source alignment remains an explicit, replayable S2b operation, or document and implement an equivalently auditable alignment artifact with complete source-to-book mappings and full-route probes. Do not make S0 silently own the sole two-clock transform.

3. **HIGH:** Redefine plan 05’s battery admission certificate. Include every material route dimension, especially source memory/window, age/gap policy, target horizon, book clock, combiner training reach, and horizon rule. Reject all unsupported combinations.

4. **HIGH:** Reconcile the advertised “any timeframe” goal with the actual battery matrix. Either add cells for every supported source-to-book combination and kernel configuration, or reduce the spec surface and state the supported subset explicitly.

5. **MEDIUM:** Amend plan 03 smoothing to honor no-fill across internal missing observations through a pinned gap/NaN policy.

6. **MEDIUM:** Amend plans 13 and 14 to define economic first-usable-session age and one-session shift on the exchange calendar, including weekend, holiday, half-day, DST, and after-close cases.

7. **MEDIUM:** Clarify whether B8 is complete while all economic members remain admission-refused pending a future E17 battery. It is safer to state it as infrastructure-only until that evidence exists.

8. **LOW:** Harden record-only enforcement in plan 11 and make plan 12’s dry read include adversarial symbols and high-memory columns.
