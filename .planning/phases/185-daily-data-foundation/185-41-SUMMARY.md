---
phase: 185-daily-data-foundation
plan: 41
subsystem: data-integrity
tags: [verdict-gate, promotion, rebuild-preconditions, d7, grafana, alerts]
requires: [185-33, 185-40]
provides:
  - "verdict_gate: REQUIRED_CHECKS, gate_symbols, fetch_verdict_scan (src/intelligence/bars/verdict_gate.py), one gate for promotion and the rebuild"
  - "COMPUTE_READY predicates over the latest bar_integrity verdicts (no backfill_status)"
  - "check_d2_landed, check_bar_coverage, check_data_layer_final_landed read verdicts (services/rebuild_preconditions.py)"
  - "live D2 test on the d2-v2 design (read-only connection)"
  - "four D7 alert gauges and five Grafana rules"
affects: [185-42, 185-43, 185-45, 189-10, 189-11, 186-26]
key-files:
  created:
    - src/intelligence/bars/verdict_gate.py
    - tests/unit/bars/test_verdict_gate.py
    - .planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-NOTE-185-41-verdict-gate.md
  modified:
    - scripts/infrastructure/instrument_compute_eligibility_audit.py
    - scripts/infrastructure/universe_expansion_promote_compute_eligible.py
    - tests/unit/scripts/test_compute_ready_predicate_apr.py
    - services/rebuild_preconditions.py
    - tests/unit/test_rebuild_preconditions.py
    - tests/integration/test_d2_single_writer_live.py
    - services/bar_reconciliation_audit.py
    - tests/unit/services/test_bar_reconciliation_audit.py
    - production/grafana/provisioning/alerting/alert-rules.yml
decisions:
  - "The promote script takes candidates from the SQL predicate and re-judges candidates and holds with the pure gate; any disagreement raises, so the two renderings of REQUIRED_CHECKS cannot drift silently"
  - "A scan that judged no symbols fails (an empty gate proves nothing); a timeframe with no required checks is refused, never passed"
  - "Alert queries wrap each gauge in last_over_time over 36 h: D7 is a daily oneshot and the collector's Prometheus exporter drops its series minutes after the run"
  - "The report age gauge is the age of the previous report when this run began; the stale rule alerts on no data (a missed run) and on age above the APR maximum, comparing two gauges"
requirements: [D-06, D-07, D-26, D-28]
metrics:
  completed: 2026-10-07
---

# Phase 185 Plan 41: Verdict-based gates Summary

Promotion and the phase 186 rebuild now read the same computed `bar_integrity` verdicts through one pure gate, `fetch_complete` is no longer read by either, the live D2 test asserts the d2-v2 design, and the spec's loud failures reach five Grafana alerts.

## Commits

- dbfdcce50: verdict_gate, both COMPUTE_READY predicates, promote script holds, audit report, tests
- 6f007d826: the verdict scan (APR age, latest verdicts and loads) moved into verdict_gate so both consumers load rows one way
- 9ae6d529e: rebuild preconditions on verdicts, `check_data_layer_final_landed`, live D2 test rewrite
- 8bc07ddf7: the 186 note (`186-NOTE-185-41-verdict-gate.md`); cites the commits above
- eacc68b07: D7 alert gauges and the five Grafana rules

## What each gate says today (read-only runs, 2026-10-07 about 14:00 UTC)

Promote script dry run (no `--commit`), the eligibility audit (read-only) and a precheck script over the fetch helpers. Nothing was promoted, demoted, deactivated or written.

