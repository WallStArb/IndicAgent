# Phase 124: Signal Universe Integrity + Cold-Start Hardening - Context

**Gathered:** 2026-06-14
**Status:** Ready for planning
**Source:** `docs/plans/2026-06-14-v2.10-signal-architecture-refactor.md` (Phase 124 section, lines ~440-625) + codebase scout + Renaissance-council discussion

<domain>
## Phase Boundary

Phase 124 delivers three coupled fixes that must all land before the Phase 126 clean replay, so the replayed corpus is valid training data:

1. **Signal universe integrity** — rewrite the detection conditions of 5 over-firing I7 plugins (15-30%/bar → reference band) so every signal in the raw universe represents an identifiable market structure, not a generic state.
2. **Cold-start hardening** — stop cold-start I6 readings from being frozen into `intelligence_features` via `ON CONFLICT DO NOTHING`; allow correction on replay via an `IS NULL`-only guard on promoted CTF columns.
3. **`--warmup` replay pass** — add an I1-I6-only pre-pass to `run_historical_pipeline.py` so the I6 cache is warm before the signal pass (replay-only solution to a replay-only cold-start problem).

**In scope:**
- 5 plugin structural detection rewrites: `trend_following`, `ofi_continuation`, `liquidity_sweep_reclaim`, `pattern_completion`, `anchored_vwap_reversion`
- Migration promoting 4 CTF sub-scores to top-level nullable columns on `intelligence_features` (+ JSONB strip for single source of truth)
- `ON CONFLICT (ts, symbol, tf) DO UPDATE ... WHERE ctf_score IS NULL` guard in `feature_writer`
- `--warmup` flag + `skip_signals` path in `run_historical_pipeline.py`
- Reader migration (grep-driven) for code reading CTF from the JSONB
- D6 SQL fire-rate sanity check (aggregate + segmented)

**Out of scope:**
- Full clean replay (Phase 126 exercises the cold-start mechanism over history)
- 3-table signal schema migration `signal_events`/`trade_frames`/`trade_executions` (Phase 127-129)
- CounterfactualTracker daemon + I6 DB bootstrap at daemon startup (Phase 130, v2.11 — permanent live cold-start fix; `--warmup` is replay-only)
- Authoritative fire-rate/edge validation (Phase 126)
- APR parameter migration (Phase 125)

</domain>

<decisions>
## Implementation Decisions

### Plugin Fix Philosophy (governing principle)

**D-01: Structural rewrite for all 5 plugins — NOT onset-guard/cooldown dedup.**

Governing principle (Renaissance-council, per user directive and the `i7-signal-quality-findings` memory): every signal in the raw universe must represent an identifiable market structure — an a priori hypothesis distinguishable from noise. Deduping a still-too-broad condition via onset guards/cooldowns lowers the *count* but leaves the *population* contaminated; the ML/genetic optimizer cannot learn from non-events. The raw signal universe IS the training data.

Therefore: for all 5 plugins, the broad continuous metric is **demoted to a context filter**, and the **trigger is re-anchored to a specific structural event**. The spec's D1-D5 onset-guard/cooldown mechanics are mostly superseded by this decision.

**D-02: Per-plugin structural mandates (researcher reads `compute_full()` and anchors each trigger to real structure).**

| Plugin | Broad metric → context filter | New structural trigger (researcher mandate) |
|---|---|---|
| `trend_following` | `abs(trend_regime) >= threshold` ("is trending") | Structural entry within the trend: pullback-to-MA reversal bar, or breakout from consolidation. `trend_regime` becomes a context filter (must be trending), not the trigger. NOT the spec's entry-window onset (which is just trend-onset, still fires on every new trend). |
| `ofi_continuation` | N-bar OFI streak (persistence) | Fresh OFI acceleration/thrust bar on top of the sustained imbalance. Streak = context; acceleration = trigger. Cooldown alone (spec D2) is a band-aid — insufficient. |
| `pattern_completion` | confidence score crossing 0.70 | Pattern's structural completion criterion (target reached / neckline break). Pattern **instance is consumed** after firing — track instance IDs; never re-fire the same instance. Confidence score is the wrong anchor. |
| `liquidity_sweep_reclaim` | `sweep_reclaimed` flag (stays hot) | Rising-edge **is** the event (spec D3 correct). Add structural specificity: close-above the swept level with acceptance, not a wick. |
| `anchored_vwap_reversion` | proximity to VWAP | Departure (>= N ATR) + return **is** the structure (spec D5 correct). Add rejection/reclaim candle confirmation on return, not just price touching VWAP. |

