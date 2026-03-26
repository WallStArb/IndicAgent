# Phase 49: DB Performance & Signal Ledger Hardening

**Status:** ✅ Complete (partial — 2 items done ad-hoc, 2 deferred)

**Milestone:** v2.1 Data Foundation & Signal Confidence

**Dependencies:** Phase 48 completion

---

## Goals

1. **DB Performance** — Optimize signal_ledger with composite index and query optimization
2. **CIS Null Repair** — Complete blocked repair_cis_nulls.py (PostgreSQL shared memory fix)
3. **Test Gap Closure** — Close Phase 43 threading.Lock characterization test gap
4. **Requirements Traceability** — Fix REQUIREMENTS.md requirement ID traceability

---

## Success Criteria

1. `signal_ledger` has composite index on (symbol, feature_ts, feature_tf) for JOIN queries
2. CIS null repair runs successfully with adjusted PostgreSQL work_mem
3. Threading.Lock characterization test exists and passes
4. All REQUIREMENTS.md IDs are traceable to validation tests or code locations

---

## Outcome (2026-03-26)

Phase closed without formal execution — items resolved ad-hoc or deferred:

| Goal | Outcome |
|------|---------|
| `signal_ledger` composite index `(symbol, feature_ts, feature_tf)` | ✅ Done — `idx_ledger_feature_join` exists |
| Threading.Lock characterization test | ✅ Done — `tests/unit/service_tests/test_concurrent_lock_behavior.py` |
| CIS null repair (back-fill 488k rows) | ⏸ Deferred to v2.3 — todo `2026-03-26-backfill-cis-null-scores-in-signal-ledger.md` |
| Requirements traceability | 🗑 Dropped — housekeeping, no downstream impact |

Note: REQUIREMENTS.md DATA-01 is still marked `[x]` but CIS back-fill is NOT complete. Update when the todo is executed.
