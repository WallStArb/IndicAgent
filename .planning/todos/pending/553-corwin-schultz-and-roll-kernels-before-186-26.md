---
status: pending
priority: P1
filed: 2026-10-27
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
