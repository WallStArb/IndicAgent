---
phase: 172-hmm-regime-volatility-only-redesign
verified: 2026-08-09T21:12:36Z
status: passed
score: 7/7 must-haves (requirements) verified; 30/30 plan-level truths checked against live codebase/DB
overrides_applied: 0
re_verification: No — initial verification
---

# Phase 172: HMM Regime — Volatility-Only Redesign Verification Report

**Phase Goal:** Replace the 5-column composite regime label (log_return, realized_vol, momentum,
vol_of_vol, rel_volume) with a standalone `regime_volatility` built from `realized_vol` +
`vol_of_vol` only (GaussianHMM, K=2 or K=3, new honest label vocabulary — not a renamed trend
vocabulary). Reuse the already-built, already-tested walk-forward fitting fix
(`_walk_forward_hmm_full`/`_seed_prior_from_label`/`_hmm_seed_stability_check`) unchanged in its
causal-correctness logic, pointed at the 2-column volatility slice instead of the 5-column
composite. Drop trend and volume as regime dimensions entirely.

**Verified:** 2026-08-09T21:12:36Z
**Status:** passed
**Re-verification:** No — initial verification

## Method

Codebase/DB ground-truth verification, not SUMMARY-trust. For every plan (172-01 through 172-07)
I cross-checked the PLAN.md frontmatter `must_haves` against: (1) live PostgreSQL state
(`PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent`), (2) the actual source of
`services/regime_writer.py`, `services/ic_engine.py`, `services/ensemble_trainer.py`,
`src/config/vocabulary_drift.py`, `src/intelligence/features/feature_vector_persistence.py`,
three migration files, and `docs/foundation/glossary.md`, (3) a live test run of every touched
test module plus the full `tests/unit/` suite, and (4) the post-completion `172-REVIEW.md`
findings (WR-01/WR-02/IN-01/IN-02) against the current git history to confirm the WR-01 bug fix
(commit `fdc14050`) and the `/simplify` gate (commit `2064369e`) actually landed in the code, not
just in commit messages.

## Goal Achievement

### Observable Truths (by requirement)

