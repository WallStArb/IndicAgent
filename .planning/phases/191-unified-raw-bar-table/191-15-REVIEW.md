---
phase: 191-unified-raw-bar-table
plan: 15
reviewed: 2026-10-17
reviewer: fresh-context code review (independent)
verdict: PASS
---

# Phase 191 Plan 15 review: ops scripts and helpers off the canonical source column

Range reviewed: `git diff d47527b19..HEAD` (51ff84d26 RED tests, 5d22c325a GREEN conversion,
e8a9af300 docs). Every conversion was checked against the pre-diff code
(`git show d47527b19:<file>`), the vendor_kind map (`src/intelligence/bars/vendor_kind.py`),
and live data (read-only psql).

## Verdict: PASS

No P1 (crash/data-loss) or P2 (wrong result) defects. Every predicate conversion is row-equivalent
to its old form on the current label map and live data; the one intentional semantic widening
(twin query, P3-1) touches report-only counters outside the exit-code arithmetic. Five P3 notes
follow, none blocking.

## Findings

### P3-1 Report counters: 1d twin query now counts (ibkr, fallback) rows the old query excluded
- File: `scripts/ops/bars/ops_raw_backfill.py:1010-1027` (consumer at 1200-1205)
- Summary: the old `_canonical_1d_twin_sql` inner-joined `VALUES (label, vendor)` of the 7
  raw-eligible labels, so canonical 1d rows whose source was `ibkr_fallback` never entered
  `n`/`with_twin`; the new query counts every 1d row grouped by `m.vendor`.
- Live impact: 197,083 canonical `(ibkr, fallback)` 1d rows exist (vs 302,744 `(ibkr, named)`,
  6,661,722 `(tradier, consolidated)`), so `exclusions["1d_canonical_with_observation_twin"]`,
  `1d_canonical_residue_no_observation_twin` and `residue_1d_by_symbol` shift versus pre-swap
  runs. None of these feed `unexplained` or `exit_code` (`finalize_report` reads twin_missing,
  unlabelled, raw_rows_without_source_key, null_1d_request, revisions only), and including
  fallback rows is arguably more correct. The `k.source = m.vendor` join itself is right:
  `ohlcv_observation` has no kind column, and the old code joined at the same vendor granularity
  (`k.source = l.vendor`). Failure scenario: an operator diffing a post-plan-15 `--check` report
  against a pre-swap one sees unexplained counter movement with no code note; the SUMMARY states
  the join but not the inclusion change.

### P3-2 `_PREMOVE_SQL` matches a vendor x kind cross product, not pair tuples
- File: `scripts/ops/bars/ops_data_bar_check.py:186-197` (binding at 522-532)
- Summary: `m.vendor = ANY(%s) AND m.kind = ANY(%s)` equals the old `m.source = ANY(('ibkr_named',
  'ibkr_venue'))` only because both judged pairs share vendor `ibkr`; the set semantics are
  cross-product, not pair-membership.
- Failure scenario: if `IBKR_1D_SOURCES` ever gains a non-ibkr label (e.g. a Tradier judged
  source), the predicate silently also matches the mixed tuples (ibkr, consolidated) or (tradier,
  named) and the pre-move defect count drifts with no error. `ops_raw_backfill.canonical_select_sql`
  already shows the right shape: `(m.vendor, m.kind) IN (VALUES ...)`. Not wrong today (verified:
  `IBKR_1D_PAIRS == {('ibkr','named'), ('ibkr','venue')}`).

### P3-3 `_LATE_NAMES_SQL` interpolates map constants into the SQL string, dropping parameterization
- File: `scripts/ops/bars/ops_head_rerun.py:204-212`
- Summary: the converted query f-string-interpolates `label_to_vendor_kind(SOURCE_NAMED)` where
  the old query bound everything with `%s`, and bypasses the `_lit()` safe-token guard
  `ops_raw_backfill` uses for the same pattern.
- Failure scenario: none today (values are code constants `'ibkr'`/`'named'` from the map), but a
  future pair value containing a quote would corrupt the SQL silently instead of being refused;
  the codebase's own discipline for constants-in-SQL is `_lit()`.

### P3-4 Revision predicate enumerates old_source forms where the pair columns are convention-proof
- File: `scripts/ops/bars/ops_data_bar_check.py:93-104`
- Summary: `IBKR_1D_REVISION_SOURCES` enumerates legacy labels plus `pair_token` forms. Complete
  for every writer convention in the codebase today (verified live: `ibkr_named` 3,781,729 /
  `ibkr/named` 18 / `ibkr/venue` 0; the bare `ibkr` 7,154 and `alpaca` 418 rows are smart_trades /
  sip_rth series, correctly out of scope). But `ohlcv_revision` carries its own populated
  `vendor`/`kind` columns on all legacy rows (3,781,729 of 3,781,729 non-null), so
  `r.vendor = 'ibkr' AND r.kind IN ('named','venue')` would be immune to any future old_source
  convention change.
- Failure scenario: a third old_source convention (e.g. the backfill reconstruction's
  bare-vendor fallback `VENDOR_KIND_TO_LABEL.get(pair, vendor)` ever applied to an unmapped
  canonical pair) reintroduces the exact silent-miss T-191-54 this deviation fixed.

