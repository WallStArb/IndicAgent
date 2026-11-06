# Corpus rerun runbook

Author: 186-31 executor. Informed by: `.planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-31-PLAN.md`, todo 593, todo 584.

The 584 corpus rerun, the fresh IC measure and the canary run as one DAG of oneshot steps under one
`corpus_run` id, driven by `services/corpus_rerun.py`. It starts only when the data gate passes
(todo 534 complete, owner rule 2026-11-04). Every gate reads the rows of that run id.

```
data_gate -> pin_gate -> pilot -> stage_1d -> s1.1h -> s1.15m -> s1.5m -> ... -> sN.5m
  -> feature_complete -> ic_measure -> d19_bound -> canary
```

Each step refuses before it writes anything unless its upstream step of the same run is
completed. There is no skip flag. A completed step re-invoked is a no-op that prints its stored
outcome. A failed step retries once its cause is fixed. Step state lives in `corpus_run_step`;
the run's identity, spans, caveats, data gate result and measured figures live in `corpus_run`.

## APR (migration 579)

| Key | Seed | Used by |
|---|---|---|
| `infra.corpus_rerun.max_disk_fraction` | 0.70 | span plan, pin gate, unit guard: growth from launch stays at or below this share of `free_bytes_at_launch` |
| `infra.corpus_rerun.disk_reserve_bytes` | 50e9 | pin gate (`check_disk_guard` reserve), unit guard: free space never below it |
| `infra.corpus_rerun.bytes_per_row_uncompressed` | 1379 | span plan; the pilot's measured figure replaces it when larger |
| `infra.corpus_rerun.compression_ratio` | 6.0 | compressed terms of every peak |
| `infra.corpus_rerun.stored_bytes_per_spool_byte` | 0.37 | unit guard; the largest measured ratio of the run wins |
| `infra.corpus_rerun.data_gate.max_missing_session_fraction` | 0.01 | data gate, 5m sessions per name-year |
| `infra.corpus_rerun.data_gate.max_missing_1d_session_fraction` | 0.01 | data gate, 1d sessions per name-year |
| `infra.corpus_rerun.data_gate.min_session_bar_fraction` | 0.9 | data gate, a session's 5m bars over its own slots |
| `infra.corpus_rerun.blocking_timers` | four bar-moving timers | pin gate |

The APR hash is part of the run's identity: changing any of these (or the rebuild's feature
config) mid-run makes every later pin gate refuse. Start a new run instead.

## Plan and launch

1. Dry plan, writes nothing:

   ```
   .venv/bin/python -m services.corpus_rerun --new-run --plan-only [--horizon YYYY-MM-DD]
   ```

   It prints the row counts per tf, free space, the limit, `max_wal_size`, the chosen spans and
   each step's projected peak by term (span rows, straddling chunk, compressed rest, 1d
   uncompressed and compressed, WAL, largest group spool), then the data gate verdict.
2. Disable the blocking timers and let their services finish. For each unit in
   `infra.corpus_rerun.blocking_timers`: `sudo systemctl disable --now <timer>`, then wait until
   `systemctl is-active <service>` reports `inactive` or `failed`. An `enabled` timer, or a
   service still running a fetch it already started, moves bars under the run; the pin gate
   refuses both. Make sure no manual IBKR history tool holds FetcherLock.
3. Create the run from the commit to pin (default HEAD of the main checkout):

   ```
   .venv/bin/python -m services.corpus_rerun --new-run [--commit <sha>] [--horizon YYYY-MM-DD]
   ```

   It plans the spans (the smallest count whose largest peak fits the limit; it refuses with the
   candidate table when none fits), creates the detached worktree
   `<main checkout>-corpus-run-<run id>` at the commit, symlinks the main checkout's `.env` and
   `logs/` into it, computes the code key and APR hash inside the worktree, and inserts
   `corpus_run`. It prints the run id and the next command.
4. Run every step from the worktree with the main checkout's interpreter:

   ```
   cd <worktree> && /home/bg/dev/indicagent/.venv/bin/python -m services.corpus_rerun \
       --run-id <id> --through canary
   ```

   `--step <name>` runs one step. Logs: `/home/bg/dev/indicagent/logs/corpus_rerun.log`; the
   rebuild spool is `logs/rebuild_spool/` there too. One runner per run: a second one on the same
   run id exits at once (advisory lock).

Resume after a kill: re-run the same `--through` command. Completed steps are no-ops; the step
that was running resumes (its completed units are skipped, a killed unit's started row is
retaken). Follow the worker-kill procedure in `docs/reference/gotchas.md` first.

## The steps and what each refusal means

