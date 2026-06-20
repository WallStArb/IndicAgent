# Phase 123: ECL Boundary Restoration - Context

**Gathered:** 2026-06-14
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-06-14-v2.10-signal-architecture-refactor.md)

<domain>
## Phase Boundary

Remove all extrinsic emission suppressors across all I7 plugins. Add 5 ECL fields plus `context_features` to the signal schema. Promote `context_features` from the `_shadow` dict to a persisted top-level signal field. Collect `factor_scores` dict in all 37 plugins before compositing. Bump `SIGNAL_SCHEMA_VERSION`. Rename architecture doc from `i7-setup-confidence-patterns` to `setup-confidence-patterns` and add ECL definition.

This phase is split into three waves:
- **Wave A** — Gate removal + schema (replay-blocking, must ship first)
- **Wave B** — Factor score persistence (same phase, not replay-blocking)
- **Wave C** — Architecture doc rename and update

</domain>

<decisions>
## Implementation Decisions

### Signal Schema (Wave A)
- Add 5 new nullable ECL fields to `src/intelligence/trading/signal_schema.py`: `ctf_score: float | None`, `ctf_confirmed: bool | None`, `zone_friction_score: float | None`, `factor_scores: dict | None`, `context_features: dict | None`
- `None` means "no data at emit time"; `0.0` means "genuine neutral reading" — these are semantically distinct populations. No `or 0.0` fallbacks.
- Increment `SIGNAL_SCHEMA_VERSION` by 1 in `signal_schema.py`
- Add all 5 new fields to `REQUIRED_PIPELINE_FIELDS` frozenset — `factor_scores` and `context_features` use `{}` (empty dict, not None) as the "plugin not yet updated" sentinel
- `mtf_alignment` plugin is EXEMPT from CTF gate removal — CTF is its intrinsic signal

### CTF Gate Removal (Wave A)
- Remove all `if abs(ctf_score) < get_min_ctf_score(): return no_signal()` patterns from all 17 `_PHASE_119_PLUGINS`
- Replacement pattern: `_ctf_raw = features.get("ctf_score"); ctf_score: float | None = float(_ctf_raw) if _ctf_raw is not None else None; ctf_confirmed: bool | None = (abs(ctf_score) >= get_min_ctf_score()) if ctf_score is not None else None`
- Pass `ctf_score=ctf_score, ctf_confirmed=ctf_confirmed` to `emit_signal`
- Affected plugins (17): `ofi_spike`, `cvd_spike`, `ofi_divergence`, `failed_breakout`, `candlestick_pattern_setup`, `session_extremes_setup`, `liquidity_hunt`, `delta_exhaustion`, `lvn_breakout`, `vwap_reclaim`, `vwap_deviation`, `momentum_breakout`, `orb15`, `orb30`, `second_leg_continuation`, `vcp`, `dual_divergence`
- Also: `microstructure_utils.detect_spike_signal` (delegate used by ofi_spike + cvd_spike)

### CTF Composite Violations (Wave A)
- `delta_exhaustion.py`: Remove `ctf_score_factor` from composite; rebalance to `0.35*exhaustion + 0.30*momentum_reversal + 0.25*volume + 0.10*persistence`
- `microstructure_utils.detect_spike_signal`: Remove CTF gate delegate and `ctf_factor` from composite; rebalance to `0.50*z_score + 0.30*volume + 0.20*persistence`

### Zone Friction Gate Removal (Wave A)
- Remove all `if zone_friction > _MAX_ZONE_FRICTION: return no_signal()` patterns
- Primary file: `supply_demand_setup.py`; grep for others
- Replacement: annotate as `zone_friction_score: float | None` top-level field, pass to `emit_signal`
- Null-preserving pattern: `_zf_raw = features.get("zone_friction_score"); zone_friction_score: float | None = float(_zf_raw) if _zf_raw is not None else None`

### Exhaustion Guard Audit (Wave A)
- Run `grep -rn "exhaustion_guard\|exhaustion_score.*no_signal\|no_signal.*exhaustion"` to find any emission suppressors
- Expected result: exhaustion score is already a feature, not a gate — no suppressors found
- If suppressors found: remove gate, annotate as `exhaustion_score: float | None` field

### context_features Promotion — Three-File Change (Wave A)
- `confidence_utils.py`: Change `capture_signal_features()` from writing to `sig["_shadow"]` to returning the dict; keep backward-compat `_shadow` write during transition
- Every I7 plugin calling `capture_signal_features()`: capture return value into `signal["context_features"]`
- `services/signal_writer.py`: Read new fields from Kafka payload in `_parse_signals()` / `_build_ledger_entries()`

### emit_signal / make_signal_from_frame Threading (Wave A)
- Add `ctf_score`, `ctf_confirmed`, `zone_friction_score`, `factor_scores`, `context_features` parameters to both functions in `plugin_utils.py`
- All optional, default `None`; pass through to `validate_signal` and the signal dict

### _PHASE_119_PLUGINS Frozenset Removal (Wave A)
- Delete `_PHASE_119_PLUGINS` frozenset and its comment from `register_plugins.py`
- Grep must return zero hits after deletion

