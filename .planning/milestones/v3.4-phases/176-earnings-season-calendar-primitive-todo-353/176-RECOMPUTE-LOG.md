# Phase 176 Plan 07: Earnings-Season Corpus Backfill — Recompute Log

Operational evidence for the migration-351 backfill of `feature_vectors.earnings_season_flag`
and `days_since_quarter_end` (plans 176-07 Task 1 pre-flight, Task 2 run telemetry, Task 3
coverage verification + `COVERED_SCOPE` manifest). Written as the work happened; nothing here
is projected from a plan — every number was observed against the live database on 2026-09-23.

---

## Task 1: Pre-flight gate (2026-09-23, ~13:45-14:00 UTC)

All five checks observed before anything was written. Any failure would have aborted the plan.

### Check 1 — competing corpus processes

```
$ ps aux | grep -E "backfill_feature_factory|ic_engine|regime_writer|forward_return_writer" | grep -v grep
(no output — exit 1 from grep = zero matches)
```

The todo-340 `--compute-only --symbols IHF --workers 1` run that was active at plan time
(2026-09-22 16:45) has exited. No corpus job owns `feature_vectors`.

### Check 2 — lock / chunk-operation check

```
SELECT pid, state, wait_event_type, wait_event, ... FROM pg_stat_activity
WHERE state <> 'idle' AND (query ILIKE '%decompress_chunk%' OR query ILIKE '%compress_chunk%'
  OR query ILIKE '%autovacuum%' OR ...hyper/feature_vectors...);
→ 0 rows

SELECT ... FROM pg_stat_activity WHERE backend_type = 'autovacuum worker'
  OR (state = 'active' AND now() - query_start > interval '5 minutes');
→ 0 rows

SELECT ... FROM pg_locks l JOIN pg_stat_activity a ... WHERE relation = feature_vectors
  OR relation IN (all 86 chunk regclasses);
→ 0 rows (no session holds any lock on the hypertable or any chunk)
```

No `decompress_chunk`/`compress_chunk`/autovacuum activity against `feature_vectors` (RESEARCH.md
Pitfall 5's 2026-09-22 contention window has fully cleared), no long-running queries, no lock
holders.

### Check 3 — schema and APR seed preconditions

```
information_schema.columns, feature_vectors:
  days_since_quarter_end | real | nullable YES
  earnings_season_flag   | real | nullable YES      (both exist — migration 350 landed)

config_state:
  feature.earnings_season.start_days = '14'   (text, castable to int)
  feature.earnings_season.end_days   = '42'   (text, castable to int)
```

Both APR values read at run time: **start_days = 14, end_days = 42**; `14 <= 42` so the window is
non-empty. The SQL reads these from `config_state` inside the statement (contract test forbids a
bare 14/42 literal), so an operator APR change between pre-flight and a future re-run is honored
by design.

### Check 4 — disk headroom (measured, not assumed)

Relation size (the parent-relation call returns 24 kB because data lives in chunks, so the
hypertable-level figure is the real one):

```
hypertable_size('feature_vectors') = 82,292,506,624 bytes (77 GB)   [== hypertable_approximate_size]
86 chunks, 86 compressed, 0 uncompressed (range 2005-09-24 → 2026-12-03)

Data filesystem (docker exec timescaledb df -h /var/lib/postgresql):
  /dev/mapper/ubuntu--vg-ubuntu--lv  913.3G total  335.1G used  540.1G avail  38% used
```

Gate arithmetic: required = 2.5 × 77 GB ≈ **193 GB**; available = **540.1 GB** → PASS.

Beyond the plan's 2.5x gate, the decompressed-heap footprint itself was probed rather than
estimated (the table is ~4.1x the row count it had at the migration-312 incident, so the 57 GB
prior does not transfer directly): decompressed the smallest chunk
(`_hyper_85_75954_chunk`, 2005 Q4, 30,969 rows), measured, recompressed it, and ran a bare
`VACUUM feature_vectors;` to leave the probe without residue:

```
decompressed chunk total relation: 43,819,008 bytes / 30,969 rows = 1,415 bytes/row (heap+index+toast)
post-recompress uncompressed chunk count: 0; hypertable size back to 77 GB
```

Extrapolated cost of the whole-table form on the live 108,639,338 rows:

| Phase | Δ disk | Free space after |
|---|---|---|
| decompress all chunks | +~154 GB (108.6M × 1,415 B) | ~386 GB |
| UPDATE rewrites every row (dead + new versions coexist) | +~154 GB worst case | ~232 GB |
| recompress + bare VACUUM reclaims dead tuples | −~154 GB | ~380 GB+ |

**Decision: whole-table form** (not the batched fallback). The plan's 2.5x gate passes
(540 > 193 GB) and the measured worst-case floor (~232 GB free at peak, >10x the 20 GB abort
line) makes batching unnecessary schedule risk. Batching changes the schedule, not the scope;
it stays documented here as the fallback if a re-run ever faces less headroom.

### Check 5 — baseline

```
count(*)                                       = 108,639,338
count(*) FILTER (earnings_season_flag IS NULL)     = 108,639,338
count(*) FILTER (days_since_quarter_end IS NULL)   = 108,639,338
```

Every row in the corpus is this backfill's responsibility (both columns were added as NULL by
migration 350; plan 176-03 only wired new-row compute). Row note: the plan's objective text
estimated "~40M rows"; the live corpus is 108.6M — the Phase 174-era universe expansion
(233 symbols present in `feature_vectors`) grew it since planning. Scope is whatever the table
holds, not the estimate. Per-tf breakdown: 5m = 75,051,415; 15m = 25,659,325; 1h = 6,961,503;
1d = 967,095.

