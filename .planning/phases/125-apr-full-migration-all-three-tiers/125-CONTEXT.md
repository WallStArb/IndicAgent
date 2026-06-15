# Phase 125: APR Full Migration — All Three Tiers - Context

**Gathered:** 2026-06-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 125 closes TODO 025: externalize all remaining hardcoded numeric constants across all three APR tiers (Tier A detection gates, Tier B confidence weights, Tier C zone geometry) so ML discovery can tune them.

**What the codebase scout found:** Migrations 128, 129, and 131 already seeded most constants into `config_state`, and most plugins already read from ConfigService via `get_sync()`. The actual remaining work is:
1. `cis_scorer.py` — 3 detection gate constants need APR seeding + code wired to config; bootstrap weights moved from hardcoded dict to `cis_weights` table load at init
2. 4 new `min_zone_width_atr` keys (new keys, distinct from existing `min_width_atr`) seeded in migration 132
3. `_assert_weights_sum` utility added and called in all Tier B plugins at prewarm/init

**In scope:**
- Migration 132: seed 3 cis gate constants + 4 new min_zone_width_atr keys + any remaining Tier A/B/C constants not yet in DB
- `CISScorer.__init__` updated to load bootstrap weights from `cis_weights` table instead of hardcoded BOOTSTRAP_WEIGHTS dict
- `_assert_weights_sum()` shared utility in `confidence_utils.py`; called in all Tier B plugins' prewarm/init
- TODO 025 closed
- `pytest tests/unit/ -q` green

**Out of scope:**
- trade_framer.py constants (deferred — requires Phase 127 counterfactual training data; see todo `2026-06-14-trade-framer-apr-migration.md`)
- Wiring Phase 126's `min_zone_width_atr` gate in `zone_engine.py` (Phase 126 wires the consumption code)
- `min_stop_distance_atr` keys (Phase 126)
- cis_weights learned-weight updates (ML discovery, v2.11+)
- Clean replay (Phase 127)

</domain>

<decisions>
## Implementation Decisions

### cis_scorer.py Wiring

**D-01: Wire 3 gate constants to APR; load bootstrap weights from cis_weights table.**

Three detection gate constants belong in APR (they are Tier A gates identical in kind to all other threshold.* keys):
- `threshold.cis.fire_threshold` = 0.35
- `threshold.cis.bucket_agree_min` = 3
- `threshold.cis.bucket_noise_floor` = 0.1

`CISScorer.__init__` must be updated to load bootstrap weights from `cis_weights` table (MAX(version) WHERE symbol='global') instead of the hardcoded `BOOTSTRAP_WEIGHTS` dict. The existing `update_weights()` hot-swap method is preserved; the service layer calls it at startup with DB-loaded weights. The `BOOTSTRAP_WEIGHTS` dict is removed (or kept as a DB-unavailable fallback only).

**Rationale:** `BOOTSTRAP_WEIGHTS` must NOT go into `config_state`. The `cis_weights` table (migration 012) is the correct and already-designed home — it's a versioned weight store with bootstrap version=1. Adding the same values to APR would create two sources of truth for weights, an architecture violation.

### min_zone_width_atr — New Keys

**D-02: Add 4 new float keys in migration 132. Do not modify the existing min_width_atr key.**

New keys to seed:
- `feature.zone_engine.min_zone_width_atr` = 1.5 (float, default/fallback)
- `feature.zone_engine.min_zone_width_atr.equity_etf` = 1.5
- `feature.zone_engine.min_zone_width_atr.forex` = 1.0
- `feature.zone_engine.min_zone_width_atr.futures` = 1.5

These are **distinct** from `feature.zone_engine.min_width_atr` = 0.25 (the zone expansion minimum in `_expand_to_min_width()` — already seeded in migration 129, already wired, leave untouched). Phase 126 wires the consumption code for the new `min_zone_width_atr` keys; Phase 125 only seeds the DB. Zero behavior change.

Phase 126's `_min_zone_width_atr(asset_class)` consumption pattern (from docs/plans/2026-06-14-phase-126-signal-universe-hardening.md):
```python
def _min_zone_width_atr(asset_class: str | None) -> float:
    key = f"feature.zone_engine.min_zone_width_atr.{asset_class}" if asset_class else None
    default = _cfg("feature.zone_engine.min_zone_width_atr", MIN_ZONE_WIDTH_ATR)
    return _cfg(key, default) if key else default
```

### Weight Sum Invariant

**D-03: Shared `_validate_weights_sum()` utility in `confidence_utils.py`, called at Tier B plugin prewarm/init.**

Signature: `_validate_weights_sum(weights: dict[str, float], plugin: str, tol: float = 1e-6) -> None`

