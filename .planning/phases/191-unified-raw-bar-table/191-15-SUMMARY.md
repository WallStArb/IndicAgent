---
phase: 191-unified-raw-bar-table
plan: 15
subsystem: database
tags: [vendor-kind, ops-scripts, sql-conversion, tdd]

requires:
  - phase: 191-unified-raw-bar-table
    provides: "plan 14's swap (canonical market_data_ohlcv carries vendor and kind; source is gone) and plan 01's vendor_kind map"
provides:
  - "Every ad hoc ops script and helper that read the canonical source column reads vendor and kind; no code selects, filters or inserts market_data_ohlcv.source"
  - "ohlcv_revision.old_source dual convention handled: the data_bar_check known-answer predicate accepts legacy labels and the vendor/kind token the raw writer logs since D2"
  - "The plan-08 fixture export keeps its source column: vendor/kind collapse through VENDOR_KIND_TO_LABEL, unmapped pair fails loud"
  - "ops_masked_slot_baseline deleted (its subject left canonical with plan 185-12)"
affects: [191-17, ops-diagnostics, integration-harness]

tech-stack:
  added: []
  patterns:
    - "Pair bridging: archive-side joins keep the source label (ohlcv_intraday_raw_archive keeps its column) and reach canonical by (m.vendor, m.kind) = (l.vendor, l.kind); canonical-only reads filter by raw-eligible pair membership, never a label join"
    - "Legacy single-column rendering through pair_token/vendor_kind_to_label instead of hand-typed label strings"

key-files:
  created:
    - tests/unit/scripts/test_ops_export_known_answer_fixtures.py
  modified:
    - scripts/ops/bars/ops_data_bar_check.py
    - scripts/ops/bars/ops_head_rerun.py
    - scripts/ops/bars/ops_source_policy.py
    - scripts/ops/bars/ops_truncated_bar_scan.py
    - scripts/ops/bars/ops_export_known_answer_fixtures.py
    - scripts/ops/bars/ops_raw_backfill.py
    - tests/unit/scripts/test_data_bar_check.py
    - tests/unit/scripts/test_head_rerun.py
    - tests/unit/scripts/test_ops_raw_backfill.py
    - tests/unit/scripts/test_ops_source_policy.py
    - tests/unit/scripts/test_truncated_bar_scan.py
    - tests/unit/test_market_data_ohlcv_boundary.py
    - tests/unit/test_market_data_ohlcv_no_synthetic_fill.py
    - tests/integration/test_market_data_ohlcv_tradeable_view.py
  deleted:
    - scripts/ops/bars/ops_masked_slot_baseline.py
    - tests/unit/scripts/test_masked_slot_baseline.py

decisions:
  - id: D-191-15-A
    decision: ops_masked_slot_baseline is deleted, not converted
    why: its subject (synthetic_fill rows in canonical) was deleted by plan 185-12 and the post-swap table has no vendor/kind for them (the NOT VALID check went with the column); converting would need a hand-typed label the plan itself forbids. Same precedent as 191-11's four old-store script deletions
  - id: D-191-15-B
    decision: the known-answer revision predicate matches both ohlcv_revision.old_source conventions
    why: live data holds both (legacy labels pre-swap, vendor/kind tokens after); a legacy-only predicate would read a replaced key the post-swap writer logged as open, the exact silent-wrong threat T-191-54
metrics:
  duration: "about 45 minutes"
  completed: 2026-10-17T02:55Z
---

# Phase 191 Plan 15: ops scripts and helpers off the canonical source column

Converted the remaining ad hoc readers of the canonical `source` column (diagnostic ops scripts and the fixture exporter) to `vendor` and `kind` through the vendor_kind map, deleted the one script whose subject no longer exists, and handled the mixed ohlcv_revision.old_source conventions the swap left in live data.

## What was done

Task 1 (TDD): failing tests first (51ff84d26), then the conversion (5d22c325a).

