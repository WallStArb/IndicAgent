# 292 - `feature_vectors.hmm_vol_churn`'s 9.4M corpus rows predate the WR-01 churn fix

**Filed:** 2026-08-09
**Source:** Phase 172 code review (WR-01) fix, landed after 172-05's corpus relabel had already run
**Status:** pending, not blocking

## The gap

Phase 172's code-review gate found and fixed a real bug (WR-01, commit `fdc14050`):
`_compute_symbol_tf_walk_forward`/`_compute_symbol_tf_volatility_walk_forward` computed
`hmm_churn`/`hmm_vol_churn` by concatenating every written (non-degenerate) walk-forward
segment's labels and running `_compute_hmm_churn` once over the concatenation — so the last
label before a skipped-segment gap and the first label after it were treated as direct
neighbors, fabricating a spurious label-change event (and elevated churn for up to
`churn_window` bars) at a boundary where no real transition was observed.

**Blast radius, checked before filing:**
- Legacy `feature_vectors.hmm_churn` (27,953,097 non-null rows): **unaffected**.
  `alpha.hmm.walk_forward.enabled = false` in production (confirmed via `config_state`) — the
  buggy trend-path function has never actually run; all 27.9M rows were written by the
  single-fit path (`_compute_symbol_tf`), which has no segment-gap concept at all.
- New `feature_vectors.hmm_vol_churn` (9,439,731 non-null rows): **affected**. Every one of
  these rows was written by plan 172-05's corpus-wide relabel, which ran the volatility
  walk-forward path (the only path for this column family) *before* this fix landed. Any
  (symbol, tf) cell whose walk-forward fit skipped a degenerate segment will have some
  fabricated churn values around that gap.

## What's needed

Decide whether `hmm_vol_churn`'s current corpus values are good enough to leave as-is (the
`regime_volatility` label itself — the column phase 172 actually cut `ic_engine.py` over
to — is completely unaffected; only this one auxiliary stat column is wrong at gap
boundaries) or whether a targeted recompute is warranted before `hmm_vol_churn` is trusted as
an ML training feature. If a recompute is warranted, it does not require a full corpus
relabel — only `hmm_vol_churn` needs to change; `regime_volatility`/`hmm_vol_prob_*`/
`hmm_vol_regime_prob`/`hmm_vol_entropy`/`hmm_vol_duration` are correct as written.

## Where

- `services/regime_writer.py` — the fixed churn computation (both `_compute_symbol_tf_walk_forward`
  and `_compute_symbol_tf_volatility_walk_forward`)
- `.planning/phases/172-hmm-regime-volatility-only-redesign/172-REVIEW.md` — WR-01's full
  writeup
- `.planning/phases/172-hmm-regime-volatility-only-redesign/172-05-SUMMARY.md` — the relabel run
  this todo's blast radius traces back to
