# Draft ledger entry: the first IC sweep, cell list and n_looks

Status: draft for owner confirmation (lead ruling 2026-11-27). Not in `docs/plans/methodology-change-ledger.md`; the lead writes the entry there only after the owner confirms it in the lead's own session. The FILL numbers come from `ic_sweep_recorder --dry-run` and cannot be known before `feature_complete` of the successor run (the run that adopts the 515 units of dcb7caa4, ledger 2026-11-27c); a dry run before it would count columns of a table the run has not certified. Assembled from todo 671's draft (269d63c44), ledger 2026-11-24f, 2026-11-24i, 2026-11-24e and the draft 2026-11-25c (`docs/research/draft-ledger-2026-11-25c-sweep-regime-columns.md`, which this entry assumes confirmed).

## What the owner is asked to rule on, in plain words

1. The count. Before the first IC pass the ledger must state how many tests (attempts) the sweep will make, because the multiple-testing correction is sized to that number. Estimate from todo 671: 1,108 cells (277 features at 4 horizons), each tested twice (the feature as measured and its mirror), so 2,216 attempts. Today's registry has 325 `feature` concepts (288 active, 20 deprecated, 17 candidate) against 305 numeric `feature_vectors` columns, so the real figure is at most 2 x 305 x 4 = 2,440 and is fixed by the dry run after `feature_complete`. Decision: approve the count as declared, or cut the list first (a cut can only shrink the count, never grow it afterwards).
2. The families. What is swept: every numeric feature column that has a `feature` concept row, on the daily clock, horizons 1, 2, 5 and 10 sessions. Left out and listed in the report, counted as nothing: columns with no concept row, path-dependent columns (todo 674), regime columns (2026-11-25c, needs its own confirmation), and columns with no tested session. Decision: confirm this list, in particular that regime columns stay out of the sweep.
3. The multiplicity treatment. Each cell is two one-sided tests, long and mirrored short, so no sign is chosen from the data; the family-wise correction is StepM over all attempts. The cost is about 5 percent on the critical t (3.92 to 4.12 with independent cells, 3.08 to 3.34 at correlation 0.7). The synthetic scale check (todo 670) is only a disclosure and cannot shrink the batch. Decision: confirm the two-attempt treatment and the volume pilot (horizon 1 first, its measured rows and bytes recorded before the other horizons run).
4. Targets are price-only (`panel.forward_returns`), as ruled in 2026-11-24e, with the three binding disclosures of the 666 decision memo in every IC report: the ex-dividend straddle table, the flag list (yield-linked columns are read on price-only targets and their cells are not evidence about the feature), and the statement that any family a cell prompts declares `panel.total_return` at registration. Reports quoting survivorship use the member-universe dividend coverage of ledger 2026-11-24j (59.7 percent of member cells covered). A fourth disclosure (indicagent-cb, 2026-11-27): stored `dividend_yield`, and any column derived from it, reads Yahoo dividend coverage only, while the research snapshot counts Yahoo else Massive as covered; names covered only by Massive (for example ACC, ACCO, ACES, ACAT, ACAS) are all NaN in the stored column (unit c6364f4d of run dcb7caa4: 0 of 38,945 rows non-null). Tracked as todo 684; not a compute fault, and no counted test reads the column today.

## Entry text to append (after confirmation)

Heading: `## 2026-11-27a: the first IC sweep, cell list and n_looks (lead record, owner veto reserved)`

