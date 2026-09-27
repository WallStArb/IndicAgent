---
phase: 186
reviewers: [claude-opus-r1, claude-opus-r2, claude-opus-r3, claude-opus-r4, claude-opus-r5, claude-opus-r6]
reviewed_at: 2026-09-27T15:11:55Z
plans_reviewed: [186-01-PLAN.md, 186-02-PLAN.md, 186-03-PLAN.md, 186-04-PLAN.md, 186-05-PLAN.md, 186-06-PLAN.md, 186-07-PLAN.md, 186-08-PLAN.md, 186-09-PLAN.md, 186-10-PLAN.md, 186-11-PLAN.md, 186-12-PLAN.md, 186-13-PLAN.md, 186-14-PLAN.md, 186-15-PLAN.md, 186-16-PLAN.md, 186-17-PLAN.md, 186-18-PLAN.md, 186-19-PLAN.md, 186-20-PLAN.md, 186-21-PLAN.md, 186-22-PLAN.md, 186-23-PLAN.md, 186-24-PLAN.md, 186-25-PLAN.md, 186-26-PLAN.md, 186-27-PLAN.md, 186-28-PLAN.md, 186-29-PLAN.md]
external_reviewers: unavailable — `agy` quota-blocked until ~2026-10-01, `codex` until ~2026-10-15 (probed 2026-09-25, not re-probed per memory); substitute: six fresh-context Claude Opus agents, one plan group each, same prompt
---

# Cross-AI Plan Review — Phase 186

External CLIs (Antigravity, Codex) were quota-blocked on 2026-09-27; per the standing fallback,
each plan group was reviewed instead by a fresh-context Claude Opus agent with repo access and a
shared adversarial prompt (`R1`..`R6`). All 29 plans were covered; group assignments:

- R1: 186-01, 186-02, 186-16, 186-29 (summary cards; scripts/analysis deletion)
- R2: 186-03, 186-04, 186-05, 186-06, 186-07, 186-17 (determinism tool, helper promotion, db hygiene, bulk-load primitive, todo 445, Postgres tuning)
- R3: 186-08, 186-12, 186-13, 186-15, 186-18 (kernel registry, feature_factory splits, regime kernel + bundle)
- R4: 186-09, 186-10, 186-14, 186-20, 186-28 (lifecycle shrink, fresh IC jobs/writer, parity + purge, fresh IC on rebuild)
- R5: 186-11, 186-19, 186-21, 186-22, 186-23 (ctx-writer retirement, old-chain code deletion, ops/APR keys, table drops, ic_engine/forward_returns deletion)
- R6: 186-24, 186-25, 186-26, 186-27 (new feature_vectors schema, rebuild writer, gated rebuild run, close-out)

## R1 Review — Claude Opus (fresh context)

**Plans:** 186-01, 186-02, 186-16, 186-29

### Summary

This is a well-evidenced plan set. Nearly every factual assertion I checked against the repo held: the 7-row `gate_evaluations`/`gate_look_log.jsonl` table in 186-01 matches the database exactly; all 18 ledger section 4 rows, the 5 reopened rows (10, 13, 14, 17, 18), every cited doc, migration, todo, milestone report and manifest exists; the three freeze/run commits resolve; the writers table matches actual `INSERT INTO` sites; the 186-16 importer list and test-deletion set match a fresh grep exactly; the sleeve `config.py` import-closure claim (only `__future__` + `dataclasses`) is true; and the 13-name DROP_TABLES list maps completely onto what 186-11, 186-22, 186-23 and 186-27 actually drop. The concerns below are coupling ambiguities and small factual nits, none of which break an invariant or lose data.

### Strengths

