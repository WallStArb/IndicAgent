---
status: pending
priority: P2
filed: 2026-08-01
source: session discussion of todo 224 (commodity/fx regime-group enablement) with user -- user
  correctly identified that forcing single-group routing discards real multi-asset-class
  correlation signal for hybrid-sensitivity instruments. Revised same day (2026-08-01) after
  finding the codebase already has the statistical primitives for a better mechanism than the
  originally-proposed discrete multi-membership routing rewrite.
---

# Gradient-conditional IC sensitivity across tag vectors (partial/magnitude-conditional IC
# over calibrated `instrument_tags.weight`, not discrete regime-group routing)

## Problem

Originally filed as "multi-vector systematic-regime join": `regime_group`'s single-membership
routing (`ic_engine.py`'s `_build_symbol_regime_class`, `AmbiguousRegimeGroupError`) forces a
hybrid-sensitivity symbol like `XLE` into exactly one regime group, discarding whichever axis
loses. The original framing (superseded by this rewrite, see below) proposed extending
`symbol_regime_class` from `dict[str, str]` to a multi-membership structure and rewriting the
8+ call sites that consume it in `ic_engine.py`'s cross-sectional pass.

**Revised mechanism (2026-08-01):** `src/intelligence/statistics/ic_math.py` already has the
statistical primitives to answer the underlying question -- "does this symbol's forward-return
predictability genuinely depend on its exposure to factor X" -- without ever assigning a
symbol to a discrete bucket at all:

- **`partial_spearman_ic(x, y, controls, condition_max)`** (line 703) -- partial Spearman IC
  of a feature against forward returns, controlling for one or more covariate series. Its own
  docstring: "every Renaissance interaction primitive has exactly 2 parent atomics
  (`feature_registry.parent_features`)" -- this is already shaped for exactly this use.
- **`magnitude_conditional_ic(X_raw, y_raw, percentile)`** (line 817) -- IC recomputed over
  the subset of bars above a magnitude threshold. Currently used for the feature's own
  |prediction| magnitude (IC-decomposition Component B, todo 090); the same shape generalizes
  to thresholding/interacting on a calibrated tag weight instead.
- **`_circular_block_bootstrap_ic` / `circular_block_bootstrap_ic_serial`** -- the existing
  per-symbol block-bootstrap CI machinery every other IC number in this codebase is gated
  through. No new statistical framework needed.

For every `(symbol, tag)` pair where `instrument_tags.weight` (Phase 146's calibrated factor-
beta loading) is non-zero, measure whether the symbol's feature-forward-return IC is
conditionally different once you account for that tag's associated external factor -- via a
partial-IC control term, or a magnitude-conditional split on the calibrated weight -- gated
through the existing bootstrap CI + BH-FDR discipline.

## Why this supersedes the original multi-membership-routing framing

- Sidesteps `AmbiguousRegimeGroupError`/`symbol_regime_class`'s single-membership constraint
  entirely -- there's no "assign symbol to N buckets" step to build. `ic_engine.py`'s existing
  routing/pass_type machinery doesn't need to change at all; this is a new, additive
  measurement layer, not a rewrite.
- Not capped at the 6 hand-built `regime_group` signal modules (equity/rates/commodity_energy/
  commodity_metals/commodity_agri/fx) -- works for any tagged exposure in `tag_vocabulary`,
  including the `'exposure'`-category tags currently sitting as unused metadata on `OIH`/`XLE`/
  `XOP` etc. (`credit_risk`, `oil_price`, `rate_sensitive`, `dollar_strength`, `yield_curve`,
  `inflation`, `late_cycle`, `china_demand`, `em_flows`, `semi_cycle` -- none of these
  currently drive any systematic-regime computation at all today).
- Continuous, not discrete -- no tier/bucket-boundary design decisions needed per axis
  (contrast with `commodity_momentum_ts.py`'s hand-chosen 4-state tiers). The gradient itself
  (calibrated weight x external factor) is the measurement, with bootstrap CI as the
  significance gate -- "earn promotion through proof," not a human pre-defining discrete
  regime states for every possible factor.
- Inherently per-symbol (each symbol's own time series against its own tag weights) -- matches
  the *existing* per-symbol circular block bootstrap exactly. Todo 186 (no cross-sectional
  pooled-panel bootstrap variant) is reviewed and confirmed NOT a blocker for this.
- Still doesn't touch the per-symbol idiosyncratic/HMM regime (`feature_vectors.regime`) at
  all -- same scope boundary as the original framing: systematic/exposure-sensitivity only.

## Why this matters

Concrete motivating examples, now calibrated via Phase 146 but currently unused for anything
except (disabled) regime-group routing: `OIH`/`XLE`/`XOP`/`AMLP` (crude-price beta,
`commodity_energy_crude`/`commodity_energy_pipeline` weight 0.8-1.0) and `GDX` (gold-price
beta, `commodity_metals_precious` weight 0.9). This measurement layer would let the corpus
show, empirically, whether `XLE`'s forward-return predictability from a feature like
`momentum_z_fast` is conditionally stronger/weaker/different when interacted with its crude-
price loading -- without ever forcing `XLE` into "the equity bucket" or "the energy bucket."

## Fix (not yet started -- real design/measurement work)

1. Pick the initial mechanism: partial-IC-with-control (does a feature's IC on symbol X change
   after controlling for an external factor return series, scaled by X's calibrated tag
   weight) vs magnitude-conditional-split (bucket by tag-weight-interacted value, compare IC
   across the split). These answer subtly different questions -- scope which is primary before
   building both. Lean toward partial-IC-with-control first since `partial_spearman_ic`
   already exists in exactly this shape.
2. Define the control/interaction input per tag: what's the actual external factor return
   series for e.g. `commodity_energy_crude` (WTI/Brent proxy)? Check what's already computed
   elsewhere (cross-asset features, regime_signals' own reference symbols) before inventing a
   new factor-return source -- `fx_dollar_carry.py`'s `REFERENCE_SYMBOLS` (`UUP`, `HYG`)
   pattern is a precedent to reuse, not reinvent.
3. Scope which `(symbol, tag)` pairs are worth measuring first -- start with the 5 confirmed
   hybrid-sensitivity symbols (`OIH`/`XLE`/`XOP`/`AMLP`/`GDX`) and their calibrated commodity
   tags, not a blanket sweep across all of `tag_vocabulary`, to keep the pilot bounded.
4. Wire bootstrap CI + BH-FDR gating identically to every other IC-eligibility gate in this
   codebase -- reuse `_circular_block_bootstrap_ic`, don't reimplement.
5. **Add an explicit minimum-effective-N gate per conditioning subset before trusting any
   gradient-conditional result** -- same failure class as todo 218's `BIL` thin-cell finding
   (a wide bootstrap CI that still happens to clear a threshold on a thin split is not
   evidence; it's the identical spurious-signal shape already caught live in this corpus).
   Splitting a single symbol's own history by conditioning-variable state (e.g. "oil
   trending" vs. "oil flat") shrinks N further on top of an already-small per-symbol sample --
   the CI clearing is not sufficient on its own. Near-term, in an 80-ETF universe, most
   single-symbol conditioning splits will be N-constrained by construction; this is expected
   to improve as the securities universe scales over time (longer-term plan, per user
   2026-08-01: as complete a tradeable securities universe as computationally tractable, scaled
   against cluster compute as that build-out happens) -- but the gate must exist regardless of
   universe size, since newly-added or inherently thin symbols will always exist at the margin.
6. Decide where results live: a new column/table, or an extension of `feature_ic_scores`'s
   existing shape -- needs a real schema decision, not assumed.
7. Once this measurement layer exists and shows which gradient axes carry real signal, revisit
   todo 224's `commodity_energy`/`commodity_metals` enablement question with actual evidence
   instead of a routing-precedence guess.

## References

- `src/intelligence/statistics/ic_math.py:703` (`partial_spearman_ic`) -- partial correlation
  controlling for covariates, the primary candidate mechanism
- `src/intelligence/statistics/ic_math.py:817` (`magnitude_conditional_ic`) -- magnitude-
  threshold-conditional IC, the secondary candidate mechanism
- `src/intelligence/statistics/ic_math.py` (`_circular_block_bootstrap_ic`,
  `circular_block_bootstrap_ic_serial`) -- existing bootstrap CI machinery this reuses
- `.planning/todos/completed/040-instrument-tag-calibrator.md` -- confirms
  `instrument_tags.weight` is now calibrated (Phase 146, closed 2026-07-17), the gradient
  input this measurement needs
- `docs/plans/2026-07-01-cross-sectional-regime-model.md` -- original design doc's "Scope
  note," source of the originally-considered (and now superseded) discrete multi-membership
  framing
- `docs/foundation/glossary.md` lines 79-111 -- idiosyncratic/symbol regime vs
  systematic/market regime vocabulary this stays consistent with
- `.planning/todos/pending/224-commodity-fx-regime-group-reenablement-decision-todo-041.md` --
  sibling todo; `fx`'s zero-collision enablement stands independently; `commodity_energy`/
  `commodity_metals` enablement should wait on evidence from this todo, not a precedence guess
- `.planning/todos/pending/186-ic-math-cross-sectional-block-bootstrap-gap.md` -- reviewed and
  confirmed NOT a blocker for this todo (this is inherently per-symbol, not cross-
  sectional/pooled)
- `.planning/todos/pending/218-bil-thin-cell-per-symbol-ic-instability.md` -- the live,
  already-observed instance of the exact thin-N spurious-CI failure mode Fix step 5 guards
  against
- `src/intelligence/regime_signals/fx_dollar_carry.py` -- precedent for a `REFERENCE_SYMBOLS`
  pattern (external factor proxy series), reuse rather than reinvent when defining
  control/interaction inputs per tag
- Live verification of the hybrid-sensitivity symbol set used to motivate this:
  `SELECT symbol, array_agg(tag) FROM instrument_tags WHERE symbol IN ('OIH','XLE','XOP','AMLP','GDX') GROUP BY symbol`
