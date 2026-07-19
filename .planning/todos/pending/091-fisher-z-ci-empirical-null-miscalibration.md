# 091 — Fisher-z analytic CI is empirically miscalibrated: 38% SUSPECT rate across most strata

**Source:** L4-2 empirical null calibration diagnostic, run 2026-07-09. Supersedes the L4-2 scope
of todo 071 (see `docs/research/measurement-ic-engine.md`'s Measurement Gaps table, new row dated
2026-07-09, for the durable record). Evidence trail: `scripts/ops/alpha/ops_ic_null_calibration.py`,
commits `93824f57` (circular-shift null kernel function), `20f639d4` (pooled-sentinel sampling
fix), `640050f1` (the n_valid-vs-pre-filter-count comparison fix that produced the trustworthy
final run).

## The finding, precisely

Circular-shift permutation (200 resamples/cell, seed=42) was run against a 66-cell stratified
sample of `feature_ic_scores` at the CI/FDR gate boundary. Of the 66 sampled cells, 29 were
evaluated (37 skipped: insufficient N after completeness filtering, unmapped lookahead scales, or
genuine remaining corpus drift — the earlier "corpus drift" explanation for most skips was itself
found to be wrong by code review and fixed in `640050f1`; residual skips are smaller and more
mundane now).

**11 of 29 evaluated cells (38%) flagged SUSPECT** (`se_ratio > 1.2`, meaning the empirical null's
standard error exceeds the analytic Fisher-z prediction by more than 20%).

SUSPECT cells span **4 of 8 sampled `(tf, is_pooled)` strata**:
- `tf=5m, is_pooled=false`: 2 SUSPECT
- `tf=15m, is_pooled=false`: 1 SUSPECT
- `tf=1d, is_pooled=false`: 3 SUSPECT
- `tf=1d, is_pooled=true`: 5 SUSPECT

This is **not** confined to one corner of the design space (e.g. not just the already-known-thin
`1d` timeframe) — `5m` and `15m`, which have abundant N (tens of thousands of observations per
cell), also show SUSPECT cells.

Several SUSPECT cells show severe non-normality alongside the SE gap, not just a wider-than-
expected variance: `hurst`/BIL/1d (`se_ratio=2.242`, Shapiro `p=0.0000`), `ret_autocorr_1`/VNQ/5m
(`se_ratio=2.200`, Shapiro `p=0.0000`). This suggests the Fisher-z CLT-normality assumption itself
may be breaking down for some features, not only the SE magnitude being off.

**Two distinct mechanisms, not one.** The 5 `tf=1d, is_pooled=true` SUSPECT cells are consistent
with the already-documented **P6 cross-sectional effective-N gap** (`docs/research/measurement-ic-engine.md`
Measurement Gaps table): 58 symbols on the same bar share regime/macro exposure and are not
independent observations, so `1/sqrt(n-3)` understates the true SE there by construction — not new
evidence the formula itself is broken. The other 6 SUSPECT cells (`ret_autocorr_1`/VNQ/5m,
`range_pct_slow`/HYG/5m, `range_pct_slow`/EWY/15m, `efficiency_ratio_slow`/BIL/1d,
`overnight_gap`/BIL/1d, `hurst`/BIL/1d) are all `is_pooled=false` — per-symbol cells with no
cross-sectional pooling involved — so P6 cannot explain them; that SE inflation is the genuinely
novel finding, most plausibly residual temporal autocorrelation that stride-subsampling didn't
fully remove (fittingly, `ret_autocorr_1`/VNQ/5m, an autocorrelation-named feature, is the most
extreme SUSPECT cell at `se_ratio=2.20`).

Full cell-by-cell table: `.superpowers/sdd/task-2-live-run-output.md` (this session's captured
stdout, the twice-corrected authoritative run — do not use the two earlier buggy runs referenced
inside that file for numbers).

## Affected mechanism

`_fisher_z_ci` in `src/intelligence/statistics/ic_math.py` — the analytic confidence interval this
diagnostic tested against the empirical permutation null.

## Downstream exposure

`_fisher_z_ci` is the exact mechanism behind `ic_ci_lower`, which gates:
- BH-FDR pass/fail (`passes_fdr` in `feature_ic_scores`)
- Walk-forward validation
- The **EIC-04 hard gate** that was just used to unblock Phase 142B (PASS at a razor-thin
  35/1585 = 2.21%, a threshold recalibrated from 0.60 based on a p-value histogram interpretation
  that itself assumes this same CI machinery is trustworthy)

A 38% SUSPECT rate spanning most strata, including high-N timeframes, is evidence the analytic CI
may be systematically too narrow — which would mean some currently-passing gates (individual
features, ensemble variants E1/E2, and possibly EIC-04 itself) are more marginal than their
reported p-values suggest. This todo states that connection factually; it does not conclude
whether EIC-04/Phase 142B's unblocking should be reconsidered — that is a decision for the project
owner, not resolved here.

