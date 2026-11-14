# Cross-sectional regime model implementation plan (archived)

Date: 2026-07-01. Condensed to a stub 2026-11-14.
Outcome: landed: `services/cross_sectional_regime_model.py` is the single regime writer, with groups declared in APR (`alpha.regime.groups`) and signal modules in `src/intelligence/regime_signals/`.

Idea kept: Regime groups are data (a tag filter, a signal type, parameters), so adding a group is configuration, not code; ambiguous routing raises rather than defaulting.

Full text: git history, `docs/plans/archive/2026-07-01-cross-sectional-regime-model.md` as of `ebb1047f9`.
