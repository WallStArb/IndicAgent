---
phase: 191-unified-raw-bar-table
plan: 21
subsystem: bars
tags: [tradier-retirement, code-deletion, vendor-kind, sources]
requires: [191-20]
provides: [tradier-free sources/vendor_kind identifiers, 30-name digest baseline]
affects: [191-22, 191-23, 191-24, 191-25]
key-files:
  modified:
    - src/intelligence/bars/sources.py
    - src/intelligence/bars/vendor_kind.py
    - src/intelligence/bars/derivation.py
    - src/intelligence/bars/corporate_actions.py
    - src/intelligence/bars/daily_rule.py
metrics:
  completed: 2026-10-29
---

# Phase 191 Plan 21: Tradier identifiers out of the bars library

SOURCE_TRADIER, ROUTE_TRADIER and VENDOR_TRADIER are gone from sources.py and vendor_kind.py, with the tradier label, served-kind, canonical-kind and observation-kind entries; canonical 1d digests for 31 names are identical before and after.

## Digest baseline and comparison

Read-only probe (a scratch script, not committed) over 31 names: 10 with the most ibkr/fallback canonical rows, 9 IBKR-only (no Alpaca rows), 12 IBKR-then-Alpaca names with first bar before 2010. After plan 20 no canonical or raw row carries vendor tradier, so "Tradier-heavy" is represented by the long IBKR histories that plan 20 re-derived. Per name it records the stored canonical 1d `bar_content_digest` (all rows, non-quarantine flag rules, built as ops_tradier_residue does) and the pure d2-v4 harness digest (`read_daily_inputs` + `derive_daily_v2` over the full inputs). Files: `logs/tradier_code_delete_digest_before.json` and `..._after.json` (worktree logs, not committed). Result: 0 differences in both digests for all 31 names. The unit fixtures for the rule (tests/unit/bars, test_vendor_kind) passed before and after with unchanged expected outputs.

## Removed-symbol decisions

| Symbol | Decision |
|---|---|
| sources.SOURCE_TRADIER, ROUTE_TRADIER | deleted. daily_rule.py imported ROUTE_TRADIER: now a local constant there (import line plus one definition, no rule change, RULE_VERSION d2-v4 untouched). |
| vendor_kind.VENDOR_TRADIER | deleted. listing_venue_writer.py used it: local constant, plan 23 deletes the official-close read. |
| tradier label in LABEL_TO_VENDOR_KIND, VENDOR_SERVED_KINDS, _CANONICAL_KIND_FOR_RAW, observation_kind branch | deleted. test_ohlcv_raw_migration_contract compares the historical migration 472 mapping, so it adds the retired label explicitly. |
| BAR_VENDORS "tradier" and BAR_KINDS "consolidated" | kept as literals: CVR codes migration 472 seeded (test_ohlcv_raw_migration_contract pins them). |
| CANONICAL_1D_SOURCES and VOLUME_BASIS_BY_VENDOR_KIND ("tradier","consolidated") | KEPT as literals with a comment. Removing the canonical pair breaks about 14 daily-stage service tests whose fixtures are Tradier-primary scenarios (plan 23 owns them) and test_volume_basis, which requires every canonical pair to have a basis. Live data has zero such rows, so the entry is inert. Plan 23 removes both with the fixtures. |
| bar_reconciliation_audit.SOURCE_TRADIER | local literal (plan 23 deletes the agreement report). |
| ops_source_policy, ops_data_bar_check | one-line local fixes (plan 25 owns them): literal pair in ops_source_policy; `_stored_label` helper in ops_data_bar_check so the tradier-keyed known-answer status test keeps its meaning. |
| services/bar_derivation._read_1d_snapshot | still calls label_to_vendor_kind: a pre-cutover snapshot CSV with source "tradier" now raises KeyError on restore. Plan 23: decide whether old snapshots must stay restorable. Two restore tests now use ibkr_named labels. |
| bar_load VENDOR_SERVED_KINDS | tradier no longer has a served-kind gate; test_bar_load_no_drop uses alpaca with a bogus kind. |

## Deviations from plan

- [Rule 3] The plan said CANONICAL_1D_SOURCES drops the pair; kept it (see table). The done-grep therefore prints the three literal lines above (BAR_VENDORS, VOLUME_BASIS, CANONICAL_1D_SOURCES).
- [Rule 3] The edit leaves daily_rule.py with a one-line import change although the plan says it is not edited; sources.py can no longer export ROUTE_TRADIER and the rule module could not import otherwise.
- The /simplify and /code-review skills are not callable from this agent; the diff (66 lines changed excluding the summary) was reviewed by hand instead.

## Verification

Full tests/unit: all pass except 4 failures that also fail on a clean `git archive HEAD` copy (pre-existing, unrelated): test_bar_source_policy_retirement::test_quarantine_sessions_go_through_the_flag_writer, test_feature_vectors_v2_rows::test_column_count_and_order_match_the_migration, test_feature_vectors_v2_schema (2 tests, migration 526 parse).

## Self-check: PASSED
