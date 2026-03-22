# Phase 46: I6 Confluence Expansion - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Expand I6's output feature vector with VIX regime measurements and EQ_INDEX sector spread data — four new independent fields in `I6Confluence`, available to Phase 49 ML as clean, separable training features. `ctf_score` formula is **not modified**. This is a data exposure phase, not a formula tuning phase.

FeaturePipelineService wires frame injection for cross_asset payload (already published by cross_asset_service) and VIX context (computed from existing bar_history). `CrossTimeframeConfluencePlugin` reads the injected frames and emits new raw measurement fields.

</domain>

<decisions>
## Implementation Decisions

### Renaissance design principle (D-01)
- **D-01:** Phase 46 is a **raw measurement exposure** phase. Never pre-normalize signals into [0,1] "favorable scores" — that imposes our interpretation of the relationship and destroys nonlinearity that Phase 49 must learn. Expose raw measurements (VIX level, z-score, spread z-score). Phase 49 learns the transformation.
- **D-02:** `ctf_score` formula is **untouched**. New fields are independent columns in `I6Confluence`, not components folded into ctf_score. Mixing VIX or sector rotation into ctf_score would destroy separability — Phase 49 couldn't untangle which component drove signal success.

### New I6Confluence output fields (D-03)
- **D-03:** Four new fields added to `I6Confluence` in `schemas.py`:
  ```python
  ctf_vix_level:           float | None  # raw VIX close level; all symbols
  ctf_vix_z:               float | None  # VIX z-score vs 20-bar rolling mean; all symbols
  ctf_eq_spread_z:         float | None  # dominant EQ pair spread z-score; EQ_INDEX only → None otherwise
  ctf_eq_pairs_confirming: float | None  # 0.0–2.0 confirming pairs; EQ_INDEX only → None otherwise
  ```
- **D-04:** `ctf_vix_*` fields are computed for **all symbols** — VIX is a global fear gauge relevant to gold, bonds, crypto, not just equities.
- **D-05:** `ctf_eq_*` fields are `None` for non-EQ_INDEX symbols. Phase 49 must segment on symbol group when including `ctf_eq_*` features in the training matrix.
- **D-06:** `float | None` type (not `float`) — `None` means data unavailable (VIX bars insufficient, cross_asset not ready). Downstream must not substitute 0.0 for None — 0.0 is a valid z-score value and would introduce false signal.

### FVG/OB alignment weights — not modified (D-07)
- **D-07:** ROADMAP said "FVG/OB alignment weights become non-zero." This is superseded. Phase 45 exposes `ctf_fvg_alignment` and `ctf_ob_alignment` as independent I6 output fields — Phase 49 learns their predictive weights. There is nothing to "weight" inside `ctf_score`. No change to I6 scoring formula.

### VIX computation module (D-08)
- **D-08:** VIX context computation lives in `src/intelligence/context/vix_context.py` — a pure function module following the same pattern as `src/intelligence/cross_asset_features.py`. FeaturePipelineService calls it and injects the result. Analytical code stays in `src/intelligence/`; transport/injection stays in `services/`. FeaturePipelineService is a frame assembler, not a signal computer.
- **D-09:** `vix_context.py` public interface:
  ```python
  def compute_vix_context(vix_bars: deque[BarMessage], z_window: int = 20) -> dict[str, Any]:
      # Returns: {"level": float, "z_score": float, "ready": True}
      # Returns: {"ready": False} when insufficient bars
  ```
  `"ready"` flag mirrors `cross_asset_features.py` convention — consistent degraded-gracefully sentinel.
- **D-10:** VIX instrument lookup: use `get_active_contracts()` to find the VIX contract dynamically — do not hardcode `"VXJ6"`. DB has both `VX` and `VIX` as active base symbols; resolve at startup to avoid fragility.

### Frame injection keys (D-11)
- **D-11:** FeaturePipelineService adds two new frame injections before I6 execution:
  ```python
  frames["cross_asset"]    # dict: cross_asset payload for current TF ({"ready": False} default)
  frames["cross_asset_5m"] # dict: cross_asset payload for 5m anchor ({"ready": False} default)
  frames["vix"]            # dict: {"level": float, "z_score": float, "ready": bool}
  ```
- **D-12:** `frames["cross_asset"]` and `frames["cross_asset_5m"]` follow the exact pattern already established in `signal_generator_service.py` (lines 1456–1459). Replicate — do not invent new patterns.
- **D-13:** `frames["cross_asset"]` is only injected for EQ_INDEX symbols (same guard as signal_generator: `resolve_eq_index_base(symbol) is not None`). `frames["vix"]` is injected for all symbols.
- **D-14:** FeaturePipelineService caches the cross_asset payload in `_cross_asset_cache: dict[str, dict]` (tf → payload) — same pattern as signal_generator_service. Subscribe to `topic_cross_asset()` via existing Kafka consumer.

### cross_timeframe.py computation (D-15)
- **D-15:** `ctf_eq_spread_z` derived from cross_asset payload with zero recompute:
  ```python
  cross_asset = frames.get("cross_asset", {})
  if cross_asset.get("ready"):
      active = cross_asset.get("active_pair", "ES_NQ")
      ctf_eq_spread_z = cross_asset.get(
          "es_nq_spread_z" if active == "ES_NQ" else "es_rty_spread_z"
      )
      ctf_eq_pairs_confirming = float(cross_asset.get("pairs_confirming", 0))
  ```
  No new computation — promotes existing `cross_asset_features.py` output to I6 field.
- **D-16:** `ctf_vix_level` and `ctf_vix_z` read directly from `frames["vix"]` dict. If `frames["vix"].get("ready")` is False, both fields emit `None`.

