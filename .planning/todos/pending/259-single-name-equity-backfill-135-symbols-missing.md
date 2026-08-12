# 259: Single-name equity backfill queue -- 135 symbols missing

**Filed:** 2026-08-05
**Status:** pending, actively converging. **Updated 2026-08-11**: this queue is the same set
client-43 (launched 2026-08-06, finished 2026-08-09: 106/151 done) and its retry chain
(client-44/46/47/48, see [[project_universe_expansion_and_ibkr_recalibration_2026_08_06]]
memory) have been backfilling since. Live check against this exact symbol list: **115/135
(85%) now have full 5-timeframe coverage, 20 remaining.** client-48 (PID varies by session,
check `ps aux | grep infrastructure_run_historical_pipeline`) is running the current retry
pass. The "holding until client-id 41" framing below is stale -- client IDs moved to 43+ long
ago; don't relaunch a duplicate backfill without checking `ps` first (concurrent historical-data
sessions collide on IBKR's shared pacing budget, see `feedback_multiple_concurrent_backfills`
memory).

## What happened

Migration 287 registered 31 new single-name equities (the first individual stocks in the
corpus). Migration 296 (consolidated 2026-08-05 from three passes) added 42 more closing
sector-orthogonality gaps. Migration 299 (same session, committed 2026-08-05) added a further
70 across sixteen waves -- agriculture, consumer durables, staples depth, energy/clean energy,
crypto, transportation, mega-cap tech/media, biotech, healthcare care-delivery, telecom, a new
`wireless_infrastructure` cross-cutting tag, homebuilders, a broad growth/cyclical/defensive
sweep, utilities/water-utility depth, and fixed-income/FX peer-group depth -- driven by an
extended "what other areas need symbols" sweep across the same session, went through 6 rounds
of `/simplify` + peer code review. Migration 301 (committed same session) added KMI/WMB as a
second and third midstream single-name complement to EPD, requested after migration 299
shipped -- also backfilled EPD's own missing `rate_sensitive` tag, caught by peer review.
None of migration 296's, 299's, or 301's symbols have any backfill launched. Consolidating
into one queue rather than tracking each migration's backfill separately (user feedback
2026-08-05: don't trickle this across multiple files).

**Full queue, verified against `market_data_ohlcv` 2026-08-05 (zero rows):**

```
AA, ADM, AEP, AMD, AMT, AMZN, ASML, AVGO, AWK, BAC, BHP, BKNG, BLK, BNTX, CCJ, CMCSA, COIN, COP,
COST, CRM, CRSP, CRWD, CSX, CTVA, CVS, DAL, DD, DHI, DOCS, DOW, DUK, ECL, ELV, EMR, ENPH, EPD,
EQIX, ETHA, ETR, EXEL, F, FDX, FSLR, FXC, GE, GEV, GILD, GM, GOOGL, GS, HCA, HD, HYD, ICLN, IHF,
ISRG, ITB, IYZ, JBHT, JETS, KMI, LEN, LIN, LLY, LMT, MARA, META, MO, MOO, MS, MSFT, MSTR, NAD,
NEE, NFLX, NLY, NTR, NUE, NVDA, NVR, ODFL, OXY, PANW, PEP, PFE, PG, PGR, PLD, PM, QCOM, R, REGN,
RIOT, RSPG, RSPU, RTX, RVMD, SHW, SLB, SO, SPG, STIP, T, TDOC, THC, TMUS, TOL, TRV, TSLA, TSM,
UBER, UNH, UNP, UPS, URA, USB, V, VCR, VDC, VGT, VHT, VOX, VPU, VRP, VRTX, VST, VZ, WHR, WMB,
WMT, WSM, WTRG, XOM, XTL, XTN
```

133 symbols total (up from 112 -- confirmed the queue grows every time this todo is refreshed,
tracking the same "don't be stingy" sweep as it kept finding real gaps). This list will shift as
client-id 41's in-flight fetch (20 original migration-287 symbols) completes more names --
re-verify the zero-row set immediately before launching, don't trust this snapshot at execution
time. NEM dropped off the queue since the last refresh (client-id 41 completed it).

## Action needed

