# Phase 65: Gradient Audit of Existing Plugins I1-I7 — Context

**Gathered:** 2026-04-08
**Status:** Ready for planning
**Source:** User discussion

<domain>
## Phase Boundary

Audit all 121 plugins across tiers I1–I7 for binary scoring shortcuts (hard thresholds, step functions, boolean clamps) and replace them with continuous gradient outputs per the Renaissance principle "never drop data that could contain signal." This is the broader sweep that extends beyond todo 028's original IC fix.

Deliverables:
- Catalog every binary/step pattern found across all plugins
- Replace each with a mathematically sound continuous gradient equivalent
- Preserve all existing test coverage and add regression tests for gradient behavior
- No manual intervention required post-deployment — automated, self-verifying changes

</domain>

<decisions>
## Implementation Decisions

### Design Philosophy — Renaissance / Jim Simons Standard
- **Continuous over binary:** A hard threshold (e.g., `if rsi > 70: score = 1.0`) discards gradient information that could be a training signal. Replace with smooth functions (sigmoid, tanh, logistic, piecewise-linear) that preserve the full spectrum.
- **Modularity:** Gradient transform functions live in shared utility modules, not duplicated per-plugin. Every plugin imports from the shared gradient library — single source of truth.
- **Reuse over repetition:** If 10 plugins need a "distance-from-threshold" gradient, that function is written once and imported everywhere.
- **Separation of concerns:** The gradient math is isolated from the plugin signal logic. A plugin computes its raw indicator value; the gradient layer maps it to [0,1] or [-1,1]. These two concerns never mix.
- **Microservices DAG integrity:** Plugins remain DB-ignorant, publish-only. The gradient refactor touches only the compute/scoring layer — no persistence changes, no schema changes.
- **Automation over manual:** The audit is systematic and exhaustive. No "we'll fix this one later." The plan must include a verification step that programmatically confirms no binary patterns remain after the changes.
- **Compute efficiency:** Gradient functions must be vectorizable (numpy-friendly). No Python loops where array operations apply. Profile before and after on a representative plugin to confirm no throughput regression.
- **Simplicity:** Prefer the simplest correct gradient (linear ramp) over an elaborate one (neural interpolation) unless data justifies complexity. Don't over-engineer.
- **Maintenance:** Each gradient function must have a docstring explaining the mapping and its rationale. Future engineers must understand why this function was chosen.

### Scope
- All 121 plugins (I1–I7), plus the 2 aggregation plugins
- Binary patterns to hunt: `if x > threshold: score = 1.0`, `bool(condition)`, `int(condition)`, `np.where(cond, 1, 0)`, `min/max clamps that collapse signal`, any step function that outputs only {0, 1} or {-1, 0, 1}
- Out of scope: schema changes, persistence layer, new plugin logic

### Automation
- Automated scanner (grep/AST) to enumerate all binary patterns before writing any fix
- Post-fix automated validator to confirm zero binary patterns remain
- All changes covered by unit tests that assert gradient continuity (assert output is NOT in {0.0, 1.0} for mid-range inputs)

### Claude's Discretion
- Which gradient function shape best fits each plugin (sigmoid vs tanh vs linear ramp vs softplus) — make the mathematically sound choice per indicator type
- How to structure the shared gradient utility module
- Whether to do one PLAN.md per tier or a single unified PLAN.md

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Plugin System
- `src/intelligence/CLAUDE.md` — tier details, plugin protocol, utility inventory
- `src/intelligence/register_plugins.py` — TIER_I1…TIER_I7 single source of truth
- `src/intelligence/schemas.py` — IntelligenceEvent typed bus schemas

### Existing Gradient Utilities (check before creating new)
- `src/intelligence/trading/atr_utils.py` — ATR helpers
- `src/intelligence/trading/confidence_utils.py` — compose_confidence, signal features
- `src/intelligence/trading/plugin_utils.py` — shared plugin helpers

### Architecture
- `CLAUDE.md` — Renaissance principles, plugin vs service boundary, performance rules
- `.planning/STATE.md` — project decisions and history
- `.planning/todos/pending/028-switch-ic-from-binary-to-continuous-pnl-r.md` — original IC fix (related)
- `.planning/todos/pending/030-fix-plugin-dependency-violations-for-wave-execution.md` — dependency audit (related)

</canonical_refs>

<specifics>
## Specific Requirements

1. **Jim Simons standard:** Every output that could encode a continuous quantity MUST. No information destruction via binarization.
2. **Shared gradient library:** Create `src/intelligence/utils/gradient_utils.py` (or equivalent) with canonical gradient functions. All plugins use it.
3. **Programmatic verification:** A script or test that scans plugin source for remaining binary patterns — passes only if count is zero.
4. **No throughput regression:** Gradient math must be numpy-vectorized. Benchmark before/after on at least one plugin per tier.
5. **No manual steps post-merge:** Tests must pass CI-clean without any manual DB or config changes.

</specifics>

<deferred>
## Deferred Ideas

- Adding new plugins or new signal types — out of scope for this phase
- Hyperparameter tuning of gradient function shapes using historical data — future ML phase
- Backfilling historical intelligence_features with re-scored gradient values — separate data backfill phase

</deferred>

---

*Phase: 65-gradient-audit-of-existing-plugins-i1-i7-broader-sweep*
*Context gathered: 2026-04-08*
