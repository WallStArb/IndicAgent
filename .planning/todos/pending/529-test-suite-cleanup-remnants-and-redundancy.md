# 529: Test-suite cleanup: delete remnants of deleted systems, consolidate redundancy, cut runtime

Filed: 2026-10-10
Owner: pending
Priority: P1 (owner directive; the suite burns time and tokens every session)
Evidence: /tmp/test_suite_audit.md (2026-10-10 audit; regenerate before deleting)

Owner directive 2026-10-10: "cleanup and organize all tests; many are remnants of old
code and many redundant; the suite burns way too much time and tokens."

Rules for the pass:
- Nothing deletes without evidence: the audited report must show the subject under
  test no longer exists (deleted in 185-45 / the v2.x archive) or a duplicate with a
  named survivor.
- Remnants of the v2.x I1-I7 path, the I8 AI stack, AlphaEngine, ensemble_trainer,
  the old ic_engine, forward_returns and the Tradier loader are the first targets;
  vacuously-passing tests are worse than none.
- Consolidation prefers one load-bearing test over three stale ones; renaming to the
  live concept beats deletion when the coverage is real.
- Speed wins second: module-scoped fixtures for per-test recomputation, stubs for
  disk/network, before any deletion of slow-but-load-bearing tests.
- CI must stay green at every commit; run the full unit suite per batch.

Deliverables:
1. Deletable-now list executed in batches with per-batch full-suite runs.
2. Redundancy consolidations with the surviving test named.
3. Speed fixes for the top offenders that survive.
4. A recorded baseline (runtime, counts) before/after.