### P3-5 Exporter collapse depends on vendor/kind column adjacency
- File: `scripts/ops/bars/ops_export_known_answer_fixtures.py:66-72`
- Summary: the legacy `source` column is only emitted when `kind` immediately follows `vendor`
  in `cur.description`; a reordered or separated pair silently writes a two-column fixture
  instead of failing loud.
- Failure scenario: a future edit to `_COLS` (or a new export query) separates the columns and
  the fixture shape drifts without an error; caught only by whoever diffs the fixture. The
  round-trip itself is sound: `VENDOR_KIND_TO_LABEL` is an exact bijection over the 9 labels
  (verified programmatically), unmapped pairs raise KeyError naming the pair (tested), and
  vendor/kind are NOT NULL on canonical so no None reaches the collapse.

## Evidence

- Diffs: all six script conversions plus every test file read in full, old vs new
  (`git show d47527b19:<path>` for each).
- Label map: 9 labels to 9 distinct pairs (bijection verified by import);
  `vendor_labels()` = map minus derived vendor minus `CANONICAL_ONLY_KINDS` = {fallback, 5m_grid}
  (`services/ohlcv_raw_writer.py:73`), so every archive-bridge and union-keys join is row-equivalent
  to the old label join.
- Live data (read-only psql):
  - `market_data_ohlcv` has `vendor`/`kind` NOT NULL, no `source` column (prod and
    `indicagent_test`); the tradeable view exposes vendor/kind (volume nulled by kind), no source.
  - canonical 1d pairs: (tradier, consolidated) 6,661,722 / (ibkr, named) 302,744 /
    (ibkr, fallback) 197,083 - nothing outside the vendor set the old twin join used.
  - `ohlcv_revision.old_source` distinct values: ibkr_named 3,781,729 / tradier 155,350 /
    derived_5m 16,355 / ibkr 7,154 (all (ibkr, smart_trades) 1d raw-series rows) /
    ibkr_fallback 4,321 / alpaca 418 (all (alpaca, sip_rth) 5m) / ibkr/smart_trades 57 /
    ibkr/named 18; all legacy ibkr_named/ibkr_venue rows carry populated vendor/kind.
  - Writer convention confirmed in code: `services/ohlcv_raw_writer.py:428-436` and
    `services/bar_derivation.py:1378, 1961` log `old_source = pair_token(vendor, kind)`.
- Sweeps: repo-wide grep for `ops_masked_slot_baseline` in .py (zero hits; remaining
  masked_slot mentions are `bar_reconciliation_audit.check_masked_slots`, a different concept,
  plus historical .planning/docs records); canonical-source predicate sweep over src/services/
  scripts (every residual `source` read is another table: ohlcv_load, ohlcv_observation,
  ohlcv_request, ohlcv_intraday_raw_archive, instrument_tags, dividend_event_coverage) - matches
  the SUMMARY's disposition table, spot-verified on six entries.
- Tests: the eight changed unit test files pass (137 passed), and the full
  `pytest tests/unit/ -q` suite run by this reviewer exits 0 with the same two unrelated skips
  the SUMMARY reports. The marker-based tests assert the
  exact bound lists (pre-move vendors/kinds, the four-form revision set excluding tradier,
  (tradier, consolidated) for the history predicate) and SQL shape (`m.source` absent); every
  new/changed test fails against the old code (attribute or assertion), none passes trivially on
  both. Integration test not executed by this reviewer (writes to indicagent_test); its fixture
  insert matches the swapped schema verified above.
- SOP: scripts import src only (Ring rule holds; no src change in the diff apart from none);
  no new numeric tunables (all new constants derive from the vendor_kind map); ops scripts stay
  read-only diagnostics/exporters writing files, no DAG surface touched; naming follows the
  constant/function conventions. No migrations.
- Deletion basis: the swap script drops `source` and the `market_data_ohlcv_no_synthetic_fill`
  check and adds vendor/kind NOT NULL (`ops_canonical_vendor_kind_swap.py:663-667`), so a
  surviving synthetic row would have failed the NOT NULL constraints - the deleted script's
  subject cannot be expressed post-swap.

## Deviation confirmations (executor's four)

1. **ops_masked_slot_baseline deleted (D-191-15-A): CONFIRMED.** Subject provably gone (plan
   185-12 stopped storing synthetic fill; post-swap table cannot represent it, per the NOT NULL
   evidence above); script, test, and both allow-list entries removed; zero dangling .py
   references repo-wide; same precedent as 191-11's deletions.
2. **ops_d1_bootstrap.py listed in plan but deleted by 191-11: CONFIRMED.** The plan's
   files_modified lists it and its test; commit 0add3a02d ("delete the four old-store scripts
   with no live caller") deleted both; neither exists on disk.
3. **ohlcv_revision.old_source dual convention (D-191-15-B): CONFIRMED.** Live data holds both
   conventions; the four-form set covers both writer code paths for judged named/venue keys and
   correctly excludes the raw-side smart_trades/sip_rth rows the pre-swap predicate also never
   matched. See P3-4 for the convention-proof alternative.
4. **Test files beyond the plan's list: CONFIRMED.** Plan listed four test files; test_ops_raw_backfill,
   test_ops_source_policy, test_truncated_bar_scan existed and asserted the old SQL (updating them
   was necessary, not optional), and the exporter had no test. The integration fixture conversion
   matches the swapped test schema.
