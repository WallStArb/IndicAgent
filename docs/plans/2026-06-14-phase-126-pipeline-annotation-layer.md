# Phase 126 — Plan P126-06: Pipeline-Layer Signal Annotation

**Status:** pending  
**Depends on:** P126-00 (USDJPY diagnostic must not block this; runs in parallel with Waves 1-2)  
**Blocks:** Phase 127 (Clean Replay) — replay corpus must be annotated uniformly before ML training

---

## Problem Statement

Every emitted signal is a labeled training example. The label is `counterfactual_pnl_r`. The feature vector is everything the model knew at the moment the signal fired: intrinsic detection factors, I6 cross-timeframe alignment, macro regime, exhaustion state, zone geometry, volatility.

The current design puts extrinsic context annotation inside plugin bodies. Each plugin developer calls `capture_signal_features()`, extracts `ctf_score`/`ctf_confirmed`/`zone_friction_score`, and passes them as kwargs to `make_signal_from_frame()`. This is a category error.

**A plugin is a pattern detector.** It fires when its intrinsic criteria are met. It knows nothing about I6. It does not need to know I6 exists. Annotation is infrastructure — it is what the pipeline applies uniformly to every signal the moment one fires.

The consequences of the current design:

1. **Selection bias in the corpus.** `ctf_score` is null for signals from Phase 118 canonical plugins (`ofi_continuation`, `cvd_divergence`, `gap_analysis_setup`) because those developers didn't add the explicit extraction. The ML model cannot distinguish "I6 had no data" (cold-start) from "this plugin didn't annotate." Training on a mixed null/populated corpus introduces a plugin-identity confound.

2. **The 30-key curated subset is a human judgment call baked into training data.** `capture_signal_features()` captures a fixed list of 28 CTF + macro fields. When a new I6 sub-score is added, it must be manually added to `capture_signal_features()`, then every plugin that calls it must be updated — or the new feature is silently absent for all historical signals until someone notices.

3. **`zone_friction_score` is produced by exactly one plugin.** It is not in the IntelligenceEvent schema and not in `flat_features`. For 29 of 30 signal-generating plugins, `zone_friction_score` is null — not because zone friction was absent but because no one formalized its production.

4. **`_I7_I6_EXEMPT` is a symptom of the root cause.** The 8 "exempt" plugins were carve-outs because wiring each plugin to I6 is tedious per-plugin work. With pipeline-layer annotation, the exemption category becomes meaningless — every plugin is annotated by the infrastructure, none by the plugin itself.

**The Renaissance principle: infrastructure annotates, detectors detect. Zero human discretion in the annotation layer.**

---

## Vocabulary

| Term | Definition | Location |
|------|-----------|----------|
| `flat_features` | Complete flattened I1-I6 feature vector for a bar, built from the typed IntelligenceEvent by `build_flat_features()`. This IS the complete model state at signal emission time. | `feature_flattening.py` |
| `context_features` | The extrinsic context snapshot stored on `signal_events`. After this plan: `flat_features` stored verbatim. Before: 30-key curated subset. | `signal_events.context_features` JSONB |
| **Surfaced ECL fields** | Key extrinsic fields promoted to top-level indexed columns on `signal_events` for fast SQL querying without JSONB extraction. Derived from `context_features` by `_annotate_signal()`. | `signal_events.ctf_score`, `.ctf_confirmed`, `.zone_friction_score` |
| `factor_scores` | Per-plugin intrinsic factor breakdown — the plugin's own computation. Stays in plugin bodies. | `signal_events.factor_scores` JSONB |

---

## What Changes

### What moves to the pipeline (infrastructure)

- Calling `capture_signal_features()` — removed from all plugin bodies
- Extracting `ctf_score`, `ctf_confirmed`, `zone_friction_score` — removed from all plugin bodies
- Passing `context_features=`, `ctf_score=`, `ctf_confirmed=`, `zone_friction_score=` to `make_signal_from_frame()` — removed

### What stays in plugins (detectors)

- Intrinsic detection logic — unchanged
- `factor_scores` construction — unchanged; only plugins know their own factors
- `frame_trade()` call and zone geometry — unchanged
- `shadow_only`, `requires_i6_confluence`, `regime_type` ClassVars — `requires_i6_confluence` becomes obsolete (see Step 7)

### What the pipeline does (new)

After any I7 plugin fires, before quality gate, `_annotate_signal(sig, flat_features)` runs on every raw signal:
1. Sets `sig["context_features"] = flat_features` — the full I1-I6 snapshot
2. Derives and surfaces top-level ECL fields from the snapshot