Raises `ValueError` (NOT `AssertionError` — asserts are disabled by `-O`) with message: `f"{plugin} weights sum to {total:.6f}, expected 1.0"`. Called in each Tier B plugin immediately after loading weights from ConfigService at prewarm/init time. This catches bad seeds at daemon startup AND bad hot-reload writes on the next prewarm cycle.

**Naming rationale:** `_assert_weights_sum` would name the mechanism (Python `assert`). `_validate_weights_sum` names the mathematical role — it validates the weight sum invariant. The naming system requires role names, not mechanism names. The roadmap uses `_assert_weights_sum` but the CONTEXT.md supersedes it on naming.

**Rationale:** Module-level asserts only guard hardcoded fallbacks (wrong for post-APR world where weights come from DB at runtime). pytest-only catches bad SQL seeds but misses runtime config writes from operators or ML agents. The `ValueError` propagates through daemon startup and prevents serving corrupted confidence scores — silent wrong answers are worse than crashes.

The pattern already exists in this codebase (`delta_exhaustion.py`, `lifecycle_tracker.py`) but is ad-hoc. This centralizes it.

### Naming Violations to Fix in Phase 125

**D-04: Fix `cfg` parameter name in `confidence_utils.py` when touching the file.**

`set_config_service(cfg: Any)` — `cfg` is a Tier 3 banned abbreviation (naming system §6). Rename parameter to `config` when adding `_validate_weights_sum()`. Apply the same fix to the module-level variable `_config_service` setter — the variable name is fine; only the parameter is banned.

**D-05: Capture two cleanup TODOs — do NOT fix in Phase 125.**

- `confidence_utils.py` file name: `Utils` is a retired word (naming system §3 retired words list). The file should be renamed to `confidence.py`. 39 import sites makes this out-of-scope for Phase 125; create a cleanup TODO to rename in a future polish phase.
- `_cfg()` in `zone_engine.py`: `cfg` abbreviation in function name. Should be `_read_config()`. Phase 125 does not touch `zone_engine.py` code; capture as a cleanup TODO.

Downstream agents: do NOT rename `confidence_utils.py` or `_cfg()` in Phase 125 — only flag as TODOs. The file rename requires a grep-and-replace across 39 callers and belongs in a dedicated cleanup commit.

### Claude's Discretion

- Exact migration number (current max is 131; next is 132 — researcher confirms no intervening migrations)
- Whether any Tier A/B constants identified in TODO 025 still need DB seeding (researcher verifies against migrations 128/129 to find gaps)
- `config_history` provenance string for new min_zone_width_atr keys: `'rca_analysis'` with reason citing Phase 126 noise-band analysis
- Whether `CISScorer` loads from `cis_weights` directly (asyncpg query) or via an injected loader; service layer wiring is researcher/planner scope
- Tolerance on `_assert_weights_sum`: 1e-6 default (float representation of 0.40+0.35+0.25 may not be exactly 1.0)

### Folded Todos

**TODO 025 — Parameter Store Full Plugin Migration** (`.planning/todos/pending/025-parameter-store-full-plugin-migration.md`): Phase 125 IS the execution of this todo. Close it in the final commit. The todo's trigger condition ("after signal ledger rebuild replay completes") is satisfied by Phase 122 completion.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope + migration inventory
- `.planning/todos/pending/025-parameter-store-full-plugin-migration.md` — authoritative Tier A/B/C constant list with target APR keys and namespaces
- `docs/plans/2026-06-14-phase-126-signal-universe-hardening.md` §P126-01 (zone width gate) — shows exact consumption pattern for min_zone_width_atr keys Phase 125 seeds
- `.planning/ROADMAP.md` §Phase 125 — success criteria (51 keys, weight sum invariant, TODO 025 close)

### Migration inventory (what's already done — researcher must verify gaps)
- `production/migrations/128_threshold_config_params.sql` — Tier A seeds: global thresholds (min_regime_weight, min_ctf_score) + Phase 124 plugin gates
- `production/migrations/129_plugin_param_store.sql` — Tier A/B/C bulk seeds: 24 Tier A keys, Tier B weights for 8 plugins, all 6 Tier C zone_engine keys
- `production/migrations/131_phase124_param_store.sql` — Phase 124 plugin APR seeds (5 rewritten plugins)
- `production/migrations/012_cis_weights_table.sql` — cis_weights table schema + bootstrap seed (version=1, weights_type='designed')

### Source files with remaining hardcoded constants
- `src/intelligence/trading/cis_scorer.py` — BOOTSTRAP_WEIGHTS dict (to be replaced by cis_weights table load), CIS_FIRE_THRESHOLD (0.35), BUCKET_AGREE_MIN (3), BUCKET_NOISE_FLOOR (0.1)
- `src/intelligence/trading/zone_engine.py` — min_width_atr() already reads from config; min_zone_width_atr DOES NOT YET EXIST (Phase 126 wires it)

