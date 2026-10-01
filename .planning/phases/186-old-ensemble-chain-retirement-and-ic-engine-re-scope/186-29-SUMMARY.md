---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: 29
subsystem: research-code-retirement
tags: [deletion, sleeve-config, determinism, import-switch]
requires: [186-03, 186-16]
provides: [scripts/analysis removed entirely; research tests import the promoted HarnessConfig]
affects: []
key-files:
  deleted: [scripts/analysis/sleeve_walk_forward/__init__.py, scripts/analysis/sleeve_walk_forward/config.py, tests/unit/sleeve_walk_forward/__init__.py, tests/unit/sleeve_walk_forward/test_config.py]
  modified: [tests/unit/research/test_evaluate.py, tests/unit/research/test_evaluate_session_scoring.py, tests/unit/research/test_evaluate_intraday.py, tests/unit/research/test_portfolio.py, tests/unit/research/test_portfolio_r1.py, tools/vulture_whitelist.py, .planning/todos/pending/448-research-lane-dependencies-for-phases-186-187.md]
requirements-completed: [D-03, D-11, D-02]
completed: 2026-10-01
---

# Phase 186 Plan 29: sleeve directory removal Summary

The last files under `scripts/analysis/` are deleted and the five research tests import `HarnessConfig` from `scripts.research.determinism.config`. The promoted determinism tool reports all three frozen books bit-identical on the post-deletion tree (exit 0).

## Commits

- f418b9fd1 refactor(186-29): switch research tests to the promoted HarnessConfig and delete the sleeve directory (D-03, D-11)

Pre-delete sha: 4f886b47919b0dc07c41d2da3c3d894db256feb9 (ancestor of main). Removed 4 files, 112 lines (config.py 60, test_config.py 52, two empty `__init__.py`).

## Gate results

1. 186-16 landed: `git ls-files` printed exactly the four survivor paths; `repro_frozen.py` exists.
2. Lane release: STATE.md row "Research (phase 183)" reads "Released by the owner 2026-10-01 for the one-line `HarnessConfig` import switch in the five research tests (186-29); otherwise the phase 183 session owns `src/intelligence/research/` and nobody else edits it" (commit 409d35d34, ancestor of main).
3. OR clause: the grep still hit the five tests, so release was the operative condition.
4. No process running from `scripts/analysis`.

## D-08 inventory (pre-edit, code)

- Switch (5): the five research tests' import lines.
- Keep by design: `repro_frozen.py:47` remap string; `tests/unit/research_tools/test_repro_frozen.py:15`; `test_determinism_modules.py:18`; provenance docstrings in `scripts/research/determinism/{signals,snapshot_io,sessions,results}.py`.
- Deleted with the directory: `tests/unit/sleeve_walk_forward/test_config.py`.
- Tooling: `tools/vulture_whitelist.py:1017` (the `sleeve` entry, see deviations). `tools/glossary_baseline.json` had no sleeve_walk_forward key.
- CLAUDE.md: no `sleeve_walk_forward` or `scripts/analysis` mention; the bit-identity rule already names the promoted tool (186-16 or later repointed it). Left alone.
- Docs: nine dated plan, research and card docs mention it as history (D-13, unchanged). Todo 448 is the only pending todo hit (provenance only; note appended).
- No `archive/` copy.

## Verification

- Determinism repro (`python -m scripts.research.determinism.repro_frozen`, from the worktree): exit 0, three bit-identical lines (phase 179 S3, phase 181 S2, phase 181 S3). Log in the session scratchpad.
- Full `pytest tests/unit`: 7862 passed, 5 skipped. Skips include `test_determinism_modules.py:77` "sleeve config removed" (by design).
- `pytest tests/unit -q --co` clean; research, research_tools, scripts subsets pass; `test_summary_cards.py` passes.
- `check_glossary.py --all` exit 0; black clean; pre-commit 9 checks passed.
- `git diff --name-status <pre-delete sha> -- src services scripts/research docs` is empty.

## Deviations from Plan

1. [Rule 1 - accuracy] The vulture whitelist entry for `sleeve` cites both the deleted config and the kept determinism copy, and the kept copy still needs the whitelist. I repointed the comment to the kept path instead of deleting the line.
2. CLAUDE.md edit not needed (already correct).
3. Pre-existing, not caused here and not touched: bare `vulture` exits 3 with the same 59 findings on main and on the branch (the plan's "vulture exits 0" criterion does not hold on main); `ruff check .` run from the worktree reports two I001 import-order findings in untouched files (`tests/unit/research_tools/test_repro_frozen.py`, `tests/unit/scripts/test_bar_campaign_preflight.py`), a worktree first-party detection effect, and the pre-commit ruff check passes on the commit.
4. The acceptance grep `scripts\.analysis` still prints three `pytest.importorskip("scripts.analysis.personal_cost_hurdle...")` lines in `tests/unit/scripts/test_research_cost_hurdle.py`. They are not importers (the tests skip, as they already did after 186-16), the file is outside files_modified, so it is left for a later plan.

## Self-Check: PASSED
