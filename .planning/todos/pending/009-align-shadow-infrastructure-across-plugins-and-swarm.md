---
created: 2026-04-27T20:44:37.278Z
title: Align shadow infrastructure across I7 plugins and swarm agents
area: architecture
files:
  - src/intelligence/trading/dual_divergence.py:44
  - src/core/swarm/base_agent.py:37
  - src/core/ml/shadow.py
  - src/intelligence/weight_updater.py:479-500
  - src/intelligence/trading/confidence_utils.py:96-179
  - src/persistence/repository/signal_ledger_repository.py:111
---

## Problem

Three independent shadow concepts exist with no shared abstractions, dead infrastructure, and naming collisions:

1. **I7 plugin shadow** — Only `DualDivergencePlugin` has `IS_SHADOW: ClassVar[bool]`. All 37 I7 plugins write `signal["_shadow"]` via `capture_signal_features()`, but this is ML training data capture, NOT shadow mode gating. Misleadingly named.
2. **Swarm agent shadow** — `SwarmBaseAgent.shadow_only = True` on all 3 swarm agents. `ShadowRecorder` exists but is never instantiated (dead code). No promotion logic exists despite comments saying "promotion process only."
3. **Feature parity shadow** — `feature_snapshots_shadow` table for A/B parity validation. Genuinely different concern.

Specific issues:
- `signal["_shadow"]` naming collision — ML feature capture masquerading as shadow mode
- `ShadowRecorder` in `src/core/ml/shadow.py` never used — dead code
- `SHADOW_PLUGINS: tuple[str, ...] = ()` in `weight_updater.py:500` — empty list, no plugins tracked
- `is_shadow` column in `signal_ledger` defaults False, no code path sets it True
- No promotion manager exists — shadow data is collected but never evaluated for promotion
- Prometheus gauges emitted (`SHADOW_*`) but nothing reads them

## Solution

**Defer until we have actual shadow plugins to promote.** Premature alignment around empty infrastructure creates maintenance burden.

When ready:
1. Rename `signal["_shadow"]` → `signal["_ml_features"]` to resolve naming collision (37 call sites)
2. Create shared `ShadowConfig` base for plugin and swarm shadow gating (common gates: N, p-value, win rate)
3. Wire or remove `ShadowRecorder` dead code
4. Build promotion manager that evaluates both plugin and swarm shadow stats against consistent gates
5. Feature parity shadow stays separate — different concern (data validation vs new code validation)
