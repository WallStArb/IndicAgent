Author: Claude (Phase 174, Plan 15 executor)

# Phase 174 D-10 Down-Cap Pilot Gate Verdict

**VERDICT:** FAIL

The pre-registered pilot gate (D-10) was run against a real, mechanically-drawn down-cap
pilot cohort, backfilled at 1d only, and both thresholds missed by a wide margin. Plan 11
must leave `alpha.universe.target_sample_size` at 0, and Plan 12's full-scale down-cap draw
must not proceed under the current design.

## Pre-registered thresholds (quoted verbatim from D-10, `174-CONTEXT.md`)

> Pilot's unconditional average pairwise daily-return correlation ≤ **0.10** (floors the
> n_eff ceiling at ~10 vs. today's ~3.1 -- a ~3x improvement in achievable independent bets,
> economically meaningful against IC~0.03-0.06).
>
> Pilot's `high_bear`-conditioned average pairwise correlation ≤ **0.30** (no worse than
> today's book's *blended-regime* unconditional average -- some correlation increase under
> systemic stress is structurally unavoidable for any equity portfolio, but it should not be
> dramatically worse than today's baseline).

These two thresholds (`0.10` unconditional, `0.30` `high_bear`-conditioned) were fixed in
code as literal, non-APR module constants (`_D10_GATE_UNCONDITIONAL_MAX = 0.10`,
`_D10_GATE_HIGH_BEAR_MAX = 0.30`) by Plan 14, commit `ec84788fb`, **before any pilot data
existed** -- the pre-registration this verdict evaluates against. Neither threshold was
touched by this plan; `git diff scripts/analysis/universe_expansion_correlation_structure_check.py`
against that commit is empty for this run.

## Measured pilot numbers vs. threshold

| Metric | Threshold | Measured | Margin/Miss |
|---|---|---|---|
| Unconditional avg pairwise corr | ≤ 0.10 | **0.3025** | misses by 0.2025 (3.0x the threshold) |
| `high_bear` avg pairwise corr | ≤ 0.30 | **0.4303** | misses by 0.1303 (1.4x the threshold) |

Both thresholds missed. The gate script's exit code was **2** (FAIL), matching this
document's verdict exactly -- no code/verdict mismatch.

Additional pilot statistics (unconditional and `high_bear`, RAW correlation, N=27 after the
coverage filter -- see below):

| Regime | N | Avg | Median | PC1 share | PC1-3 share | n_eff | n_obs |
|---|---|---|---|---|---|---|---|
| unconditional | 27 | 0.3025 | 0.2813 | 34.79% | 43.90% | 3.05 | 2178 |
| high_bear | 27 | 0.4303 | 0.4389 | 47.54% | 57.52% | 2.22 | 432 |

## Full per-regime pilot table (RAW), set beside the baseline (117-name existing book, from
`174-14-SUMMARY.md`, reproduced exactly from `docs/research/phase174-single-name-book-correlation-structure-2026-09-15.md`)

| Regime | Pilot N | Pilot Avg | Pilot n_eff | Baseline N | Baseline Avg | Baseline n_eff |
|---|---|---|---|---|---|---|
| unconditional | 27 | 0.3025 | 3.05 | 117 | 0.3164 | 3.10 |
| high_bear | 27 | 0.4303 | 2.22 | 117 | 0.4789 | 2.07 |
| high_bull | 27 | 0.3090 | 2.99 | 117 | 0.3020 | 3.25 |
| high_neutral | 27 | 0.1849 | 4.65 | 117 | 0.2030 | 4.77 |
| low_bear | 27 | 0.2922 | 3.14 | 117 | 0.3111 | 3.15 |
| low_bull | 27 | 0.2225 | 3.98 | 117 | 0.1731 | 5.55 |
| low_neutral | 27 | 0.2315 | 3.85 | 117 | 0.1985 | 4.87 |
| mid_bear | 27 | 0.3361 | 2.77 | 117 | 0.3213 | 3.06 |
| mid_bull | 27 | 0.2137 | 4.12 | 117 | 0.1423 | 6.68 |
| mid_neutral | 27 | 0.2313 | 3.85 | 117 | 0.2061 | 4.70 |

**The pilot's correlation structure is essentially indistinguishable from the existing
large/mega-cap book's, regime by regime.** The down-cap stratification did not produce a
materially less-correlated population -- if anything the pilot is slightly *more* correlated
than the baseline in `high_bull`/`low_bull`/`mid_bull`, and only marginally less correlated
unconditional/`high_bear`. This is the central finding: down-cap alone, drawn this way, does
not buy the diversification D-10 was testing for.

## Coverage filter and realized cohort size

The diagnostic's `<95%`-of-daily-bars coverage filter dropped **13 of 40** pilot symbols
(32.5%) -- a materially higher drop rate than the baseline document's 11-of-128 (8.6%),
consistent with a down-cap sample skewing toward younger/more-recently-listed companies.
Realized pilot N after filtering: **27**.

