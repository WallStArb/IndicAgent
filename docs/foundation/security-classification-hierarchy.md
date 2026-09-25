# Security Classification Hierarchy (SCH)

**Author:** Claude (Opus 5.5)
**Status:** current, Layer 1 built in Phase 182 (2026-09-25)
**Last Updated:** 2026-09-25
**Phase introduced:** 182 (todo 384, closed)
**Design record:** [stratification-security-classification-hierarchy.md](../research/stratification-security-classification-hierarchy.md)

---

## What it is

The Security Classification Hierarchy answers one question per instrument: where does it sit in a
single-parent tree of asset class, sector, industry group and industry, as of a given date. It
replaces the flat `instruments.contract_details->>'sector'` string, which mixed asset classes and
sectors at one level, encoded sub-sectors inside strings (`materials_mining`,
`industrials_rail`), held a catch-all `equity` value and left 40 active single names blank. No
industry group or industry level existed anywhere before this.

Consumers are stratification, peer groups, reporting and onboarding. Research over history
before 2026-09-25 does not use it (see "No history before the build date" below); the S1 residual
target uses causal price-correlation clusters instead.

## Why a third registry

The project already has two registries for knowledge about instruments and codes. A
classification fits neither:

- **ITR** (`instrument_tags`) holds falsifiable claims. A tag carries weight, evidence and a
  p-value, and can expire on repeated failed measurement. A classification assignment is a
  decision about where a security belongs; there is nothing to measure it against, so those
  columns would be meaningless.
- **CVR** (`controlled_vocabulary`) holds flat definitional codes per namespace. A
  classification needs a single-parent tree, effective dating per instrument, and an
  immutable parent for each node. Adding `parent_code` to CVR was proposed and retracted on
  2026-07-04 because it would make every namespace pay for a structure only one needs.

So the hierarchy has its own three tables, its own read service and its own enforcement, like
its siblings.

## Tables

Created by migration 364.

**`classification_scheme`** - one row per scheme: `scheme` (identifier, `^[a-z0-9_]+$`), `name`,
`authority`, `source_ref`. Today there is exactly one row, `indicagent_v1`, authority
`IndicAgent`.

**`classification_node`** - the tree. Primary key `(scheme, code)`; `parent_code` references
`(scheme, code)` in the same table; `level` (1 = asset class); `name`; `path` (the code chain from
the root down to this node, stored so readers never recurse). Checks: a node has no parent
exactly when it is level 1, `cardinality(path) = level`, and the last path element is the code.

**`instrument_classification`** - one row per assignment: `symbol`, `scheme`, `code`,
`valid_from`, `valid_to`, `source_ref`. Primary key `(symbol, scheme, valid_from)`. Foreign key
to `instruments(symbol)` with `ON DELETE RESTRICT`, so deleting an instrument that has a
classification fails instead of erasing its history. Foreign key to `classification_node`.

### Invariants

- **Append-only in effect.** A reclassification closes the current row's `valid_to` and inserts
  a new row. Rows are never updated in place to change a code.
- **One current row.** The partial unique index `uq_instrument_classification_current` on
  `(symbol, scheme) WHERE valid_to IS NULL` makes a second open row a unique violation.
- **Node immutability.** A code's `parent_code` and `level` never change. Codes embed their
  parent (`EQ`, `EQ.IT`, `EQ.IT.SEMI`, `EQ.IT.SEMI.EQUIP`), so moving a node mints a new code, the
  same way GICS handles a reparent. Every seed or node-adding migration runs a guard that raises
  if a staged node disagrees with the stored one. Only `name` may be updated.
- **Deepest-node membership.** An instrument is assigned to one node, the deepest its identity
  supports. Membership at every shallower level is implied by that node's `path`.
- **As-of joins.** A historical question joins on `valid_from <= d AND (valid_to IS NULL OR d <
  valid_to)`. Joining on today's current row for a past date leaks future reclassifications
  into the past.

### No history before the build date

Every assignment's `valid_from` is the date migration 365 was applied, 2026-09-25. The scheme did
not exist earlier. Writing earlier rows would mean backfilling today's snapshot into the past,
which is exactly the look-ahead this design exists to prevent. An as-of lookup for a date before
2026-09-25 returns the unclassified stratum.

## The indicagent_v1 scheme

Four levels: asset class, sector, industry group, industry. Seven asset classes: `EQ` Equity,
`FI` Fixed income, `CMD` Commodity, `CCY` Currency, `CRY` Crypto, `VOL` Volatility, `MA`
Multi-asset. At build time the tree has 118 nodes (7, 31, 27 and 53 at levels 1 to 4).

**Equity levels 2 to 4 are named after the public GICS structure** (11 sectors, industry groups,
industries) but the scheme is not GICS and must not be called GICS. GICS assignments are licensed
and ETFs have none; every assignment here is IndicAgent's own decision, with authority
`IndicAgent`. `EQ.BROAD` ("Broad market (multi-sector)") is a level-2 node for funds whose
mandate spans two or more sectors. The seed validator rejects "GICS" in any scheme field.

**Non-equity branches** have their own level-2 splits (for example fixed income into government
rates, corporate credit, municipal, inflation-linked, preferred and others; commodity into energy
commodities, precious metals, industrial metals, agriculture, broad). Non-equity nodes are seeded
only when an instrument uses them, so `CCY.EM`, `CRY.BROAD`, `VOL.RATES` and `MA.ALLOC` wait until
an instrument needs one. All 25 equity industry groups are seeded in full; equity level 4 is
seeded on use.

**Node names are unique within a level.** The level-2 name becomes `Instrument.sector`, so two
level-2 nodes named "Energy" (equity and commodity) would silently merge; the commodity node is
"Energy commodities".

