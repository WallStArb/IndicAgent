# 1d primary swap: Tradier to IBKR SMART, evidence

**Author:** Claude (Opus 5.5), 2026-10-07, at Brandon's request (plan 185-46 Task 2)
**Status:** measured 2026-10-07 (rules pre-registered in 40c1a2402; results below); 185-47 reruns
`--classify` after 189-10 Task 1b
**Informed by:** docs/plans/2026-10-06-data-layer-integrity-design.md; summaries of plans 185-33, 185-36,
185-38 and 185-41; owner decision 2026-10-07 (Tradier will not be funded, 1d primary moves to IBKR; D-01)

Plan 185-46 measures and prepares; 185-47 applies the swap; 185-48 retires the Tradier loader. This
document fixes the rules that judge 185-47 before any number below exists, then records the
measurements (request rate, nightly cost, volume basis, per-name classes) that 185-47 and 189-10 read.
The Tradier daily timer was disabled on 2026-10-07; the freeze point is the last Tradier bar date,
2026-10-06, on all 1,529 active names (last loaded row 2026-10-07 11:52:38 UTC).

## Pre-registered rules

Committed before the measurement script ran against the data. Thresholds named here are APR keys read
at run time; no number in this section is copied into code.

Standing of the Tradier history (owner answer 2026-10-07). Tradier bars dated before D are canonical
history under the dated policy rows and keep their full standing in d2-v2, the verdict gate and the
rebuild. What stops is new Tradier fetching (the account is unfunded), not the use of what was
fetched. The class tests in R2 decide only who owns bars from D on and whether a Tradier head is kept;
they never decide whether pre-D Tradier bars are trusted.

R1, shape F (forward from D). The open 1d default row of bar_source_policy (primary tradier, fallback
ibkr) is closed at D and a new default (primary ibkr, no fallback) opens at D. D is the first NYSE
session after the maximum Tradier observation date (route TRADIER, timeframe 1d) at the time 185-47
runs. Every bar dated before D stays as it is. Stop condition: 185-47 does not run if any Tradier
observation is dated on or after D.

R2, per-name classes. Over the common sessions of a name (date, Tradier close, IBKR SMART TRADES
close), current scale as d2-v2 chooses it (`common_session_closes`), with window_sessions,
tolerance_bp, min_overlap and min_agree_share read from APR
(threshold.bar_integrity.fallback_basis_window_sessions, fallback_basis_tolerance_bp,
tradier_admission_min_overlap_sessions, tradier_admission_min_agree_share):
- Class A: at least one common session exists and the median IBKR/Tradier close ratio over the last
  min(window_sessions, n_common) common sessions is within tolerance_bp of 1.
- Class B: that median is outside tolerance and the 185-38 admission test (`tradier_admission`) over
  the same pairs reports recent_disagrees with at least min_overlap common sessions.
- Class C: otherwise (no common session, or outside tolerance with fewer than min_overlap sessions).
  A name with no SMART TRADES observation yet is class C with reason no_ibkr_yet; 185-47 reruns the
  classification after the one-time IBKR fetch (189-10 Task 1b).

Head candidate. The Tradier head is the run of Tradier dates before IBKR's first SMART TRADES bar. It
is kept only when the median IBKR/Tradier close ratio over the first window_sessions common sessions
from IBKR's first bar is within tolerance_bp of 1; with no common session it is not kept.

R3, what each class gets in 185-47.
- A: no symbol row; the new default applies from D.
- B: a whole-history primary-ibkr symbol row (the existing admission sweep or `--add`). When the head
  candidate keeps the Tradier head, two rows instead: primary tradier before IBKR's first bar, primary
  ibkr from it, so the head is not lost.
