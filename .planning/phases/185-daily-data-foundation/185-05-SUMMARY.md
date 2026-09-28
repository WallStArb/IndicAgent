---
phase: 185-daily-data-foundation
plan: 05
subsystem: bars
tags: [d2a-scrub-rules, known-answers, corroboration-ceiling, apr, pure-functions]

# Dependency graph
requires: [185-04]
provides:
  - src/intelligence/bars/scrub_rules.py: BarFlag/ScrubParams/SymbolBars/ScrubResult, RULE_VERSION "scrub-v1", run_rules
  - the eight D2a rules as pure APR-parameterized functions (ohlc_invariant, non_positive_price, price_sanity, vol_scaled_jump, stale_print, volume_outlier, view_disagreement, plus return_magnitude/gap_before_next)
  - D-11 corroboration ceiling: count_corroborating + corroborated_verdict (downgrade only at max_ratio <= threshold.bar_scrub.corroboration_max_clearable_ratio)
  - ScrubParams.from_apr(mapping, tf) consuming the 16 migration-381/reused config_state keys
  - price_sanity candidates exposed in ScrubResult for plan 10's cross-symbol pass
affects: [185-10, 185-12, 185-17]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Rules as numpy-vectorized pure functions over SymbolBars arrays; only the stale-run scan and flagged-bar BarFlag construction loop, both over offenders"
    - "Known-answer gate: every dry-run and legacy confirmed_corrupt row pinned in tests/fixtures/bars before any rule touches research data"

key-files:
  created:
    - src/intelligence/bars/scrub_rules.py
    - tests/unit/bars/test_scrub_rules.py
    - tests/unit/bars/test_scrub_known_answers.py
    - tests/unit/bars/test_corroboration_ceiling.py
    - tests/unit/bars/test_flag_parity.py
    - tests/unit/bars/_builders.py
  modified:
    - tests/fixtures/bars/price_sanity_status_rows.csv
    - tests/fixtures/bars/README.md
    - scripts/ops/bars/ops_export_known_answer_fixtures.py
    - tools/check_plugin_invariants.sh

key-decisions:
  - "classify_candidate_bar imported unchanged from statistics/price_sanity.py and run as a batch rule with prev_close/next_open arguments (D-13); price_sanity.py byte-identical"
  - "FXY 2008-09-24 recorded as the one known disagreement: with live neighbors its max_ratio is 9.94 (under the 10.0 threshold) so the current rule says PLAUSIBLE; it stays quarantined via the legacy_price_sanity_status flag copied by migration 381, and the threshold was not weakened"
  - "view_disagreement is standalone (called by plans 12/17 with both price views), not part of run_rules: SymbolBars carries one view"
  - "vol_scaled_jump requires the sigma window full (n > jump_vol_window + 1), so short series and warmups are never judged"

patterns-established:
  - "Fixture three-bar windows built from real neighbor columns (prev_close/next_open), never synthetic guesses, so known-answer tests fail only on rule disagreement"

requirements-completed: [D-08, D-10, D-11, D-13, D-14]

# Metrics
duration: about 3.5 h (four TDD commits plus fixture ground-truthing)
completed: 2026-09-27
---

# Plan 185-05: D2a pure scrub rules summary

**All eight D2a rules plus the two D-14 ported flags live as pure APR-parameterized functions in src/intelligence/bars/scrub_rules.py, proven against the full known-answer set (45/27/1864 dry-run rows, 15 legacy rows, SPY/MRNA/ALMS fixtures) before plan 10 runs them over the corpus**

## Performance
- **Duration:** about 3.5 h (task 1 known answers + ceiling, task 2 remaining rules + parity, self-review pass)
- **Completed:** 2026-09-27
- **Tasks:** 2

## Known-answer results
- 45 dry-run CONFIRMED_CORRUPT 1d rows: all quarantined via price_sanity with matching implausible_fields; synthetic flat neighbors never flagged
- 1,864 AMBIGUOUS rows: zero quarantined, every one stays a recorded candidate
- 27 MARKET_EVENT rows: all stay CONFIRMED_CORRUPT under the D-11 ceiling (corroboration_max_clearable_ratio 2.5); downgrade still works at/below 2.5, blocked above
- 15 legacy confirmed_corrupt 1d rows: 14 re-confirmed by the rule, FXY 2008-09-24 pinned as the known disagreement (quarantined via legacy_price_sanity_status)
- SPY 2024 (252 bars), MRNA/ALMS seam windows: zero quarantine flags; synthetic 2:1 split with recorded corporate action raises no jump flag

## Acceptance verified
- `grep -nE "asyncpg|psycopg|ConfigService" src/intelligence/bars/scrub_rules.py` returns nothing; decimal-literal audit lists only the 1.4826 MAD constant; `git diff --quiet` on statistics/price_sanity.py
- 36 tests in tests/unit/bars/ green; full `.venv/bin/pytest tests/unit/ -q` green (2 pre-existing unrelated skips)
- All thresholds flow through ScrubParams.from_apr (seeded config_state values pinned by test, text-value coercion covered)

## Task commits
1. **Task 1 RED: known-answer + corroboration-ceiling tests** - `67ab944fe`
2. **Task 1 GREEN: price_sanity batch rule + corroboration ceiling** - `b8befb20a`
3. **Task 2 RED: remaining D2a behaviors + D-14 parity tests** - `b788251cc`
4. **Task 2 GREEN: remaining D2a rules + D-14 flag ports** - `6c668778b`
5. **Self-review cleanup: dead _flags helper dropped** - `849b473a1`

**Plan metadata:** this commit

## Deviations from plan
- Fixture ground-truthing: price_sanity_status_rows.csv gained prev_close/next_open columns (nearest traded bars over market_data_ohlcv_tradeable, via LATERAL subqueries added to scripts/ops/bars/ops_export_known_answer_fixtures.py; README updated). The plan's synthetic-neighbor fallback would have vacuously passed all 15 legacy rows; real neighbors make the known-answer test fail only on genuine rule disagreement
- FXY 2008-09-24 known disagreement recorded instead of forcing agreement (see key-decisions); system-level quarantine still holds through the legacy flag
- tools/check_plugin_invariants.sh: src/intelligence/bars/* added to the class-naming exclusion (same rationale as statistics//research/: pure Ring 1 data/computation types, not plugin code)
- tests/unit/bars/_builders.py extended beyond files_modified (test-support builders: seeded_apr, three_bar_window, load_dry_run_report)
- stale_print off-by-one rule bug found and fixed during GREEN (block_id was 1-based while starts/lengths are 0-based, flagging the wrong block); covered by the run-length behavioral test
- Test helper APR overrides initially passed bare field names (silently keeping seeded windows); call sites corrected to full config_state keys

## Issues encountered
- None beyond the above.

## User setup required
None.

## Next phase readiness
- Plan 10 consumes run_rules per symbol, collects price_sanity_candidates across symbols, then applies count_corroborating + corroborated_verdict before writing flags through bar_derivation_batch
- Plans 12/17 call view_disagreement directly with the ADJUSTED_LAST and TRADES close series plus the explained set
- No migration this plan (185-05 owns none; 380/381 already applied)

## Self-Check: PASSED
All six key files present on disk; all five task commits found in git log.

---
*Phase: 185-daily-data-foundation*
*Completed: 2026-09-27*