### Utility + pattern sources
- `src/intelligence/trading/confidence_utils.py` — home for `_assert_weights_sum()`; already contains weight math helpers
- `src/intelligence/trading/delta_exhaustion.py` — module-level assert pattern (reference, do NOT copy — see D-03 rationale)
- `src/config/config_service.py` — `get_sync()` usage pattern; `OPS_PREFIXES` (must include `"ui."` for ui.* keys)
- `production/migrations/129_plugin_param_store.sql` — canonical migration format for config_schema + config_state + config_history triple insert

### Architecture + principles
- `docs/foundation/parameter-store.md` — description field conventions (`[initial_estimate]`, `[conventional]`, `[rca_analysis]`), ML learning target notation
- `CLAUDE.md` §Parameter Store — namespaces, provenance lifecycle, adding a parameter SOP
- `CLAUDE.md` §Key Rules — `config_service.get_sync()` usage, `ValueError` over `AssertionError`

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `confidence_utils.py` `_cfg()` wrapper pattern (module-level `_config_service` + `set_config_service()`) — same pattern used in `zone_engine.py`, `aggregator.py`. New `_assert_weights_sum()` goes here.
- `production/migrations/129_plugin_param_store.sql` — the full triple-insert pattern (config_schema + config_state + config_history). Migration 132 follows this exactly.
- `cis_weights` table (migration 012) — already has bootstrap weights at version=1, `weights_type='designed'`. CISScorer just needs to read from it at init instead of using the hardcoded dict.

### Established Patterns
- `get_sync(key, default)` — synchronous config fetch with fallback; used in all already-wired plugins. Tier B plugins load all weights in one prewarm batch, then pass dict to `_assert_weights_sum()`.
- Plugin prewarm via `_prewarm_threshold_config()` in `intelligence_pipeline.py` — called at startup; this is where weight loading + `_assert_weights_sum()` calls go.
- `ON CONFLICT (config_key) DO NOTHING` — safe idempotent insert for all config_schema / config_state rows.
- `ON CONFLICT (config_key) DO NOTHING` does NOT work for updating existing rows. For the 3 new CIS gate keys (new rows), `DO NOTHING` is correct.

### Integration Points
- `intelligence_pipeline.py` `_prewarm_threshold_config()` — where all Tier B plugins have their weights loaded from config; `_assert_weights_sum()` is called here for each plugin
- `cis_scorer.py` `CISScorer.__init__` — load bootstrap weights from DB query on `cis_weights` (MAX version WHERE symbol='global'); service layer passes `config_service` or a loader at construction
- `production/migrations/` — next migration file is `132_phase125_param_store.sql`; researcher confirms max is 131

</code_context>

<specifics>
## Specific Ideas

- **Renaissance design principle applied throughout**: single source of truth per concern — `cis_weights` table owns CIS weights, APR owns gates. Don't duplicate.
- **`ValueError` over `AssertionError`**: Python `-O` flag disables asserts; production code can be optimized. `ValueError` always fires.
- **The 4 new min_zone_width_atr keys are a contract for Phase 126**: Phase 126's P126-01 plan cites "if 125 not complete, hard-code with TODO comment." Completing Phase 125 unblocks Phase 126 P126-01 without workarounds.
- **todo trade_framer APR migration explicitly deferred**: requires `counterfactual_pnl_r` training data that doesn't exist until Phase 127-130. Do not attempt.

</specifics>

<deferred>
## Deferred Ideas

- **trade_framer.py constants** — 16 hardcoded ATR multipliers and RR thresholds. Deferred to after Phase 127 (requires counterfactual_pnl_r data for ML tuning). See `.planning/todos/pending/2026-06-14-trade-framer-apr-migration.md`. CLAUDE.md architecture violation; schedule as a standalone phase once Phase 127 ships.
- **cis_weights learned-weight ML loop** — Phase B architecture (ML-trained weights replacing bootstrap). Requires 100+ resolved signals per segment. v2.11+.
- **min_stop_distance_atr per-asset-class keys** — Phase 126 scope (needed when wiring the zone-width gate).

### Reviewed Todos (not folded)

- `2026-06-14-trade-framer-apr-migration.md` — Reviewed; explicitly deferred. Requires Phase 127 counterfactual training data before ML can tune these constants. Not in Phase 125 scope.
- `019-sr-strength-calibration.md` — Reviewed; SR strength weights (zone_engine default_strength) are separate from the Tier B weights in scope. Belongs in a dedicated SR calibration phase once replay data exists.

</deferred>

---

*Phase: 125-apr-full-migration-all-three-tiers*
*Context gathered: 2026-06-14 via /gsd-discuss-phase (Renaissance-council discussion)*