- C: a hold row (primary tradier, fallback ibkr, from the name's first observation, open-ended), so no
  IBKR bar is spliced where no seam evidence exists; the name is listed as frozen.

R4, nightly cost bound. The update lane (owner answer 2026-10-07: one request per name per timeframe
for 1d and 5m, short span since the last stored bar, widened by the revision-window overlap required by
the design review) for every active name costs at most 120 minutes a night (half of
infra.backfill.run_budget_minutes). The gap-fill lane has its own budget row in the results and is not
bounded by R4. Above the bound nothing changes here: the figure is carried into 189-10 Task 2's
extrapolation and a todo is filed.

R5, volume basis. The IBKR SMART over Tradier volume ratio is recorded, never rescaled or spliced, and
has no pass line.

R6, apply criteria for 185-47.
- C1: for every class A and C name the dry run shows changed 0 and removed 0, and new bars equal to the
  count of distinct SMART TRADES dates on or after D for class A and 0 for class C.
- C2: class B changes and removals are listed per name with the Tradier head bars lost.
- C3: the four zero-tolerance checks (policy_conformance, lineage_missing, canonical_recompute,
  digest_fresh) have 0 failing names after the apply.
- C4: no (symbol, check) pair goes from pass to fail.
- C5: fail-to-pass transitions are listed.
- C6: the failing-name count of every check is at most its count before.
- C7: freshness_1d failures after the apply are listed with a reason per name (class C, IBKR never
  answered, fetch gap).
- C8: one dry run after the apply shows 0 new, 0 changed, 0 removed.

## Results

Measured 2026-10-07 between 13:25 and 13:32 EDT by
`scripts/research/swap_1d_primary_measure.py --rate --census --volume --classify --out
logs/185-46_measure.json --tsv logs/185-46_classify.tsv` (read-only connection), plus
`scripts/ops/bars/ops_source_policy.py --admission-sweep --report logs/185-46_admission_sweep.tsv`
(dry run, no `--apply`). APR at run time: window_sessions 20, tolerance_bp 10, min_overlap 60,
min_agree_share 0.9, inter_item_pause_s 2.0, run_budget_minutes 240, limiter 200 per 600 s for 1d and
the default 58 per 600 s for 5m.

### Census

| measure | value |
|---|---|
| active names | 1,529 |
| compute_1d names | 1,502 |
| names with Tradier 1d observations | 1,529 (last date 2026-10-06) |
| names with SMART TRADES 1d observations | 1,037 |
| names with no SMART TRADES observation | 492 |
| of those, never asked for IBKR 1d | 475 (473 compute_1d) |
| of those, asked and never answered with bars | 17 |
| late-start names (IBKR first bar more than 7 days after Tradier's) | 647 |
| Tradier bars before IBKR's first bar on those names | 985,615 |
| Tradier-only interior dates inside IBKR's span | 34,266 on 442 names |
| earliest IBKR SMART TRADES bar | 2005-11-21 |
| bar_source_policy 1d | 1 open default (tradier, fallback ibkr, from 1990-01-01); 74 open and 1 closed symbol rows, all primary ibkr, no fallback |

Every plan-time count reproduces exactly. D, by R1, is 2026-10-07 today (the first NYSE session after
2026-10-06); no SMART TRADES observation is dated on or after it yet.

### Request rate

From ohlcv_request, source ibkr, timeframe 1d or 5m, route SMART, TRADES, test callers excluded.
Requests per hour is the median over hours holding at least 50 requests.

| ledger | requests | per hour | hours used | latency mean | median | p90 | no_data | failed |
|---|---|---|---|---|---|---|---|---|
| 1d, all spans | 3,250 | 431 | 7 | 1.93 s | 0.15 s | 1.76 s | 9.0% | 0.2% |
| 1d, spans of at most 10 days (update-lane shape) | 2,798 | 431 | 7 | 1.54 s | 0.15 s | 1.73 s | 0.6% | 0.1% |
| 5m, all spans (about 60-day windows) | 1,012 | none | 0 | 13.98 s | 10.40 s | 34.28 s | 0% | 0% |
| 5m, spans of at most 10 days | 14 | none | 0 | 0.59 s | 0.07 s | 1.89 s | 0% | 0% |

The 1d ledger comes from the historical pipeline, the D1 bootstrap and the venue study, not from the
fetcher, and its busy hours mix SMART with venue routes: counting every IBKR 1d route, the busiest
hours reached 942, 998 and 862 requests, so the SMART-only median of 431 is a floor set by how those
jobs interleaved, not by IBKR. The fetcher's own 1d ceiling is its serial bound, 3,600 / (2.0 s pause
+ 1.54 s latency) = about 1,017 requests an hour, under the 1,200 limiter; the all-route peaks agree
with it. No 5m hour reached 50 requests (latency binds at about 14 s a window). The fetcher log holds
no `run summary:` line (the fetcher prints it to stdout); the journal holds one, the 189-06 smoke run
(7 items, 5m only), so there is no fetcher-run 1d figure yet. 189-10 Task 1b's fetch record supplies
the first.

### Nightly cost (R4)

`nightly_cost_minutes` takes the larger of the pacing bound (names / requests per hour) and the
serial bound (names x (pause + mean latency)). The update lane is one request per name per timeframe;
the revision-window overlap keeps it one short request, so the at-most-10-day latency applies.

| update lane | names | rate used | minutes |
|---|---|---|---|
| 1d at the measured rate | 1,529 | 431 / h | 212.9 |
| 1d at the fetcher bound (serial binds) | 1,529 | 1,200 / h limiter | 90.2 |
| 5m today (names with 5m) | 233 | 348 / h limiter | 40.2 |
| 5m after the 5m drain (compute_1d) | 1,502 | 348 / h limiter | 259.0 |

| update lane total | minutes | R4 bound (120) |
|---|---|---|
| today, fetcher bound | 130.4 | fails |
| today, measured 1d rate | 253.0 | fails |
| after the drain, fetcher bound | 349.2 | fails |
| after the drain, measured 1d rate | 471.8 | fails |

| gap-fill lane, per run (not bounded by R4) | names | minutes |
|---|---|---|
| 1d, one full-depth request per name failing session_coverage | 240 | 15.7 |
| 5m, one 150-day chunk per name failing slot_coverage (lower bound) | 240 | 63.9 |

R4 fails in every case. The 1d update lane alone fits (90 minutes at the fetcher bound); the 5m update
lane does not once every compute_1d name holds 5m, because 5m shares the default 58-per-10-minutes
window. By R4 nothing changes here: the figure is carried into 189-10 Task 2 and todo 505 is filed.
The lever it names is the 5m pacing figure itself: src/providers/ibkr.py records that IBKR's hard
pacing rule binds bars of 30 seconds or less and that bars of a minute or more meet only a soft
slowdown, so a measured 5m ceiling (`infrastructure_ibkr_chunk_and_rate_limit_probe.py
--rate-timeframe 5m --rate-ceilings ...`, then `infra.ibkr.rate_limit_max_requests_by_tf`) is the test, not an assumption.

5m restatement for 189-10 Task 2. Its floor of 10.6 days assumes the whole day is 5m stream time. The
update lane takes a slice each day that grows as names gain 5m: 130 minutes at the start of the drain
and 349 at the end at the fetcher bound, about 240 on average. Deducted per day, the floor becomes
about 12.7 days (11.7 at the starting slice, 14.0 at the ending one), and the 12 to 18 day expectation
becomes about 14.4 to 21.6 days. At the measured 1d rate the average slice is about 362 minutes, the
floor about 14.2 days and the expectation about 16 to 24 days. 189-10 Task 2's "at most 18 days"
criterion is therefore at risk at the upper end unless the 5m pacing figure rises.

### Volume basis (R5)

IBKR SMART over Tradier daily volume, per name the median ratio over common sessions with both volumes
positive (latest observation per vendor and date), on the 1,037 names with SMART TRADES observations.

| window | names | p10 | p50 | p90 | share below 0.5 |
|---|---|---|---|---|---|
| last 250 common sessions | 1,032 | 0.418 | 0.541 | 0.853 | 35.9% |
| full history | 1,032 | 0.585 | 0.758 | 0.935 | 4.1% |

| year | names | p10 | p50 | p90 |
|---|---|---|---|---|
| 2006 | 517 | 0.899 | 0.953 | 1.126 |
| 2008 | 564 | 0.910 | 0.954 | 1.035 |
| 2010 | 620 | 0.891 | 0.941 | 0.999 |
| 2012 | 695 | 0.866 | 0.928 | 1.004 |
| 2013 | 728 | 0.872 | 0.925 | 1.000 |
| 2014 | 752 | 0.735 | 0.839 | 0.960 |
| 2016 | 807 | 0.721 | 0.832 | 0.969 |
| 2018 | 867 | 0.644 | 0.770 | 0.953 |
| 2020 | 917 | 0.538 | 0.700 | 0.929 |
| 2022 | 950 | 0.456 | 0.625 | 0.901 |
| 2024 | 971 | 0.377 | 0.557 | 0.863 |
| 2025 | 1,000 | 0.381 | 0.542 | 0.853 |
| 2026 | 1,008 | 0.421 | 0.539 | 0.826 |

Every year is in logs/185-46_measure.json; the table keeps a subset that shows the trend. Five names have no usable common session (CART, CC, CUBE, FLUT, LEA) and are listed, not
dropped. IBKR SMART counts less volume than Tradier, and the gap has widened every year since about
2013: from about 0.95 to about 0.54 at the median. At D the canonical 1d volume of a class A name
steps to roughly 0.54 of its Tradier level on one date for every name together; the step is not
uniform (p10 0.42, p90 0.85), so it is a cross-sectional change as well as a level change.

Consumers of canonical 1d volume, and what a one-time level step at D does to each:
- Research panel (`src/intelligence/research/panel.py` volume field, read from
  market_data_ohlcv_tradeable) and `research/legs.py`: any spec reading volume across D sees a
  per-name level drop; within-window statistics spanning D are biased. The volume_basis_break gate
  (review amendment item 2, carried by todo 501 and filed by 185-48) covers it.
- `research/guards.py`: checks volume is finite and positive only; a level step does not trip it.
- Feature kernels (`features/kernels/volume.py`: rel_volume, volume_z, dollar_vol_z, vol_trend_ratio,
  vol_range_ratio, CMF; `kernels/smc.py` impulse volume over a trailing mean; `kernels/calendar.py`):
  every trailing-window ratio or z-score drops for one window length after D, then re-centers; a
  cross-sectional rank shifts by each name's own ratio. The 186-26 rebuild computes these over D.
- `market_data_ohlcv_tradeable` (volume > 0): unaffected; IBKR bars with positive volume stay
  tradeable.
- `bars/scrub_rules.py` volume_outlier (robust z of log volume over a trailing window): a one-day
  drop of about ln(0.54) = -0.62 in log volume is small next to the MAD threshold for most names, but
  a name with a very stable volume could be flagged on the days after D; 185-47's C4 and C6 catch a
  new failure.
- D7 `daily_vs_intraday` (`services/bar_reconciliation_audit.py`): compares the D1 SMART TRADES daily
  observation with the regular-session 5m aggregate, both IBKR SMART, so it is unaffected; from D it
  could read canonical 1d instead, since both sides are then IBKR SMART.
- D7 `vendor_agreement`: records the per-year IBKR over Tradier volume ratio; after D no new Tradier
  rows arrive, so its last year stops growing; no verdict reads it.
- Grid parity volume tolerance (D7 grid_parity): compares derived 15m and 1h with the vendor archive,
  both IBKR intraday; 1d volume does not enter it.
- `bars/digest.py`, `bars/integrity_checks.py`: hash and recompute stored values; a correct swap
  changes nothing they would flag.

### Per-name classes (R2)

| class | names with SMART TRADES (1,037) | all active (1,529) |
|---|---|---|
| A | 1,017 | 1,017 |
| B | 8 | 8 |
| C | 12 | 504 |

Class C reasons: no_ibkr_yet 492, no_common 6 (CART, CC, CUBE, ETHA, FLUT, LEA), few_common 6 (CNH 11,
EU 1, FROG 55, LGND 10, SNEX 43, VSEC 8 common sessions). The no_common names hold SMART TRADES rows
but none on the current scale: a split recorded after IBKR's last fetch (ETHA 2026-10-02, by Tradier
refetch) leaves every earlier IBKR answer at the old scale. 189-10 Task 1b's refresh step gives them
current-scale answers, and 185-47's rerun of `--classify` decides them again.

