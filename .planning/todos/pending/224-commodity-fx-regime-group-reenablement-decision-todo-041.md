---
status: pending
priority: P2
filed: 2026-08-01
source: session review of commodity/fx regime-group disablement while discussing symbol-universe
  scope with user. Revised same day: fx confirmed collision-free and ready to enable; commodity
  sub-groups' thinness identified as a separate, near-term-fixable axis (unify into one
  `commodity` group) distinct from the equity-collision axis now owned by todo 225.
---

# Commodity/FX regime-group re-enablement (todo 041's original taxonomy question, refreshed)

## Problem

`alpha.regime.groups` (migration 222) ships 4 of 6 groups disabled: `commodity_energy`,
`commodity_metals`, `commodity_agri`, `fx`. Both `commodity_momentum_ts.py` and
`fx_dollar_carry.py` are fully implemented, not stubs -- they've shipped `enabled: false`
since inception, gated on "todo 041" (tag exposure-vs-sensitivity taxonomy audit), referenced
across `ROADMAP.md`/`roadmap-decision-log.md`/Phase 144 docs but never filed as its own
standalone pending todo until this session.

This turned out to bundle two genuinely separate problems, now split apart:

**1. `fx` has no problem at all.** Verified (2026-08-01): `UUP`/`FXA`/`FXE`/`IBIT` carry zero
tag collisions with any other enabled group, on either Job 1 (`cross_sectional_regime_model.py`'s
peer-averaging) or Job 2 (`ic_engine.py`'s `_build_symbol_regime_class` routing). It can be
enabled today with zero code changes and zero crash risk. The only reason it hasn't happened is
sequencing -- see Fix.

**2. Commodity groups have two independent problems, not one.**
- **Equity-tag collision (Job 2, single-membership routing):** `OIH`/`XLE`/`XOP`/`AMLP`
  (energy) and `GDX` (metals) all carry both an `eq_*` tag (matching the enabled `equity`
  group) and a `commodity_*` tag simultaneously. `ic_engine.py`'s router requires exactly one
  group per symbol and raises `AmbiguousRegimeGroupError` on multi-match by design (never
  silently picks one). These 5 symbols are *already* routed to `equity` today (since `equity`
  is enabled and they match it); enabling any commodity sub-group makes them double-eligible
  with no resolution rule. **This axis is now owned by
  [225](225-multi-vector-systematic-regime-join-hybrid-sensitivity-symbols.md)** -- its
  gradient-conditional IC approach lets a hybrid symbol answer to both axes independently
  instead of forcing a pick. Not solved by anything in this todo.
- **Group thinness (Job 1, peer-set size):** independent of the collision question above, the
  three commodity sub-groups are each too small on their own to compute a reliable
  cross-sectional signal. `commodity_energy` has 4 members (all 4 collide with equity anyway),
  `commodity_metals` has 5 (only `GDX` collides), `commodity_agri` has exactly 1 (`DBA` --
  unusable alone). `commodity_momentum_ts.py`'s own docstring targets 4-8 instrument peer
  groups; `commodity_agri` doesn't clear that bar at all. **This axis is fixable now,
  independent of 225** -- see Fix step 2.

Bonus finding while checking group membership: `DBC` (Invesco DB Commodity Index -- the
cleanest possible commodity holder, GSCI-weighted, zero equity-tag collision) carries a
`commodity_broad` tag that isn't matched by *any* current group's `tag_filter`. It's currently
routed to nothing, a pure oversight independent of both problems above.

## Why this matters

- Symbols tagged `fx_*`/`commodity_*` (9 distinct: 4 energy, 5 metals, 1 agri, 5 fx/crypto, plus
  `DBC` unrouted entirely) currently get pooled IC only, never regime-stratified IC -- a real
  measurement gap relative to the equity/rates groups.
- Every new-instrument or config-affecting corpus change re-triggers the full pipeline
  (historically 20-30+ hours); sequencing fx-now / commodity-unification-next / 225-after
  avoids wasted rebuild cycles on groups that would immediately crash or produce thin,
  unreliable signal if enabled as-is.
- Unifying the commodity sub-groups now (rather than waiting on individual sub-group expansion)
  matches the project's stated long-term direction of scaling the securities universe against
  future cluster compute -- start with one coarser, statistically sturdier `commodity` group
  now; re-split into energy/metals/agri later once each sub-group has enough dedicated members
  on its own. Not a permanent design, a staged one.

## Fix

**Near-term, unblocked, not gated on todo 225:**

1. **DONE 2026-08-01** (migration 280): `fx` flipped to `enabled: true` in
   `alpha.regime.groups`, plus `dual_write_symbol_hmm: true` (not originally scoped in this
   step, added to avoid reproducing the same per-symbol-HMM-measurement gap already fixed
   twice for rates/equity via migrations 247/262). Confirmed zero effect on the currently
   in-flight `ic_engine` run (started 2026-07-30 17:08:55 EDT, config loaded once at process
   startup) -- takes effect on the NEXT `cross_sectional_regime_model.py` +
   `ic_engine.py` invocation.
2. Unify `commodity_energy`/`commodity_metals`/`commodity_agri` into a single `commodity`
   group (~10 members once combined: `OIH`/`XLE`/`XOP`/`AMLP`/`GLD`/`SLV`/`PPLT`/`DBB`/`GDX`/
   `DBA`, plus `DBC` once its `commodity_broad` tag is added to the merged group's
   `tag_filter`). Clears `commodity_momentum_ts.py`'s 4-8 instrument design floor comfortably;
   resolves `commodity_agri`'s N=1 problem without a separate expansion effort. **This does
   NOT resolve the equity-tag collision** -- `AMLP`/`GDX`/`OIH`/`XLE`/`XOP` still match both
   `equity` and the unified `commodity` group; enabling the unified group still needs either
   225's fix or an accepted interim exclusion of those 5 symbols from one axis. Don't let this
   step create a false impression that unifying alone unblocks enablement.
3. Fix `DBC`'s routing gap -- add `commodity_broad` to the (unified, per step 2) `commodity`
   group's `tag_filter`. Free N+1, zero collision risk.
4. Re-split the unified `commodity` group back into energy/metals/agri once the securities
   universe has grown enough that each sub-group can independently clear the 4-8 instrument
   floor -- track against the long-term universe-scaling direction, not on a fixed date.

**Blocked on [225](225-multi-vector-systematic-regime-join-hybrid-sensitivity-symbols.md):**

5. Resolve the `AMLP`/`GDX`/`OIH`/`XLE`/`XOP` equity-collision axis via 225's gradient-
   conditional IC measurement (or, if 225 stalls, revisit an explicit interim precedence
   exception as a documented, deliberate fallback -- not a default).
6. Once resolved, the unified `commodity` group (or its later re-split successors) can be
   enabled without `AmbiguousRegimeGroupError` risk.

## References

- `production/migrations/222_regime_group.sql` -- original schema/APR seed, groups shipped
  disabled by design
- `src/intelligence/regime_signals/commodity_momentum_ts.py`,
  `src/intelligence/regime_signals/fx_dollar_carry.py` -- fully implemented, `enabled: false`
  noted in each module's own docstring; `commodity_momentum_ts.py`'s docstring states the 4-8
  instrument peer-group design target this todo's unification step targets
- `docs/research/roadmap-decision-log.md` -- "Why commodity/fx enablement is blocked" + "Why
  OIH/XLE staying in equity breadth ... isn't a blocker" decision notes
- `.planning/phases/146-empirical-instrument-tag-calibrator-planned/146-CONTEXT.md` --
  confirms todo 041 was folded into the canonical design doc, not resolved as its own decision
- `docs/plans/2026-06-27-etf-universe-expansion.md` -- 58->80 ETF expansion that populated
  these groups' tags in the first place
- `.planning/todos/pending/225-multi-vector-systematic-regime-join-hybrid-sensitivity-symbols.md`
  -- owns the equity-collision axis; this todo owns fx-enablement and commodity-group-thinness,
  explicitly not the same problem
- Live queries used to confirm current state:
  `SELECT symbol, array_agg(tag) FROM instrument_tags WHERE symbol IN ('OIH','XLE','XOP','AMLP','GDX') GROUP BY symbol`
  and `SELECT symbol, array_agg(tag) FROM instrument_tags WHERE symbol = 'DBC' GROUP BY symbol`
- **Cross-link added 2026-08-01 (consolidation pass):** `docs/research/stratification-dimension-unification.md`
  -- this todo's `regime_group` enablement work is the producer side of that doc's contract;
  the doc's 2026-08-01 reconciliation section now cites this todo directly for fx/commodity
  status.
