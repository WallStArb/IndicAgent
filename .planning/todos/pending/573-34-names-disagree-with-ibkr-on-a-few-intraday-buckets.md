---
status: pending
priority: P2
filed: 2026-10-31
source: post-fix audit 2026-10-31 (grid_parity fails 34 names after the volume slack)
---

# 34 names disagree with the IBKR archive on a few derived 15m and 1h buckets

Prices are exact in grid_parity, so each mismatched bucket is a real vendor disagreement between the
Alpaca-derived bar and the IBKR archive: 486 of 15,430,155 buckets at 15m, 158 of 3,770,896 at 1h, at most
0.1% of one name's buckets (DBC 73 of 75,634; GE 52 of 61,414). Names: DBC, CTVA (held for its rescale), DBA,
GE, CWB, ETHA, DBB, EDV, ITA, ALGN, ASYS, BIIB, AMD, EZU, INDA, EQIX, HD, HON, IYT, BKE, ISRG, KWEB, MTUM, QUAL,
ATRO, FXE, LIN, ASTE, CAL, BELFA, BH, ACTG, SHY, XLC.

They stay out of the intraday feature build (186-26 stage 2 excludes them). To release a name: list its
mismatched stamps, decide per stamp which vendor is wrong (the odd print, a stale last-trade, a corporate
action stamp), and record the classification; then the next audit passes it or the name joins a later stage.
