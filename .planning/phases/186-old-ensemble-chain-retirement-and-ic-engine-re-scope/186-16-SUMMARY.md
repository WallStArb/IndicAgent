---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: 16
subsystem: research-code-retirement
tags: [deletion, scripts-analysis, apr-retirement, vulture, determinism]
requires: [186-01, 186-02, 186-03, 186-04]
provides: [scripts/analysis deleted except the HarnessConfig closure, migration 412]
affects: [186-19, 186-23, 186-29]
key-files:
  deleted: [scripts/analysis/ (94 files), 26 test files]
  created: [production/migrations/412_retire_analysis_only_apr_keys.sql]
  modified: [tools/vulture_whitelist.py, tools/glossary_baseline.json, CLAUDE.md, src/intelligence/features/kernels/_hmm.py, services/regime_writer.py]
decisions:
  - "Merge to main held: the card lint fails on one card (see Blocked)."
metrics:
  completed: 2026-09-30
status: blocked-before-merge
---

# Phase 186 Plan 16: scripts/analysis deletion Summary

The directory is deleted on branch `phase-186-16-analysis-deletion` (worktree `/home/bg/dev/indicagent-186-16`), but the branch is NOT merged to main. The plan's own stop condition tripped after the deletion.

## Blocked

186-16 blocked: card legacy-alpha-score-residual-single-security-15m cites scripts/analysis/alpha_score_residual_bucketed_retest_15m.py not present at its recipe_commit.

`tests/unit/test_summary_cards.py::test_repo_source_paths_exist_at_recipe_commit_or_head` fails on the post-deletion tree; it is the only failing test in the full unit run. The card's `recipe_commit` is f8eceadf4 (2026-09-03); the cited script was added by 8841bc219 (2026-09-11) and existed only at HEAD, so once deleted it resolves nowhere. The plan says the fix belongs to that card's plan (186-02), not here. Card front matter was not touched. Options for the coordinator (a card edit, not a code change): point the card's `recipe_commit` at a commit that contains the script (8841bc219 or the pre-delete sha), or drop that line from the card's `sources`. Either is a one-line edit in `docs/research/summary-cards/legacy-alpha-score-residual-single-security-15m.md`; after it, `pytest tests/unit/test_summary_cards.py -q -rs` passes and the branch fast-forwards to main.

## Commits (branch, on main 920f8e2b3)

- e2cc0299d refactor(186-16): delete scripts/analysis except the sleeve config closure (D-12)
- 800264349 refactor(186-16): delete the regime kernel helpers only the deleted analysis pilots called (186-13 extra scope)
- 8d8d9b048 chore(186-16): migration 412 retires APR keys read only by deleted analysis scripts
- 97ba0d092 docs(186-16): correct the docs that named deleted analysis scripts as current

Pre-delete sha: 920f8e2b36b305f8c46069d8a91d326e6b1244db (ancestor of main, confirmed).

## Gate results (Task 1)

1. 186-01/02 summaries exist; card lint passed with git checks active before deletion (no skip).
2. 186-03 summary records the three bit-identical lines; `scripts/research/determinism/repro_frozen.py` exists.
3. 186-04 landed: audit, date_panel, cost_hurdle, feature_matrix exist; `grep -c scripts.analysis` is 0 for the promote script and test_compute_ready_predicate_apr.
4. No process running a `scripts/analysis` script.
5. Lane imports are only the five `HarnessConfig` lines (tests/unit/research/test_evaluate*.py, test_portfolio*.py).
6. `config.py` imports only `__future__` and `dataclasses`; keep set is `sleeve_walk_forward/__init__.py` and `config.py`.

D-08 inventory: 96 tracked files, 26,843 lines before (94 deleted, 2 kept); no crontab, systemd, production/systemd or Grafana mention; pending todos 423 and 448 cite it as provenance only (248 and 445 no longer mention it). 65 docs mention the path (dated records, unchanged except the three below). No archive copy exists (D-13).

## Deleted set versus the plan

120 files deleted: 94 under scripts/analysis and 26 tests (8 tests/unit, 5 tests/unit/scripts, 11 tests/unit/sleeve_walk_forward, tests/live/test_sleeve_walk_forward_snapshot.py and tests/live/__init__.py, matching the list in the plan). `git diff --name-status 920f8e2b3 HEAD | grep -c '^D'` is 120; no file deleted that is not in the plan. The deletion commit's non-D files are exactly test_config.py, vulture_whitelist.py, glossary_baseline.json. `git diff --shortstat` of the deletion commit: 123 files, 27 insertions, 32,092 deletions.

## repro_frozen before and after

Same command both times, `python -m scripts.research.determinism.repro_frozen <scratch>` (the promoted tool, `--logs /home/bg/dev/indicagent/logs` on the after run; default resolves to the same directory), before on the pre-deletion worktree, after on the post-deletion tree with `sleeve_walk_forward/evaluate.py` gone. Both, exit 0:

