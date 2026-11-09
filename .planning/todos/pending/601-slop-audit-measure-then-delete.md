---
status: pending
priority: P1
filed: 2026-11-09
source: owner 2026-11-09 ("clean up slop like Jim Simons would demand"); measured baseline below
---

# Slop audit: measure the consumer graph, then delete what has no reader

## What

Vulture at 80% confidence finds only 4 items, so dead-code lint is clean; the slop is structural. Baseline measured 2026-11-09:

- `feature_vectors`: 311 stored columns; the number with no consumer is not yet counted.
- Largest files: `feature_factory.py` 3,922 lines, `services/bar_reconciliation_audit.py` 3,146, `services/backfill_feature_factory.py` 2,424 (a second "feature factory": check for duplicated logic), `research/runner.py` 2,395, `kernels/price.py` 2,378, `providers/ibkr.py` 2,357, `services/_batch_utils.py` 2,241, `services/bar_derivation.py` 2,127.
- Docs: 468 markdown files (17 in `docs/plans/`, 106 archived). Tests: 524 files.

## Protocol (Musk 5-step, in order: requirements, delete, simplify, accelerate, automate)

1. Consumer graph: for every `feature_vectors` column, find the kernel, family, book, IC-measure or registry row that reads it. A column with no reader is NOT a deletion candidate (owner 2026-11-09: no reader does not mean no signal; never drop data that could contain signal). It is an untested hypothesis: route it to the `ic_measure` discovery sweep so it earns a counted verdict or a family. Output is a table in `docs/research/` with the counts per class.
2. Compare `backfill_feature_factory` against `feature_factory`; merge or delete the duplicate path.
3. After the Massive basis study (todo 600): delete the completeness logic it replaces (ask-ledger readers, most of D7 `bar_reconciliation_audit`, gap_plan for Massive spans).
4. Remove tests in the same commit as the code they cover.
5. Large-file splits only where step 1 or 2 shows a seam; size alone is not a reason.

## Gates

Never edit a module a live fingerprinted batch writer imports while its run is live or resumable. Each deletion: `/simplify`, `/review`, `pytest tests/unit/ -n auto`, and `repro_frozen` bit-identical when research or statistics files change. A column drop that touches a compressed hypertable follows the compressed-column migration template and ends with `VACUUM`.

## First measurement, 2026-11-09 (literal-name scan, an upper bound)

Of 311 `feature_vectors` columns, 104 are named in a research, service, measure or script module and 206 (66%) appear only in the kernels and `feature_factory.py` that produce them (examples: `aroon_*`, `cci_*`, `bars_since_*`, `bsl_dist_atr`, `choch_*`, `demand_*`, `breaker_*`). This overcounts unread columns: it misses dynamic reads (the IC measure over all columns, family selection by registry prefix). Next: join against the concept registry and the IC measure's column set, then split the 206 into read generically, read by a family, and truly unread. Do not drop any column on this scan alone.

## Ruling 2026-11-09 (owner): discovery over deletion for feature columns

Columns are deleted only on data-quality grounds: constant, all-NULL, exact duplicates (the todo 564 class), or failing the volume, lookahead or basis checks. Everything else stays and is swept by the `ic_measure` proposer, Renaissance-style: measure IC across all of them, count every look against the vintage, select with StepM, promote only on positive net expectation. The proposer's coverage of all 311 columns is the thing to verify, and the multiple-testing count for a 206-column sweep must be declared before the sweep runs. The 66% figure above is a coverage-of-readers number, not a slop number. Code-side slop (duplicate factories, completeness logic Massive replaces, dead tests) is unchanged.

## What the discovery sweep tests per feature (owner 2026-11-09)

A feature that belongs to no family yet is evaluated three ways, in this order, each counted against the vintage:

1. Alone: IC term structure across horizons (`ic_measure` today).
2. Conditional on regime: IC split by the stored regimes (segment by regime). A near-zero pooled IC can hide a strong, sign-flipping conditional IC.
3. Incremental: IC after controlling for existing family members (partial or orthogonalized IC), as a candidate input to the S7 combiner. A feature correlated with an existing member adds nothing whatever its own IC.

Pairwise interactions are tested only for features that pass 1 or 2, or that carry a pre-registered mechanism. About 21,000 pairs among 206 columns would guarantee false positives; test hierarchically, declare the look count before the run, select with StepM. A feature that passes becomes a family member by pre-registration, never by an outcome screen alone (glossary: family).
