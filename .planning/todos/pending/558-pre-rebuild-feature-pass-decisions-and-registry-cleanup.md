---
status: pending
priority: P1
filed: 2026-10-28
source: owner question 2026-10-28 (new features, factors and signals; missing atomic features; cleanup)
---

# Decide the pre-rebuild stored-column additions and clean the feature registry

## Status (2026-11-01)

The owed Opus/Fable-class rigor pass landed 2026-11-01 (session indicagent-2c, review section in
the doc): the eight-row add-list stands, with five spec pin-downs (trailing-window z for
`market_residual_z`; SPY as the market series; the `days_to_ex_dividend` availability-time proof;
one pinned `residual_beta_stability` estimator; one declared window per column). The candidate
list is decided. The doc
(`docs/plans/2026-10-28-pre-rebuild-feature-additions-draft.md`, review section) carries the
add-list for the next rebuild pass (idiosyncratic_volatility, the market-residual trio,
residual_beta_stability, max_daily_return, max_drawdown, downside_deviation, size_proxy,
dividend_yield, days_to_ex_dividend; composites stay research-layer-first). Window policy
changed by the owner 2026-10-31: the window never closes; new columns ride the next pass.
Remaining work here is implementation (blocked until stage 2 finishes, kernels are in the
rebuild fingerprint), the rank_z registry retirement, and the measured redundancy_group fill
after the rebuild.

## What

Unreviewed Sonnet 5.5 draft; the cleanup items and candidate list are the assistant's proposals, not owner or lane decisions. Needs an Opus or Fable rigor pass before anyone relies on it. The rank_z finding rests on todo 421 and a kernel grep; the `ret_acf1_z` duplicate is an unmeasured inference.

`kernels/` is in the 186-26 rebuild's fingerprint (todo 555), so a stored column added after the
rebuild starts forces a follow-up rebuild. The draft pass
`docs/plans/2026-10-28-pre-rebuild-feature-additions-draft.md` lists the candidates (market residual
return and its OU half-life, residual beta stability, a size proxy, dividend yield and days to
ex-dividend, MAX, maximum drawdown, downside deviation, idiosyncratic volatility) and the cleanup.

1. Before 186-26 launches: the lane owners decide which candidates a first-batch family names as
   members (those ride the rebuild) and whether a fundamentals source comes before or after the
   first feature family.
2. With the rebuild: confirm the registry rows for `momentum_rank_z`, `volume_rank_z` and
   `volatility_rank_z` (stored, never computed, still active) retire with the old table.
3. After the rebuild: measure the `ret_acf1_z` against `ret_autocorr_1` correlation, then fill
   `redundancy_group` (empty for all 302 features) from measured correlations. Nothing is dropped
   on a duplicate finding alone.

## Done when

The candidate list is decided and recorded before 186-26 starts, the three rank_z registry rows are
retired, and `redundancy_group` is filled from measured correlations.