- `data_gate`: 186-32's `run_data_gate` over the compute_1d universe at the run's horizon. It
  counts, per name and year, every NYSE session from the name's proven start that holds a
  tradeable 1d bar and 5m coverage from the era's policy primary. It reports the 1d sessions
  before the calendar's first session per name (`pre_calendar_1d_sessions`), names without a
  proven start or without sessions, and the names held by a 1d empty-history span of the era's
  policy primary (`held_names`). On a pass, one transaction writes `corpus_run.data_gate`,
  appends the survivorship caveat unless one with its code is present, and completes the step.
  A refusal writes the counts and failing name-years to the failed step's summary and nothing to
  `corpus_run.caveats`. Fix: finish the backfill (todo 534), then retry the step.
- `pin_gate`, repeated before every compute step: the process runs in the run's worktree, HEAD
  equals `corpus_run.code_commit`, the rebuild code key and APR hash equal the run's, `services`
  is imported from the worktree, FetcherLock is free, each blocking timer is `disabled` or
  `masked` and its service `inactive` or `failed` (an unknown answer refuses), no live writer
  process, the D-32 rebuild preconditions pass, `check_disk_guard` covers the remaining
  compressed bytes plus the next span's peak less its compressed part plus `max_wal_size`, and
  the growth since launch plus the next step's projected increment stays inside the limit. Each
  check is recorded in the step summary.
- `pilot`: stage_1d's symbol chunk 0 and one 1h unit of span 1 (the first year of span 1 that
  holds one), both ordinary units of the real stages, kept; later stages skip them as completed.
  G1-G3 (`scripts/ops/ops_feature_column_screen.py` on chunk 0, 1d and 1h) and G4-G5
  (`scripts/ops/ops_pilot_compute_gate.py`, every chunk 0 name at 1d and 1h) must pass. It
  records per-piece wall time, the extrapolated wall clock per stage, the DB load against the
  other lanes, the 1d and intraday bytes per row and the stored-per-spool ratio in
  `corpus_run.measured`. Then it re-projects the run's spans with the larger bytes per row. If a
  span overflows, the pilot fails and stage_1d never runs; spans are immutable, so the recovery
  is a new run, which plans more spans.
- `stage_1d`, then `s<k>.1h`, `s<k>.15m`, `s<k>.5m` per span: `run_rebuild_stage` on the full
  universe under the run id with the run's unit disk guard. The step fails on a failed, refused
  or abandoned unit, or on a unit of its scope without a completed row that is the run's own or
  adopted. After `s<k>.5m` every feature_vectors chunk ending by the span's end (short of the
  open chunk) must be compressed; the chunk straddling the boundary compresses after the next
  span.
- `feature_complete`: the full scope re-planned now. Every planned unit has a completed row of
  the run (own or adopted); no started or failed row under the run; no digest-blind symbol in
  the plan or any stage summary; the column screen passes per tf. A revised bar renames its unit,
  so it shows here as missing.
- `ic_measure` under the run id, then `d19_bound` (no `feature_ic_scores` row at or after
  `alpha.validation.oos_start`), then the canary
  (`scripts/ops/alpha/ops_canary_integrity_assert.py --run-id`).

## The survivorship caveat

IBKR serves only names that trade today and the universe was chosen today, so every result whose
sample includes pre-2016 5m is survivorship-biased (todo 534 owner decision 2026-11-04, code
`survivorship_pre2016_ibkr_5m`). The data gate's pass writes it to `corpus_run.caveats` with its
counts, in the same transaction as the result; the array is append only (migration 578) and a
retried step never duplicates it. The `ic_measure` and `canary` step summaries carry
`corpus_run.caveats` verbatim. Any result read from this run discloses it.

## Adoption

A unit skipped because a completed provenance row with its identity already exists keeps that
row's run id (completed rows are immutable). The step records it in its summary's `adopted` list
as `{unit_key, batch_key, adopted_from_run_id}`. Every one-run check (span steps,
`feature_complete`, the canary) counts a unit when its completed row carries this run id, or when
a completed step adopted exactly that batch_key from exactly the run that row records. A second
run over identical inputs adopts everything and passes; an adoption naming another batch_key is
refused.

## Recovery

- A unit completed under another run and not adopted, or a stale started row: `feature_complete`
  (or the span step) fails and lists the batch keys. Supersede those provenance rows through the
  sanctioned `completed -> superseded` transition (migration 416), delete their rows with the
  unit's `replace_where` (for feature_vectors: the unit's tf, symbols and range), then retry the
  stage step under the same run id. The runner never does this itself.
- A disk refusal (`disk_refused` in the stage summary, reason `disk_guard`): the refused unit has
  no provenance row and stays pending; the stage stopped dispatching and still ran its
  compression. Check free space (`df`), confirm the compression finished, and re-run the same
  step. If the projection itself was wrong, the pilot's measured figures and the run's maxima are
  in `corpus_run.measured`; a run that cannot fit needs a new run with more spans.
- A pin refusal: fix the named cause (timer, lock, process, wrong directory) and retry; a code
  key, commit or APR hash mismatch means the run cannot continue on this code: start a new run.
