# Phase 45: I6 → I7 Confluence Wiring + Exhaustion Standardization - Context

**Gathered:** 2026-03-21
**Status:** Ready for planning

<domain>
## Phase Boundary

All 36 I7 plugins wire I6 ctf_* sub-scores AND exhaustion fields into their signal output as a standardized shadow capture dict — zero confidence modification in Phase 45. Shadow data feeds Phase 49 ML weight learning. Phase 47 graduates (flips the switch) once Phase 49 delivers learned weights.

Also fixes two infrastructure pain points in the same phase window: OHLCV chunk fragmentation (15,721 → ~365 chunks) and SignalLifecycleService O(N) scan → O(1) index.

</domain>

<decisions>
## Implementation Decisions

### ctf_fvg_alignment + ctf_ob_alignment exposure (D-01)
- **D-01:** Expose `ctf_fvg_alignment` and `ctf_ob_alignment` as new output fields from `cross_timeframe.py` — currently computed via `confluence_smc.py` (`score_fvg_alignment`, `score_ob_alignment`) but never emitted to the IntelligenceEvent. Add to output dict, `I6Context` schema in `schemas.py`, and `IntelligenceEvent`.
- **D-02:** Float range is **[0, 1]** — alignment scores, not signed directional values. Consistent with all other ctf_* fields (`ctf_trend_alignment`, `ctf_regime_agreement`). Default 0.0 when no FVG/OB data available.

### Shadow architecture — Option C, no weight computation (D-03)
- **D-03:** Phase 45 is **data capture only**. No confidence modification whatsoever. `capture_confluence_features()` reads raw ctf_* fields + exhaustion fields from `frames["features"]` and returns a structured `_shadow_dict`. Plugin assigns `signal["_shadow"] = shadow_dict`. Live `confidence` is unchanged.
- **D-04:** `ConfluenceWeightProfile` dataclass is defined in Phase 45 with all weights = 0.0. Serves as the interface contract for Phase 49 to fill in learned weights — code structure is in place, weights are placeholders. Each plugin declares its family profile name.
- **D-05:** Phase 49 learns optimal weights per plugin per regime. Phase 47 graduation flips `SHADOW_MODE = False` once Phase 49 weights are validated — no plugin body changes needed, just profile constants updated.

### capture_confluence_features() interface (D-06)
- **D-06:** Single function in `confidence_utils.py`:
  ```python
  def capture_confluence_features(
      features: dict[str, Any],
      direction: int,
      profile_name: str,
      existing_confidence: float,
  ) -> dict[str, Any]:
  ```
  Returns a `_shadow_dict` with raw feature values. No confidence modification. Per-plugin change is ~4 lines: one import, one call, one assignment to `signal["_shadow"]`.

### Shadow dict schema (D-07)
- **D-07:** Standardized schema — every plugin emits the same structure:
  ```python
  {
      "profile":              "trend",           # family name string
      "existing_confidence":  0.72,             # unchanged live score
      "ctf_score":            0.81,
      "ctf_trend_alignment":  0.74,             # always captured even if not primary for this family
      "ctf_structure_alignment": 0.60,
      "ctf_regime_agreement": 0.55,
      "ctf_fvg_alignment":    0.40,             # now available after D-01
      "ctf_ob_alignment":     0.35,             # now available after D-01
      "exhaustion_score":     0.45,
      "exhaustion_side":      "bull",
      "exhaustion_bars":      2.0,
  }
  ```
  Lives in `intelligence_features.i7` JSONB as `signal["_shadow"]`. Queryable: `i7 -> 'trad_TrendFollowing' -> '_shadow' ->> 'ctf_score'`. No migration, no new columns.

