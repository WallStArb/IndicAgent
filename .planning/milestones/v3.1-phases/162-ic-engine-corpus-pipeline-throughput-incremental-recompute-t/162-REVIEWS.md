---
phase: 162
reviewers: [codex]
reviewed_at: 2026-07-22T10:32:10Z
plans_reviewed: [162-01-PLAN.md, 162-02-PLAN.md, 162-03-PLAN.md, 162-04-PLAN.md]
---

# Cross-AI Plan Review — Phase 162

**Reviewer selection:** `antigravity` (agy) and `codex` were detected available; `claude` was
skipped as self (`CLAUDE_CODE_ENTRYPOINT=cli`). No `--` reviewer flags were passed, and
`review.default_reviewers` is configured to `["codex"]`, so only **codex** was invoked per the
documented selection precedence (individual flags → `--all` → `default_reviewers` → all
detected). Antigravity was available but not included this run.

## Codex Review

**Summary**

The four-wave sequence is directionally sound: it isolates structural refactors before any fingerprinting, treats the thread-count change as output-neutral, and reserves the cross-run correctness proof for the final wave. The main quality of the plan is that it is empirically gated and explicitly defends against silent stale IC. The main weakness is that `162-03` is a very large correctness surface: fingerprint completeness, invalidation semantics, and legacy skip logic all converge there, so a missed reference or an incomplete watermark will defeat the phase goal even if the unit tests pass.

**Strengths**

- The dependency order is correct: structural churn in `162-01` happens before fingerprinting in `162-03`, which avoids invalidating code-hash fingerprints after they are seeded.
- The plan is careful about statistical integrity: feature-axis chunking is chosen explicitly because time-axis chunking would change the statistic.
- `DO NOTHING` idempotency is preserved by design, which avoids breaking existing expectations around re-runs.
- The fingerprint plan is defense-in-depth, not single-point-of-failure: code hash, APR snapshot, and upstream watermarks all have to align.
- The plan separates output-changing work from output-neutral work, especially in `162-02`, which is the right way to reduce risk.
- The verification model is strong: each wave has targeted tests, and the final wave adds a real DB equivalence harness instead of relying only on unit tests.

**Concerns**

### `162-01`
- **MEDIUM** The extracted cross-sectional helper and the shared feature-block helper are both large behavioral changes in one wave. If either diverges subtly from the existing symbol-side shape, the "bit-identical after each internal step" guarantee becomes hard to prove in practice.
- **MEDIUM** The plan assumes the new feature-blocked helper can be made output-identical while also restructuring the per-scale loop. That is correct in principle, but it is the most regression-prone part of the phase.
- **LOW** The walk-forward extraction is well scoped, but the daily context-features copy has an extra guard that must remain local. That boundary should be called out in the code review checklist, not just in the task text.

### `162-02`
- **MEDIUM** Changing `cross_sectional_bootstrap_threads` from scalar to `dict[str, int]` is a type break, not just a config refactor. The plan updates the obvious call site, but it should also explicitly audit every remaining read path, test fixture, and serialized config consumer.
- **MEDIUM** The "safe pre-migration defaults" story is good, but only if all callers tolerate the field type change before the migration lands. That backward-compatibility assumption should be tested directly.
- **LOW** The benchmark is useful, but it is operationally gated and can become stale quickly. Its role should stay advisory, not prescriptive.

### `162-03`
- **HIGH** The biggest risk in the entire phase is that the fingerprint skip is not actually replacing every existing skip mechanism. If any inner `existing_keys` logic still short-circuits rows after the outer fingerprint check, you can still serve stale or partially recomputed cells.
- **HIGH** The upstream watermark design is expensive and easy to get subtly wrong. If it becomes too query-heavy, the "skip path" may still be materially slow enough to erase most of the throughput gain.
- **HIGH** The watermark strategy is also only as good as its coverage. If any source of IC-relevant mutation is omitted, the phase reintroduces the exact silent-staleness failure it is trying to eliminate.
- **HIGH** The delete-then-insert invalidation path is safer than `DO UPDATE`, but the delete predicate is delicate. A missing key column would either over-delete unrelated rows or under-delete stale ones.
- **MEDIUM** Deleting the `.pkl` checkpoint system is defensible, but it removes a fallback recovery mechanism before the new fingerprint path has been proven in practice. That is acceptable only if `162-04` is truly treated as a hard gate.
- **MEDIUM** The field-classification test is strong, but the plan should also require a grep-level audit of all `ICEngineConfig` consumers so the new dict-based or classification-based logic does not miss a dependent code path.
- **MEDIUM** The plan makes `ic_cell_fingerprints` an upsert target, which is fine, but concurrency behavior is underspecified. If two runs overlap, the last writer wins unless there is a run-level lock or explicit single-run enforcement in `main()`.

### `162-04`
- **MEDIUM** The equivalence harness is the right proof, but the sample design is underspecified. A "~5-symbol subset" can be too small to cover pooled, symbol-side, and cross-sectional branches unless it is deliberately stratified.
- **MEDIUM** `ps aux | grep ic_engine` is a fragile concurrency guard. It can miss edge cases and can also false-positive on its own invocation or wrapper processes.
- **LOW** The no-op wall-clock threshold is valuable, but it is highly environment-sensitive. It should be treated as a performance observation, not a strict CI gate.

**Suggestions**