| gate | result |
|---|---|
| promote `compute_1d`, dry run | 0 candidates, 27 held. All 27 are held as "missing" on every 1d check: D7 judges only the `compute_1d` universe, so these names have no verdict rows (finding 1) |
| promote `compute`, dry run | 0 candidates, 1,296 held (the not-yet-promoted active names); 5m slot_coverage and coverage_cache fail or are missing for all 1,296 |
| audit, 1d gate over all 1,529 active names | 1,217 pass, 312 fail: session_coverage 267 (240 judged names plus the 27 unjudged), unexplained_seam 35 (8 plus 27), vendor_basis_run 73 (46 plus 27), the other four 1d checks 27 each (the unjudged names) |
| audit, 1d gate: currently promoted `compute_eligible_1d` names that would no longer qualify | 285 of 1,502 (240 session_coverage, 8 unexplained_seam, 46 vendor_basis_run, union 285). Not demoted; a finding |
| audit, `compute` gate (5m, 15m, 1h, 1d) | 0 pass of 1,529. Of the 233 promoted `compute` names all 233 would not qualify: 5m slot_coverage 233, 5m coverage_cache 228, 15m grid_parity 59, 1h grid_parity 72, plus the 1d failures. digest_fresh and stray_vendor_rows pass |
| `check_d2_landed` (1,502 `compute_1d` names) | fails: 285 names, the same three checks (240, 8, 46) |
| `check_bar_coverage` (233 `compute` names, 5m 15m 1h + stray_vendor_rows) | fails: 233 of 233 (slot_coverage 233, coverage_cache 228, grid_parity 59 on 15m and 72 on 1h) |
| `check_data_layer_final_landed` | fails: 185-42, 185-43, 185-45 and 189-11 SUMMARY files absent |

These counts match the 185-33 and 185-40 live reports (240, 8, 46, grid_parity 59 and 72, coverage_cache 228 of 233 in this scope). The grid_parity volume tolerance stays an owner decision; the rule is as written.

## Tests

- tests/unit/bars/test_verdict_gate.py (21), test_compute_ready_predicate_apr.py, test_rebuild_preconditions.py (35), test_bar_reconciliation_audit.py: green.
- tests/integration/test_d2_single_writer_live.py: 6 passed in 2 min 58 s against the live-shaped DB, on a connection set `default_transaction_read_only = on`. Asserts: canonical sources are a subset of tradier, ibkr_fallback, ibkr_named; ibkr_named bars only on dates an IBKR exception policy row covers; every visible 1d bar has a lineage row with request ids and the rule version is d2-v2; a seeded 17-name sample (an exception name, a fallback name, a both-vendors name, 14 random) recomputed with `derive_daily_v2` equals the stored bars on every field and source; every month with bars has a current digest; the split-seam test (vacuous while `corporate_action_current` is empty). `_KNOWN_PRE_FENCE_ORPHANS` and the TLT exception are deleted.
- `tests/unit/ -q` (full): no failures (5 existing skips). ruff and black clean on every touched file. Pre-commit's 9 checks passed on every commit. No edit under src/intelligence/research or statistics, so repro_frozen did not apply.

## Alerts

`production/grafana/provisioning/alerting/alert-rules.yml` parses; the five rules (`bar_integrity_failing_uid`, `bar_integrity_report_stale_uid`, `ibkr_fetcher_sla_breached_uid`, `tradier_refused_uid`, `revision_refused_uid`) are in the HIGH group. Each PromQL expression parses in the live Prometheus. The compose file mounts `production/grafana/provisioning` read-only into the container, so no copy was needed; the provisioning reload endpoint (`POST /api/admin/provisioning/alerting/reload`) was enough, no container restart. The Grafana API lists all five (16 rules in total). No CI test reads this file.

The new D7 gauges do not exist in Prometheus until D7's next run with this code (06:00 window); I did not run D7 by hand because it writes verdict rows. Until then `bar_integrity_failing` and the two refusal rules read no data (NoData), and `bar_integrity_report_stale` alerts on no data by design once the 36 h lookback is empty. Expect the stale rule to fire once after deploy if D7 has not emitted by then, and `bar_integrity_failing` to fire on the first run (240 names fail today).

## Deviations from plan