Body: Declared before any IC cell is measured or recorded (E21 rule 6; rulings 2026-11-24i; the condition of 2026-11-24f). Scope: timeframe 1d, horizons from APR `alpha.ic_measure.horizons` (1, 2, 5, 10), every numeric `feature_vectors` column that has a `feature`-domain concept row and passes the recorder's admission refusals (path dependent, builder path dependent, regime origin per 2026-11-25c); the dry-run report lists the excluded columns and the columns with no tested session, and none of them is measured or counted. Each cell is two attempts, the long (the measured per-session rank IC) and the mirrored short (its negation), each tested one-sided positive by the shipped StepM; no sign is fitted or chosen. Targets: `panel.forward_returns` price-only (2026-11-24e, todo 666), with the three disclosures of the 666 memo in every report, the `dividend_yield` coverage disclosure (todo 684) and the member-universe dividend coverage of 2026-11-24j. Floor: `alpha.ic_sweep.min_names_per_session` = 30 (migration 618). Cell list: FILL features measured, FILL excluded without a concept row, FILL excluded inadmissible, FILL unmeasured per horizon; n_looks = FILL (the dry run's `batch_attempts`: 2 x the measured cells summed over the four horizons) for the full sweep, and the recorder refuses to write unless `--declared-n-looks` equals it. Volume pilot first (E21 volume gate): block `--horizons 1`, n_looks FILL (2 x measured cells), measured rows and series bytes recorded in todo 671 before the other horizons run; the remaining blocks are a second declaration if the pilot's volume is as expected. A bad block is a new spec and a new charge, never an edit (ruling 2026-11-25). Code: the commit the recorder runs at, an ancestor of origin/main, from a detached worktree with a clean tree. The 670 disclosure line (replicate counts, effective-breadth set, tails, seed base) is appended before the check runs. Conditions already met: the sweep-cell writer (671) and the synthetic check (670) are built and in the successor run's pin (code key 487f4ab434); `feature` is in the ledger's domain lookup (ed2b16c9b), and `repro_frozen` is bit-identical on 0b5af0466, which contains it. Conditions still open: the sweep stays behind the prior-driven families (design note 2026-11-24); the write-path ledger line; `feature_complete` for the successor run; the recorder's 25-name memory check; two identical dry runs on one pin (pilot gate b); the 670 disclosure line; the owner's confirmation of this entry and of 2026-11-25c. No threshold, spec, recorded statistic or counted look changes; this entry declares the count of the first sweep before it is made.

## Run section: the exact steps from `feature_complete` to the first counted block

These steps close the checklist in todo 671 ("Remaining before the first counted 1d sweep"); the item numbers below are that checklist's. Steps 1, 3 and 6 are heavy. They run through the guarded launcher of todo 690 (watchdog, host and memory gates, one heavy job, timers held) once it lands; the raw commands below are what it wraps, and are not to be run bare on this host (DIMM fault 2026-11-23).