| # | Requirement | Truth | Status | Evidence |
|---|---|---|---|---|
| 1 | REQ-1 (schema/APR/CVR foundation) | `feature_vectors` carries the 8-column `regime_volatility` family; 4 `alpha.hmm_volatility.*` APR keys exist; `regime_volatility` CVR namespace (calm/elevated/turbulent) exists; legacy `regime`/`regime_hmm` untouched | VERIFIED | `information_schema.columns` returns all 8 new columns (`regime_volatility`, `hmm_vol_prob_calm/elevated/turbulent`, `hmm_vol_regime_prob`, `hmm_vol_entropy`, `hmm_vol_duration`, `hmm_vol_churn`); `config_state` has all 4 `alpha.hmm_volatility.*` keys; `controlled_vocabulary` has exactly `calm`/`elevated`/`turbulent` under namespace `regime_volatility`; `feature_vectors.regime` non-NULL count unchanged (26,791,341 both before 172-02 per SUMMARY and after full relabel per direct query) |
| 2 | REQ-1 (silent-corruption guards) | New columns excluded from upsert `DO UPDATE SET` and from `ensemble_trainer`'s training feature matrix | VERIFIED | `services/ensemble_trainer.py` imports `REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES` into `_META_COLS` (grep confirmed, line ~460); `tests/unit/test_feature_vector_persistence_column_ownership.py` and `tests/unit/test_ensemble_trainer_meta_cols.py` both pass (5+3 tests) |
| 3 | REQ-2 (vocabulary-parametrized pure functions) | `_build_label_map`/`_state_groups_by_vocab` generalized without changing existing trend behavior; K=2 volatility config produces calm/turbulent with no KeyError; dedicated 2-column obs-matrix builder, never sliced from composite | VERIFIED | `services/regime_writer.py` has `_TREND_VOCAB`, `_VOLATILITY_VOCAB`, `_build_label_map(means, vocab=None)`, `_state_groups_by_vocab`, `_build_obs_matrix_volatility` (all grep-confirmed present); `tests/unit/services/test_regime_writer.py` K=2/K=3/K=4/K=5/K=6 vocab tests pass; `valid_start = vol_window + vol_of_vol_window - 2` confirmed present (diverges intentionally from composite's `max(windows)-1`) |
| 4 | REQ-4 (single-cell compute + write path) | End-to-end labeling for one (symbol, tf) cell; walk-forward causal logic byte-identical; volatility path always runs walk-forward, no single-fit fallback; separate write path from legacy `regime` | VERIFIED | `_walk_forward_hmm_full(vocab=)`, `_fetch_obs_matrix_volatility`, `_compute_symbol_tf_volatility_walk_forward`, `_write_regime_volatility_results`, `--regime-column {regime,regime_volatility}` dispatch all present in `services/regime_writer.py`; `--regime-column regime_volatility --no-walk-forward` is `parser.error()` (grep-confirmed at line ~2301) |
| 5 | REQ-5 (full-corpus relabel) | Relabel gated on literal `VERDICT: GO`; APR values are the measured 172-01 values, not migration 307's plan-time estimates; every cell labeled or explicitly skipped; legacy `regime` column byte-identical before/after | VERIFIED | `172-NULL-ARM-WIDER-SCOPE.md` line 1 is literally `VERDICT: GO`; live DB `alpha.hmm_volatility.vol_window`/`.vol_of_vol_window` = 250/250 (the 172-01-measured, migration-308-reconciled value, not migration 307's seeded 20/60); `evidence/172-05-relabel-coverage.json` shows 262 labeled + 58 skipped (all with `skip_reason`), 0 failed, out of 320 cells; live DB query confirms `regime` non-NULL count = 26,791,341 identical to the coverage JSON's `legacy_regime_nonnull_before`/`_after` |
| 6 | REQ-5 (corpus data state) | `regime_volatility` populated corpus-wide, only registered vocabulary codes | VERIFIED | Live query: 9,439,731 non-NULL `regime_volatility` rows across 80 distinct symbols; distinct values are exactly `calm` (3,543,060) / `elevated` (4,120,267) / `turbulent` (1,776,404) — matches the CVR namespace exactly, no stray values |
| 7 | REQ-6 (ic_engine cutover) | Startup gate and per-symbol stratification source repointed to `regime_volatility`; legacy `regime` column no longer read by any `ic_engine.py` code path; adjacent regime machinery (routing, dual_write, pooled sentinel) verified unaffected in writing; two vocabularies proven disjoint under `regime_scope=symbol_hmm` | VERIFIED | `services/ic_engine.py` line 1682 gates on `EXISTS(... WHERE regime_volatility IS NOT NULL)`; line 2597 is `SELECT bar_ts, regime_volatility, {feature_cols}`; grep across the whole file for `FROM feature_vectors` (9 hits) confirms no other query selects the bare `regime` column; `172-IC-ENGINE-CUTOVER.md` contains an executed `VINTAGE DISJOINT: PASS` banner; live `config_state.alpha.regime.groups` shows 4 groups, all `dual_write_symbol_hmm: true`, matching the audit's claim |
| 8 | REQ-6 (vintage separation, no data loss) | Old trend-vintage `feature_ic_scores` rows remain queryable and distinguishable, nothing deleted | VERIFIED | Live query: `feature_ic_scores` total rows = 1,091,788 (matches 172-07's before/after: 1,062,880 → 1,091,788); 338,720 rows still carry retired trend labels (untouched); 876 rows carry `regime_scope='symbol_hmm', regime='turbulent'` for XLF/1d (matches 172-07-SUMMARY's claimed count exactly) |
| 9 | REQ-7 (downstream re-verification with real numbers) | A real scoped `ic_engine.py --refresh` run produces volatility-keyed rows; scoped run recorded as smoke test, not full-corpus proof, tracked via todo 285; `ensemble_trainer`'s independence from the per-symbol column is proven by a regression test | VERIFIED | `evidence/172-07-ic-refresh-scoped.json` exists with real row counts; `.planning/todos/pending/285-phase172-full-scope-ic-engine-verification-after-volatility-cutover.md` exists; `tests/unit/services/test_ensemble_trainer_regime_source.py` (9 tests) passes, including one behavioral test driving `_process_stratum()` end-to-end with two label vocabularies |
| 10 | REQ-7 (glossary) | `docs/foundation/glossary.md`'s regime entry describes the volatility-only system standing on its own, no reference to a phase planning doc | VERIFIED | `### regime` entry (lines 75-98) fully rewritten: names the 2-D observation vector, `alpha.hmm_volatility.n_components`, `calm`/`elevated`/`turbulent`, walk-forward expanding-window fit, `feature_vectors.regime_volatility`; states the null-arm rationale in its own words; zero references to any `.planning/` path or `171-FINAL-VERDICT.md` in the entry text |
| 11 | Walk-forward causal logic reused unchanged | `_walk_forward_hmm_full`/`_seed_prior_from_label`/`_hmm_seed_stability_check`'s causal-correctness logic is untouched, only vocabulary-parametrized | VERIFIED | 172-03/172-04 SUMMARYs document `git diff` checks confirming zero change inside the trend-path functions; independently confirmed via code review (`172-REVIEW.md`) which traced the full write path and found no column-order/vocabulary/lookahead defects in either path |
| 12 | Trend/volume dropped as regime *dimensions* for the new label | `regime_volatility`'s observation matrix uses only `realized_vol`+`vol_of_vol`; no trend-semantic identifier in the volatility code path | VERIFIED | `_build_obs_matrix_volatility(timestamps, closes, vol_window, vol_of_vol_window)` builds a strict `(n, 2)` matrix directly (grep-confirmed, no momentum/rel_volume params); this is a phased cutover per the plan's and ROADMAP's own explicit design (legacy `regime`/composite builder intentionally left running for backward compatibility, not deleted) — consistent with "Rough shape" step (1) in the ROADMAP goal text itself |

