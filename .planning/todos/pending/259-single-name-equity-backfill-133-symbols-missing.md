# 259: Single-name equity backfill queue -- 133 symbols missing

**Filed:** 2026-08-05
**Status:** pending -- holding until client-id 41 run finishes (user decision 2026-08-05)

## What happened

Migration 287 registered 31 new single-name equities (the first individual stocks in the
corpus). Migration 296 (consolidated 2026-08-05 from three passes) added 42 more closing
sector-orthogonality gaps. Migration 299 (same session, committed 2026-08-05) added a further
70 across sixteen waves -- agriculture, consumer durables, staples depth, energy/clean energy,
crypto, transportation, mega-cap tech/media, biotech, healthcare care-delivery, telecom, a new
`wireless_infrastructure` cross-cutting tag, homebuilders, a broad growth/cyclical/defensive
sweep, utilities/water-utility depth, and fixed-income/FX peer-group depth -- driven by an
extended "what other areas need symbols" sweep across the same session, went through 6 rounds
of `/simplify` + peer code review. None of migration 296's or 299's symbols have any backfill
launched. Consolidating into one queue rather than tracking each migration's backfill
separately (user feedback 2026-08-05: don't trickle this across multiple files).

**Full queue, verified against `market_data_ohlcv` 2026-08-05 (zero rows):**

```
AA, ADM, AEP, AMD, AMT, AMZN, ASML, AVGO, AWK, BAC, BHP, BKNG, BLK, BNTX, CCJ, CMCSA, COIN, COP,
COST, CRM, CRSP, CRWD, CSX, CTVA, CVS, DAL, DD, DHI, DOCS, DOW, DUK, ECL, ELV, EMR, ENPH, EPD,
EQIX, ETHA, ETR, EXEL, F, FDX, FSLR, FXC, GE, GEV, GILD, GM, GOOGL, GS, HCA, HD, HYD, ICLN, IHF,
ISRG, ITB, IYZ, JBHT, JETS, LEN, LIN, LLY, LMT, MARA, META, MO, MOO, MS, MSFT, MSTR, NAD, NEE,
NFLX, NLY, NTR, NUE, NVDA, NVR, ODFL, OXY, PANW, PEP, PFE, PG, PGR, PLD, PM, QCOM, R, REGN,
RIOT, RSPG, RSPU, RTX, RVMD, SHW, SLB, SO, SPG, STIP, T, TDOC, THC, TMUS, TOL, TRV, TSLA, TSM,
UBER, UNH, UNP, UPS, URA, USB, V, VCR, VDC, VGT, VHT, VOX, VPU, VRP, VRTX, VST, VZ, WHR, WMT,
WSM, WTRG, XOM, XTL, XTN
```

133 symbols total (up from 112 -- confirmed the queue grows every time this todo is refreshed,
tracking the same "don't be stingy" sweep as it kept finding real gaps). This list will shift as
client-id 41's in-flight fetch (20 original migration-287 symbols) completes more names --
re-verify the zero-row set immediately before launching, don't trust this snapshot at execution
time. NEM dropped off the queue since the last refresh (client-id 41 completed it).

## Action needed

Once client-id 41 finishes (currently running, started 2026-08-05 06:05, ~20 symbols), launch
one consolidated backfill for the remaining zero-row set using a fresh client-id (43, not
reusing 35/40/41/42):

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

**Session note (2026-08-05):** the universe went from 111 to 229 active instruments in one
sitting (roughly 2x). Stopping point reached deliberately -- confirmed with the user that
further equity sweeps have hit diminishing returns, and more symbols now increases the
already-large >50% zero-OHLCV-data ratio rather than delivering value. The backfill, not more
symbol coverage, is the actual bottleneck going forward.

## Why this matters

`get_active_contracts()` returns 229 active rows but 133 of them (>55%) have no OHLCV data at
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
- KMI/WMB (Kinder Morgan / Williams Companies) -- proposed as a second midstream single name
  to complement EPD, never confirmed or added. Low priority given EPD + AMLP already exist.
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
