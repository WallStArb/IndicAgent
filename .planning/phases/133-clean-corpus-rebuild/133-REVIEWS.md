---
phase: 133
reviewers: [codex]
reviewed_at: 2026-06-18T05:50:00Z
plans_reviewed: [133-01-PLAN.md, 133-02-PLAN.md, 133-03-PLAN.md, 133-04-PLAN.md, 133-05-PLAN.md, 133-06-PLAN.md, 133-07-PLAN.md]
---

# Cross-AI Plan Review — Phase 133

## Reviewer Status

| Reviewer | Status | Notes |
|----------|--------|-------|
| codex | ✓ success | OpenAI Codex v0.128.0 |
| antigravity | ✗ skipped | Known non-TTY stdout drop bug (agy -p silently drops response when stdout is not a TTY; no PTY workaround available — `unbuffer` not installed, `script` captures only boilerplate) |
| claude | ✗ skipped | Running inside Claude Code — skipped for independence |
| ollama | ✗ timeout | qwen3.5:4b timed out on 14KB prompt |

---

## Codex Review

**Summary**
The phase is broadly well-structured: it separates verification, schema change, destructive reset, replay, integrity validation, and final closure in the right order. The main weakness is operational specificity, not architecture: the plan is strong on intent, but several steps need tighter execution details to avoid silent data corruption, especially around the trade-frame hypertable migration, the new `signal_ts` writer requirement, and the acceptance gates for `ctf_score` and replay integrity.

**Strengths**
- The wave ordering is sensible: cleanup before schema change, schema change before truncation, truncation before backfill, and replay verification before acceptance.
- The plan correctly treats Plan 01 as verification/documentation closure, not a needless migration, which matches the current schema mapping in `src/intelligence/schemas.py`.
- The hypertable migration sequence is directionally correct and matches the existing 3-table schema dependency model.
- The plan recognizes the `signal_ts` FK-anchor requirement for `trade_executions`, which is the right model for a hypertable-backed `trade_frames`.
- The acceptance criteria are materially better than a simple row-count check: they explicitly look for degenerate `ctf_score`, low `stopped_at_entry`, and hypertable status.
- B4/B5/B2/B3 are correctly placed before the rebuild, because those are prerequisite correctness fixes, not post-hoc cleanup.

**Concerns**
- **HIGH**: Plan 03 says to create `production/migrations/146_trade_frames_hypertable.sql`, but `146_phase132_trade_framer_apr.sql` already exists in the repo. That is an execution ambiguity and a real risk of overwriting or misordering migrations. **[VERIFIED: `production/migrations/146_phase132_trade_framer_apr.sql` confirmed present — migration must be renumbered to 147 or higher]**
- **HIGH**: Plan 03 only names `lifecycle_replay.py`, but the new non-null `trade_executions.signal_ts` requirement affects every execution writer. Any missed writer will hard-fail after the migration.
- **HIGH**: The lifecycle replay script uses manual transaction control and long-running batch processing; changing B2 to `async with conn.transaction()` needs care to preserve `commit_every` semantics and not accidentally wrap the whole replay in one giant transaction.
- **HIGH**: The acceptance criteria do not explicitly include the integrity counters from `_verify_replay` as hard gates in Plan 06, even though those are the strongest protection against silent corruption. The plan mentions them in Plan 05, but Plan 06 should repeat them as certification criteria.
- **MEDIUM**: The cold-start `ctf_score=0.0` exception is conceptually correct, but the plan does not define the exclusion rule precisely enough. Because `0.0` is a valid non-null value, the 85% gate will fail unless the first bar of each `(symbol, tf)` is explicitly excluded or the count of such bars is verified small enough to not affect the gate.
- **MEDIUM**: An 85% `ctf_score > 0.05` threshold is a useful floor, but it is not sufficient by itself for corpus quality. A localized failure in one symbol or timeframe could still pass globally. The plan should require per-symbol and per-timeframe breakdowns.
- **MEDIUM**: Plan 02's rename of `confidence_utils.py` to `confidence.py` is a large mechanical change across many imports. The repo has many consumers — the plan should explicitly require a full import sweep and compatibility verification.
- **MEDIUM**: Plan 01's live DB verification is reasonable, but it should pin the exact environment and output artifact so the verification is reproducible, not a one-off check.
- **LOW**: Deleting phase-127 scripts may reduce auditability unless they are archived. For a financial corpus rebuild, keeping historical artifacts is usually safer than hard deletion.