**D-03: Researcher must verify plugin history/state access.** The scout shows `compute_full(self, frames: dict[str, Any])` receives a single current frame, not a history window. The spec's `features_history[-i]` / `features_prev` / `frames[-i]` references assume history that may not be in scope. If a structural trigger needs lookback (TrendFollowing pullback, AnchoredVWAP departure, PatternCompletion instance tracking), the researcher/planner designs the state mechanism — likely a per-plugin rolling buffer via the `Parallel dicts → dataclass` pattern (CLAUDE.md rule) and pattern-instance ID tracking for `PatternCompletion`. This is implementation-level; not pre-decided here.

### Cold-Start Storage Shape

**D-04: Promote 4 CTF sub-scores to top-level nullable columns now.** The spec's D8 SQL targets columns that do not exist (scout confirms only `cross_timeframe_context` JSONB exists). This is the long-term, correct design: CTF sub-scores are first-class extrinsic features ML attributes against and must support clean NULL semantics. Phase 127 designs the *signal-side* 3-table split; this is the *feature-side* substrate 124 owns and 127 inherits. NOT scope creep — faithful to the roadmap success criterion (`WHERE ctf_score IS NULL`).

Migration (next global number — researcher confirms; global max is 123):
1. `ALTER TABLE intelligence_features ADD COLUMN IF NOT EXISTS ctf_score double precision` (and `ctf_trend_alignment`, `ctf_structure_alignment`, `ctf_regime_agreement`) — all nullable.
2. Backfill from JSONB: `UPDATE intelligence_features SET ctf_score = NULLIF(cross_timeframe_context->>'ctf_score','')::double precision WHERE ctf_score IS NULL` (handle null vs missing key vs empty string).
3. **Single source of truth:** strip the 4 CTF keys from `cross_timeframe_context` JSONB (keep non-CTF I6 context). Researcher grep-migrates any reader pulling CTF from the JSONB to the columns.

**D-05: IS NULL-only guard (Phase 123 locked).** `ON CONFLICT (ts, symbol, tf) DO UPDATE SET ctf_score=EXCLUDED.ctf_score, ctf_trend_alignment=EXCLUDED.ctf_trend_alignment, ctf_structure_alignment=EXCLUDED.ctf_structure_alignment, ctf_regime_agreement=EXCLUDED.ctf_regime_agreement WHERE intelligence_features.ctf_score IS NULL`. Guard on `ctf_score IS NULL` is the cold-start proxy (I6 computes all four together). NEVER `IS NULL OR = 0.0` — 0.0 is genuine neutral (Phase 123).

**D-06: Pre-Phase-123 rows frozen at 0.0 are NOT corrected here.** Those rows are regenerated by the Phase 126 clean replay. 124 ships the mechanism; 126 exercises it over history. Correct separation.

**D-07: Spec file path is stale.** `feature_writer.py` lives at `services/feature_writer.py` (ON CONFLICT at line 96), not `src/intelligence/writers/feature_writer.py` as the spec states. Use the real path.

### Waves

**D-08: Two waves.** Wave A (deterministic, ship first): D-04 migration + D-05 guard + reader migration + `--warmup` flag. Unit-test gated, no behavioral iteration. Wave B (behavioral, after): the 5 plugin structural rewrites + D6 segmented fire-rate sanity. Foundation before risk.