### Plugin family profile assignments (D-08)
- **D-08:** Five families, each declared as a constant in `confidence_utils.py`:
  - `"trend"` → TrendFollowing, MTFAlignment, MomentumBreakout, SqueezeExpansion, VCP, SecondLegContinuation, RegimeTransition
  - `"mean_reversion"` → MeanReversion, VWAPDeviation, VWAPReclaim, AnchoredVWAPReversion, POCRejection, HVNRejection
  - `"smc"` → FVGFill, CHoCHReversal, SupplyDemandSetup, LiquiditySweepReclaim, LiquidityHunt, PatternCompletion, LVNBreakout
  - `"microstructure"` → OFIContinuation, OFIDivergence, OFISpike, CVDDivergence, CVDSpike, DivergenceStack, DualDivergence, CrossAssetDivergence
  - `"session"` → SessionExtremesSetup, FailedBreakout, ORB15, ORB30, PrevDayLevelTest, GapAnalysisSetup, CandlestickPatternSetup
  - `"exempt"` → DeltaExhaustion (IS the exhaustion signal — see D-09)

### DeltaExhaustion exemption (D-09)
- **D-09:** `DeltaExhaustion` is exempt from exhaustion field capture in shadow dict — it IS the exhaustion detector. Calling `apply_exhaustion_guard` on itself is circular. Still captures ctf_* fields. Documents exemption with explicit inline comment: `# exempt from exhaustion shadow: this plugin IS the exhaustion detector`.

### Microstructure family treatment (D-10)
- **D-10:** OFI/CVD/delta are execution signals, not structural signals. CTF misalignment doesn't invalidate OFI — it signals hostile context. Shadow dict captures `ctf_score` raw for Phase 49 to learn the optimal gate/modifier behavior. No confidence modification in Phase 45.

### Infrastructure: OHLCV rebuild (D-11) — DROPPED
- **D-11:** ~~OHLCV rebuild~~ — **Not needed.** `market_data_ohlcv` was cleared during Phase 44.3 (0 chunks), chunk interval already set to 30 days (verified 2026-03-21). The 15,721-chunk fragmentation problem no longer exists. Plan 45-04 removed from phase scope.

### Infrastructure: Lifecycle O(1) index (D-12)
- **D-13:** SignalLifecycleService active-signal lookup replaced with `{(symbol, tf): [signal_ids]}` index dict. Chandelier state written to DB only when stop price changes by ≥ 0.01% (write guard).
- **D-14:** Separate plan (45-04, was 45-05) — independent of all confluence wiring plans.

### Claude's Discretion
- Exact `ConfluenceWeightProfile` field names (weights are all 0.0 as placeholders anyway)
- How `capture_confluence_features()` handles missing ctf_* fields (safe `.get(key, 0.0)` defaults)
- Whether TrendFollowing's existing `ctf_score` usage is refactored to the new pattern or left as-is (it already works correctly as a reference impl)
- Per-plugin family assignment edge cases during planning (e.g. ChoCH is reversal-like but SMC family makes more sense structurally)

</decisions>

<specifics>
## Specific Ideas

- `trend_following.py` is the reference implementation — already has `ctf_score` wired (0.20 weight) + `apply_exhaustion_guard`. Phase 45 refactors it to use `capture_confluence_features()` and removes the inline weight (weight → 0.0 in profile placeholder). This makes it consistent with all other plugins rather than a special case.
- Shadow dict should be captured even when a signal does NOT fire (for rejected signals) — this gives Phase 49 negative examples. Add shadow capture before early-exit returns where feasible. **Not mandatory for Phase 45 — nice-to-have, defer to planning judgment.**
- "We're not in a rush" — Phase 49 delivers learned weights. Phase 47 graduation waits for Phase 49. No pressure to hardcode anything.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### I6 confluence output (what's being exposed)
- `src/intelligence/confluence/cross_timeframe.py` — current output dict (lines 114-119); `score_fvg_alignment` and `score_ob_alignment` called here but not emitted
- `src/intelligence/confluence/confluence_smc.py` — `score_fvg_alignment()` and `score_ob_alignment()` implementations; return values are [0,1] floats
- `src/intelligence/schemas.py` lines 688-693 — current `I6Context` ctf_* fields; `ctf_fvg_alignment` and `ctf_ob_alignment` must be added here