---

## Extensibility Contract

**Adding a new extrinsic feature to the training corpus:**

If the new feature is a formal tier output (added to IntelligenceEvent schema):
- Zero code changes needed. `build_flat_features()` iterates all tier sub-models; the new field appears in `flat_features` → automatically in `context_features` on every signal.

If the new feature should be promoted to a surfaced top-level column:
- Add one line to `_SURFACED_ECL_FIELDS` tuple in `signal_processor.py`
- Add one extraction line to `_annotate_signal()`
- Add a DB migration for the new column on `signal_events`
- No plugin changes

**Adding a new I6 plugin:**
- Zero annotation code needed. The new I6 output lands in IntelligenceEvent → `flat_features` → every signal's `context_features`.

This is the guarantee that the current design cannot provide.

---

## Steps

### Step 1 — Audit: what is and is not in `flat_features`

Before writing any code, establish ground truth on what `flat_features` contains vs. what is missing.

- [ ] Run a bar through the pipeline in debug mode and print all keys in `flat_features`. Document the complete key set.
- [ ] Confirm: `ctf_score`, `ctf_trend_alignment`, all 16 CTF sub-scores — are these in `flat_features`? (Expected: yes, via `i6` sub-model in `build_flat_features()`)
- [ ] Confirm: `exhaustion_score`, `exhaustion_side`, `exhaustion_bars` — are these in `flat_features`? (Expected: yes, via `i2` cmp_ExhaustionScore fields in IntelligenceEvent)
- [ ] Confirm: `vix_z`, `vix_level`, `ftq_score`, `yield_curve_slope`, `corr_z` — are these in `flat_features`? (Expected: yes, via `i4` sub-model)
- [ ] Confirm: `zone_friction_score` — is this in `flat_features`? (Expected: NO — not in IntelligenceEvent schema, see Step 2)
- [ ] Document any other fields currently in `capture_signal_features()` output that are NOT in `flat_features`
- [ ] Write findings to a comment block at the top of `_annotate_signal()` before implementation

### Step 2 — Formalize `zone_friction_score` production

