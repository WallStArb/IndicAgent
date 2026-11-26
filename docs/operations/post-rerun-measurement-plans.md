# Post-rerun measurement plans (parked, not run)

**Status:** prepared 2026-11-26 by indicagent-26 for the lead; nothing here has been run. Each plan waits for the corpus rerun to land the rebuilt rows and for the host to be released (the pilot is DB-heavy). Read-only unless stated. A plan that reads a return or an IC is a counted look (E21) and goes through the runner or the first 1d IC pass; it is never an ad hoc query.

| Todo | Plan | Reads returns | Counted |
|---|---|---|---|
| 583 | K=3 refusal share on the full 1d universe | no | no |
| 571 | concept reset: backup, counts, demotion through the service | no | no |
| 558 | `ret_acf1_z` against `ret_autocorr_1` correlation, then `redundancy_group` | no | no |
| 461 | `gap_z` IC re-measure | yes | yes, rides the first 1d IC pass |
| 466 | 303 and 304 regime benchmark rerun | yes | yes, runner spec |

## 583: K=3 refusal share (no fit, no write)

```bash
.venv/bin/python scripts/ops/ops_hmm_refusal_screen.py --tf 1d --family trend --stored --symbols-file <member names, one per line> --out /tmp/583_trend_k3.jsonl
.venv/bin/python scripts/ops/ops_hmm_refusal_screen.py --tf 1d --family volatility --stored --symbols-file <same> --out /tmp/583_vol_k3.jsonl
.venv/bin/python scripts/ops/ops_hmm_refusal_screen.py --summarize /tmp/583_trend_k3.jsonl /tmp/583_vol_k3.jsonl
```

`--stored` reads the written regime columns and lays the segments over the bars, so each name costs one query. Expected shape: one row per (tf, K) with the refused-segment share, the share of modelled names with zero output and the median written share. The result decides which names are declared regime-unknown before any regime-segmented 1d spec (HMM NaN is judged on written segments only, todo 661).

## 571: concept reset (writes; owner-approved, after the rerun and todo 564's batch)

Baseline now (2026-11-26, read): `concept_registry` holds active 288, candidate 111, deprecated 25. The todo says 306 active, so recount at the moment of the reset.

```sql
SELECT status, count(*) FROM concept_registry WHERE domain = 'feature' GROUP BY 1 ORDER BY 1;
SELECT count(*) FROM concept_evaluation;   -- the 590 old evaluations from 2026-09-24
```

Backup first: `pg_dump -Fc` of `concept_registry`, `concept_evaluation`, `concept_gate`, `concept_transition_log`, `concept_recipe`, `concept_parent`, `concept_annotation` into `data/backups/reset-<date>/` (`PGPASSWORD=postgres pg_dump -U postgres -h localhost -d indicagent -Fc -t <table> -f <file>` per table). Demotion goes through `ConceptRegistryService.record_transition(conn, domain="feature", name=<n>, from_status="active", to_status="candidate", reason="operator_override", notes="todo 571 reset after the corpus rerun")` for each active name (never an UPDATE; the CAS makes a rerun a no-op). Verify: the first query shows 0 active and `concept_transition_log` holds one `operator_override` row per demoted name. Before the demotion read `feature_factory.py` and `services/feature_lifecycle.py` as the todo's item 3 asks, so statuses do not change which columns are computed.

## 558: `ret_acf1_z` against `ret_autocorr_1` (feature against feature, no return)

```sql
SELECT corr(ret_acf1_z, ret_autocorr_1) AS pooled_corr, count(*) AS n
FROM feature_vectors
WHERE tf = '1d' AND bar_ts < '2025-12-24'
  AND ret_acf1_z IS NOT NULL AND ret_autocorr_1 IS NOT NULL;
```

Then the per-name spread on a seeded sample (a name list from `universe_membership`): the same `corr` grouped by `symbol`, report the median and the 5th and 95th percentile. Expected shape: one pooled coefficient and three per-name quantiles. If both are above the project's redundancy threshold, fill `redundancy_group` for the pair through the registry service path; nothing is dropped on this finding alone.

## 461: `gap_z` re-measure (counted)

Do not query. `gap_z` is a column of the 1d feature block, so its cells are in the first 1d IC pass (scope 1d, `ic_tfs` 1d, ledgered with its cell count first; see the decision log entry of 2026-11-26). Read its rows from that pass's `feature_ic_scores` output, and read the rebuild's drift report for `gap_z` (it should show the column moving against the pre-fix rows). Close the todo with those two facts.

## 466: 303 and 304 benchmark rerun (counted)

Not a query: a runner spec on the rebuilt regime columns that repeats the 303 and 304 comparison (candidates against `regime_volatility`) on the same sample symbols, plus the null-arm control, declared before it is read and counted. It waits for the first IC pass and for the lead's ruling on whether the two DEAD verdicts are worth a counted look at all (the annotations already say they are biased toward dead).  The `NON_FEATURE_COLS` item in the todo is moot: the module it names was deleted with todo 554.
