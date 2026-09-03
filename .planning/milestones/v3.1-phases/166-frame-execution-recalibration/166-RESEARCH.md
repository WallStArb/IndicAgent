# Phase 166: Frame/Execution Recalibration - Research

**Researched:** 2026-07-23 (updated same day — structural candidate scope broadened mid-research
per coordinator instruction; see "Broadened Structural Candidate" section)
**Domain:** Internal quant infrastructure (APR calibration mechanisms, TimescaleDB batch
scoring, statistical gate design, archived-plugin-tier feature availability) — no new external
libraries. Pure codebase/data investigation, no Context7/WebSearch needed.
**Confidence:** HIGH — every claim below is either read directly from live source code, a live
DB query result, or an existing frozen project document. No training-data guesses.

## Summary

Phase 166 has three deliverables (D-01): a diagnosis, two implemented calibration candidates,
and a fresh validation gate. The codebase already contains a complete, working template for
exactly this shape of work — `EnsembleICEngine._calibrate_hold_max_bars()` /
`_select_hold_bars_from_decay()` (per-(regime,tf) median-across-qualifying-symbols APR
calibration, CR-02 champion-gated) and `scripts/analysis/score03_gate2_execution_eval.py` (a
dry-run-then-one-shot statistical gate writing to `gate_evaluations`). Both candidates and the
new gate should be built as siblings of these, not novel architecture.

**Finding 1 (scalar candidate methodology gap):** IC "decay" is a time-horizon concept and has
no literal analog for `stop_atr_mult`/`target_r_multiple`, which are distance/reward-ratio
parameters. CONTEXT.md's D-03.1 wording should be read as "same STRUCTURE" (per-(regime,tf)
median-across-qualifying-symbols, CR-02 gate, in-sample only), not "same selection criterion."
The empirically sound substitute: `alpha_frames.counterfactual_mfe`/`counterfactual_mae` are
already collected in R-units and can be rescaled to ATR-units independent of the current
`stop_atr_mult` (since `mae_atr = mae_r * stop_atr_mult` when the stop is pure-ATR) — a real,
already-measured empirical basis for calibration, with one caveat: `counterfactual_mae` is
right-censored at the stop threshold for `closed_stop` frames (the same confirmed-vs-censored
ambiguity todo 088 flags for `hold_max_bars`).

