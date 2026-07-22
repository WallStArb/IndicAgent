---
status: completed
priority: P1
filed: 2026-07-19
completed: 2026-07-22
source: Component F (todo 097) definitive full-corpus A/B verdict
  (docs/plans/methodology-change-ledger.md E8 addendum) -- a genuinely new finding not
  visible in any smaller sample run this session or in Fable 5's own review
resolved: 2026-07-20 -- root cause is corrupt-print contamination of true_range_pct
  (same class as todos 148/149/151/152); no separate fix needed here. 151/154's
  correction pass ran but missed 3 named rows (VWO/DIA/KRE) -- CV re-check 2026-07-20
  confirmed still not at parity; blocked on 160 landing, then re-checked a third time
---

## Disposition (2026-07-22) — third CV re-check: PARITY REACHED, todo closed

Todo 160's fix (see its own disposition) went well beyond its original 2-row scope
once its candidate-discovery mechanism was found to be structurally broken --
corrected 40 bars across 14 symbols, then 7 more across FXY/IWM once a threshold-
sensitivity gap surfaced closing out this check. Ran the exact same per-`(tf,
regime_label)` `true_range_pct` CV sweep this todo's diagnostic used for both prior
checks (`feature_vectors JOIN market_regimes ON regime_group='equity' AND tf AND
ts=bar_ts`, `GROUP BY tf, regime_label`, `stddev/avg` as CV):

