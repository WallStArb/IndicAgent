---
status: closed
priority: P2
filed: 2026-11-13
source: IBKR code removal (commits 49e0b7284, 778a9f06c, 6b2ec7ffc), vulture diff against HEAD
---

# Dead code left by the IBKR removal, and who writes ohlcv_empty_history

## What

The deletion orphaned code vulture now flags (about 38 findings above the HEAD baseline):

- `scripts/infrastructure/backfill/_empty_history.py`: `reconcile_empty_history`, `apply_empty_range`,
  `load_first_bar`, `load_fresh_heads`, `load_reverify_days`, `load_tape_floors`, `record_head_per_tf`.
  This module is the registered sole writer of `ohlcv_empty_history`
  (`tests/unit/test_single_writer_registry.py`), and its only driver was the deleted fetcher, so
  today nothing writes the table. Decide: keep the table as a frozen record and drop the writer, or
  keep a writer for the Massive path. Readers: `bar_reconciliation_audit`, `bar_auditor`,
  `corpus_rerun_data_gate`, `rebuild_preconditions`, `gap_plan`.
- `scripts/infrastructure/backfill/_d1_gaps.py`: `detect_gaps_1d_from_d1`, `detect_gaps_from_record`,
  `with_overlap_window`.
- `src/intelligence/bars/vendor_kind.py`: `observation_kind`, `vendor_kind_to_label`;
  `derivation.py` `SOURCE_NAMED`, `SOURCE_VENUE`; `corporate_actions.infer_split`; `seams.find_seams`.
- `services/ohlcv_coverage_writer.reset_failures`, `services/ohlcv_raw_writer.read_stored_closes`,
  `src/config/instrument_onboarding` (keep `onboard_instrument`: the Stage 2 onboarding path, todo 609,
  needs it).

## Gate

After step 7 Part D passes, because the card and canaries still read the vendor-label logic.

## Done when

`vulture` shows no finding that the removal introduced, and the single-writer registry names a live
writer (or a recorded retirement) for `ohlcv_empty_history`.

## Closure 2026-11-13

Done in 59309a5b1, earlier than the gate named: none of the deleted code is evidence for step 7 (the
card, counts, witness and canaries read raw rows and the vendor-label logic, not these helpers).
Deleted: the three `_d1_gaps` detectors, the `_empty_history` writer set (the module now only reads),
`infer_split`, `find_seams`, `observation_kind`, `vendor_kind_to_label`, `SOURCE_NAMED` and
`SOURCE_VENUE`, `reset_failures`, `read_stored_closes`, three dead metrics, the `DataProvider` history
method, the IBKR conftest fixture, the coverage-SLA alert and the plugin-fallback panel.
Decisions: `ohlcv_empty_history` is a frozen record (registered with an empty writer tuple; its readers
stay); `ohlcv_provider_head` is dropped (migration 592, 3,060 IBKR head rows, no reader or writer);
`instrument_onboarding.onboard_instrument` stays for the Stage 2 path (todo 609);
`emit_integrity_fact_sync` and the v2.x `PLUGIN_*` metrics stay (tested, outside this removal).
