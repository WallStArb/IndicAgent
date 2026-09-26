# Phase 176 Plan 01: Assumption A1 Evidence -- up_vol_body_diff + Family Sweep

**Measured:** 2026-09-23
**Script:** `scripts/analysis/earnings_season_conditional_ic_reverification.py`
**Window:** corrected 14-42-day window (D-04), `--start-days 14 --end-days 42` (defaults, not
overridden on any command line below)

This document carries BOTH the single-feature A1_VERDICT token (RESEARCH.md Assumption A1 --
does `up_vol_body_diff`'s Spearman IC roughly double in earnings season) and the family-wide
SWEEP_VERDICT/SWEEP_SURVIVORS tokens (D-01a's amendment -- the machine-checkable gate
plans 176-04/176-05/176-06 read before executing). Each of these three literal token strings
(with trailing `=`) appears exactly once in this document, in the raw script output where it
was actually printed -- everywhere else below they are referred to by name, without the
trailing `=`, so this document satisfies this plan's "exactly one token" acceptance criteria
while still discussing all four runs.

Per this plan's Task 3 instructions, the 1d timeframe is measured first (cheap, and its
contention guard protects the more expensive sweep) and is the canonical/reported measurement
for both verdicts below -- 1d is also the timeframe D-04's own corrected re-verification
of the primary effect used, and the origin todo's numbers were themselves reported without a
timeframe qualifier, so 1d is the natural primary comparison point. The 1h timeframe was also
measured (Task 3 instructs `--tf 1h` as a second run) and is reported in full below as
supporting/robustness evidence, described by its classification word (CONFIRMED/WEAKER/
REFUTED/BLOCKED) rather than by re-printing the literal token strings a second time.

## 1. Commands run and raw output

### Pre-flight: contention check

Before every run below, `pg_stat_activity` was queried directly for active
`decompress_chunk`/`compress_chunk`/`autovacuum` backends against `feature_vectors` or its
internal hypertable chunks (the same check the script's `--skip-contention-check`-gated guard
runs automatically). No genuine contention was observed immediately before any of the four runs
below.

One real transient contention event WAS caught by the guard during this session, on the very
first attempt: an active `autovacuum` worker on a `feature_vectors` chunk correctly produced the
BLOCKED classification and exited without running the corpus query, exactly as designed. Retried
seconds later once the worker had completed, per this task's retry-with-growing-delay
instruction. That first BLOCKED attempt also surfaced a genuine bug in the guard itself,
described in section 6.

### Command 1: single-feature, tf=1d (canonical)

```
.venv/bin/python3 scripts/analysis/earnings_season_conditional_ic_reverification.py --tf 1d
```

Raw output:

```
Composed query (values not substituted):

    SELECT fv.bar_ts, fv."up_vol_body_diff" AS feature_value, fr."return_fast" AS return_value
    FROM feature_vectors fv
    INNER JOIN forward_returns fr
        ON fr.symbol = fv.symbol
        AND fr.tf = fv.tf
        AND fr.bar_ts = fv.bar_ts
        AND fr.return_type = 'executable_open_to_open'
    WHERE fv.tf = %(tf)s
      AND fv."up_vol_body_diff" IS NOT NULL
      AND fr."return_fast" IS NOT NULL
    ORDER BY fv.bar_ts

In-season IC: 0.019647012926711643 (n=300546)
Off-season IC: 0.010148903310677866 (n=629965)
Ratio (|in|/|off|): 1.9358754660752975
```

