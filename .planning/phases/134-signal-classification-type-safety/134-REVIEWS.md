---
phase: 134
reviewers: [codex]
reviewed_at: 2026-06-18T10:42:00Z
plans_reviewed: [134-01-PLAN.md, 134-02-PLAN.md, 134-03-PLAN.md]
reviewer_notes: |
  antigravity: headless capture unavailable (non-TTY stdout drop, known v1.107.0 bug — see memory feedback_review_tooling)
  ollama: connection timeout on generation (model not loaded)
  claude: auto-skipped (running inside Claude Code — not independent)
---

# Cross-AI Plan Review — Phase 134: Signal Classification Type Safety

## Codex Review

**Summary**

The phase direction is good, but the plans are not yet complete enough to be safe for a live system with strict integrity requirements. Plan 01 misses at least one live write path and has an unresolved mismatch with the existing `condition_expired` transition; Plan 02 does not cover all `entry_type` literal sites in `src`; Plan 03 underestimates the operational cost of converting live tables, especially the hypertable, to native PG ENUMs. As written, the biggest risk is a schema change that is technically correct in isolation but breaks current runtime behavior or leaves write paths inconsistent.

**Strengths**

- The three-wave split is sensible and keeps the changes isolated.
- The plans respect the core contract model: Python enums for code, PG constraints/enums for the database.
- Migration sequencing is aligned with the phase numbering convention.
- Plan 01 correctly recognizes that backfill logic must mirror the runtime classifier.
- Plan 03 correctly separates `exit_reason` from the classification enum space.

**Concerns**

*Plan 01*

- **HIGH:** The plan only names `lifecycle_replay.py`, but `trade_executions` inserts also happen through the repository layer in `src/persistence/repository/signal_events_repository.py:294` and `:537`. If that live path is not updated, `outcome` will still be missing on production writes.
- **HIGH:** The current lifecycle code emits `condition_expired` as an outcome in `src/intelligence/trading/lifecycle_tracker.py:357`, but `SignalOutcome` only contains 8 values. A CHECK constraint enumerating only the 8 enum values will reject any row that persists `condition_expired` verbatim.
- **HIGH:** The market-entry replay path currently treats stop exits as `outcome=None` and only writes rows when `outcome is not None` (around `lifecycle_replay.py:662`). If the plan expects `trade_executions.outcome` for every exit event, it needs an explicit classification branch for market stop exits.
- **MEDIUM:** The backfill SQL must match `_classify_stop_outcome()` exactly, including the `bars_in_trade_count is None` branch (`lifecycle_tracker.py:556`). Drift between SQL and Python is a silent wrong-answer risk.
- **MEDIUM:** Adding a CHECK on a large live table can be expensive. The plan should state whether the constraint is added in one transaction, validated later, or applied during a maintenance window.

*Plan 02*

- **HIGH:** The file list is incomplete. There is still a bare `entry_type` reference in `src/intelligence/ai/narrative/narrative_prompts.py:75`, which is outside the listed edit set. If the goal is zero bare literals in `src/`, this file must be included.
- **MEDIUM:** `signal_schema.py` still defaults `entry_type` to `"at_close"` as a bare string literal. Acceptable if `EntryType` remains a `str` subclass, but should be addressed if the goal is complete type safety.
- **MEDIUM:** The plan should explicitly cover every caller that constructs or forwards `entry_type`, not just `trade_framer.py` dependents. The framing and narrative layers both have hardcoded assumptions.
- **LOW:** Should include a preflight audit of current `trade_frames.entry_type` values before applying the constraint on a live table.

*Plan 03*

