# Phase 49: DB Performance & Signal Ledger Hardening

**Status:** 📋 Planned

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

## Plans

(TBD — Planning will occur when Phase 48 is complete)
