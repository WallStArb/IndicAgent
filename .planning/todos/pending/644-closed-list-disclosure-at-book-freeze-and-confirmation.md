---
status: pending
priority: P2
filed: 2026-11-19
source: preregistration Amendment 2026-11-18 (closed list), item 4 and build item B-C
owner: lead
---

# Disclose the closed list's member count and excluded newcomers at every freeze and confirmation

## What

The adopted amendment requires, at every book freeze and every forward confirmation, the member count at each month-end after L = 2026-11-09 and the count of securities on Alpaca's active asset list that date that are absent from the list at L (the excluded newcomers), so the decay of breadth is a number and not an assumption. The count of newcomers needs the Alpaca asset list as a source (todo 643 captures it; until then the member counts alone are disclosable).

## Done when

The freeze and confirmation reports print both numbers per month-end after L from the ledger (`rule_id = 'stage2-closed-list'` rows) and the captured asset list, and a test pins the section.