### Artifacts written in Task 1

- `production/migrations/351_earnings_season_backfill.sql` — four-step round trip (APR guard →
  decompress → scoped two-column UPDATE → recompress → bare VACUUM), idempotent via
  `IS DISTINCT FROM` scoping, window bounds read from `config_state` at run time, temporary
  `_m351_*` SQL helpers written once and dropped in-transaction
- `tests/unit/test_earnings_season_backfill_contract.py` — 8 source-level assertions including
  the structural two-column SET-list parse (T-176-07-03's proof), no 14/42 literals, bare
  top-level VACUUM, `if_compressed => true`, idempotency scoping, RAISE EXCEPTION guard,
  explicit UTC cast
- TDD gates: RED commit `519e3cd70` (8/8 failing), GREEN after the migration landed (8/8 +
  `test_compressed_hypertable_migration_vacuum_check.py` all passing)

## Task 2: Round trip execution (2026-09-23), interrupted by a power loss and completed in recovery

### What happened

Migration 351 was started after the Task 1 pre-flight (~14:00 UTC). Steps 0-2 (APR guard,
decompress all chunks, scoped two-column UPDATE) ran inside one transaction, and that
transaction **committed**. A site power outage then rebooted the server (~17:40 UTC) during
step 3 (recompress, which runs outside the transaction). Postgres crash recovery kept the
committed UPDATE; 37 of 86 chunks were left uncompressed and the step-4 VACUUM never ran.

The original run's in-flight telemetry (psql output, the wall-clock pair, disk and
`wait_event` samples) was written under `/tmp` and was lost with the reboot (tmpfs). **Not
recorded and not reconstructable:** original start/end timestamps, elapsed seconds, the
psql-reported rows-updated figure, and the peak-disk trajectory during decompress/UPDATE.
Postgres came back clean after the reboot (both TimescaleDB containers healthy, no ENOSPC in
the run's aftermath), but the minimum free disk reached during the run is unknown. The
cost-measurement goal of this task (replacing the stale 16,432s prior) is therefore **not met**
by this run; treat the round trip's cost as still unmeasured.

### Recovery (concurrent session indicagent-62, 18:07-18:37 UTC)

Completed steps 3 and 4 by hand: TimescaleDB's columnstore policy job plus a manual
`compress_chunk()` over the remaining pre-2026 chunks, and two bare `VACUUM feature_vectors;`
passes. Telemetry from that session's recovery log:

```
18:07:23 uncompressed=35 free= 413G
18:09:23 uncompressed=30 free= 434G
18:11:23 uncompressed=24 free= 458G
18:13:24 uncompressed=18 free= 479G
18:14:24 policy done; 16 still uncompressed (13 pre-2026 + 3 in 2026)
18:14:24 VACUUM start, free= 486G
18:34:00 VACUUM exit=0 free= 486G
18:34:17 manual compress of the 13 pre-2026 chunks
18:37:00 compress done; uncompressed=3
18:37:01 VACUUM2 exit=0 free= 518G
```

Post-recovery state: 83 compressed / 3 uncompressed chunks; free disk 518 GB (vs 540.1 GB
pre-run, with the concurrent OHLCV catch-up backfill also writing); the temporary `_m351_*`
helper functions are absent from `pg_proc` (the committed transaction dropped them).

**Deviation (uncompressed chunk count):** the acceptance criterion expects 0 uncompressed
chunks. The 3 remaining are the 2026-03-08, 2026-06-06 and 2026-09-04 chunks, all inside the
policy's `compress_after = 6 mons` window, so the columnstore policy will not compress them, and
the live `feature_vector_writer` targets the newest one. Leaving them uncompressed is the
policy's steady state, not a leftover of the round trip. (Task 1 recorded 86/86 compressed
pre-run; those three had been compressed manually at some earlier point.)

