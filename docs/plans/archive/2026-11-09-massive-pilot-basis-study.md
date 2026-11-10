# Massive pilot basis study (archived)

Date: 2026-11-09 (runbook), amended 2026-11-10. Archived 2026-11-10.
Outcome: never run to a verdict. The owner ruled Massive is used regardless, so the admit or refuse
gate was dropped; the checks that decide how each name and span loads moved into
`docs/plans/2026-11-10-massive-admission-db-design.md` section 8a.

Ideas kept (all in section 8a): a frozen, hashed split list and ticker-as-of map instead of a fitted
factor; an increment-aware price agreement band; the day file against its own minute file; the 1d census
with 592 straddles; units, session and record sanity; publish lag and the manifest completeness proof;
survivorship measured and disclosed, never a gate; Massive as the yardstick with a third-witness rule.

Findings worth keeping from the calibration probes (2026-11-10):
- Step 0 layout: `.csv.gz`, columns `ticker,volume,open,close,high,low,window_start,transactions`,
  `window_start` in nanoseconds, extended hours included, plain dollars and shares in 2010.
- 286 of 835 names in 2010-03 show a Massive to IBKR 1d close ratio away from 1; the split table explains 1; 103
  sit near no split ratio (IBKR `smart_trades` carries non-split adjustments).
- IBKR stores adjusted prices at cent precision; a 1 bp tolerance cannot pass against them.
- Massive `BNY` in 2010 is a different security from our `BNY`; 86 of 921 held names have no same-ticker Massive row.
- The day file is not the aggregate of its own minute file (2003-09-10: close differs on 1,976 of 7,716 names).
- IBKR emits zero-volume bars where Massive has none (CORT 57 of 78 on 2010-01-04).

Partial result tables (not a verdict): `logs/massive_pilot/`.
Full text: git history, `79aeb9aa7` (final) and `b371b84c9` (before the amendment).