**Geography and style are deliberately not levels.** A country fund or a value fund is placed by
its sector mandate (usually `EQ.BROAD`). Country and style exposures are tag questions for ITR,
where they can be measured.

### Assignment depth and source_ref

Depth follows the instrument:

- A single name goes to its industry (level 4). SMH-style funds pinned to one industry go there
  too.
- An ETF goes to the deepest node holding roughly 80% or more of its index weight by the fund's
  own methodology, otherwise one level up; a mandate spanning two or more sectors goes to
  `EQ.BROAD`. XLK sits at `EQ.IT`, SMH at `EQ.IT.SEMI.EQUIP`, SPY at `EQ.BROAD`.
- A consumer asking for a deeper level than an assignment reaches gets the unclassified stratum,
  not a guess.

`source_ref` records how each assignment was made. The allowed values (`ALLOWED_SOURCE_REFS`):

| source_ref | Applies to | Basis |
|---|---|---|
| `ibkr_contract_details+review` | single-name equities (168 at build) | IBKR `reqContractDetails` industry/category/subcategory as a candidate, reviewed into a node against the company's primary business |
| `fund_mandate` | ETFs and other funds (105 at build) | the fund's stated index and methodology |
| `contract_spec` | futures and FX rows (22 at build, all inactive) | the contract specification |

The reviewed mapping is committed data (`src/config/classification_seed_data.py`), never computed
at runtime. The review record, including every override and its evidence, is
`.planning/phases/182-security-classification-hierarchy-todo-384/182-03-REVIEW.md`.

## Read layer

**`ClassificationService`** (`src/config/classification_service.py`) is cached at init like
`ConfigService` and `VocabularyService`: `initialize()` loads both tables once, and every reader
after that is a synchronous dict lookup with no database call.

- `node_at_level(symbol, level, as_of=None)` returns the code of the level-`level` ancestor of
  the symbol's as-of assignment.
- `name_at_level(symbol, level, as_of=None)` returns that node's name.
- `assignment_as_of(symbol, as_of=None)` returns the raw row or None.

`node_at_level` and `name_at_level` never return None. When no assignment applies on that date,
or the assignment does not reach the requested level, they return the scheme-qualified
**unclassified stratum**, `indicagent_v1:unclassified` (`unclassified_code()`). Stratified
analysis treats it as its own explicit bucket rather than dropping rows.

**`current_level_name_sql(alias, level=2)`** returns a correlated scalar subquery for synchronous
SQL builders that cannot hold a service instance. `get_active_contracts()` and
`cache_manager._instrument_from_row()` use it to fill `Instrument.sector` with the level-2 node
name, falling back to the unclassified label. `contract_details->>'sector'` is historical data
only: it is still stored, no longer written by onboarding, and no longer read as a source of
truth.

## Enforcement

GitHub CI runs `tests/unit/` only and has no database, so coverage cannot be a CI test. It is
enforced at three points that do run automatically:

1. **Seed time.** Migration 365 ends with a `DO` block that raises, rolling back the whole
   seed, if any active instrument lacks a current assignment. The seed also carries the node
   immutability guard and an assignment-disagreement guard.
2. **Onboarding.** `onboard_instrument()` (`src/config/instrument_onboarding.py`) requires a
   `ClassificationAssignment` and hard-fails without one; there is no skip escape hatch. The row
   is written inside the onboarding transaction.
3. **Nightly drift audit.** `ClassificationCoverageAuditor` (`python -m
   src.config.classification_coverage`) runs in `ops_corpus_pipeline_run.sh` beside
   `VocabularyDriftAuditor`. It reports any active instrument without a current assignment
   (integrity_monitor fact, OTel counter, `logger.error` naming the symbols) and the unclassified
   stratum size per level. It is observability, not a gate.

The unit suite covers the service and the seed logic without a database, and a byte-equality
test keeps migration 365 identical to the data module's render.

Two integration test files check the live schema and data:
`tests/integration/test_classification_schema.py` (keys, the current-row index, RESTRICT, the
immutability guard, path consistency, no scheme named GICS) and
`tests/integration/test_instrument_classification_coverage.py` (coverage, source_ref, the
build-date floor, depth, the service round trip, `Instrument.sector`). They query the live
`indicagent` DB, write only inside rolled-back transactions, and are **local-only: they are not
GitHub-CI-enforced**. Run them with `--noconftest` until todo 413 fixes the integration
conftest's scratch-DB rebuild:

```
.venv/bin/pytest tests/integration/test_classification_schema.py \
  tests/integration/test_instrument_classification_coverage.py -m integration --noconftest -q
```

## Changing the classification

**Reclassify an instrument.** Write a migration that sets `valid_to` on the current row to the
change date and inserts a new row with `valid_from` equal to that date and the new code and
`source_ref`. Record the evidence in the migration header. Never update `code` in place.

**Add a node.** Write a migration that runs `render_node_guard_sql(scheme, nodes)` from
`src/config/classification_seed.py` for the new node and its ancestors, then inserts the node
with its `path`. The guard fails the migration if any staged node disagrees with a stored one on
parent or level. Moving a node means a new code, never an edited parent.

**Onboard an instrument.** Pass a `ClassificationAssignment(code, source_ref)` to
`onboard_instrument()`. The code must already be a current node.

Apply migrations with `psql -v ON_ERROR_STOP=1 -f` and commit them in the same session.

## Not built

**Layer 2** (a `parent_tag` column on `tag_vocabulary`, for IndicAgent's own soft, weighted
sub-classifications under ITR) is not built. Its trigger in the design doc, the first concrete
custom-classification research question with a defined measurement, has not fired. No second scheme exists; adding one means a new `classification_scheme` row and its own
nodes, with the same invariants.
