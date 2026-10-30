---
status: pending
priority: P1
filed: 2026-10-30
source: data lane, intraday audit recount (grid_parity fails 144 names in the 2026-10-30 full sweep)
---

# grid_parity fails names whose only difference is volume rounding

`integrity_checks.grid_parity` compares derived 15m and 1h buckets with IBKR's own archive exactly.
Measured on the IBKR era (before 2016-01-04) for ADP, AIG, AME and ABT: open, high, low and close
match on every shared bucket, and every volume difference is 1 or 2 shares, the archive being the
larger. The mismatch counts equal the audit's (AIG 23,278 of 23,278; ADP 32,131 vs 32,129; AME 506
vs 500). IBKR rounds fractional-share volume once per bucket; the derived value sums rounded 5m
bars, so a 15m bucket (three constituents) can differ by up to 2 shares and a 1h bucket by more.

AAP is a different case and stays a real failure: 3 price mismatches and 15 volume mismatches up
to 40,700 shares.

Owner 2026-10-30: a few shares of volume is not a concern; the bound is approved.

Rule (the audit's exactness stays for prices): prices stay exact;
volume passes when the archive minus derived lies in [0, constituents - 1]. Anything outside still
fails. Measure the 1h grid the same way before fixing the bound, and count how many of the 144
names clear under the rule and how many still fail for real. Substantive diff: simplify, review,
full unit suite.
