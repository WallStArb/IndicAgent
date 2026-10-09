---
status: pending
priority: P3
filed: 2026-10-09
corrected: 2026-10-09 (premise withdrawn after a dry-run verification; see below)
source: owner directive 2026-10-09 ("depth should be measured correctly for each TF"); corrected by the same day's verification
---

# Provider-head granularity per timeframe (the surviving piece of todo 526)

## Correction 2026-10-09 (the original premise is withdrawn)

The original body claimed the queue infers depth from each series' earliest stored bar, leaving
163 head gaps invisible and requiring an expected-domain planner rework. A dry run of the ten
genuinely short names disproves the claim: the planner already computes gap from
min(depth_days, proven_days, floor) - actual, where proven_days is the deepest stored series of
the symbol (1d, which stays IBKR-deep) and floor is max(ohlcv_provider_head.head_ts,
ohlcv_empty_history.empty_through). ODFL plans 6,197 gap-days, AAP 4,521, IEF and SHY 3,946,
TLT 3,399, CSX 3,356, AMD 3,002, all SLA-banded. The "163 invisible head gaps" were almost
entirely the vendor floors differing (1d floor 2000-01-03, IBKR 5m floor 2006-07): not missing
data. The phase 2 canonical-load hold's rationale dissolves with it: an Alpaca 5m load changes
neither proven depth (1d) nor the floor, so IBKR head planning survives it.

What remains real and worth doing, small:

- `ohlcv_provider_head` has no timeframe column (PK: symbol, provider). The 1d head stands in as
  the floor for every timeframe. For IBKR this is approximately right (1d floor 2000, 5m floor
  2006-07) but the empty-history walk pays a few definitive no-data round trips per name per
  timeframe to discover what a per-TF head row would state outright. Migrate the PK to
  (symbol, provider, timeframe), seed per-TF floors from the measured vendor floors, and let the
  existing walk keep them fresh.
## What

The fetch queue plans depth from each series' earliest stored bar (`_fetch_queue.py`:
`depth = days_since(earliest_timestamp)`). That inference is the root of a whole defect class:

- 163 names hold 5m that starts years after their 1d begins (125 in the old intraday set);
  the queue cannot see their heads, so no run will ever plan them.
- The phase 2 Alpaca load would hide IBKR heads the same way (the sequencing hold on the
  phase 2 canonical load exists only because of this).
- `ohlcv_provider_head` has no timeframe column (PK: symbol, provider): the vendor floor is
  measured for 1d only, so per-TF floors (IBKR 5m floor is ~2006-07, measured in the pilot;
  15m/1h derive from 5m) are not even representable.

The fix, planner-side, no writer changes:

1. **Migration:** `ohlcv_provider_head` PK becomes (symbol, provider, timeframe). Global
   per-vendor-per-TF floors are measured once on a sample (walk back until empty) and recorded
   as sentinel rows; per-name rows exist only where a probe contradicts the global floor
   (the empty-history definitive-no-data path already produces them).
2. **Expected-domain planning:** for each (symbol, provider, timeframe), the expected domain is
   [max(provider floor, listing anchor), now]; the plan is the expected domain minus stored spans
   (per source: bars carry `source`) minus answered windows. Stored-bar earliest is never an
   input. Heads and tails become one gap model; the head-extension special case dies.
3. **Effect:** the 163 head-gap names plan correctly; the IBKR drain and the Alpaca all-names
   load run in parallel with no sequencing hold (each planner plans only its own provider's
   missing spans; first-writer-stays still governs overlaps); T4's nightly reads the same
   planner.

## Sequencing note

The phase 2 canonical-load hold (todo 523 record, coordination with indicagent-87) can lift as
soon as this lands, not when the drain completes. Until then the hold stands.

## Done when

Provider head carries per-TF floors; the queue plans from expected domains; a name with a pre-earliest
gap plans a backfill run without any special flag; the 163 names plan and fill; the phase 2 hold
is lifted by the owner after a verified pass.