- 186-16's importer inventory is exactly right. I reproduced `grep -rnE "(from|import) +scripts\.analysis"` repo-wide; every outside importer is accounted for (5 research tests kept, `test_date_panel.py` and `test_compute_ready_predicate_apr.py` to 186-04, `universe_expansion_promote_compute_eligible.py:34` to 186-04, the rest deleted), and no importer of a surviving module is missed.
- 186-01's `gate_evaluations` table (gate_id/result/run_ts, 7 rows, the unnamed 2026-07-23 look) verified live read-only: identical. The `gate_look_log:2026-07-23T00:26:31.223260Z` ref matches the jsonl `run_ts` byte-for-byte.
- 186-02's 18-row interfaces table verified against `docs/research/construction-verdict-ledger.md` section 4 (18 rows, verdict wordings map onto the 6-value enum including `REJECTED_AS_AXIS` for row 8 and `INCONCLUSIVE` for row 9) and section 2 (exactly rows 10, 13, 14, 17, 18 reopened). Freeze commits `0c33a2596`/`da0548a96`/`f461bdc54` all resolve.
- DROP_TABLES (13) fully reconciles with downstream reality: ctx_events/ctx_snapshots (186-11), 9 chain tables (186-22), forward_returns (186-23), feature_vectors (186-27). No drop plan drops a table outside the list.
- Deletion discipline is strong: pre-delete sha recorded, D-08 greps with recorded output, no archive copies, migrations committed with apply, boundary allow-list verified to contain zero `scripts/analysis/` entries (so nothing to remove there, correctly not listed in files_modified).
- 186-16's measured "95 Python files, ~26.8k lines" is accurate (95 .py + excluded_features.json, 26,843 lines).
- Gate structure is honest: both deletion plans gate on real conditions (process check via ps, card lint with git checks active, STATE.md lane row quoted verbatim in the summary) and stop safely rather than proceeding degraded.

### Concerns

- **MEDIUM — 186-16 gate 3 hardcodes 186-04's discretionary module names.** Task 1 gate 3 requires `scripts/research/date_panel.py`, `cost_hurdle.py`, `feature_matrix.py` to exist, but the outline (186-PLAN-OUTLINE.md:91-96) says 186-04's module names are "Claude's discretion". If 186-04 picks different names, 186-16 false-blocks on a healthy tree. Failure mode: safe stop, but a blocked wave-3 plan needs a re-gate edit. Evidence: 186-16-PLAN Task 1 gate 3 vs outline lines 91-96.
- **MEDIUM — 186-01's git-history checks skip in CI, and the D-06 coverage gate is only as strong as the drop plans' local runs.** The `test` job uses default checkout (`.github/workflows/ci.yml:175`, no fetch-depth; the `fetch-depth: 0` at :94 belongs to `plugin-guards` only), so 186-01's claim is correct, but T-186-01-06's "drop plans run the lint locally" is stated in 186-01, not enforced by 186-22's own text I can see (outline line 273 does say "card lint green" as 186-22's gate). Acceptable, but 186-23 (drops forward_returns) does not name the card lint as a gate anywhere; coverage happens to hold because the card already exists. LOW-to-MEDIUM; worth one line in 186-23's gate.
- **LOW — 186-16's glossary-baseline count is wrong.** Task 2 says "delete the keys for files that no longer exist (the three `scripts/analysis/...` keys today)", but `tools/glossary_baseline.json` has five keys naming files 186-16 deletes: lines 88, 91, 94 (scripts/analysis) plus lines 151, 154 (`tests/unit/sleeve_walk_forward/test_run.py`, `test_synthetic.py`). The general instruction covers all five if followed literally, and stale keys don't fail `check_glossary`, so impact is cosmetic; 186-29's later "any key containing sleeve_walk_forward" sweep would catch the stragglers anyway.
- **LOW — 186-16 Task 2 acceptance `git diff --name-status <pre-delete sha> | grep -v "^D"`** is only correct if evaluated at the deletion commit; after Task 3's edits (migration, docs, README, todo) the same command lists extra non-D files. Ambiguity an executor could misread as a failure or, worse, satisfy early.
- **LOW — line-number drift in cited anchors.** CLAUDE.md `fetch_training_matrix` reference is at line 157, not 159 (186-16 interfaces; plan says re-grep, so harmless). Same class: 186-02 cites ledger "sections 2 and 4 (lines 47-122)" which is approximately right.
- **LOW — 186-02 rule 3's table-extraction heuristic** (`grep -oiE "(from|join)\s+[a-z_]+"` over the script at recipe_commit) will match CTE names and prose words; the `to_regclass`/migration confirmation step mitigates, but expect noisy `tables` lists. Not a correctness risk given the confirmation step.