- ops_data_bar_check: the known-answer stored row arrives as (vendor, kind) and renders to a label through vendor_kind_to_label (unmapped pair fails loud); the Tradier-history and pre-move predicates bind pairs derived from IBKR_1D_SOURCES; the ohlcv_revision predicate accepts legacy labels plus pair_token forms (D-191-15-B).
- ops_head_rerun: the late-names SQL extracted to _LATE_NAMES_SQL on the (ibkr, named) pair via label_to_vendor_kind(SOURCE_NAMED); the rest of the file was already pair-based (plan 191-11/13 work; only this one query remained).
- ops_source_policy: _INCUMBENT_SQL binds $2/$3 from label_to_vendor_kind(SOURCE_TRADIER).
- ops_truncated_bar_scan: _CANON_SQL selects vendor directly; the LABEL_TO_VENDOR_KIND label lookup in the consumer is gone.
- ops_export_known_answer_fixtures: selects vendor and kind; _write_cursor_rows collapses an adjacent pair into the legacy `source` label column, so the plan-08 fixture shape is byte-identical (header and label values round-trip).
- ops_raw_backfill: canonical_select_sql pair-filters with a VALUES membership test (no label join); the archive bridge (disagreeing select, vs-archive balance, disagree sample) joins its label to the canonical pair; _EXCLUSION_SQL groups by (vendor, kind) with DERIVED_PAIR named and unlabelled keys reported as pair tokens; the 1d observation twin matches k.source = m.vendor; the union-keys canonical branch joins on the pair. Archive-side a.source reads and the ohlcv_observation VALUES alias m are untouched by design.
- tests/integration/test_market_data_ohlcv_tradeable_view.py: the fixture insert carries (vendor, kind); the test passes against the swapped indicagent_test table.
- label_inputs.py: no change needed; its only source read is dividend_event_coverage.source (a different table that keeps the column). Verified, not skipped.

## Widened sweep: every remaining hit dispositioned

`grep -rlE "market_data_ohlcv" src services scripts --include=*.py | xargs grep -nE "(^|[^_.a-zA-Z])source\b"`, comments stripped, reviewed line by line. market_data_ohlcv_old and ops_canonical_vendor_kind_swap are excluded (the old table keeps its column until plan 17; the swap script is its history). Every remaining hit:

| File | Hits | Disposition |
|---|---|---|
| scripts/ops/bars/ops_raw_backfill.py | 26 | ohlcv_load.source INSERT/reads, ohlcv_observation VALUES alias + o.source mapping, archive a.source joins (label column by design), ohlcv_request, prose |
| services/ic_measure.py | 24 | FeatureSource dataclass fields and docstrings; no canonical SQL |
| scripts/ops/bars/ops_capture_completeness.py | 13 | ohlcv_load.source ledger reads (the table keeps source); ohlcv_raw reads use vendor; canonical appears in a docstring only |
| services/bar_reconciliation_audit.py | 12 | ohlcv_load.source queries; prose |
| services/tag_calibrator.py | 9 | instrument_tags/instrument_annotations source column |
| src/intelligence/research/guards.py | 8 | SignalSource type; prose |
| scripts/ops/bars/ops_selection_gate.py | 6 | ohlcv_intraday_raw_archive.source (line 1215 names the table); comment |
| services/cross_sectional_regime_model.py | 5 | instrument_tags source='human' |
| services/bar_derivation.py | 5 | ohlcv_load.source INSERT; label_to_vendor_kind(row["source"]) over a policy/ledger row; prose (live unit, plan 13 territory) |
| scripts/ops/bars/ops_data_bar_check.py | 5 | ohlcv_revision.old_source (both conventions matched), dividend_event_coverage c.source='yahoo', comments |
| src/intelligence/research/snapshot.py | 4 | dividend_event_coverage.source='yahoo'; manifest dict keys (untouched; no research edit, no repro_frozen trigger) |
| services/_batch_utils.py | 4 | docstrings |
| src/intelligence/services/bar_history_seeder.py | 3 | Bar payload label fields (source=SOURCE_IBKR_SEED); bar_writer maps labels to pairs |
| src/config/vocabulary_drift.py | 3 | prose about feature_vectors columns |
| services/feature_vector_pipeline.py | 3 | docstrings |
| services/bar_writer.py | 3 | payload label to pair mapping (the raw writer's own labels) |
| src/intelligence/bars/sources.py | 2 | docstring identifiers |
| src/intelligence/bars/daily_rule.py | 2 | primary_source policy field prose |
| services/regime_writer.py, services/backfill_feature_factory.py | 2+2 | prose; getattr(b, "source") payload field |
| scripts/ops/bars/ops_head_rerun.py | 2 | ohlcv_request r.source; comment |
| scripts/ops/bars/ops_export_known_answer_fixtures.py | 2 | comments describing the collapse |
| scripts/infrastructure/features_capture_regime_kernel_golden.py | 2 | manifest dict key "source": "kernel" |
| src/providers/base_provider_agent.py, src/persistence/logic/warmup_provider.py, services/bar_replay_provider.py | 1 each | docstrings; payload fields; dict key |
| scripts/ops/bars/ops_truncated_bar_scan.py | 1 | ohlcv_request source='ibkr' (_ENDS_SQL) |
| scripts/ops/bars/ops_source_policy.py | 1 | prose "source admission" |

Tests building rows with a source column (grep -rln market_data_ohlcv tests/unit tests/integration): test_market_data_ohlcv_tradeable_view.py converted (above); test_ic_measure.py inserts name no source column (unchanged); test_backfill_feature_factory.py source= is a provider payload label (unchanged); test_bar_write_no_first_write_wins.py and test_bar_selection.py carry no source-column inserts; the bar_derivation test suites already build (vendor, kind) rows. No hit in a module a resumed unit runs was found (no plan-13 miss).

Done-criterion checks: the widened sweep above leaves no canonical source read (no bare `SELECT source` or `source IN` against market_data_ohlcv); `select count(*) from information_schema.columns where table_name='market_data_ohlcv' and column_name='source'` prints 0; full unit suite green (7,852 tests, exit 0, 2 unrelated skips). repro_frozen not required: no edit under src/intelligence/research or statistics.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Dead subject] ops_masked_slot_baseline.py deleted instead of converted (D-191-15-A)**
- Found during: Task 1 sweep
- Issue: the script counts synthetic_fill rows in canonical; plan 185-12 deleted those rows and the post-swap table has no kind that could represent them, so every conversion would either error or hand-type a label with no vendor_kind mapping (which the plan forbids)
- Fix: deleted the script, its test, and its two allow-list entries (test_market_data_ohlcv_boundary.py, test_market_data_ohlcv_no_synthetic_fill.py); repo-wide grep found no other code references
- Commit: 5d22c325a

**2. [Plan staleness] ops_d1_bootstrap.py and tests/unit/scripts/test_d1_bootstrap.py no longer exist**
- Found during: Task 1 sweep
- Issue: the plan's files_modified lists them, but 191-11 (0add3a02d) deleted both with the other old-store scripts
- Fix: nothing to convert; disposition recorded here

**3. [Rule 1 - Bug] ohlcv_revision.old_source mixed conventions (D-191-15-B)**
- Found during: Task 1 (live-data check)
- Issue: post-swap revision rows carry the vendor/kind token (the raw writer's D2 convention), legacy rows carry labels; the original predicate would silently miss new rows
- Fix: IBKR_1D_REVISION_SOURCES = legacy labels + pair_token forms, both derived from vendor_kind
- Commit: 5d22c325a

**4. [Rule 2 - Missing coverage] test files beyond the plan's list updated/created**
- The plan listed four test files; test_ops_raw_backfill.py, test_ops_source_policy.py and test_truncated_bar_scan.py exist and assert the old SQL, and the exporter had no test. Updated all three, added test_ops_export_known_answer_fixtures.py, converted the integration fixture insert
- Commit: 51ff84d26, 5d22c325a

## Notes

- ops_raw_backfill still references ohlcv_observation: the table exists (to_regclass non-null; plan 191-11 replaced its first-bar use in ops_head_rerun, not the backfill's mapping), so no disposition beyond this note was needed.
- No new APR keys, no migrations, no research/statistics edits.

## Self-Check: PASSED

Commits 51ff84d26 and 5d22c325a exist on main; all key-files listed above exist on disk (verified via git show --stat of both commits); this SUMMARY is committed with the state updates.
