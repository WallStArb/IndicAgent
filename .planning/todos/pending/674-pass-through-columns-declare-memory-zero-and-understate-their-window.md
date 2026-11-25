---
status: pending
priority: P1
filed: 2026-11-24
source: indicagent-fb, member check for todo 669 (lead ruling 2026-11-24: a silent wrong answer)
---

# 21 stored columns declare memory 0 although their windows are 21 to 311 bars

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

## End state

Every stored column declares its true window, or is refused as a member before any certificate is looked up: `effective_memory_bars(column)` is at least the trailing window its builder reads, and a test fails if a pass-through kernel can ever declare less than its builder.

## The 21 columns (checkable list)

Kernel, builder module, and where the window lives; the window is the stored APR config value and the registry's own `definition_warmup(column, config, "1d")` where one is declared (the first row the value can exist; the builder's seed-independence span is that plus its slack of 2).

| Pass-through kernel (`kernels/`) | Column | Window source (grid kernel and APR key) | `definition_warmup` 1d |
|---|---|---|---|
| `distribution_pass_through` (`distribution.py`) | `max_daily_return` | `distribution_daily` memory = max of `feature.max_daily_return.window` (21), `max_drawdown_window`, `downside_deviation_window` | 0 (none declared) |
| | `max_drawdown`, `downside_deviation` | same grid kernel | 0 (none declared) |
| `market_residual_pass_through` (`residual.py`) | `market_residual_return` | `market_residual_daily` memory = `factor_beta_window` + max(z 252, idiosyncratic 21, lag1_acf 63, beta stability) + 2 | 60 |
| | `idiosyncratic_volatility` | same | 80 |
| | `market_residual_z` | same | 311 |
| | `market_residual_lag1_acf` | same | 122 |
| | `residual_beta_stability` | same | 119 |
| `macro_pass_through` (`macro.py`) | `equity_beta_z`, `rate_beta_z` | `factor_beta_daily`: `factor_beta_window` 60 plus `factor_beta_zscore_window` 252 | 311 |
| | `vix_z`, `flight_quality`, `yield_slope_z`, `tip_tlt_ret_z`, `hyg_lqd_ret_z`, `sb_corr_fast`, `sb_corr_slow`, `sb_corr_z` | `cross_asset_daily` / `build_cross_asset_series`: `cross_asset_rv_window`, `vix_zscore_window`, `yield_curve_zscore_window`, `tip_tlt_zscore_window`, `hyg_lqd_zscore_window`, `sb_corr_window_fast/slow`, `sb_corr_zscore_window` | 0 (none declared) |
| `dividend_yield_pass_through` (`dividend.py`) | `dividend_yield` | the dividend kernel's memory `dividend_yield_window + 1` (line 160) | 0 (none declared) |
| `ctf_passthrough` (`cross_tf.py`) | `ctf_momentum`, `ctf_vwap_align` | `ctf_vwap_window` (cross-timeframe grid) | 0 (none declared) |

That is 3 + 5 + 10 + 1 + 2 = 21. The ten macro columns, the three distribution columns, the dividend column and the two cross-timeframe columns declare no `definition`, so even the first-row number is 0 there: the fix must read the builder's own window for them, not `definition_warmup`.

## Scope

1. Decide the declaration: (a) one int per kernel equal to the builder's memory expression. It edits only the five kernel modules, so only the units holding those columns re-key; it over-declares the short columns of a kernel (for example `vix_z` would carry the 313 of `equity_beta_z` and lose early rows it could have kept), which is measurable before choosing. (b) allow `memory` as an int or a per-output mapping, as `definition` and `memory_anchor` already are: exact, but `registry.py` is in every kernel's import closure, so it moves every kernel's key and with it the whole rebuild pin. Recommendation: (a), measure the extra masked rows on the 25 pilot names first, and take (b) only if that loss is material, because (b) re-keys the entire stored table for a 21-column defect.
2. Make the pass-through memory derive from the same expression as the grid kernel (one definition), not a second number.
3. Add the test below, and run `scripts/research/determinism/repro_frozen.py` only if a research or statistics file is touched (it should not be).

## Test (fails today)

`tests/unit/features/test_pass_through_memory.py`, for every kernel whose name ends in `_pass_through` or `passthrough` (found from `default_registry().kernels`, so a new one cannot escape): each pair of pass-through output and its grid kernel is listed in the test; the test asserts `effective_memory_bars(output) >= grid_memory_for(output)` and `>= definition_warmup(output)` under the default config and under a config with every window doubled; and a guard test fails when a pass-through kernel is not in the pair list. Must fail on 2026-11-24 main for all 21 columns.

## Landing constraint and which pins it touches

- It edits kernel modules (option a) and also `src/intelligence/features/contract/registry.py` (option b only) (`macro.py`, `residual.py`, `distribution.py`, `dividend.py`, `cross_tf.py`), all in the rebuild writer's import closure. `rebuild_code_key()` moves under either option (it hashes the registry's kernels and the writer closure); under (a) the unit key moves for the units holding these columns, under (b) for every unit. Print `rebuild_code_key()` before and after in a detached worktree off `origin/main`.
- Never while a run that imports them is live: the corpus pilot `f9f69166` is pinned at `09708ae249f2`, and an edit discards every completed cell (`code_content_key`). Land only when no corpus run is live.
- Pins it affects: the pin of any counted corpus test. The stage_1d feature rebuild writes the stored rows that a counted corpus run reads, under the key current at that time. Landing after `stage_1d` has written them re-keys the units of the 21 columns and forces their rebuild (the rows before the builder's slack rows change from a stored value to NaN: at most 2 rows per name per column for the rolling builders, measured before the rebuild). The cheapest sequence is therefore after the pilot passes and before `stage_1d` is launched; the lead rules the order.
- Stored values: a declared memory above the builder's NaN prefix masks the slack rows, so it can change a stored value in the first rows of each series. Quantify on the pilot rows before the rebuild (a read of the 25 pilot names, no corpus compute).

## Gates

Unit suite by exit code, ruff, black, `tools/check_glossary.py`, `/simplify`, an independent review of the worktree diff, the new test failing before and passing after, `rebuild_code_key()` before and after recorded in the closure note, and no edit while a corpus run is live. Doc: `docs/foundation/` kernel-registry text if it states the pass-through contract (the kernels' own comments say memory 0 by design; update them with the fix).

## Related

Todo 669 (the member check that found it; every certificate under 669 needs this first), todo 586 (the same size failure mode with persistence), `docs/plans/2026-11-24-family-order-after-1d-corpus.md` (H-B and market-residual families use these columns).