### Idempotency check (deviation: predicate count instead of a full re-run)

Re-running migration 351 unchanged is not cheap, as the plan assumed: step 1 unconditionally
decompresses every compressed chunk (~154 GB of heap per Task 1's probe), then step 3
recompresses and step 4 VACUUMs, all before the no-op UPDATE matters. Instead the UPDATE's own
WHERE predicate was evaluated as a count, using session-temporary copies of the two helper
functions (`pg_temp`, identical bodies) and the same `config_state` lookup:

```
count(*) FILTER (WHERE days_since_quarter_end IS DISTINCT FROM dsq(bar_ts)
                    OR earnings_season_flag IS DISTINCT FROM esf(bar_ts, start_days, end_days)) = 0
```

over all 108,639,338 rows (scan 21:03:38-21:15:45 UTC, 12m07s, no other query on
`feature_vectors`). Zero rows satisfy the predicate, so a re-run would update zero rows. This
is the same claim, measured without the round trip.

### Acceptance

- NULL `earnings_season_flag` or `days_since_quarter_end` rows: **0** of 108,639,338
- Rows the UPDATE predicate would still touch: **0**
- Row count unchanged from the Task 1 baseline (108,639,338)

## Task 3: Coverage verification

### Collateral-damage check

No checksum apparatus is needed: the executed statement's SET list names exactly
`days_since_quarter_end` and `earnings_season_flag`, which
`tests/unit/test_earnings_season_backfill_contract.py` asserts by parsing the SET clause, so no
other column was addressable. Cheap confirmation (corpus-wide, against the 108,639,338 baseline):

| column | non-NULL rows | fully-NULL symbols |
|---|---|---|
| `regime` | 31,204,768 | BIL, EMLC, ETHA, IBIT, VIXY |
| `regime_volatility` | 31,004,453 | BIL, EMLC, ETHA, VIXY, VRP |

The fully-NULL `regime` set is identical to the `regime_coverage_auditor` run of 2026-09-23
06:00 UTC (pre-migration: "feature_vectors.regime is 100% NULL for these symbols"), so the
partial `regime` coverage predates this migration. No pre-run `regime_volatility` snapshot
exists to compare against; the SET-list proof is what covers that column. Plan 176-04's
per-symbol pass reads `regime_volatility`, so its sub-cells for VRP/BIL/EMLC/ETHA/VIXY will be
empty by construction.

### Verification 1: coverage

932 (symbol, tf) pairs, 233 symbols x 4 tfs (5m, 15m, 1h, 1d). Aggregate coverage **100.0%**
(108,639,338 / 108,639,338). Pairs below 100%: **none**. Per-symbol table in the appendix.

### Verification 2: the flag is not constant

`count(DISTINCT earnings_season_flag)` is 2 corpus-wide, and 2 for **all 233** symbols on
`1d` (and for every one of the 932 pairs).

### Verification 3: agreement with 176-01's pure classifier

20 rows sampled (seeded RNG, random (symbol, tf) and random bar_ts 2006-2026) and checked
against `days_since_quarter_end` / `is_earnings_season` from
`scripts/analysis/earnings_season_conditional_ic_reverification.py`, bounds read from
`config_state` (14/42). **20/20 agree**, spanning **18 distinct quarters**, including a
quarter-end day (MTUM 5m 2016-06-30, dsq 0, flag 0) and a Dec 30 day (GOOGL 1d 2024-12-30,
dsq 91).

### Verification 4: in-season fraction per tf

| tf | rows | avg(earnings_season_flag) |
|---|---|---|
| 5m | 75,051,415 | 0.3275 |
| 15m | 25,659,325 | 0.3264 |
| 1h | 6,961,503 | 0.3269 |
| 1d | 967,095 | 0.3253 |

All inside the 0.25-0.40 band, close to the expected 29/91 = 0.319.

## COVERED_SCOPE

```
COVERED_SCOPE_SYMBOLS=AA,AAPL,ADM,AEP,AGG,AMD,AMLP,AMT,AMZN,ARKK,ASML,AVGO,AWK,AXP,BA,BAC,BHP,BIL,BKNG,BLK,BNTX,BTAL,CAT,CCJ,CIBR,CMCSA,COIN,COP,COST,CRM,CRSP,CRWD,CSX,CTVA,CVS,CVX,CWB,DAL,DBA,DBB,DBC,DD,DE,DHI,DIA,DIS,DOCS,DOW,DUK,ECL,EDV,EEM,EFA,ELV,EMB,EMLC,EMR,ENPH,EPD,EQIX,ETHA,ETR,EWG,EWJ,EWT,EWY,EWZ,EXEL,EZU,F,FCX,FDX,FSLR,FXA,FXC,FXE,FXI,FXY,GDX,GE,GEV,GILD,GLD,GM,GOOGL,GS,HCA,HD,HON,HYD,HYG,IBB,IBIT,ICLN,IEF,IGV,IHF,INDA,IPO,ISRG,ITA,ITB,IWM,IYT,IYZ,JBHT,JETS,JNJ,JPM,KMI,KO,KRE,KWEB,LEN,LIN,LLY,LMT,LQD,MARA,MCD,MCHI,META,MMM,MO,MOO,MRK,MS,MSFT,MSTR,MTUM,MUB,NAD,NEE,NEM,NFLX,NLY,NTR,NUE,NVDA,NVR,ODFL,OIH,OXY,PANW,PEP,PFE,PFF,PG,PGR,PLD,PM,PPLT,QCOM,QQQ,QUAL,R,REGN,RIOT,RSP,RSPG,RSPU,RTX,RVMD,SCHD,SDOG,SHW,SHY,SLB,SLV,SMH,SO,SPG,SPHB,SPY,STIP,T,TDOC,THC,TIP,TLT,TMUS,TOL,TRV,TSLA,TSM,UBER,UNH,UNP,UPS,URA,USB,USMV,UUP,V,VCR,VDC,VGT,VHT,VIXY,VNQ,VOX,VPU,VRP,VRTX,VST,VTV,VUG,VWO,VYM,VZ,WHR,WMB,WMT,WSM,WTRG,XBI,XHB,XLB,XLC,XLE,XLF,XLI,XLK,XLP,XLRE,XLU,XLV,XLY,XOM,XOP,XRT,XTL,XTN
COVERED_SCOPE_TFS=5m,15m,1h,1d
COVERED_SCOPE_N_SYMBOLS=233
COVERED_SCOPE_N_PAIRS=932
COVERED_SCOPE_ROWS=108639338
COVERED_SCOPE_MAX_BAR_TS=2026-09-18T19:55:00Z
```

Symbols are derived from `SELECT DISTINCT symbol FROM feature_vectors`, and every pair is at
100% coverage. The instruments equity filter returns a 273-symbol superset; the 40 extra have
zero `feature_vectors` rows and are not in scope.

The gate verdict is entitled to claim: **measured over 233 symbols x 4 tfs (5m/15m/1h/1d),
108,639,338 rows, bar_ts through 2026-09-18 19:55 UTC.** Rows written after this manifest are
populated at compute time by plan 176-03's wiring, not by this backfill; 176-08 should re-check
`count(*) WHERE earnings_season_flag IS NULL` = 0 at its own pre-flight rather than rely on this
snapshot.

## Appendix: per-symbol row counts (all 100% covered)

| symbol | 5m rows | 15m rows | 1h rows | 1d rows | coverage |
|---|---|---|---|---|---|
| AA | 190,889 | 63,494 | 16,912 | 2,211 | 100% |
| AAPL | 392,519 | 130,393 | 35,518 | 4,875 | 100% |
| ADM | 392,658 | 129,984 | 36,569 | 4,776 | 100% |
| AEP | 392,648 | 129,985 | 36,573 | 4,776 | 100% |
| AGG | 388,948 | 129,761 | 29,779 | 4,776 | 100% |
| AMD | 226,514 | 75,300 | 20,092 | 2,664 | 100% |
| AMLP | 311,265 | 103,710 | 23,808 | 3,759 | 100% |
| AMT | 392,738 | 129,997 | 36,573 | 4,776 | 100% |
| AMZN | 392,638 | 130,004 | 36,579 | 4,777 | 100% |
| ARKK | 179,464 | 62,097 | 15,056 | 2,697 | 100% |
| ASML | 391,862 | 129,998 | 36,571 | 4,774 | 100% |
| AVGO | 205,292 | 68,239 | 18,191 | 2,391 | 100% |
| AWK | 357,302 | 118,927 | 31,844 | 4,351 | 100% |
| AXP | 392,389 | 130,347 | 35,444 | 4,865 | 100% |
| BA | 392,377 | 130,344 | 35,444 | 4,865 | 100% |
| BAC | 392,665 | 129,984 | 36,569 | 4,776 | 100% |
| BHP | 392,654 | 129,985 | 36,569 | 4,776 | 100% |
| BIL | 330,699 | 122,218 | 28,752 | 4,601 | 100% |
| BKNG | 382,956 | 129,647 | 36,583 | 4,777 | 100% |
| BLK | 383,128 | 129,989 | 36,571 | 4,776 | 100% |
| BNTX | 131,434 | 44,117 | 11,715 | 1,464 | 100% |
| BTAL | 110,488 | 51,011 | 15,118 | 3,154 | 100% |
| CAT | 392,541 | 130,346 | 35,444 | 4,865 | 100% |
| CCJ | 384,807 | 117,123 | 31,358 | 4,773 | 100% |
| CIBR | 192,455 | 69,725 | 16,436 | 2,536 | 100% |
| CMCSA | 392,637 | 130,057 | 36,579 | 4,777 | 100% |
| COIN | 103,704 | 34,387 | 9,075 | 1,085 | 100% |
| COP | 384,909 | 117,149 | 31,361 | 4,773 | 100% |
| COST | 392,866 | 130,003 | 36,579 | 4,777 | 100% |
| CRM | 384,902 | 117,149 | 31,361 | 4,773 | 100% |
| CRSP | 186,788 | 63,291 | 16,919 | 2,211 | 100% |
| CRWD | 139,654 | 46,373 | 12,299 | 1,548 | 100% |
| CSX | 207,440 | 68,941 | 18,380 | 2,420 | 100% |
| CTVA | 132,753 | 33,843 | 7,175 | 1,560 | 100% |
| CVS | 384,896 | 117,146 | 31,361 | 4,773 | 100% |
| CVX | 392,388 | 130,346 | 35,444 | 4,865 | 100% |
| CWB | 313,771 | 110,875 | 25,792 | 4,101 | 100% |
| DAL | 376,745 | 112,531 | 29,115 | 4,600 | 100% |
| DBA | 367,977 | 127,031 | 29,204 | 4,671 | 100% |
| DBB | 259,209 | 114,230 | 29,025 | 4,671 | 100% |
| DBC | 388,898 | 130,477 | 29,948 | 4,793 | 100% |
| DD | 172,208 | 57,237 | 15,226 | 1,993 | 100% |
| DE | 392,371 | 130,346 | 35,444 | 4,865 | 100% |
| DHI | 384,904 | 117,149 | 31,361 | 4,773 | 100% |
| DIA | 392,292 | 129,043 | 30,007 | 4,807 | 100% |
| DIS | 392,389 | 130,347 | 35,444 | 4,865 | 100% |
| DOCS | 92,037 | 20,251 | 3,517 | 1,035 | 100% |
| DOW | 136,420 | 35,050 | 7,499 | 1,606 | 100% |
| DUK | 384,984 | 117,162 | 31,355 | 4,776 | 100% |
| ECL | 384,827 | 117,146 | 31,361 | 4,773 | 100% |
| EDV | 237,255 | 101,675 | 26,688 | 4,411 | 100% |
| EEM | 392,364 | 130,625 | 29,978 | 4,809 | 100% |
| EFA | 392,368 | 130,624 | 29,977 | 4,808 | 100% |
| ELV | 384,834 | 117,142 | 31,363 | 4,776 | 100% |
| EMB | 338,484 | 116,579 | 27,467 | 4,433 | 100% |
| EMLC | 296,160 | 103,962 | 27,985 | 3,808 | 100% |
| EMR | 384,889 | 117,146 | 31,361 | 4,773 | 100% |
| ENPH | 275,286 | 93,518 | 25,093 | 3,384 | 100% |
| EPD | 392,591 | 129,982 | 36,569 | 4,776 | 100% |
| EQIX | 389,928 | 129,996 | 36,579 | 4,777 | 100% |
| ETHA | 39,736 | 13,064 | 3,337 | 262 | 100% |
| ETR | 392,639 | 129,982 | 36,569 | 4,776 | 100% |
| EWG | 390,412 | 130,567 | 29,972 | 4,798 | 100% |
| EWJ | 391,861 | 130,457 | 29,940 | 4,803 | 100% |
| EWT | 391,690 | 130,449 | 29,942 | 4,803 | 100% |
| EWY | 391,647 | 130,457 | 29,940 | 4,803 | 100% |
| EWZ | 391,844 | 130,452 | 29,940 | 4,794 | 100% |
| EXEL | 392,658 | 129,992 | 36,578 | 4,777 | 100% |
| EZU | 373,205 | 129,779 | 29,965 | 4,798 | 100% |
| F | 392,677 | 129,984 | 36,569 | 4,776 | 100% |
| FCX | 392,390 | 130,347 | 35,444 | 4,865 | 100% |
| FDX | 392,646 | 129,981 | 36,569 | 4,776 | 100% |
| FSLR | 384,945 | 128,146 | 34,330 | 4,708 | 100% |
| FXA | 184,584 | 89,436 | 27,335 | 4,795 | 100% |
| FXC | 203,305 | 100,564 | 33,821 | 4,776 | 100% |
| FXE | 322,939 | 124,534 | 29,893 | 4,798 | 100% |
| FXI | 392,082 | 130,549 | 29,963 | 4,796 | 100% |
| FXY | 276,949 | 116,535 | 28,947 | 4,648 | 100% |
| GDX | 393,624 | 130,851 | 35,234 | 4,808 | 100% |
| GE | 392,550 | 129,982 | 36,561 | 4,773 | 100% |
| GEV | 45,938 | 15,132 | 3,894 | 342 | 100% |
| GILD | 392,853 | 129,999 | 36,579 | 4,777 | 100% |
| GLD | 396,080 | 131,501 | 35,758 | 4,833 | 100% |
| GM | 306,916 | 102,102 | 27,311 | 3,701 | 100% |
| GOOGL | 392,843 | 129,990 | 36,589 | 4,776 | 100% |
| GS | 392,676 | 129,986 | 36,569 | 4,776 | 100% |
| HCA | 300,988 | 100,144 | 26,785 | 3,625 | 100% |
| HD | 392,681 | 129,986 | 36,569 | 4,776 | 100% |
| HON | 392,393 | 130,348 | 35,444 | 4,865 | 100% |
| HYD | 299,175 | 109,322 | 30,173 | 4,152 | 100% |
| HYG | 364,456 | 124,081 | 33,619 | 4,611 | 100% |
| IBB | 347,872 | 116,206 | 31,142 | 4,242 | 100% |
| IBIT | 50,153 | 16,549 | 3,665 | 391 | 100% |
| ICLN | 212,885 | 92,407 | 30,457 | 4,307 | 100% |
| IEF | 176,022 | 58,513 | 15,572 | 2,011 | 100% |
| IGV | 328,279 | 125,340 | 35,637 | 4,809 | 100% |
| IHF | 226,711 | 109,402 | 34,958 | 4,803 | 100% |
| INDA | 245,321 | 82,627 | 22,196 | 2,965 | 100% |
| IPO | 101,328 | 51,676 | 16,198 | 2,961 | 100% |
| ISRG | 390,644 | 129,994 | 36,579 | 4,777 | 100% |
| ITA | 292,175 | 117,001 | 34,630 | 4,808 | 100% |
| ITB | 380,422 | 129,320 | 35,137 | 4,776 | 100% |
| IWM | 394,059 | 130,862 | 35,632 | 4,807 | 100% |
| IYT | 374,310 | 130,081 | 29,941 | 4,794 | 100% |
| IYZ | 374,178 | 129,572 | 36,503 | 4,771 | 100% |
| JBHT | 392,522 | 130,003 | 36,579 | 4,777 | 100% |
| JETS | 161,409 | 62,997 | 19,166 | 2,584 | 100% |
| JNJ | 392,391 | 130,347 | 35,444 | 4,865 | 100% |
| JPM | 392,394 | 130,348 | 35,444 | 4,865 | 100% |
| KMI | 302,450 | 100,619 | 26,912 | 3,643 | 100% |
| KO | 392,550 | 130,348 | 35,444 | 4,865 | 100% |
| KRE | 379,995 | 128,391 | 34,883 | 4,808 | 100% |
| KWEB | 223,328 | 79,816 | 22,174 | 3,013 | 100% |
| LEN | 392,671 | 129,986 | 36,569 | 4,776 | 100% |
| LIN | 151,443 | 50,307 | 13,367 | 1,700 | 100% |
| LLY | 392,664 | 129,985 | 36,569 | 4,776 | 100% |
| LMT | 392,649 | 129,986 | 36,569 | 4,776 | 100% |
| LQD | 387,220 | 129,985 | 35,390 | 4,776 | 100% |
| MARA | 193,960 | 72,501 | 20,585 | 2,775 | 100% |
| MCD | 392,370 | 130,341 | 35,443 | 4,865 | 100% |
| MCHI | 205,126 | 68,238 | 15,585 | 2,390 | 100% |
| META | 277,534 | 92,310 | 24,680 | 3,324 | 100% |
| MMM | 392,391 | 130,347 | 35,444 | 4,865 | 100% |
| MO | 392,667 | 129,985 | 36,569 | 4,776 | 100% |
| MOO | 288,006 | 115,296 | 32,878 | 4,510 | 100% |
| MRK | 392,474 | 130,374 | 35,504 | 4,873 | 100% |
| MS | 392,667 | 129,985 | 36,569 | 4,776 | 100% |
| MSFT | 392,871 | 130,003 | 36,579 | 4,777 | 100% |
| MSTR | 347,381 | 127,542 | 36,569 | 4,777 | 100% |
| MTUM | 225,368 | 80,250 | 22,551 | 3,091 | 100% |
| MUB | 344,489 | 121,796 | 32,935 | 4,506 | 100% |
| NAD | 294,623 | 119,797 | 36,433 | 4,776 | 100% |
| NEE | 314,956 | 104,767 | 28,032 | 3,803 | 100% |
| NEM | 392,379 | 130,344 | 35,444 | 4,865 | 100% |
| NFLX | 392,635 | 129,967 | 36,564 | 4,775 | 100% |
| NLY | 392,669 | 129,986 | 36,573 | 4,776 | 100% |
| NTR | 167,802 | 55,742 | 14,826 | 1,910 | 100% |
| NUE | 392,386 | 130,346 | 35,443 | 4,865 | 100% |
| NVDA | 392,874 | 130,004 | 36,579 | 4,777 | 100% |
| NVR | 332,263 | 125,697 | 36,445 | 4,776 | 100% |
| ODFL | 55,370 | 27,394 | 8,957 | 314 | 100% |
| OIH | 284,963 | 94,977 | 25,395 | 3,422 | 100% |
| OXY | 392,656 | 129,983 | 36,569 | 4,776 | 100% |
| PANW | 274,092 | 91,212 | 24,384 | 3,281 | 100% |
| PEP | 168,351 | 55,925 | 14,875 | 1,917 | 100% |
| PFE | 392,648 | 129,979 | 36,566 | 4,776 | 100% |
| PFF | 176,035 | 58,512 | 15,573 | 2,012 | 100% |
| PG | 392,394 | 130,348 | 35,444 | 4,865 | 100% |
| PGR | 392,548 | 130,038 | 36,569 | 4,776 | 100% |
| PLD | 296,424 | 98,605 | 26,369 | 3,566 | 100% |
| PM | 359,459 | 119,611 | 32,028 | 4,377 | 100% |
| PPLT | 235,241 | 100,288 | 24,711 | 3,917 | 100% |
| QCOM | 392,878 | 130,006 | 36,580 | 4,777 | 100% |
| QQQ | 394,264 | 130,896 | 35,692 | 4,809 | 100% |
| QUAL | 221,329 | 80,163 | 22,443 | 3,029 | 100% |
| R | 387,711 | 129,933 | 36,569 | 4,776 | 100% |
| REGN | 391,497 | 129,919 | 36,562 | 4,776 | 100% |
| RIOT | 221,145 | 81,049 | 23,042 | 3,174 | 100% |
| RSP | 390,507 | 130,816 | 35,585 | 4,806 | 100% |
| RSPG | 162,669 | 81,976 | 28,870 | 4,667 | 100% |
| RSPU | 111,738 | 67,545 | 26,948 | 4,551 | 100% |
| RTX | 392,646 | 129,992 | 36,571 | 4,776 | 100% |
| RVMD | 124,635 | 41,969 | 11,118 | 1,377 | 100% |
| SCHD | 282,902 | 95,983 | 25,695 | 3,465 | 100% |
| SDOG | 202,546 | 86,005 | 20,951 | 3,294 | 100% |
| SHW | 392,318 | 129,977 | 36,567 | 4,776 | 100% |
| SHY | 177,706 | 59,085 | 15,727 | 2,032 | 100% |
| SLB | 392,641 | 129,979 | 36,567 | 4,776 | 100% |
| SLV | 393,659 | 130,855 | 35,350 | 4,806 | 100% |
| SMH | 285,424 | 95,017 | 25,404 | 3,423 | 100% |
| SO | 392,647 | 129,979 | 36,567 | 4,776 | 100% |
| SPG | 392,619 | 129,978 | 36,567 | 4,776 | 100% |
| SPHB | 212,622 | 87,234 | 22,167 | 3,574 | 100% |
| SPY | 392,374 | 130,632 | 30,017 | 4,803 | 100% |
| STIP | 213,412 | 88,814 | 26,857 | 3,691 | 100% |
| T | 392,640 | 129,976 | 36,017 | 4,776 | 100% |
| TDOC | 215,688 | 72,065 | 19,224 | 2,541 | 100% |
| THC | 392,558 | 129,978 | 36,571 | 4,776 | 100% |
| TIP | 392,797 | 130,842 | 35,588 | 4,805 | 100% |
| TLT | 205,262 | 68,255 | 18,196 | 2,389 | 100% |
| TMUS | 210,416 | 109,232 | 29,234 | 3,978 | 100% |
| TOL | 392,618 | 129,977 | 36,567 | 4,776 | 100% |
| TRV | 379,914 | 126,480 | 33,874 | 4,640 | 100% |
| TSLA | 310,253 | 104,782 | 28,002 | 3,800 | 100% |
| TSM | 392,646 | 129,978 | 36,566 | 4,776 | 100% |
| UBER | 141,354 | 46,940 | 12,453 | 1,570 | 100% |
| UNH | 392,528 | 130,032 | 36,567 | 4,776 | 100% |
| UNP | 392,523 | 129,979 | 36,567 | 4,776 | 100% |
| UPS | 392,527 | 129,975 | 36,559 | 4,774 | 100% |
| URA | 262,762 | 99,254 | 27,372 | 3,709 | 100% |
| USB | 392,525 | 129,974 | 36,559 | 4,774 | 100% |
| USMV | 271,619 | 92,795 | 25,257 | 3,458 | 100% |
| UUP | 352,493 | 123,258 | 28,725 | 4,640 | 100% |
| V | 359,208 | 119,583 | 32,017 | 4,373 | 100% |
| VCR | 288,006 | 121,524 | 36,004 | 4,773 | 100% |
| VDC | 323,019 | 126,664 | 36,462 | 4,773 | 100% |
| VGT | 371,929 | 128,845 | 36,509 | 4,773 | 100% |
| VHT | 347,430 | 127,766 | 36,559 | 4,773 | 100% |
| VIXY | 264,631 | 96,043 | 26,855 | 3,695 | 100% |
| VNQ | 390,419 | 130,793 | 35,614 | 4,806 | 100% |
| VOX | 290,969 | 121,384 | 36,089 | 4,773 | 100% |
| VPU | 340,836 | 126,731 | 36,477 | 4,773 | 100% |
| VRP | 210,604 | 77,577 | 21,211 | 2,834 | 100% |
| VRTX | 392,354 | 129,914 | 36,550 | 4,773 | 100% |
| VST | 186,186 | 62,766 | 16,899 | 2,221 | 100% |
| VTV | 386,369 | 130,427 | 29,971 | 4,806 | 100% |
| VUG | 387,323 | 130,585 | 35,600 | 4,807 | 100% |
| VWO | 391,246 | 130,582 | 29,972 | 4,797 | 100% |
| VYM | 348,235 | 122,718 | 29,218 | 4,707 | 100% |
| VZ | 392,451 | 129,943 | 36,552 | 4,774 | 100% |
| WHR | 392,238 | 129,938 | 36,551 | 4,774 | 100% |
| WMB | 392,422 | 129,936 | 36,550 | 4,774 | 100% |
| WMT | 392,450 | 129,943 | 36,552 | 4,773 | 100% |
| WSM | 392,348 | 129,939 | 36,552 | 4,774 | 100% |
| WTRG | 392,301 | 129,941 | 36,552 | 4,773 | 100% |
| XBI | 359,154 | 126,441 | 35,292 | 4,807 | 100% |
| XHB | 392,218 | 130,760 | 35,645 | 4,807 | 100% |
| XLB | 394,010 | 130,858 | 35,632 | 4,807 | 100% |
| XLC | 158,422 | 52,783 | 14,035 | 1,792 | 100% |
| XLE | 394,062 | 130,861 | 35,633 | 4,807 | 100% |
| XLF | 394,038 | 130,858 | 35,633 | 4,807 | 100% |
| XLI | 393,936 | 130,857 | 35,631 | 4,807 | 100% |
| XLK | 394,034 | 130,858 | 35,632 | 4,807 | 100% |
| XLP | 393,921 | 130,850 | 35,602 | 4,807 | 100% |
| XLRE | 195,952 | 66,083 | 18,089 | 2,462 | 100% |
| XLU | 392,280 | 130,601 | 29,972 | 4,805 | 100% |
| XLV | 392,208 | 130,604 | 29,975 | 4,805 | 100% |
| XLY | 393,755 | 130,854 | 35,626 | 4,805 | 100% |
| XOM | 392,425 | 129,935 | 36,551 | 4,773 | 100% |
| XOP | 373,244 | 127,104 | 34,790 | 4,804 | 100% |
| XRT | 381,482 | 128,891 | 34,929 | 4,801 | 100% |
| XTL | 43,706 | 30,598 | 16,670 | 3,512 | 100% |
| XTN | 115,625 | 65,022 | 24,011 | 3,620 | 100% |
