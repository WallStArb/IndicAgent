---
phase: 148
reviewers: [antigravity, codex]
reviewed_at: 2026-07-22T16:10:00.000Z
plans_reviewed: [148-01-PLAN.md, 148-02-PLAN.md, 148-03-PLAN.md, 148-04-PLAN.md, 148-05-PLAN.md]
---

# Cross-AI Plan Review — Phase 148 (Alpha Scoring System)

## Antigravity Review

### Plan 1: 148-01-PLAN.md (Schema Migration & Test Scaffolding)

**Summary:** Establishes `alpha_strategy_scores` and `gate_evaluations`, seeds `alpha.scoring.*` APR keys, creates Wave 0 RED test scaffolds.

**Strengths:** dynamic migration-number lookup avoids collisions; `ON CONFLICT DO NOTHING` idempotent seeding; TDD scaffolding forces clear failing boundaries.

**Concerns:**
- LOW — unbounded `alpha_strategy_scores` growth via `run_ts` with no pruning mechanism.
- LOW — loose JSONB `evidence` field risks structural drift between Gate 1/Gate 2 schemas.

**Suggestions:** add `(gate_id, run_ts DESC)` and `(symbol, tf, run_ts DESC)` indexes; define an explicit schema/dataclass contract for gate evidence.

**Risk:** LOW.

### Plan 2: 148-02-PLAN.md (AlphaScorer Build)

**Summary:** `AlphaScorer(BaseBatch)` aggregates closed `alpha_frames` into decile buckets via `evaluate_frame_gate` reuse.

**Strengths:** reuses frozen bootstrap logic instead of duplicating it; `min_strategy_n` filter guards against noise; safely re-runnable (not OOS-consuming).

**Concerns:**
- MEDIUM — **Signature Mapping Risk:** `evaluate_frame_gate` returns dicts keyed by `tf`/`regime`; if `AlphaScorer` passes a 4-tuple `(symbol, tf, regime, decile)` group key, mapping the result back to individual table columns is custom parsing prone to index errors.
- LOW — exception variable naming discipline (`error` not `exc`) needs developer mindfulness.

**Suggestions:** validate `evaluate_frame_gate`'s actual output shape against a multi-key tuple before coding the remap loop; write a dedicated unpacking helper.

**Risk:** LOW-MEDIUM.

### Plan 3: 148-03-PLAN.md (Gate 1 / Signal Proof Script)

**Summary:** `ops_oos_gate1_signal_eval.py`, locked to Fisher-z (no bootstrap) for baseline comparability.

**Strengths:** methodology lock ensures apples-to-apples OOS-vs-baseline comparison; reads `ensemble_alpha` not `alpha_events` (avoids post-selection bias); fail-loud `oos_start` guard; sha256-audited look-log.

**Concerns:**
- MEDIUM — **Developer Testing Lockout:** the "must be 0 rows" pre-run assertion means any dev-time test execution of the pipeline risks permanently consuming the one-shot gate or polluting the look-log.
- LOW — undeclared `statsmodels` dependency (fdr_bh) could crash if not pre-installed.

**Suggestions:** add a `--dry-run`/`--test-only` flag bypassing DB writes and look-log append; assert `statsmodels` import at setup.

**Risk:** MEDIUM.

### Plan 4: 148-04-PLAN.md (Gate 2 / Execution Proof Script)

**Summary:** `score03_gate2_execution_eval.py`, pairs pooled criteria with a mandatory regime-stratified breakdown across all 5 SHADOW-REVIEW criteria.

**Strengths:** regime-stratified companion prevents a passing pooled average from hiding localized regime failures; APR-driven thresholds; verbatim baseline citation guards against silent divergence.

**Concerns:**
- HIGH — **Group Key Interface Mismatch:** reusing `evaluate_frame_gate` with a custom `group_key=(direction, regime)` risks a crash at the call site if the internal parser assumes a standard `(tf, regime)` shape or doesn't support `direction` as a tuple index.
- LOW — no default APR fallback complicates local mock testing (correct behavior for production, friction for dev).

**Suggestions:** isolate-test the `(direction, regime)` tuple against the real helper signature before committing to the call shape.

**Risk:** MEDIUM.

### Plan 5: 148-05-PLAN.md (Gate Execution & Promotion Record)

**Summary:** Executes Gate 1 → Gate 2 in strict sequence, appends the look-log, writes the promotion decision doc.

**Strengths:** strict D-02 sequencing; pre-run zero-count guards against accidental re-runs; rigid doc-formatting requirements (verbatim numbers, no em-dashes) reduce reporting drift.

**Concerns:**
- HIGH — **Non-Atomic Script Execution:** a network/DB disconnect between the pre-run count check and the final row write leaves an ambiguous retry state (log file vs. DB may disagree on what actually landed).
- MEDIUM — **Conflation of System and Gate Failures:** a statistical FAIL verdict must still produce a `result='fail'` row, not raise an exception that halts the orchestrator — the plan doesn't explicitly distinguish "gate ran and failed" from "gate crashed."

**Suggestions:** wrap the check+write in a single DB transaction so a crash mid-run rolls back cleanly and is safely retryable; explicitly catch statistical-failure outcomes (insufficient N, unstable walk-forward) as valid `result='fail'` writes, not exceptions.

**Risk:** MEDIUM-HIGH.

---

## Codex Review