### I7 plugin infrastructure (wiring target)
- `src/intelligence/trading/confidence_utils.py` — `compose_confidence()`, `CONF_FLOOR`, `CONF_CEIL`; `capture_confluence_features()` and `ConfluenceWeightProfile` go here
- `src/intelligence/trading/exhaustion_utils.py` — `apply_exhaustion_guard()`, `apply_exhaustion_boost()` signatures; shadow dict must capture exhaustion fields from `frames["features"]`
- `src/intelligence/trading/plugin_utils.py` — existing utility patterns; follow same import/export conventions
- `src/intelligence/trading/trend_following.py` — reference implementation; currently has inline `ctf_score` wiring (lines 58, 87-93) and `apply_exhaustion_guard` (line 109); refactor to `capture_confluence_features()` pattern

### Plugin registry
- `src/intelligence/register_plugins.py` — `TIER_I7` list (36 plugins); all must be wired

### ROADMAP success criteria
- `.planning/ROADMAP.md` §Phase 45 — 7 success criteria (SC-1 through SC-7); grep confirms, shadow log visible, lifecycle O(1), OHLCV ≤ 400 chunks

### Infrastructure targets
- `services/signal_lifecycle_service.py` — O(N) active-signal scan to replace with O(1) index dict
- `src/intelligence/trading/lifecycle_tracker.py` — chandelier state; add ≥ 0.01% write guard

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `confidence_utils.compose_confidence()`: all plugins already call this as their final step — natural integration point, `capture_confluence_features()` gets called just before it
- `exhaustion_utils.apply_exhaustion_guard/boost()`: existing functions; shadow dict captures the same `exhaustion_score`, `exhaustion_side`, `exhaustion_bars` fields these read
- `plugin_utils.no_signal()`: used for early exits — consider whether shadow capture makes sense before early exits (planning discretion)
- `signal_schema.make_signal()`: constructs signal dicts; `_shadow` key added after construction, not inside factory

### Established Patterns
- `frames["features"]` dict: all I7 plugins already read from this; ctf_* and exhaustion fields are available here once I6 runs
- `features.get("key", 0.0)` safe default pattern: used throughout I7 plugins; apply same to ctf_fvg_alignment + ctf_ob_alignment
- `dataclass` plugin pattern: all I7 plugins are `@dataclass`; `ConfluenceWeightProfile` follows same convention

### Integration Points
- `cross_timeframe.py` output dict → `IntelligenceEvent.i6` → `frames["features"]` in I7 plugins: adding `ctf_fvg_alignment` and `ctf_ob_alignment` flows through this path automatically
- `intelligence_features.i7` JSONB column: shadow dict stored here as `signal["_shadow"]`; no schema migration needed

</code_context>

<deferred>
## Deferred Ideas

- **Shadow capture on rejected signals** (negative training examples for Phase 49) — mentioned as a nice-to-have; defer to planning judgment, not mandatory for Phase 45
- **Per-regime shadow logging** (log which regime was active at signal fire time alongside ctf features) — useful for Phase 49 but out of scope; `regime_type` is already in the signal dict so Phase 49 can join on it anyway
- **ConfluenceWeightProfile weights** (non-zero values) — explicitly deferred to Phase 49; Phase 45 placeholders are all 0.0
- **Phase 47 graduation flag** (`SHADOW_MODE` constant) — the constant should be placed during Phase 45 (set to True) so Phase 47 only needs to flip it; where to put it (settings.py vs confidence_utils.py) is a Phase 47 decision

</deferred>

---

*Phase: 45-i6-i7-confluence-wiring-exhaustion-standardization*
*Context gathered: 2026-03-21*