### Test Updates (Wave A)
- `tests/unit/intelligence/test_i7_extrinsic_contract.py`: Flip assertions — `ctf=0.0 → no_signal()` becomes `ctf=None → valid signal with ctf_confirmed=False`
- Any test that mocks signals without the 5 new fields: add `"factor_scores": {}, "context_features": {}`

### Factor Scores Collection (Wave B)
- Every `compute_full()` in all 37 plugins collects `factor_scores` dict before compositing
- Keys are plugin-specific, values are pre-composite [0, 1] scores, rounded to 4 decimal places
- Pass `factor_scores=factor_scores` to `emit_signal`

### Architecture Doc (Wave C)
- `git mv docs/architecture/i7-setup-confidence-patterns.md docs/architecture/setup-confidence-patterns.md`
- Update doc: title, add ECL section, update Pattern Vocabulary table to distinguish CONFIDENCE FACTOR vs EXTRINSIC CONFIDENCE VECTOR (ECL)
- Update Pattern 3 description
- Update all cross-references across docs/, src/, tests/

### Claude's Discretion
- Order of file modifications within Wave A (the spec identifies dependencies but the exact commit sequence within the wave is implementation-level)
- How to handle signal dicts in unit tests that don't yet include the new ECL fields (use `{}` defaults)
- Whether to add `ctf_score`, `ctf_confirmed`, `zone_friction_score` to LedgerEntry now or leave for Phase 128 writer migration (confirm against signal_writer.py current schema)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Signal Schema
- `src/intelligence/trading/signal_schema.py` — `SIGNAL_SCHEMA_VERSION`, `REQUIRED_PIPELINE_FIELDS`, signal dict shape
- `src/intelligence/trading/plugin_utils.py` — `emit_signal`, `make_signal_from_frame` signatures
- `src/intelligence/trading/confidence_utils.py` — `capture_signal_features`, `compose_confidence`

### ECL Architecture
- `docs/plans/2026-06-14-v2.10-signal-architecture-refactor.md` — authoritative spec (Phase 123 section, lines ~58-438)
- `docs/architecture/setup-confidence-patterns.md` (or `i7-setup-confidence-patterns.md` pre-rename) — current architecture doc

### Plugin System
- `src/intelligence/register_plugins.py` — `_PHASE_119_PLUGINS` frozenset, plugin tier lists
- `src/intelligence/CLAUDE.md` — plugin tier details and I7 confidence pattern rules

### Signal Pipeline
- `src/intelligence/pipeline/signal_processor.py` — where context_features must be injected into signal record
- `services/signal_writer.py` — `_parse_signals` / `_build_ledger_entries` — where new fields are read from Kafka payload

### Tests
- `tests/unit/intelligence/test_i7_extrinsic_contract.py` — the test file that must be updated

### Foundation
- `CLAUDE.md` — DAG invariants, signal status strings, asyncpg rules, signal schema field names
- `docs/foundation/principles.md` — data retention and emit-all principles

</canonical_refs>

<specifics>
## Specific Implementation Notes

### Phase 123 Success Criteria (from spec)
1. `pytest tests/unit/intelligence/ -q` — green
2. `grep -rn '"ctf_score".*or 0\.0\|"ctf.*", 0\.0' src/` — zero hits
3. `grep -rn "_PHASE_119_PLUGINS" src/ tests/` — zero hits
4. `grep -rn "zone_friction.*no_signal\|no_signal.*zone_friction" src/intelligence/trading/` — zero hits
5. `grep -rn "i7-setup-confidence-patterns" docs/ src/ tests/` — zero hits
6. All 37 plugin `compute_full()` methods collect `factor_scores` dict
7. `context_features` populated from `signal_processor.py`, not from `_shadow` dict
8. `SIGNAL_SCHEMA_VERSION` incremented

### Key Invariant
`factor_scores` and `context_features` use `{}` (empty dict, not `None`) as the absent-plugin-sentinel. `None` is reserved for "field not written" — distinct from "plugin emitted no factors".

### Verification Gate After Wave A
After wave A is deployed (in review/test), run:
```sql
SELECT COUNT(*) FILTER (WHERE context_features IS NOT NULL) AS with_ctx,
       COUNT(*) FILTER (WHERE context_features IS NULL)     AS null_ctx
FROM signal_ledger
WHERE ts > now() - interval '10 minutes';
```
Expected: `null_ctx = 0` for signals produced after the deploy.

</specifics>

<deferred>
## Deferred Ideas

- `--warmup` flag for historical replay — deferred to Phase 124
- ON CONFLICT IS NULL guard for CTF columns in feature_writer — deferred to Phase 124
- 5 over-firing plugin fixes — deferred to Phase 124
- APR parameter migration — deferred to Phase 125
- Clean replay — deferred to Phase 126
- 3-table schema design — deferred to Phase 127
- Database migration — deferred to Phase 128
- Script rewriting — deferred to Phase 129
- CounterfactualTracker daemon — deferred to Phase 130 (v2.11)
- I6 DB bootstrap at daemon startup — deferred to Phase 130 (v2.11)

</deferred>

---

*Phase: 123-ecl-boundary-restoration*
*Context gathered: 2026-06-14 via PRD Express Path (docs/plans/2026-06-14-v2.10-signal-architecture-refactor.md)*
