---
status: pending
priority: P2
filed: 2026-11-13
source: review 9 of origin/massive-8a-load-checks at 0a636280a (r5j); lead scope cut 2026-11-13 (indicagent-d0)
---

# Massive 8a load checks: review 9 ledger, label and hygiene items

## Why deferred

The lead cut review 9 to the items that can change an (era, timeframe) verdict (1, 4 and 5, landed as r5k). Convergence is measured by rerunning and comparing the era/timeframe partition with r5j, not by further review. The items below do not move a verdict; they change ledger rows, labels, summary fields or cost. None is verified against the code yet: verify each before fixing, and push back with evidence where it is false.

## Items (review 9 numbering; line numbers at 0a636280a)

- 2 (ledger) `ops_massive_load_checks.py:1956`: witness independence per cited split ROW, not per date. A market split whose only market-fact source is `massive_reference` cannot convict the incumbent, whatever non-market `calendar_audit` rows share its date. Test with the live shape (ELS 2019-10-15, OKE 2012-06-01, WST 2004-09-29, UHAL 2022-11-09).
- 3 (ledger) `ops_massive_load_checks.py:2391/2401`: `incumbent_rescaled` is true only for the IBKR `smart_trades` 1d series that rule 7 rescaled; 5m rows are never rescaled.
- 6 (summary field) `ops_massive_load_checks.py:2538`: `vendor_wide_return_agreement` reflects stage C price stops only; systemic stops are reported under their own stage keys. If the design says the vendor-wide rule is superseded, rename the field to what it now measures.
- 7 (count) `massive_load_checks.py:93`: the defect share counts a row once (union of the defective and duplicate masks).
- 8 (cost) `ops_massive_load_checks.py:2291`: fold once; `judged_timeframes` computed once per name-era and passed down.
- 9 (cost) `ops_massive_load_checks.py:941`: `sanity_of` once per day file.
- 10 (duplication) `ops_massive_load_checks.py:1937`: use `cited_sources`; delete the inline copy.

## Done when

Each item is fixed or rejected with evidence, the bars and touched script tests pass (live-DB probes with `--sql-probe-url`), and a rerun shows the era/timeframe partition unchanged from the run that landed the runner. A change that does move a verdict is a finding, not hygiene: stop and rule on it first.
