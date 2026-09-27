---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: 01
subsystem: research-records
tags: [summary-cards, yaml-lint, ci-guard, old-chain-retirement, d06-drop-gate]

# Dependency graph
requires:
  - phase: 183-research-layer (frozen verdicts, ledger)
    provides: verdict wording conventions the card verdict enum covers
  - phase: planning (186-RESEARCH, 186-CONTEXT)
    provides: D-04/D-05/D-06 requirements, table facts, gate evidence pointers
provides:
  - Checked-in card schema under docs/research/summary-cards/ (README)
  - tests/unit/test_summary_cards.py: strict-YAML card lint plus DROP_TABLES drop-coverage gate (D-06)
  - 8 legacy_verdict cards for the old ensemble chain's processes
  - 6 dead_cache cards covering all remaining drop targets
affects: [186-02 (ledger verdict cards), 186-11/186-22/186-27 and all drop plans (gate on this lint), 186-19 (deletes the spread tracker with its spec preserved in a card), 187 (loads cards as legacy_verdict attempts)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Strict YAML loader (YAML 1.2 booleans only) copied from spec.py so `reproducible: no` cannot pass"
    - "Doc-record lint analog of test_todo_priorities_link_integrity.py: one assert-not-set per rule, lru_cached scans"
    - "Git-history checks that skip with a stated reason on shallow clones"

key-files:
  created:
    - docs/research/summary-cards/README.md
    - tests/unit/test_summary_cards.py
    - docs/research/summary-cards/legacy-phase142a-ensemble-ic.md
    - docs/research/summary-cards/legacy-phase142b-frames-frame04.md
    - docs/research/summary-cards/legacy-phase148-score-01-03.md
    - docs/research/summary-cards/legacy-phase148-oos-gates.md
    - docs/research/summary-cards/legacy-gate166-frame-recalibration.md
    - docs/research/summary-cards/legacy-ctf-momentum-decile-ls.md
    - docs/research/summary-cards/legacy-em-cal-emission-threshold.md
    - docs/research/summary-cards/legacy-ensemble-champion.md
    - docs/research/summary-cards/cache-context-features.md
    - docs/research/summary-cards/cache-feature-ic-scores-history.md
    - docs/research/summary-cards/cache-ctx-tables.md
    - docs/research/summary-cards/cache-forward-returns.md
    - docs/research/summary-cards/cache-feature-vectors-v1.md
    - docs/research/summary-cards/cache-feature-ic-scores-v1.md
  modified: []

key-decisions:
  - "Verdicts: 142A and 142B are DEAD (built, verified, never run against real rows); phase 148 gates FAIL per gate2_execution; SCORE-01/02/03 INCONCLUSIVE (its signal gate passed, its execution gate failed, and the kill-on-paper verdict belongs to the ledger card 186-02 writes); EM-CAL INCONCLUSIVE per the review's own framing (never run under falsifiable conditions); ctf decile LS and the ensemble champion FAIL"
  - "gate2_execution's identity as the unnamed 2026-07-23 look is established via the gate_evaluations row; its gate_look_log line has no gate_id key, so the card cites gate_look_log:2026-07-23T00:26:31.223260Z"
  - "The full ctf_momentum decile spec (feature, decile_fraction, leg mechanics, cost hurdles, null control, attribution bound) is preserved in prose in legacy-ctf-momentum-decile-ls.md so 186-19 can delete the tracker"
  - "Sizes for hypertables copied from the 186 planning records (parent-relation size queries do not include chunks); row counts re-verified live 2026-09-27"

patterns-established:
  - "Summary card format: strict front matter, copied-only numbers, db: sources with SQL and run date in prose"
  - "DROP_TABLES coverage gate: any future drop target must be added to the test constant and get a card before dropping"

requirements-completed: [D-04, D-05, D-06]

# Metrics
duration: 35min
completed: 2026-09-27
---

# Phase 186 Plan 01: Summary cards, card lint and drop-table coverage Summary

**Card schema plus a CI lint that gates every phase 186 table drop (D-06), and 14 cards: 8 legacy_verdict records of the old ensemble chain's processes and 6 dead_cache records, with all DROP_TABLES covered and numbers copied from stored rows, reports and gate looks only (D-04, D-05).**

## Performance

- **Duration:** 35 min
- **Started:** 2026-09-27T22:46:54Z
- **Completed:** 2026-09-27T23:21:50Z
- **Tasks:** 3
- **Files modified:** 16 created

## Accomplishments

- Card schema README (front matter table, source-reference grammar, append-only and no-rescore rules) under `docs/research/summary-cards/`
- `tests/unit/test_summary_cards.py`: 41 tests, strict YAML loading (rejects `reproducible: no`), source-ref resolution against `.planning/gate_look_log.jsonl`, git existence checks for recipe pointers (skip with stated reason on shallow clones), and full 14-table DROP_TABLES coverage
- Eight legacy_verdict cards (142A ensemble IC, 142B frames/FRAME-04, 148 SCORE-01/02/03, 148 OOS gates, gate166 recalibration, ctf_momentum decile LS, EM-CAL emission threshold, the run_2025122405150000 ensemble champion) with every number copied, never recomputed
- Six dead_cache cards (context_features, feature_ic_scores_history, ctx_events + ctx_snapshots, forward_returns, feature_vectors v1, feature_ic_scores v1) with live row counts re-read 2026-09-27

## Card list with tables and coverage

| Card | Kind / verdict | tables |
|---|---|---|
| legacy-phase142a-ensemble-ic | legacy_verdict / DEAD | alpha_ensemble_ic |
| legacy-phase142b-frames-frame04 | legacy_verdict / DEAD | alpha_frames |
| legacy-phase148-score-01-03 | legacy_verdict / INCONCLUSIVE | alpha_strategy_scores, alpha_frames |
| legacy-phase148-oos-gates | legacy_verdict / FAIL | ensemble_alpha, forward_returns, alpha_frames |
| legacy-gate166-frame-recalibration | legacy_verdict / FAIL | alpha_frames |
| legacy-ctf-momentum-decile-ls | legacy_verdict / FAIL | construction_spreads |
| legacy-em-cal-emission-threshold | legacy_verdict / INCONCLUSIVE | ensemble_alpha, forward_returns, alpha_events |
| legacy-ensemble-champion | legacy_verdict / FAIL | ensemble_weights, ensemble_alpha, alpha_events |
| cache-context-features | dead_cache / NO_CONCLUSION | context_features |
| cache-feature-ic-scores-history | dead_cache / NO_CONCLUSION | feature_ic_scores_history |
| cache-ctx-tables | dead_cache / NO_CONCLUSION | ctx_events, ctx_snapshots |
| cache-forward-returns | dead_cache / NO_CONCLUSION | forward_returns |
| cache-feature-vectors-v1 | dead_cache / NO_CONCLUSION | feature_vectors |
| cache-feature-ic-scores-v1 | dead_cache / NO_CONCLUSION | feature_ic_scores |

Coverage result: `_uncovered_tables` returns the empty set over all 14 cards; the lint runs 41 passed, 0 skipped, 0 failed.

## Read-only SQL run (all on 2026-09-27)

- `SELECT count(*) FROM alpha_ensemble_ic / alpha_frames / alpha_strategy_scores / ensemble_weights / ensemble_alpha / alpha_events / construction_spreads / context_features / feature_ic_scores_history / ctx_events / ctx_snapshots / forward_returns / feature_vectors / feature_ic_scores` (card row counts)
- `SELECT gate_id, result, run_ts, evidence FROM gate_evaluations ORDER BY run_ts` (gate evidence for cards 4-6)
- gate1_signal cell aggregate: `count(cell), passes_fdr, walk_forward_stable` over `jsonb_array_elements(evidence->'cells')` (640 | 238 | 241)
- ensemble_weights cells/features/versions: distinct (symbol, tf, regime, weight_version) = 33, distinct feature_name = 101
- alpha_strategy_scores per-row dump ordered by run_ts (SPY/5m/high_bear block quoted in card 3)
- feature_ic_scores: `SELECT DISTINCT training_window_end` (single value 2025-12-24 05:15:00+00) and `GROUP BY regime_scope, is_pooled` (scope split quoted in the card, matching the planning record exactly)

## Task Commits

Each task was committed atomically on branch `gsd/186-01-summary-cards`, rebased onto main after the 185 session advanced it, then fast-forward merged:

1. **Task 1: Worktree, card schema README and the card-lint test** - `7aeead70a` (test; TDD RED: fixture tests green, real-card tests red)
2. **Task 2: Eight old-chain process cards (legacy_verdict)** - `fed6ed148` (docs)
3. **Task 3: Six dead-cache cards, full coverage green, merge** - `42fb59427` (docs)

**Plan metadata:** see the SUMMARY commit and `docs(186): check off plan 01 in ROADMAP`.

## Files Created/Modified

- `docs/research/summary-cards/README.md` - card schema, allowed values, source-reference grammar, drop-gate contract
- `tests/unit/test_summary_cards.py` - card lint and D-06 drop-table coverage check (41 tests)
- `docs/research/summary-cards/legacy-*.md` (8 files) - old-chain process verdict cards
- `docs/research/summary-cards/cache-*.md` (6 files) - dead-cache cards

## Decisions Made

See key-decisions. Verdict assignments are the only judgment calls the plan left open; each is grounded in the card's own sources.

## Deviations from Plan

None - plan executed exactly as written. (Main moved during execution due to the concurrent 185 session; the plan's own merge protocol covers this via rebase-and-rerun-lint, so it is not a deviation. Schema detail was explicitly delegated to executor discretion in the task text.)

## Issues Encountered

- YAML plain scalars containing ": " (titles like "Dead cache: forward_returns", known_defects items with colons) parsed as mappings and failed the lint; fixed by quoting those values.
- `pg_total_relation_size` on hypertable parents excludes chunks, so recorded sizes come from the 186 planning records while row counts were re-verified live; noted per card in "Where the numbers came from".

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Ready for 186-02: the 18 ledger verdict cards, plus the reverse `related_cards` links from its side (this plan left card 4's `related_cards` empty for it, per the plan).
- All drop plans (186-11, 186-22, 186-27, 186-28 and others) can gate on `pytest tests/unit/test_summary_cards.py -q` being green; any new drop target must be added to `DROP_TABLES` with a card first.
- CI note: the git-history checks skip on CI's shallow checkout by design (T-186-01-06 accepted); drop plans run the lint locally in a full checkout.

## Self-Check: PASSED

- All 16 created files exist on disk in the merged tree (verified with `[ -f ]` before writing this section).
- Commits `7aeead70a`, `fed6ed148`, `42fb59427` exist on main and were pushed to `origin/main` (`4c2f8510e..42fb59427`).
- Final verification rerun in the merged tree: `pytest tests/unit/test_summary_cards.py -rs` = 41 passed, 0 skipped; `pytest tests/unit -q` exit 0; 14 cards + README present; `git diff --stat main...branch -- src services production scripts` empty before merge.

---
*Phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope*
*Completed: 2026-09-27*