- **HIGH:** The plan underestimates migration risk for live tables, especially `signal_events` as a TimescaleDB hypertable. Converting `signal_events.status` to a PG ENUM requires a table rewrite or will acquire long locks. Needs an explicit downtime/maintenance strategy, not just a DDL sequence.
- **HIGH:** The "phantom value" assumption is not safe as written. `chandelier_stop` and `condition_expired` are still emitted by live lifecycle code (`lifecycle_tracker.py:343` and `:368`). The audit may show zero rows in one corpus, but the code path proves they are not phantom in the general sense.
- **MEDIUM:** The transition from TEXT+CHECK (Plan 01) to native ENUM (Plan 03) for `outcome` should be explicitly documented — including how existing non-enum values are normalized or excluded before the cast.
- **MEDIUM:** The verification plan needs insert-level coverage, not just row-distribution checks. The critical failure mode is "valid business value rejected by ENUM" — best caught by round-trip insert tests against each live writer.
- **LOW:** Documenting phantom exit reasons in comments is appropriate but is not a substitute for the pre-migration audit.

**Suggestions**

- Add `src/persistence/repository/signal_events_repository.py` to Plan 01 and update `_INSERT_TRADE_EXECUTIONS_SQL` plus `record_execution()` so the live execution path persists `outcome`.
- Decide explicitly whether `condition_expired` is a persisted classification, a transient runtime label, or a remapped outcome. The current plan leaves this unresolved — it surfaces in Plan 01 (CHECK constraint) and Plan 03 (phantom assumption).
- For Plan 02, run a repo-wide grep for all 5 entry_type strings before calling the plan complete. Expand the edit set beyond the listed files.
- For Plan 03, split the migration into "create types" → "audit and normalize data" → "alter column types" with an explicit operational window for the hypertable conversion.
- Add tests that exercise the actual writer paths, not just enum equality: repository insert, replay insert, and a failure case for `condition_expired` if it remains unresolved.
- Consider centralizing outcome normalization in one helper used by both runtime and backfill so SQL does not have to duplicate classifier logic.

**Risk Assessment:** **HIGH**

The plans touch live schema enforcement and multiple write paths, but currently miss at least one production writer and do not resolve the existing `condition_expired` label mismatch. Plan 03 also carries meaningful lock/rewrite risk on a live hypertable. Feasible, but plans need tightening before execution.

---

## Consensus Summary

Only one reviewer produced output (codex). Antigravity is blocked by a non-TTY stdout capture bug; Ollama timed out on generation; Claude auto-skipped for independence.

### Key Findings (All HIGH)

1. **Missing live write path** — `signal_events_repository.py` writes to `trade_executions` outside `lifecycle_replay.py` and is not in Plan 01's scope. Outcome will be NULL on production writes.

2. **`condition_expired` is unresolved** — Lives in lifecycle code, not in `SignalOutcome`. The CHECK constraint will reject it. Plan must decide: add to `SignalOutcome`, remap it, or remove the code path.

3. **Hypertable lock risk** — `signal_events` is a TimescaleDB hypertable. `ALTER COLUMN ... TYPE signal_status_type` will rewrite it or lock it. Plan 03 needs an explicit maintenance strategy.

4. **Incomplete literal sweep (Plan 02)** — `narrative_prompts.py:75` contains a bare entry_type reference outside the planned file list.

5. **Phantom values aren't phantom** — `chandelier_stop` and `condition_expired` are live code paths, not dead code. Zero rows in current corpus ≠ safe to exclude from PG ENUM.

### Recommended Pre-Execution Fixes

Before running `/gsd-execute-phase 134`:

1. Add `signal_events_repository.py` to Plan 01 scope; audit and update `record_execution()` to write `outcome`
2. Decide `condition_expired` fate — either add `CONDITION_EXPIRED = "condition_expired"` to `SignalOutcome` or remove the code path from `lifecycle_tracker.py`
3. Add a preflight: `grep -rn '"at_close"\|"at_pullback"\|"at_limit"\|"at_reclaim"\|"zone_proximal"' src/ --include="*.py"` and include all hits in Plan 02
4. Add a maintenance window note to Plan 03 for the `signal_events` hypertable conversion
5. Add round-trip insert tests to Plan 03 acceptance criteria
