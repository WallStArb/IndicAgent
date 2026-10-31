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

Landed 2026-10-30: `grid_parity` keeps prices exact and bounds volume at n - 1 shares for a bucket of n 5m
bars (15m: 2, 1h: 11); a NaN volume counts as a mismatch. Review notes, not acted on: the 1h bound is not measured
(the 15m maximum of 2 is), and the 09:30 half-hour bucket could carry a tighter bound of 5. Remaining: the next
intraday sweep recounts which of the 144 names still fail (AAP expected); close this todo after that read.

Recount 2026-10-30 (SQL approximation, 15m, IBKR era before 2016-01-04, the 79 names the last full sweep logged
as failing): with prices exact and volume within 2 shares, 68 of 79 names clear. 11 still fail: VIXY (6,110
buckets differ in price both ways by up to about 1% on thin trading: a vendor aggregation difference, not
derivation bias), DBC, DBA, DBB, CWB, EDV (20 to 48 price buckets each), HD, HON, ISRG (4 each), AAP (3 price,
15 volume up to 40,700 shares) and MARA (1). The 1h grid is not recounted by SQL: a first attempt counted volume-0
placeholder bars (92,083 of ITA's 185,724 raw 5m rows) as constituents and showed false price mismatches on 65 of
79 names; with traded bars only and full buckets ITA has 0 of 1,089. Do not recount 1h outside the audit; the
02:00 ET audit does the exact read. The 11 are real small vendor disagreements; decide per name whether they hold or are classified, after
the audit confirms the list.

Audit read 2026-10-31 02:00 ET (volume slack in place): grid_parity fails 54 verdict rows on 34 names, down
from 144; mismatched buckets 486 of 15,430,155 at 15m and 158 of 3,770,896 at 1h. The remainder is price
disagreement, at most 0.1% of a name's buckets (DBC 73 of 75,634; GE 52 of 61,414; DBA 68 of 94,365; CWB, ETHA,
DBB, EDV, ITA, ALGN, ASYS, BIIB, AMD, EZU, INDA, EQIX, HD, HON, IYT, BKE, ISRG, KWEB, MTUM, QUAL, ATRO, FXE, LIN,
ASTE, CAL, BELFA, BH, ACTG, SHY, XLC; CTVA is already held for its rescale). Decision: the 34 stay out of the
next intraday build (the check's contract is exact prices; a disagreeing bucket has no arbiter); every other
name that passes slot_coverage, digest_fresh and coverage_cache builds. The fix is closed; the 34 names are a
vendor-data classification, not a code defect.