**Score:** 12/12 derived truths verified (spanning all 7 REQ IDs). No truth failed, no truth uncertain.

### Post-Completion Review Fixes (verified live in code, not just claimed in commit messages)

| Finding | Fix Commit | Verified Live In Code |
|---|---|---|
| WR-01: `hmm_churn`/`hmm_vol_churn` fabricated a label-change event across skipped walk-forward segment gaps (both trend and volatility paths) | `fdc14050` | Both `_compute_symbol_tf_walk_forward` (~line 1116) and `_compute_symbol_tf_volatility_walk_forward` (~line 1275) now compute churn per-segment (`[_compute_hmm_churn(labels, churn_window) for labels in written_segment_labels]`) then concatenate, not concatenate-then-compute-once |
| WR-02: `_hmm_seed_stability_check` hardwired to `_TREND_VOCAB` | `fdc14050` | `_hmm_seed_stability_check` signature now has `vocab: dict[str, str] | None = None`, passed through to `_build_label_map(model.means_, vocab=vocab)` |
| Simplify-gate cleanup (dead code, drift-proof col_types, ic_engine `EXISTS` perf fix) | `2064369e` | Confirmed applied; full `tests/unit/` suite green after both commits |

### Known, Explicitly-Tracked Gap (not a phase-goal blocker)

