---
status: closed
priority: P1
filed: 2026-10-27
closed: 2026-10-27
source: indicagent-24 and indicagent-5b, phase 184 kernel placement discussion (184-REVIEWS row 10); routed to indicagent-3a, owner of the 186-26 launch
---

# Land Corwin-Schultz and Roll spread kernels before 186-26 launches; close todo 390 in the same change

## What

Two OHLCV microstructure proxies have no stored implementation today:

- Corwin-Schultz high-low spread estimator (two-day high/low ranges).
- Roll implied spread (serial covariance of price changes).

Amihud illiquidity already exists as `illiq` in `src/intelligence/features/kernels/volume.py`, but
its divisor is unguarded against a zero-price bar (todo 390).

## Recommendation

1. Add Corwin-Schultz and Roll as stored kernels in `src/intelligence/features/kernels/` before
   186-26 launches, with declared memory and the registry contract, so they are computed once with
   provenance and research reads them through 184's S0 feature path. They must not go in
   `src/intelligence/features/research_kernels/`: a research kernel is allowed only when no stored
   column computes the concept, and only on the way to promotion (184-REVIEWS row 10).
2. Close todo 390's `illiq` divide-by-zero in the same change, so Amihud enters the rebuild clean.

## Why now

`kernels/` is in the 186-26 rebuild's fingerprinted import closure. 186-26 waits on 191-20 to 23
(realistically 2026-10-28 at the earliest), which leaves a window to land these first. After the
launch, adding them means a follow-up rebuild, which costs far more than two columns now. The
sequencing call belongs with whoever launches 186-26 (indicagent-3a).

## Out of scope

Cross-sectional rank z kernels (momentum, volatility, volume rank) are not stored features. A
cross-sectional rank is a transform over stored per-symbol columns at a decision time, so it
belongs in research S0/S2 as a declared panel transform, never in the per-symbol kernel contract.
Candidate for a phase 184 follow-up S0 transform.

## Depends on

Todo 390. Must land before the 186-26 launch, or wait for a follow-up rebuild.

## Sequencing decision (indicagent-3a, 186-26 launch owner, 2026-10-27)

Land before 186-26 launches. Conditions:

1. Todo 553 and todo 390's `illiq` divide-by-zero fix land in one reviewed change before
   191-23's summary, which is 3a's launch trigger; 3a checks `git log -- src/intelligence/features/kernels/`
   against this todo's status before starting the rebuild.
2. The kernels read only tradeable bars and are pure (CLAUDE.md research invariants). On 1d they see
   the D-191-Q vendor seam at 2016 (Alpaca consolidated after, IBKR before); the kernel spec states
   how each behaves across it.
3. Tell indicagent-3a when it is merged.

Owner of the change: indicagent-24 (phase 184 lane).

## Resolution

Landed 2026-10-27 together with todo 390, before the 186-26 launch.

- `src/intelligence/features/kernels/liquidity.py` (origin `liquidity`): `high_low_spread`
  (Corwin-Schultz, overnight-adjusted two-bar estimates, negatives set to 0 per the paper,
  mean over `feature.high_low_spread.window` = 21 pairs; declared memory = window) and
  `roll_spread` (Roll, `2 sqrt(-cov)` of consecutive log close changes over
  `feature.roll_spread.window` = 252 pairs, NaN when the covariance is >= 0; declared memory =
  window + 1). Both proportional spreads, NaN rather than filled, neither path dependent.
- Migration 526 seeds the two APR keys and adds both columns to `feature_vectors_v2` (applied
  live; the table had 0 rows). The two outputs are `V2_ONLY_COLUMNS` in the registry: the legacy
  FeatureVector and the old `feature_vectors` table do not carry them.
- Vendor seam (condition 2): neither kernel branches on the vendor; a window spanning the
  2016-01-04 seam computes normally and the module docstring discloses it. Both estimators read
  only price ratios, so a constant level difference cancels within an era; the IBKR over Alpaca
  ln(high / low) ratio on raw 1d (16 names, 2016-2017, 7,678 sessions) has median 1.000 and p05
  to p95 0.992 to 1.013. A level step left at the seam by an unresolved D-191-Q hold (HON: IBKR
  97.38 on 2015-12-31, Alpaca 195.57 on 2016-01-04) is a data defect every cross-bar column
  sees, not handled in the kernels.
- Tests: `tests/unit/intelligence/test_liquidity_kernels.py` (hand values, NaN contract,
  causality probe and memory check, the zero-close Amihud case).
- Found on the way, filed as todo 555: `amihud_illiq_z` is 0 on almost every stored row (the
  z-score's absolute std floor is above the raw Amihud scale).
