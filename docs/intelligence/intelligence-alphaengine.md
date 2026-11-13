# AlphaEngine — IC-Weighted Factor Model *(archived; concept condensed)*

**Status:** the AlphaEngine name and emission chain are retired (glossary, 2026-09-26); the
mechanism this doc described was deleted in phase 186 (ensemble_trainer, alpha_publisher,
alpha_events, the correlation engine and the decay monitor are gone; `ic_measure` and the
research kernel chain replaced them). Condensed 2026-11-13 to the rationale that still governs
the codebase. Full text: git history.

## The core idea (verbatim, still governing)

The v2.x intelligence pipeline had a structural flaw that could not be fixed by tuning: researchers encoded hypotheses about what constitutes edge into I5/I6/I7 — named patterns, confluence rules, signal firing conditions. The system could only discover edges the researcher already believed in. Outcomes were only observed for bars the researcher's filter allowed through. 138 plugins produced approximately 15 independent views.

This is confirmation bias with extra steps. The fix is not better plugins. The fix is a different epistemology.

> The researcher produces features. The data discovers confluence. The IC engine arbitrates.

No human defines what feature combinations constitute edge. The ensemble finds it.

## What gets cut (the decision record)

| Tier | Status |
|------|--------|
| **I1-I4** | Concepts survive. Implementation is a clean rewrite — pure functions in the Feature Factory, replacing the plugin-based I1-I4 orchestration entirely. |
| **I5** (chart patterns, divergences) | Archived. |
| **I6** (confluence scoring) | Archived. |
| **I7** (signal plugins, signal emission) | Archived (signal surface dropped by migrations 462 and 521). |
| **Plugin registry** | Replaced by a typed function library. "No transitional shims, no parallel operation." |

## What replaced it

- `FeatureFactory.compute()` (`src/intelligence/feature_factory.py`): one stateless pure function
  producing the `FeatureVector` columns; no per-feature plugin files, no self-registration lists.
- **Extensibility is a schema migration, not a registration:** write the kernel, add the
  `feature_vectors` column by migration, insert the `concept_registry` row. Evidence gates
  promotion (UCR lifecycle), not a startup validator.
- IC measurement and ensemble governance: `docs/intelligence/intelligence-alphaengine-methodology.md`
  (canonical for the live `ic_measure` path) and the unified design
  (`docs/plans/2026-09-26-unified-research-to-production-design.md`).
- The full why-plugins-were-rejected analysis: `docs/concepts/plugin-composability.md`
  ("What Replaced It in v3.0").