**1. [Design call] Verdict scan moved into verdict_gate.py.** The plan places the pure gate there; the I/O that loads rows (APR age, latest verdicts, latest changing loads) was first written in the audit script and then moved into the same module (`fetch_verdict_scan`, `load_report_max_age_hours`, both taking a connection and only reading), so the rebuild preconditions (services) do not import from scripts. Commit 6f007d826.

**2. [Rule 1 - Bug] `fetch_coverage_inputs` queried columns that do not exist.** `ohlcv_empty_history` has `empty_from` and `empty_through`, not `first_bar` and `last_bar`; the first read-only precheck failed with UndefinedColumn. The query now reads the real columns (test pins them). Commit 9ae6d529e.

**3. `check_bar_coverage` no longer takes tradeable spans.** It judges the intraday verdicts, which supersede the raw span test (slot_coverage per year). `fetch_coverage_inputs` and `CoverageRow` stay because the writer imports `CoverageRow` and 186-26 uses the counts elsewhere; the gate only uses its empty-history spans.

**4. Alert design for a oneshot.** The plan states the expressions as bare gauge comparisons. The collector's Prometheus exporter keeps a series about five minutes, and D7 runs once a day, so the rules wrap each gauge in `last_over_time(...[36h])` (the lookback is the run cadence, not a threshold). The report age gauge is the previous report's age at run start, because a gauge recorded at run end would read about zero. `bar_integrity_report_stale` uses noDataState Alerting so a D7 that stops running alerts.

**5. 186-26-PLAN.md was not edited.** The brief says to create only the note in the phase 186 directory, so the note alone carries the change and the timing (STATE.md's lane table also marks phase 186 as a separate lane).

**6. STATE.md, ROADMAP.md and REQUIREMENTS.md were not edited** (shared-checkout rule; the orchestrator updates them). Requirement ids D-06, D-07, D-26, D-28 are not yet marked complete.

## Findings

1. **Promotion cannot succeed for a never-judged name.** D7's verdict report covers the `compute_1d` universe (1,502). The 27 active names with `compute_eligible_1d = false` have no verdict rows, so the new `compute_1d` gate holds them as "missing" no matter how complete their data is, and no run can ever produce the verdicts that would promote them. The old gate had the same shape for no reason; the new one needs D7 to judge the promotion candidates (the `backfill` dimension, 1,529 names) in the 1d report, and the `compute` candidates in the intraday report. I did not change D7's universe here: it alters the live report size (about 27 more names, 1d cost +2 percent) and adds failing names to the alerts, and the plan does not list it. Needs a todo or a decision before the onboarding SOP's stage 8 can run again. Until then the SOP's promote step reports "held, missing" by design.
2. **`ibkr_fetcher_sla_breached` is a dead alert until todo 498.** The fetcher records `ohlcv_coverage_sla_breached_series` with a `job` attribute and the collector drops every metric carrying a `job` label; the series is absent from Prometheus today. The rule is provisioned as planned and reads NoData; it starts working when 498 is fixed. The fetcher is not edited here.
3. 285 promoted `compute_1d` names and all 233 promoted `compute` names would fail the new gates today. Nothing is demoted (the tool only promotes); these names stay flagged until the owner decides what a failing verdict means for an already promoted name.
4. The gates require freshness against the latest changing load: Tradier's nightly 21:30 EDT load makes every 1d verdict stale until D7's 06:00 run. Between 21:30 and 06:00 the `compute_1d` gate fails everything by design; promote and rebuild only after a morning run.

## Known stubs

None.

## Threat flags

None. The new code reads `integrity_monitor`, `ohlcv_load`, `config_state` and SUMMARY file presence; it writes nothing. The only new surface is gauges and alert rules.

## Self-Check

Files exist: verdict_gate.py, test_verdict_gate.py, the 186 note, the modified files above. Commits dbfdcce50, 6f007d826, 9ae6d529e, 8bc07ddf7, eacc68b07 are in `git log`. The five rule uids are in the Grafana API.

Self-Check: PASSED
