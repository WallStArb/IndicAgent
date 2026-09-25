# Phase 182: Security classification hierarchy (todo 384) - context

**Gathered:** 2026-09-25, owner decision to build (conversation, 2026-09-25).
**Design source:** `docs/research/stratification-security-classification-hierarchy.md` (Layer 1).
**Author:** Claude (Opus 5.5).

## Why now

The flat `instruments.contract_details->>'sector'` label was the only per-name classification.
It mixed asset classes and sectors at one level, encoded sub-sectors in strings
(`materials_mining`, `industrials_rail`), held a catch-all `equity` value (GLD, SMH, SPY, TLT,
XLF; fixed by migration 363), and left 40 active single names unlabeled. No industry group or
industry level exists anywhere. The research residual target no longer depends on labels (S1
uses causal price-correlation clusters, f83609725), so this phase is off the research critical
path; its consumers are stratification, peer groups, reporting and onboarding.

## Decisions (locked)

- **D-01 Scope is Layer 1 only.** `classification_scheme`, `classification_node`,
  `instrument_classification` exactly as the design doc specifies: point-in-time,
  append-only in effect (close `valid_to`, insert new), `ON DELETE RESTRICT`, partial unique
  index for one current row per (symbol, scheme), node-immutability guard in the seed (parent
  and level never change for a code; the seed crashes on disagreement). Layer 2's `parent_tag`
  is NOT built: the design doc's own trigger (a first hierarchical-tag consumer) has not fired.
- **D-02 First scheme: `indicagent_v1`, project-owned, four levels:** asset class > sector >
  industry group > industry. Codes embed their parent (`EQ`, `EQ.IT`, `EQ.IT.SEMI`,
  `EQ.IT.SEMI.EQUIP`), so a reparent mints a new code, as in GICS. `parent_code` is still
  stored explicitly (design doc rule).
- **D-03 Equity levels 2-4 follow the public GICS structure** (11 sectors, industry groups,
  industries) by name, but the scheme is not GICS and must not be called GICS: GICS
  assignments are licensed, and ETFs have none. `authority` = 'IndicAgent', `source_ref`
  records how each assignment was made.
- **D-04 Non-equity asset classes:** fixed income, commodity, currency, crypto, volatility,
  multi-asset, each with its own level-2 split (for example fixed income > rates / credit /
  municipal / inflation-linked / preferred; commodity > energy / precious metals / industrial
  metals / agriculture / broad). Exact node list is a plan deliverable, reviewed before seeding.
- **D-05 Assignment depth follows the instrument.** A single name goes to its industry (level
  4). An ETF goes to the deepest level its mandate pins down (SMH to the semiconductors
  industry; XLK to the IT sector; SPY to the equity asset class with a broad-market sector
  node). Assignment above the leaf is allowed by the design; consumers asking for a deeper level
  get the explicit `unclassified` stratum (D-08).
- **D-06 Sources.** Single names: IBKR `reqContractDetails` industry / category / subcategory,
  fetched through `src/providers/ibkr.py` (the only ib_async file), used as a seed candidate and
  human-reviewed into `indicagent_v1` nodes. ETFs: fund mandate (name, issuer description).
  `source_ref` distinguishes `ibkr_contract_details+review` from `fund_mandate`. The reviewed
  mapping is committed as data (a seed file or migration), never computed at runtime.
- **D-07 No history before the build date.** Every assignment's `valid_from` is the build date.
  The scheme did not exist earlier, so any earlier row would be a backfill from a current
  snapshot, which the design forbids. Research over pre-build history uses the causal
  clusters, not this table. Reclassifications from the build date on close the old row and
  insert a new one.
- **D-08 Read layer.** `ClassificationService` (`src/config/`, cached at init like
  `ConfigService` and `VocabularyService`, no hot-path DB calls): as-of lookup of a symbol's node
  at a requested level, returning the scheme-qualified `unclassified` label, never NULL, when
  the assignment does not reach that level or does not exist as of that date.
- **D-09 Coverage is enforced, not hoped for.** Every active instrument gets a current
  `indicagent_v1` assignment in this phase (273 today, including the 40 unlabeled 1d-pilot
  names). Onboarding (`src/config/instrument_onboarding.py`) requires a classification for any
  new instrument. A unit or CI test fails when an active instrument has no current assignment.
- **D-10 The flat label stops being a source of truth.** Its readers
  (`src/config/settings.py` Instrument.sector, `src/intelligence/pipeline/cache_manager.py`,
  `src/api/routes/signals.py`) move to `ClassificationService` (sector = level-2 node name).
  The JSON field stays in `contract_details` as historical data and is no longer written.
- **D-11 Migration discipline.** Schema and seed land as numbered migrations, applied live and
  committed in the same breath (CLAUDE.md rule). Next free number at plan time (363 is taken).

## Out of scope

- Layer 2 `parent_tag` and any custom soft taxonomy (D-01).
- GICS or any licensed classification feed; SIC or ICB schemes.
- Issuer identity (GOOG/GOOGL both carry rows, design doc open question 2).
- Using this table in the research residual target (S1 uses causal clusters by decision,
  2026-09-25).
- Options open-interest capture (an open owner question, separate).

## Canonical references

- `docs/research/stratification-security-classification-hierarchy.md` (design, Layer 1 schema)
- `production/migrations/363_sector_label_fixes.sql` (interim flat-label cleanup)
- `.planning/todos/pending/384-security-classification-hierarchy-build-trigger-already-fired.md`
- `docs/foundation/controlled-vocabulary-registry.md`, `docs/foundation/instrument-tag-registry.md`
  (sibling registries; this is deliberately a third, separate system)
- `docs/foundation/naming-system.md` (concept `classification` -> `ClassificationService`,
  `classification_*` tables)
