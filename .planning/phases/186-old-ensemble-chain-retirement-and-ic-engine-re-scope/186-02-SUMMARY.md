---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: 02
subsystem: research-records
tags: [summary-cards, verdict-ledger, legacy-verdict, old-chain-retirement, d05-d06]

requires:
  - phase: 186-01
    provides: card schema, card lint (tests/unit/test_summary_cards.py) and the 186-01 process cards to cross-link
provides:
  - 18 legacy_verdict cards, one per row of construction-verdict-ledger.md section 4
  - One pointer paragraph after the section 4 table listing the 18 card ids
affects: [186-16 (deletes scripts/analysis/, gates on card lint), 186-22 (drops the old chain tables), 187 (loads cards as legacy_verdict attempts)]

tech-stack:
  added: []
  patterns:
    - "Recipe pointer = last commit touching the script at or before the numbers' date, or the run commit the spec names when the script exists at it"

key-files:
  created:
    - docs/research/summary-cards/legacy-jump-diffusion-decomposition.md
    - docs/research/summary-cards/legacy-cointegrated-pairs-residual.md
    - docs/research/summary-cards/legacy-retail-immediacy-provision.md
    - docs/research/summary-cards/legacy-dealer-hedging-flow.md
    - docs/research/summary-cards/legacy-statistical-factor-residual.md
    - docs/research/summary-cards/legacy-todo303-per-symbol-trend-regime.md
    - docs/research/summary-cards/legacy-todo304-percentile-rank-regimes.md
    - docs/research/summary-cards/legacy-todo281-dominance-confirmation-axes.md
    - docs/research/summary-cards/legacy-n1-nonlinear-interaction-combiner.md
    - docs/research/summary-cards/legacy-range-pct-fast-xs-ls-h5.md
    - docs/research/summary-cards/legacy-phase148-alpha-score-directional.md
    - docs/research/summary-cards/legacy-bars-since-high-fast-xs-ls-h5.md
    - docs/research/summary-cards/legacy-alpha-score-residual-single-security-15m.md
    - docs/research/summary-cards/legacy-range-pct-fast-xs-ls-h5-single-name-only.md
    - docs/research/summary-cards/legacy-ha-extreme-volume-divergence.md
    - docs/research/summary-cards/legacy-hb-confirmed-reversal.md
    - docs/research/summary-cards/legacy-tsmom-sleeve.md
    - docs/research/summary-cards/legacy-phase179-sleeve-walk-forward.md
  modified:
    - docs/research/construction-verdict-ledger.md

key-decisions:
  - "Pointer paragraph instead of a card column in ledger section 4, so the 18 frozen rows stay byte-identical (diff of the extracted table before and after, and against main after the rebase, is empty)"
  - "forward_span_looks counts one per distinct run that read data at or after 2025-12-24 (ledger rows 1-9: 1, 2, 1, 2, 1, 1, 0, 1, 5); cards built on in-sample-only runs carry 0; row 11 is 0 because its two looks live on legacy-phase148-oos-gates; row 7 is 0 because the todo 303 card counts the shared run"
  - "Row 18 recipe_commit is the E14 rerun's main commit (5fa10430a), not the freeze commit the plan lists, because the recorded numbers come from the rerun; the freeze and frozen-run code commits are recorded as results entries"

patterns-established:
  - "A card whose verdict came from an unpushed or later-deleted script names the nearest committed script in recipe.script and says so in the prose"

requirements-completed: [D-05, D-06]

duration: about 1h20min
completed: 2026-09-29
---

# Phase 186 Plan 02: Ledger verdict cards Summary

**Eighteen lint-validated legacy_verdict cards, one per section 4 row of the construction verdict ledger, each pinning its recipe to a git commit and carrying numbers copied from the ledger, its docs or `concept_registry` (D-05), plus one pointer paragraph in the ledger (D-06).**

## Accomplishments

- 18 cards written in the 186-01 schema; five (`range_pct_fast_xs_ls_h5`, its single-name form, `alpha_score_residual_single_security_15m`, `tsmom_sleeve`, phase 179) carry `status_now: reopened` with a `reopened_as` pointer to ledger section 2.
- Phase 148 card cross-links `legacy-phase148-oos-gates`, `legacy-phase148-score-01-03` and `legacy-ensemble-champion`; phase 179 links `legacy-ensemble-champion` and `legacy-tsmom-sleeve`; the 10/14, 15/16, 6/7 and 17/18 pairs link each other.
- `tests/unit/test_summary_cards.py`: 41 passed, 0 skipped (git checks active) over the full 32-card set.
- Ledger section 4 rows unchanged; the only ledger edit is one paragraph (4 added lines) after the section 4 table.

## Cards