Class B: CTVA, ELS, LION, MTCH, NEXN, RGEN, W, WEX. Every one already holds an open primary-ibkr
symbol row from 185-38, so R3 adds no row for them. Heads: 662 names with SMART have a Tradier head
before IBKR's first current-scale bar and 542 of those heads are keepable by the head rule; no class B
name has a keepable head (LION 4,867, W 1,919, WEX 1,614 and NEXN 329 head bars fail the first-window
median), and those heads are already not canonical under the 185-38 rows.

### Admission sweep comparison

The dry run judged the 1,502 compute_1d names: admitted 841, write 73, route_185_37 113,
keep_no_overlap 475. Its write set is not class B. Class B is a subset of it (all 8), and the other 65
write names are names where Tradier was never the canonical series (incumbent false): 54 class A, 11
class C (the 6 few_common names and 5 of the no_common names). 72 of the 73 hold an open symbol row;
VMRK holds the closed one. The 113 route_185_37 names are all class A on the recent window, which is
the RJF-like past basis run the sweep routes to 185-37. The two rules ask different questions (the
sweep: is Tradier admissible over the whole history; R2: who should own bars from D on), so the
difference is expected and not a defect of either.

Finding for 185-47 (no rule is changed here). 11 class C names already hold an open primary-ibkr
symbol row (CART, CC, CNH, CUBE, EU, FLUT, FROG, LEA, LGND, SNEX, VSEC); ETHA is the only class C name
with SMART and no symbol row. R3's hold row (primary tradier, fallback ibkr) would overlap their open
rows and would reverse the 185-38 decision, and C1's "new 0 for class C" would be wrong for them,
since their policy is already IBKR. 185-47 should treat a name with any 1d symbol row as decided, as
`rows_to_write` already does, and judge C1 by each name's effective policy from D. Its amendment block
should say so before it runs.

## Deferred

A replacement or second 1d vendor is Stage V (D-01) and is not added here.
