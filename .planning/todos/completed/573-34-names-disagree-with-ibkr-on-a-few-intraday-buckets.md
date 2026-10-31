---
status: completed
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

## Classification complete (data lane, 2026-10-31): the archive is the outlier in all 644 stamps

All 34 names reproduced with the audit's own rebucket + grid_parity (486 15m + 158 1h, per-name
counts match the audit log). Detail: `logs/todo573_grid_parity_classification.md`,
`logs/todo573_buckets.tsv` (644 records), generator `logs/todo573_generator.py`. Three classes,
zero canonical-5m defects:

1. **Restatement skew, 18 names** (ALGN ASYS ATRO ACTG ASTE BKE BIIB BELFA EQIX EZU IYT ITA AMD
   LIN BH CAL FXE GE): whole recent days where the archive 15m/1h was served once (2026-10-01/02)
   and the day's 5m was re-served later (verified `archive_older`); penny-level on one print or
   1-3% volume. GE's two days are uniform 4-7 bp price-only offsets, volume exact.
2. **Archive coarse-bar truncation, 14 names** (DBC DBA CWB DBB EDV INDA KWEB MTUM QUAL HD HON
   ISRG SHY XLC): one fixed clock slot per name where the archive bar misses trades its neighbors
   reconcile exactly (DBC 18:00 UTC holds 800 vs 37,300); 210 of 644 stamps pre-2016; dates recur
   across names, a systemic IBKR archive artifact.
3. **Wrong-basis archive rows, 2 names** (ETHA 2024-08-14 price/3 volume x3; CTVA three days on a
   5.57x-divided scale contradicting IBKR's own D1): split back-adjustment stuck in the archive;
   canonical and Alpaca's own 1d agree. ETHA/CTVA stay held (CTVA already held, todo 516).

Recommended release: wave 1 (18 restatement-skew names) now; wave 2 (14 truncation names) with
the stamp list recorded as dated exceptions; wave 3 (ETHA, CTVA) after their wrong-basis archive
rows are re-fetched into the revision log. The wave-1/2 mechanism is todo 524's deferred D7 rule:
a dated tolerance keyed on the archive row's `served_at` being older than the day's 5m `served_at`
(or a one-time archive re-fetch of the listed stamps), which rides with the rebuild lane. The
released names enter the feature build as their own stage-2b unit after stage 2 drains, same pin.

## Released 2026-10-31 (D7 landed the same day)

The recommended release mechanism is todo 524's D7 rule, landed 2026-10-31: waves 1 (18
restatement-skew names) and 2 (14 truncation names) release by the freshness rule plus the
recorded stamp list (`config/bars/grid_parity_dated_exceptions.json`), not a hand-edited symbol
list, so the next audit passes them and every future 5m restatement self-dates instead of
re-failing. ETHA and CTVA stay held (wave 3 in the file, loader skips it) until their
wrong-basis archive rows are re-fetched into the revision log. The released names enter the
feature build as the stage 2b unit after stage 2 drains (rebuild lane).