| tf | regime | CV: original | CV: re-check #2 (2026-07-20) | CV: re-check #3 (2026-07-22) |
|---|---|---|---|---|
| 5m | low_bull | 582.9 | 313.24 | **3.49** |
| 15m | low_bull | 469.4 | 279.22 | **2.80** |
| 1h | mid_bull (new outlier, found in re-check #2) | -- | 324.49 | **3.17** |

Both `low_bull` cells and the `1h/mid_bull` cell newly surfaced in re-check #2 are
now squarely in the same order of magnitude as every clean regime (full 36-cell
sweep ranges 0.75-6, excluding one explained exception below) -- exactly the
closing criterion this todo's own "Root cause CONFIRMED" section set: "if
`low_bull`'s CV drops to the same order as every other regime, the divergence
resolves as a side effect."

**One remaining elevated cell, confirmed NOT a gap:** `5m/high_bear` stayed at
CV≈116 before and after the FXY/IWM follow-up fix (116.14 → 116.31, i.e.
unchanged). Pulled its outlier rows directly: dominated by IGV/CWB (`true_range_pct`
456/306) at 2010-05-06 18:45-18:50 -- the same May 6 2010 Flash Crash cluster this
todo's own 2026-07-20 note already adjudicated as "legitimate crisis volatility per
the same carve-out established in todo 152, not corrupt data." A CV metric is
dominated by its largest squared deviations, so FXY/IWM's ~9.9x corrections
(genuine fixes, found investigating this same cell) barely move a number this
cluster already dominates by ~2000x in variance contribution. No action needed --
this is expected, already-explained variance, not a new discovery gap.

**Not re-run as part of this closure** (already confirmed encouraging in the
2026-07-20 session, and this todo's own text only gated closure on the CV number,
not a fourth A/B pass): `ops_vol_normalized_target_ab.py --all-regimes`. If
Component F's promotion decision needs a fresh number, re-run it against the now-
corrected corpus as its own action, not blocking this todo's closure.

**Mechanism 1 (denominator-side corrupt-print contamination) is now fully
resolved**, not just confirmed. `low_bull` no longer needs a carve-out in Component
F's promotion decision.


# Vol-normalized vs. raw-return POOLED IC diverges sharply and specifically in `low_bull`
# regime strata -- not explained by low N, mechanism unknown

## Problem

097's definitive `--all-regimes` A/B (106 strata, post-143.1-07 corpus) found median rank
correlation 0.7173 between raw-return and vol-normalized (`return_x / true_range_pct`)
POOLED IC rankings -- real divergence, not near-identical, so the transform stays a live
candidate rather than being retired.

But the divergence is not uniform: `low_bull` regime strata (across multiple tfs) show a
median rank correlation of 0.351 (n=12 strata) vs. 0.731 for every other regime (n=94
strata) -- a 2x gap. Critically, this is NOT the "thin data reads as noise" pattern that
explains the previously-known 1d/extended-horizon outliers (e.g. 1d/high_bull/60 at
n=588). Several `low_bull` cells are among the best-powered strata in the ENTIRE 106-row
run:

| tf | regime | lookahead | n_independent | rank_corr |
|---|---|---|---|---|
| 1h | mid_bull | 1 | 50,079 | 0.0485 |
| 15m | low_bull | 5 | 367,448 | 0.1101 |
| 1h | low_bull | 1 | 81,018 | 0.1726 |
| 15m | low_bull | 1 | 436,346 | 0.2349 |
| 5m | low_bull | 20 | 253,384 | 0.2415 |

Broader pattern: `bull`-family regimes overall lag `bear`/`neutral` (median rank_corr
0.56 vs. 0.75/0.80), but `low_bull` specifically is the extreme driver, not the whole
`bull` family uniformly.

## Why this matters

Component F's keep/retire decision for the vol-normalized target directly affects what
the ensemble trains on (POOLED-strata IC feeds `ensemble_trainer.py`'s eligibility and
weighting). A target whose behavior diverges sharply and specifically in one regime,
for reasons nobody understands yet, is a real risk to promote uniformly -- either the
raw or the vol-normalized ranking could be systematically wrong specifically in
`low_bull` conditions, and right now there's no way to tell which.

## Investigation (not yet started)

Candidate mechanisms, none confirmed:

1. **`true_range_pct` (the vol-normalization denominator) behaves unusually in
   genuinely low-volatility bull conditions.** If the denominator is itself compressed
   or noisy exactly when the regime label says volatility is low, dividing by it could
   amplify noise disproportionately in `low_bull` specifically. Check: distribution of
   `true_range_pct` within `low_bull` vs. other regimes: is it unusually small,
   unusually noisy (high coefficient of variation), or bimodal?
2. **A real economic difference in what predicts returns in `low_bull` regimes under
   the two target definitions** -- not a measurement artifact but a genuine finding
   that vol-normalization changes which features matter specifically in quiet bull
   markets. Would need domain reasoning, not just a statistical check, to confirm.
3. **Regime-boundary contamination** -- check whether `low_bull` bars are
   disproportionately near regime transition boundaries (where the label itself may be
   less reliable) compared to other regimes' bars in this corpus.

## Fix / next step

Not a fix yet -- this is a "measure before deciding" todo (per this project's own
"measure, don't defer" convention). Cheapest first check: pull the `true_range_pct`
distribution (mean, CV, skew) for `low_bull` vs. every other regime across the same tfs
this A/B covered, using data already fetched by `ops_vol_normalized_target_ab.py`'s own
POOLED array assembly (no new query shape needed, just a diagnostic report over data
the script already pulls). If mechanism 1 confirms, the fix is regime-conditional (e.g.
exclude `low_bull` from vol-normalized promotion, or find a better denominator there,
not a global target choice). If it doesn't confirm, escalate to domain reasoning /
Fable review before making any promotion call.

**Blocks:** any decision to promote vol-normalized as a shadow `weight_version` variant
should wait on this, or explicitly carve out `low_bull` from the promoted scope pending
this investigation -- see the open decision recorded in 097 / the E8 ledger addendum.

## Sizing

Todo-sized. The `true_range_pct` distribution check is cheap (reuses existing data,
half a day). Escalation to domain reasoning if the cheap check doesn't explain it is
open-ended and would need its own scoping at that point.

## Root cause CONFIRMED (2026-07-20) -- mechanism 1, but not as originally framed

Ran the cheap first check this todo specified: `true_range_pct` distribution (mean, stddev,
CV) per (tf, regime), pure SQL aggregate over `feature_vectors JOIN market_regimes`, no new
query shape, no data pulled into Python. Result was decisive, not the "compressed
denominator amplifies noise generally" story mechanism 1 originally hypothesized:

| tf | regime | n | mean_trp | cv |
|---|---|---|---|---|
| 5m | low_bull | 7,150,792 | 0.0017 | **582.9** |
| 5m | mid_bull | 5,062,464 | 0.0012 | 31.7 |
| 15m | low_bull | 2,427,948 | 0.0036 | **469.4** |
| 1d | low_bull | 103,023 | 0.0240 | **148.6** |
| 1h | low_bull | 614,948 | 0.0040 | 1.13 (normal) |

`low_bull`'s **mean** `true_range_pct` is unremarkable (comparable to neighboring regimes)
-- it's the **stddev/CV that's 10-100x every other regime's**, and only in specific
tf x regime cells (1h/low_bull is completely normal; 1h/mid_bull, not low_bull, is the
outlier there instead). A genuine "quiet bull market compresses the vol-normalization
denominator" effect would show a smooth pattern tied to `mean_trp` magnitude across all
cells. This doesn't -- it's the signature of a small number of extreme-outlier bars, not a
regime-wide statistical property.

Pulled the actual outlier rows (`true_range_pct > 0.5`, i.e. >50% implied range) within
`low_bull` cells and cross-checked against raw `market_data_ohlcv`:

| symbol | tf | bar_ts | open | high | true_range_pct |
|---|---|---|---|---|---|
| VWO | 5m | 2007-05-02 15:40 | 41.79 | **99999.99** | 2390.77 |
| DIA | 1d | 2009-06-02 | 87.14 | **100000** | 1143.43 |
| KRE | 5m | 2007-09-18 18:15 | 44.43 | **400** | 7.86 |
| XRT | 15m | 2007-09-18 18:15 | 19.64 | **231.54** | 10.68 |
| UUP | 15m | 2007-06-19 19:00 | 25.07 | 25.07 (flat) | 38.89 (zero-range degenerate print, vol=100) |

**These are the exact same corrupt IBKR prints already identified by the parallel
148/149/151/152 price-sanity investigation** -- `VWO`/`UUP`/`XRT` are named verbatim in
todo 152's "confirmed no economic basis" list. `99999.99`/`100000` are textbook
fabricated/sentinel-overflow ticks, not real prices; nothing here is an ambiguous
crisis-event case like 152's Flash Crash rows. Two instances are new to that investigation
and worth flagging for it directly (not acting on here, per the other session's active
ownership of that work): **DIA 2009-06-02** (not previously named) and **KRE 2007-09-18**
(a full year before the already-known 2008-09-18 KRE Lehman-aftermath event -- a distinct
occurrence, same symbol).

**Why this specifically corrupts `low_bull`'s feature ranking (not just inflates variance):**
the A/B script's `rank_correlation` compares, across all 155 features, each feature's
raw-target IC vs. vol-normalized-target IC for a stratum. Because `vol_normalized_return`
divides every feature's shared target column by the same `true_range_pct` value per row, a
handful of corrupt bars with grotesquely inflated `true_range_pct` inject a *shared,
correlated* perturbation into every feature's vol-IC estimate simultaneously at those rows
-- not independent per-feature noise. That's enough to measurably decorrelate the
vol-normalized feature ranking from the raw ranking in exactly the well-powered cells this
todo's evidence table showed (367K-436K obs cells aren't "thin data reads as noise" --
they're "a few outlier rows share-corrupt every feature's target in the same direction").

**Resolution: no separate fix needed from this todo.** This is squarely 149's scope (bar
ingestion price-sanity guard, upstream of `market_data_ohlcv` -- `true_range_pct` is
computed downstream from raw OHLC, so it inherits whatever 149 catches at the source) and
151's scope (backward cleanup of known corrupt prints, which should add DIA/KRE-2007-09-18
to its list). Once those land, re-run this todo's `true_range_pct` CV check and
`ops_vol_normalized_target_ab.py --all-regimes` -- if `low_bull`'s CV drops to the same
order as every other regime, the divergence resolves as a side effect and Component F's
promotion decision can proceed without a `low_bull` carve-out. **Mechanism 1 confirmed in
spirit (denominator-side corruption), mechanism 2 (real economic effect) and mechanism 3
(regime-boundary contamination) both ruled out** -- no domain-reasoning/Fable escalation
needed, this was a data-integrity question, not a methodology ambiguity.