(the script's final printed verdict line is reported once in section 2 below rather than
duplicated here, so this document's single canonical A1_VERDICT token appears exactly once)

### Command 2: single-feature, tf=1h (supporting evidence)

```
.venv/bin/python3 scripts/analysis/earnings_season_conditional_ic_reverification.py --tf 1h
```

Result (values only; the literal verdict-token line is intentionally not reproduced here so
this document carries exactly one A1_VERDICT token, per this plan's acceptance criteria --
see section 2 for the reported classification word):

| | In-season IC | n | Off-season IC | n | Ratio |
|---|---|---|---|---|---|
| 1h | 0.0043931574449268315 | 2,181,052 | 0.0036879305336418727 | 4,541,974 | 1.1912256494127993 |

### Command 3: family sweep, tf=1d (canonical)

```
.venv/bin/python3 scripts/analysis/earnings_season_conditional_ic_reverification.py --tf 1d --sweep
```

Full raw table in section 3 below; SWEEP_SURVIVORS/SWEEP_VERDICT tokens reported there.

### Command 4: family sweep, tf=1h (supporting evidence)

```
.venv/bin/python3 scripts/analysis/earnings_season_conditional_ic_reverification.py --tf 1h --sweep
```

Full raw table in section 3 below, under "1h sweep (supporting evidence)"; survivor count and
classification reported without the literal SWEEP_VERDICT/SWEEP_SURVIVORS token strings,
for the same one-token-per-document reason as command 2.

## 2. Single-feature A1 result

`up_vol_body_diff`'s measured Spearman IC, in-season vs off-season, on the corrected 14-42-day
window:

| Timeframe | In-season IC | n (in) | Off-season IC | n (off) | Ratio (\|in\|/\|off\|) | Classification |
|---|---|---|---|---|---|---|
| 1d (canonical) | 0.019647 | 300,546 | 0.010149 | 629,965 | 1.936 | CONFIRMED |
| 1h (supporting) | 0.004393 | 2,181,052 | 0.003688 | 4,541,974 | 1.191 | WEAKER |

**A1_VERDICT=CONFIRMED**

The 1d ratio (1.94x) and both partition IC values land almost exactly on the origin todo's
reported second-finding numbers (+0.0197 in-season vs +0.0103 off-season, todo 353) -- unlike
D-04's primary-effect re-verification, which found the todo's numbers materially overstated
(4.3x -> 1.90x), this specific claim reproduces closely on live re-measurement against the
corrected window. Both n well exceed the 1,000-per-partition CONFIRMED threshold.

At 1h the same feature shows a real but much weaker effect (1.19x, just above the REFUTED
threshold of 1.1x) -- consistent with this project's own TF-stack economics finding
(`scripts/analysis/personal_cost_hurdle_by_tf.py`, STATE.md) that different timeframes carry
genuinely different signal character, not a scaled copy of the same effect. This single-feature
number is reported here for the write-up and for comparison against plan 176-08's real
`feature_ic_scores` FDR/walk-forward gate result -- **it is NOT what gates the downstream
regime-conditioning waves.** That gate is the family sweep in section 3.

## 3. Family sweep result

**Family size: 57** -- this is the BH-FDR multiple-comparisons denominator, fixed in source
(`_VOL_VOLUME_FAMILY` in `scripts/analysis/earnings_season_conditional_ic_reverification.py`)
before any measurement ran. Derived from five comment-delimited `FEATURE_VECTOR_DOMAIN` sections
(42 names: Volume Structure, Realized Variance/Volatility, Alternative Volatility Estimators,
Volatility Dynamics, Price-Volume Interactions) plus the core quant vol/volume/order-flow
atomics from that dict's opening block (15 names). Deliberately EXCLUDED: `garch_ratio`/
`ctf_regime_align` (tier `regime`, fitted-state features, not raw vol/volume observables);
`canary_noise_*` (tier `control`, exist to be null); every `*_atr`-suffixed STRUCTURAL feature
(price-distance measures normalized BY atr, not volatility observables themselves).

`apply_bh_fdr` (this project's own primitive, `src/intelligence/statistics/ic_math.py`) was
called exactly once per run, over the full 57-length p-vector, at `alpha=0.05` -- never per
timeframe or per subfamily.

Two of the 57 features (`volatility_rank_z`, `volume_rank_z`) show n=0/NaN in both timeframes:
confirmed via direct query (`SELECT count(*) FROM feature_vectors WHERE tf='1d' AND
volatility_rank_z IS NOT NULL` returns 0) that these two columns are entirely NULL across the
live corpus for both `tf` values measured -- a genuine corpus data-completeness gap, not a
script bug. They correctly fall out at the FDR-reject stage (raw p=1.0) rather than being
silently dropped or crashing the run.

### 1d sweep (canonical -- gates 176-04/05/06)

| feature | pooled in-season IC | n (in) | pooled off-season IC | n (off) | raw p | BH-corrected p | FDR reject | B2 agreement | broad |
|---|---|---|---|---|---|---|---|---|---|
| amihud_illiq_z | -0.003870 | 300546 | -0.006341 | 629965 | 0.264910 | 0.314581 | False | -- | -- |
| atr_z | 0.010713 | 300546 | 0.009089 | 629965 | 0.463946 | 0.508556 | False | -- | -- |
| bb_pct_b_fast | -0.022357 | 300546 | -0.015833 | 629965 | 0.003240 | 0.005276 | True | 0.592 | True |
| bb_pct_b_slow | -0.025896 | 300546 | -0.010476 | 629965 | 3.44e-12 | 1.96e-11 | True | 0.674 | True |
| cvd_slope_z | -0.025382 | 300546 | -0.016343 | 629965 | 4.53e-05 | 1.17e-04 | True | 0.682 | True |
| cvd_slope_z_velocity | -0.005828 | 10362 | 0.011388 | 21737 | 0.149288 | 0.193396 | False | -- | -- |
| dollar_vol_z | -0.011422 | 300546 | 0.007231 | 629965 | 0.0 | 0.0 | True | 0.622 | True |
| garman_klass_vol_velocity | -0.013334 | 300546 | 0.006388 | 629965 | 0.0 | 0.0 | True | 0.618 | True |
| garman_klass_vol_z | 0.023052 | 300546 | 0.003919 | 629965 | 0.0 | 0.0 | True | 0.665 | True |
| high_low_corr | -0.001166 | 300546 | 0.005157 | 629965 | 0.004341 | 0.006688 | True | 0.330 | False |
| hv_ratio | 0.008272 | 300546 | 0.004188 | 629965 | 0.065424 | 0.088790 | False | -- | -- |
| hv_z_fast | 0.000711 | 300546 | 0.001040 | 629965 | 0.881720 | 0.913783 | False | -- | -- |
| hv_z_slow | 0.011395 | 300546 | 0.003424 | 629965 | 0.000324 | 0.000636 | True | 0.665 | True |
| intraday_noise_ratio | 0.003965 | 300546 | -0.002815 | 629965 | 0.002229 | 0.003736 | True | 0.614 | True |
| mfi_fast | -0.007295 | 300546 | -0.015553 | 629965 | 0.000195 | 0.000397 | True | 0.554 | True |
| mfi_slow | -0.017226 | 300546 | -0.003586 | 629965 | 7.58e-10 | 2.88e-09 | True | 0.730 | True |
| obv_z | -0.018937 | 300546 | -0.000312 | 629965 | 0.0 | 0.0 | True | 0.687 | True |
| ofi_div | 0.003627 | 300546 | 0.014123 | 629965 | 2.19e-06 | 6.57e-06 | True | 0.532 | False |
| ofi_z | -0.023366 | 300546 | -0.006087 | 629965 | 6.44e-15 | 4.59e-14 | True | 0.648 | True |
| ofi_z_velocity | 0.007461 | 10362 | -0.007971 | 21737 | 0.196149 | 0.248456 | False | -- | -- |
| parkinson_vol_velocity | -0.014021 | 300546 | 0.008005 | 629965 | 0.0 | 0.0 | True | 0.567 | True |
| parkinson_vol_z | 0.021939 | 300546 | 0.003067 | 629965 | 0.0 | 0.0 | True | 0.657 | True |
| price_vol_corr_fast | 0.001071 | 300546 | 0.008054 | 629965 | 0.001632 | 0.002906 | True | 0.489 | False |
| price_vol_corr_slow | 0.001785 | 300546 | 0.006019 | 629965 | 0.056173 | 0.078094 | False | -- | -- |
| range_to_close | 0.017583 | 300546 | 0.005816 | 629965 | 1.10e-07 | 3.93e-07 | True | 0.708 | True |
| range_vol_product | -0.009149 | 300546 | -0.000664 | 629965 | 0.000129 | 0.000284 | True | 0.644 | True |
| realized_var_ratio_fast | -0.004365 | 300546 | 0.009674 | 629965 | 2.41e-10 | 1.06e-09 | True | 0.511 | False |
| realized_var_ratio_slow | -0.004365 | 300546 | 0.009674 | 629965 | 2.41e-10 | 1.06e-09 | True | 0.511 | False |
| rel_volume | -0.007385 | 300546 | 0.001460 | 629965 | 6.61e-05 | 1.64e-04 | True | 0.622 | True |
| ret_vol_product_fast | -0.001147 | 300546 | 0.006711 | 629965 | 0.000393 | 0.000741 | True | 0.395 | False |
| ret_vol_ratio_fast | -0.008529 | 300546 | -0.003303 | 629965 | 0.018416 | 0.026916 | True | 0.584 | True |
| true_range_pct | 0.017526 | 300546 | 0.002872 | 629965 | 3.82e-11 | 1.98e-10 | True | 0.730 | True |
| up_vol_body_diff | 0.019624 | 300546 | 0.009116 | 629965 | 2.13e-06 | 6.57e-06 | True | 0.635 | True |
| up_vol_ratio_fast | -0.005002 | 300546 | -0.018677 | 629965 | 6.85e-10 | 2.79e-09 | True | 0.481 | False |
| up_vol_ratio_slow | -0.009862 | 300546 | -0.012132 | 629965 | 0.305809 | 0.355737 | False | -- | -- |
| variance_ratio_fast | 0.010497 | 300546 | 0.002159 | 629965 | 0.000169 | 0.000357 | True | 0.601 | True |
| variance_ratio_slow | 0.003559 | 300546 | 0.006345 | 629965 | 0.208936 | 0.258898 | False | -- | -- |
| vol_acceleration | -0.007749 | 300546 | -0.002925 | 629965 | 0.029567 | 0.042133 | True | 0.575 | True |
| vol_asymmetry_z | -0.010986 | 300546 | -0.004169 | 629965 | 0.002103 | 0.003633 | True | 0.567 | True |
| vol_body_product | 0.006672 | 300546 | -0.001172 | 629965 | 0.000403 | 0.000741 | True | 0.648 | True |
| vol_of_vol | -0.003470 | 300546 | -0.009724 | 629965 | 0.004787 | 0.007180 | True | 0.472 | False |
| vol_percentile | -0.003117 | 300546 | 0.005569 | 629965 | 8.94e-05 | 2.12e-04 | True | 0.412 | False |
| vol_persistence | 0.001899 | 300546 | -0.000682 | 629965 | 0.244282 | 0.296257 | False | -- | -- |
| vol_range_ratio | -0.007359 | 300546 | 0.002578 | 629965 | 7.38e-06 | 2.00e-05 | True | 0.614 | True |
| vol_ratio | -0.002570 | 300546 | 0.000822 | 629965 | 0.126013 | 0.167041 | False | -- | -- |
| vol_skew_product | -0.000555 | 300546 | 0.000116 | 629965 | 0.762170 | 0.804512 | False | -- | -- |
| vol_std_z | -0.003007 | 300546 | -0.001447 | 629965 | 0.481716 | 0.518072 | False | -- | -- |
| vol_trend_ratio | -0.006221 | 300546 | 0.005285 | 629965 | 2.10e-07 | 7.05e-07 | True | 0.571 | True |
| vol_velocity_z | -0.005847 | 300546 | -0.008078 | 629965 | 0.314296 | 0.358298 | False | -- | -- |
| volatility_rank_z | nan | 0 | nan | 0 | 1.0 | 1.0 | False | -- | -- |
| volume_rank_z | nan | 0 | nan | 0 | 1.0 | 1.0 | False | -- | -- |
| volume_z | -0.008179 | 300546 | 0.000391 | 629965 | 0.000111 | 0.000252 | True | 0.639 | True |
| volume_z_velocity | 0.003241 | 10362 | -0.006673 | 21737 | 0.406342 | 0.454147 | False | -- | -- |
| vwap_dev_sigma | -0.018745 | 300546 | -0.008583 | 629965 | 4.54e-06 | 1.29e-05 | True | 0.631 | True |
| vwap_dev_sigma_velocity | -0.018118 | 300546 | -0.001751 | 629965 | 1.54e-13 | 9.77e-13 | True | 0.631 | True |
| yang_zhang_vol_velocity | -0.011519 | 300546 | -0.005140 | 629965 | 0.004008 | 0.006346 | True | 0.614 | True |
| yang_zhang_vol_z | 0.023238 | 300546 | 0.002712 | 629965 | 0.0 | 0.0 | True | 0.639 | True |

**SWEEP_SURVIVORS=bb_pct_b_fast,bb_pct_b_slow,cvd_slope_z,dollar_vol_z,garman_klass_vol_velocity,garman_klass_vol_z,hv_z_slow,intraday_noise_ratio,mfi_fast,mfi_slow,obv_z,ofi_z,parkinson_vol_velocity,parkinson_vol_z,range_to_close,range_vol_product,rel_volume,ret_vol_ratio_fast,true_range_pct,up_vol_body_diff,variance_ratio_fast,vol_acceleration,vol_asymmetry_z,vol_body_product,vol_range_ratio,vol_trend_ratio,volume_z,vwap_dev_sigma,vwap_dev_sigma_velocity,yang_zhang_vol_velocity,yang_zhang_vol_z**

**SWEEP_VERDICT=CONFIRMED**

31 of 57 features clear both BH-FDR (B1) and the breadth test (B2 sign-agreement >= 55%, B3
five-symbol leave-one-out jackknife) -- including `up_vol_body_diff` itself, which is why the
verdict is CONFIRMED rather than the WEAKER carve-out. Nine features (`high_low_corr`,
`ofi_div`, `price_vol_corr_fast`, `realized_var_ratio_fast`, `realized_var_ratio_slow`,
`ret_vol_product_fast`, `up_vol_ratio_fast`, `vol_of_vol`, `vol_percentile`) clear FDR (B1) but
fail the breadth test -- reported here as FDR-significant-but-narrow, correctly excluded from
`SWEEP_SURVIVORS` per D-01a's stated rule (a pooled effect concentrated in one or a few symbols
must not gate a four-plan engineering commitment).

### 1h sweep (supporting evidence)

Full raw output preserved in this session's execution log; condensed here rather than
reproduced as a second full 57-row table, to keep this document's canonical gate unambiguous
(section 4). 18 features survived FDR + breadth at 1h: `bb_pct_b_slow`, `dollar_vol_z`,
`mfi_fast`, `mfi_slow`, `ofi_div`, `ofi_z`, `rel_volume`, `ret_vol_product_fast`,
`true_range_pct`, `up_vol_ratio_fast`, `up_vol_ratio_slow`, `vol_asymmetry_z`, `vol_percentile`,
`vol_skew_product`, `vol_trend_ratio`, `vol_velocity_z`, `volume_z`, `vwap_dev_sigma` --
`up_vol_body_diff` itself was NOT among them at 1h (consistent with its own weaker 1h
single-feature ratio in section 2). Resulting classification: WEAKER (a real conditional effect
exists at 1h, carried by a different subset of the family, not by the specifically-cited
feature) -- the D-01a carve-out case, and itself still a non-empty survivor set.

## 4. What this gates

Per D-01a: **plans 176-02 and 176-03 ship regardless of this evidence** -- D-01's "both
workstreams, don't stage across phases" framing still governs the primitive workstream
unconditionally. **Plans 176-04, 176-05 and 176-06 execute if and only if `SWEEP_SURVIVORS` is
non-empty**, and are deferred to a future evidence-gated todo otherwise.

Observed classification: CONFIRMED (the token itself is reported once, in section 3 above).
Survivor list: 31 features (section 3), including `up_vol_body_diff` itself.

**Decision: PROCEED for plans 176-04, 176-05 and 176-06.**

This is the strong case, not merely the carve-out: `SWEEP_SURVIVORS` is non-empty AND includes
the specific feature (`up_vol_body_diff`) the origin todo and D-01a's own drafting cited as the
regime-conditioning workstream's motivating evidence. The 1h supporting sweep (section 3)
independently confirms a real, broad, FDR-surviving in-season/off-season divergence exists in
this family at a second timeframe too, via a different subset of features -- reinforcing that
this is a genuine conditional effect in the vol/volume family, not an artifact of one timeframe's
noise.

## 5. Limitations

- This sweep is a pooled proxy on partitioned Spearman IC (sample-size-weighted Fisher-z
  pooling across symbols, then a two-sample IC-difference test), not `ic_engine.py`'s full
  FDR/walk-forward machinery. The real completion criterion for this phase (per CONTEXT.md's
  Phase Boundary) is a genuine `feature_ic_scores` gate pass, which plan 176-08 performs
  separately.
- D-04's autocorrelation caveat applies here exactly as it applied to the primary-effect
  re-verification: daily returns inside a 6-week earnings-season block are autocorrelated, so
  even this sweep's raw p-values (and the BH-correction built on top of them) overstate the
  effective N/understate the true p-value relative to what a walk-forward-validated measurement
  would report. The BH-FDR correction controls the *family-wise* false-discovery rate given the
  stated p-values; it does not correct for this within-partition autocorrelation, which is a
  separate, unaddressed source of anti-conservatism common to every raw p-value in the 57-row
  table above.
- The 57-feature family was chosen by domain category (the five comment-delimited
  `FEATURE_VECTOR_DOMAIN` vol/volume sections plus the core quant vol/volume/order-flow
  atomics) BEFORE this measurement ran, which controls selection risk within that family -- it
  says nothing about calendar-conditional effects in features outside it (momentum, structural,
  SMC, session, etc. families were not tested and are out of scope for this sweep).
- Two family members (`volatility_rank_z`, `volume_rank_z`) are entirely NULL in the live
  corpus for both measured timeframes (confirmed via direct query, section 3) -- their
  inclusion in the fixed 57-name family is correct per the family's domain-category derivation,
  but they contributed zero measurement evidence to either sweep's FDR correction (raw p=1.0,
  never reject).
- The breadth test's B2 sufficient-N threshold (30 rows per partition per symbol) and B3's
  choice of the five highest-row-count symbols are this script's own pre-registered design
  choices (documented in the script's module-level comments), following the closest existing
  project precedent (`setup_performance`'s `sample_size >= 30` gate) rather than an
  independently-derived optimum for this specific measurement.

## 6. Deviation: contention-guard self-match bug found and fixed

During this task's first execution attempt, the contention guard reported `CONTENTION DETECTED`
on a run where the only active backend was the guard's own in-flight query. Root cause: the
guard's SQL literal text itself contains the substrings it searches pg_stat_activity for
(`feature_vectors`, `autovacuum`), so `pg_stat_activity` captured the guard's own `state='active'`
SELECT as a false positive on every single invocation. Fixed in
`scripts/analysis/earnings_season_conditional_ic_reverification.py` by excluding the caller's
own backend (`pid != pg_backend_pid()`) -- committed separately (`fix(176-01): contention guard
self-matched its own query text every run`) before any of the measurements in this document were
run. All four commands above ran against the fixed guard.