```
phase 179 S3: bit-identical [ 0.21612308 -0.14601638 -0.10558864]
phase 181 S2 (signal from Panel): bit-identical
phase 181 S3: bit-identical [0.19424572]
```

The "not recorded in frozen artifact, skipped" lines are identical in both runs. logs/phase179/rerun_e14 and logs/phase181 are read only by the tool. tests/fixtures (regime kernel golden, kernel_parity) are unmodified (`git diff --name-only tests/fixtures` empty).

## Guard-test allow-list edits

- tools/vulture_whitelist.py: 11 stale lines naming deleted paths removed; 24 entries added (each reasoned, owner named): config dataclass fields (sleeve, training_start, embargo_sessions, n_tested, min_positive_sub_periods), frozen Snapshot fields (all_1d, sleeve_features, sleeve_has_row, equity_labels), n_bar_ts, date_panel methods (family_stat, bootstrap_ci, sync_shift_null_p), MATERIALITY_GATE_NAMES, is_materiality_eligible (ITR predicate, keep), chain.py `options`, six portfolio/weighting.py functions, two ic_math.py functions. Vulture delta against the pre-deletion baseline is 0.
- tools/glossary_baseline.json: 5 stale keys removed by hand (3 scripts/analysis, 2 sleeve test files); check_glossary exits 0.
- tests/unit/test_market_data_ohlcv_boundary.py: no allow-list entry named a deleted script (no change).

## 186-13 extra scope

Deleted `_walk_forward_hmm_labels`, `_hmm_seed_stability_check`, `_state_groups`, the numpy `_alpha_pass` and the `_causal_decode` alias from `kernels/_hmm.py`, and five re-exports from `services/regime_writer.py`. The numpy filter moved into `tests/unit/_hmm_decode_helpers.py` as the `_causal_decode` causality oracle (test_hmm_jit keeps its own `_alpha_pass_ref`). Tests of the deleted functions removed (state_groups order, seed stability x2, labels-vs-full equality); the two walk-forward tests that used the label-only function (future-data causality, segment-seed continuity) were rewritten onto `_walk_forward_hmm_full`. Docstrings naming deleted names were corrected. Repo-wide grep of src, services, scripts, tests, tools for each deleted name (monkeypatch strings included) finds only the unrelated `test_causal_decode_*` test names. `_hmm.py` is edited: it is in ic_engine's import closure if ic_engine loads it, so the code key moves; no ic_engine corpus run was live (`ps` empty).

## APR retirement

Candidates: 67 keys appear in scripts/analysis at the pre-delete sha. Only `alpha.regime_stratification.max_correlation` and `alpha.validation.regime_gate_min_clusters` have zero literal and zero f-string readers on the post-deletion tree. Migration 412 applied (count 0 in config_state and config_schema) and committed in 8d8d9b048. Also zero-reader but owned elsewhere: `alpha.scoring.max_drawdown_ratio` and `alpha.scoring.min_sharpe` (186-21). `alpha.equity_regime.*` keys are read through `params.get` in regime_signals/breadth_vol.py (kept).

## Docs and other

CLAUDE.md lines 38 and 176 repointed to `python -m scripts.research.determinism.repro_frozen` (186-04 had not). Corrected: instrument-tag-registry.md, alpha-research-architecture.md, apr-calibration-backlog.md (row removed, note added), summary-cards/README.md ("Deleted recipe code" paragraph), todo 448 progress line.

## Tests

- Full `pytest tests/unit/ -q --ignore=tests/unit/scripts/test_venue_study_script.py` on the branch tree (worktree): one failure, the card-lint test above; everything else passes. Before the 186-13 extra-scope and migration commits, the same run on the deletion commit passed, exit 0 (with `-x`). Not yet run on merged main (not merged).
- New skips: two `test_research_cost_hurdle.py` importorskip comparisons (by design).
- ruff: two I001 findings (tests/unit/research_tools/test_repro_frozen.py, tests/unit/scripts/test_bar_campaign_preflight.py) are pre-existing: they reproduce in a worktree at 920f8e2b3 before any change. black clean; glossary clean. vulture exits 3 on main itself before this plan (67 findings in 186-04/183/185 code); this plan adds none.

## Deviations

- Plan said "push" and "remove worktree" at the end; held per the coordinator (no push) and per the block (no merge).
- Migration number is 412 (411 was highest at last check); the 186-17 worktree is behind main and could also choose 412; check before it lands.
- CLAUDE.md repointed beyond the plan's single-line mention (two lines still named the deleted tool).

## Adjacent findings (not fixed)

- vulture fails on main independent of this plan (cost_hurdle.py constants, feature_factory, bars/measure modules, etc.); whoever owns phases 183/185/186-04 needs to whitelist or use them.
- The two ruff I001 findings above appear only in linked worktrees (first-party detection); harmless on main except test_repro_frozen.py, which also fails in the main checkout.

## Self-Check

Files and commits verified by git log on the branch; the deleted-file count (120) and the non-D list were compared with the plan. Manual review pass only: /simplify and /review cannot be invoked from an executor.