| Symbol | Coverage (fraction of 2179 distinct dates, 2018-01-01 to 2026-09-02) |
|---|---|
| PURR | 0.0863 |
| WSHP | 0.0918 |
| JBS | 0.1409 |
| CRWV | 0.1652 |
| UPB | 0.2175 |
| ALMS | 0.2510 |
| AVBP | 0.2997 |
| ATMU | 0.3763 |
| RIVN | 0.5539 |
| ARRY | 0.6774 |
| BEAM | 0.7581 |
| PGNY | 0.7903 |
| COFS | 0.9018 |

**Estimate stability:** N=27 is a small sample for a pairwise-correlation estimate --
`27 * 26 / 2 = 351` pairs feed the unconditional average, and only 432 `high_bear` daily
observations feed that regime's estimate (vs. the baseline's 117-name/larger-N estimate).
The point estimate should be read as directionally informative, not a precise measurement --
but the margin by which both thresholds were missed (3.0x and 1.4x respectively) is large
enough that instability at this N does not plausibly change the FAIL verdict: closing a
0.20-wide gap on the unconditional threshold, or a 0.13-wide gap on `high_bear`, would
require an implausibly large sampling-error correction in exactly the favorable direction on
both regimes simultaneously.

## Union-cohort diagnostic (non-gating)

Per the plan's explicit instruction, this diagnostic is recorded for the phase's record and
does **not** feed the PASS/FAIL verdict above -- D-10 fixed exactly two conditions before any
data existed, and adding a third after seeing the result would be the post-hoc adjustment
pre-registration exists to prevent.

Cohort: the union of the pilot (40 symbols) and the existing `single_name_equity` book (128
symbols) = 168 symbols, all now carrying the `single_name_equity` tag (this plan added it to
all 40 onboarded pilot symbols in Task 1, alongside the pre-existing 128). Coverage filter
dropped 24/168 (14.3%), retaining N=144.

| Regime | N | Avg | Median | n_eff |
|---|---|---|---|---|
| unconditional | 144 | 0.3076 | 0.2939 | 3.20 |
| high_bear | 144 | 0.4643 | 0.4724 | 2.14 |

**Interpretation:** the union cohort's correlation structure (0.3076 unconditional, 0.4643
`high_bear`) sits almost exactly between the pilot-alone (0.3025 / 0.4303) and baseline-alone
(0.3164 / 0.4789) numbers -- essentially unchanged from either half measured on its own. A
cohort that genuinely decorrelated from the existing book would pull the union's average
pairwise correlation down materially below both individual halves (more low-correlation
pairs entering the average); instead the union tracks a simple size-weighted blend. This
means the pilot does not just fail to be internally decorrelated (the gate's own finding) --
it also does not diversify *against* the existing book. Adding this down-cap population to
the current single-name book would not move incremental effective breadth meaningfully in
either direction; both populations appear to be driven by substantially the same common
factor structure.

## SPY-residualized view (non-gating context, per Plan 14's documented reason)

Per `services/ic_engine.py`'s actual IC computation (pooled `rankdata(X, axis=0)` across
every symbol and timestamp in a cell, never cross-sectionally demeaned), raw correlation --
not residualized -- is what the D-10 gate measures, since a common market-wide move is never
netted out before ranking. The residualized table below is reported for interpretability
only and never fed the gate:

| Regime | N | Avg | Median | n_eff |
|---|---|---|---|---|
| unconditional | 27 | 0.1045 | 0.0894 | 7.26 |
| high_bear | 27 | 0.0899 | 0.0830 | 8.09 |

Fitted SPY beta distribution (pilot): mean=1.0846, median=1.0805, std=0.3221, min=0.4407,
max=1.7366.

**Interpretation:** the gap between raw (0.30/0.43) and SPY-residualized (0.10/0.09) is
large -- residualizing against a single market-beta factor removes roughly two-thirds of the
raw correlation. This means the pilot's raw correlation is *mostly market-beta-driven*
rather than a distinct, structural common-factor clustering specific to the down-cap
segment: these are ordinary equities with market betas clustered near 1.0 (mean 1.08),
moving together primarily because they are all long-only long-beta equity exposure, not
because of some down-cap-specific co-movement mechanism. This does not change the verdict
above (the gate is deliberately defined on raw, not residualized, correlation, because that
is what actually limits `ic_engine`'s realized pooled-rank IC) -- but it is a useful
diagnostic for whatever comes next: a residualization or beta-neutralization step in a
future construction might recover more of the n_eff gain D-10 was testing for than
raw-correlation stratification alone can deliver.

## D-01 invariant: `alpha.universe.target_sample_size`

Verified `0` before Task 1's onboarding commit ran, `0` again immediately after (Task 1's
own post-commit assertion), and `0` again at the time this document was written:

```
$ PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -tA \
    -c "SELECT config_value FROM config_state WHERE config_key='alpha.universe.target_sample_size'"
0
```

Per D-01, this key stays 0/unset -- this plan did not set it, and per the FAIL verdict below,
Plan 11 must not set it either until a different down-cap construction is designed and
re-gated. `universe_expansion_stratified_sourcing.py`'s `_async_main()` returns exit code 1
with a `FAILED:` message whenever `target_sample_size <= 0`, so Plan 12's full-scale sourcing
CLI is structurally blocked from running at this value -- the full-scale draw cannot proceed
by a convention someone has to remember, but by a crash-loud guard already merged and
unit-tested (Plan 08).

