# 176-08 pre-flight notes (gathered 2026-09-23, before the run)

Read-only checks done early so the multi-day run does not trip on them. Re-verify each at run
time; these are a head start, not a substitute.

## Check (2) registry alignment: passes, but the plan's literal query is wrong

- `SELECT count(*) FROM concept_registry WHERE domain='feature'` returns **302**;
  `len(dataclasses.fields(FeatureVector))` is **300**.
- The two extra rows are `new_high_flag` and `new_low_flag` (status `deprecated`, created
  2026-07-09) and have **no `concept_gate` row**.
- ic_engine's real gate (`main()`, "Feature registry alignment gate") loads through
  `ConceptRegistryService.load_sync()`, whose `_LOAD_CONCEPTS_SYNC_SQL` inner-joins
  `concept_gate`. That join yields exactly 300 names, equal to the dataclass. The gate passes.
- Use the join form when re-checking:
  `SELECT count(*) FROM concept_registry r JOIN concept_gate g USING (concept_id) WHERE r.domain='feature'`.
- Both new features have a `concept_gate` row.

## Check (4) training window: holdout in effect

- `alpha.validation.oos_start` = `2025-12-24T05:15:00Z` (set), so the LEAST() clamp applies.
- `alpha.ic.earnings_season_conditioned` = `true`.

## Scope effect of 176-06's disk-backed skip (the verdict must state this)

`_plan_season_subcells` skips season sub-cells for any cross-sectional cell routed to a
disk-backed memmap (`use_disk`, triggered at `infra.ic_engine.disk_backed_min_rows` =
2,000,000 rows). Corpus arithmetic (COVERED_SCOPE row counts over ~9 regime cells per tf):

| tf | rows | ~rows per cell | cross-sectional season sub-cells |
|---|---|---|---|
| 5m | 75.1M | ~8M | skipped (disk-backed) |
| 15m | 25.7M | ~2.8M | mostly skipped; todo 386's exact count may pull some cells under 2M |
| 1h | 7.0M | ~0.8M | computed |
| 1d | 0.97M | ~0.1M | computed |

Per-cell truth comes from the `ic_engine.season_subcell_pass` log line (`use_disk`, `skipped`).
1d is 176-01's canonical gating tf, and 176-04's per-symbol path covers all four tfs, so the
verdict is not undermined, but it must say "cross-sectional earnings-season cells measured on
1h/1d (+ any in-RAM 15m cells)" rather than implying all tfs.

## Sequencing (agreed with concurrent session indicagent-62)

The run starts only after, in order: indicagent-62's `fix/174-code-review` ic_engine commits
(CR-03, WR-06, headroom APR + reserve floor, migration 352) merge; todo 386 (exact cell-row
count, `alpha.ic.max_cell_rows` back to 15M, migration 353) lands on top; the unit suite is
green. All of these move `code_content_key`, so one recompute absorbs them. Todo 389 (short-
horizon cell deletion) lands AFTER the verdict, per its pre-registration. Check with
indicagent-62 before starting the run.
