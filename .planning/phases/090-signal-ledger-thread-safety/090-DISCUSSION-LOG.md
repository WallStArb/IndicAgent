# Phase 090: Signal Ledger Hardening + Thread Safety - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-19
**Phase:** 090-signal-ledger-thread-safety
**Areas discussed:** Context adequacy review, THREAD-02 status, Renaissance-grade test design, missing call site tracking, snapshot() lock-free documentation

---

## Context Adequacy (existing CONTEXT.md review)

User asked whether existing context was sufficient for a "Jim Simons / Renaissance" standard, demanding modularity, reuse, separation of concerns, automation over manual work, and balance of efficiency with simplicity.

Code audit revealed:

| Finding | Status |
|---------|--------|
| THREAD-02 (CacheManager asyncio locks) | Already shipped in Phase 089 — context was stale |
| THREAD-01 (settings.py RLock) | Not done — still needed |
| LEDGER-01/02 (to_insert_params → _to_row) | Not done — still needed |
| Test coverage gap vs fleet standard | Missing — no tuple-count guard test |
| test_pipeline_attribution.py:94 call site | Not tracked in canonical_refs |
| snapshot() lock-free intentionality | Not documented |

---

## Gaps to Fold into Phase 090

| Option | Description | Selected |
|--------|-------------|----------|
| Mark THREAD-02 complete | Update context so planner knows CacheManager locks are shipped | ✓ |
| Add tuple-count guard test | Dynamic _INSERT_SQL count vs len(_to_row()); self-maintaining | ✓ |
| Track test_pipeline_attribution.py call site | Add to canonical_refs as rename target | ✓ |
| Document snapshot() lock-free intentionality | Add code comment + CONTEXT note explaining asyncio invariant | ✓ |

**User's choice:** All four gaps folded in. Reiterated Renaissance principle: automate everything, no manual tasks, prefer dynamic assertions over hardcoded constants.

**Notes:** User specifically requested that the test NOT hardcode 65 — parse `_INSERT_SQL` dynamically (regex `\$\d+` count). This mirrors the principle of "instrument everything" applied to schema correctness.

---

## Claude's Discretion

- Exact field-name comment style in `_to_row()` — follow `feature_writer_agent._record_to_insert_params()` verbatim
- Whether snapshot() comment lands in Plan 01 or Plan 02 (Plan 02 more natural)
- Import placement for `re` in test file (standard library, top of file)

## Deferred Ideas

- Full asyncpg named-parameter support — would require a custom wrapper layer; complexity not justified
- Signal ledger schema column reduction — data migration required; v2.7 cleanup
- Removal of `_active_contracts_cache` globals — deferred to CacheManager migration phase
- RLock contention metric — lock is uncontested >99.9% of the time; overhead not worth instrumenting given simplicity principle
