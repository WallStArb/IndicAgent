---
status: pending
priority: P1
filed: 2026-11-24
source: indicagent-fb, member check for todo 669 (lead ruling 2026-11-24: a silent wrong answer)
---

# A pass-through member's reach is read as 0: 11 stored columns reach back 21 to 311 bars, 10 are path dependent

## What

`KernelRegistry.effective_memory_bars` (`src/intelligence/features/contract/registry.py:419`) is the one definition of a column's memory: the producing kernel's own `memory(config)` plus the largest effective memory of the kernels that produce its inputs. The five `*_pass_through` kernels read their values from external inputs (`ext_*`, a builder's grid), so they have no upstream kernel, and each declares `memory=lambda config: 0` ("the path dependence belongs to the builder and its grid kernel; warmup is the builder's own NaN-until-full discipline"). The builder's real window therefore never reaches the declared memory. Verified from the code on 2026-11-24, `effective_memory_bars` under the stored APR config:

```
max_daily_return: kernel=distribution_pass_through effective_memory_bars=0 path_dependent=False
idiosyncratic_volatility: kernel=market_residual_pass_through effective_memory_bars=0 path_dependent=False
equity_beta_z: kernel=macro_pass_through effective_memory_bars=0 path_dependent=False
market_residual_z: kernel=market_residual_pass_through effective_memory_bars=0 path_dependent=False
market_residual_lag1_acf: kernel=market_residual_pass_through effective_memory_bars=0 path_dependent=False
apr windows: {'max_daily_return_window': 21, 'idiosyncratic_volatility_window': 21, 'market_residual_z_window': 252, 'market_residual_lag1_acf_window': 63, 'factor_beta_zscore_window': 252}
```

Why it is a silent wrong answer, not a missing feature: the runner takes a feature member's source memory from this number (`runner._member_memory` -> `feature_inputs.column_memory_bars` -> `feature_memory_bars`). It feeds (1) the certificate bound `source_memory_bars_max` (`null_battery_persistent.admit` accepts 0 under any bound), (2) the member's warmup mask (`feature_inputs.warmup_mask` masks nothing at 0), and (3) the E17 memory `L` of the run (`_member_memories`, `book_memory`, `e17_memory`), which sets the HAC lag and the bootstrap block. An understated `L` for a persistent member makes the test statistic's size too large, the same failure mode as todo 586, and no gate refuses it. It is unreachable today only because no stored 1d feature route is certified (todo 669); every route built under 669 would inherit it, and the first counted corpus families (H-B low risk, market-residual reversion) are made of exactly these columns.

## Premise, as corrected 2026-11-24

Memory 0 is right for the rebuild and stays (D-26: `test_every_externally_fed_kernel_declares_memory_in_the_consuming_tf`): the writer feeds the external builders the full source history, so a stored value does not depend on where the row grid starts, and `column_warmup_bars` masks nothing. The defect is that the research member path reads the same number as the member's reach (`feature_memory_bars`), where a pass-through reaches back over its builder's window. An earlier build that raised the declared memory (`wip/674-pass-through-memory-option-c`, local, not landed) failed the suite: the reviewed path-dependent allow list, the causality probe statuses, 20 production-path golden digests, a macro alignment probe row, and the D-26 test, and it would have masked rows the builders already fill correctly.

## End state

A member's reach is the larger of the kernel's memory and the first row its value can exist (`definition_warmup`), so a certificate bound, a warmup mask and the E17 memory L see the builder window, with no change to any stored value, golden or probe status; and a pass-through of a path-dependent builder (cross-asset `flight_quality` and the date-level z-scores that share its builder, ctf Wilder RSI) is refused as a member.

## The 21 columns (checkable list)

| Pass-through kernel (`kernels/`) | Column | Builder window (first row of the value) | Declared before | R1 |
|---|---|---|---|---|
| `distribution_pass_through` | `max_daily_return` | `max_daily_return_window` returns (21) | none | definition |
| | `max_drawdown`, `downside_deviation` | `max_drawdown_window - 1` closes, `downside_deviation_window` returns (251, 252) | none | definition |
| `market_residual_pass_through` | `market_residual_return`, `idiosyncratic_volatility`, `market_residual_z`, `market_residual_lag1_acf`, `residual_beta_stability` | beta window plus the statistic's window minus 1 (60, 80, 311, 122, 119) | declared | reach reads it |
| `macro_pass_through` | `equity_beta_z`, `rate_beta_z` | beta window plus z window minus 1 (311) | declared | reach reads it |
| `dividend_yield_pass_through` | `dividend_yield` | `dividend_yield_window - 1` (251) | none | definition |
| `macro_pass_through` | `vix_z`, `flight_quality`, `yield_slope_z`, `tip_tlt_ret_z`, `hyg_lqd_ret_z`, `sb_corr_fast`, `sb_corr_slow`, `sb_corr_z` | date-level record whose first row is where its input series begin (data, not code); the kernel documents definition 0; `flight_quality` anchors to the first close | 0 by design | refused as members (R2) |
| `ctf_passthrough` | `ctf_momentum`, `ctf_vwap_align` | Wilder RSI from the series start; the VWAP window is in HTF bars | 0 | refused as members (R2) |

Eleven columns get a reach (R1); ten are refused (R2). The eight cross-asset columns are symbol-independent date functions (one value per date for every name), so they carry no cross-sectional information as members in any case.

## Scope: two commits, split by what each touches (lead ruling 2026-11-24)

R1 (rebuild closure; lands with the corpus re-pin before `stage_1d`, with todo 583): declare the first-row `definition` for `max_daily_return`, `max_drawdown`, `downside_deviation` and `dividend_yield`; add the optional `tf` argument and the `max(memory, definition_warmup)` reach to `feature_memory_bars` in `registry.py`; add the declared `Kernel.builder_path_dependent` marker (output to reason, validated, no behaviour change) on the ten pass-through outputs whose builder grid kernel is path dependent (the eight cross-asset columns from `cross_asset_daily`, the two ctf columns from `ctf_source`), with a test that the marker set equals the reviewed list and that a pass-through is marked exactly when its builder is path dependent (lead ruling 2026-11-24: no hard-coded column list in `feature_inputs`). Test `tests/unit/intelligence/test_feature_memory_reach.py`: the 11 columns reach their builder window with memory 0 kept, no other non-path-dependent column's reach differs from its memory, the full unit suite with no golden or probe-status change. `rebuild_code_key()` moves (registry and two kernel modules).

Review note for R2: the definitions are in daily bars and ignore `tf` (like the existing macro and residual ones), and these columns are broadcast to the intraday tfs, so a 5m-source member would read 251 as 251 five-minute bars (about 3 sessions) instead of about 19,600. Lead ruling 2026-11-24: R2 refuses daily-defined pass-throughs (the eleven with a reach) as members whose source tf is not 1d, rather than scaling; the 1d scope of the corpus is unaffected. R1 already changes the research warmup mask and E17 L for the 11 columns through `feature_inputs`, though no file under `research/` or `statistics/` is edited; `repro_frozen` runs with the R1 re-pin once the lead frees the slot.

R2 (research; held with 669, never beside a live counted run; needs `repro_frozen`): pass the source tf from `feature_inputs.column_memory_bars` to `feature_memory_bars`; refuse the marked pass-throughs in `column_memory_bars` by reading the marker (not by a path-dependent flag, which would change `macro_products`' mask and first stored row); `tests/unit/intelligence/test_pass_through_memory.py` asserting reach at least the builder window and the refusal, with a guard that fails on a pass-through column not listed.

## Landing constraint and pins

R1 edits `registry.py` and two kernel modules, all in the rebuild writer's import closure, so `rebuild_code_key()` moves: never while a run that imports them is live (the pilot `f9f69166` is pinned at `09708ae249f2`), and it rides the corpus re-pin before `stage_1d` with todo 583. R2 never beside a live counted run.

## Gates

Unit suite by exit code, ruff, black, `tools/check_glossary.py`, `/simplify`, an independent review of the worktree diff, `rebuild_code_key()` before and after in the closure note, and for R2 `repro_frozen`.

## Related

Todo 669 (the member check that found it; every certificate under 669 needs this first), todo 586, `docs/plans/2026-11-24-family-order-after-1d-corpus.md`.

## Hand-off 2026-11-25 (indicagent-8a, for the lead)

Both parts are built and held; nothing is pushed. They land in one re-pin on `wip/repin-integration` (order 652, R1, R2, 670/671, gate); the superseded option (a) branch is archived as tag `archive/674-option-c-2026-11`.

- R1: `258deab73` on `wip/674-r1-reach-and-definitions`. A pass-through member's reach is `max(memory, definition_warmup)`; first-row definitions for four columns; pass-through memory stays 0. It edits kernel modules in the rebuild writer's closure, so it moves `rebuild_code_key()` from 09708ae249f2 to 212a76c35332 and rides the single corpus re-pin before stage_1d, together with the todo 652 kernel declarations.
- R2: `4d520ebb5` on `wip/674-r2-member-refusal`, stacked on R1. It edits `src/intelligence/research/`, so it needs `repro_frozen` bit-identical and does not land beside a live counted run; sequence it after the counted runs.
- R1 does not change `vix_reversion_product` or `vix_z` (reach unchanged on the synthetic config; `vix_z` has no definition). The R5 finding in the 652 triage stays open for the vix clock.
- Before any push: `tests/unit` at `-n 4` and `git log origin/main..HEAD` listing only the intended commits.