**Suggestions**
- Rename the hypertable migration to a unique, non-conflicting filename (147 or higher) and update Plan 03 to reference the correct file.
- Expand Plan 03 into a writer inventory checklist: list every `INSERT INTO trade_executions` callsite, update them all before applying the FK change, add a dry-run or unit test that fails if any insert path omits `signal_ts`.
- Make the cold-start exception operational: exclude the first bar per `(symbol, tf)` explicitly, record the expected count of cold-start rows (~316), assert that the exclusion set is exactly what you expect.
- Strengthen acceptance criteria: require `_verify_replay` counters to be exactly `0/0/0` in Plan 06 as well, require per-symbol and per-timeframe `ctf_score` distributions, require a consistency check between `signal_events`, `trade_frames`, and `trade_executions` counts.
- Add structural integrity checks to Plan 06: no orphan `trade_frames`, no `trade_executions` with missing `frame_id` anchors, `trade_frames` composite PK and hypertable status confirmed in the same run.
- For B2, preserve `commit_every` behavior explicitly in the implementation plan so the replay remains chunk-committed during long runs.
- For Plan 05, name the exact `_verify_replay` invocation and make it a hard gate, not a log-parsing convenience.
- For Plan 07, separate "final cleanup" from "merge/push" so rollback boundaries are clearer if acceptance fails late.

**Risk Assessment**
**HIGH** — The plan is directionally correct, but it combines a destructive corpus wipe, a schema rewrite, and multiple writer-path changes in one phase. That is inherently high risk in a financial intelligence system, because the worst failure mode is not a crash but a silently biased corpus that still passes superficial checks. The migration sequence itself is sound, but the plan needs tighter operational controls, explicit writer coverage, and stronger acceptance gates before it is execution-ready.

---

## Consensus Summary

Single reviewer (Codex) — no multi-reviewer consensus available. Key findings from Codex:

### Agreed Strengths
- Wave ordering is correct (cleanup → schema → truncate → backfill → lifecycle → acceptance)
- D-05 items correctly placed as prerequisites, not post-hoc cleanup
- Acceptance criteria are substantive (degenerate ctf_score check, stopped_at_entry rate, hypertable confirmation)
- signal_ts FK-anchor design for trade_executions is architecturally sound

### Agreed Concerns (Actionable Before Execution)

1. **Migration number collision (HIGH):** Plan 03 targets `146_trade_frames_hypertable.sql` but `146_phase132_trade_framer_apr.sql` already exists. The migration must be renumbered — next available appears to be 147.

2. **Writer coverage gap (HIGH):** Plan 03 scopes the `signal_ts` fix only to `lifecycle_replay.py`. Every INSERT INTO trade_executions across the entire codebase must be updated before applying the migration, or the first writer that doesn't include `signal_ts` will hard-fail with a NOT NULL constraint violation.

3. **B2 transaction batch semantics (HIGH):** Replacing manual COMMIT with `async with conn.transaction():` must preserve the `--commit-every N` batching behavior. Wrapping the entire per-symbol loop in one transaction defeats the purpose and risks a multi-hour single transaction.

4. **_verify_replay not in Plan 06 gates (HIGH):** The three-counter gate (stale_unresolved=0, target_no_pnl=0, orphan_signal_events=0) should be a formal D-04 gate in the acceptance report, not just a Plan 05 artifact. It is the primary protection against silent corpus corruption.

5. **ctf_score gate precision (MEDIUM):** The 85% threshold is computed globally. A broken symbol or TF could still pass. Per-symbol breakdown should be part of the acceptance report.

### Divergent Views
N/A — single reviewer.

---

*To incorporate this feedback:*
- Fix migration number in Plan 03 (146 → next available)
- Add explicit writer inventory task to Plan 03
- Add B2 batch-commit preservation note
- Add _verify_replay counters as a D-04 gate in Plan 06