**Summary:** Well-structured, composition-driven — reuses existing IC/bootstrap machinery, cleanly separates the two OOS gates, defers irreversible live runs to a dedicated wave. Main weakness is operational/methodological fragility rather than basic feasibility: Gate 2's proxy criterion, one-shot sensitivity to query/config drift, and underspecified decile tie-handling.

**Strengths:**
- Clear phase decomposition (migration → build → execution waves), irreversible runs isolated in 148-05.
- Strong reuse discipline: `evaluate_frame_gate`, `frame_gate_passes`, existing Fisher-z path — no reinvented statistics.
- Clean signal-proof/execution-proof separation (148-03/148-04).
- Migration plan explicit about schema, APR seeds, `config_history` auditability.
- Validation scaffolding named and scoped, reducing ambiguity for Wave 2.
- Decision-record wave correctly required to disclose both gates independently, not collapse to one verdict.

**Concerns:**
- HIGH — Gate 2's criterion 5 is an acknowledged operational proxy, not the literal SHADOW-REVIEW criterion; final pass/fail is partly a substitute measurement.
- HIGH — no pre-run snapshot/lock mechanism (query hash, APR values, row counts) before either irreversible gate run; unnoticed filter drift or an upstream data refresh could invalidate the one-shot look with no clean retry path.
- MEDIUM — `NTILE(10)` decile bucketing in `AlphaScorer` has no defined tie-breaking sort; ties on `alpha_score` make decile assignment unstable across runs.
- MEDIUM — scorer deliberately not registered as a systemd/DAG service ("weekly oneshot" language implies recurring operation that doesn't actually exist yet).
- MEDIUM — validation is lighter than the irreversible work warrants: Wave 0 tests are mostly collection stubs; no explicit integration check that migration seeds `config_history`, gate scripts write exactly one audit row, or the look-log is append-only.
- LOW — migration-renumbering fallback (if 248 is taken) leaves the hardcoded `changed_by='migration_248'` audit label able to drift from the actual filename.

**Suggestions:**
- Add a deterministic secondary sort for `NTILE(10)` (e.g. `ORDER BY alpha_score, bar_ts, frame_id`); state the tie policy explicitly.
- Add a pre-run evidence snapshot (SQL/query hash, APR values, row counts) before each irreversible gate execution.
- Mark the criterion-5 proxy explicitly as "proxy pass/fail" in the decision-record schema so it can't be mistaken for the literal criterion.
- Either add minimal service registration now, or rename deliverable language so it doesn't imply a live timer that doesn't exist.
- Add integration-style assertions on the exact `gate_evaluations` payload shape per gate script, not just unit-level/collection checks.
- Derive the migration audit string from the actual file number (or a generic identifier) rather than a hardcoded literal.

**Risk Assessment:** HIGH. Coherent, reuse-based plan, but success hinges on two one-shot live evaluations, exact reproduction of known numbers, and a proxy-based criterion — fragile enough that a small SQL/APR/ordering drift could invalidate the milestone with no clean retry path.

---

## Consensus Summary

### Agreed Strengths
- Strong reuse discipline — both reviewers independently praised avoiding reinvented statistics (`evaluate_frame_gate`/Fisher-z/bootstrap machinery reused, not rebuilt).
- Clean separation of Gate 1 (signal proof) and Gate 2 (execution proof), with irreversible runs correctly isolated to the final execution wave.
- Migration/APR seeding is explicit and auditable.

### Agreed Concerns (highest priority — both reviewers converged independently)
1. **`evaluate_frame_gate` group-key reuse is structurally risky** (Antigravity: MEDIUM on 148-02's `(symbol, tf, regime, decile)` mapping; HIGH on 148-04's `(direction, regime)` mapping). Both flag the same root cause from different call sites: the helper's native output shape may not generalize cleanly to the custom group keys these two new call sites pass in. **Recommendation: verify the actual `evaluate_frame_gate` return shape against both custom group-key tuples in isolation before Wave 2 implementation, not discovered mid-integration.**
2. **Irreversible one-shot gate runs lack a pre-run integrity snapshot and safe-retry story** (Codex: HIGH — no query-hash/config/row-count snapshot before either irreversible run; Antigravity: HIGH — 148-05's check-then-write is not atomic, ambiguous state on a crash between the two). **Recommendation: wrap each gate's pre-run assertion + evidence write in a single DB transaction, and log a pre-run snapshot (config values, row counts) alongside the look-log entry** so a crash mid-run is both diagnosable and safely retryable.
3. **Validation is lighter than the irreversible stakes warrant** (Codex: MEDIUM — Wave 0 tests are mostly collection stubs, no integration check on exact payload shape or look-log append-only-ness; Antigravity: MEDIUM on 148-03's testing lockout — the same "must be 0 rows" guard that makes production runs safe also blocks safe dev-time testing without a dry-run escape hatch).

### Divergent Views
- Codex treats Gate 2's criterion-5 proxy as a HIGH-severity methodological gap; Antigravity didn't flag it at all (it's an already-disclosed, pre-registered design decision per 148-CONTEXT.md D-06, not new information — worth weighing Codex's concern against the fact this was a conscious, documented tradeoff, not an oversight).
- Antigravity raised `alpha_strategy_scores` unbounded growth (LOW) and JSONB evidence-schema drift (LOW); Codex didn't surface either — likely below Codex's severity floor given both are genuinely low-stakes for a milestone-gating phase.
- Codex flagged the migration-audit-label drift risk (LOW) tied to the renumbering fallback; Antigravity didn't independently surface this, though it's a real, cheap-to-fix gap given this project's history of concurrent migration-number collisions.