### Graceful degradation (D-17)
- **D-17:** All four new fields default to `None` when upstream data is unavailable. Cross_timeframe never substitutes 0.0 for missing data — always `None`. Callers (Phase 49 feature builder) handle None by excluding the feature for that bar, not imputing.

### Shadow dict update (D-18)
- **D-18:** The `capture_confluence_features()` function introduced in Phase 45 must be extended to include the four new fields in the `_shadow` dict. Planning-time task: update `confidence_utils.py` to read and log `ctf_vix_level`, `ctf_vix_z`, `ctf_eq_spread_z`, `ctf_eq_pairs_confirming` from `features` dict.

### Claude's Discretion
- `z_window = 20` default in `compute_vix_context()` — same as `_Z_SCORE_WINDOW` in `cross_asset_features.py` for consistency; planner may adjust
- Whether `frames["cross_asset_5m"]` is read by `cross_timeframe.py` or ignored (I6 already has multi-TF context via `intel_<tf>`; 5m variant may only matter for I7 plugins)
- `src/intelligence/context/` directory creation — new subdirectory, follows existing `src/intelligence/confluence/`, `src/intelligence/structure/` pattern

</decisions>

<specifics>
## Specific Ideas

- `cross_asset_features.py` is the exact template for `vix_context.py` — same module structure, same `"ready"` sentinel, same pure-function pattern, no imports from service layer
- `_CROSS_ASSET_VALID_TFS: frozenset[str] = frozenset({"1m", "5m", "15m", "1h"})` already defined in signal_generator_service — FeaturePipelineService should define its own equivalent constant rather than importing from signal_generator
- The `active_pair` field in cross_asset payload (`"ES_NQ"` or `"ES_RTY"`) drives which spread z-score to promote — use the dominant pair, not a fixed pair, so `ctf_eq_spread_z` always reflects the most active divergence

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### I6 schema (extension target)
- `src/intelligence/schemas.py` lines 678–710 — `I6Confluence` class; new fields added here; `IntelligenceEvent.i6` carries this type
- `src/intelligence/confluence/cross_timeframe.py` — `CrossTimeframeConfluencePlugin.compute_full()` output dict; new fields added to return value

### Frame injection pattern (replicate, don't invent)
- `services/signal_generator_service.py` lines 1455–1465 — canonical `frames["cross_asset"]` + `frames["cross_asset_5m"]` injection pattern; `_cross_asset_cache` dict pattern
- `services/signal_generator_service.py` lines 1500–1515 — cross_asset topic subscription + cache update pattern
- `services/feature_pipeline_service.py` lines 620–640 — existing frame assembly block; new injections go here

### VIX module template
- `src/intelligence/cross_asset_features.py` — pure function module pattern; `compute_eq_index_features()` signature and `{"ready": False}` convention; `vix_context.py` follows this exactly

### Cross_asset payload schema
- `src/intelligence/cross_asset_features.py` lines 233–245 — full cross_asset return dict; `es_nq_spread_z`, `es_rty_spread_z`, `pairs_confirming`, `active_pair`, `ready` fields
- `src/core/stream_keys.py` line 110 — `topic_cross_asset()` function

### Settings / instrument resolution
- `src/config/settings.py` — `get_active_contracts()`, VIX instrument entry (`base="VIX"`); use this to resolve VIX contract symbol dynamically

### Phase 45 shadow dict (extension needed)
- `.planning/phases/45-i6-i7-confluence-wiring-exhaustion-standardization/45-CONTEXT.md` D-07 — shadow dict schema; Phase 46 adds 4 new fields to this dict via `capture_confluence_features()` update

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `cross_asset_features.compute_eq_index_features()`: template for `compute_vix_context()` — same module structure, same ready/not-ready contract
- `resolve_eq_index_base(symbol)`: guards EQ_INDEX-only injection — already imported in signal_generator_service; FeaturePipelineService needs same import
- `topic_cross_asset(env_name)`: already in stream_keys.py; FeaturePipelineService subscribes using this

### Established Patterns
- `{"ready": False}` sentinel: used throughout cross_asset_features and signal_generator as the degraded-gracefully default — all new code follows this
- `_cross_asset_cache: dict[str, dict]` (tf → payload): canonical per-TF cache pattern from signal_generator_service; replicate in FeaturePipelineService
- `frames.get("key", {}).get("field")`: safe frame access pattern — always use `.get()` with default, never direct key access on frame dicts

### Integration Points
- FeaturePipelineService frame assembly block (lines 620–640): new injections slot in before I6 plugin execution
- `I6Confluence` → `IntelligenceEvent.i6` → `BarIntelligenceRecord` → `intelligence_features.i6` JSONB: new fields flow through automatically once added to `I6Confluence`
- Phase 45 `capture_confluence_features()` in `confidence_utils.py`: reads from `frames["features"]` which contains I6 output; must be updated to capture 4 new fields

</code_context>

<deferred>
## Deferred Ideas

- **Commodity/bond cross-asset groups** (CL/GC spread, ZN/ZB spread) — `cross_asset_service` currently EQ_INDEX only; extending to other groups is a future phase, not Phase 46
- **VIX term structure** (VX front vs back month spread) — more precise regime signal than spot VIX level; requires multi-contract VIX tracking; defer to Phase 50 or later
- **`ctf_eq_corr_break`** — `eq_corr_break` field in cross_asset payload (correlation break between short and long window) is also available but not included in Phase 46 to keep scope minimal; add to Phase 50 if Phase 49 signals it has alpha
- **Non-zero FVG/OB weights in ctf_score formula** — superseded by D-07; Phase 49 learns weights on independent `ctf_fvg_alignment`/`ctf_ob_alignment` fields; no formula change needed

</deferred>

---

*Phase: 46-i6-confluence-expansion*
*Context gathered: 2026-03-22*
