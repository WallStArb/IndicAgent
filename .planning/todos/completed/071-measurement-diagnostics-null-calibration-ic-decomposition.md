# 071 — Measurement diagnostics: empirical null calibration + IC hit-rate/magnitude decomposition (CLOSED — L4-2 investigated, L4-4 re-filed as todo 090)

**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §7 (L4-2, L4-4).
**Priority:** medium — cheap, standalone, no schema dependency; good candidates to run against
the current corpus once the ic_engine incident (todo 067) is resolved and a fresh rerun completes.
**Gate:** none structurally; practically wants a healthy `feature_ic_scores` table to run against.

## Status (2026-07-09): split, both halves dispositioned

This todo covered two unrelated scopes. Both are now accounted for separately:

- **L4-2 (empirical null calibration) — investigated, not resolved-clean.** Ran via
  `scripts/ops/alpha/ops_ic_null_calibration.py` against the live corpus: 29/66 sampled cells
  evaluated, **11/29 (38%) flagged SUSPECT** (`se_ratio > 1.2`), spanning 4 of 8 sampled
  `(tf, is_pooled)` strata including high-N `5m`/`15m`, not just thin `1d`. This is evidence the
  analytic Fisher-z CI may be systematically too narrow, not the "agree, delete the bootstrap
  keys" outcome this todo originally anticipated. Durable record:
  `docs/research/measurement-ic-engine.md`'s Measurement Gaps table (new L4-2 row, dated
  2026-07-09). Follow-up work (bootstrap reopening decision, full-corpus confirmation run) is now
  its own todo: `.planning/todos/pending/091-fisher-z-ci-empirical-null-miscalibration.md`. The
  `alpha.ic.bootstrap_*` APR keys were **not** deleted — see todo 091 for why.
- **L4-4 (IC hit-rate × magnitude decomposition) — untouched, re-filed standalone.** See
  `.planning/todos/pending/090-ic-decomposition-hit-rate-magnitude.md`.

Nothing remains open on this file; it is closed and archived here for history.

## L4-2 — Empirical null calibration via circular-shift permutation (original scope, now see todo 091)

The analytic inference chain (stride subsampling → Spearman → Fisher-z CI → HAC Sharpe) rests on
assumptions (post-stride independence, Fisher-z normality at these Ns) never validated end-to-end
on this data. Diagnostic: circularly shift the forward-return series by a random large offset
(preserves autocorrelation structure, destroys alignment), recompute the full IC pipeline, repeat
~200 times for a sample of cells, compare the empirical null IC distribution against what the
analytic p-values assume.

Related dead weight this settles either way: `alpha.ic.bootstrap_*` APR keys exist with zero
readers (bottomup audit §2.3). If analytic and empirical nulls agree, delete the keys with
evidence; if not, implement the block bootstrap in the kernel and the keys finally get their
reader.

**Mechanics:** one-off script over the existing corpus + kernel functions; CPU-bound, the
existing `ProcessPoolExecutor` pattern handles it.

## L4-4 — IC decomposition: hit-rate × magnitude (original scope, now see todo 090)

A single Spearman IC conflates directional accuracy (sign agreement fraction) and magnitude
alignment (are the big predictions the big moves). Two predictors with identical IC can have
opposite profiles and decay differently (magnitude alignment usually dies first as an edge
crowds). Report both as diagnostic columns (no gate change): `sign_hit_rate` and
IC-conditional-on-large-`|prediction|`. Cheap kernel additions; sharpens Phase 143's decay
monitors for free.
