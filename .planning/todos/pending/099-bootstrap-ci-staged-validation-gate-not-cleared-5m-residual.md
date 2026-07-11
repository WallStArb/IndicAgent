---
status: pending
priority: P1
filed: 2026-07-11
source: Phase 143.1-01 (Component A, todo 091) staged-validation gate
---

# Bootstrap CI staged-validation gate did not clear the pre-committed bound (5m residual)

## Finding

Phase 143.1-01 replaced `_fisher_z_ci` with the corrected circular block bootstrap
(`_circular_block_bootstrap_ic`, re-ranks the resampled subset per iteration -- the
pre-ranking bug is genuinely fixed) at all 3 `services/ic_engine.py` call sites. The
staged-validation diagnostic (`scripts/ops/alpha/ops_ic_null_calibration.py
--ci-method bootstrap`) was run against the same 66-72 cell stratified sample that
previously reported 38% SUSPECT under Fisher-z (11/29 evaluated), per the pre-committed
pass threshold recorded in `docs/plans/methodology-change-ledger.md` (E6): `<= 2`
SUSPECT cells out of 66-72 evaluated AND no single `(tf, is_pooled)` stratum with more
than 1 SUSPECT cell.

**Result: the bootstrap is a substantial, real improvement (6-8/29 = 21-28% SUSPECT vs.
38% under Fisher-z) but does NOT clear the pre-committed bound.** The residual is
concentrated in the `tf=5m, is_pooled=False` stratum (3-4 SUSPECT cells depending on
`--n-permutations`, vs. the `<= 1` bound), specifically:
- `ret_autocorr_1` / VNQ -- an autocorrelation feature, expected to have long memory
- `month_sin` / EFA
- `ctf_momentum` / XHB, IBB -- momentum features, also expected to have some persistence

## Ruled out as the cause (empirically checked, not assumed)

- **Not small-sample noise in the null benchmark:** increasing `--n-permutations` from
  200 to 1000 did NOT reduce the SUSPECT count (6 -> 8; the same 5m cells stayed flagged
  or got worse). A noise-driven false positive would be expected to *decrease* with more
  permutations, not increase.
- **Not an under-sized bootstrap block:** re-running the 5m cells at
  `bootstrap_block_size` = 78 (APR default, ~1 trading day), 156, 390, and 780 (~10
  trading days) produced an IDENTICAL 4/7 SUSPECT count for 5m at every block size
  tested, with `se_ratio` for the flagged cells staying flat or slightly WORSENING at
  larger block sizes (e.g. `ret_autocorr_1`/VNQ: 1.96 -> 2.06 -> 2.24 -> 2.38 as block
  size grows 78 -> 780). If insufficient block length were the cause, se_ratio should
  improve monotonically as block size grows toward capturing the full autocorrelation
  structure -- it does not.

## Not yet investigated (this todo's scope)

- Whether these specific features (autocorrelation / momentum) have a structurally
  different variance regime (e.g., regime-conditional heteroskedasticity, volatility
  clustering) that neither Fisher-z's CLT assumption NOR a stationary block bootstrap
  captures -- would need a regime-conditional or wild-bootstrap variant, a genuinely
  different (and more complex) statistical machinery, not a parameter tweak.
- Whether the `_circular_shift_null`-based empirical benchmark itself (single global
  circular shift, not a block bootstrap) is the right ground truth to validate the
  block bootstrap against for exactly these high-persistence features -- the two
  methods make different assumptions and may legitimately disagree on exactly the
  cells where persistence is strongest.
- Whether these specific 5 features are rare enough in the full ~150-feature corpus
  that a slightly elevated false-narrow-CI rate on them specifically is an acceptable,
  bounded residual risk vs. blocking the entire corpus re-run indefinitely.

## Decision needed

Per Phase 143.1-01's plan (`143.1-01-PLAN.md`), this is an explicit HARD sequencing
gate: "Plan 07's corpus-wide re-run must not start until this passes." The gate has NOT
passed as measured. The bootstrap CI code itself was still shipped (Tasks 1-2 of
143.1-01) because it is unconditionally correct relative to what it replaced (fixes a
proven pre-ranking bug, substantially reduces but does not eliminate the SUSPECT rate)
-- but Plan 07 (or any future corpus-wide re-run task) should NOT proceed until either:
(a) this residual is investigated and resolved/explained, or (b) the project owner
makes an explicit, recorded decision to accept the residual risk and proceed anyway
(which would itself need a methodology-change-ledger entry, since it changes the
pre-committed gate's outcome after seeing the result).

## References

- `docs/plans/methodology-change-ledger.md` E6 entry (pre-committed threshold + measured
  result)
- `.planning/phases/143.1-measurement-and-eligibility-integrity-fisher-z-ci-bootstrap-/143.1-01-SUMMARY.md`
- `scripts/ops/alpha/ops_ic_null_calibration.py --ci-method bootstrap`
