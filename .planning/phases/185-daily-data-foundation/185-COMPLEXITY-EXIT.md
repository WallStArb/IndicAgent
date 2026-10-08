# Phase 185 complexity exit (plan 185-43)

Measured with the 185-44 producer, unchanged: `.venv/bin/python -m scripts.ops.ops_complexity_census --markdown`
(read-only). Columns: the 185-44 baseline (2026-10-06T22:29Z, SHA 74fb3fd4b), the start of this
plan (2026-10-07T23:55Z, SHA b286a2910, after 185-31 to 185-42, 185-44 to 185-46, 189-07 and
189-08), and the end of this plan (2026-10-08, after fa48d2cce plus the archive Status edits
committed with this file). Definitions are the baseline file's.

## Counts

| Measure | Baseline | Start of 185-43 | End | Delta vs baseline | Down? |
|---|---|---|---|---|---|
| scripts_total | 103 | 83 | 80 | -23 | yes |
| scripts_ops | 36 | 28 | 27 | -9 | yes |
| temporary_entries | 2 | 1 | 1 | -1 | yes |
| tables_public | 100 | 80 | 77 | -23 | yes |
| views_public | 14 | 15 | 15 | +1 | no, explained below |
| apr_keys_without_reader | 177 | 211 | 51 | -126 | yes |
| services_without_live_consumer | 38 | 21 | 21 | -17 | yes |
| todos_pending | 88 | 97 | 92 | +4 | no, explained below |
| docs_stale_status | 10 | 10 | 1 | -9 | yes |
| apr_keys_total (context) | 845 | 858 | 681 | -164 | |

## What this plan removed

- Scripts (3): `universe_expansion_pilot_draw.py`, `universe_expansion_onboard_gap_fill_etfs.py`,
  `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py` (78d4e90d7).
- Tables (3 live, 2 catalog-only): `backfill_status`, `batch_job_checkpoints`,
  `ic_cell_fingerprints`; `market_data_ohlcv_new` and `market_data_ohlcv_old` leave the migration
  catalog (migration 459, dumps in `data/backups/185-43/`).
- APR keys (177): every `_PENDING_RETIREMENT` entry naming 185-43, 13 orphaned `alert.lag.*`
  keys, the `alpha.frame.*` family (120) and `threshold.signal_audit.*` (6), and seven single
  keys with no code left (migration 459 header lists them). The census rose from 177 to 211
  between the baseline and this plan's start because 185-42 and 185-45 parked their orphans for
  this plan; it ends at 51.
- Todos: 056, 223, 317, 462, 484, 488, 500 closed (fa48d2cce).
- Docs: nine `docs/plans/archive/` designs carried an open Status (Draft, In progress,
  PROPOSED) although they sit in the archive; their Status now reads Archived.

## Counts that did not go down

### views_public: 14 -> 15 (+1)

| Item | Added by | Justification |
|---|---|---|
| `canonical_bar_lineage` | 185-38 (migration 447) | The stored lineage table became a view derived on read (data layer integrity design section 4): a side table that could disagree with the bars was replaced by a view that cannot. The same change removed one table, so tables plus views fell. |

### todos_pending: 88 -> 92 (+4)

Seven baseline todos left `pending/` (056, 223, 317, 462, 484, 488 by this plan; 490 by
185-35). Eleven were filed after the baseline, each an open item a plan found and could not
close in its own scope; every one has a PRIORITIES row and an owner:

| Todo | Filed by | Why it stays open |
|---|---|---|
| 499 | 185-32 | Gap readers still plan from stored bars; step 3 (move them to `ohlcv_coverage`) has no plan yet |
| 501 | 185-29 | S0 data-quality hand-off in the research snapshot and runner; owned by the phase 183 session, blocks the paused research lane |
| 502 | 185-41 | D7 judges only `compute_1d` names, so a new name can never pass the promote gate |
| 504 | owner request 2026-10-07 | Dividend writer source registry and per-symbol failure policy (PSKY fails the unit nightly) |
| 505 | 185-46 | The nightly update lane exceeds R4; the 5m pacing ceiling is unmeasured (189-10 Task 2) |
| 506 | 189-08 | The rebuild writer's `--fetch-only` takes FetcherLock after 186-26 (the one TEMPORARY entry) |
| 507 | 189-08 | Split re-fetch in-process under the fetcher lock (gates 189-10 Task 1b) |
| 508 | 185-37 | Stale-basis Tradier heads; owner picks the head treatment before 186-26 |
| 509 | 185-45 | The v2.x remainder live surfaces still need (feature_vector_pipeline coupling, dashboard routes, ML chain); owner calls |
| 510 | 185-43 | Delete the 185-38, 185-43 and 185-45 backups on or after 2026-11-06 (the 30-day rule) |
| 511 | 185-43 | ISLAND head rule owner decision, carried from closed todo 500 |

### Residue that stays counted and why

- docs_stale_status (1): `docs/architecture/architecture-overview.md` is a staleness-quarantined
  draft that predates phases 170 to 172. Rewriting the architecture overview is a doc project of
  its own, not a Status edit; it stays flagged so nobody trusts it.
- apr_keys_without_reader (51): the frozen 2026-10-06 keys that remain (regime family thresholds,
  `alpha.construction.*`, `alpha.ic.*`, zone engine stop distances and a few infra keys). Their
  domains (regime families, construction rules, the IC measure) are live or are inputs the phase
  186 and 187 designs may read, so retiring them is a decision for those phases, not a cleanup
  step. The guard keeps the list shrink-only.
- services_without_live_consumer (21): the dormant streaming chain (todo 366: ibkr-provider,
  provider-merger, bar-writer, bar-aggregator, bar-auditor, bar-replay, cross-asset,
  macro-compute, feature-vector-pipeline), six batch services run by hand or by the rebuild with
  no installed unit (bar-derivation, ic-measure, regime-writer, feature-lifecycle,
  feature-parity-auditor, economic-series-writer), and six support daemons that are inactive
  (alerting-agent, dlq-drain, config-service, outbox-dispatcher, self-healing-agent,
  service-auditor). None was in this plan's scope; todo 509 owns the v2.x-coupled ones.
- temporary_entries (1): `test_ibkr_history_lock_boundary.py` allows the rebuild writer's
  `--fetch-only` without FetcherLock until after 186-26 (todo 506). The two baseline entries in
  `test_ibkr_history_lease_boundary.py` were retired by 189-08.
- Raw market data tables (`market_data_ohlcv`, `ohlcv_observation`, `ohlcv_request`,
  `ohlcv_revision`, `ohlcv_load`, `corporate_action`, the intraday archive) are never counted as
  debt to delete.

## Guards and suite at exit

Recorded in `185-43-SUMMARY.md` (vulture against the pre-plan tree, the boundary, registry,
expiry and reader guards, the full unit suite).