**D-09: 124 does NOT run a full replay.** Authoritative fire-rate/edge validation is Phase 126's job. 124 lands code + a SQL sanity check on available data. The whole point of the refactor is the replay runs once, clean, over corrected everything.

### Fire-Rate Diagnostic

**D-10: Fire-rate is a diagnostic, not a tuned target.** A correct structural rewrite naturally lands in the reference band (0.1-2.5%: SqueezeExpansion 0.3%, SupplyDemand 0.1%, CVDDivergence 1-2.5%) because the condition became genuinely rare. If still high, iterate the structure, not a threshold. No one-size number — each plugin's bar is its own structural frequency.

**D-11: Segment by regime (Renaissance refinement).** Aggregate fire-rate hides regime-specific noise. D6 SQL measures fire-rate by `setup_plugin × symbol × timeframe × regime`; no segment is a hotspot (>~5%). A hotspot = residual non-event contamination concentrated in that regime.

**124 sanity gate (two-part):**
1. Aggregate material reduction: 15-30% → single digits (rewrite changed behavior)
2. Segmented: no `setup_plugin × symbol × timeframe × regime` segment > ~5%

**126 authoritative gate (deferred, for reference):** aggregate in reference band OR documented justification; plus edge (`pnl_r`/`counterfactual`) non-random per shadow promotion gate (n>=100, bootstrap CI lower > 0).

**D-12: Validation table in 124 is `signal_ledger.setup_plugin`.** The 3-table `signal_events` migration is Phase 127-129; researcher confirms `signal_events` does not yet exist (Phase 123 was schema fields + gate removal, not table creation).

### Claude's Discretion

- Exact migration number (confirm global max, watch the 120/121 pre-existing conflicts between `production/migrations/` and `db/migrations/` noted in Phase 122)
- How JSONB null/missing-key/empty-string is normalized during backfill (the `NULLIF(...,'')::double precision` pattern, plus missing-key handling)
- Whether `--warmup`'s `skip_signals` path already exists in `run_historical_pipeline.py` or must be added (researcher confirms)
- Per-plugin structural trigger specifics within the mandates in D-02 (the mandate names the structure class; the planner specifies the geometry)
- Commit sequence within each wave

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Authoritative spec (read the Phase 124 section, but note the errors flagged in D-04/D-07)
- `docs/plans/2026-06-14-v2.10-signal-architecture-refactor.md` §Phase 124 (lines ~440-625) — D1-D10 detail, success criteria. NOTE: D8 SQL targets non-existent columns (see D-04); file path for feature_writer is stale (see D-07). The onset-guard/cooldown mechanics (D1, D2, D4) are superseded by D-01/D-02.

### Plugin source (all 5 to rewrite)
- `src/intelligence/trading/trend_following.py` — `compute_full(self, frames)` at line 55
- `src/intelligence/trading/ofi_continuation.py`
- `src/intelligence/trading/liquidity_sweep_reclaim.py`
- `src/intelligence/trading/pattern_completion.py`
- `src/intelligence/trading/anchored_vwap_reversion.py`

### Cold-start + warmup plumbing
- `services/feature_writer.py` — `ON CONFLICT (ts, symbol, tf) DO NOTHING` at line 96 (NOT `src/intelligence/writers/`)
- `production/scripts/run_historical_pipeline.py` — add `--warmup`; check for existing `skip_signals` path
- `production/migrations/` — migration conventions; global max is 123; beware 120/121 conflicts

### Schema + semantics (locked by Phase 123)
- `.planning/phases/123-ecl-boundary-restoration/123-CONTEXT.md` — None-vs-0.0 semantics (D-05 guard basis); ECL boundary (all extrinsic vectors are annotations, not gates)
- `src/intelligence/trading/signal_schema.py` — `SIGNAL_SCHEMA_VERSION`, `REQUIRED_PIPELINE_FIELDS`

