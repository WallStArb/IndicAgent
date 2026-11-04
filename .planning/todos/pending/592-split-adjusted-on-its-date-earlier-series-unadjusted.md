---
status: pending
priority: P1
filed: 2026-11-04
source: todo 587 review, per-series split audit (ops_split_calendar_audit, 2026-11-04 rerun)
---

# Splits canonical crosses adjusted on their date while an earlier raw series is off scale

## What

The 587 audit records a split only when canonical steps by the ratio on its date. With every raw
series now measured on its own (its close over Yahoo's split-adjusted close across the date, 20
sessions a side inside the neighbouring calendar events), nine splits canonical crosses cleanly
show a raw series off scale before them. When that series serves canonical before a seam, the break
lands at the seam instead (the 2016-01-04 IBKR-to-Alpaca seam for the Alpaca-era cases).

Per-series log step across the date (-log f = unadjusted, +log f = adjusted twice, null =
unmeasurable), from `config/corporate_actions/split_calendar_audit_2026_11_04.csv`:

| Split | f | canonical at the date | step per series |
|---|---|---|---|
| FBIZ 2015-08-31 | 2 | ibkr/named | ibkr/smart_trades +0.693 |
| IJR 2017-01-19 | 2 | alpaca/sip_rth | alpaca 0.000, ibkr +0.693 |
| MTCH 2020-07-01 | 3.5 | alpaca/sip_rth | alpaca 0.000, ibkr -1.129 (IAC separation) |
| MVBF 2014-04-02 | 2 | ibkr/named | ibkr null |
| NVDA 2001-09-10 | 2 | ibkr/named | ibkr -0.693 |
| PATK 2017-12-11 | 1.5 | alpaca/sip_rth | alpaca 0.000, ibkr +0.916 |
| RJF 2021-09-22 | 1.5 | alpaca/sip_rth | alpaca 0.000, ibkr +0.405 |
| UHAL 2022-11-10 | 10 | ibkr/fallback | both null |
| WST 2004-09-29 | 2 | ibkr/named | ibkr -0.693 |

NVDA and WST (ibkr/named, canonical adjusted at the date but the raw series not) mean canonical's
own step was measured on a different bar set than the series median: check for a mid-span raw
restatement. The + cases are IBKR history adjusted for a split it did not carry (or twice).

## Do

Per case, find where canonical breaks (D7's generalized split_continuity on a dry run names the
seam), decide the fact (a calendar_audit row naming the off-scale series, a quarantine, or nothing
when that series never serves canonical), and fold the rule into the audit if a class emerges.
Not part of the 587 landing.
