---
status: pending
priority: P1
filed: 2026-07-21
source: found while fixing todo (restore-symbol-hmm-ic-measurement, unblocks Phase 144's
  D-05 gate) -- the same silent-suppression mechanism affects the equity regime group too,
  a separate and older question nobody ever built a falsifier gate to test.
---

# `equity` group's cross-sectional-vs-per-symbol-HMM Stage-1 conditioning decision was never falsifier-tested

## What's wrong

`services/ic_engine.py`'s regime-group routing (`cross_sectional = mr_dict is not None`,
line ~965) permanently replaces a routed symbol's per-symbol HMM (`symbol_hmm`-scope)
`feature_ic_scores` measurement with cross-sectional measurement the moment that symbol
matches an enabled regime group's `tag_filter`. This was just fixed for the `rates` group
(migration 247, `alpha.regime.groups`' new per-group `dual_write_symbol_hmm` field) because
Phase 144's D-05 acceptance gate needed fresh `symbol_hmm` data to evaluate its F1 falsifier
for `TLT`.

The same silent suppression has applied to every `equity`-routed symbol (e.g. `SPY`, ~50+
symbols) since equity's cross-sectional regime group was first enabled -- verified live
2026-07-21: `SPY` has zero `symbol_hmm`-scope rows in `feature_ic_scores`. Unlike `rates`,
no D-05-equivalent falsifier gate was ever built to test whether cross-sectional labels
actually separate IC better than per-symbol HMM for equity symbols -- the choice was a
silent implementation-order side effect of when routing shipped, not an earned, proven
decision. Per this project's own principles ("earn promotion through proof," "resist
overfitting," "empirical over theoretical"), an unproven default masquerading as settled is
exactly the class of gap that should rank above "merely convenient."

## Fix direction

Not urgent, not solved by this fix. Two possible directions, need a real design decision:
1. Build an equity-scoped equivalent of Phase 144's D-05 F1/F2 falsifier gate (same
   `evaluate_frame_gate`/separation-metric machinery, different symbol universe), then
   decide whether to set `alpha.regime.groups`' `equity` entry's `dual_write_symbol_hmm=true`
   temporarily while that gate runs -- mechanism is already general-purpose (one-line APR
   change, zero code, per migration 247's design).
2. Decide the cross-sectional choice for equity is self-evidently correct enough (e.g. the
   equity cross-sectional model has a much longer track record / more validation than
   `rates` did) and explicitly document that as an accepted, reasoned default rather than
   an unexamined one -- still requires SOME evidence-gathering, not a rubber-stamp.

Do not silently accelerate this into `dual_write_symbol_hmm=true` for equity without either
building the gate or making the explicit reasoned-default case -- that would repeat the
exact "accelerate before it's justified" mistake this whole investigation started from.

## Progress (2026-07-27)

Direction 1 chosen and executed partially:

1. **Migration 262 applied** (`production/migrations/262_regime_groups_dual_write_symbol_hmm_equity.sql`)
   -- `alpha.regime.groups`' `equity` entry now carries `dual_write_symbol_hmm=true`, sibling
   of migration 247's `rates` fix. Zero-cost config change (config loads once at process
   startup, confirmed against `services/ic_engine.py`), so this has no effect on todo 183's
   currently in-flight recompute -- it takes effect on the NEXT `ic_engine` process start.
2. **Falsifier gate script written and verified**: `scripts/analysis/equity_regime_separation_gate.py`,
   generalized from Phase 144's D-05 gate (`phase144_regime_separation_gate.py`) to equity's
   ~50-symbol universe (majority-rule F1 generalization, documented in the script's own
   docstring as its own deliverable, matching the original gate's convention). **Caught a real
   bug in its own development**: the obvious symbol-universe filter
   (`instruments.contract_details->>'asset_class'='equity'`) is WRONG -- that column marks
   ETF-wrapper type, not regime-group routing. It returned 29/80 symbols (TLT, GLD, FXA, HYG,
   ...) that are actually routed to `rates`/`commodity_*`/`fx` groups and were never suppressed
   in the first place, producing a real-looking but meaningless verdict from stale data
   (`computed_at=2026-07-24`, predating migration 262). Fixed to query `instrument_tags` for
   the actual `eq_*`/`intl_*` routing tags (the same match `ic_engine.py`'s
   `_resolve_symbol_routing` uses) -- correctly returns 49 symbols, and correctly confirms SPY
   (and all 49) have zero `symbol_hmm` rows, matching this todo's original 2026-07-21 finding
   exactly. **Precondition check verified working correctly against live data before being
   trusted** -- currently reports BLOCKED-ON-NEXT-IC-ENGINE-RUN, as expected.
3. **Concrete next step, not yet done, READY NOW**: todo 183's recompute completed
   2026-07-27T21:55 UTC (single-writer discipline, D-07/D-08, is clear -- confirmed no
   `ic_engine` process is currently running). Its config load predates migration 262
   (18:19 UTC vs. 262's 15:10 UTC the following day), so the falsifier gate is still correctly
   BLOCKED as of this writing -- the fix is a fresh scoped run, not waiting further. Run a
   *scoped* pass rather than waiting for the next full corpus rebuild: `ic_engine.py --symbols
   <the 49 equity symbols> --tf <tfs> --training-window-end <champion window>` (default mode,
   NOT `--cross-sectional-only` -- the per-symbol pass is what performs the dual-write). This
   is cheap (49 symbols, not the full ~150-symbol corpus) and Phase 162's fingerprint mechanism
   should skip already-fresh cross-sectional cells, so the added cost is mostly the new
   `symbol_hmm` computation itself. Then re-run `equity_regime_separation_gate.py` (no
   `--force` needed) for the real verdict.

## References

- `services/ic_engine.py:965` -- the suppression mechanism
- `production/migrations/247_regime_groups_dual_write_symbol_hmm.sql` -- the `rates` fix
  this todo is the sibling of
- `scripts/analysis/phase144_regime_separation_gate.py` -- the D-05 falsifier gate pattern
  an equity-scoped equivalent would follow
- `docs/superpowers/specs/2026-07-21-restore-symbol-hmm-ic-measurement-for-routed-symbols-design.md`
  -- design doc that first surfaced this as an explicit out-of-scope follow-up