### Suggestions

- In 186-16 gate 3, replace the three file-existence checks with the name-agnostic condition that actually matters: the two repoint greps print 0 (already present) plus `grep -rnE "(from|import) +scripts\.analysis" scripts/infrastructure tests/unit/scripts` being empty except sanctioned paths. Keep the filenames as an informational note, not a gate.
- In 186-16 Task 2, scope the non-D diff check to the deletion commit (`git diff --name-status HEAD~1 HEAD` at that commit, or `<pre-delete sha>..HEAD` evaluated before Task 3 starts), and say which.
- 186-16 Task 2: correct "the three scripts/analysis/... keys today" to five, or just say "every key naming a path this plan deletes, including the two tests/unit/sleeve_walk_forward keys".
- Consider adding one sentence to 186-23's gate (other reviewer's plan, flag to the phase owner) that the card lint must be green, matching 186-22, since it drops `forward_returns`.
- 186-01: the strict-loader copy from `src/intelligence/research/spec.py:317-338` is a good instinct; add a fixture asserting a YAML `yes`/`on` also parses as a string (YAML 1.1 booleans beyond no/yes pairs), since the resolver copy is subtle.

### Risk assessment

**LOW-to-MEDIUM overall.** No plan asserts anything false that would cause data loss, a broken invariant, or an unsafe execution; every load-bearing repo claim I tested (importers, tables, rows, verdicts, commits, allow-lists) checked out. The residual risk is execution friction: the 186-16 gate's hardcoded sibling-plan filenames could false-block, and the two card plans (01, 02) are heavy transcription work where a mis-copied number is the main hazard; their mitigation (every number pinned to a source with SQL and run date in prose, lint-enforced refs) is the right shape for that.

### Cross-plan checks

- **Names vs outline:** wave numbers match the outline for all four plans (01 w1, 02 w2, 16 w3, 29 w4); depends_on edges match outline rows exactly. Binding names used (`scripts/research/determinism/repro_frozen.py`, `HarnessConfig` import line, `tests/unit/research_tools/test_determinism_modules.py`, card id grammar) are consistent across 01/02/16/29 and the outline.
- **Gate circularity:** none. 01 → 02 → 16 → 29 is a clean chain; 16 gates on 01+02 card lint plus 03's recorded bit-identity plus 04's repoint; 29 gates on 16's survivor set plus lane release. 16's note on 186-13 (`_compute_symbol_tf` importers) is order-independent as claimed: the 11 `hmm_*` importer pilots are deleted by 16, verified they exist and are not in the keep set.
- **Deletion/keep handoff 16 → 29:** survivor set (4 paths) matches what a fresh `git ls-files` implies post-16; `test_config.py`'s rewritten assertion `shift_memory == 504+252+2` matches the actual `HarnessConfig.shift_memory = 758`; the "sleeve config removed" skip in 186-03's byte-equality test is anticipated in 29's scope limits.
- **Card pointers vs deletions:** every `scripts/analysis/` path cited by a 01/02 card will be gone from HEAD after 16/29; the lint's dual check (`recipe_commit:<path>` OR `HEAD:<path>`) plus 16's post-deletion lint rerun and the README "Deleted recipe code" paragraph close this correctly.
- **Boundary allow-list:** `tests/unit/test_market_data_ohlcv_boundary.py` has no `scripts/analysis/` entries, so no same-commit allow-list removal is needed; 186-16's files_modified correctly omits it.
- **186-01 key_links names "downstream drop plans 186-11, 186-22, 186-27"** but not 186-23 (forward_returns drop) — coverage still holds since the card exists; cosmetic.

---

<!-- R2..R6 sections appended below as each reviewer completes; consensus summary written after all six. -->
