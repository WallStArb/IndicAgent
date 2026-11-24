---
status: pending
priority: P1
filed: 2026-11-24
source: indicagent-3d family-order note, lead ruling 2026-11-24
---

# The sweep-cell writer: record each measured IC cell as a counted attempt through the S6 ledger

## What

E21 (methodology-change-ledger, adopted 2026-11-13) counts every measured level 1 cell (feature, timeframe, horizon) as one `research_run` evidence attempt in mode `real`, with its per-session pooled cross-sectional IC stored as the attempt's series in `research_run_series`, written only through S6. `services/ic_measure.py` writes only `feature_ic_scores` (pooled IC with a strided sample and a bootstrap interval; no per-session series), and `research_run_series` is written only by `src/intelligence/research/ledger.py` and its callers. Without this writer a sweep is an uncounted look and no IC pass may run (ledger 2026-11-24f).

## Spec (design 2026-11-24, indicagent-94; implementer follows this)

Two parts, each with one owner, so single_writer holds.

1. Compute: a pure function in `src/intelligence/measure/` (beside `ic.py`), `session_rank_ic(features [S, N, F], target [S, N], valid) -> ic [S, F]`: for each session s, the Spearman rank correlation across names of each feature with the target, using only names where the target and that feature are finite (the E21 "finite values only"), NaN when fewer than `min_obs` names (reuse `MeasureParams.min_obs`) or a degenerate cross-section. Ranks are taken once per (session, feature) and once per (session, horizon); Spearman is the Pearson of the ranks, a single [N x F]ᵀ[N x H] product per session. Targets come from the kernel `panel.forward_returns` (executable, open to open; never a stored table), purged so every target window ends before `alpha.validation.oos_start` (E21 rule 4; the series stops at that bound). Pure arrays in, arrays out; no database. It does not change `pooled_rank_ic`, so `feature_ic_scores` and its recorded values stay bit-identical.
2. Record: one new method on `PostgresLedger` (S6, `ledger.py`), `record_sweep_block(request, identities, series_by_concept)`, in one transaction under `LEDGER_LOCK_KEY`: insert one `research_run` row per cell (kind `evidence`, mode `real`, `concept_id` the feature's concept row, shared `run_group` for the (timeframe, horizon) block, `spec_hash` the hash of the block's spec text that pins timeframe, horizon, target definition, panel snapshot hash, feature list hash and code commit) and, in the same transaction, move each to its terminal status with its `AttemptSeries` (`completed` with a series; a cell with no tested session is `failed` with no series, and stays charged under the existing `UNCHARGED_STATUSES` and resultless-failure rules). One transaction per block means a crash leaves no `started` orphan and a rerun of the same block is refused by `PRIOR_REAL_RUN_SQL` (E18's no-silent-repeat rule), never half-written. Blocks are the four horizons of the 1d tf (about 277 cells each); a block is computed fully (and cached outside the database) before its transaction opens.

The caller is a new oneshot step in the corpus chain, run after `ic_measure` and before any family reads a cell: `services/ic_sweep_recorder.py` (concept name `ic_sweep_recorder`, class `IcSweepRecorder`, a `BaseBatch` that computes through the pure function and writes only through the ledger). It does not write `feature_ic_scores`. The service registry gets its `_DAG_ORDER` and `_AGENT_ID_TO_UNIT` entries and an `alert.lag.*` key per the project rules.

Rules it must honour: E21 rules 1 to 6 as adopted; E17 per-session granularity (the series is the same kind of object as a book's D_s, on the common date calendar); E18 selection (the cells enter the StepM universe through `select_books.py`, which already reads `evidence` runs); `no_fill` (a missing feature value drops that name from that session, never a fill); `temporal_integrity` (features read by availability time, the target from the kernel); `determinism` (the block's series is a function of the snapshot hash, the code key and the spec hash). The ledger line declares `n_looks` (the batch's cell count) before each batch; 670 runs first and sets how large a batch may be.

Where `repro_frozen` applies: the new method edits `src/intelligence/research/ledger.py`, so `.venv/bin/python -m scripts.research.determinism.repro_frozen <scratch_dir> --logs /home/bg/dev/indicagent/logs` must report bit-identical, and the methodology ledger gets a line for the new write path (it adds no statistic and moves no recorded spec hash, as E21's adoption note already says). The pure function under `src/intelligence/measure/` is outside that gate but is imported by `services/ic_measure.py`: land it in a detached worktree off `origin/main` while no run that imports `ic_measure` is live (the corpus chain stops at `feature_complete` until this lands, ledger 2026-11-24f).

Tests: `session_rank_ic` against `scipy.stats.spearmanr` per session on a small random panel with NaN holes (exact to 1e-12), invariance to name order, NaN rule below `min_obs`, no read past `oos_start` (a planted target after the bound changes nothing); `record_sweep_block` against a test database: row count equals cell count, every row has a series, a second call with the same spec is refused with no new rows, a failed block leaves zero rows, the guard trigger still refuses a second series write, `n_sessions`, `span_start` and `span_end` headline columns equal the series; the unit test that no module other than `ledger.py` inserts into `research_run` or `research_run_series` keeps passing (extend its allow-list by nothing).

Cost (estimate): rows 1,108 `research_run` plus 1,108 series; a series is about 5,500 dates and values, about 12 bytes each in the arrays, so about 73 MB of series and a few MB of rows (E21's volume gate: measure row count and series bytes on one block before the full sweep, and record the measured numbers here). Compute: ranking dominates, 277 features x 5,500 sessions x about 3,000 names, roughly 20 to 40 minutes at 4 workers and well under the memory of `ic_measure` at width 16 when run in session chunks (todo 667's time-chunk pattern, bit-identical by construction since sessions are independent); measure on one block first.

Failure modes: stored `feature_vectors` values for warmup or path-dependent columns (refused by the existing admission gates, as `ic_measure` does); a regime or object-dependent column read without `refuse_regime_columns`; the sign problem (below); a feature whose concept row is missing; two sweeps writing the same block at once (the advisory lock and the spec-hash refusal); the target definition drifting between `ic_measure` and the recorder (both call `panel.forward_returns` with the same horizon list from APR `alpha.ic_measure.horizons`); the todo 666 decision (price-only targets skip dividends) must be ledgered before the first sweep, and the recorder inherits it.

Gates: tests by exit code, `repro_frozen` bit-identical, ruff, black, glossary, `/simplify`, `/review`, and an independent review before the first batch. Blocks nothing else; blocked by nothing but the lead's answers below.

## Questions the lead must settle before the build

1. `PostgresLedger._concept_id` looks a concept up only in `_RESEARCH_DOMAINS`, but E21 rule 3 wants the feature's own concept row (domain `feature`) as the cell's `concept_id`. Either widen that lookup to the feature domain (an edit to S6; `repro_frozen` covers it) or give each cell a research-domain identity of kind `member` with the feature as its parent. The first matches E21 as written.
2. Sign. StepM tests a mean above zero, and a level 1 cell can be strongly negative (`gap_z` at -0.023 in the old read). E21 does not say whether a cell's series is stored with the sign measured, with the sign fixed in-fold (design section 4.2 uses training-fold signs for `corpus_family`), or as two attempts per cell (two-sided, doubling the cells to about 2,216). This changes what the series is, so it needs a ledger line; I did not decide it.
3. Per-session IC at 1d horizons greater than 1 overlaps (MA(h-1)); StepM's `block_mean` (20) exceeds the longest horizon, so the correction handles it, but the E17 daily amendment's flat-top HAC (todo 547) is not what StepM uses per series. Confirm StepM stays as shipped for cells.

## Ruling aid for Q1 and Q2 (2026-11-24, indicagent-94; the lead decides)

### Q1: which concept row is a cell's `concept_id`

What the text says:
- `docs/plans/methodology-change-ledger.md:1285-1287` (E21 rule 3): "Every measured cell is recorded as one `research_run` attempt (kind `evidence`, mode `real`, `concept_id` the feature's concept row, `run_group` the batch, the spec pinning the cell definition including its coordinates)".
- `src/intelligence/research/ledger.py:77` `_RESEARCH_DOMAINS = ("family", "member", "combiner", "construction_rule", "book")`, and `ledger.py:477-485` `_concept_id` looks a name up only in those domains and raises `LedgerRefusal("unknown construction identity: ...")`. The live registry has 325 `feature`, 18 `member`, 80 `family`, 1 `book` rows.
- `research_run.concept_id` is a plain foreign key to `concept_registry` (migration 515, `concept_id uuid NOT NULL REFERENCES concept_registry (concept_id)`). The readers join without a domain filter (`src/api/routes/research.py:72`, `scripts/research/render_research_ledger.py:58`, `ledger.py:543`).

Options:
- A. Add `"feature"` to `_RESEARCH_DOMAINS` (a one-token S6 edit). Matches E21 as written. Cost: 0 extra concept rows, 1 series per cell, no change to the StepM universe size. The `repro_frozen` gate and a methodology line apply because the file is under `src/intelligence/research/`. A feature name is unique inside its domain only, so the lookup must be domain-qualified for a name that also exists as a member (check for collisions first; the record shows none today, unverified).
- B. One research-domain `member` identity per cell with the feature as parent. Cost: 1,108 new `member` rows beside today's 18, lineage edges, a `recipe` per member (`_check_recipes` refuses a run concept with no recipe when recipes are passed), and a registry that no longer separates tested families from swept columns. Deviates from E21 rule 3.
- C. No registry row; store the coordinates only in `spec_blob`. Not possible: `concept_id` is NOT NULL.

Recommendation: A. It is the literal E21 text, the smallest change, and keeps lineage (`informed_by`, `run_group`) pointing at the feature the person read.

### Q2: the sign of a cell's series

What the text says:
- `docs/plans/methodology-change-ledger.md:1280-1281` (E21 rule 2): "Each cell's series is its pooled per-session IC over the vintage (dates, finite values only)". Nothing says the sign is changed.
- `src/intelligence/statistics/stepm.py` docstring: "H0_k: series k's mean is at or below zero; the selection set is every k rejected". It is one-sided in the positive direction.
- `docs/plans/2026-09-26-unified-research-to-production-design.md:164`: "Equal weight ... sign from the family prior; for a family with no prior (`corpus_family`), sign of the expanding training-fold IC, which makes it an in-fold combiner" (also line 301 and `src/intelligence/research/combiner.py:331 in_fold_signs`). That is an in-fold sign for members of a book, a different object from a level 1 cell.
- Ledger E21 sets no direction; the design's section 7.3.2 "statistic beats zero" is the positive side. Silence means a strongly negative cell is never selected, although `gap_z`-type contrarian effects are real candidates (todo 461 and the 2026-08 negative-IC audit at `methodology-change-ledger.md:428-465` are the precedent for sign-asymmetric gates excluding contrarian features by construction).

Options and cost (measured read-only, no DB, shipped `stepm` helpers: `stationary_bootstrap_indices` and `hac_mean_test`, sample-studentized path, 1,500 sessions, 4,000 draws, block mean 20, step-1 critical t = 95th percentile of the maximum bootstrap t; the shipped `stepm` adjusted p of the top t matched the share of draws exactly on a 200-series check, 0.9893 both ways; total run under 2 minutes on one core). Critical t by effective correlation rho between cells:

| Universe | rho 0 | rho 0.3 | rho 0.7 | rho 0.9 |
|---|---|---|---|---|
| 16 series (today) | 2.74 | 2.67 | 2.49 | 2.10 |
| + 1,108 cells, one sign each (measured sign or in-fold sign) | 3.92 | 3.76 | 3.08 | 2.56 |
| + 1,108 cells, two attempts each (cell and its mirror) | 4.12 | 3.96 | 3.34 | 2.91 |
| + 2,216 independent cells (upper bound) | 4.09 | 3.86 | 3.06 | 2.54 |

- S1. Store the measured sign as is (positive side only). Universe +1,108. Critical t about 3.9 at rho 0 to 3.1 at rho 0.7. A contrarian cell can never be selected, and a cell's detected direction would have to be taken from the row afterwards, outside the correction.
- S2. In-fold sign (the sign of the expanding training-fold IC, as `in_fold_signs` does). Universe +1,108, same critical t as S1. The series would be the oriented per-session IC, so a contrarian feature enters positively only after a training window is read; that makes the series depend on a fitted choice, which E21 rule 2 does not describe (a pooled per-session IC) and needs a ledger line. The sign selection itself must then be inside the fold, never read by a person.
- S3. Two attempts per cell (the measured series and its negation). Universe +2,216. Critical t rises by 0.20 over S1 (about 5 percent: 3.92 to 4.12 at rho 0; 3.08 to 3.34 at rho 0.7; 2.56 to 2.91 at rho 0.9). It is the exact two-sided test, covers both directions with no fitted choice, and the doubled count is almost wholly a mirror, so the real tightening is the 0.2 in t, not the 2.0 times the cell count.
- Reading for `reversal_21`: its recorded adjusted p of 0.0135 and 0.0045 on 12 series (todo 670) correspond to a t near 3.0 to 3.3 (per-test p about 0.0135 over 12, an approximation from the todo's numbers, not the recorded t). Against these thresholds it would clear a 1,108-cell sweep only if the cells are strongly correlated (rho 0.7 or more; the ledger's effective breadth of about 8.4 of 230 at `construction-verdict-ledger.md:215` points that way but is a feature-correlation figure, not a cell-series one). At rho 0 to 0.3 it drops under S1, S2 and S3 alike. This is what todo 670 exists to measure on the real cell series; read the thresholds above as the scale of the problem.

Recommendation: S3. It needs no fitted choice, matches E21's blind counting ("a proposal never measured costs nothing"), keeps the series a plain per-session IC (so the E21 text stands unamended except one sentence), and the extra price over S1 is 0.2 in t. S2 is cheaper only in cell count and adds an in-fold dependency the recorder would have to own. Note S3 stores 2,216 rows and 146 MB of series (the estimate above doubled), still small.

If the lead prefers S1 (positive side only), record that the sweep tests only positive-IC features and that contrarian cells are read as disclosure, never selected.
