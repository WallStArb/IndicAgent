# Restore per-symbol HMM (`symbol_hmm`) IC measurement for regime-group-routed symbols

Unblocks Phase 144's D-05 acceptance gate, which cannot evaluate its F1 falsifier because
`TLT` (routed to the `rates` cross-sectional regime group since Phase 144 shipped) has not
received a fresh `symbol_hmm`-scoped `feature_ic_scores` row since 2026-07-17 — before the
most recent corpus rebuild — and never will again under the current design.

## Problem

`services/ic_engine.py:965` — `cross_sectional = mr_dict is not None` — is a single boolean
that governs an ENTIRE per-symbol IC compute pass. Any symbol matching an enabled
`alpha.regime.groups` entry's `tag_filter` gets `mr_dict` provided, which switches its whole
regime-column computation to the group's cross-sectional labels, permanently replacing (not
supplementing) its own per-symbol HMM (`feature_vectors.regime`) measurement. Verified live:
81 distinct symbols in the corpus, only 19 (the ones matching no enabled group) still carry
`symbol_hmm`-scope rows; both `equity`-routed (e.g. `SPY`) and `rates`-routed (`TLT`) symbols
have zero `symbol_hmm` rows since routing went live.

This directly breaks Phase 144's own D-05 acceptance gate
(`scripts/analysis/phase144_regime_separation_gate.py`), whose F1 falsifier requires
comparing TLT's per-symbol HMM `trending_up`/`trending_down` labels against the new `rates`
cross-sectional label — data that structurally cannot exist going forward under the current
design. This is not a data-freshness problem the next corpus rebuild fixes; it needs a code
change.

**Important scoping clarification, verified before designing a fix:** `feature_vectors.regime`
(the actual per-symbol HMM label, written by `regime_writer.py`) is computed unconditionally
for every symbol regardless of routing status — nothing is lost at that layer, and it is NOT
what todo 165's regime-stratified promotion gate consumed (`alpha_frames.regime` traces to
`feature_vectors.regime`, unaffected by this bug). The gap is narrower and more specific: only
`feature_ic_scores`'s per-symbol-HMM-conditioned IC MEASUREMENT goes dark for routed symbols.

## Design

**Framing:** dual-write is not a permanent architectural stance — it is this project's own
"shadow mode first" principle applied to Stage-1 regime-conditioning decisions. You measure
both label sources while the question of which one should stratify a group is genuinely open,
then simplify to the winner once a falsifier gate answers it. `rates` has an open question
(D-05 exists specifically to answer it) — dual-write on. `equity`'s equivalent question was
never asked (silently defaulted to cross-sectional-only the moment routing shipped, with no
falsifier gate ever built) — a separate, real gap, filed as its own follow-up todo rather than
solved as a side effect of unblocking `rates`.

**APR change:** `alpha.regime.groups` (existing JSON-list APR key) gains one new field per
group entry, sibling to `enabled`/`tag_filter`/`signal_type`/`params_prefix`:
`dual_write_symbol_hmm: bool`, defaulting to `false` for every existing group. Set to `true`
for `rates` only. No new APR key, no new schema surface beyond one field — reuses the existing
per-group config list exactly as designed.

**Code change — extraction, not duplicated logic.** `_compute_symbol_tf`
(`services/ic_engine.py:780-1256`) already fetches `feature_vectors.regime` unconditionally at
line 851 — the expensive I/O (feature-matrix fetch, forward-return alignment, `~line 834-954`)
is shared regardless of routing status. Only the clustering + per-scale IC/bootstrap loop
(`~line 975-1256`) needs to run twice for a dual-write symbol. Extract that loop into a pure
helper:

```python
def _compute_regime_ic_cells(
    X_aligned, returns_mat, complete_mat, regime_labels, regime_scope, ...
) -> tuple[list[dict], list[float], list[int]]:
    ...
```

taking the aligned feature/return matrices plus one regime-label array and a `regime_scope`
string, returning result rows + parallel p-value bookkeeping for that pass. `_compute_symbol_tf`
calls it once with the cross-sectional label array + `regime_scope="cross_sectional"` (today's
behavior, unconditional whenever `mr_dict` is provided), and — only when the symbol's group
has `dual_write_symbol_hmm=true` — calls it again with the original `regime_aligned` array
(the per-symbol HMM labels already fetched) + `regime_scope="symbol_hmm"`, merging both
passes' results/p-values before returning. This is a genuine separation-of-concerns
improvement in code this fix already has to touch (separates "which labels to measure
against" from "how to measure IC for a given label set") — not scope creep.

**No DAG/topology change.** Same inputs (`feature_vectors`, `forward_returns`,
`market_regimes`), same output table (`feature_ic_scores`), more rows only for dual-write
symbols. No new tables, no new services, no new consumers.

**No new concurrency pattern.** The worker is already `ProcessPoolExecutor`-dispatched,
CPU-bound (clustering, bootstrap). A sequential second pass inside the same worker is correct
and simple — introducing intra-worker async/threading for CPU-bound sequential work would add
complexity with no throughput benefit.

**BH-FDR interaction — verified, no change needed.** `_backfill_bh_fdr`
(`services/ic_engine.py:2403-2463`) is deliberately corpus-wide, one `multipletests()` call
across every pending row in the training window regardless of `regime_scope` — a prior bug
("~232x FDR inflation") came specifically from scoping this too narrowly. The 19 currently-
unrouted symbols' `symbol_hmm` rows already sit in this same shared family today; adding
`rates`-group `symbol_hmm` rows is more of the same kind of row this design was already built
to absorb, not a new methodological question. Giving these rows their own separate FDR family
would reintroduce the exact bug pattern the corpus-wide design already fixed. No change to
`_backfill_bh_fdr` itself.

**Backfill scope — targeted, not a full corpus rebuild.** `ic_engine.py` already supports
`--symbols`. Re-run scoped to the 12 `rates`-group members: `TLT IEF SHY HYG LQD EMB AGG TIP
BIL MUB PFF EDV` (verified live against `instrument_tags` matching `fi_%`).

## Out of scope — filed as new follow-up todo

**Equity group's cross-sectional-vs-per-symbol-HMM Stage-1 conditioning question was never
falsifier-tested** — it silently defaulted to cross-sectional-only the moment routing shipped,
with no D-05-equivalent gate ever built to test whether that default is actually correct. Real
gap, not urgent (no active decision blocked on it today), not solved by this fix — the general
`dual_write_symbol_hmm` mechanism this fix builds makes flipping `equity`'s flag a one-line APR
change whenever that gate gets built, zero code required.

## Testing

- Unit test for the extracted `_compute_regime_ic_cells` helper: given a fixed `X_aligned`/
  `returns_mat`/`complete_mat` and two different label arrays, confirms each call's output
  rows carry the `regime_scope` passed to that call, and that calling it twice with different
  label arrays produces the union of both result sets (no cross-contamination between passes).
- Unit test confirming `_compute_symbol_tf`'s dual-write branch only fires when
  `dual_write_symbol_hmm=true` for the symbol's routed group, and that the non-dual-write path
  (today's behavior for `equity` and every disabled group) is byte-for-byte unchanged.
- Live verification (not just unit tests): scoped `ic_engine.py --symbols <rates group>`
  re-run, confirm fresh `symbol_hmm` rows exist for `TLT` post-run, then re-run
  `phase144_regime_separation_gate.py` and confirm F1 is now evaluable (no longer
  INCONCLUSIVE).
