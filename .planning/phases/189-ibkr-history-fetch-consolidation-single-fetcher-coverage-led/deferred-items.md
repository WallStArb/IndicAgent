# Phase 189 deferred items

Out-of-scope findings logged during execution. Not fixed in the plan that found them.

## From 189-06 (cutover, 2026-10-06)

1. **No `job_completed_total` reaches Prometheus, for any job.** The OTel collector's
   Prometheus exporter (`otel/opentelemetry-collector-contrib:0.153.0`,
   `production/otel-collector-config.yaml`) rejects every metric that carries a `job` label:
   `failed to convert metric job_completed_total: duplicate label names in constant and
   variable labels`. The same error hits `job_duration_seconds` and the fetcher's
   `ohlcv_coverage_sla_breached_series`. It has logged since the container started
   (2026-06-22), so the D-06 oneshot contract has had no Prometheus surface since then. The
   fetcher and the Tradier loader do emit (the collector receives and then drops them). Likely
   fix: rename the metric label (for example `job_name`), or stop the exporter's
   resource-to-label promotion from adding a constant `job` label. This is an observability
   change across every oneshot and needs its own todo and a PRIORITIES.md row.
2. **The `nightly_skipped` D7 check fires on every `partial` fetcher run.** Until todo 490
   (the grid stage's archive verify on twice-observed revised bars for A, AAP, ABBV, ACRS,
   ACVA, ADBE and ADP) is fixed, every fetcher run that lands 5m rows ends `partial`. The audit
   reads that status as a finding, so the daily audit reports one `nightly_skipped` finding
   each day. 189-04 predicted this, and it clears when todo 490 closes.
3. **`indicagent-bar-reconciliation-audit.service`'s comment says "No timer".** It now has a
   daily timer (`indicagent-bar-reconciliation-audit.timer`, 06:00 UTC). The unit file was
   created by 185-23 and was left unedited here (cutover hard rule: no edits to production
   files this plan did not create). Fix the comment when plan 07 deletes the nightly.
   Fixed in 189-07 (3f100aaaf), installed copy synced.
4. **Ledger 15m/1h bound semantics differ between the bootstrap and the incremental writer.**
   Migration 432's bootstrap, and `rebuild_from_stored_state`, which mirrors it, take
   15m/1h bounds over the union of the archive and the grid, so derived grid 1h bars
   (session-aligned, last slot 19:30) count. `upsert_coverage` only widens from fetched
   archive chunks. After a rebuild, a 1h row can read up to 30 minutes later than the archive
   max. Ranking is unaffected at day granularity. Choose one definition when plan 08 touches
   the ledger.
5. **Tradier-owned 1d ledger rows are never refreshed.** The fetcher skips owned 1d series,
   and `refresh_1d_bounds` runs only for the 1d symbols it touched, so 1,266 owned 1d rows go
   stale after each Tradier load. They are never queued, so the queue is unaffected, but
   their `latest_timestamp` misleads anyone reading the ledger directly. Option: call
   `refresh_1d_bounds` for the loaded names after the Tradier load. That needs a role grant
   decision, because the loader is not a ledger writer today.
6. **Live APR descriptions name deleted machinery (found in 189-07).** `config_schema`
   descriptions still cite deleted files: `infra.ibkr.historical_request_timeout_sec` points at
   the backfill_retry_loop.sh watchdog (now the fetcher unit's WatchdogSec), and
   `infra.backfill.default_scopes` describes the nightly legs, the todo 449 HTF campaign and
   PAUSE_5M (migration 445 changed the value, not the description). Fold a description-only
   UPDATE into the next migration that touches either key (189-08 or 189-10).
7. **`infra.ibkr_history_lease.nightly_wait_minutes` loses its last real reader (found in
   189-07).** The nightly read it; the only remaining mention is
   infrastructure_run_historical_pipeline.py's `--lease-wait-minutes` help text, which keeps the
   185-44 reader guard green. When 189-08 absorbs that script, the key needs a
   `_PENDING_RETIREMENT` entry with `retire: <plan>` (or a delete migration) in the same commit.
8. **The D7 `nightly_skipped` check reports a finding every day while the fetcher timer is
   disabled (189-07 to 189-10).** The status file `logs/nightly_backfill_status.json` is
   written only by fetcher runs, so it goes stale past `max_age_hours`. Expected under the
   owner's stop; it clears on the first run after 189-10. The check and file keep their
   nightly names; renaming them is a monitor-key change for a later plan.