Placeholders: `<RUN>` the successor run id; `<KEY>` its code key prefix (487f4ab434); `<SWEEP>` the commit the recorder and the 670 check run at, a pushed commit containing todo 690 (the recorder reads stored features, so it need not be the run's pin, and its HEAD is the code commit its spec hashes record; before step 0, `git diff --stat <PIN> <SWEEP>` must touch only the recorder, the 670 script and the 690 launcher, or another surface the lead accepts in writing, because the panel, target and refusal code come from `<SWEEP>` while the features came from the pin); `<DATE>` the UTC date; `<SEED>` the 670 seed base its settings line declares; `<N_PILOT>` and `<N_REST>` the n_looks the confirmed entry declares. `PY=/home/bg/dev/indicagent/.venv/bin/python`.

Step 0, once: a detached worktree for the recorder and the 670 check (not a run worktree).

```
cd /home/bg/dev/indicagent && git fetch -q
git worktree add --detach /home/bg/dev/indicagent-wt-sweep <SWEEP>
cd /home/bg/dev/indicagent-wt-sweep && ln -s /home/bg/dev/indicagent/.env .env && ln -s /home/bg/dev/indicagent/logs logs
```

Step 1, todo 670 (item 4; about 1.6 h on 4 cores, needs no feature rows; run when the recorded universe is final). The settings line goes into the ledger first; then:

```
$PY scripts/research/stepm_sweep_scale_check.py \
  logs/research/stepm_checks/sweep_scale_<DATE>.json --seed-base <SEED> --cells 1220 --workers 4
```

Check the JSON's `baseline_without_null_cells` against `select_books` run on the same vintage at the same time (the universe the check loaded) before quoting its `report` per setting.

Step 2, item 6, after `feature_complete`: the recorder on 25 names (light), peak RSS into todo 671.

```
/usr/bin/time -v $PY -m services.ic_sweep_recorder --tf 1d --dry-run --symbols <25 names> \
  --report logs/ic_sweep_dry_25_<DATE>.json 2> logs/ic_sweep_dry_25_<DATE>.time
grep "Maximum resident set size" logs/ic_sweep_dry_25_<DATE>.time
grep bar_digests_absent logs/ic_sweep_recorder.log   # a dry run allows them; the real run refuses
```

Step 3, item 7, pilot gate (b) and the FILL numbers (heavy, twice, one pin, no write between):

```
$PY -m services.ic_sweep_recorder --tf 1d --dry-run --report logs/ic_sweep_dry_a_<DATE>.json
$PY -m services.ic_sweep_recorder --tf 1d --dry-run --report logs/ic_sweep_dry_b_<DATE>.json
cmp logs/ic_sweep_dry_a_<DATE>.json logs/ic_sweep_dry_b_<DATE>.json && echo identical
```

`cmp` is a value test only once todo 690 adds the per-block spec hashes and series digests to the report; today the report holds counts and name lists. Fill the entry from it: `batch_attempts` (the n_looks), `excluded_no_concept`, `excluded_inadmissible` and `unmeasured` by horizon; the measured feature count is in the recorder's log line `ic_sweep_recorder.measured` (`features`). Then the owner confirms, and the lead appends this entry and the 670 disclosure line.

Step 4, item 10, IC measure memory and its floor:

```
cd /home/bg/dev/indicagent   # the main checkout: the launcher finds the run worktree beside its own repo
RSS_CHECK=1 RSS_SYMBOLS_FILE=<file, exactly 25 names one per line> setsid -f bash scripts/ops/ic_measure_launch.sh <RUN> <KEY>
grep rss logs/family10_run_status.txt | tail -3
```

The 25-name peak is a per-name figure: extrapolate it to the full grid at width 16 (todo 471: about 15 GiB plus the interpreter) and set `infra.run_guarded.mem_floor_gib.ic_measure` through `ConfigService.set` to cover the larger of that projection and the stage_1d peak, with a `config_history` reason giving both numbers (40 today is migration 623's seed).

Step 5, the IC measure (heavy; it releases the timers on a clean exit):

```
cd /home/bg/dev/indicagent
PREFLIGHT_ONLY=1 bash scripts/ops/ic_measure_launch.sh <RUN> <KEY>
setsid -f bash scripts/ops/ic_measure_launch.sh <RUN> <KEY>
```

Item 9 decides whether step 6 runs before step 5, inside the window the stage holds (recommended), or after it under a fresh hold.

Step 6, item 11, the volume pilot block (heavy; a real run refuses a dirty tree, a moved HEAD and an unpublished commit):

```
cd /home/bg/dev/indicagent-wt-sweep
$PY -m services.ic_sweep_recorder --tf 1d --horizons 1 --declared-n-looks <N_PILOT> \
  --report logs/ic_sweep_pilot_<DATE>.json
```

Then check the block: rows equal the declared attempts, every completed row has one series, and `n_sessions`, `span_start` and `span_end` equal its series; record rows and series bytes in todo 671. Step 7, item 12, after a second declaration: the same command with `--horizons 2,5,10 --declared-n-looks <N_REST>`.

## Draft text for the two ledger lines this sweep still needs (lead writes them; owner veto reserved)

Write path (todo 671's landing constraint asks for its own line): `## <date letter>: sweep cells are recorded through S6 (record_sweep_block); no statistic moves (todo 671; lead record, owner veto reserved)`. Body: `PostgresLedger.record_sweep_block` (ed2b16c9b; review fixes d282e9ac7, 07368e980, 5f918ea8f, b1e684490) writes one block per (timeframe, horizon, direction) in one transaction under `LEDGER_LOCK_KEY`: a `research_run` row per cell (kind evidence, mode real, the feature's own concept row by the domain-qualified lookup) and its series, each moved to its terminal status in the same transaction, so a crash leaves no started orphan, and a repeat of the same block is refused by `PRIOR_REAL_RUN_SQL`. Sweep rows carry the spec path prefix `SWEEP_SPEC_PATH_PREFIX`, which keeps them out of `backfill_attempt_series` and lets `select_books` read their horizon from the spec without resolving it through git; `select_books` counts them as attempts like every evidence run. `repro_frozen` bit-identical on 0b5af0466. It adds no statistic and moves no recorded spec hash.

670 settings (before step 1): `## <date letter>: the sweep-scale StepM check, settings declared before it runs (todo 670; lead record, owner veto reserved)`. Body: a disclosure, not a gate (2026-11-24i). `stepm_sweep_scale_check.py` at <SWEEP>, on the recorded attempt series of vintage <VINTAGE> (<n> series), run after the last counted family before the sweep: 1,220 base cells (an upper bound, 305 numeric columns x 4 horizons, until the dry run fixes the count; more cells only tighten), each entered as itself and its negation; cell horizons 1, 2, 5 and 10 split evenly; scale drawn from 0.02 to 0.03; cells grouped into n_eff independent groups with within-group correlation 0.9, n_eff {8, 50, cells}; shocks Student t (5 degrees of freedom) and normal; warmup masks drawn uniform up to 252 sessions; 8 replicates per setting; seed base <SEED>, replicate seed `seed_base + 10000 * setting + replicate`; StepM as shipped (APR fwer 0.05, block mean 20, reps 2,000, seed 187; `max_horizon_sessions` the larger of the recorded maximum and 10). The zero-cell baseline must reproduce exactly the `select_books` read of the same vintage taken when the check runs. A changed setting is a new dated line.
