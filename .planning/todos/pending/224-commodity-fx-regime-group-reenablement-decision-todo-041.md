---
status: pending
priority: P2
filed: 2026-08-01
source: session review of commodity/fx regime-group disablement while discussing symbol-universe scope with user
---

# Commodity/FX regime-group re-enablement decision (todo 041's original taxonomy question, refreshed)

## Problem

`alpha.regime.groups` (migration 222) ships 4 of 6 groups disabled: `commodity_energy`,
`commodity_metals`, `commodity_agri`, `fx`. Both `commodity_momentum_ts.py` and
`fx_dollar_carry.py` are fully implemented, not stubs -- they've shipped `enabled: false`
since inception, gated on "todo 041" (tag exposure-vs-sensitivity taxonomy audit),
referenced across `ROADMAP.md`/`roadmap-decision-log.md`/Phase 144 docs but never filed as
its own standalone pending todo file until now.

**Concrete blocker, confirmed live in today's data (2026-08-01):** `OIH`, `XLE`, `XOP` all
carry both an `eq_*` tag (`eq_sector`/`eq_sub_sector`, matching the enabled `equity` group)
and `commodity_energy_crude` (matching the disabled `commodity_energy` group) simultaneously.
The router raises `AmbiguousRegimeGroupError` -- fail loud, never silently pick one -- the
instant a symbol matches more than one *enabled* group. Flipping `commodity_energy.enabled`
to `true` today would crash the next `ic_engine` run on the first of these three symbols it
hits.

Phase 146 (Empirical Instrument Tag Calibrator, closed 2026-07-17) folded todo 041's
taxonomy-soundness question directly into `docs/research/stratification-instrument-tag-calibrator.md`
rather than resolving it as a standalone decision -- but Phase 144's own completion notes
(2026-07-22, five days *after* Phase 146 closed) still list commodity/fx enablement as
blocked on it, and the OIH/XLE/XOP collision is still live in the data today. Nobody has come
back to actually apply the taxonomy decision and flip the flags.

## Why this matters

- Symbols tagged `fx_*`/`commodity_*` (9 distinct: 4 energy, 5 metals, 1 agri, 5 fx/crypto)
  currently get pooled IC only, never regime-stratified IC -- a real measurement gap for
  those symbols relative to the equity/rates groups.
- `commodity_agri` has only 1 tagged instrument (`DBA`) against the module's own stated 4-8
  instrument design range (`commodity_momentum_ts.py` docstring) -- even after the
  taxonomy/routing question is resolved, agri may need more coverage before its regime
  signal is statistically meaningful. Deliberately not filing that as a separate expansion
  todo yet -- see Fix step 3.
- Every new-instrument corpus change re-triggers the full 6-step pipeline (historically
  20-30+ hours); resolving the routing question before touching instrument coverage avoids
  wasted rebuild cycles on groups that would immediately crash if enabled.

## Fix (not yet started)

1. Decide the actual tag-routing rule for dual-exposure symbols (OIH/XLE/XOP-shaped: literal
   sector ETF + commodity-sensitivity tag). Options sketched in
   `docs/research/roadmap-decision-log.md`'s Phase 144 section: (a) keep them in equity by
   convention (current default, already judged "not a blocker" for Job-1 peer-set purity as
   of 2026-07-22, revisit only if Phase 146 tag calibration shows material contamination --
   has anyone actually checked that since?), (b) give commodity/exposure tags lower routing
   priority than sensitivity/sector tags, (c) exclude dual-tagged symbols from whichever
   group activates second.
2. Re-verify Phase 146's tag calibration output
   (`docs/research/stratification-instrument-tag-calibrator.md`) for whether it actually
   flags OIH/XLE/XOP-style contamination now that real data exists -- its 2026-07-17 closure
   predates Phase 144 completing and predates the current corpus.
3. Once routing is decided: flip `commodity_energy`/`commodity_metals`/`fx` to
   `enabled: true` in `alpha.regime.groups` (`config_state`), confirm zero
   `AmbiguousRegimeGroupError` on the current instrument set, and separately assess whether
   `commodity_agri` (N=1) needs instrument-count expansion before its group is worth enabling
   too -- don't conflate that with the routing decision.
4. Batch into a future scheduled corpus rebuild rather than triggering a standalone one (same
   discipline as todos 155/171).

## References

- `production/migrations/222_regime_group.sql` -- original schema/APR seed, groups shipped
  disabled by design
- `src/intelligence/regime_signals/commodity_momentum_ts.py`,
  `src/intelligence/regime_signals/fx_dollar_carry.py` -- fully implemented, `enabled: false`
  noted in each module's own docstring
- `docs/research/roadmap-decision-log.md` -- "Why commodity/fx enablement is blocked" + "Why
  OIH/XLE staying in equity breadth ... isn't a blocker" decision notes
- `.planning/phases/146-empirical-instrument-tag-calibrator-planned/146-CONTEXT.md` --
  confirms todo 041 was folded into the canonical design doc, not resolved as its own
  decision
- `docs/plans/2026-06-27-etf-universe-expansion.md` -- 58->80 ETF expansion that populated
  these groups' tags in the first place
- Live query used to confirm the collision is still current:
  `SELECT symbol, array_agg(tag) FROM instrument_tags WHERE symbol IN ('OIH','XLE','XOP') GROUP BY symbol`
