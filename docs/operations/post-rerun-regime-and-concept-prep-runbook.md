# Post-rerun prep: K=3 refusal share (todo 583) and concept layer reset (todo 571)

Both items run after the corpus rerun has written the rebuilt `feature_vectors` and no heavy job is live. Nothing here has been run; the queries and steps are written ahead so the day the rerun lands is mechanical. Read-only queries use one connection and one timeframe at a time. Judge every result by the printed numbers, never a tail.

## 583: refusal share of the K=3 regime fit on the full 1d universe

Goal (todo 583 "Done when" 1 and 2): count the names with no regime at all and the share of walk-forward segments the occupation gate refused, then either fix the cause or declare those names regime-unknown before any 1d spec segments by regime.

Facts the queries rely on:
- `feature_vectors` is keyed `(symbol, tf, bar_ts)`. The trend family's `regime` and the volatility family's `regime_volatility` are non-null only where the walk-forward segment was written (segment status 1, `src/intelligence/features/kernels/_hmm.py`, status codes at line 1073). Refused segments (status 2 degenerate occupation, 3 not converged) leave the column NULL.
- Todo 661 closed without a stored status column: presence of the regime column is the written-segment test, as `scripts/ops/ops_hmm_refusal_screen.py --stored` already uses.
- K=3 is the decided 1d value (E20, migration 566). Warmup rows are NULL by design, so judge a name only from its first written row.

Per-name coverage on 1d, trend family (run once, then repeat with `regime_volatility`):

```sql
WITH per_name AS (
  SELECT symbol,
         count(*)                                   AS rows_total,
         count(regime)                              AS rows_written,
         min(bar_ts) FILTER (WHERE regime IS NOT NULL) AS first_written
  FROM feature_vectors
  WHERE tf = '1d'
  GROUP BY symbol
)
SELECT
  count(*)                                                   AS names,
  count(*) FILTER (WHERE rows_written = 0)                   AS names_no_regime,
  count(*) FILTER (WHERE rows_written > 0
                   AND rows_written < rows_total)            AS names_partial,
  round(100.0 * count(*) FILTER (WHERE rows_written = 0) / count(*), 2) AS pct_no_regime,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY rows_written::float / rows_total)
                                                             AS median_written_share
FROM per_name;
```

Names with no regime, for the declaration list (write to a file, do not load into a table):

```sql
SELECT symbol, count(*) AS rows_total
FROM feature_vectors
WHERE tf = '1d'
GROUP BY symbol
HAVING count(regime) = 0
ORDER BY symbol;
```

Refusal reason (refused-segment share by status) needs a recompute, not a stored read, because the status is not stored. Use the existing instrument, 25 to 100 names at a time, outside any heavy job:

```bash
.venv/bin/python scripts/ops/ops_hmm_refusal_screen.py --tf 1d --n-components 3 \
  --symbols-file <names_no_regime.txt> --out <scratch>/583_k3_refusal.jsonl
.venv/bin/python scripts/ops/ops_hmm_refusal_screen.py --summarize <scratch>/583_k3_refusal.jsonl
```

Compare the summary against the K sweep table in todo 583 (1d refusal set at K=3 refused 29.9 percent of segments, 2.2 percent of names with zero output, median written share 76.1 percent). A stored share far from that means the rebuild and the screen disagree: stop and report before declaring anything.

Decision rule: names with zero output and a refusal reason of `degenerate_occupation` on every segment are declared regime-unknown in the research panel (a spec that segments by regime drops them and says so); any other reason is a defect to fix, not a declaration. Record the counts and the declaration in todo 583, then close its "Done when" items 1 and 2.

## 571: concept layer reset

Trigger (todo 571): the corpus rerun is complete on every timeframe the layer reads, todo 564's batch is applied, and the lead gives the go. The owner approved the reset; it runs once.

1. Confirm quiet: no `corpus_rerun`, `ic_measure` or `feature_factory` process (`pgrep -af`), no counted run live. The reset changes concept statuses that `feature_factory` reads, so a live rebuild must not overlap.
2. Back up first, custom format, one dump per run, into a dated directory outside git:

```bash
mkdir -p data/backups/reset-$(date -u +%Y%m%d)
PGPASSWORD=postgres pg_dump -U postgres -h localhost -d indicagent -Fc \
  -t concept_registry -t concept_evaluation -t concept_gate -t concept_transition_log \
  -t concept_recipe -t concept_parent -t concept_annotation \
  -f data/backups/reset-$(date -u +%Y%m%d)/concept_layer.dump
pg_restore --list data/backups/reset-$(date -u +%Y%m%d)/concept_layer.dump | wc -l   # nonzero, and the seven tables listed
```

3. Count before: `SELECT status, count(*) FROM concept_registry GROUP BY status;` (expect about 306 `active`) and `SELECT count(*) FROM concept_evaluation WHERE created_at < '2026-09-25';` (expect about 590). Record both.
4. Decide with the data lane whether `feature_factory` must compute the full column set whatever the status: todo 571 names a `feature_factory` that no longer exists; the rebuild writer is `services/backfill_feature_factory.py` (it has no read of concept status as of 2026-11-24, checked by grep). Re-read it and `services/feature_lifecycle.py` before demoting; do not assume.
5. Demote through `ConceptRegistryService.record_transition(conn, domain=..., name=..., from_status='active', to_status='candidate', reason=...)` in one script, one transaction per concept, with a reason that names todo 571 (check `concept_transition_log`'s reason CHECK vocabulary first, or the call raises); no direct UPDATE (UCR rule: only the service flips a status). Repeat for any `shadow_only`. Clear the `concept_gate` counters through the same service path if it exposes one; otherwise stop and report.
6. `concept_evaluation` rows from 2026-09-24: one migration in the style of migration 544 (check the table's append-only triggers first, disable, delete, re-enable in the same transaction), committed in the same breath as the live apply.
7. Verify: no concept `active` on evidence from before the rerun; `concept_transition_log` shows the demotions with the reason; counts after match counts before (306 moved, none lost); the dump still restores into a scratch database if a restore test is wanted (`pg_restore -d <scratch>`).
8. Re-earn `active` only through the normal evaluation on clean features; nothing here promotes.

Rollback: restore the seven tables from the dump taken in step 2 into a scratch database and compare; a production restore needs the lead and an idle system.