### Architecture + principles
- `docs/architecture/setup-confidence-patterns.md` — post-Phase-123 name; CONFIDENCE FACTOR vs ECL distinction
- `docs/foundation/principles.md` — "segment by regime", "data quality over model complexity", "the raw signal universe is the training data"
- `CLAUDE.md` — DAG invariants, `Parallel dicts → dataclass` rule, asyncpg JSONB handling, IS NULL semantics

### Reference behavior (well-behaved plugin fire-rates)
- SqueezeExpansion ~0.3%, SupplyDemand ~0.1%, CVDDivergence 1-2.5% — the target diagnostic band

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `Parallel dicts → dataclass` pattern (CLAUDE.md) — for per-plugin rolling buffers if lookback state is needed (TrendFollowing pullback, AnchoredVWAP departure window, PatternCompletion instance registry)
- `get_atr_with_floor_from_frames` / `get_atr_with_floor` (atr_utils.py) — ATR-based distance thresholds (AnchoredVWAP departure ATR, reference Phase 122 D-14)
- Existing rising-edge / event-onset patterns in well-behaved plugins (SqueezeExpansion, SupplyDemand) — reference for how structural-once detection is done correctly in this codebase

### Established Patterns
- I7 `compute_full()` returns a signal dict via `emit_signal`/`make_signal_from_frame` (Phase 123 added ECL field threading); structural triggers must thread through the same emit path
- `no_signal()` is the no-emit contract (vs raising)
- Migrations: `ADD COLUMN IF NOT EXISTS` guard (Phase 122 D-06 precedent — migration 013 made a prior attempt at an i2 column)
- `SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0` per connection before any DML on compressed chunks (Phase 121 pattern)

### Integration Points
- `services/feature_writer.py` `_INSERT_FEATURE_SQL` / `_record_to_insert_params` — where the 4 new CTF columns enter the INSERT tuple and the ON CONFLICT guard lives
- `cross_timeframe_context` JSONB — source for backfill, then stripped of CTF keys
- `signal_ledger.setup_plugin` — fire-rate diagnostic table in 124
- `run_historical_pipeline.py` `run_pipeline()` — `--warmup` calls it twice (skip_signals=True, then normal)

</code_context>

<specifics>
## Specific Ideas

- The user's standing directive throughout this discussion: apply Renaissance-council / Jim Simons rigor — data integrity paramount, eliminate complexity, single source of truth, segment by regime, guard against hidden biases (aggregate numbers hide regime-specific noise), build a foundation each iteration refines. This is encoded in CLAUDE.md design mindset and reinforced here.
- Single source of truth (D-04): once CTF is promoted to columns, the JSONB must NOT retain a duplicate copy — strip the keys in the same migration. Two sources of truth = drift.
- The spec's onset-guard fixes (D1 entry-window, D2 cooldown, D4 threshold-crossing) are explicitly rejected for the 3 continuous-score plugins because they dedupe a still-too-broad condition and would contaminate training data per the i7-signal-quality-findings memory. The spec's edge/structural fixes (D3 rising-edge, D5 departure+return) are retained and reinforced with added structural specificity.

</specifics>

<deferred>
## Deferred Ideas

- **CounterfactualTracker daemon + I6 DB bootstrap at daemon startup** — Phase 130 (v2.11). Permanent cold-start elimination for *live* trading. `--warmup` is the replay-only solution; live trading needs the daemon to bootstrap I6 state from `intelligence_features` at startup.
- **Full historical cold-start correction (pre-Phase-123 rows frozen at 0.0)** — Phase 126 clean replay regenerates everything; the IS NULL guard (D-05) deliberately does not touch 0.0 rows.
- **Authoritative fire-rate + edge validation** — Phase 126 (clean replay over corrected pipeline).
- **3-table signal schema** — Phase 127-129.
- **APR parameter migration (51 constants)** — Phase 125.

</deferred>

---

*Phase: 124-signal-universe-integrity-cold-start-hardening*
*Context gathered: 2026-06-14 via /gsd-discuss-phase (Renaissance-council discussion)*
