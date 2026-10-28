# D-191-Q three-vendor 1d arbitration (todo 545)

Author: scripts/ops/bars/ops_d191q_arbitration.py (read-only session). Informed by: D-191-Q in docs/plans/2026-10-12-unified-raw-bar-table-design.md, todo 545.

Run 2026-10-27T21:24:41.252106+00:00. Window 2016-01-04 to 2026-10-06 (Tradier's last 1d session). Tolerance 10.0 bp per session, a span of at least 20 sessions, a class share of at least 0.9. 1529 names. Plan: `/home/bg/dev/indicagent/data/policy_plans/d191q_1d_plan_20261027.json` (gitignored), the document `ops_source_policy.py --plan` takes; nothing was written to the database.

## Classes

| Class | Action | Spans | Sessions | Names |
|-------|--------|-------|----------|-------|
| alpaca_differs | noise | 5026 | 6,586 | 872 |
| alpaca_differs | row | 46 | 72,826 | 46 |
| ibkr_defective | evidence | 1318 | 19,344 | 194 |
| pre_ibkr_history | hold | 27 | 18,934 | 27 |
| pre_ibkr_history | info | 116 | 186,015 | 116 |
| three_way | hold | 26 | 30,975 | 23 |
| three_way | noise | 413 | 749 | 150 |
| two_vendor | hold | 2 | 1,368 | 2 |
| two_vendor | noise | 40 | 61 | 22 |

Actions: row = an IBKR symbol row (IBKR = Tradier, Alpaca differs); evidence = IBKR is wrong and Alpaca serves (Alpaca = Tradier); hold = for the owner, no row; noise = shorter than the span minimum (Alpaca serves); info = Alpaca before IBKR history IBKR has not verified (Alpaca serves).

## IBKR symbol rows (46)

| Symbol | From | To (excl.) | Sessions | IBKR/Alpaca | Tradier/Alpaca |
|--------|------|------------|----------|-------------|----------------|
| ALKS | 2016-01-04 | 2023-11-16 | 1980 | 0.9297 | 0.9296 |
| APTV | 2017-11-17 | 2026-04-01 | 2101 | 0.8471 | 0.8471 |
| AWI | 2016-01-04 | 2016-04-02 | 62 | 0.4333 | 0.4333 |
| BHP | 2016-01-04 | 2022-06-02 | 1615 | 0.8918 | 0.8918 |
| BIIB | 2016-01-04 | 2017-02-02 | 273 | 0.9211 | 0.9211 |
| BWA | 2016-01-04 | 2023-07-04 | 1887 | 0.8796 | 0.8796 |
| CHTR | 2016-01-04 | 2016-05-18 | 94 | 1.1060 | 1.1060 |
| CMCSA | 2016-01-04 | 2026-01-03 | 2515 | 0.9368 | 0.9368 |
| DD | 2017-09-01 | 2025-11-01 | 2053 | 0.4182 | 0.4182 |
| DELL | 2018-12-28 | 2021-11-02 | 717 | 0.9981 | 0.9981 |
| DHR | 2016-01-04 | 2023-09-30 | 1949 | 0.8864 | 0.8864 |
| DTE | 2016-01-04 | 2021-07-01 | 1383 | 0.8508 | 0.8508 |
| ECHO | 2016-01-04 | 2019-09-11 | 928 | 0.8101 | 0.8101 |
| EHC | 2016-01-04 | 2022-07-01 | 1635 | 0.7951 | 0.7951 |
| ENOV | 2016-01-04 | 2022-04-05 | 1575 | 0.5733 | 0.5733 |
| ENSG | 2016-01-04 | 2019-10-01 | 942 | 0.9347 | 0.9352 |
| EQT | 2016-01-04 | 2018-11-13 | 722 | 0.4354 | 0.4355 |
| EXC | 2016-01-04 | 2022-02-02 | 1532 | 0.7131 | 0.7131 |
| FBIN | 2016-01-04 | 2022-12-15 | 1751 | 0.8546 | 0.8546 |
| FDX | 2016-01-04 | 2026-05-30 | 2616 | 0.8053 | 0.8053 |
| FLEX | 2016-01-04 | 2024-01-03 | 2013 | 0.7274 | 0.7274 |
| FNF | 2016-01-04 | 2025-12-17 | 2504 | 0.9264 | 0.9266 |
| FTAI | 2016-01-04 | 2022-08-02 | 1655 | 0.8539 | 0.8539 |
| FWONK | 2017-01-25 | 2023-07-20 | 1631 | 0.9832 | 0.9829 |
| GE | 2016-01-04 | 2024-04-03 | 2075 | 0.6223 | 0.6223 |
| ILMN | 2016-01-04 | 2024-06-25 | 2132 | 0.9718 | 0.9720 |
| IR | 2017-05-12 | 2020-02-29 | 704 | 0.8824 | 0.8824 |
| J | 2016-01-04 | 2025-05-16 | 2356 | 0.8265 | 0.8264 |
| JEF | 2016-01-04 | 2023-01-14 | 1771 | 0.8945 | 0.8944 |
| LGND | 2016-01-04 | 2022-11-02 | 1721 | 0.6236 | 0.6236 |
| LH | 2016-01-04 | 2023-07-01 | 1886 | 0.8591 | 0.8583 |
| MMM | 2016-01-04 | 2024-03-29 | 2073 | 0.8361 | 0.8361 |
| MRK | 2016-01-04 | 2021-06-03 | 1363 | 0.9535 | 0.9535 |
| NAT | 2016-01-04 | 2017-08-10 | 404 | 0.9912 | 0.9912 |
| PNR | 2016-01-04 | 2018-05-01 | 585 | 0.6715 | 0.6715 |
| QGEN | 2016-01-04 | 2026-01-08 | 2518 | 1.0827 | 1.0827 |
| SCCO | 2016-01-04 | 2026-08-11 | 2665 | 0.9157 | 0.9157 |
| SPGI | 2016-01-04 | 2026-07-01 | 2637 | 0.9459 | 0.9459 |
| T | 2016-01-04 | 2022-04-09 | 1579 | 0.7548 | 0.7548 |
| TT | 2016-01-04 | 2020-02-29 | 1046 | 0.8824 | 0.8824 |
| UHAL | 2016-01-04 | 2022-11-10 | 1727 | 0.1000 | 0.1000 |
| WDC | 2016-01-04 | 2025-02-22 | 2298 | 0.7556 | 0.7554 |
| WPC | 2016-01-04 | 2023-11-02 | 1972 | 0.9790 | 0.9790 |
| XLF | 2016-01-04 | 2016-09-17 | 179 | 0.8120 | 0.8123 |
| ZBH | 2016-01-04 | 2022-03-01 | 1550 | 0.9701 | 0.9701 |
| ZD | 2016-01-04 | 2021-10-08 | 1452 | 0.8692 | 0.8692 |

## Hold list (55)

IBKR/Tradier is the ratio of the two medians: near 1 on a three_way span means IBKR and Tradier both adjusted the history (a spin-off) with factors a few bp apart, so the per-session test could not call it alpaca_differs.

| Symbol | Class | From | To | Sessions | With Tradier | IBKR/Alpaca | Tradier/Alpaca | IBKR/Tradier |
|--------|-------|------|----|----------|--------------|-------------|----------------|--------------|
| SW | pre_ibkr_history | 2016-01-04 | 2024-07-05 | 2140 | 911 |  |  |  |
| AKTS | pre_ibkr_history | 2017-03-13 | 2024-12-17 | 1956 | 1956 |  |  |  |
| COO | pre_ibkr_history | 2016-01-04 | 2023-09-25 | 1945 | 1945 |  |  |  |
| CRH | pre_ibkr_history | 2016-01-04 | 2023-09-22 | 1944 | 801 |  |  |  |
| CR | pre_ibkr_history | 2016-01-04 | 2023-03-28 | 1821 | 1821 |  |  |  |
| TPL | pre_ibkr_history | 2016-01-04 | 2021-01-11 | 1265 | 688 |  |  |  |
| EXE | pre_ibkr_history | 2016-01-04 | 2020-06-26 | 1129 | 1129 |  |  |  |
| CRC | pre_ibkr_history | 2016-06-01 | 2020-07-15 | 1038 | 1038 |  |  |  |
| CMPR | pre_ibkr_history | 2016-01-04 | 2019-12-03 | 987 | 987 |  |  |  |
| LION | pre_ibkr_history | 2016-01-04 | 2022-02-24 | 915 | 915 |  |  |  |
| CART | pre_ibkr_history | 2016-01-05 | 2019-12-31 | 846 | 0 |  |  |  |
| FOXA | pre_ibkr_history | 2016-01-04 | 2019-03-12 | 802 | 1 |  |  |  |
| ST | pre_ibkr_history | 2016-01-04 | 2018-03-27 | 562 | 562 |  |  |  |
| DD | pre_ibkr_history | 2016-01-04 | 2017-08-31 | 420 | 0 |  |  |  |
| DOW | pre_ibkr_history | 2016-01-04 | 2017-08-31 | 420 | 0 |  |  |  |
| DK | pre_ibkr_history | 2016-01-04 | 2017-06-30 | 377 | 377 |  |  |  |
| APO | pre_ibkr_history | 2016-01-04 | 2016-12-08 | 237 | 237 |  |  |  |
| ITT | pre_ibkr_history | 2016-01-04 | 2016-05-16 | 93 | 93 |  |  |  |
| AVGO | pre_ibkr_history | 2016-01-04 | 2016-02-01 | 20 | 20 |  |  |  |
| AA | pre_ibkr_history | 2016-10-06 | 2016-10-17 | 8 | 0 |  |  |  |
| FCFS | pre_ibkr_history | 2016-08-31 | 2016-09-01 | 2 | 2 |  |  |  |
| FERG | pre_ibkr_history | 2021-03-08 | 2021-03-09 | 2 | 1 |  |  |  |
| ARRY | pre_ibkr_history | 2020-10-15 | 2020-10-15 | 1 | 1 |  |  |  |
| IBEX | pre_ibkr_history | 2020-08-07 | 2020-08-07 | 1 | 1 |  |  |  |
| NRIX | pre_ibkr_history | 2020-07-24 | 2020-07-24 | 1 | 1 |  |  |  |
| RLAY | pre_ibkr_history | 2020-07-16 | 2020-07-16 | 1 | 1 |  |  |  |
| VOR | pre_ibkr_history | 2021-02-05 | 2021-02-05 | 1 | 1 |  |  |  |
| HON | three_way | 2016-01-04 | 2026-06-26 | 2635 | 2633 | 0.4938 | 0.4954 | 0.9967 |
| ATRO | three_way | 2016-01-04 | 2026-06-12 | 2626 | 2626 | 0.8315 | 0.8333 | 0.9978 |
| BDX | three_way | 2016-01-04 | 2026-02-09 | 2540 | 2540 | 0.7802 | 0.7667 | 1.0177 |
| CBSH | three_way | 2016-01-04 | 2025-12-01 | 2493 | 2493 | 0.7835 | 0.7835 | 0.9999 |
| LEN | three_way | 2016-01-04 | 2025-01-17 | 2275 | 2275 | 0.9609 | 0.9256 | 1.0381 |
| FTV | three_way | 2016-07-05 | 2025-06-27 | 2259 | 2259 | 0.7535 | 0.7534 | 1.0002 |
| CENT | three_way | 2016-01-04 | 2024-02-08 | 2039 | 2039 | 0.7827 | 0.8000 | 0.9784 |
| CTVA | three_way | 2019-06-03 | 2026-09-30 | 1843 | 1843 | 0.1795 | 0.1500 | 1.1964 |
| XPO | three_way | 2016-01-04 | 2022-10-31 | 1720 | 1720 | 0.5941 | 0.3457 | 1.7187 |
| POST | three_way | 2016-01-04 | 2022-03-10 | 1558 | 1558 | 0.6820 | 0.6543 | 1.0423 |
| CNH | three_way | 2016-01-04 | 2021-12-31 | 1511 | 1511 | 0.8696 | 0.8687 | 1.0010 |
| GYRE | three_way | 2017-02-13 | 2023-01-12 | 1490 | 1490 | 0.6731 | 0.0667 | 10.0964 |
| RTX | three_way | 2016-01-04 | 2020-04-02 | 1070 | 1070 | 0.2949 | 0.3147 | 0.9372 |
| FTI | three_way | 2017-01-17 | 2021-02-12 | 1027 | 1027 | 0.7440 | 0.8186 | 0.9089 |
| EU | three_way | 2023-01-23 | 2026-09-24 | 922 | 922 | 0.9627 | 0.9644 | 0.9982 |
| DHC | three_way | 2016-07-01 | 2019-12-31 | 881 | 881 | 0.9647 | 0.9692 | 0.9953 |
| SNEX | three_way | 2016-01-04 | 2019-10-22 | 577 | 43 | 1.5000 | 0.9783 | 1.5333 |
| NEXN | three_way | 2024-01-10 | 2025-02-14 | 276 | 52 | 2.0000 | 0.9659 | 2.0705 |
| IJR | three_way | 2016-01-04 | 2017-01-17 | 262 | 262 | 0.5000 | 1.9999 | 0.2500 |
| YUM | three_way | 2016-01-04 | 2016-10-31 | 210 | 210 | 0.7191 | 0.7177 | 1.0020 |
| JCI | three_way | 2016-01-04 | 2016-10-28 | 209 | 209 | 0.8698 | 0.8949 | 0.9719 |
| KNX | three_way | 2016-01-04 | 2016-10-20 | 203 | 203 | 0.9176 | 1.3889 | 0.6607 |
| LION | three_way | 2022-03-01 | 2023-03-07 | 149 | 149 | 0.9679 | 1.0104 | 0.9580 |
| KNX | three_way | 2016-11-18 | 2017-04-13 | 100 | 100 | 0.9660 | 1.3889 | 0.6955 |
| KNX | three_way | 2017-04-18 | 2017-08-01 | 74 | 74 | 0.9935 | 1.3889 | 0.7153 |
| KNX | three_way | 2017-08-03 | 2017-09-08 | 26 | 26 | 0.9964 | 1.3889 | 0.7174 |
| ELS | two_vendor | 2016-01-04 | 2019-10-15 | 953 | 0 | 0.5000 |  |  |
| QBTS | two_vendor | 2020-12-11 | 2022-08-05 | 415 | 0 | 0.6877 |  |  |

## IBKR-defective spans (1318 spans, 194 names, 19,344 sessions)

Alpaca agrees with Tradier and IBKR does not: Alpaca serves under the default, no row. Largest names by sessions:

| Symbol | Sessions |
|--------|----------|
| UNIT | 2409 |
| VATE | 2056 |
| OKE | 1942 |
| SSP | 1888 |
| SAFE | 1449 |
| RJF | 1440 |
| UAMY | 1300 |
| APO | 1272 |
| CUBI | 1249 |
| TMUS | 1126 |
| ETHA | 528 |
| PATK | 489 |
| GME | 367 |
| NVDA | 258 |
| BNTX | 197 |
| RSPF | 180 |
| CVNA | 168 |
| PARR | 162 |
| TAN | 159 |
| ENPH | 61 |
| ACMR | 52 |
| EPSN | 41 |
| SIRI | 38 |
| RAIL | 37 |
| PMTS | 35 |
| WULF | 27 |
| AXSM | 24 |
| MOD | 24 |
| BATRA | 23 |
| FLGT | 23 |

## Live symbol rows (154)

Retired: confirmed 132, replaced 4. Kept: 18.

| Symbol | Kept because |
|--------|--------------|
| BDX | hold: the arbitration left spans for the owner |
| CART | hold: the arbitration left spans for the owner |
| CNH | hold: the arbitration left spans for the owner |
| CTVA | hold: the arbitration left spans for the owner |
| ELS | hold: the arbitration left spans for the owner |
| EU | hold: the arbitration left spans for the owner |
| FTI | hold: the arbitration left spans for the owner |
| FTV | hold: the arbitration left spans for the owner |
| FTV | hold: the arbitration left spans for the owner |
| FTV | hold: the arbitration left spans for the owner |
| GYRE | hold: the arbitration left spans for the owner |
| LION | hold: the arbitration left spans for the owner |
| NEXN | hold: the arbitration left spans for the owner |
| POST | hold: the arbitration left spans for the owner |
| QRVO | no common Alpaca and IBKR sessions to arbitrate |
| SNEX | hold: the arbitration left spans for the owner |
| TPL | hold: the arbitration left spans for the owner |
| YUM | hold: the arbitration left spans for the owner |
