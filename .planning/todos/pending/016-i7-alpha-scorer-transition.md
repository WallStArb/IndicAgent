---
**Created:** 2026-06-28
**Area:** intelligence
**Type:** refactor
**Priority:** P2
**Effort:** 3-5 days
**Benefit:** Replaces binary emission with continuous alpha scores; ensemble IS the new I7
**Risk:** high (core signal path change)
**Gate:** IC engine stable + shadow mode validated
---

# 016 — I7 Alpha Scorer Transition

**Priority: Medium — structural migration; defines the long-term relationship between v2.x I7 and v3.0 ensemble.**
**Gate: Phase 144 (v2.x retirement gate) must have a defined plan; this is the path to retirement.**
**Plan doc:** `docs/plans/2026-06-20-i7-alpha-scorer-transition.md`

---

## What It Is

I7 plugins currently make a binary emission decision: "is this a signal?" The v3.0 architecture replaces that with a continuous alpha score: each plugin computes `alpha_score = raw_confidence × direction` every bar, regardless of whether it would have "fired" before. The ensemble IS the new I7 emission decision.

This is the structural migration that closes the gap between v2.x (binary plugins) and v3.0 (continuous IC-measured features). It is the prerequisite for retiring v2.x with evidence rather than by convention.

---

## Why Renaissance Demands This

The current v2.x I7 plugins embody researcher hypotheses about when to fire. Those hypotheses have never been validated against forward returns. The IC engine proves which features predict returns — but the plugins still gate emission through hand-coded logic. The transition moves gating from "researcher says fire" to "IC Sharpe says this feature predicts."

Two signals running in parallel (I7 binary + v3.0 alpha score) is a dual-pipeline shadow comparison (todo 007). But the comparison only makes sense if I7 produces a comparable continuous output. A binary signal vs. a continuous score cannot be compared directly on outcome quality.

---

## Scope

**What retires:**
- Emission decision layer in I7 plugins (the `if confidence > threshold: emit` logic)
- Setup names as first-class emission concepts (retire correlated redundant ones after IC discovery identifies them)
- Hand-encoded confluence rules in I7 plugins

**What survives (rewritten):**
- I7 plugins as alpha scorers: `alpha_score = confidence × direction` on every bar, no emission decision
- Zone proximity and structure features as inputs to FeatureFactory (they're primitives, not setup logic)
- Entry type logic (`at_close`, `at_pullback`) as post-emission execution strategies in Phase 142 trade framing

**Signal Events enrichment during transition:**
Add `alpha_score` column to `signal_events`. Prospectively populated as plugins convert. Legacy rows have `NULL`. This column becomes the comparison surface for todo 007.

**Observability during transition:**
- `i7_plugin_mode` gauge: 1=alpha scorer, 0=legacy emitter
- `i7_plugin_alpha_score_null_total` counter: incomplete conversions
- `i7_conversion_complete` gauge: 1 when all plugins converted

---

## Sequencing

Do NOT start this migration until:
1. Phase 141 (corpus quality gate) passes — need clean IC results to know which I7 feature dimensions have signal
2. Todo 007 (dual pipeline shadow comparison) has a defined comparison protocol — the comparison informs which plugins to retire vs. convert

This is a 2-4 week migration touching 35 I7 plugins. Plan as a phase, not a todo, when Phase 143 is running.

---

## Files Affected

- `src/intelligence/trading/` — all I7 plugin files (~35 plugins)
- `src/intelligence/trading/plugin_utils.py` — remove binary emission helpers, add alpha_score computation pattern
- `services/signal_writer_agent.py` — adapt to consume continuous scores when plugins are in alpha-scorer mode
- DB migration: add `alpha_score` column to `signal_events`