`feature_vectors.hmm_vol_churn`'s 9.4M corpus values were written by plan 172-05's relabel
**before** the WR-01 fix landed, so this one auxiliary stat column's values are stale at
walk-forward segment-gap boundaries. The `regime_volatility` label column itself — the actual
deliverable `ic_engine.py` was cut over to — is unaffected; only `hmm_vol_churn` (not consumed by
`ic_engine.py`'s stratification and excluded from `ensemble_trainer`'s training matrix as a
regime_volatility-family column) carries pre-fix values. Tracked in
`.planning/todos/pending/292-hmm-vol-churn-corpus-values-predate-wr01-fix.md`, confirmed present
and accurately describing the blast radius. Not treated as a gap against this phase's goal
because the goal is about the `regime_volatility` label, not the auxiliary churn diagnostic.

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `production/migrations/307_regime_volatility_schema_apr_cvr.sql` | Schema/APR/CVR foundation | VERIFIED | Applied to live DB, confirmed idempotent per SUMMARY, all objects present live |
| `production/migrations/308_regime_volatility_apr_reconciliation.sql` | APR reconciliation to measured values | VERIFIED | Live `config_state` shows 250/250, matching this migration's target values |
| `production/migrations/309_feature_ic_scores_regime_vocabulary_comments.sql` | Corrected schema comments | VERIFIED | File present, comment-only, `CHECK` constraint untouched |
| `services/regime_writer.py` | Vocabulary-parametrized functions + volatility compute/write path | VERIFIED | All named functions present and correct (see truths table) |
| `services/ic_engine.py` | Startup gate + per-symbol fetch repointed | VERIFIED | Confirmed via direct grep/read of live source |
| `.planning/milestones/v3.1-phases/172-hmm-regime-volatility-only-redesign/172-NULL-ARM-WIDER-SCOPE.md` | GO/NO-GO verdict | VERIFIED | Literal `VERDICT: GO` line present |
| `.planning/milestones/v3.1-phases/172-hmm-regime-volatility-only-redesign/172-CORPUS-RELABEL.md` | Relabel gate evidence | VERIFIED | Present, 320-cell coverage matches evidence JSON |
| `.planning/milestones/v3.1-phases/172-hmm-regime-volatility-only-redesign/172-IC-ENGINE-CUTOVER.md` | Written audit of adjacent regime machinery | VERIFIED | Contains `VINTAGE DISJOINT: PASS` with real query output |
| `.planning/milestones/v3.1-phases/172-hmm-regime-volatility-only-redesign/172-DOWNSTREAM-VERIFICATION.md` | Real-number downstream re-verification | VERIFIED | Both required sections present with real, spot-checked numbers |
| `docs/foundation/glossary.md` | Standalone regime entry rewrite | VERIFIED | Rewritten, self-contained, no `.planning/` reference |
| `evidence/172-01-*.json`, `evidence/172-05-relabel-coverage.json`, `evidence/172-07-ic-refresh-scoped.json` | Machine-readable evidence | VERIFIED | All three parsed directly; contents match SUMMARY/doc claims exactly |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `regime_writer.py::_build_obs_matrix_volatility` | `regime_writer.py::_build_label_map` | column 0 = realized_vol drives ascending sort | VERIFIED | Code comment + test coverage confirm calm→elevated→turbulent ordering |
| `regime_writer.py::_write_regime_volatility_results` | `feature_vector_persistence.py::REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES` | imported column list, never hand-typed | VERIFIED | Grep confirms import at line 79, used at line 1931 |
| `172-NULL-ARM-WIDER-SCOPE.md` | corpus relabel run | grep for literal `VERDICT: GO` | VERIFIED | Line 1 of the doc is exactly `VERDICT: GO` |
| `ic_engine.py::_assert_prerequisites` | `feature_vectors.regime_volatility` | startup gate count/EXISTS query | VERIFIED | Live code at line 1682 |
| `ic_engine.py::_compute_symbol_tf` | `feature_vectors.regime_volatility` | per-symbol feature-matrix SELECT | VERIFIED | Live code at line 2597, only such SELECT in the file |
| `ic_engine.py --refresh` | `feature_ic_scores` | scoped real run writes volatility labels under `regime_scope=symbol_hmm` | VERIFIED | Live DB query: 876 XLF/turbulent rows exist exactly as claimed |
| `docs/foundation/glossary.md` | `feature_vectors.regime_volatility` | Code surface line | VERIFIED | Line 97 names it explicitly |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Full touched-module test suite | `.venv/bin/pytest tests/unit/services/test_regime_writer.py tests/unit/services/test_ic_engine.py tests/unit/services/test_ensemble_trainer_regime_source.py tests/unit/test_ensemble_trainer_meta_cols.py tests/unit/test_feature_vector_persistence_column_ownership.py tests/unit/test_vocabulary_drift_audit.py tests/unit/scripts/test_ops_regime_null_out_and_verify.py -v` | 149 passed, 0 failed | PASS |
| Full repo unit suite (regression check) | `.venv/bin/pytest tests/unit/ -q` | All passed, 2 pre-existing unrelated skips | PASS |
| `feature_vectors.regime_volatility` corpus state | Direct psql query | 9,439,731 rows, 80 symbols, codes exactly {calm, elevated, turbulent} | PASS |
| `feature_vectors.regime` unchanged | Direct psql query | 26,791,341 (matches every SUMMARY's claimed before/after value) | PASS |
| `alpha.hmm_volatility.*` live APR values | Direct psql query | n_components=3, vol_window=250, vol_of_vol_window=250, covariance_type=full | PASS |
| `regime_volatility` CVR codes | Direct psql query | calm/elevated/turbulent only | PASS |
| `feature_ic_scores` post-cutover proof | Direct psql query | 876 XLF/turbulent `symbol_hmm` rows; 0 trend-vocabulary rows added by this cutover; 338,720 pre-existing trend rows preserved | PASS |
| WR-01 fix live in code | `git blame` + direct read | Per-segment churn computation confirmed in both trend and volatility paths | PASS |
| Debt-marker scan on all files touched by this phase | `grep -nE "TBD|FIXME|XXX"` across every phase-172-modified source/migration/test file | Zero markers in any file introduced or edited by this phase | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| REQ-1 | 172-02 | Schema/APR/CVR foundation | SATISFIED | Migration 307 live, all objects confirmed in DB |
| REQ-2 | 172-03 | Vocabulary-parametrized pure functions | SATISFIED | `_build_label_map`/`_state_groups_by_vocab`/`_build_obs_matrix_volatility` present, tested |
| REQ-3 | 172-01 | Wider-scope null-arm GO/NO-GO gate | SATISFIED | `VERDICT: GO`, 15m/5m tested, window sweep executed, evidence JSON complete |
| REQ-4 | 172-04 | Single-cell volatility compute + write path | SATISFIED | End-to-end path present, `--regime-column` dispatch live |
| REQ-5 | 172-05 | Full-corpus relabel | SATISFIED | 9,439,731 rows live in DB, 0 failed cells, legacy column untouched |
| REQ-6 | 172-06 | ic_engine regime-source cutover | SATISFIED | Startup gate + fetch repointed, audit doc with real query output |
| REQ-7 | 172-07 | Downstream re-verification + glossary | SATISFIED | Real scoped run proof (876 rows), regression test, glossary rewrite |

No orphaned requirements: all 7 ROADMAP-declared REQ IDs (REQ-1 through REQ-7) are each claimed
by exactly one plan's `requirements-completed` frontmatter field, matching the ROADMAP phase
section's own requirement-to-plan mapping. `.planning/REQUIREMENTS.md` does not exist as a
separate file in this repo — requirement definitions live inline in the ROADMAP.md phase section,
which was used as the source of truth per Step 2a/6b fallback.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| `services/regime_writer.py` | 117 | `TBD` in a comment referencing an unassigned migration number for `alpha.hmm.walk_forward.refit_every_bars.<tf>` | INFO | Pre-existing from Phase 171 (commit `1300ec8d7`, 2026-08-05, predates Phase 172's 2026-08-09 start), not touched by any of this phase's 7 plans (confirmed via `git blame`), purely a stale comment (the underlying APR keys already exist and work, per migration 292 references elsewhere in the codebase), not functional debt. Per CLAUDE.md's "not a retroactive sweep of existing docs" convention, correctly left alone by this phase. Not a blocker. |

No other TBD/FIXME/XXX/placeholder/stub patterns found in any file created or modified by this
phase (migrations 307/308/309, `regime_writer.py`, `ic_engine.py`, `ensemble_trainer.py`,
`vocabulary_drift.py`, `feature_vector_persistence.py`, `ops_regime_null_out_and_verify.py`,
`glossary.md`, and all associated test files).

### Human Verification Required

None. This phase's deliverables (schema, APR, CVR, compute/write path, corpus relabel,
ic_engine cutover, downstream re-verification, glossary) are all verifiable via direct database
query, source inspection, and automated test execution — no UI, real-time behavior, or external
service integration involved.

### Gaps Summary

No gaps found against the phase goal. All 7 requirements are satisfied with direct database and
code evidence, not SUMMARY-trust. The one known limitation (`hmm_vol_churn`'s pre-WR-01-fix
corpus values) is explicitly tracked as todo 292, does not affect the `regime_volatility` label
itself (the actual phase deliverable and the column `ic_engine.py` was cut over to), and is
correctly scoped as a follow-up decision rather than a phase-blocking defect. Todo 285 (full-scope
`ic_engine.py` verification beyond the 5-symbol smoke test) is also explicitly tracked and was
never claimed as done by this phase — the phase's own SUMMARY/DOWNSTREAM-VERIFICATION correctly
labels its `ic_engine.py --refresh` proof as a smoke test, not full-corpus verification, which
matches this phase's REQ-7 wording exactly ("A real scoped ic_engine run ... proving the cutover
works end to end rather than only passing unit tests" — not "the full corpus is re-verified").

---
*Verified: 2026-08-09T21:12:36Z*
*Verifier: Claude (gsd-verifier)*
