# Pre-rebuild feature additions: a draft pass

**Status:** Draft for the build (186) and research (184, 187) lane owners, 2026-10-28. Nothing here is decided or built. Unreviewed Sonnet 5.5 draft; the cleanup items and candidate list are the assistant's proposals, not owner or lane decisions. Needs an Opus or Fable rigor pass before anyone relies on it.
**Mapped by:** Claude (Sonnet 5.5), interactive session, from the owner's question "do we need new features, factors or signals". Read-only: no kernel was read or run; names come from the stored column list and the planning docs.
**Why now:** `kernels/` is in the 186-26 rebuild's fingerprint (todo 555), so a stored column added or changed after the rebuild starts forces a follow-up rebuild. The window closes when 191-21, 22 and 23 land and 186-26 starts.

## Method

Compared the ledger (`docs/research/construction-verdict-ledger.md`), the open todos (550 to 556), the idea docs and the stat arb map (`docs/ideas/signal-equity-stat-arb-method-map.md`) against the 322 columns of `feature_vectors` and the three research kernels (`research_kernels/rolling.py`: rolling percentile, rolling max distance, rolling VWAP deviation). The stored table is stale since 2026-08-10 (todo 411), so presence here means the column exists, not that its coverage is good; the rebuild recomputes every column.

## Rule proposed for what becomes a stored column

A stored column is a single-name function of that name's own bars and fixed macro inputs, needed by a queued family. Anything cross-sectional, residualized or sector-relative stays in the research layer (S0 kernels, S1 target), which is why the `rank_z` trio was dropped in 186-24 and why residual momentum is a research construction. A column added without a family waiting for it is not a look, but it adds nothing until a family tests it, so the window is spent only on columns with a named consumer.

## Findings

| Candidate | State | Proposal |
|---|---|---|
| Ledger pending members (`up_vol_ratio_fast`, `ofi_z`, `obv_z`, `mfi_slow`) | Stored | No work |
| Corwin-Schultz and Roll spread estimators (todo 553) | Kernels landed; stored columns arrive with the rebuild | Keep before 186-26; they feed the cost model (todo 437) |
| `amihud_illiq_z` | Stored but zero on almost every row (todo 555) | Fix before 186-26 (3a recorded the sequencing decision) |
| Rolling percentile, max distance, VWAP deviation | Research kernels only (todos 550 to 552, gated on 186-27) | Leave; promote after the rebuild as planned |
| Long-lookback 12-1 month momentum and residual momentum | Research layer by design (family 11, S1 residual returns) | No stored column |
| PCA or sector-ETF residual reversion, ML on residuals (stat arb map) | Research layer | No stored column |
| Idiosyncratic volatility (residual vol against the market) | Not stored; `equity_beta_z` shows the macro-input pattern exists | Candidate: one single-name kernel on a fixed macro series; needs a family that consumes it |
| MAX (largest daily return in a window), maximum drawdown, downside deviation | Not stored (`vol_asymmetry_z`, `dist_from_high_*` are partial) | Candidate: cheap single-name kernels; the same consumer test applies |
| Daily realized variance from 5m bars | Not stored; no active family reads 5m (todo 445) | Defer; revisit when a 5m family is queued |
| Jump measures | Not stored; `jump_diffusion_decomposition` is DEAD (2026-08-07) | Skip |
| Fundamentals (size, value, quality, earnings surprise) | Not stored; only `earnings_season_flag` and `days_since_quarter_end` | Blocked on a data source; not a rebuild matter |
| Short interest, borrow | Not stored; todo 438 is forward-only capture | Blocked on data |
| Sector-relative and cross-sectional ranks | Not stored by design; the stored `momentum_rank_z`, `volume_rank_z`, `volatility_rank_z` are removed by the rebuild (todo 421) | Research layer |
| Regime inputs for style spreads (todo 548) | S7 has no regime slot | Separate build, not a rebuild matter |

## Recommendation

Land the spread kernels and the Amihud fix before 186-26, as already planned. Add idiosyncratic volatility, MAX, maximum drawdown and downside deviation to the rebuild only if a family in the first feature batch names them as members; otherwise they enter later through the research kernels (184-02's `kernel_source`) at no rebuild cost and join the stored registry after 186-27 (todos 550 to 552 are the pattern). Everything else is research-layer or blocked on data.

## Candidates the stat arb ideas imply

Added 2026-10-28 after the owner's follow-up. The same consumer test applies to each.

| Candidate | Kind | State | Note |
|---|---|---|---|
| Residual return against the market (return minus beta times the market series), its z-score and lag-1 autocorrelation | Atomic, single-name on a fixed macro series | Not stored; `equity_beta_z` shows the pattern | Market-only residual can be stored; the sector residual needs point-in-time classification, so it stays in S1 |
| Rolling OU half-life and equilibrium sigma of a residual (`ln 2 / kappa`, `sigma_eq`) | Composite over the residual above | Not stored | Defines the stat arb z-score `(X - m) / sigma_eq`; test in the research layer first |
| Residual beta stability (rolling change in beta) | Atomic | Not stored | The slides' "factor-model drift" risk, measured instead of assumed |
| Size proxy (rolling mean log dollar volume) | Atomic | Not stored (`dollar_vol_z` is a z-score) | Gives a size factor for a residual model without shares outstanding |
| Dividend yield and days to ex-dividend | Atomic, event | Not stored; data exists in `dividend_events_reconciled` | Ledger row "corporate-action event family"; needs outside-coverage handling (unknown, never zero) |
| Residual reversal conditioned on a volume shock, on illiquidity or on regime | Composite interaction | Nine stored `*_product` columns exist | Test through the S7 combiner, not as new stored products |
| Rolling PCA factor loadings and eigenvalue spectrum | Cross-sectional | Not stored | Research layer by design |
| Rolling cointegration statistics | Pair-level | Not stored | Pairs verdict is DEAD, closed for good; no work |

Composite features are better tested through the combiner than hard-coded: the stored `*_product`
columns are the pattern the registry already carries, and its `nonlinear_interaction_combiner` result
is inconclusive, so adding more of them buys nothing until that is settled.

## Cleanup found

- **Dead columns:** `momentum_rank_z`, `volume_rank_z` and `volatility_rank_z` are stored and registered
  active, but no kernel computes them (never computed, todo 421). The rebuild replaces the table;
  confirm the registry rows retire with it, since the registry still lists them as active features.
- **Possible duplicate:** `ret_acf1_z` and `ret_autocorr_1` both measure lag-1 return autocorrelation
  (one z-scored). Check their correlation on the rebuilt table before judging; the rule is never to
  drop data that could carry signal, so this is a measurement, not a deletion.
- **No redundancy handling:** the registry's `redundancy_group` is empty for all 302 features. Many
  stored columns are near-duplicates by construction (three range-based volatility estimators and
  their velocities, fast and slow pairs). Filling the groups is the registry's mechanism for this.
- **Correct as they are:** the five `canary_*` columns are controls, and `new_high_flag` and
  `new_low_flag` are deprecated tombstones.

## Open decisions for the lane owners

1. Does the first feature family name any of the candidate columns above? If yes, they ride the rebuild.
2. Is a fundamentals source worth sourcing before the first feature family, or after it?
3. Fill `redundancy_group` after the rebuild, from measured correlations?