## Proposed next steps

1. **A full-corpus confirmation run may be warranted before acting**, given the stakes (this
   touches every CI-gated promotion in the stack). The 66-cell stratified sample is a diagnostic,
   not an exhaustive census — before reopening bootstrap machinery, consider whether a broader run
   (all strata, more cells per stratum, or the full `feature_ic_scores` table) changes the picture
   materially, or just tightens the same conclusion. Any such run should stratify `is_pooled=true`
   vs. `is_pooled=false` results explicitly and report them separately, so the P6 cross-sectional
   effect and the novel per-symbol autocorrelation effect don't get re-conflated into one number.
2. **Reopening circular block bootstrap in the kernel is the natural fix per the original design
   doc** (`docs/plans/2026-07-09-ic-null-calibration-design.md`), but treat this as the leading
   candidate, not a foregone conclusion, until step 1's confirmation (or the project owner's
   explicit call) settles it. If pursued: implement circular block bootstrap in `ic_math.py`,
   giving the currently-dead `alpha.ic.bootstrap_seed`, `alpha.ic.bootstrap_resamples`, and
   `alpha.ic.bootstrap_block_size.{5m,15m,1h,1d}` APR keys (migrations 161, 165, 177; zero readers
   since circular block bootstrap was removed from `ic_engine.py`) their first real reader.
3. Do **not** delete the `alpha.ic.bootstrap_*` APR keys — this todo is the reason they need to
   stay live pending the decision above.
4. Whatever is decided, record the decision explicitly in the methodology-change-ledger (per this
   project's existing pre-commitment convention for gate-affecting decisions) before any gate
   threshold or promotion status is touched as a consequence.

**Priority:** high — this bears directly on whether currently-passing gates (feature promotion,
BH-FDR, EIC-04) are as reliable as their reported p-values claim. Not urgent to execute
immediately, but should not sit indefinitely given what it touches.

## Confirmation run, 2026-07-19 — post-bootstrap-fix, against the fresh 143.1-07 corpus

`_circular_block_bootstrap_ic` (143.1-01) is unconditionally live in production
(`ic_engine.py:1963`, no flag gate) — the 143.1-07 corpus re-run that finished 2026-07-19 already
computed `feature_ic_scores` CIs via bootstrap, not Fisher-z. Re-ran
`scripts/ops/alpha/ops_ic_null_calibration.py --ci-method bootstrap` against this fresh vintage
(`training_window_end=2025-12-24 05:15:00+00:00`) to check whether the fix actually resolved the
miscalibration. Note: the script had a schema-drift bug (`mr.asset_class` — a column that no
longer exists since Phase 144's regime-model rewrite; fixed to `mr.regime_group`) blocking any run
until today.

**Result: 4/19 evaluated cells SUSPECT (21%), down from 11/29 (38%) pre-bootstrap.** Real
improvement, not fully resolved. Sharper than the original diffuse finding: 3 of the 4 SUSPECT
cells are the *same feature*, `ctf_momentum` (XLY/5m, EWJ/5m, QQQ/15m), plus one `flight_quality`
cell (VWO/1h). All 4 are `is_pooled=False` (per-symbol, not the P6 cross-sectional effective-N
mechanism). This looks like a feature-specific autocorrelation problem — `ctf_momentum`'s true
decay structure may exceed the current `bootstrap_block_size` for its scale — rather than a
general bootstrap-methodology failure across the corpus. Caveat: 49/68 sampled cells were skipped
(insufficient N / stratum mismatch) this run, a higher skip rate than the original 37/66 —
smaller effective evidence base than ideal; a stratified sample specifically targeting
`ctf_momentum`/`flight_quality` cells would settle whether this generalizes to those features'
other cells or is isolated to these three.

**Resolved by Fable 5 review, 2026-07-19** (`docs/research/fable-2026-07-19-lookahead-and-target-calibration-review.md`,
Q2): the mechanism is confirmed, not just hypothesized. Measured integrated autocorrelation time
vs. each feature's tf bootstrap block size directly: `ctf_momentum` runs ~4x its block size
consistently across tfs (structural — it's HTF-derived, not incidental) and `flight_quality`
(a TLT/SPY macro-divergence feature) runs ~750x its block size at 1h (no feasible block size
fixes this — a months-scale decorrelation has almost no independent observations at intraday
tfs). Per this project's principles (proof before promotion, resist overfitting, instrument
everything): **do not per-feature-tune block size** (overfitting one dial to one symptom, and it
doesn't help `flight_quality` at all) — the correct close-out is standing instrumentation: a
dependence-length diagnostic + lower-trust flag, filed as
[145](145-bootstrap-dependence-length-flag.md). **091 stays open until that flag lands** — the
21% residual is acceptable to carry forward only WITH the flag in place, not silently. When 145
ships, close 091 and record the decision (this residual rate, the flag's existence, the
deliberate non-fix of per-feature block sizes) in `docs/plans/methodology-change-ledger.md`.