## Pivot recommendation

D-10's gate failed on both pre-registered thresholds, by a wide margin (3.0x and 1.4x
respectively), on a mechanically-drawn, unbiased, down-cap-reaching sample (4 of 40 drawn
symbols were in the smallest-market-cap decile). The union-cohort diagnostic reinforces this:
the pilot does not diversify meaningfully against the existing book either. Plan 12 (the
full-scale down-cap draw) **should not proceed under the current design** -- backfilling a
much larger down-cap sample at the same construction (unbiased market-cap-stratified random
draw from Russell 3000, no other axis) would very likely reproduce the same correlation
structure at scale, paying the full multi-thousand-symbol backfill and `ic_engine` OOM-fix
engineering cost (D-04) for a population this pilot already shows delivers near-zero
incremental effective breadth over the existing 117-128 name book.

**Candidate next moves, for the user's decision -- not decided here:**

1. **A different stratification axis than market-cap decile.** The residualized-vs-raw gap
   above suggests the down-cap population's co-movement is mostly ordinary market-beta
   exposure, not a down-cap-specific factor. A sector-neutral or industry-spread
   construction (drawing across GICS sectors within cap bands, rather than cap alone) might
   surface names with genuinely different factor exposures rather than more names correlated
   through the same market-beta channel.
2. **Accepting that raw breadth via single-name expansion is not the available lever**, at
   least not through unbiased-random construction, and returning to the cross-TF fusion
   option `.planning/STATE.md`'s Strategic Plan section records as the competing,
   not-yet-decided priority (momentum decorrelates across TFs, per
   `project_cross_tf_signal_correlation_2026_09_13`) -- a structurally different mechanism for
   raising effective breadth than adding more correlated single names.
3. **A beta-neutralization or residualization step** applied to whatever single-name
   population already exists (down-cap or not), informed by the large raw/residualized gap
   measured above -- this is a construction-design question, not explored further by this
   plan.

This is a recommendation, not a decision -- per D-10's own framing, the phase's next move on
this specific lever is the user's call.

## Corpus retention

Per this project's data-retention principle (never drop data that could contain signal), the
40-symbol pilot cohort **stays in the corpus** regardless of this verdict. All 40 symbols
remain `is_active=true`, `compute_eligible_1d=true`, `compute_eligible=false`,
`live_tradeable=false`, tagged both `eq_broad` and `single_name_equity`, with real 1d history
back to their respective listing/onboarding dates. This is a measurement asset either way --
roughly 40 additional down-cap names with real daily history, cheaply acquired (single 1d
request per symbol, ~196K bars total), available for any future construction that wants to
re-examine this population under a different design.

## Provenance

- **Holdings file:** `/var/tmp/phase174_pilot_iwv_holdings.csv`, downloaded 2026-09-16 from
  `https://www.ishares.com/us/products/239714/ishares-russell-3000-etf/latest-holdings.csv`,
  sha256 `f143e656387a1628578a268dcdf6c81947df6fbe6ba14113bb5a24820b038f44`, 2564 accepted rows
  (5 filler-dropped, 11 rejected) out of 2580 raw rows.
- **APR values in play at draw time:**
  - `alpha.universe.stratified_sample_random_state` = 42
  - `alpha.universe.cap_bucket_count` = 10
  - `alpha.universe.pilot_sample_size` = 40
  - `alpha.universe.target_sample_size` = **0** (unset, as required by D-01, unchanged
    throughout this plan)
- **Drawn list (40 symbols, alphabetical):** ACTG, ALMS, ARRY, ATMU, AVBP, BEAM, BKE, CASY,
  CENT, COFS, CRI, CRUS, CRWV, CSTM, DAR, FRHC, GKOS, GRBK, INSW, JBS, KEX, MAR, MGM, MTH,
  PGNY, PURR, RCL, RGR, RIVN, RJF, SLM, SPNT, SSP, THRM, TXT, UNFI, UPB, VNDA, WCC, WSHP.
  0 rejected during onboarding (all 40 qualified against IBKR).
- **Gate script exit code:** 2 (FAIL), matching this document's `**VERDICT:** FAIL` line.
- **Gate JSON output:** `/var/tmp/phase174_pilot_gate.json`.
- **Union-cohort JSON output:** `/var/tmp/phase174_union_cohort.json`.

## Construction-verdict-ledger.md

This verdict is **not** added to `docs/research/construction-verdict-ledger.md`. That
ledger's own stated scope is "predictive-signal hypothesis tests only (does construction X
have real, tradeable IC/edge)," explicitly excluding "infrastructure phases, architecture
decisions, or regime-labeling mechanics unless they were themselves the thing under test."
D-10's gate is a data-population/correlation-structure diagnostic that determines whether a
backfill is worth its engineering cost -- it measures correlation structure, not IC or
tradeable edge, and no `feature_ic_scores`/`alpha_ensemble_ic` measurement was made against
this cohort. Per the ledger's own criteria, this verdict does not belong there.