**Sequencing changed 2026-08-06 (user request):** before launching the full client-id 43
batch, run a bounded probe of two long-assumed IBKR constants in `src/providers/ibkr.py` --
`_MAX_CHUNK_DAYS` (per-request duration ceiling per timeframe) and `_IBKR_HIST_RATE_LIMIT`
(currently 55 req/10min, APR-tagged `[conventional]` in migration 276 -- inherited developer
convention, never independently measured against this account, unlike `_MAX_CHUNK_DAYS`'s
`[rca_analysis]`-tagged probe citations for 5m/15m/1h). The probe script
(`scripts/infrastructure/backfill/infrastructure_ibkr_chunk_and_rate_limit_probe.py`, new 2026-08-06) is
already armed to run automatically once client-id 41 exits (Monitor task `bikc169dk`) --
tests widened 1d/1h chunk windows and the rate limiter up to IBKR's documented 60 req/10min
ceiling, using real zero-row queued symbols (a successful test is real backfill progress, a
failed one writes nothing). Deliberately does NOT auto-launch client-id 43 or modify
production APR config after -- stops and reports so any discovered headroom gets applied
deliberately, not silently.

Once the probe completes and its findings are reviewed (and any resulting
`infra.ibkr.chunk_days.*`/`infra.ibkr.rate_limit_max_requests` APR changes applied, if
warranted), launch the consolidated backfill for the remaining zero-row set using a fresh
client-id (43, not reusing 35/40/41/42/44 -- 44 is the probe's own dedicated client-id):

```
.venv/bin/python scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py \
  --symbols <re-verified zero-row list> \
  --client-id 43
```

Same depth as the rest of the corpus: 20yr on 1d/1h/15m/5m, 90d on 1m. Don't run concurrently
with another historical-data session against IBKR Gateway (pacing contention).

Per [[project_end_to_end_corpus_compute_after_backfill]] (memory, 2026-08-05): once this
backfill completes, the next step is bundling Phase 151 waves 6-7, the CTF join-fix recompute,
and possibly todo 248's HMM walk-forward flag into one `ic_engine` pass -- not resuming Phase
151 in isolation.

**Session note (2026-08-05):** the universe went from 111 to 231 active instruments in one
sitting (roughly 2x). Stopping point reached deliberately -- confirmed with the user that
further equity sweeps have hit diminishing returns, and more symbols now increases the
already-large >50% zero-OHLCV-data ratio rather than delivering value. The backfill, not more
symbol coverage, is the actual bottleneck going forward. KMI/WMB (migration 301) landed after
this note was first written -- one small, targeted addition, not a resumption of the broader
sweep.

## Why this matters

`get_active_contracts()` returns 231 active rows but 135 of them (>58%) have no OHLCV data at
all -- any downstream corpus pipeline step (feature_factory, regime_writer, ic_engine,
cross_sectional_regime_model) that iterates active contracts will either error or silently skip
these symbols. The entire point of this session's sector-orthogonality expansion -- filling
real_estate/utilities/uranium/agriculture/biotech/crypto/transportation/fixed-income/FX gaps
with genuinely distinct factor loadings -- delivers zero measurable value until this backfill
runs.

## Also still open, not part of this backfill queue

- Colgate-Palmolive (CL) -- hard ticker collision with the existing WTI Crude Oil futures
  instrument (`instruments.symbol` is a primary key). Excluded from migration 299. No decision
  made on whether a symbol-aliasing workaround is worth building for one name.
- BAC.PRL (preferred-share proxy for fi_preferred depth) -- excluded on unconfirmed
  IBKR-contract-format-risk grounds (not the ticker-collision reason originally stated, which
  code review found factually wrong -- see migration 299's wave-16 comment for the correction).
  Not investigated further.
- `fx_usd` remains a genuine N=1 peer group (UUP only) -- no second dollar-index construction
  was found/offered during this session's fixed-income/FX sweep. See todo 271.
- Todo 271 (new, filed this session): no automated audit exists for thin/missing
  `instrument_tags` peer groups -- every gap fixed this session was found by a human asking
  "what about X?" in conversation, not by a query. Real process gap, out of scope for a
  migration diff.
