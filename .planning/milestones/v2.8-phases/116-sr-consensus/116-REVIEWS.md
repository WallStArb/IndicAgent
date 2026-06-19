---
phase: 116
reviewers: [codex]
reviewed_at: 2026-06-05T18:00:00Z
plans_reviewed: [116-01-PLAN.md, 116-02-PLAN.md, 116-03-PLAN.md]
gemini_status: rate_limited
---

# Cross-AI Plan Review — Phase 116

## Codex Review

### Summary

The three-plan sequence is mostly coherent and correctly ordered: Plan 01 fixes the bad I3 SR source, Plan 02 expands reusable zone synthesis, and Plan 03 persists a confluenced I4 feature after schema fields exist. The plans are detailed enough to execute and include good verification gates. The main risk is a directional mismatch in Plan 02/03 around `collect_sr_candidates()` and `_VP_DIRECTION`: the new API defines `direction=1` as resistance and `direction=-1` as support, but existing `_VP_DIRECTION` is keyed for trade direction, where `1` maps to support-side VP fields. That can silently add wrong VP candidates to support/resistance consensus.

### Strengths

- Correctly targets the actual root causes: fixed percent cluster radius, TF-blind lookback, synthetic `price * 0.98/1.02` fallback
- ATR sourcing via `frames["i1"]["atr_14"]` matches the project's "ATR computed in I1" convention
- TF lookback table is explicit and conservative
- Keeps the output field names unchanged, limiting downstream schema churn
- Volume-weighted strength with a 2x cap is simple and bounded
- `find_best_level()` is the right encapsulation boundary — Plan 03 does not import private clustering helpers
- `dist_atr` inversion is correct: smaller HVN distance produces stronger score
- `collect_sr_candidates()` cleanly separates proximity-gated SR collection from entry/stop-bounded trade-zone collection
- Correct schema-first ordering prevents `I4Context(extra="forbid")` startup failures
- Round-number grid is instrument-agnostic and price-magnitude based
- Registration checklist covers import, schema validation list, registry call, TIER_I4, and I4_WAVE_B

### Concerns

**HIGH — Direction semantics conflict with existing `_VP_DIRECTION` (Plan 02/03):**
Existing `collect_candidates(direction=1)` means long trade and collects support-side candidates, so `_VP_DIRECTION[1]` maps to `val` and `nearest_hvn_below`. Plan 02 redefines `direction=1` as resistance in `collect_sr_candidates()`, but then reuses `_VP_DIRECTION[direction]`. This means resistance collection may include below-price VP fields, and support collection may include above-price fields — silently adding wrong-side VP candidates to the consensus.

**HIGH — Plan 03 inherits Plan 02's direction bug:**
If Plan 02 keeps the `_VP_DIRECTION` reuse, `ctx_SRConsensus` can confluence wrong-side VP candidates for both support and resistance sides.

**MEDIUM — Sparse output semantics (Plan 01):**
The plan omits absent nearest levels while some pipeline consumers may expect every declared output key. If the aggregator treats missing keys differently from `None`, this may create inconsistent feature rows. Also conflicts with Plan 03's "all None when no level" framing.

**MEDIUM — `_age_bars` semantic shift (Plan 01):**
`*_age_bars` is now age within the TF lookback window after slicing, not the original frame. This is a semantic change that may affect any consumer using age as a proxy for level staleness.

**MEDIUM — `confluence_score=0.0` vs `None` inconsistency (Plan 03):**
Success criteria says "all None when no level within TF cap" but the plan returns `confluence_score=0.0` when no candidate found. Downstream numeric consumers should see documented behavior here.

**MEDIUM — Round numbers can dominate (Plan 03):**
Round-number candidates can be the sole result when no structural candidates exist. "Multi-source confluenced" degrades to a single round number via `find_best_level()` fallback — may be intended but should be tested explicitly.

**LOW — ATR fallback in I3 (Plan 01):**
ATR fallback to `current_price * 0.005` preserves old behavior when ATR is missing. Weakens the ATR-proportional guarantee for malformed frames.

**LOW — Round number dedup (Plan 03):**
`_round_number_candidates()` can generate duplicate levels across grid sizes (e.g. 7400 appears in the 100 and 1000 grids when near a major round). Dedup not applied after appending round numbers — duplicates could inflate clustering.

**LOW — Test fixtures (Plan 01):**
Random walk fixtures can become brittle when cluster radius changes. Deterministic fixtures with explicit pivot placement are more reliable.

### Suggestions

- **Fix VP direction for `collect_sr_candidates()`:** use a separate SR-specific mapping — support uses `val`/`nearest_hvn_below`/`poc` below price, resistance uses `vah`/`nearest_hvn_above`/`poc` above price. Do NOT reuse `_VP_DIRECTION[direction]` as-is.
- Add tests proving support candidates never include `nearest_hvn_above`/`vah`, and resistance candidates never include `nearest_hvn_below`/`val`.
- Explicitly decide whether missing I3 SR outputs should be omitted or emitted as `None`; align with feature writer behavior.
- Resolve "all None" vs "score 0.0" before implementation — document that `price=None, dist_atr=None, confluence_score=0.0` is the intended no-candidate output.
- Dedup combined candidates (structural + round number) before passing to `find_best_level()`.
- Add a test where every candidate is outside `atr * TF cap` and assert no level is emitted.
- Add a test where structural and round-number candidates cluster together and confirm averaged consensus level.
- Rename or document clearly that `collect_sr_candidates(direction=1)` means resistance, unlike `collect_candidates(direction=1)` which means long-trade support zone.

### Risk Assessment

**HIGH** on Plan 02/03 until the VP direction bug is fixed. **MEDIUM** on Plan 01 (sparse output semantics). After the VP direction fix, overall phase risk drops to **MEDIUM** — architecture is sound, dependency ordering is right, private internals are properly encapsulated.

---

## Gemini Review

Gemini CLI hit rate limits during review — no output produced. Re-run with: `cat /tmp/gsd-review-prompt-116.md | gemini -p -`

---

## Consensus Summary

### Agreed Strengths (Codex — single reviewer)

- Three-step fix correctly ordered: bad inputs first, synthesis extension second, persistence third
- `find_best_level()` as public encapsulation of private zone_engine clustering is the right boundary
- Schema-first ordering in Plan 03 prevents startup RuntimeError
- ATR-proportional clustering and TF-proportional lookback are sound replacements for fixed-percent and TF-blind approaches
- Instrument-agnostic round number grid via price-magnitude is correct design

### Critical Concern (Single Reviewer — treat as HIGH priority)

**`_VP_DIRECTION` reuse bug in `collect_sr_candidates()`:** The existing `_VP_DIRECTION` dict maps trade direction (1=long) to support-side VP fields. `collect_sr_candidates()` uses SR direction (1=resistance) with the same dict — this inverts which VP fields are included for each side. Fix required before execution.

### Open Questions

- Should missing I3 SR outputs be omitted keys or `None` values? Needs explicit decision to align I3 → I4 → feature writer chain.
- Should `confluence_score` be `None` or `0.0` when no candidate found? The "all None" spec and "0.0 score" plan text conflict.