## A/B rank-correlation re-run (2026-07-20, post-151/154 corrections)

Ran `ops_vol_normalized_target_ab.py --all-regimes` after both 151's backfill correction and
154's DIA/KRE cleanup landed. Result: 106 reliable strata, median rank_corr 0.7087.

`low_bull`'s previously-extreme cells are still on the low end (5m/low_bull lookahead=20/60 at
0.0041/0.0009; 15m/low_bull across lookaheads at 0.17-0.29; 1h/low_bull/1 at 0.2526), but critically
**comparable or worse values now show up in OTHER regimes too** — e.g. 1h/mid_bull/1 at **-0.0182**
(worse than any `low_bull` cell at that timeframe), 1d/mid_bull lookahead=20/60 at 0.0146/0.0293
(same order as `low_bull`'s worst 1d cell), 15m/mid_bull/20 at 0.2132. This is the pattern this
todo's own root-cause section predicted would happen if the fix worked: the previously-singular
"`low_bull` is uniquely 2x worse than everything else" signature is gone — what's left looks like
the ordinary "thin data / long lookahead reads as noise" pattern this todo explicitly said was
NOT what was happening before (see "Problem" section above, the `n_independent` counterexamples).

**Not yet closed.** This A/B rank-correlation re-run is one of the two checks this todo's "Fix /
next step" section asked for. The other — re-pulling `true_range_pct`'s per-(tf, regime) CV
directly (the actual metric that diagnosed the 10-100x low_bull outlier in the first place,
not a proxy for it) — has NOT been re-run. Do not close this todo until that CV number is
confirmed back at parity with other regimes; the rank-correlation improvement is consistent with
resolution but is not the same measurement as the original diagnostic.

## `true_range_pct` CV re-check (2026-07-20) — STILL NOT AT PARITY, root cause re-confirmed

Ran the full per-(tf, regime_label) CV sweep this todo required (`feature_vectors JOIN
market_regimes ON regime_group='equity'`, all 4 tfs x 9 regimes, 36 cells). Result: **not
resolved.** `low_bull`'s CV dropped from the original 582.9/469.4 to 313.24 (5m) / 279.22
(15m) — real improvement from 151/154's corrections, but still ~150-300x every clean
regime's CV (~1-6), nowhere near parity. This full sweep also surfaced two cells the
original 5-row snippet never covered: 1h/mid_bull at CV=324.49 and 5m/high_bear at
CV=116.00 — same signature, different cells.

Cross-checked the worst outlier rows against raw `market_data_ohlcv`: **the exact same
fabricated sentinel prints from the original diagnosis are still live, uncorrected** —
`VWO` 1h 2007-05-02 15:00 (`high=99999.99`), `DIA` 5m 2009-06-02 14:00 (`high=100000`),
`KRE` 5m 2007-09-18 18:15 (`high=400`). These are the exact three rows this todo's own
"Root cause CONFIRMED" section named and flagged "for [151/154] directly... not acting on
here" — they were never actually picked up by that correction pass. (Separately verified
the new 1h/mid_bull / 5m/high_bear outlier cluster at 2010-05-06 18:45-18:55 (IGV/CWB/VUG)
is the real May 6 2010 Flash Crash — legitimate crisis volatility per the same carve-out
established in todo 152, not corrupt data. No action needed there.)

**Mechanism 1 (denominator-side corrupt-print contamination) stays fully confirmed** — this
is not a new root cause, it's the same one, just incompletely corrected. Filed the specific
gap as [160](160-vwo-dia-kre-corrupt-prints-uncorrected.md) rather than fixing inline here
(correction goes through the `price_sanity_status` mechanism + recompute, not a raw UPDATE,
and is squarely 151/154's owned tooling/scope). **Still blocked — do not close 147 until
160 lands and this CV check is re-run a third time.**

## References

- `.planning/todos/pending/097-vol-normalized-return-target-pooled-ic.md` -- parent
  A/B result this finding came out of
- `docs/plans/methodology-change-ledger.md` E8 addendum, 2026-07-19 -- full numbers,
  definitive verdict, and the open promotion decision this todo gates part of
- `scripts/ops/alpha/ops_vol_normalized_target_ab.py` -- the A/B script; its
  `_fetch_pooled_arrays` already pulls `true_range_pct` (via `_FEATURE_NAMES`) for
  every evaluated stratum, reusable for the cheap first check above
- `src/intelligence/statistics/ic_math.py` `vol_normalized_return` -- the transform
  under investigation
