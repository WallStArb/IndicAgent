# Phase 182 deferred items

Out-of-scope discoveries logged by plan executors; not fixed in the plan that found them.

## From plan 03 (2026-09-25)

- **RSPG `instruments` row is mislabeled.** `contract_details->>'name'` = "Invesco S&P 500 Equal
  Weight Consumer Staples ETF" and `sector` = `consumer_staples`, but RSPG has been the Equal
  Weight Energy fund since Invesco's 2023 ticker renaming (staples is RSPS). Two-year daily-return
  correlation: 0.98 with XLE, 0.15 with XLP. The indicagent_v1 seed already maps RSPG to
  EQ.EN.ENERGY with this evidence; the `name` field needs a data-fix migration (the flat `sector`
  field stops being a source of truth under D-10 but is still stored).
- **VIX and VX are duplicate inactive rows** for the same CFE VIX future (both trading class VX,
  point value 1000, exchange CFE). Both classified VOL.EQUITY. Whether to retire one is an
  instruments-table decision.
