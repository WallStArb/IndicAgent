---
status: pending
priority: P2
filed: 2026-07-22
source: recorded as a "trigger, not yet executed" note in ROADMAP.md/STATE.md when closing
  Phase 144's D-05 gate (symbol_hmm restoration fix) -- filing as its own todo so it can't
  silently ride forever as prose buried in a large planning doc.
---

# Re-verify Phase 144 D-05's F1 result on the full corpus before reverting `rates.dual_write_symbol_hmm`

## What's wrong (nothing, yet -- this is a "don't forget" item, not a bug)

`alpha.regime.groups`' `rates` entry has `dual_write_symbol_hmm=true` (migration 247,
2026-07-22), deliberately temporary — the design's own comment frames it as shadow-mode
measurement "while that question is open," per this project's "shadow mode first"
principle. Phase 144's D-05 gate then answered the question for `rates`: F1 not triggered
(TLT's per-symbol HMM stays deficient relative to cross-sectional), so per the pre-committed
decision, `rates` should eventually simplify back down to single-pass cross-sectional-only
measurement (Musk step 2 — delete once genuinely proven).

**But that verdict was produced from a scoped 12-symbol verification run** (`ic_engine.py
--symbols TLT IEF SHY HYG LQD EMB AGG TIP BIL MUB PFF EDV`), not a full corpus rebuild.
Flipping `dual_write_symbol_hmm` back to `false` on the strength of a partial sample would
be premature — the risk of reverting too early is silently losing the dual-write safety net
before the result is actually stable at full scale. The risk of never revisiting it is the
opposite failure: paying double IC-measurement cost for `rates` forever, on a question
that's already been answered, because nobody remembered to check.

## Fix direction

When the next full corpus rebuild runs (whatever triggers it — likely batched with
[146](146-lookahead-grid-per-tf-recalibration.md)'s grid fix and
[155](155-price-sanity-status-historical-backfill.md)'s backfill effects, same "ride the next
rebuild, don't trigger one standalone" logic those two already follow):

1. Re-run `scripts/analysis/phase144_regime_separation_gate.py` against the full-corpus data.
2. Confirm F1 still does not trigger for `rates`/TLT (i.e., the 12-symbol scoped result
   holds at full scale, not an artifact of the smaller sample).
3. If confirmed stable: write a new migration setting `rates.dual_write_symbol_hmm=false`,
   closing this todo. If NOT confirmed (F1 flips, or results are ambiguous at full scale):
   do not revert — re-open the question, don't force a premature simplification either way.

Not urgent — `dual_write_symbol_hmm=true` costs extra compute per `ic_engine` run for
`rates`'s ~12 symbols, not correctness. No rush to close this before the next rebuild
naturally happens anyway.

## References

- `production/migrations/247_regime_groups_dual_write_symbol_hmm.sql` — sets the flag this
  todo tracks reverting
- `.planning/ROADMAP.md`'s Phase 144 section — full D-05 verdict and this exact trigger,
  recorded in prose there; this todo exists so it isn't only prose
- `scripts/analysis/phase144_regime_separation_gate.py` — the gate to re-run
