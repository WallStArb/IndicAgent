---
status: completed
priority: P0
filed: 2026-07-19
completed: 2026-07-20
source: user question "why are the OHLCV prints corrupt, should we fix them" prompted a
  per-row investigation of todo 148's flagged rows against actual market history --
  found the guard cannot distinguish genuine data corruption from real, documented
  crisis events, and is currently misclassifying the latter as "suspect."
---

## Disposition (2026-07-20)

Shipped option (1) as recommended: cross-symbol corroboration in
`services/forward_return_writer.py` (`_build_corroborated_windows_temp_table_sql` +
`_apply_cross_symbol_corroboration`, new `--reclassify-suspect-only` CLI mode), gated by
two new APR keys (`alpha.quant.cross_symbol_corroboration.min_symbols=4`,
`.window_minutes=60`, migrations 240/241). Ran the corrective pass against the live
corpus: the confirmed May 6 2010 Flash Crash cluster (CWB/ITA/RSP/VTV/VUG/VYM,
18:20-18:55 UTC) is fully cleared; the genuine isolated corruption (UUP/XRT/VWO, 38 rows)
is untouched. 5m suspect count dropped 50→34 exactly as previewed against live data
before the fix was finalized.

**Design detour, worth knowing if this pattern recurs elsewhere:** the first two
implementations both failed live-data verification before the third one worked --
(1) an exact-`bar_ts`+same-scale match design never fired because a real event's
suspect flags stagger across bars and scales per symbol (fixed by pooling all 4 scales
+ matching within a `window_minutes` range instead of exact equality); (2) that fix ran
4 sequential per-scale `UPDATE`s in one transaction, each recomputing its own pooling
query from live (partially-mutated) table state -- a same-transaction read-skew that
wrote 11 wrong rows to production before being caught by re-verification and fixed by
freezing the pooling determination into a temp table computed once, upfront. Both bugs
were only found because each design change was verified against real production data,
not just unit tests, before being trusted.

Unblocked [151](151-known-corrupt-ohlcv-print-cleanup.md)'s `--apply` step (still
pending human review, not run). Also unblocked `ops_known_corrupt_print_cleanup.py`'s
`MARKET_EVENT` verdict (same corroboration signal, applied to raw-OHLCV classification).

# `return_{scale}_suspect` guard (todo 148) flags real historical crisis events as corrupt -- magnitude-only ceiling can't distinguish them from genuine bad prints

## Problem

Todo 148's guard (`alpha.quant.max_abs_return.{tf}`, sqrt-scaled per lookahead) flags any
return whose magnitude exceeds a per-tf ceiling as `suspect` and excludes it from
mean-based consumers. Investigated every currently-flagged row (76 total) against actual
market history and found two genuinely different populations conflated under one
mechanism:

**Confirmed genuine corruption** (no economic basis at any timescale):
- `UUP` 2007-06-20 19:00 UTC: two real (non-zero-volume) IBKR prints report `open=1000`
  on a ~$25 ETF. The flat-carry-forward calendar-fill mechanism then propagated that bad
  value across 8 more placeholder bars until real trading resumed -- see
  `.planning/todos/pending/151-known-corrupt-ohlcv-print-cleanup.md` for the fix.
- `XRT` 2007-09-18 18:15 UTC: `open=19.64, high=231.54, close=52.88` on a stock trading
  ~$19.60 all day, reverting within two bars. No real-world cause found.
- `VWO` 2007-07-26 (1d): `open=25.47`, roughly half the surrounding days' ~$49-50 range,
  while the same day's high (49.13) and close (46.77) traded normally -- an anomalous
  print on the open field specifically.

**Confirmed real, documented market history** (should NOT be flagged or excluded):
- `CWB`/`ITA`/`RSP`/`VTV`/`VUG`/`VYM`, all flagged within the SAME 17:00-19:00 UTC window
  on 2010-05-06 -- that's 2:32-3:08pm EDT, the **May 6, 2010 Flash Crash**. `ITA` genuinely
  traded to $0.07 that afternoon. Six unrelated ETFs flagging in the same 40-minute
  historical window is diagnostic on its own: corruption doesn't hit six symbols
  simultaneously at the same historical minute; a market-wide liquidity vacuum does.