| card_id | verdict | status_now | recipe.script (scripts/analysis/) | recipe_commit | tables | forward_span_looks |
|---|---|---|---|---|---|---|
| legacy-jump-diffusion-decomposition | DEAD | closed | jump_diffusion_decomposition_spy_pilot.py | 803294354add0500e08238e7195fa1f04ec0c276 | feature_vectors, forward_returns, market_data_ohlcv_tradeable | 1 |
| legacy-cointegrated-pairs-residual | DEAD | closed | cointegrated_pairs_residual_same_sector_screen.py | 9843888f14a7f65250eb23caf1fab20b1004643f | market_data_ohlcv_tradeable, instruments, instrument_tags | 2 |
| legacy-retail-immediacy-provision | DEAD | closed | retail_immediacy_provision_levered_sleeve_pilot.py | 0a8a0a16a8962b7be7e3948289bf5558b3472a88 | market_data_ohlcv_tradeable | 1 |
| legacy-dealer-hedging-flow | DEAD | closed | dealer_hedging_flow_expiry_calendar_pilot.py | 0a8a0a16a8962b7be7e3948289bf5558b3472a88 | market_data_ohlcv_tradeable | 2 |
| legacy-statistical-factor-residual | DEAD | closed | statistical_factor_residual_stage3_ic_falsification.py | a026dc1f2d579605092beebb496c616bb104235f | market_data_ohlcv_tradeable, forward_returns, feature_ic_scores | 1 |
| legacy-todo303-per-symbol-trend-regime | DEAD | closed | per_symbol_regime_candidates_stage3_falsification.py | 1084a1d1152532adc1339e577f7fcb59a60c517a | feature_vectors, forward_returns, market_data_ohlcv_tradeable | 1 |
| legacy-todo304-percentile-rank-regimes | DEAD | closed | per_symbol_regime_candidates_stage3_falsification.py | 1084a1d1152532adc1339e577f7fcb59a60c517a | feature_vectors, forward_returns, market_data_ohlcv_tradeable | 0 |
| legacy-todo281-dominance-confirmation-axes | REJECTED_AS_AXIS | closed | hmm_candidate_regime_axes_identifiability_sweep.py | a9252f8efa3eac1d9eadc3a5c41e0e2b971138b9 | market_data_ohlcv_tradeable, instrument_tags, config_state | 1 |
| legacy-n1-nonlinear-interaction-combiner | INCONCLUSIVE | closed | nonlinear_interaction_combiner_n1_verdict.py | f0d363f901b1eba2594ca737131818bb175ed3dd | feature_vectors, forward_returns, instruments, concept_registry | 5 |
| legacy-range-pct-fast-xs-ls-h5 | DEAD | reopened | range_pct_fast_xs_ls_h5_falsification.py | 8f0bd464bb3e02e78b95e53d02520aba96f15fe4 | feature_vectors, forward_returns, concept_registry | 0 |
| legacy-phase148-alpha-score-directional | KILLED_ON_PAPER | closed | phase148_personal_hurdle_placement.py | c3ad8116c358c6df8e227489400018c418c27d4f | ensemble_alpha, forward_returns, alpha_frames, gate_evaluations, concept_registry | 0 |
| legacy-bars-since-high-fast-xs-ls-h5 | DEAD | closed | personal_edge_paper_screen.py | c3ad8116c358c6df8e227489400018c418c27d4f | feature_ic_scores, market_regimes, feature_vectors, forward_returns, concept_registry | 0 |
| legacy-alpha-score-residual-single-security-15m | FAIL | reopened | alpha_score_residual_single_security_15m.py | f8eceadf4c0108087ecd0138f9805c715096789f | alpha_events, forward_returns, instruments, concept_registry | 0 |
| legacy-range-pct-fast-xs-ls-h5-single-name-only | DEAD | reopened | range_pct_fast_beta_by_universe_composition.py | 9adf3f2d48d1ff6f3feb445bfa228122fe6594f8 | feature_vectors, forward_returns, instrument_tags, concept_registry | 0 |
| legacy-ha-extreme-volume-divergence | FAIL | closed | extreme_volume_divergence_track1.py | f461bdc549c0cdc901046aa46ae68648ec461d51 | feature_vectors, forward_returns | 0 |
| legacy-hb-confirmed-reversal | FAIL | closed | extreme_volume_divergence_track1.py | f461bdc549c0cdc901046aa46ae68648ec461d51 | feature_vectors, forward_returns | 0 |
| legacy-tsmom-sleeve | FAIL | reopened | sleeve_walk_forward/run.py | 0c33a2596e2906dab905f4d6ddc68f1e32827091 | market_data_ohlcv_tradeable, forward_returns, instruments, instrument_tags, feature_vectors, market_regimes, concept_registry | 0 |
| legacy-phase179-sleeve-walk-forward | FAIL | reopened | sleeve_walk_forward/run.py | 5fa10430a9a411189e04db57085edf5faf4be2b1 | feature_vectors, forward_returns, market_regimes, market_data_ohlcv_tradeable, instruments, instrument_tags, concept_registry, feature_ic_scores | 0 |

