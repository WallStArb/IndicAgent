# 259: Single-name equity backfill queue -- 53 symbols missing

**Filed:** 2026-08-05
**Status:** pending -- holding until client-id 41 run finishes (user decision 2026-08-05)

## What happened

Migration 287 (commit `301d8225`, 2026-08-05) registered 31 new single-name equities in
`instruments` (the first individual stocks in the corpus -- everything prior is ETF/basket).
Commit message claims all 31 symbols' OHLCV backfill launched via
`infrastructure_run_historical_pipeline.py` (client-id 41), but the actual launched process only
has 20 symbols in its `--symbols` arg:

```
AAPL,JPM,MCD,PG,CAT,MMM,BA,FCX,NEM,NUE,DE,CVX,KO,DIS,MRK,JNJ,AXP,HON,V,TRV
```

**11 symbols from migration 287 have zero backfill launched:** XOM, SLB, COP, AA, BHP, GE, UNP,
EMR, DD, LIN, OXY.

Since filing, migration 296 (consolidated 2026-08-05 from three passes, see that file's header
for the full audit rationale) registered 42 more single-name equities/ETFs closing sector-
orthogonality gaps -- none of their backfills have been launched either. Consolidating all of it
into one queue rather than tracking each migration's backfill as a separate todo (user feedback
2026-08-05: don't trickle this across multiple files).

**Full queue, verified against `market_data_ohlcv` 2026-08-05 (zero rows, excluding the 8 of
client-id 41's 20 symbols still mid-fetch -- JPM, MCD, PG, MMM, KO, MRK, V, TRV -- which are
already covered by that in-flight process):**

```
AA, AEP, AMT, AMZN, AVGO, BAC, BHP, BKNG, BLK, CCJ, CMCSA, COP, COST, DAL, DD, DHI, DOW, DUK,
ECL, EMR, EQIX, GE, GS, HD, ISRG, LIN, LLY, MS, MSFT, NEE, NFLX, OXY, PEP, PFE, PGR, PLD, RTX,
SLB, SO, T, TMUS, TSLA, TSM, UNH, UNP, UPS, URA, USB, VRTX, VZ, WMT, XOM
```

53 symbols total.

## Action needed

Once the client-id 41 run (20 symbols) completes, launch the consolidated backfill for all 53
remaining symbols:

```
.venv/bin/python scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py \
  --symbols AA,AEP,AMT,AMZN,AVGO,BAC,BHP,BKNG,BLK,CCJ,CMCSA,COP,COST,DAL,DD,DHI,DOW,DUK,ECL,EMR,EQIX,GE,GS,HD,ISRG,LIN,LLY,MS,MSFT,NEE,NFLX,OXY,PEP,PFE,PGR,PLD,RTX,SLB,SO,T,TMUS,TSLA,TSM,UNH,UNP,UPS,URA,USB,VRTX,VZ,WMT,XOM \
  --client-id 42
```

Same depth as the rest of the corpus: 20yr on 1d/1h/15m/5m, 90d on 1m. Use a fresh client-id (42)
rather than reusing 41/40/35 -- don't run concurrently with another historical-data session
against IBKR Gateway (pacing contention), per user decision 2026-08-05 to hold until the current
run finishes. Re-verify the zero-row set right before launching (client-id 41 may have finished
more symbols by then, including the 8 currently mid-fetch).

## Why this matters

Without this, `get_active_contracts()` returns 153 active rows but 53 of them have no OHLCV data
at all -- any downstream corpus pipeline step (feature_factory, regime_writer, etc.) that
iterates active contracts will either error or silently skip these symbols. The whole point of
migration 296's sector-orthogonality expansion (more single-name data points, distinct factor
loadings per sector) delivers zero value until this backfill runs -- every sector migration 296
added a name to (technology, healthcare, financials, real estate, utilities, communication
services, materials chemicals, consumer discretionary/staples) still has zero single-name
coverage in the actual corpus until this queue clears.
