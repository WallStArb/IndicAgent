---
status: pending
priority: P1
filed: 2026-10-03
source: interactive session (185 Tradier decision)
---

# Reconcile Tradier and IBKR daily bars before D

## What

Tradier was the primary 1d source from 2026-10-03 (migration 438) until D = 2026-10-07 (migration 456;
the account is not funded and plan 185-48 deleted the loader). Its bars stay canonical before D, so which
vendor's closes are right still decides that history. Raw answers from both vendors sit in D1 beside each
other. Measured over 3.9M overlapping bars and 989 names: 6.5% of closes differ beyond tolerance
(18.6% in 2006 falling to 1.0% in 2026), the median IBKR/Tradier volume ratio is 0.80 (0.96 in 2006, 0.55 in
2026), and HON's Tradier closes sit a constant 0.33% above IBKR's in every year, before and after its spin-offs.
Which vendor's closes are right is open. The dividend-adjustment hypothesis is refuted (median ex-date close
difference 0 bp, a dividend-adjusted close would show about -49 bp).

## Work

1. Arbitrate the differing closes against what neither vendor owns: corporate-action dates, the known-corrupt
   prints D2a already uses, and the daily range implied by the stored 5m bars. Per-name and per-year result, the
   share each vendor wins.
2. Explain the 42 names whose closes differ on most bars (a whole-history scale offset like HON's).
3. The volume basis moved to todo 518 (the step at D for every name; volume is never rescaled).
4. Void (185-48, 2026-10-08): no Tradier token is needed; the account will not be funded and the loader,
   provider and Settings fields are deleted.

D7's vendor_agreement table holds the stored overlap (constant since the Tradier observations end at
2026-10-06); this todo decides what it means for the history before D.