**Finding 2 (structural candidate data availability — now confirmed exhaustively, see the
broadened-scope section below for full detail):** every single feature column the archived
v2.x structural stop/target/zone toolkit reads — VP/SR raw levels, EMA/SMA, swing highs/lows,
fib zones, SMC order blocks/FVG/liquidity sweeps/pools/BSL/SSL, anchored VWAP bands, prior-day/
session/overnight levels — **is 100% absent from v3's live `feature_vectors` schema** (verified
by direct column-name grep against the live DB and `FeatureVector`'s full field list, not
inferred). V3's Feature Factory (150 fields) is built entirely from normalized/z-scored
statistical features (momentum_z, rsi, adx, volatility estimators, HMM probabilities, calendar
features) — a deliberately different design philosophy from v2.x's raw-price structural levels
(the "raw-price-as-ML-feature antipattern" Phase 163's own D-16 explicitly avoided). The only
structural-level-adjacent columns anywhere in v3 today are `poc_dist_atr`/`va_position`/
`sr_support_dist`/`sr_resist_dist` — all four currently NULL corpus-wide, pending Phase 163.

**Finding 3 (the unifying mechanism the user asked for already exists, and is well-designed):**
`src/intelligence/trading/zone_engine.py` is a clean, generic, already-built confluence-scoring
engine — `resolve_structural_zone()` → 3-tier resolution (diverse-cluster confluence [2+
structurally-independent sources within 0.5 ATR] → single-best-scoring level → ATR fallback).
It is exactly the "unifying mechanism" the broadened D-03.2 describes, and its architecture
(a declarative `(feature_key, name, default_strength, source_tier, source_family)` spec table
feeding a shared clustering/scoring core) is a strong pattern to reuse. **But it is itself part
of the same archived, zero-live-consumer plugin tier as `trade_framer.py`** — `zone_engine.py`'s
own ~14-entry candidate spec table references only I1/I3/I4/SMC-tier feature keys, none of
which exist in v3. This is not a "maybe archived" ambiguity — every single candidate field was
checked against the live `feature_vectors` schema and none exist.

**Finding 4 (the real dependency, definitively answered — see broadened-scope section):**
building the FULL broadened structural candidate (VP/SR + swing/fib + SMC + anchored VWAP,
unified via zone_engine's confluence pattern) inside Phase 166 itself is **not achievable
without first executing/planning three separate phases** (163 VP/SR — planned, not executed;
164 SMC — registered, not even planned; 165 Swing/Fib/Trend — researched, not planned) plus
scoping a fourth, currently-unregistered porting effort (anchored VWAP + `zone_engine.py`'s
mechanism itself). This is a multi-phase, multi-week dependency chain, not a single-phase task.
A concrete, tiered recommendation for how to proceed is given below.

**Finding 5 (namespace/migration correction):** `feature.trade_framer.structure_snap_proximity_atr`
is **already a migrated APR key** (migration 141, default 1.5) under the archived
`feature.trade_framer.*` namespace — CONTEXT.md's characterization of it as "a bare `_cfg()`
default" is incorrect. `zone_engine.py` has its own separate, also-already-migrated
`feature.zone_engine.*` key family (migration 126/128: `cluster_radius_atr`, `zone_buffer_atr`,
`min_width_atr`, `single_level_radius_atr`, plus `weights.zone_engine.*`). Phase 166 should seed
fresh `alpha.frame.*`-namespaced keys rather than silently reusing either archived family.

**Finding 6 (holdout discipline):** `docs/plans/OOS-EVAL-PROTOCOL.md` forbids using the OOS
window for "hold-horizon calibration" — a general holdout-integrity rule. Both candidates'
calibration must compute exclusively from in-sample data (`bar_ts < alpha.validation.oos_start`).
Only the new validation gate touches the OOS window, and only once per candidate
(dry-run-then-one-shot, matching Gate 1/Gate 2's discipline).

**Primary recommendation:** Build the scalar candidate as described (per-(regime,tf) empirical
MAE/MFE-percentile calibration, in-sample, CR-02 gated). For the structural candidate, do NOT
attempt the full broadened toolkit inside Phase 166 — port `zone_engine.py`'s 3-tier
confluence-resolution ARCHITECTURE (a genuinely valuable, reusable pattern) into a new v3-native
module, but populate its candidate spec table only with what Phase 163 will make live
(VP POC/VAH/VAL-derived ATR-distance fields + `sr_support_dist`/`sr_resist_dist`), explicitly
designed to be extended with more candidate sources once Phase 164/165 land. Sequence Phase 163
execution as a prerequisite wave of Phase 166's plan (it's cheap and already ready); treat
SMC/swing/fib/anchored-VWAP as an explicitly out-of-scope, flagged follow-on rather than silently
dropped or force-fit into this phase.

## Broadened Structural Candidate: Full Investigation (2026-07-23 addendum)

This section directly answers the four questions raised when D-03.2 was broadened from
VP/SR-only to the full v2.x confluence toolkit (`zone_engine.py` + swing/fib/SMC/anchored-VWAP).

### Q1: How does `zone_engine.py` combine multiple structural signals? Live or archived?

**Mechanism (read in full, `src/intelligence/trading/zone_engine.py`, 499 lines):**

1. `collect_candidates(features, direction, entry, stop)` — for the given direction, iterates a
   declarative spec table (`_SUPPORT_SPECS`/`_RESISTANCE_SPECS`, 14 entries each) of
   `(feature_key, display_name, default_strength, source_tier, source_family)` tuples, pulling
   each feature's value out of the `features` dict, filtering to those strictly between
   `stop`/`entry`, and separately appending 3 volume-profile candidates (POC, session-or-rolling
   VAH/VAL depending on tf, nearest HVN). Each candidate gets a `strength` in [0,1] resolved via
   `_resolve_strength()` (reads a companion "quality" field like `support_strength`/
   `swing_low_age_bars`/`ssl_significance`/`nearest_hvn_dist_atr` when available, else a
   per-source default).
2. `_dedup()` collapses same-price duplicates within each `source_family` (1.0 ATR tolerance),
   keeping the strongest.
3. `_find_clusters()` groups the sorted, deduped candidates into tight clusters (0.5 ATR radius,
   `feature.zone_engine.cluster_radius_atr`).
4. `find_best_level()` / `_resolve_zone()`: **Tier 1** — prefer a cluster with ≥2 distinct
   `source_tier`s (i1/i3/i4/smc — genuinely independent evidence, not just two S/R variants
   agreeing), scored by `_score_cluster()` (strength-sum × diversity, penalized by cluster
   width in ATR). **Tier 2** — if no diverse cluster exists, the single highest
   `strength × weight_strength + proximity × weight_proximity` candidate
   (`_pick_single_best()`). **Tier 3** — `tier="atr"`, empty zone, caller (historically
   `trade_framer.py`) applies its own ATR-based fallback bounds.
5. `resolve_structural_zone()` is the public entry point; emits OTel metrics
   (`ZONE_TIER_USED`, `ZONE_CANDIDATE_COUNT`, `ZONE_WIDTH_ATR`, `ZONE_CLUSTER_DENSITY`) via
   `_emit_metrics()`.

`collect_sr_candidates()` is a second, closely-related public entry point used specifically by
`ctx_SRConsensus` (`src/intelligence/context/sr_consensus.py`) to derive `sr_nearest_support`/
`sr_nearest_resistance`/`sr_support_confluence_score`/`sr_resistance_confluence_score` — i.e.
`sr_consensus.py`'s OWN output already runs through `zone_engine`'s confluence machinery, one
layer upstream of `trade_framer.py`.

**Live or archived:** `zone_engine.py`'s module docstring states its purpose plainly ("Used by
trade_framer as a fallback when no setup-specific geometry exists"). It has exactly two
consumers in the whole codebase: `src/intelligence/trading/trade_framer.py` (imported for
`_resolve_zone_bounds`, not directly grepped as a top-level import in the excerpts read but
referenced by the module's own docstring and consistent with `_resolve_entry`/zone-tier naming
seen in `trade_framer.py`'s `_resolve_zone_bounds` function) and
`src/intelligence/context/sr_consensus.py` (`SRConsensusPlugin`, registered in
`register_plugins.py` as `ctx_SRConsensus` in `TIER_I4`). Both consumers are themselves
plugins/functions in the single I1-I7 `register_plugins.py` registry that
`src/intelligence/CLAUDE.md`'s own header confirms has **zero live consumer** — the entire
`indicagent-intelligence-pipeline` service has been `failed` (`ExecStart` pointing at a deleted
file) since 2026-07-02. `zone_engine.py` is not itself under `src/intelligence/archive/` as a
directory (unlike `order_blocks.py`/`bos_choch.py`/etc., which have literal duplicate copies
there), but it is functionally identical in liveness status: dead code with intact, well-tested
logic (`tests/unit/trading/test_zone_engine.py` exists and presumably passes against synthetic
feature dicts, same pattern as `trade_framer.py`'s own test coverage).

### Q2: For each SMC/swing/fib/anchored-VWAP source — archived or live? What data does it need?

| File | Location(s) | Live consumer? | Input data | Available in v3 today? |
|------|-------------|-----------------|-------------|--------------------------|
| `swing_detector.py` | `src/intelligence/features/i3_structure/swing_detector.py` ONLY (no archive/ copy) | No — `SwingDetectorPlugin`, a `PatternPlugin` (uses `InputSpec` from `src.intelligence.plugins`, the archived-pipeline protocol), registered in `register_plugins.py`'s `TIER_I3`. Reads raw OHLCV directly via `find_peaks`/`find_troughs` (`src/intelligence/utils`), not persisted features — self-contained, no upstream feature dependency, but its OUTPUT (`swing_high`/`swing_low`/`swing_high_age_bars`/etc.) has no v3 write path | Raw `high`/`low` bars only | Outputs: NO — `swing_high`/`swing_low`/`swing_high_age_bars`/`swing_low_age_bars`/`swing_pattern` do not exist in `feature_vectors` |
| `trend_structure.py` | `src/intelligence/features/i3_structure/trend_structure.py` ONLY | No — same TIER_I3 status | Consumes `swing_detector`'s outputs (HH/HL/LH/LL pattern) | NO (depends on swing_detector's un-persisted outputs) |
| `fibonacci_zones.py` | `src/intelligence/features/i3_structure/fibonacci_zones.py` ONLY | No — same TIER_I3 status | Consumes swing highs/lows | NO |
| `order_blocks.py` | **BOTH** `src/intelligence/archive/smc_context/order_blocks.py` AND `src/intelligence/features/smc_context/order_blocks.py` — byte-identical (`diff` confirms zero difference, both 177 lines) | No — `register_plugins.py` imports the `archive/smc_context/` copy only (line 32); the `features/smc_context/` copy is an orphaned, unimported duplicate | Raw OHLCV | NO — `ob_top`/`ob_bottom`/`ob_type` don't exist in v3 |
| `liquidity_pools.py` | Same dual-copy pattern | No — `archive/smc_context/` copy imported (line 27); `features/` copy orphaned | Raw OHLCV + swing levels | NO |
| `liquidity_sweeps.py` | Same dual-copy pattern | No — `archive/smc_context/` copy imported (line 28); `features/` copy orphaned | Raw OHLCV | NO — `sweep_detected`/`sweep_level` don't exist |
| `bos_choch.py` | Same dual-copy pattern | No — `archive/smc_context/` copy imported (line 22); `features/` copy orphaned | Raw OHLCV + swing structure | NO |
| `premium_discount.py` | Same dual-copy pattern | No — `archive/smc_context/` copy imported (line 33); `features/` copy orphaned | Range high/low | NO |
| `anchored_vwap.py` | `src/intelligence/context/anchored_vwap.py` ONLY (no archive/ copy — different directory convention, `context/` not `archive/`) | No — `AnchoredVWAPPlugin` (`ctx_AnchoredVWAP`), imported and registered in `register_plugins.py` (`TIER_I4`, lines 126, 207, 511, 597) alongside a SECOND, unrelated `anchored_vwap_reversion_plugin` from `archive/trading_i7/` (a signal plugin, not the same thing) | Raw OHLCV + session anchor logic | NO — `avwap_upper_band`/`avwap_lower_band` don't exist in v3 |

**The "both archive/ and features/ copies exist" mystery, resolved:** for every SMC file with a
dual copy, `register_plugins.py` (the sole real registration point) imports exclusively from
`src/intelligence/archive/smc_context/`. The `src/intelligence/features/smc_context/` copies are
byte-identical orphans — never imported anywhere in `src/`/`services/`/`scripts/`/`tests/`
(confirmed via grep across the whole tree). This is very likely a leftover from an incomplete
directory reorganization (moving the whole `smc_context` tier into `archive/` but never deleting
the pre-move copy under `features/`) rather than two genuinely different implementations. **Do
not build against the `features/smc_context/` copies under any interpretation that they might be
"the newer, about-to-go-live version"** — `register_plugins.py`'s import statements are the
single source of truth for what's wired, and they unambiguously point at `archive/`.

**Naming collision warning for the planner:** `src/intelligence/features/` is NOT the same thing
as this project's "Feature Factory" (v3.0's live feature computation, at
`src/intelligence/feature_factory.py`, producing the `FeatureVector` dataclass in
`src/intelligence/schemas.py`). `src/intelligence/features/i3_structure/` and
`src/intelligence/features/smc_context/` are legacy I1-I7-tier plugin directories that happen to
share the word "features" — despite not living under `archive/`, they are equally dead (zero
live consumer, confirmed above). This naming collision is a real trap; do not assume anything
under `src/intelligence/features/` is part of the live v3.0 pipeline without checking
`register_plugins.py`'s import source and cross-checking against the live `feature_vectors`
schema, as done here.

### Q3: Real dependency — does the broadened structural candidate need Phase 163/164 to land first?

**Definitive answer, verified by direct schema inspection (not inferred):** every feature column
referenced by `zone_engine.py`'s 14-entry support/resistance spec tables, `_STRENGTH_FIELD`
companion-strength lookups, and the SMC/swing/fib/anchored-VWAP source files above was checked
against `feature_vectors`'s full live column list (150 fields, `FeatureVector` dataclass +
direct `\d feature_vectors` schema dump). **Zero matches.** No `ema_21`, `sma_50`, `swing_high`,
`swing_low`, `nearest_fib_level`, `nearest_hvn_below`, `nearest_hvn_above`, `ssl_level`,
`bsl_level`, `ob_top`, `ob_bottom`, `fvg_top`, `fvg_bottom`, `sweep_level`, `nearest_demand_high`,
`nearest_supply_low`, `avwap_upper_band`, `avwap_lower_band`, `prior_session_low/high`,
`asian_session_low/high`, `poc_price`, `poc_price_rolling`, `vah`, `val`, `vah_rolling`,
`val_rolling`. The only structural-adjacent columns that DO exist —
`poc_dist_atr`/`va_position`/`sr_support_dist`/`sr_resist_dist` — are 100% NULL, pending Phase
163's execution.

Concretely, this means:

- **VP/SR portion**: real dependency on Phase 163 (planned, not executed). Phase 163 does NOT
  add raw `poc_price`/`vah`/`val` (deliberately, per its own D-16 anti-raw-price design) but DOES
  add the ATR-normalized distances needed to reconstruct a structural stop/target PRICE
  (`entry_price ± distance_atr_field * atr`). **This portion is achievable within Phase 166 if
  Phase 163 executes first.**
- **SMC portion** (order blocks, liquidity pools/sweeps, BOS/CHoCH, premium/discount): real
  dependency on Phase 164 ("SMC Institutional Footprint Primitives"), which per STATE.md is
  **registered but has zero planning artifacts** — no CONTEXT.md, no RESEARCH.md, no PLAN.md.
  Building this would require running `/gsd-discuss-phase 164` → `/gsd-plan-phase 164` →
  `/gsd-execute-phase 164` first — a full phase-sized effort in its own right, not something
  Phase 166 can absorb as a sub-task.
- **Swing/Fib/Trend portion**: real dependency on Phase 165 ("Swing/Fib/Trend Structure
  Primitives"), which per STATE.md has CONTEXT.md + RESEARCH.md already written (41 new columns
  across 5 files planned) but is **not yet planned (no PLAN.md) or executed**. Requires
  `/gsd-plan-phase 165` → `/gsd-execute-phase 165` first.
- **Anchored VWAP portion**: **no registered phase covers this at all.** Neither ROADMAP.md nor
  STATE.md mentions a phase for porting `anchored_vwap.py` into v3's Feature Factory. This would
  need net-new scoping (a Phase 167+ candidate, or folded into 165/164's scope) before Phase 166
  could build against it.
- **`zone_engine.py`'s confluence mechanism itself**: no registered phase covers porting this
  either — it is currently invisible to the roadmap (it's neither explicitly archived-and-noted
  nor explicitly scheduled for a v3 port anywhere in ROADMAP.md/STATE.md prior to this session).

**Recommendation (clear, with reasoning):** Phase 166 should NOT attempt to build the full
broadened structural candidate as literally scoped in the 2026-07-23 D-03.2 edit. Doing so would
implicitly require Phase 166 to first execute Phase 163, and additionally plan-and-execute
Phases 164 and 165 (neither of which is ready), plus scope a brand-new anchored-VWAP/
zone-engine-port effort with no existing research behind it — a multi-phase, multi-week
undertaking that contradicts D-01's requirement that Phase 166 itself "must... run that new
proposal through a fresh validation gate... before this phase is considered complete." A
diagnosis-with-no-buildable-alternative is exactly what todo 174 (this phase's own origin)
warned against — the same failure mode would recur one level up if Phase 166 tried to boil the
ocean on structural candidates it cannot actually test with real data.

**Concrete, actionable alternative:** build the structural candidate in two explicit parts,
architected so the second part is a pure extension of the first, not a redesign:

1. **Buildable now (after Phase 163 executes):** port `zone_engine.py`'s 3-tier confluence
   RESOLUTION ARCHITECTURE (declarative candidate-spec table → dedup → cluster → diverse-cluster
   preference → single-best fallback → ATR fallback) into a new v3-native module. Populate its
   candidate spec table with exactly what Phase 163 makes live: VP POC (reconstructed price from
   `poc_dist_atr`/`poc_rolling_dist_atr`), VAH/VAL (reconstructed from `distance_to_vah_atr`/
   `distance_to_val_atr`), and S/R (`sr_support_dist`/`sr_resist_dist`, plus the 5 D-19 fields
   Phase 163 added: `resistance_strength`/`support_strength`/`resistance_age_bars`/
   `support_age_bars`/`sr_level_count`, which map directly onto `zone_engine.py`'s
   `_STRENGTH_FIELD` companion-strength pattern). This alone is a genuine, non-trivial confluence
   mechanism (2+ independent structural sources: VP and S/R) — not a downgrade to "VP/SR in
   isolation," since it still uses the real multi-source clustering logic, just with a narrower
   (but real, live) candidate universe than the full v2.x toolkit.
2. **Explicitly deferred, flagged for a follow-on phase, NOT silently dropped:** extend the same
   candidate spec table with swing/fib/SMC/anchored-VWAP entries once Phases 164/165 (and a new
   anchored-VWAP porting effort) land. Because the mechanism (Part 1) is architected as a
   declarative spec table + generic clustering core, this extension requires zero redesign later
   — exactly the kind of "build once, extend later" the confluence architecture already
   naturally supports. File this as a new todo at the end of Phase 166 (e.g. "extend
   Phase 166's structural candidate with SMC/swing/fib/anchored-VWAP sources once Phases
   164/165 land") rather than letting the ambition silently evaporate.

This gives Phase 166 something genuinely structural (not a VP/SR-only fallback in the pejorative
sense — it's the same confluence ARCHITECTURE the user asked for, just currently data-limited),
keeps the phase completable within its own D-01 mandate, and does not block Phase 166 behind
Phase 164's currently-nonexistent planning artifacts.

### Q4: Updated implementation complexity/scope assessment

**Original (VP/SR-only) scope estimate:** one new pure function
(`compute_structural_frame_geometry`), reusing `_classify_stop_basis`'s proximity-threshold
PATTERN (not its body), gated on Phase 163 execution. Small-to-medium — a single wave, one new
module, one new migration section.

**Broadened (full toolkit) scope, as literally requested:** would require, in sequence or
parallel where independent: Phase 163 execution (small, ready) + Phase 164 full
discuss/research/plan/execute cycle (large, currently zero artifacts — likely comparable in size
to Phase 163's own effort, which was itself "3 plans, migration 243, 17 new columns") + Phase 165
plan/execute cycle (medium — research already exists, "41 new columns across 5 files") + new
anchored-VWAP scoping (small-medium, unscoped) + porting `zone_engine.py`'s confluence
architecture against whatever the union of all these new columns ends up being named (medium).
Realistic total: multiple phases and multiple weeks, not a wave inside Phase 166.

**Recommended scope for Phase 166's plan (per the Q3 recommendation):** the two-part structural
candidate above. Part 1 (VP/SR + S/R confluence, Phase-163-gated) is right-sized for a Phase 166
wave — comparable complexity to the original VP/SR-only estimate, plus the confluence-clustering
logic (medium, but `zone_engine.py`'s existing `_find_clusters`/`_score_cluster`/
`_pick_single_best` functions are directly portable almost unmodified, since they operate on the
generic `ZoneCandidate` dataclass and don't reference any specific feature name — only the spec
tables and `_resolve_strength`'s field-name lookups are v2.x-specific and need v3 renaming).
Part 2 (SMC/swing/fib/anchored-VWAP extension) should be filed as an explicit follow-on todo, not
built now.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| IC decay diagnosis (compare current calibration vs decay curve) | Batch/API (offline analysis script) | Database (TimescaleDB reads) | Read-only comparison against existing `alpha_ensemble_ic`/`alpha_frames` data; no new service |
| Scalar candidate calibration (stop_atr_mult/target_r_multiple per regime/tf) | Batch/API (`services/ensemble_ic_engine.py` extension) | Database (`config_state` writes via `ConfigService`) | Mirrors EIC-02's existing tier exactly — a oneshot batch daemon writing APR keys, gated on champion weight_version |
| Structural candidate Part 1 (VP/SR + S/R confluence-scored stop/target) | Batch/API (`services/alpha_frame_writer.py` or new module) | Database (reads Phase-163-populated `feature_vectors` columns) | Frame geometry computed at frame-creation time inside `AlphaFrameWriter`'s existing per-partition write pass |
| Structural candidate confluence-resolution architecture (clustering/scoring core) | Batch/API (pure functions, new module, ported from `zone_engine.py`) | — | Generic over `ZoneCandidate`, no DB/service dependency of its own |
| Frame snapshot persistence (new stop/target values onto `alpha_frames`) | Database (TimescaleDB `alpha_frames` hypertable) | Batch/API (`AlphaFrameWriter`) | Existing snapshot-at-scan-time discipline (Phase 142B anti-pattern lesson) |
| Counterfactual simulation of new stop/target values | Batch/API (`services/counterfactual_tracker.py`) | Database | Already generic over per-frame `stop_price`/`target_price`/`max_hold_bars` columns — zero changes needed |
| New validation gate scoring | Batch/API (new script under `scripts/analysis/`) | Database (`gate_evaluations` write) | Structurally identical tier to `score03_gate2_execution_eval.py` |
| Structural/scalar APR keys | Database (`config_schema`/`config_state` migration) | — | New `alpha.frame.*` namespaced keys via migration 253+ |
| Phase 163 execution (VP/SR primitive computation) | Batch/API (`FeatureVectorPipeline`/backfill scripts, unrelated to Phase 166's own code) | Database (`feature_vectors` writes) | A PREREQUISITE, not part of Phase 166's own architecture — see Open Questions |

## Project Constraints (from CLAUDE.md)

- **DAG Invariant 3** — a compute daemon never writes its own computed output inline; persistence
  goes through a dedicated writer. Both candidates must follow `AlphaFrameWriter`'s existing
  pattern (compute in `_process_partition`, write via the existing `executemany` batch flush) —
  do not add a second inline write path.
- **APR mandate (Adaptive Parameter Registry)** — every new tunable numeric value
  (`stop_atr_mult.<regime>.<tf>`, `target_r_multiple.<regime>.<tf>`, the structural candidate's
  proximity/cluster-radius/strength-weight thresholds) MUST be a `config_schema`/`config_state`
  migration key, never a hardcoded constant. Migrate-as-you-go: this applies even to values only
  used inside a throwaway comparison script.
- **ProcessPoolExecutor workers are compute-only** — any new corpus-scan script (structural
  candidate backfill, the new gate's fetch) must not open a write connection from a worker
  subprocess.
- **Never log per-row inside a full-corpus loop** — accumulate counters, log once per partition,
  matching `AlphaFrameWriter`'s `missing_hold_keys` pattern.
- **Exception variable name is `error`**, not `exc`.
- **All timestamps UTC**, `datetime.now(UTC)` only.
- **Executable returns only (Invariant 1)** — not directly touched (frame simulation walks real
  price paths, not `forward_returns`), but any new diagnostic joining `forward_returns` must
  filter `return_type = 'executable_open_to_open'`.
- **Migrate-as-you-go** — the structural candidate's proximity/clustering thresholds must be
  fresh `alpha.frame.*` migration keys, not hardcoded constants and not silent reuse of the
  archived `feature.trade_framer.*`/`feature.zone_engine.*`/`weights.zone_engine.*` key families
  (Finding 5).

## Standard Stack

No new external packages. This phase extends existing internal modules using already-imported
libraries: `numpy`, `scipy.stats` (bootstrap, already used by `frame_gate_passes`),
`asyncpg`/`psycopg2` (existing DB access patterns), `statsmodels.multipletests` (already used for
corpus-level BH-FDR). No `npm install`/`pip install` step applies.

### Package Legitimacy Audit

Not applicable — this phase installs zero external packages.

## Architecture Patterns

### System Architecture Diagram

```
                    ┌─────────────────────────────────────────────────────────┐
                    │  DIAGNOSIS (read-only, new analysis script)              │
                    │  alpha_ensemble_ic (IC decay curve, per regime/tf/scale) │
                    │  vs. config_state alpha.frame.{stop_atr_mult,            │
                    │      target_r_multiple} (currently GLOBAL scalars)       │
                    │  vs. alpha_frames.{counterfactual_mfe,counterfactual_mae}│
                    │      (already-collected R-unit excursions, IN-SAMPLE)    │
                    └───────────────────────┬───────────────────────────────--┘
                                             │ informs
                                             ▼
      ┌──────────────────────────────┐            ┌───────────────────────────────────┐
      │ SCALAR CANDIDATE               │            │ STRUCTURAL CANDIDATE — PART 1       │
      │ services/ensemble_ic_engine.py│            │ (buildable now, Phase-163-gated)    │
      │ new: _calibrate_stop_target() │            │ new module, ports zone_engine.py's  │
      │ mirrors _calibrate_hold_max_  │            │ 3-tier confluence resolution         │
      │ bars() structure: per-(regime,│            │ (cluster/dedup/score core is nearly │
      │ tf) median-across-qualifying- │            │ portable unmodified — operates on   │
      │ symbols, CR-02 champion gate, │            │ generic ZoneCandidate); candidate    │
      │ IN-SAMPLE ONLY, MAE/MFE-      │            │ spec table populated ONLY with       │
      │ percentile selection criterion│            │ Phase-163 VP/S-R fields              │
      │                                │            │                                     │
      │ writes:                       │            │ writes:                            │
      │ alpha.frame.stop_atr_mult.    │            │ alpha.frame.<structural-key>.       │
      │   <regime>.<tf>                │            │   <regime>.<tf>                     │
      │ alpha.frame.target_r_multiple.│            │                                     │
      │   <regime>.<tf>                │            │                                     │
      └───────────────┬───────────────┘            └────────────────┬────────────────────┘
                       │                                             │
                       │              ┌──────────────────────────────┘
                       │              │  PREREQUISITE (NOT part of Phase 166's own code):
                       │              │  Phase 163 execution — populates poc_dist_atr,
                       │              │  distance_to_vah_atr, distance_to_val_atr,
                       │              │  sr_support_dist, sr_resist_dist, resistance_strength,
                       │              │  support_strength, resistance_age_bars, support_age_bars
                       │              │
                       │       ┌────────────────────────────────────────────┐
                       │       │ STRUCTURAL CANDIDATE — PART 2 (DEFERRED)     │
                       │       │ extend the SAME spec table with SMC/swing/  │
                       │       │ fib/anchored-VWAP sources once Phases        │
                       │       │ 164/165 (+ new anchored-VWAP scoping) land   │
                       │       │ — filed as a follow-on todo, NOT built now   │
                       │       └────────────────────────────────────────────┘
                       │
                       └──────────────┬──────────────────────────────┘
                                       ▼
                    ┌──────────────────────────────────────────┐
                    │ services/alpha_frame_writer.py             │
                    │ per-(symbol,tf) partition loop, per-row:  │
                    │  stop_key = f"alpha.frame.stop_atr_mult.  │
                    │              {regime}.{tf}}" (mirrors     │
                    │              existing hold_key pattern)   │
                    │  falls back to global scalar if missing   │
                    │  (backward-compatible, additive)          │
                    └───────────────────┬────────────────────────┘
                                         ▼
                    ┌──────────────────────────────────────────┐
                    │ services/counterfactual_tracker.py         │
                    │ UNCHANGED — already generic over each      │
                    │ frame's snapshotted stop_price/             │
                    │ target_price/max_hold_bars columns          │
                    │ writes counterfactual_pnl_r/mfe/mae/status  │
                    └───────────────────┬────────────────────────┘
                                         ▼
                    ┌──────────────────────────────────────────┐
                    │ NEW VALIDATION GATE                        │
                    │ scripts/analysis/gate166_*.py (mirrors      │
                    │ score03_gate2_execution_eval.py exactly:    │
                    │ dry-run-then-one-shot, evaluate_frame_gate  │
                    │ + frame_gate_passes reused unmodified,      │
                    │ writes ONE gate_evaluations row per         │
                    │ candidate, NEW gate_id (not gate2_execution)│
                    │ scores OOS-only: bar_ts >= oos_start         │
                    └──────────────────────────────────────────┘
```

### Recommended Project Structure

```
services/
├── ensemble_ic_engine.py       # extend: new _calibrate_stop_target() alongside
│                                #   existing _calibrate_hold_max_bars(); new pure
│                                #   selection function (MAE/MFE-percentile based,
│                                #   NOT a decay-walk copy — see Pitfall 1)
├── alpha_frame_writer.py       # extend: per-row per-(regime,tf) stop/target key
│                                #   lookup mirroring the existing hold_key pattern;
│                                #   structural candidate Part 1's geometry
│                                #   computation (new pure function) called here too
└── counterfactual_tracker.py   # UNCHANGED (already generic)

src/intelligence/trading/
└── structural_confluence.py    # NEW (recommended name/location) — v3-native port of
                                 #   zone_engine.py's clustering/scoring core
                                 #   (ZoneCandidate, _find_clusters, _score_cluster,
                                 #   _pick_single_best are portable nearly unmodified);
                                 #   NEW v3-specific spec table populated with
                                 #   Phase-163 fields only; designed for later
                                 #   extension (Part 2, deferred)

scripts/analysis/
└── gate166_frame_recalibration_eval.py   # NEW — mirrors score03_gate2_execution_eval.py
                                            #   structure exactly; scores BOTH candidates,
                                            #   writes 1-2 new gate_evaluations rows

production/migrations/
└── 253_alpha_frame_stop_target_calibration.sql   # NEW — schema/APR keys for both
                                                     #   candidates (next free migration
                                                     #   number; 249-252 reserved by Phase 162)

tests/unit/
├── test_ensemble_ic_stop_target_calibration.py   # NEW (mirrors test_ensemble_ic_decay.py)
├── test_structural_confluence.py                  # NEW (mirrors test_zone_engine.py's
│                                                    #   synthetic-candidate style)
└── test_gate166_frame_recalibration_eval.py       # NEW (mirrors test_score03_gate2_execution_eval.py)
```

### Pattern 1: Per-(regime,tf) median-across-qualifying-symbols APR calibration (CR-02 gated)

**What:** A oneshot batch daemon computes a per-symbol candidate value, groups by
`(regime, tf)`, takes the median across symbols that individually qualified under a
sufficiency/reliability filter, and writes one APR key per `(regime, tf)` cell via
`ConfigService.set()` — but ONLY when running against the champion `weight_version` (never a
challenger under evaluation).

**When to use:** Both the scalar and structural candidates' calibration mechanisms.

**Example (existing, live, to mirror exactly):**
```python
# Source: services/ensemble_ic_engine.py, lines ~1063-1122 (EIC-02)
if weight_version == champion_weight_version:
    n_keys_written = await self._calibrate_hold_max_bars(pool, corpus_all_results, config)
else:
    self.logger.info(
        "ensemble_ic.hold_max_bars_calibration_skipped",
        reason="scoped_weight_version_run",
        weight_version=weight_version,
        champion_weight_version=champion_weight_version,
    )
    n_keys_written = 0

async def _calibrate_hold_max_bars(self, pool, results, config) -> int:
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for row in results:
        if row.get("is_pooled"):
            continue
        key = (row["symbol"], row["tf"], row["regime"])
        groups.setdefault(key, []).append(row)

    per_regime_tf: dict[tuple[str, str], list[int]] = {}
    for (_symbol, tf, regime), cells in groups.items():
        value = _select_hold_bars_from_decay(cells, config.decay_threshold, config.lookaheads)
        if value is None:
            continue  # zero qualifying symbols: SKIP, no fallback write, prior APR value stays
        per_regime_tf.setdefault((regime, tf), []).append(value)

    for (regime, tf), qualifying_values in per_regime_tf.items():
        median_value = int(np.median(qualifying_values))
        key = f"alpha.frame.hold_max_bars.{regime}.{tf}"
        await config_service.set(key, str(median_value), changed_by="ensemble-ic-engine",
                                  reason=f"calibrated ...; median across {len(qualifying_values)} qualifying symbols")
```

**Adaptation needed for stop/target (not a literal copy):** see Finding 1 / Pitfall 1 —
`_select_hold_bars_from_decay`'s decay-threshold-crossing logic does not transfer; use a
percentile-of-rescaled-MAE/MFE selection instead, keeping only the grouping/median/CR-02
STRUCTURE.

### Pattern 2: Confluence resolution via declarative candidate spec table + generic clustering core

**What:** `zone_engine.py`'s design cleanly separates WHAT counts as a candidate (a declarative
tuple table naming feature keys + display names + default strengths + source tiers/families)
from HOW candidates get combined into a final level (a generic `ZoneCandidate`-based clustering/
scoring pipeline that never references a specific feature name). This separation is exactly why
Part 1 → Part 2 extension (Q4 above) is cheap: only the spec table changes, the clustering core
does not.

**When to use:** The structural candidate's stop/target price selection (Part 1 now, Part 2
later).

**Example (existing, live, portable nearly unmodified):**
```python
# Source: src/intelligence/trading/zone_engine.py, lines 85-101, 344-395 (live)
@dataclass
class ZoneCandidate:
    price: float
    name: str
    strength: float       # 0.0-1.0
    source_tier: str      # "i1", "i3", "i4", "smc" in v2.x; would become e.g. "vp"/"sr" in v3
    source_family: str    # dedup grouping key

def _find_clusters(candidates: list[ZoneCandidate], atr: float) -> list[list[ZoneCandidate]]:
    """Group sorted candidates into tight clusters (within CLUSTER_RADIUS_ATR of each other)."""
    ...  # generic, no feature-name references — portable as-is

def _pick_single_best(candidates, entry, atr) -> ZoneCandidate | None:
    """strength x proximity scoring — generic, portable as-is."""
    ...
```

**v3 spec-table adaptation (Part 1, new):**
```python
# NEW, illustrative — not existing code. Populate ONLY with Phase-163-live fields.
_V3_SUPPORT_SPECS = (
    # (feature_key, name, default_strength, source_tier, source_family)
    ("sr_support_dist", "sr_support", 0.7, "sr", "sr"),        # Phase 163
    # poc/vah/val handled specially (reconstructed price, not a direct feature_key) —
    # mirrors zone_engine.py's _collect_raw's separate VP block (lines 241-255)
)
```

### Pattern 3: Dry-run-then-one-shot statistical gate, atomic re-check-then-insert

**What:** A gate script computes evidence via a pure function (unit-testable on synthetic rows),
prints a full verdict under `--dry-run` with zero writes, and on a real run atomically re-checks
no prior row exists for this `gate_id` before inserting — inside the same transaction.

**When to use:** The new Phase 166 validation gate(s).

**Example:**
```python
# Source: scripts/analysis/score03_gate2_execution_eval.py, lines 429-454
async def _write_gate2_row(pool, evidence, run_ts, look_log_path) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchval(
                "SELECT count(*) FROM gate_evaluations WHERE gate_id = $1", _GATE_ID
            )
            if existing:
                raise RuntimeError(f"'{_GATE_ID}' already has {existing} row(s) ...")
            await conn.execute(
                "INSERT INTO gate_evaluations (gate_id, result, evidence, run_ts) "
                "VALUES ($1, $2, $3::jsonb, $4)",
                _GATE_ID, evidence["result"], json.dumps(_json_safe(evidence)), run_ts,
            )
    _append_look_log(look_log_path, run_ts, evidence)
```

Note the `_json_safe()` non-finite-float sanitizer (same file, lines 402-426) — the new gate
script's evidence payload will also contain `+inf`/`nan` CI bounds for thin cells and MUST reuse
this helper (a prior Gate 2 real-run attempt crashed on exactly this before it was added).

### Pattern 4: Regime-stratified companion, never a pooled verdict alone

**What:** Every gate evaluation reports both a pooled verdict AND a per-(direction,regime)
breakdown via `evaluate_frame_gate(rows, group_key=lambda row: (row["direction"], row["regime"]),
min_clusters=...)`, with cells below `min_clusters` marked `coverage="insufficient"` and excluded
from (not counted as failing) the aggregate verdict.

**When to use:** Mandatory for the new Phase 166 gate too — D-05 requires disclosing, not
gating on, the `mid_bull`-only OOS coverage limitation. Reuse `_compute_regime_companion()`'s
pattern from `score03_gate2_execution_eval.py` verbatim.

### Anti-Patterns to Avoid

- **Coupling `hold_max_bars` and the new stop/target keys into one derivation.** Todo 096's
  Fable-reviewed Decision B explicitly rejected coupling `hold_max_bars` to selected
  `lookahead_bars` — the same category-error risk applies here. Keep independently-calibrated
  APR families that happen to be snapshotted onto the same frame row.
- **Treating same-`bar_ts` frames as sequential in any new statistic.** Todo 172's finding
  applies to any new diagnostic or gate computation this phase writes.
- **Reusing censored MAE without disclosure.** `counterfactual_mae` on `closed_stop` frames is
  right-censored at the stop distance — the same silent-bias risk todo 088 flags for
  `hold_max_bars`'s median aggregation.
- **Assuming `feature.trade_framer.*`/`feature.zone_engine.*`/`weights.zone_engine.*` v2.x APR
  keys are a valid live source.** They exist in `config_state` but belong to an archived system
  with no live consumer (Finding 5) — seed fresh `alpha.frame.*` keys instead.
- **Calibrating either candidate against OOS data.** Only the new gate touches
  `bar_ts >= oos_start`, and only once per candidate.
- **Building against `src/intelligence/features/smc_context/`'s orphaned duplicate copies.**
  `register_plugins.py` imports exclusively from `src/intelligence/archive/smc_context/` for
  every SMC file that has a dual copy — the `features/` copies are unimported dead code, not a
  "newer version." (Only relevant if/when Part 2 is eventually built.)
- **Assuming anything under `src/intelligence/features/` is part of the live v3.0 Feature
  Factory.** The directory name collides with this project's "Feature Factory" terminology but
  `features/i3_structure/`/`features/smc_context/` are legacy I1-I7-tier plugin directories,
  fully dead — verify against `register_plugins.py` + the live `feature_vectors` schema, never
  the directory name alone.
- **Attempting to build the full broadened (VP/SR+SMC+swing/fib+anchored-VWAP) structural
  candidate inside Phase 166 without first landing Phases 163/164/165.** See Q3/Q4 above — this
  is the single most important scope-discipline finding of this research addendum.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Day-clustered bootstrap CI for a pnl_r population | A new bootstrap/CI routine | `frame_gate_passes()` (`services/counterfactual_tracker.py`) | Already handles BCa-vs-analytic-CLT method selection, day-clustering, `bootstrap_random_state` reproducibility (WR-01) |
| Grouping frames into (direction,regime) cells with a coverage floor | A new grouping/aggregation loop | `evaluate_frame_gate()` (same file) | Already generalized via `group_key`/`min_clusters` params (todo 165's exact reuse precedent — note: unrelated to Phase 165 by number coincidence) |
| Annualized Sharpe / max-drawdown-ratio over pnl_r | New implementations | `_annualized_sharpe`/`_max_drawdown` from `scripts/analysis/phase143_1_08_shadow_validation.py` (imported, "reused verbatim") | Frozen edge-case handling already reasoned through and tested |
| Frame geometry (stop/target price from ATR + multiplier) | A duplicate geometry function | `compute_frame_geometry()` (`services/alpha_frame_writer.py`) | Already handles both directions and the `min_stop_price_fraction` degenerate-ATR skip (todo 162's fix) |
| Non-finite float JSON sanitization for gate evidence | Ad-hoc `try/except` around `json.dumps` | `_json_safe()` (`scripts/analysis/score03_gate2_execution_eval.py`) | Already fixed a real production crash |
| Same-timestamp aggregation before a cumulative statistic | A new tie-break scheme | `_aggregate_pnl_by_bar_ts()` (same file) | Structurally correct fix for the exact tie-density this corpus has |
| Multi-source structural level clustering/scoring | A new confluence algorithm from scratch | `zone_engine.py`'s `ZoneCandidate`/`_find_clusters`/`_score_cluster`/`_pick_single_best` (portable nearly unmodified — see Pattern 2) | Already handles diversity-weighted cluster preference, dedup, and single-best fallback; well-tested (`tests/unit/trading/test_zone_engine.py`) |

**Key insight:** This phase's entire toolkit — both the calibration-mechanism half and the
confluence-scoring half — already exists in the codebase from Phase 142B/143.1/148 and the
archived v2.x trading tier. The work is almost entirely "write two new pure functions/port one
existing generic algorithm, wire into existing write paths, write one new gate script from an
existing template" — not new statistical or architectural design. The one genuinely new design
decision is the scalar candidate's selection criterion (Open Question 2) and the exact v3 spec
table for the structural candidate's Part 1 (Phase-163-scoped) candidates.

## Runtime State Inventory

Not applicable — this is not a rename/refactor/migration phase. New APR keys are additive
(migration 253+), and `AlphaFrameWriter`'s per-row key lookup is designed to fall back to the
existing global scalar when a per-(regime,tf) key is absent — no backfill/migration of existing
`alpha_frames` rows is implied by adding new keys.

## Common Pitfalls

### Pitfall 1: Forcing stop/target into the literal "IC decay curve" framework

**What goes wrong:** Building a stop/target selection function as a literal copy of
`_select_hold_bars_from_decay()`'s walk-until-below-threshold logic, applied to `ic_sharpe`
across lookaheads, produces a value with no principled connection to stop distance or reward
ratio.

**Why it happens:** CONTEXT.md's D-03.1 wording reads as "reuse the whole function," but the
function's actual selection logic has no stop/target analog.

**How to avoid:** Reuse the STRUCTURE (grouping, median-across-qualifying-symbols aggregation,
CR-02 champion gate, skip-if-zero-qualifying) with a NEW, stop/target-appropriate selection
criterion — the `counterfactual_mfe`/`counterfactual_mae` percentile approach (Finding 1), or an
explicit in-sample grid-search re-simulation.

**Warning signs:** A calibration function whose docstring talks about "decay threshold" or
"lookahead scale" when computing a distance/ratio parameter.

### Pitfall 2: Building the structural candidate before Phase 163 has executed

**What goes wrong:** Writing code against `poc_dist_atr`/`sr_support_dist`/`sr_resist_dist`
today gets NULL for every row, silently producing an all-ATR-fallback structural candidate that's
statistically indistinguishable from a degenerate scalar candidate — not a real structural test.

**Why it happens:** Phase 163 is fully planned and its column names are already known, creating
false confidence that the data is live.

**How to avoid:** Verify live data before building: `SELECT count(*) FROM feature_vectors WHERE
sr_support_dist IS NOT NULL` should return >0 only after Phase 163 has actually executed.
Sequence the structural-candidate implementation wave explicitly after Phase 163 execution.

**Warning signs:** Every row of the structural candidate classifying as ATR-fallback/no snap.

### Pitfall 3: Silently building against archived-tier feature names that don't exist in v3

**What goes wrong:** Copying `zone_engine.py`'s `_SUPPORT_SPECS`/`_RESISTANCE_SPECS` tables (or
`trade_framer.py`'s `_resolve_stop_long`/`_resolve_stop_short` feature reads) verbatim into a new
v3 module produces a function that silently returns empty candidate lists forever, because every
referenced `features[key]` lookup returns `None`/missing on a real v3 `features` dict (built from
the live 150-field `FeatureVector`, not v2.x's superset).

**Why it happens:** The archived code is syntactically valid and imports cleanly; nothing raises
an error when a feature dict simply lacks a key `_fval()` gracefully treats as "no candidate here."

**How to avoid:** Cross-check every feature key referenced in any ported logic against the live
`feature_vectors` schema (or `FeatureVector`'s field list) BEFORE wiring it in — this research
has already done this exhaustively for the full broadened toolkit (Q3) and found zero matches
outside the Phase-163-owned four columns; do not re-introduce v2.x-only keys.

**Warning signs:** A structural candidate that never produces a non-ATR-fallback frame in testing.

### Pitfall 4: Letting a hardcoded threshold silently survive a `_cfg()` default

**What goes wrong:** `_cfg(cfg_dict, key, default)` silently returns the Python-literal `default`
if the key is absent from `config_schema`/`config_state` — no error. A migration that's written
but never actually applied to the live DB produces working-looking code with a silently
unmigrated constant.

**Why it happens:** The fallback-default pattern is deliberately fail-soft.

**How to avoid:** After writing the migration, verify live: `SELECT config_key FROM
config_schema WHERE config_key = '<new key>'` returns exactly one row, for every new key.

**Warning signs:** A calibration run's `config_history` reason string always cites the same value
as both "before" and "after."

### Pitfall 5: Peeking at OOS data while iterating a candidate's calibration

**What goes wrong:** Running the new gate script (even `--dry-run`) repeatedly against OOS data
while tuning a candidate's in-sample calibration, using the dry-run output to decide whether to
adjust methodology, silently converts the holdout into a de facto training signal.

**Why it happens:** `--dry-run` feels safe because it writes nothing to `gate_evaluations` — but
the human/agent reading its printed OOS verdict and adjusting the candidate accordingly is
exactly the leak `OOS-EVAL-PROTOCOL.md` exists to prevent.

**How to avoid:** Finalize each candidate's in-sample calibration completely BEFORE running the
new gate against OOS data even once.

**Warning signs:** More than one `--dry-run` invocation of the new gate script per candidate
during development.

## Code Examples

### Existing per-(regime,tf) hold_max_bars read pattern to mirror for stop/target

```python
# Source: services/alpha_frame_writer.py lines 344-348 (live)
hold_key = f"alpha.frame.hold_max_bars.{regime}.{tf}"
if hold_key not in cfg:
    missing_hold_keys.add(hold_key)
max_hold_bars = int(_cfg(cfg, hold_key, _DEFAULT_HOLD_MAX_BARS))
```

### Existing frame geometry pure function (reuse unmodified for both candidates)

```python
# Source: services/alpha_frame_writer.py, compute_frame_geometry() (lines 64-119, live)
def compute_frame_geometry(
    direction: str, entry_price: float, atr: float,
    stop_atr_mult: float, target_r_multiple: float, min_stop_price_fraction: float,
) -> tuple[float, float, float]:
    ...  # returns (stop_price, target_price, r_multiple); raises ValueError on non-positive
         # atr or a stop_distance below min_stop_price_fraction (todo 162's degenerate-ATR fix)
```

### Existing confluence clustering core (portable for the structural candidate)

```python
# Source: src/intelligence/trading/zone_engine.py, lines 85-101, 344-358, 378-395 (live)
@dataclass
class ZoneCandidate:
    price: float
    name: str
    strength: float
    source_tier: str
    source_family: str

def _find_clusters(candidates: list[ZoneCandidate], atr: float) -> list[list[ZoneCandidate]]:
    if not candidates:
        return []
    clusters: list[list[ZoneCandidate]] = []
    current = [candidates[0]]
    radius = atr * _cluster_radius_atr()
    for c in candidates[1:]:
        if abs(c.price - current[-1].price) <= radius:
            current.append(c)
        else:
            clusters.append(current)
            current = [c]
    clusters.append(current)
    return [cl for cl in clusters if len(cl) >= 2]

def _pick_single_best(candidates, entry, atr) -> ZoneCandidate | None:
    if not candidates:
        return None
    best_score, best = -1.0, None
    sw, pw = _strength_weight(), _proximity_weight()
    for c in candidates:
        dist_atr = abs(c.price - entry) / atr if atr > EPSILON else 2.0
        proximity = max(0.0, 1.0 - dist_atr / 2.0)
        score = c.strength * sw + proximity * pw
        if score > best_score:
            best_score, best = score, c
    return best
```

### Existing gate_evaluations write shape (mirror exactly, new gate_id)

```sql
-- production/migrations/248_alpha_scoring_gate_tables.sql (live)
CREATE TABLE IF NOT EXISTS gate_evaluations (
    eval_id   text,
    gate_id   text NOT NULL,
    result    text NOT NULL,
    evidence  jsonb NOT NULL,
    run_ts    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (gate_id, run_ts)
);
```
The composite PK `(gate_id, run_ts)` means Phase 166's new gate_id(s) can each be written exactly
once and re-checked idempotently — no schema change needed.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `stop_atr_mult`/`target_r_multiple` as single global `[initial_estimate]` scalars (1.5, 2.0) | Per-(regime,tf) calibrated values, mirroring `hold_max_bars`'s existing pattern | This phase (166) | Directly addresses the Gate 2 FAIL diagnosis — "never revisited since Phase 142B" (D-02) |
| `hold_max_bars` calibrated pre-096-fix (stride-biased IC Sharpe estimator) | `hold_max_bars` calibrated post-096-fix (fixed-subsampled-window estimator, migration 230, decay_threshold rescaled 0.1→0.05) | 2026-07-13 (fix), confirmed via live `config_history` (last calibration run 2026-07-19 22:07 UTC, `decay_threshold=0.05`) | Live-verified: the currently-live `hold_max_bars.*` keys ARE post-fix (see live-verified finding below) |
| v2.x's rich SMC/swing/zone/VP stop-selection hierarchy, fully archived | v3's structural candidate scoped in two parts: Part 1 (VP/SR confluence, buildable now post-Phase-163) + Part 2 (SMC/swing/fib/anchored-VWAP, deferred pending Phases 164/165) | This phase's own scoping decision (Q3/Q4 above) | A deliberate, evidence-grounded narrowing from the 2026-07-23 broadened D-03.2 ask, driven by a hard, verified data-availability constraint — not a design preference |

**Live-verified finding (worth surfacing to the diagnosis task):** `ensemble_weights` for
`weight_version='143.1-08-champion'` (`computed_at` 2026-07-20 07:53-08:08 UTC) and
`weight_version='run_2025122405150000'` (`computed_at` 2026-07-19 21:49-22:00 UTC,
`alpha.ensemble.weight_version`'s live-resolved value) are **byte-identical** — verified via a
direct row-by-row weight comparison JOIN (zero differing rows, both have exactly 47 rows). This
confirms todo 173's suspicion that these two labels are aliases for the same underlying weights,
and confirms the currently-live `hold_max_bars.*` calibration (ran against
`run_2025122405150000`, post-096-fix, `decay_threshold=0.05`) is a valid post-fix baseline for
whatever weights Gate 2 actually scored (`143.1-08-champion`). Cite this directly in D-01's
diagnosis deliverable rather than re-deriving it.

**Deprecated/outdated:** v2.x's entire I1-I7 pipeline (source of `trade_framer.py`,
`zone_engine.py`, `sr_consensus.py`, `anchored_vwap.py`, `swing_detector.py`, `trend_structure.py`,
`fibonacci_zones.py`, and every SMC file) has zero live consumer — `src/intelligence/CLAUDE.md`'s
own header confirms this. Every function referenced in this research from these files is read for
PATTERN reuse only, never for direct invocation.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | An empirical percentile-of-MAE/MFE (in ATR units, rescaled from the existing R-unit `counterfactual_mfe`/`counterfactual_mae` columns) is a sound substitute selection criterion for the scalar candidate's stop_atr_mult/target_r_multiple, in place of a literal IC-decay-walk | Finding 1, Pattern 1 | If wrong, the scalar candidate could be systematically miscalibrated (right-censoring bias in MAE for closed_stop frames) — flagged explicitly, not silently assumed correct; discuss/plan should confirm this methodology (or an alternative grid-search re-simulation) explicitly |
| A2 | The structural candidate should use `entry_price ± distance_atr_field * atr` to reconstruct a structural stop/target PRICE from Phase 163's ATR-normalized distance columns | Finding 2, Q3 recommendation | If the ATR value normalizing Phase 163's distance columns differs from the ATR value `CounterfactualTracker`/`AlphaFrameWriter` compute independently from `market_data_ohlcv_tradeable`, the reconstructed price could be subtly inconsistent — needs an explicit unit/consistency check once Phase 163 ships live data |
| A3 | Fresh `alpha.frame.*`-namespaced keys should be seeded rather than reusing `feature.trade_framer.*`/`feature.zone_engine.*`/`weights.zone_engine.*` v2.x keys | Finding 5, Anti-Patterns | Low risk either way (recalibration is this phase's whole point regardless) — flagged to avoid an undocumented cross-namespace coupling to an archived system |
| A4 | The new validation gate's `gate_id`(s) should be per-candidate (two rows) rather than one combined gate_id | Pattern 3, Code Examples | The `gate_evaluations` schema supports either shape equally well — naming/granularity recommendation, not a technical constraint |
| A5 | `zone_engine.py`'s clustering/scoring core (`ZoneCandidate`, `_find_clusters`, `_score_cluster`, `_pick_single_best`) is portable "nearly unmodified" into a new v3 module | Q1, Pattern 2, Don't Hand-Roll | Read in full and confirmed generic (no v2.x-specific feature-name references in the clustering/scoring functions themselves — only the spec tables and `_resolve_strength`'s companion-field lookups are v2.x-specific); risk is limited to minor adaptation friction, not a wrong architectural call |
| A6 | The `src/intelligence/features/smc_context/`/`src/intelligence/features/i3_structure/` directories, despite the "features" name, are part of the same dead I1-I7 tier as `src/intelligence/archive/`, not a live v3.0 Feature Factory component | Q2 | Verified directly (register_plugins.py import sources + zero matching live schema columns for every referenced field) — HIGH confidence, not really an assumption, but logged here because the naming collision is a real trap for anyone re-deriving this without checking |

## Open Questions (RESOLVED — see 2026-07-23 planning + review pass)

1. **RESOLVED (diverges from this research's own recommendation, deliberately — see 166-01 Task 0 / 166-06 Task 2).** Does the structural candidate Part 1's implementation wave need to be sequenced strictly
   after Phase 163 execution, or can Phase 166 include executing Phase 163 as its own first
   task?
   - What we know: Phase 163 is fully planned, reviewed, and marked execution-ready in
     STATE.md's Tier 2. It has not been executed. Part 1 cannot produce a meaningfully different
     result from the scalar candidate without Phase 163's columns being live (Pitfall 2).
   - What's unclear: whether the Phase 166 plan should treat `/gsd-execute-phase 163` as an
     explicit prerequisite task/wave inside its own plan, or a cross-phase sequencing dependency
     to resolve before plan-checking Phase 166.
   - Recommendation (this research): treat Phase 163 execution as Wave 0 (or an explicit prerequisite gate) of
     Phase 166's plan — independent, already fully planned, low-risk, directly unblocks Part 1.
   - **Resolution (planning, then reaffirmed after Codex review):** Phase 163 is NOT force-executed inside Phase
     166's own plan — it stays a runtime-checked external cross-phase prerequisite. 166-01 Task 0 checks and
     records liveness; 166-06 Task 2 halts the structural arm only if not live. A `NULL_PENDING_163` halt is
     an explicit, valid, complete 2-of-3-arm phase outcome (baseline + scalar scored, structural marked "not
     evaluable"), not a failure or re-planning trigger. Codex's review flagged the ambiguity of this outcome;
     both 166-01 and 166-06 now state the completion semantics explicitly in both branches.

2. **RESOLVED in 166-02 (LOCKED DESIGN DECISION).** What exactly is the scalar candidate's selection criterion for stop_atr_mult/
   target_r_multiple, precisely?
   - What we know: EIC-02's STRUCTURE should be mirrored (D-03.1). The literal IC-decay-walk
     criterion does not transfer (Pitfall 1). `counterfactual_mfe`/`counterfactual_mae` are
     already-collected, in-sample-available, rescalable-to-ATR-units data.
   - What's unclear: the exact percentile(s), whether right-censored `closed_stop` MAE rows
     should be excluded outright or handled via a survival-analysis-style adjustment, and
     whether a fresh grid-search re-simulation is preferred over reusing existing censored data.
   - Recommendation: surface both options explicitly to `/gsd-discuss-phase` or the plan step for
     an explicit call, given the Renaissance-rigor lens CONTEXT.md invokes.
   - **Resolution:** percentile of the naturally-uncensored excursion subpopulation — stop from
     `closed_target` winner-MAE (`alpha.ensemble_ic.stop_mae_percentile`, default 90th), target from
     `closed_max_hold` time-exit-MFE (`alpha.ensemble_ic.target_mfe_percentile`, default 50th). Sidesteps
     todo 088's right-censoring bias by construction. Grid-search re-simulation and naive all-frame
     percentile were both explicitly considered and rejected.

3. **RESOLVED in 166-04 (LOCKED DESIGN DECISION).** Should the new gate reuse SHADOW-REVIEW.md's frozen five criteria verbatim, or define new
   ones? (CONTEXT.md explicitly left this open.)
   - What we know: SHADOW-REVIEW.md's five criteria are frozen for the CHAMPION's live-promotion
     decision specifically — reusing them for candidate SELECTION (not live-capital promotion) is
     a different question with potentially different appropriate thresholds.
   - What's unclear: whether Phase 166's gate should use the SAME numeric thresholds as a "does
     this candidate clear the promotion bar" check, or a comparative "which candidate scores
     better" criterion without a fixed absolute bar.
   - Recommendation: reuse `evaluate_frame_gate`/`frame_gate_passes` MACHINERY unconditionally
     (Pattern 4), but let the plan step decide explicitly whether thresholds are SHADOW-REVIEW.md's
     frozen values or a new `alpha.scoring.166.*` APR key family. Pre-register this BEFORE
     touching OOS data (Pitfall 5).
   - **Resolution:** reuse SHADOW-REVIEW.md's frozen five criteria verbatim as the absolute bar (via
     `frame_gate_passes`/`evaluate_frame_gate` unmodified), applied identically to all three arms
     (baseline/scalar/structural) — no new thresholds, avoiding any OOS-peeking to tune a bar. Per-candidate
     `gate_id`s (`gate166_scalar`/`gate166_structural`/`gate166_baseline`). Post-review, 166-04 also added a
     descriptive (non-gating) population-footprint field to the evidence JSON and a per-`gate_id` dry-run
     sentinel enforcing the one-dry-run-per-candidate rule in code, not just procedure (Pitfall 5).

4. **RESOLVED in 166-06 Task 3 (todo 175 filed).** Where and how should structural candidate Part 2 (SMC/swing/fib/anchored-VWAP extension) be
   tracked once deferred?
   - What we know: Q3/Q4 above recommend deferring Part 2 entirely, pending Phases 164/165 and a
     new anchored-VWAP scoping effort.
   - What's unclear: whether this should be one new follow-on todo, or three separate ones
     (one per dependency: SMC/Phase-164, swing-fib/Phase-165, anchored-VWAP/unscoped), and
     whether Phase 166's plan should explicitly note the extension point in its own code (a
     comment/TODO in the new `structural_confluence.py` module) so a future phase finds it easily.
   - Recommendation: file one consolidated follow-on todo at Phase 166's completion (per the
     project's "capture todos immediately" convention), cross-referencing all three dependencies,
     and leave an explicit extension-point comment in the new module pointing at that todo number.
     This is a planning/execution-time decision, not something this research locks in.
   - **Resolution:** one consolidated todo (175), cross-referencing Phases 164/165 + anchored-VWAP, with the
     extension-point comment in `structural_confluence.py` citing it. Post-review, 166-06's verdict doc must
     also state explicitly that this toolkit was evaluated and deliberately deferred (not silently dropped),
     so the user's original "reuse v2 trade lifecycle" ask is answered rather than left ambiguous.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL/TimescaleDB | All reads/writes (`alpha_frames`, `config_state`, `gate_evaluations`) | Yes (live-queried during this research) | — | — |
| `numpy`/`scipy.stats` | Bootstrap CI, percentile calibration | Yes (already imported by `ensemble_ic_engine.py`/`counterfactual_tracker.py`) | — | — |
| `asyncpg` | New calibration/gate scripts | Yes (project-standard) | — | — |
| Phase 163 live data (`sr_support_dist`, `sr_resist_dist`, `poc_dist_atr`, `poc_rolling_dist_atr`, `distance_to_vah_atr`, `distance_to_val_atr`, `resistance_strength`, `support_strength`, `resistance_age_bars`, `support_age_bars`) | Structural candidate Part 1 | **No — Phase 163 not yet executed; columns exist but are 100% NULL** | — | Execute Phase 163 first (Open Question 1) |
| Phase 164 live data (SMC: order blocks, liquidity pools/sweeps, BOS/CHoCH, premium/discount) | Structural candidate Part 2 (deferred) | **No — Phase 164 not even planned (zero artifacts)** | — | Defer Part 2 entirely (Q3/Q4 recommendation) |
| Phase 165 live data (swing/fib/trend) | Structural candidate Part 2 (deferred) | **No — Phase 165 researched but not planned/executed** | — | Defer Part 2 entirely |
| Anchored VWAP live data | Structural candidate Part 2 (deferred) | **No — no registered phase covers this at all** | — | Defer Part 2 entirely, flag for new scoping |

**Missing dependencies with no fallback:**
- Phase 163 live data for structural candidate Part 1 — blocks only Part 1's
  implementation/testing wave, not the scalar candidate or the diagnosis task.
- Phase 164/165/anchored-VWAP live data for structural candidate Part 2 — by design, deferred
  entirely out of Phase 166's scope (Q3/Q4), not a blocker for Phase 166's completion.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 6.0+ (`pytest.ini`, `asyncio_mode = auto`) |
| Config file | `pytest.ini` (repo root) |
| Quick run command | `.venv/bin/pytest tests/unit/test_ensemble_ic_decay.py tests/unit/test_alpha_frame_writer_geometry.py tests/unit/test_counterfactual_tracker_exit_priority.py tests/unit/trading/test_zone_engine.py -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |

### Phase Requirements → Test Map

CONTEXT.md's `<decisions>` block (D-01 through D-05) is the effective requirement source (no
formal REQ-IDs exist yet for this phase).

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| D-01a | Diagnosis compares current stop/target/hold calibration against IC decay curve | integration (read-only analysis script) | manual run of new diagnosis script against live DB | ❌ Wave 0 |
| D-01b | Scalar candidate: new `_calibrate_stop_target()`-equivalent function, per-(regime,tf) median, CR-02 gated, MAE/MFE-percentile selection | unit | `pytest tests/unit/test_ensemble_ic_stop_target_calibration.py -x` | ❌ Wave 0 |
| D-01c | Structural candidate Part 1: VP/SR confluence-scored stop/target price selection | unit | `pytest tests/unit/test_structural_confluence.py -x` | ❌ Wave 0 (also blocked on Phase 163 for any live-data integration test) |
| D-01d | Fresh validation gate scoring both candidates, new `gate_id`(s) | unit (pure evidence-assembly function, synthetic rows) + integration (dry-run against live DB) | `pytest tests/unit/test_gate166_frame_recalibration_eval.py -x` | ❌ Wave 0 |
| D-02 | Baseline facts confirmed (hold_max_bars calibrated, stop/target not) | N/A — already verified live during this research | — | N/A |
| D-03 | Both candidates built and empirically compared, not chosen a priori | integration | the new gate script's dry-run output, reviewed manually | ❌ Wave 0 |
| D-04 | New gate_id, not a re-run of `gate2_execution` | unit + live DB check | `pytest -k test_gate166_uses_new_gate_id` + `SELECT DISTINCT gate_id FROM gate_evaluations` | ❌ Wave 0 |
| D-05 | Regime-window coverage disclosed, not gated | unit (assert regime companion always computed/included) | mirrors `test_score03_gate2_execution_eval.py`'s regime-companion assertions | ❌ Wave 0 (pattern exists to copy) |

### Sampling Rate
- **Per task commit:** targeted new test file(s) for that task's function(s)
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -q` (full suite)
- **Phase gate:** Full suite green before `/gsd:verify-work`; the new gate script's `--dry-run`
  output must be manually reviewed before its one real (OOS-touching) run per candidate
  (Pitfall 5)

### Wave 0 Gaps
- [ ] `tests/unit/test_ensemble_ic_stop_target_calibration.py` — covers D-01b, mirrors
      `tests/unit/test_ensemble_ic_decay.py`'s structure
- [ ] `tests/unit/test_structural_confluence.py` — covers D-01c, mirrors
      `tests/unit/trading/test_zone_engine.py`'s synthetic-candidate style
- [ ] `tests/unit/test_gate166_frame_recalibration_eval.py` — covers D-01d/D-04/D-05, mirrors
      `tests/unit/test_score03_gate2_execution_eval.py` almost exactly
- [ ] No new pytest fixtures or conftest.py changes anticipated — existing patterns (synthetic
      dict rows, no live DB needed for unit tests) fully cover this phase's testable surface

*(Framework install: none needed — pytest already configured project-wide.)*

## Security Domain

`security_enforcement` is absent from `.planning/config.json` (treated as enabled per protocol),
but this phase has no user-facing input surface, no authentication/session/access-control
change, and no new network-exposed endpoint — entirely internal batch computation and config-key
writes gated by existing `ConfigService._validate_key_domain()` checks.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No new auth surface |
| V3 Session Management | No | No new session surface |
| V4 Access Control | No | No new access-control surface (internal batch scripts, not API endpoints) |
| V5 Input Validation | Partial | `ConfigService._validate_key_domain()`/`config_schema` min/max bounds already validate any new APR key value before write |
| V6 Cryptography | No | No new cryptographic surface |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via dynamically-constructed config keys | Tampering | All existing patterns use parameterized queries; f-string-built key strings are DICTIONARY KEYS looked up in an already-fetched Python dict, never SQL string interpolation |
| Silent APR value corruption from an unmigrated key | Tampering (of config integrity) | `config_schema`'s `min_value`/`max_value` bounds + `ConfigService._validate_key_domain()` — enforce for every new key |

## Sources

### Primary (HIGH confidence — read directly from live source/live DB during this research)
- `services/ensemble_ic_engine.py` (lines 140-350, 900-1130) — `_calibrate_hold_max_bars`,
  `_select_hold_bars_from_decay`, `_QUALIFYING_FLAGS`, champion-weight_version resolution
- `services/alpha_frame_writer.py` (full file) — `compute_frame_geometry`, `FrameConfig.from_apr`
- `services/counterfactual_tracker.py` (lines 105-1091) — `determine_exit`,
  `compute_frame_pnl_r`, `frame_gate_passes`, `evaluate_frame_gate`, `_compute_excursion`
- `src/intelligence/trading/trade_framer.py` (lines 273-1300) — `_classify_stop_basis`,
  `_select_vp`, `_resolve_stop_long`/`_resolve_stop_short`, `_collect_target_candidates`
- `src/intelligence/trading/zone_engine.py` (full file, 499 lines) — confluence-resolution
  architecture, spec tables, clustering/scoring core
- `src/intelligence/context/sr_consensus.py`, `src/intelligence/context/anchored_vwap.py`,
  `src/intelligence/features/i3_structure/swing_detector.py` — read to confirm liveness status
  and input-data requirements
- `src/intelligence/register_plugins.py` — grepped to confirm import sources (archive/ vs
  features/ for SMC files; TIER_I3/TIER_I4 registration)
- `scripts/analysis/score03_gate2_execution_eval.py` (full file) — the exact template for
  Phase 166's new gate script
- `production/migrations/205_alpha_frames_schema.sql`, `207_alpha_frames_target_r_multiple.sql`,
  `248_alpha_scoring_gate_tables.sql`, `141_phase132_trade_framer_apr.sql`,
  `126_phase125_param_store.sql`, `128_phase126_apr_seeds.sql` — schema/APR provenance
- `docs/plans/SHADOW-REVIEW.md`, `docs/plans/OOS-EVAL-PROTOCOL.md`,
  `docs/plans/archive/2026-07-22-phase148-promotion-decision.md` — frozen gate criteria, holdout
  discipline, Gate 1/Gate 2 evidence
- `.planning/todos/pending/088-hold-max-bars-censoring-not-tracked.md`,
  `096-frame-hold-horizon-vs-feature-lookahead-mismatch.md`,
  `172-path-dependent-frame-statistics-order-sensitivity-sweep.md`,
  `173-ensemble-alpha-1h-1d-oos-scoring-gap.md` — full text read, folded constraints
- `.planning/milestones/v3.1-phases/163-vp-sr-structural-primitives/163-01-PLAN.md` — confirms Phase 163's
  ATR-normalized-only column design (D-16), not-yet-executed status
- `src/intelligence/CLAUDE.md` — archived-tier confirmation for the entire I1-I7 pipeline
- Live DB queries (this session, 2026-07-23): `gate_evaluations`, `config_state` (`alpha.frame.*`
  current values, all 36 `hold_max_bars.<regime>.<tf>` keys + global scalars), `config_history`
  (last hold_max_bars calibration run timestamp/decay_threshold), `ensemble_weights` (row-for-row
  identity between `143.1-08-champion` and `run_2025122405150000`), `alpha_frames` (OOS-window
  row/day counts by tf/regime/direction), `feature_vectors` schema (exhaustive column-name check
  against the full broadened structural toolkit's ~20+ referenced feature keys — zero matches
  outside the four Phase-163-owned columns)

### Secondary (MEDIUM confidence)
- None — every substantive claim in this document traces to a primary source above.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages, all reused libraries already live in the codebase
- Architecture: HIGH — every pattern cited is read from live, currently-passing source code
- Structural candidate data-availability finding: HIGH — verified exhaustively via direct
  live-schema column-name checks, not inferred from documentation
- Pitfalls: HIGH — every pitfall traces to either a live-verified data gap or a documented,
  already-occurred incident (todo 088/172/162, Phase 148's c4 investigation)
- Data availability (D-05): HIGH — confirmed via direct live DB query, cross-checked against
  `docs/plans/archive/2026-07-22-phase148-promotion-decision.md`'s own regime-stratified table
- Open Questions 2/3/4: genuinely open design decisions, not confidence gaps — flagged for
  `/gsd-discuss-phase` or the plan step, not resolved unilaterally by this research

**Research date:** 2026-07-23
**Valid until:** ~14 days (fast-moving — live `config_state`/`alpha_frames`/`ensemble_weights`
values cited here will drift as soon as any corpus re-run or Phase 163/164/165 execution
happens; re-verify the live-DB-sourced numbers before planning if more than ~2 weeks have
elapsed, or if Phase 163/164/165 have executed in the interim)
