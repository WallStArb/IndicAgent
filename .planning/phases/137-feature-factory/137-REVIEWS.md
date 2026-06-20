---
phase: 137
reviewers: [codex]
reviewed_at: 2026-06-20T17:45:00Z
plans_reviewed: [137-P1-PLAN.md, 137-P2-PLAN.md, 137-P3-PLAN.md, 137-P4-PLAN.md, 137-P5-PLAN.md, 137-P6-PLAN.md]
skipped: [claude (self — running inside Claude Code), antigravity (known non-TTY stdout drop bug)]
---

# Cross-AI Plan Review — Phase 137

## Codex Review

**Summary**

The phase plans are well-structured and unusually complete for a multi-service cutover: they separate schema, transport, compute, writer, backfill, and pipeline cutover into ordered waves; they explicitly guard causal correctness; and they use DB constraints plus unit tests to enforce the new contract. The main weakness is internal consistency: a few plan sections disagree on column and placeholder counts, and some operational details are still underspecified enough to create avoidable implementation risk during the backfill and writer retarget.

**Strengths**

- The wave ordering is sound: schema and contract scaffolding first, pure compute second, writer/backfill third, and cutover last.
- Causal correctness is treated as a first-class requirement, especially around forward-only HMM and the `regime_label_source` constraint.
- The plans consistently avoid hardcoding transport/topic strings by routing through `stream_keys.py`.
- The migration plan uses DB constraints to fail loudly on invalid regime labels instead of allowing silent corruption.
- The backfill plan includes resumability via `backfill_status`, which is the right operational safeguard for a long-running historical job.
- The writer retarget plan correctly preserves the proven `BaseWriter` infrastructure instead of rebuilding batching/DLQ/metrics from scratch.
- The archive plan explicitly says "move intact, do not edit," which is the right posture for preserving institutional memory.
- The cutover plan includes a live smoke test and a full unit suite gate, which is appropriate for a release of this scope.

**Concerns**

- **HIGH** - `137-P4-PLAN.md` has an internal contract mismatch: it specifies `42` positional placeholders and a `42`-tuple, but the listed `feature_vectors` insert columns add up to `41` total fields (`6` metadata fields + `35` features). That off-by-one will break either the SQL or the param builder unless corrected.
- **HIGH** - `137-P1-PLAN.md` mixes two incompatible counts for the same schema: it says "36 typed columns" in the success criteria, but the acceptance criteria correctly expect `41` total columns. That wording is confusing enough to produce a wrong implementation or a false validation expectation.
- **HIGH** - `137-P5-PLAN.md` does not checkpoint the fetch stage separately from the compute stage. If the IBKR fetch is interrupted midway, the plan implies the job will re-download without a resume boundary, which is expensive and can make operational recovery messy.
- **HIGH** - `137-P5-PLAN.md` defines `theoretical_max` only as "TF bar-seconds × depth," but that is too vague for an accuracy gate. The plan needs a precise bar-count formula per timeframe, especially because trading calendars, market closures, and warm-up bars can all skew the count.
- **MEDIUM** - `137-P3-PLAN.md` is ambiguous about the `FeatureFactory` config contract: one section says `compute()` takes `config`, another says the factory stores a frozen config and reads from `self._config`. That duality is easy to implement inconsistently and should be made single-source.
- **MEDIUM** - `137-P5-PLAN.md` uses hardcoded operational numbers like a `500`-bar warm-up window and `~500` row batch inserts. Those are not feature thresholds, but they still violate the project's general anti-hardcoding discipline unless they are explicitly justified or made configurable.
- **MEDIUM** - `137-P6-PLAN.md` assumes a repo-wide import sweep will be enough to make archiving safe, but it does not explicitly address package-level `__init__.py` re-exports, test helper imports, or any code that dynamically imports archived paths. That can still produce collection-time import errors.
- **MEDIUM** - `137-P4-PLAN.md` says the writer should parse malformed payloads into DLQ batches, but it does not explicitly define how to handle partially valid nested `FeatureVector` payloads versus entirely wrong schema payloads. That distinction matters for DLQ correctness.
- **LOW** - `137-P6-PLAN.md` leans on `systemctl`-driven smoke testing, which is realistic operationally but brittle as a validation gate. A controlled integration harness would be easier to repeat.
- **LOW** - `137-P1-PLAN.md` enforces the `smoothed` rejection at the DB level, but the plan does not also mention a runtime assertion in the backfill/pipeline code path. The DB check is sufficient for integrity, but a loud runtime check would make the failure easier to diagnose.

