---
phase: 163
reviewers: [codex]
reviewed_at: 2026-07-20T23:00:00Z
plans_reviewed: [163-01-PLAN.md, 163-02-PLAN.md, 163-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 163 (VP/SR Structural Primitives)

## Codex Review

**Summary**

The plans are broadly well-structured and, on the final authoritative scope, internally consistent: they converge on 4 existing structural columns plus 12 new ones, for 16 total structural entries, and the phase ordering is sensible (`01` schema/contract, `02` VP wiring, `03` S/R wiring). The main problems are not scope count, but verification strength and a few under-specified algorithmic details that could still let a silent regression through. The historical 9/10/14-column prose in `CONTEXT.md` is superseded by the final 12-column contract, but it is still easy to misread if someone is skimming.

**Strengths**

- The dependency order is correct: schema/registry contract first, live/batch VP wiring second, stateless S/R third.
- The final feature count is consistent across the plans: 12 new VP features plus the 4 original structural fields equals 16 total.
- The no-raw-price rule is explicit and repeated in the right places, which protects cross-sectional IC validity.
- The plans correctly separate stateful session VP from stateless S/R, which matches the underlying algorithms.
- The collinearity facts are documented instead of being left implicit, especially for `va_width_atr` and `poc_session_rolling_divergence_atr`.
- The regression-test intent is good: both plans try to catch the original "frozen default" failure mode and live/batch divergence.

**Concerns**

- **HIGH** (fixed during review, see below): Plan 01's third automated verify line for the registry-vs-dataclass drift gate was a no-op — `SELECT ... OR true` always evaluates true, and the Python line imported modules without asserting equality, swallowing import errors via `2>/dev/null` and unconditionally printing a success-looking message.
- **MEDIUM**: The exact-collinearity features (`va_width_atr`, `poc_session_rolling_divergence_atr`) are intentionally kept, but the plans specify no concrete mechanical safeguard beyond code comments — risk is to downstream IC ranking (redundant columns inflating apparent feature breadth), not to this phase's own correctness.
- **MEDIUM**: Plan 03's S/R port ("minimal cluster-to-mean-price is sufficient") is underspecified relative to the archived `support_resistance.py` clustering behavior around ties/pivot density — parity with the reference implementation is not pinned by a golden-value test.
- **MEDIUM**: VP recomputes the histogram from scratch per bar in both live and batch (O(n²)-ish per session) — acceptable at current window sizes but no stated performance budget for 58 ETFs × 4 timeframes at scale.
- **LOW**: CONTEXT.md's historical 9/10/14-column narrative (D-13→D-16→D-17→D-18 correction trail) is fine for provenance but a footgun for a skimming reader; the final 12-column section is authoritative.

**Suggestions**

- Replace Plan 01's weak verify line with a real `set(feature_registry.feature_name) == set(dataclasses.fields(FeatureVector))` assertion — **done, see Resolution below**.
- Add an explicit regression assertion for the collinear-pair identity (not just a comment) so redundancy is mechanically visible in tests, not just documented.
- For S/R, either port the archived clustering semantics more faithfully or add a golden-value fixture test so "close enough" doesn't drift over time.
- Add a short performance note/benchmark target for per-bar histogram recomputation at backfill scale.
- Consider a single shared constant/manifest for the 12 new VP field names so migration, schema, domain, persistence, and tests can't drift from each other.

**Risk Assessment**

**Medium.** The phase is decomposed well and the final 12-field contract is coherent — not a scope or ordering failure. The residual risk is silent correctness issues: (now-fixed) weak verification in Plan 01, intentionally redundant features without a mechanical downstream safeguard, and an S/R implementation that is still somewhat approximate for a feature that matters to IC measurement.

---

## Resolution

The HIGH finding was verified directly against `163-01-PLAN.md` (the no-op was real — `OR true` and an unconditional `echo`/swallowed `2>/dev/null` import) and fixed in the same session: the third automated verify line now writes `feature_registry.feature_name` to a temp file and asserts set-equality against `dataclasses.fields(FeatureVector)` in Python, raising `AssertionError` with the exact diff on mismatch instead of always reporting success.

The three MEDIUM concerns and the LOW note are accepted as-is for this phase — none block execution:
- Collinearity mechanical safeguard: deferred to todo 038's collinearity diagnostic per D-17/D-18's own stated reasoning (this phase documents, the IC/ensemble pipeline enforces).
- S/R clustering fidelity: D-04's "simple, self-contained" choice was already a deliberate scope decision (not `ctx_SRConsensus`); a golden-value fixture is a reasonable follow-up, not a blocker for this phase's promotion bar (D-07 — standalone correctness, not literal parity with the archived plugin).
- VP per-bar histogram cost: acceptable at current corpus scale (58 ETFs × 4 TFs); revisit only if corpus throughput (Phase 162) surfaces this as a hot path.
- CONTEXT.md historical count narrative: intentional decision log (D-13 → D-16 → D-17 → D-18), not a live contract — the final "12, not 10" line is unambiguous.

## Consensus Summary

Single reviewer (Codex) this round — Claude and Antigravity were available but Claude was skipped for reviewer independence (self-review) per this session's runtime; Antigravity was not additionally dispatched since Codex is the configured `review.default_reviewers` for this project. No divergent views to reconcile.
