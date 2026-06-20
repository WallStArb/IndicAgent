# Phase 125: APR Full Migration — All Three Tiers - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-14
**Phase:** 125-apr-full-migration-all-three-tiers
**Areas discussed:** cis_scorer.py wiring, min_zone_width_atr seed, Weight sum invariant

---

## cis_scorer.py wiring

| Option | Description | Selected |
|--------|-------------|----------|
| Add weights.cis.* to config_state as bootstrap source | Seed all 6 bucket weights in config_state migration 132. CISScorer reads them via get_sync(). | |
| Skip cis_scorer.py — defer to a dedicated cis-weights phase | Exclude from 125; plan separate phase for the cis_weights + APR bootstrap design. | |
| Only migrate CIS gate constants (skip bucket weights) | Externalize CIS_FIRE_THRESHOLD + BUCKET_AGREE_MIN + BUCKET_NOISE_FLOOR to APR; leave BOOTSTRAP_WEIGHTS for cis_weights phase. | ✓ (Renaissance reasoning) |

**User's choice:** User asked for Renaissance-council reasoning ("What would Jim Simons demand?") and deferred the decision to Claude.

**Notes:** Renaissance analysis: `cis_weights` table (migration 012) is the correct and already-designed home for CIS bootstrap weights — it's a versioned weight store seeded at version=1. Putting the same values in `config_state` would create two sources of truth for weights, which is an architecture violation. The 3 detection gate constants (0.35, 3, 0.1) are Tier A gates identical in kind to every other threshold.* key and belong in APR. Additionally, CISScorer needs to load bootstrap weights from `cis_weights` at init rather than hardcoded dict — removes the hardcoded dependency without polluting APR.

---

## min_zone_width_atr seed

| Option | Description | Selected |
|--------|-------------|----------|
| Single JSON key with per-class map | feature.zone_engine.min_zone_width_atr as JSON '{"equity":1.5,"forex":1.0,"futures":1.5}' | |
| Three separate float keys | feature.zone_engine.min_zone_width_atr.equity + .forex + .futures as distinct float keys | |
| Defer — leave at 0.25, document intent for Phase 126 | No change; Phase 126 adds per-class keys when it wires the gate | |

**User's choice:** User initially selected "Single JSON key" but then asked for Renaissance-council reasoning.

**Notes:** Codebase scout revealed `feature.zone_engine.min_zone_width_atr` is a NEW key (distinct from existing `feature.zone_engine.min_width_atr` = 0.25). Phase 126 plan shows the consumption code uses a default key + per-class suffix pattern (e.g., `feature.zone_engine.min_zone_width_atr.equity_etf`). This means 4 separate float keys (default + 3 per-class) is the correct design — matches Phase 126's `_min_zone_width_atr(asset_class)` consumption function exactly. The existing `min_width_atr` float key at 0.25 is left untouched.

---

## Weight sum invariant

| Option | Description | Selected |
|--------|-------------|----------|
| Shared utility in confidence_utils.py, called at plugin init | _assert_weights_sum() raises ValueError at prewarm/init after config load | ✓ (Renaissance reasoning) |
| Module-level assert at import time | Mirror delta_exhaustion.py pattern — fires at import but only guards hardcoded fallbacks post-APR | |
| pytest unit test only | CI catches bad seeds; no runtime assertion | |

**User's choice:** User asked for Renaissance-council reasoning and deferred to Claude.

**Notes:** Module-level asserts only guard hardcoded defaults — after APR migration, weights come from DB at runtime, so module-level assert would miss bad config writes. pytest-only catches bad SQL seeds but misses runtime operator or ML agent writes to config_state at 2am. The failure mode (weights not summing to 1.0) produces a silent wrong answer: systematically biased confidence scores contaminating every bar and the entire training corpus. `ValueError` (not `AssertionError` — asserts disabled by `-O`) propagates through daemon startup and prevents serving corrupted data.

---

## Claude's Discretion

- **cis_scorer.py wiring approach**: Full Renaissance analysis; user delegated the decision entirely.
- **min_zone_width_atr key design**: User selected JSON initially, then delegated final reasoning; Claude discovered the correct design from Phase 126 plan source.
- **Weight sum invariant placement**: User delegated; Claude applied Renaissance reasoning about failure modes.
- **Exact migration number (132)**: Confirmed from max migration 131.
- **CISScorer init loading mechanism**: Service-layer wiring details left to researcher/planner.

## Deferred Ideas

- **trade_framer.py APR migration**: 16 hardcoded constants. Requires Phase 127 counterfactual_pnl_r training data. Tracked in `.planning/todos/pending/2026-06-14-trade-framer-apr-migration.md`.
- **cis_weights ML learned-weight loop**: v2.11+, requires 100+ resolved signals per segment.
- **min_stop_distance_atr per-asset-class keys**: Phase 126 scope.
- **SR strength calibration** (todo 019): Separate phase after replay data exists.