**Suggestions**

- Fix the `41` vs `42` inconsistency in `137-P4-PLAN.md` before implementation starts.
- Rewrite the `137-P1-PLAN.md` schema wording so it clearly distinguishes "41 total columns" from "35 feature floats + 6 metadata fields."
- Define `theoretical_max` in `137-P5-PLAN.md` as an exact bar-count function per timeframe and trading calendar, not a rough depth estimate.
- Add an explicit checkpoint for the fetch stage in `137-P5-PLAN.md`, or state clearly that the fetch stage is intentionally idempotent and stateless.
- Collapse the `FeatureFactory` config contract in `137-P3-PLAN.md` to one form only: either constructor-held frozen config or explicit `config` argument, not both.
- Make the backfill batch size and warm-up size configurable, or document why those two numbers are intentionally operational and not APR-controlled.
- Add an explicit "no package re-export breakage" note to `137-P6-PLAN.md`, including a test-collection pass after archive moves.
- Clarify the DLQ split in `137-P4-PLAN.md` between parse failure, schema mismatch, and transport failure.
- Consider adding a lightweight integration smoke harness for cutover validation so the final gate is not tied entirely to systemd/service state.
- Add a one-line note in `137-P1-PLAN.md` or `137-P6-PLAN.md` that the `alpha.` prefix change is a code-level control-plane change, not a migration change, so it is not accidentally rolled back with the SQL.

**Risk Assessment**

HIGH — The overall plan is strong, but this is a coordinated rebuild of the intelligence layer with multiple live-path dependencies, historical backfill, and archive moves. The phase is also carrying concrete internal inconsistencies including the writer placeholder count mismatch and the schema count wording mismatch. Those are fixable, but until they are cleaned up, the risk of implementation drift or a late-stage cutover failure is high.

---

## Consensus Summary

Only one external reviewer (Codex) ran. Summary reflects Codex findings only.

### Agreed Strengths

- Wave ordering is correct: schema/contracts → compute → writer/backfill → cutover
- Causal correctness (forward-only HMM, `regime_label_source` DB constraint) treated as first-class
- `stream_keys.py` routing enforced — no hardcoded topic strings
- `backfill_status` checkpoint/resume is the right safeguard for a 232-pair job
- `BaseWriter` reuse for feature_writer is correct — proven infrastructure preserved
- Archive-intact-without-modification is the right posture

### Agreed Concerns (action required before execution)

1. **[HIGH] Column count mismatch** — P1 says "36 typed columns" (35 features + pipeline_version) but does not account for metadata columns (symbol, tf, bar_ts, regime, regime_label_source, pipeline_version = 6). P4 says 42 placeholders but 6+35=41. One of these counts is wrong. Resolve before P4 execution.
2. **[HIGH] Backfill theoretical_max is underspecified** — "TF bar-seconds × depth" is too vague to be a verification gate. Needs an exact formula accounting for trading calendar, market closures, warm-up bars.
3. **[HIGH] Backfill fetch stage has no checkpoint** — If the IBKR fetch is interrupted mid-run, the job re-downloads from scratch. Either make fetch idempotent (already-fetched symbols skip) or add a fetch-stage checkpoint to `backfill_status`.
4. **[MEDIUM] FeatureFactory config contract is ambiguous** — P3 describes both constructor-held `self._config` and `config` as a compute() argument. Pick one before implementation.
5. **[MEDIUM] `__init__.py` re-exports not covered in archive sweep** — P6 import sweep may miss package-level re-exports and test helper imports, causing collection errors.

### Divergent Views

N/A — single reviewer.