`recipe_commit` per card was resolved with `git log -1 --format=%H --before="<date> 23:59:59" -- <script>` unless the row says otherwise below; the command is recorded in each card's "Where the numbers came from".

## Read-only SQL (run 2026-09-29)

- `SELECT name, status, added_phase, created_at, metadata FROM concept_registry WHERE domain = 'construction' AND status = 'deprecated' ORDER BY created_at;` (rows 10 to 14; five deprecated construction rows returned, matching the plan). Its SQL and date are also in each of those five cards.
- `SELECT to_regclass(...)` for the table names used in `tables` (all existing).
- `SELECT timestamp::date FROM market_data_ohlcv_tradeable WHERE symbol='SPY' AND timeframe='1d' AND timestamp<='2026-08-12' ORDER BY timestamp DESC OFFSET 1999 LIMIT 1;` (returned 2018-08-22, the span start of the statistical factor residual card).
- `SELECT min(timestamp), max(timestamp) FROM market_data_ohlcv WHERE symbol='SPY' AND timeframe='1d'` (context only; not used in a card).

No INSERT, UPDATE, DELETE or DDL was run.

## Verification

- Section 4 table (`sed -n '/^## 4\./,/^## 5\./p' ... | grep '^|'`) before versus after: `diff` exit 0. After the rebase onto main (two research-lane ledger commits landed meanwhile) it is also identical to main's section 4.
- Each of the 18 card ids appears exactly once in the ledger.
- `tests/unit/test_summary_cards.py`: 41 passed, 0 skipped, on the worktree and again after the rebase.
- Full `pytest tests/unit/ -q` on the worktree before the rebase: exit 0 (3 pre-existing skips). Result on merged main: see the completion report (run after the merge).
- No em dash or Unicode minus in `docs/research/summary-cards/`.
- `/simplify` and `/review` were not run: the diff is docs only (cards and one ledger paragraph), so there is no code to review.

## Deviations from Plan

### Auto-fixed and judgment calls

**1. [Rule 1 - Bug] Plan count of 31 cards is 32**
- **Found during:** Task 2 and Task 3 acceptance checks
- **Issue:** the plan says 13 cards from 186-01 plus 18 gives 31, but 186-01 wrote 14 (8 legacy_verdict, 6 dead_cache), so the directory holds 32 cards.
- **Fix:** none needed; the lint covers all 32. Noted so downstream plans do not assert 31.

**2. [Rule 3 - Blocking] Retail immediacy recipe_commit could not follow the date rule**
- **Issue:** the pilot script was first committed 2026-08-08 09:21 -0400 (with the dealer hedging pilot), the day after the run, so `--before="2026-08-07 23:59:59"` returns nothing.
- **Fix:** used the only commit touching the path, 0a8a0a16a; explained in the card.

**3. [Rule 3 - Blocking] Two doc-named scripts differ from the plan's expected script**
- Rows 6 and 7: the doc names `per_symbol_regime_candidates_stage3_falsification.py` (one shared run for todos 303 and 304) as the verdict-producing script, not `per_symbol_trend_candidates_stage1_pilot.py`; used the doc's and put the Stage 1 and 2 scripts in `sources`. `forward_span_looks` counted on the todo 303 card only.
- Row 12: concept_registry metadata says no committed falsification script exists for the unconditional spread check (todo 374); `recipe.script` is `personal_edge_paper_screen.py`, the script that produced the 0.11 premise, and the card states this.

**4. [Judgment] Row 18 recipe_commit is the E14 rerun commit**
- The plan lists the freeze commit da0548a96; the recorded numbers come from the rerun at main `5fa10430a` (prereg 12.5), and `run.py` exists at it, so that is the pointer. The freeze commit and the frozen-run code commit (a64af3d1a) are `results` entries.

**5. [Judgment] Rows 15 and 16 recipe_commit is the run commit f461bdc54, a docs commit**
- The ledger names f461bdc54 as the run commit (the run log records `git_commit` f461bdc54...), and the script exists at it, so the plan's rule applies.

**6. [Judgment] Author line says Claude Sonnet 5.5**
- The plan text says `Author: Claude Opus 5.5`; the executing model was Sonnet 5.5, so the cards state that.

**7. [Process] Merge order**
- The three task commits were rebased in the worktree onto main (main gained two research-lane commits; no conflict), fast-forward merged, and the SUMMARY was committed on main directly with a pathspec rather than in the branch. Docs-only diff class.

## Known Stubs

None.

## Threat Flags

None. No network, auth, file-access or schema surface was added; only markdown records.

## Self-Check: PASSED (files exist, lint green with git checks active; commits recorded in the completion report)
