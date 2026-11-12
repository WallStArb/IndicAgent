---
status: closed
priority: P3
filed: 2026-11-01
source: data-layer redundancy audit (docs/plans/2026-11-01-data-layer-redundancy-audit.md)
gate: todo 534 (the pre-2016 5m campaign) closes
closed: 2026-11-12
---

# Re-measure the campaign doors when the 534 campaign closes

`ops_head_rerun.py`, `ops_intraday_venue_recovery.py`, `ops_ibkr_1d_deepening_gate.sh`,
`_campaign.py` and `ops_truncated_bar_scan.py` stand while the 534 campaign runs; each is a
distinct safety posture over the same fetcher, not a duplicate. When 534 closes, measure each
door's remaining call volume and disposition keep / delete / capture-as-todo, so the fetch
family does not accumulate retired doors the way the Tradier family did.

Done when: each of the five has a dated disposition line in this todo.

## Closure 2026-11-12

Closed 2026-11-12 (lead): superseded by Massive (todo 600). The data-complete gate is Massive admission, the IBKR fetcher timer is disabled, and the IBKR leg joins todo 600's deletion list once step 7 proves itself (owner 2026-11-10: stop polishing IBKR/Alpaca-era data).
