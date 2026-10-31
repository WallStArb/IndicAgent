# Pre-rebuild feature additions

**Status:** Decided at PM level 2026-10-31 (review pass below); owner retains veto. Supersedes the draft-only framing: the owner reopened the window 2026-10-31 ("the window never closes; solid ideas land prior to a corpus rerun"), so candidate columns target the next rebuild pass after 186-26 stage 2, not a closed window.
**Mapped by:** Claude (Sonnet 5.5), interactive session, 2026-10-28, from the owner's question "do we need new features, factors or signals". Read-only: no kernel was read or run; names come from the stored column list and the planning docs.
**Reviewed by:** Claude (Opus 5.5), session indicagent-9f, 2026-10-31. Verdicts and the add-list are in the review section; the draft tables below are kept verbatim as the mapping record.
**Why now:** `kernels/` is in the 186-26 rebuild's fingerprint (todo 555), so a stored column added after the rebuild starts rides the next rebuild pass. Per the owner (2026-10-31) that is acceptable and expected for solid candidates; stage 2 running since 2026-10-31 means implementation lands in the next pass window, while the review and registry preparation happen now.

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

## Review pass (Opus, 2026-10-31)

Kept: the stored-column rule (single-name, own bars plus fixed macro inputs, named consumer or
queued family) and the composite-through-combiner stance. Both are correct discipline and the
owner's reopened window does not weaken them; it changes only the cost line, since a follow-up
rebuild pass is now an accepted vehicle rather than a forbidden one.

Corrections to the draft's state column: the spread kernels (todo 553) and the Amihud fix
(todos 555/560/563) landed before 186-26 started (final at 107f9a395), so the two "land before
186-26" rows are done. The 186-26 stage 1 rebuild ran 2026-10-29 and stage 2 (5m/15m/1h) is
running now; `hma_slope_z` and the constant columns are todo 564's batch, not this doc's.

### Add-list for the next rebuild pass (decided, registry rows enter as `candidate`)

Each is a single-name function of own bars (or own bars plus a fixed macro series already
stored by the `equity_beta_z` pattern), with a cross-sectional prior strong enough to name a
consumer in the first feature-family batch (phase 184). Implementation order follows the
kernel-sibling rule: where a stored kernel already computes the ingredients, the new column is
its sibling, not a new recipe class.

| Column | Consumer rationale | Notes |
|---|---|---|
| `idiosyncratic_volatility` (residual std of daily returns vs the fixed market series, rolling) | Ang et al. idio-vol premium; first feature family names it | Sibling of `equity_beta_z`: same regression, residual std instead of slope |
| `market_residual_return` + `market_residual_z` + `market_residual_lag1_acf` | Stat arb spread family (ledger section 2, todo 559 prereg) | Market-only residual stored by design; sector residual stays in S1 (point-in-time classification) |
| `residual_beta_stability` (rolling change in market beta) | Factor-drift risk measured, not assumed; guards the residual families | Cheap sibling of the beta kernel |
| `max_daily_return` (MAX effect, declared window) | Lottery-demand discount, Bali et al.; strong cross-sectional prior | One window only; more windows is overfitting before evidence |
| `max_drawdown` (rolling window) | Drawdown is a distinct risk state from volatility; regime segmentation input | Declared memory like every other rolling column |
| `downside_deviation` (rolling, target = 0) | Downside semivol asymmetry; complements `vol_asymmetry_z` | NaN below warmup, never zero |
| `size_proxy` (rolling mean log dollar volume) | Size factor for the residual model without shares outstanding | Distinct from `dollar_vol_z` (a z-score); store the level's log, not a rank |
| `dividend_yield` + `days_to_ex_dividend` | Corporate-action event family; data exists in `dividend_events_reconciled` | Outside `dividend_event_coverage` the value is unknown: NaN, never zero (the dividends rule) |

### Research-layer first, no stored column (confirmed)

OU half-life and equilibrium sigma of the residual, residual reversal interactions (volume
shock, illiquidity, regime): composites tested through the research kernels and the S7
combiner, promoted to storage only after a family verdict earns it (the 550-552 pattern).
Rolling PCA/cointegration: layer rules already exclude them (and the pairs verdict is DEAD).
Fundamentals, short interest, borrow: blocked on a data source (todo 438 covers borrow
forward-only); sourcing fundamentals is a separate admission decision (the Databento basis
study pattern applies), not a rebuild matter.

### Cleanup confirmed

Retire the three never-computed `rank_z` registry rows with the next pass. Fill
`redundancy_group` from measured correlations on the rebuilt table (after stage 2 completes),
not from construction intuition. Measure `ret_acf1_z` vs `ret_autocorr_1` correlation before
any dedup judgment; the rule is never to drop data that could carry signal.

### Open items (owner, non-blocking)

1. Fundamentals source admission: defer until the first feature family runs; a source decision
   needs the same measured-basis treatment as the Databento study.
2. The first feature family's prereg names which add-list members it consumes; that naming is
   the consumer test, and any add-list column no family names stays `candidate` (still built in
   the pass, per the owner's standing directive, but never `active` until consumed).