`zone_friction_score` is currently produced by `supply_demand_setup.py` alone via plugin-local logic. It is not in the IntelligenceEvent schema. For it to appear in `flat_features` (and therefore in every signal's `context_features`), it must be produced by a formal tier.

- [ ] Read `supply_demand_setup.py` to understand exactly how `zone_friction_score` is computed — what inputs, what formula
- [ ] Determine the correct tier for it: if it is derived from zone structure (nearest_demand_low, nearest_supply_high etc.), it belongs in I3 (structure) or as an I6 confluence sub-score. If it requires real-time zone proximity from the live bar, I6 is correct.
- [ ] Decision: add `zone_friction_score: float | None` to the appropriate tier sub-model in `src/intelligence/schemas.py`
- [ ] Implement the computation in the chosen tier plugin (I3 or I6) using the same formula currently in `supply_demand_setup.py`
- [ ] Verify: after the tier computes it, `zone_friction_score` appears in `flat_features` automatically via `build_flat_features()`
- [ ] Remove the zone_friction computation from `supply_demand_setup.py` plugin body — it now reads from `flat_features` via the pipeline annotation

### Step 3 — Implement `_annotate_signal()` in `signal_processor.py`

- [ ] Add at module level:
  ```python
  from src.intelligence.trading.confidence_utils import MIN_CTF_SCORE

  # Surfaced ECL fields: top-level indexed columns on signal_events.
  # To add a new surfaced field: (1) add to this tuple, (2) add extraction
  # line in _annotate_signal(), (3) add DB migration for the column.
  _SURFACED_ECL_FIELDS: tuple[str, ...] = (
      "ctf_score",
      "ctf_confirmed",   # derived from ctf_score, not read from flat_features
      "zone_friction_score",
      # future: "exhaustion_score", "hmm_regime_weight", etc.
  )

  def _annotate_signal(sig: dict, flat_features: dict) -> None:
      """Pipeline-layer extrinsic annotation. Applied to every I7 signal uniformly.

      Plugins are pattern detectors — they return intrinsic evidence only.
      This function is the single point where the full market context at emission
      time is attached to every signal. No plugin may call capture_signal_features().

      Extensibility: new tier outputs appear in context_features automatically.
      New surfaced columns: add to _SURFACED_ECL_FIELDS + one line below + DB migration.
      """
      # Complete feature snapshot — the full I1-I6 state at signal emission time.
      # Stored as-is: build_flat_features() already filters None values.
      sig["context_features"] = flat_features

      # Surfaced ECL fields: derived from snapshot, promoted to indexed top-level columns.
      _ctf_raw = flat_features.get("ctf_score")
      ctf_score: float | None = float(_ctf_raw) if _ctf_raw is not None else None
      sig["ctf_score"] = ctf_score
      sig["ctf_confirmed"] = (abs(ctf_score) >= MIN_CTF_SCORE) if ctf_score is not None else None
      sig["zone_friction_score"] = flat_features.get("zone_friction_score")
  ```
- [ ] Wire into `process()` immediately after `pre_quality_confidence` stamping and before alpha decay. The annotation must precede all gates so that even regime-suppressed signals carry their full context:
  ```python
  # Extrinsic annotation — pipeline responsibility, applied uniformly before any gate.
  for sig in raw_signals:
      _annotate_signal(sig, features)
  ```
  (Note: `features` is already computed on the line that resolves flat_features vs build_flat_features.)

### Step 4 — Strip `capture_signal_features()` from all plugin bodies

This is a mechanical sweep across all 30 signal-generating plugins.

- [ ] Run: `grep -rn "capture_signal_features" src/intelligence/trading/` — list all call sites
- [ ] For each plugin file:
  - Remove the `capture_signal_features(...)` call and the `ctx = ` assignment
  - Remove `context_features=ctx` kwarg from `make_signal_from_frame()` call
  - Remove `from .confidence_utils import capture_signal_features` from imports if it's the only use
- [ ] For the 14 plugins that also extracted `ctf_score=`, `ctf_confirmed=`, `zone_friction_score=` explicitly: remove those extraction blocks and those kwargs from `make_signal_from_frame()` calls
- [ ] `grep -rn "capture_signal_features" src/intelligence/` after sweep — must return zero results outside `confidence_utils.py` itself and any remaining tests
- [ ] Do NOT touch `factor_scores` — that stays in plugin bodies

### Step 5 — Clean up `make_signal_from_frame()` in `signal_schema.py`

The ECL kwargs were plugin concerns. They are now pipeline concerns. Remove them from the construction boundary.

- [ ] Remove kwargs: `ctf_score`, `ctf_confirmed`, `zone_friction_score`, `context_features`, `features_snapshot`
- [ ] Remove corresponding `sig["ctf_score"] = ctf_score` etc. assignments — these are now set by `_annotate_signal()`
- [ ] Keep `factor_scores` kwarg — plugin-generated intrinsic breakdown, not a pipeline concern
- [ ] Audit: `features_snapshot` was used only for `zone_source` extraction (`sig["zone_source"] = (features_snapshot or {}).get("zone_source")`). Verify `zone_source` is passed through the TradeFrame result and set from there instead. If it is, `features_snapshot` kwarg is fully removable. If not, keep only `features_snapshot` for `zone_source` extraction.
- [ ] Run `grep -rn "ctf_score=\|ctf_confirmed=\|zone_friction_score=\|context_features=" src/intelligence/trading/` — must return zero results in plugin bodies

### Step 6 — Delete `_I7_I6_EXEMPT` and clean `validate_tier()`

- [ ] Delete `_I7_I6_EXEMPT` frozenset from `register_plugins.py`
- [ ] In `validate_tier()` in `src/intelligence/plugins/base.py`: remove the `requires_i6_confluence` check and the `_I7_I6_EXEMPT` carve-out. The annotation contract is now enforced by the pipeline, not by per-plugin ClassVar.
- [ ] Remove `requires_i6_confluence: bool` ClassVar from all 8 formerly-exempt plugins (it is now a meaningless field)
- [ ] `grep -r "_I7_I6_EXEMPT\|requires_i6_confluence" src/ tests/` — must return zero results

### Step 7 — Deprecate `capture_signal_features()` in `confidence_utils.py`

- [ ] Add a deprecation comment at the top of the function:
  ```python
  # DEPRECATED (Phase 126): Annotation is now pipeline-layer responsibility.
  # This function is no longer called from plugin bodies. See signal_processor._annotate_signal().
  # Retained for one release cycle; delete in Phase 128 after confirming no external callers.
  ```
- [ ] Confirm no external callers remain: `grep -rn "capture_signal_features" src/ services/ tests/` outside `confidence_utils.py` itself and any test that explicitly tests the function in isolation
- [ ] If tests reference `capture_signal_features()` directly: update them to test `_annotate_signal()` behavior instead

### Step 8 — Bump `SIGNAL_SCHEMA_VERSION`

`context_features` has changed from a 30-key curated subset to the full `flat_features` snapshot. This is a schema change.

- [ ] Increment `SIGNAL_SCHEMA_VERSION` in `src/intelligence/trading/signal_schema.py`
- [ ] Add a version changelog comment noting: "v(N+1): context_features is full flat_features snapshot (I1-I6 complete); previously 30-key curated subset from capture_signal_features(). Signals before this version have the old schema in context_features."
- [ ] Note in Phase 127 (Clean Replay) plan: ML training should segment by schema_version. Signals pre-Phase-126 have sparse context_features; signals post-Phase-126 have complete snapshots. Train only on post-126 corpus for context_features-dependent models.

### Step 9 — Unit tests

- [ ] `tests/unit/intelligence/test_pipeline_annotation.py` (new file):
  - Every signal emitted from `signal_processor.process()` has `context_features` that is non-empty
  - `ctf_score` is not null when `flat_features` contains a non-null `ctf_score`
  - `ctf_confirmed` is correctly derived (`abs(ctf_score) >= MIN_CTF_SCORE`)
  - `zone_friction_score` is not null when `flat_features` contains a non-null `zone_friction_score` (after Step 2 formalizes it)
  - `ctf_score` is null (not missing key — the key exists with None value) when `flat_features` has no `ctf_score` (cold-start simulation)
  - A plugin that does NOT call `capture_signal_features()` produces a fully annotated signal
  - Adding a new key to the mock `flat_features` dict causes it to appear in `signal["context_features"]` without code changes (extensibility contract test)
- [ ] `tests/unit/intelligence/test_i7_extrinsic_contract.py` (existing): update to assert `capture_signal_features` is NOT called in any plugin body (import graph check or AST inspection)
- [ ] `pytest tests/unit/ -q` green

---

## Success Criteria

| # | Criterion | Measurable condition |
|---|-----------|---------------------|
| A | Full snapshot on every signal | `signal["context_features"]` equals `flat_features` for every signal emitted by `signal_processor.process()` |
| B | Surfaced fields always populated | `ctf_score`, `ctf_confirmed`, `zone_friction_score` are present (not missing keys) on every signal; null only when source data is genuinely absent |
| C | Zero plugin annotation code | `grep -rn "capture_signal_features" src/intelligence/trading/` returns empty outside `confidence_utils.py` |
| D | Zero plugin ECL kwargs | `grep -rn "ctf_score=\|context_features=" src/intelligence/trading/` returns empty outside `signal_schema.py` |
| E | Exempt category deleted | `grep -r "_I7_I6_EXEMPT\|requires_i6_confluence" src/` returns empty |
| F | `zone_friction_score` formalized | `zone_friction_score` appears in `flat_features` output (verified by unit test); computed by a formal tier plugin, not a plugin body |
| G | Extensibility verified | Unit test confirms new key in `flat_features` automatically appears in `signal["context_features"]` |
| H | Schema version bumped | `SIGNAL_SCHEMA_VERSION` incremented; changelog comment added |
| I | Tests green | `pytest tests/unit/ -q` passes |

---

## What This Does NOT Change

| Item | Why untouched |
|------|--------------|
| `factor_scores` in plugin bodies | Plugin-specific intrinsic breakdown — only the plugin knows its factors |
| HMM regime gate in plugins | Emission eligibility gate is plugin responsibility; annotation is not |
| `frame_trade()` and zone geometry | Construction of TradeFrame is plugin concern |
| DB schema for `context_features` column | Already JSONB; content changes, schema does not |
| Signal lifecycle tracking | Unrelated to annotation |
| I6 plugin implementations | I6 computes its outputs regardless; this plan just captures them correctly |

---

## Impact on Phase 127 (Clean Replay)

The replay corpus produced after this plan is the first corpus where every signal carries a complete, uniform feature snapshot. This is the minimum requirement for any ML training on `context_features`. Phase 127 documentation should state: the clean replay is valid for ML training on context_features features from the first bar processed after Phase 126 deployment.

Signals generated before Phase 126 deployment have heterogeneous `context_features` (30-key curated subset, populated only for compliant plugins). They remain valid training data for `raw_confidence` and `factor_scores` models but should not be used for `context_features`-dependent models without schema_version filtering.

---

*Plan created: 2026-06-14*  
*Implements: ANNOTATION-INTEGRITY-01 (architecture uniformity), SIGNAL-QUALITY-03 (complete feature snapshot)*  
*Workstream A gate: must complete before Phase 127 (Clean Replay)*
