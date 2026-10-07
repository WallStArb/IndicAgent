# 185-33 resume note (paused 2026-10-07 by owner request, low session tokens)

## Done
- No task committed. No migration applied (449 not written; `ls production/migrations` showed 448-452 free, 453/454 present).
- No live change made. No process started. 186 files not touched.

## Uncommitted files (RED tests for Task 1, untracked, not yet run)
- tests/unit/test_bar_integrity_apr_migration_contract.py (three keys: session_coverage_min_1d 0.999 float, vendor_ratio_run_min_sessions 5 int, report_max_age_hours 30 int; all [initial_estimate], not ML targets; header must name bar_reconciliation_audit.py, 185-33, section 6 and the four zero-tolerance checks; D7 source must contain each key literal)
- tests/unit/bars/test_vendor_basis.py (API: BasisRun, find_basis_runs, classify_run(run, ibkr, tradier, splits, *, tolerance_bp), ratio_pairs, canonical_vendor, blocking, VENDOR_IBKR/VENDOR_TRADIER; RJF run ends 2021-09-21 ratio 0.667 tradier continuous; REX run ends 2025-09-08 ratio 2.0 ibkr continuous)

## Exact next step
1. Write tests/unit/bars/test_integrity_checks.py, run the three test files (must fail), commit RED with explicit pathspecs.
2. Write migration 449 (template: 454), re-check the number, apply with psql -f under lock_timeout, implement vendor_basis.py and integrity_checks.py, commit GREEN together with the migration.
3. Task 2 and 3 as in the plan.

## Design decisions reached (from reading D7, daily_rule, bar_derivation, views)
- Pure judge per name in D7, IO loader per name; reuse by import from services/bar_derivation.py: _SELECT_DAILY_OBSERVATIONS_SQL with _D2V2_ROUTES, _SELECT_DAILY_SPLITS_SQL, _SELECT_POLICY_1D_SQL, _SELECT_STORED_1D_SQL, _SELECT_1D_FLAG_RULES_SQL, _SELECT_CURRENT_1D_DIGESTS_SQL, _month_digest_rows, _epoch_seconds; CANONICAL_1D_SOURCES; derive_daily_v2 and current_closes from daily_rule.
- canonical_recompute: write_contract.classify(incoming, stored, removal_scope=all stored keys); findings = new + changed + removed dates (stricter than the stage's span scope).
- digest_fresh: recompute months exactly as write_1d_digests (non-quarantine flag rules per row, empty months in range included) and also require rule_version d2-v2.
- lineage_missing: one set-based read of the canonical_bar_lineage view (request_ids IS NULL) left-joined to market_data_ohlcv_tradeable for visibility (185-38 measured 42 s); hidden NULL rows feed untraced_quarantined_1d (informational, passed true).
- refused_head_1d: len(derive_daily_v2(...).refused_head), informational.
- session_coverage: stored bar dates plus answered-empty sessions (ohlcv_empty_history 1d spans and TRADIER no_data windows; IBKR SMART no_data alone is not evidence, since IBKR history starts at the last venue move) over NYSE sessions from first bar to the last completed session; sessions built once from the policy's earliest valid_from. Dead names will fail on their tail: report, do not adjust.
- policy_conformance: over all stored rows (stricter than visible); expected label tradier or ibkr_named per resolve_policy; ibkr_fallback only when the policy fallback is ibkr and no Tradier observation on that date.
- vendor_basis_run: pairs from current_closes; blocking only when the classified continuous vendor is not the canonical vendor of the run's stored bars; undecided runs reported, not blocking (must_haves wording).
- unexplained_seam: per-name split of the existing _seams result samples.
- report_age: passed when the latest 1d ohlcv_load is not after the run start; metric = hours from that load to run start; threshold = report_max_age_hours.
- Writes: emit_integrity_facts_async in one transaction per name group, monitor_type bar_integrity, subject SYM|1d; add "threshold.bar_integrity.%" to D7 _APR_PATTERNS.
- Possible Rule 1 fix seen: D7 ALLOWED_SOURCES["1d"] lacks ibkr_fallback, so stray_sources may flag 128,785 fallback rows in its window; confirm on the live run.
- Unit file has no TimeoutStartSec (oneshot default: no timeout).
- Orchestrator brief vs plan: the plan (amended) drops mixed_source_names and moves check_d2_landed and the 186 note to 185-41; follow the plan and report it.