- Add an explicit audit step before `162-03` for every `existing_keys` reference in `services/ic_engine.py`, not just the main prefilter. The plan currently says "replace the skip," but the inner skip paths need to be removed or made fingerprint-aware too.
- Add a single-run guard in `main()` for the fingerprint phase, ideally an advisory lock or a DB lock, so overlapping runs cannot race on `ic_cell_fingerprints` or delete stale rows concurrently.
- Batch or cache watermark queries in `162-03` by symbol, tf, and regime group. The correctness design is fine, but the main-process precheck must not become the new bottleneck.
- Strengthen `162-02` with a repository-wide search for `cross_sectional_bootstrap_threads` reads and config serialization sites. The type change should be treated as a compatibility boundary.
- Make the `162-04` subset explicitly stratified: include at least one pooled symbol, one symbol-HMM path, one cross-sectional path, and multiple timeframes. Otherwise the harness can pass while missing a branch.
- Replace the `ps aux | grep` gate with a less ambiguous process check or a lock file if the script is intended to be reused operationally.
- Add one test that asserts `_backfill_bh_fdr` still runs over the full window family even when the fingerprint skip count is 100%. That is a critical regression guard for the phase's statistical integrity.

**Risk Assessment**

**HIGH**

The plan is well structured, but the highest-value work is also the highest-risk work: `162-03` changes the system's definition of "already done" and the mechanism that decides whether to trust cached IC. If that logic is incomplete, the system can silently serve stale results downstream, which is worse than a slow run. The phase is still viable, but it needs very tight audit coverage around skip logic, watermark completeness, and invalidation scope to keep the correctness guarantee intact.

---

## Independent Verification (this session, before presenting results)

Codex's single HIGH concern most worth checking against ground truth is the `existing_keys`
completeness claim — a vague "might be incomplete" assertion is cheap to make and expensive to
chase, so it was verified directly against live `services/ic_engine.py` rather than taken on
faith:

**Confirmed real.** `existing_keys` is referenced at 4 call sites beyond the main()-level query
`162-03-PLAN.md` explicitly replaces (`:3448-3460`, before `worker_args`): `ic_engine.py:1049`,
`:1471`, `:1844`, `:2183` — all *inside* the compute functions, doing a finer-grained per-feature
skip (distinct from the whole-cell gate the plan targets). `162-RESEARCH.md` itself names two of
these (`:1049`, `:2183`) as "one step further out" from the main() query, so the gap was known at
research time but the plan's Task 3 action text only says "REPLACE the fingerprint-blind
`existing_keys` skip" (singular) and never states what value — if any — gets threaded to workers
for these inner checks after main()'s `existing_keys` computation is removed.

The concrete risk: if a cell is fingerprint-invalidated, its stale `feature_ic_scores` rows are
DELETEd, and the cell is dispatched to a worker — but if that worker still receives a stale
`existing_keys_frozen` snapshot (captured before the delete, since it was historically computed
once at the top of `main()`), its inner per-feature check could still treat those now-deleted
keys as "already done" and skip recomputing them, leaving the cell's rows permanently missing
rather than merely stale. This is plausibly *worse* than the failure mode the fingerprint was
built to prevent.

**Verdict: CONFIRMED, worth a plan correction before executing 162-03**, not dismissed as
reviewer noise. The other three HIGH items (watermark query cost, watermark coverage
completeness, delete-predicate precision) are legitimate but already substantially mitigated by
the plan's existing design (per-table watermark methods, DB-free in-place-mutation test, exact
cell-key-scoped DELETE) — flagged here as read-during-execution risks, not blocking gaps.

## Consensus Summary

Single reviewer this run (see selection note above) — no cross-reviewer agreement/divergence to
synthesize. Treat Codex's findings as the full external signal for this pass.

### Confirmed-worth-fixing before 162-03 executes
- **`existing_keys` inner-skip completeness** (verified above) — 162-03's Task 3 action must
  explicitly state what happens to the inner per-feature `existing_keys` checks at
  `ic_engine.py:1049/1471/1844/2183` post-refactor. The safest resolution consistent with the
  plan's own design: since the outer fingerprint gate now decides skip-vs-compute at the
  whole-cell level before a worker is ever dispatched, any cell reaching a worker is by
  definition freshly invalidated — so workers should receive an **empty** `existing_keys` (or the
  parameter should be removed from the worker signature entirely), never the pre-delete
  snapshot. This needs to be an explicit task line and an explicit test, not an implicit
  consequence left for the executor to infer.

### Worth a read during 162-03/162-04 execution, not a blocking gap
- Single-run concurrency guard on `ic_cell_fingerprints` writes (no advisory lock currently
  specified — acceptable for now since this is an internal, operator-invoked batch job with no
  scheduler, per this phase's own explicit non-goal, but worth a one-line note in the task if a
  second concurrent invocation is ever plausible).
- Watermark query cost at scale (per-table watermark functions should be batched/cached across
  the corpus rather than issued per-cell, per Codex's suggestion — a performance concern, not a
  correctness one).
- `162-04`'s "~5-symbol subset" should be explicitly stratified (pooled + symbol_hmm +
  cross_sectional + multiple tfs), not left to incidental sample composition.
- `ps aux | grep ic_engine` as a concurrency guard is already only a documented operator
  precondition (checked manually before benchmarking/memory runs), not a coded runtime gate — the
  fragility Codex flags is real but scoped to a human pre-check, not a silent correctness risk.

### Divergent Views
N/A — single reviewer.