- `IPO`/`QUAL`/`RSP`/`USMV`, flagged 2015-08-21 and 2015-08-24 -- the **August 24, 2015
  ETF flash crash** (NAV-arbitrage breakdown at market open during a China-driven
  selloff).
- `OIH`/`XOP`, 2020-03-06 -- Saudi-Russia oil price war news, real oil-sector volatility.
- `KRE`, 2008-09-18 -- three days after Lehman's bankruptcy filing; checked the raw bars
  directly, this is real high-volume panic trading in a regional-bank ETF, not corruption.

Per this project's Renaissance principle ("never drop data that could contain signal"),
silently excluding the Flash Crash from mean-based consumers is a real defect, not a
conservative default -- tail-risk events are exactly the data a research platform most
needs to reason about correctly, not the data it should treat as noise.

**Not yet checked:** `EZU` 2006-12-28 (flagged 15m/5m mid/fast) -- the specific flagged
timestamps' raw bars didn't show anything obviously anomalous in the window checked;
insufficient evidence to classify either way. `KRE`'s classification above is based on
one investigated window (19:35-20:05 UTC) and should be spot-checked against its exact
flagged bar if the timestamps differ.

## Fix

The magnitude-only ceiling structurally cannot make this distinction -- a real Flash
Crash return and a fabricated $1000-print return can have the same magnitude. Options,
not mutually exclusive:

1. **Cross-symbol corroboration check**: if N other symbols (N >= some small threshold,
   e.g. 3) show a similarly extreme move at the same (tf, timestamp), treat it as a
   real market-wide event, not a candidate for suspect-flagging -- this is exactly the
   signal that distinguished the Flash Crash cluster above from the isolated UUP/XRT
   prints. Directly implementable: extend the existing per-row suspect computation with
   a same-bar_ts cross-symbol count from `market_data_ohlcv`/`forward_returns`.
2. **Documented historical-event allowlist**: a small, explicit, human-curated list of
   known crisis windows (2008 GFC, May 6 2010 Flash Crash, Aug 24 2015 ETF flash crash,
   Feb 2018 Volmageddon, March 2020 COVID crash, etc.) that suppresses flagging within
   those windows regardless of magnitude. Simpler than (1), but requires maintaining the
   list and doesn't generalize to undocumented/smaller real events.
3. **Revert-shape check**: genuine corruption in the confirmed cases above shows either
   (a) a sustained implausible plateau with no reversion (UUP, via carry-forward
   propagation) or (b) a single-print anomaly with no real trading volume supporting it
   (XRT's high=231.54 print, VWO's open=25.47) -- versus real crisis moves showing
   continuous, volume-supported price action throughout the event (KRE's 2008-09-18
   sequence, ITA's Flash Crash bars, which show non-trivial volume at every step, not a
   single unsupported print). A volume/continuity check alongside the magnitude ceiling
   could catch this distinction without needing cross-symbol data or a curated list.

Recommend (1) as the primary fix -- it's mechanical, generalizes to future undocumented
events, and is the strongest single signal found in this investigation (the Flash Crash
cluster was obvious specifically because it was cross-symbol). Consider layering (3) as
a secondary signal for single-symbol events a cross-symbol check would miss. (2) as a
cheap supplementary safety net given how few major, well-known events actually matter
at daily-ETF-history timescales.

## Sizing

Todo-sized for option (1) alone: one additional per-row SQL predicate/CTE (count of
other symbols flagged at the same (tf, bar_ts) within some tolerance), threading through
the existing `_build_forward_return_sql` suspect computation in
`services/forward_return_writer.py`. Requires re-flagging the existing 76 suspect rows
(a corrective UPDATE, not a new migration) once implemented. Larger if (3) is layered in
too (needs a volume-continuity metric definition and its own threshold).

## References

- `.planning/todos/completed/148-forward-return-corrupt-print-guard.md` -- the guard
  this todo corrects
- `.planning/todos/pending/151-known-corrupt-ohlcv-print-cleanup.md` -- the confirmed-
  corruption cleanup (UUP/XRT/VWO), independent of this todo's cross-symbol-check work
- `services/forward_return_writer.py` `_build_forward_return_sql` -- suspect-flag
  computation, the edit site for option (1)
- `src/intelligence/statistics/ic_math.py` `scale_max_abs_return` -- the magnitude
  ceiling this todo does not replace, only supplements
