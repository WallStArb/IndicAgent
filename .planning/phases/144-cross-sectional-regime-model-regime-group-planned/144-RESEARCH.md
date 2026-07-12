# Phase 144: Cross-Sectional Regime Model (`regime_group`) - Research

**Researched:** 2026-07-12
**Domain:** PostgreSQL/TimescaleDB batch pipeline service (regime labeling) + `ic_engine.py` routing integration
**Confidence:** HIGH (this phase is executing a pre-existing, unusually complete implementation
plan against a live, fully-inspected codebase — nearly every claim below is `[VERIFIED]` against
the actual current file, not inferred)

## Summary

Phase 144 executes `docs/plans/2026-07-01-cross-sectional-regime-model.md` (2687 lines, Tasks
0-9), which is materially still correct in design and ~85% correct in implementation-level
detail. This research's job was to find the 15% that has drifted since 2026-07-01 and would
otherwise cause a literal-diff application to fail or (worse) silently reintroduce a bug.

Three classes of drift were found, all `[VERIFIED]` against the live files:

1. **Migration number.** Plan doc says `189`; the correct next-free number is **`229`**
   (highest applied is `228_instrument_tag_vocabulary_v2.sql`). Migration numbers in this repo
   have been renumbered multiple times historically and even collide (two files each at `214`
   and `215`) without being fatal — there is no `schema_migrations` tracking table, migrations
   are applied by hand via `psql -f`. Pick the true next number (229) for cleanliness but don't
   treat a later collision as a blocker if a concurrent session grabs it first.

2. **`ic_engine.py`'s structure has moved significantly.** The plan doc's Task 5 diffs
   (`_load_apr` returning a dict, `mr_dict_by_tf` as a single flat dict, `_compute_cross_sectional_tf(apr=...)`)
   describe a pre-Phase-143/143.1 version of the file. The live file (3020 lines, was ~1970 when
   the plan doc was written) now binds config through a frozen `ICEngineConfig` dataclass
   (`from_apr()` classmethod), threads a deterministic bootstrap RNG through every compute call,
   and has 5 new dataclass fields from Phase 143/143.1. The **intent** of all 6-7 touch points
   the plan doc describes is still correct and still needed — only the literal code around them
   must be adapted to the current shapes. Full mapping in the Architecture Patterns section below.

3. **Two real regressions would ship if Task 2's `breadth_vol.py` is implemented literally as
   written in the plan doc**, both `[VERIFIED]` by diffing the plan doc's code against the live
   `services/equity_regime_model.py` it claims to extract from:
   - The plan doc's `compute()` uses `vix_z.rank(pct=True, na_option="keep")` — a **non-causal,
     whole-series rank** (ranks every point against future values too). The live
     `equity_regime_model.py._compute_vix_pct_rank()` deliberately replaced this exact pattern
     with a **causal bisect-based expanding rank** as **Phase 141's P0-T2 / V1 look-ahead-bias
     fix** (dedicated test: `tests/unit/services/test_equity_regime_model_causal.py`). Copying
     the plan doc's `breadth_vol.py` verbatim reintroduces a fixed look-ahead bias bug.
   - The plan doc's `breadth_vol.py` treats APR window params (`ma_window=200`,
     `vix_z_window=252`, `realized_vol_window=20`) as **literal bar counts**, applied identically
     across all 4 TFs. The live `equity_regime_model.py` explicitly scales these via
     `_tf_window(daily_window, tf)` (200 days → 15,600 bars at 5m, 1,764 bars at 1h, 20 bars at
     1d) — without this, a `vix_z_window=252` would mean "252 five-minute bars" (~21 trading
     hours) at 5m instead of the intended "1 trading year," and the low/mid/high tier thresholds
     would be miscalibrated per-TF.

The cross-sectional regime-contamination bug this phase fixes is also independently
`[VERIFIED]` live: `_compute_cross_sectional_tf`'s current `chunk_sql` (line ~1591) filters only
by `tf` and `bar_ts IN (regime_timestamps)` — it has **no symbol filter at all**. Every symbol in
the corpus (including all 12 `fi_*` bond ETFs, GLD/SLV/VNQ, IBIT) is currently pooled into the
`asset_class='equity'`-labeled cross-sectional cells. This is exactly the "contaminated equity
regime label" bug described in CONTEXT.md D-01, confirmed at the SQL level.

**Primary recommendation:** Follow the plan doc's task order and design as-is (glossary → migration →
breadth_vol → curve_credit → dispatcher → ic_engine routing → pipeline rewire → commodity/fx
modules → tag vocabulary), but (a) fix `breadth_vol.py`'s two regressions during Task 2 by porting
`equity_regime_model.py`'s causal-rank and `_tf_window` logic instead of the plan doc's literal
code, (b) re-derive Task 5's `ic_engine.py` diffs against the current dataclass-based
`ICEngineConfig`/RNG-threaded structure rather than applying the plan doc's line-anchored patches,
and (c) simplify Task 6's pipeline-script edit — the pipeline is now 8 steps (not 6), and
`equity_regime_model` already occupies its own step 4 slot, so this is a same-slot script-name
swap, not a step-insertion.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Peer-group resolution (symbol → regime_group) | Batch compute (`cross_sectional_regime_model.py`, `ic_engine.py`) | Database (`instrument_tags`) | Tag-based routing resolved once per run from a table; no runtime service owns this as state |
| Cross-sectional signal computation (breadth_vol, curve_credit, etc.) | Batch compute (pure signal modules in `src/intelligence/regime_signals/`) | — | Pure functions, no DB — matches project's compute≠persistence SoC rule |
| `market_regimes` persistence | Database / Writer (`cross_sectional_regime_model.py`'s `_write_rows`) | — | Single writer, batch upsert, no daemon holds a long-lived write connection |
| Regime-stratified IC measurement | Batch compute (`ic_engine.py`) | Database (`feature_ic_scores`) | Consumes `market_regimes` + `feature_vectors`, writes IC statistics |
| Config (group definitions, per-group thresholds) | Database (APR `config_state`/`config_schema`) | — | Adaptive Parameter Registry mandate — no hardcoded thresholds per CLAUDE.md |
| Empirical re-measurement (acceptance gate) | Batch compute (ad hoc SQL against `feature_ic_scores`) | — | One-time analysis, not a persisted service; queued behind the 143.1-07 corpus rebuild |

<phase_requirements>
## Phase Requirements

No requirement IDs were mapped to this phase (`phase_req_ids` is null per the orchestrator scope).
This phase's scope is instead fully defined by CONTEXT.md's `## Decisions` (D-01 through D-08)
and the canonical implementation plan doc — see `<user_constraints>` below.
</phase_requirements>

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Phase 144 ships exactly `docs/plans/2026-07-01-cross-sectional-regime-model.md`'s
  Tasks 0-9: migration 189-equivalent (renumber to next free migration — corpus is at 228 as of
  2026-07-12, plan doc's literal "189" is stale), `src/intelligence/regime_signals/` (breadth_vol
  + curve_credit; commodity/fx modules ship present but `enabled: false`),
  `services/cross_sectional_regime_model.py` dispatcher, `services/ic_engine.py` routing
  (`_build_symbol_regime_class`, `AmbiguousRegimeGroupError`, per-group `mr_dicts_by_group`).
- **D-02:** Todo 026 P2b (degenerate-model occupation-fraction gate) and P2c (`hmm_churn`
  column) were investigated as candidates to bundle in — **verified already shipped 2026-07-06 via
  Phase 143 Plan 01 (LIFECYCLE-00)**. Nothing to bundle.
- **D-03:** Todo 026's remaining item (P3, empirical vix/breadth threshold calibration) is
  already split into standalone `.planning/todos/pending/092-equity-regime-model-threshold-calibration.md`
  — stays separate, not folded into this phase's plan.
- **D-04:** Todo 041 (tag exposure-vs-sensitivity taxonomy audit) gates commodity/fx group
  *enablement* only (those groups ship `enabled: false` regardless) — does not block or need to
  be folded into this phase's plan.

### Acceptance gate: this phase includes the empirical re-measurement
- **D-05:** Phase 144 is not "done" at code-complete. Its own verification includes running the
  widened Step 1 protocol from `docs/research/fable-2026-07-07-phase144-conditioning-decision.md`
  §6 Input 1: per-symbol TLT vs. the new `rates` cross-sectional group (not the old contaminated
  equity comparison), one representative per enabled `regime_group`, todo 026's existing bands
  (gap < 0.01 deficient, 0.01-0.05 ambiguous). This is the pre-committed falsifier check (F1/F2
  in that doc) that decides whether per-symbol HMM stays demoted-to-shadow for `rates` (already
  the default live behavior via routing) or the factor-augmented HMM challenger (option c) gets
  triggered.
- **D-06:** This re-measurement step is necessarily sequenced after the corpus re-run (see D-07)
  — it cannot run against stale data. Plan-phase should scope it as this phase's final
  verification task, not as a separate follow-up todo.

### Sequencing relative to the in-flight 143.1-07 corpus rebuild
- **D-07:** Code, migration, dispatcher, and `ic_engine.py` routing work can be planned and
  executed now — none of it touches the in-flight `143.1-07` corpus rebuild. Defer running
  `cross_sectional_regime_model.py` full-run and the batched `ic_engine` re-run (and therefore
  D-05's Step 1 gate) until 143.1-07 completes and is verified clean — single-writer discipline
  on derived tables.
- **D-08:** No code changes needed to check 143.1-07's status at execute-phase time — check
  `feature_ic_scores` row freshness / the corpus pipeline state memory before running the
  measurement step.

### Claude's Discretion
- Exact migration number (whatever is next free — plan doc's literal "189" is stale). **Resolved
  by this research: 229.**
- Whether to keep `equity_regime_model.py` as a deprecated rollback fallback (plan doc's Task 1
  says yes, no functional changes) — follow the plan doc unless a reason emerges not to.
- Commodity/fx signal modules (`commodity_momentum_ts.py`, `fx_dollar_carry.py`) ship as part of
  this phase per the plan doc's File Map even though their groups stay `enabled: false` — build
  them now (cheap, already spec'd with tests) rather than defer.

### Deferred Ideas (OUT OF SCOPE)
- **concept_registry row-grain question** — not resolved here; `concept_registry` itself does
  not exist yet. Revisit at future v3.15 planning.
- Todo 026 P2b/P2c, Todo 026 P3 / Todo 092, Todo 041, Todo 039, Todo 038 — all reviewed during
  discuss-phase and explicitly not folded into this phase's plan (see CONTEXT.md `<deferred>`
  for full reasoning per item).
</user_constraints>

## Project Constraints (from CLAUDE.md)

These apply to every file this phase creates or modifies, verified relevant to this phase's scope:

- **Exception variable name is `error`** — `except X as error:`, not `exc`. (Plan doc already
  follows this convention throughout.)
- **All timestamps UTC** — `datetime.now(UTC)` only, never `datetime.now()`/`.utcnow()`.
- **APR mandate**: every new numeric threshold in this phase's signal modules (window sizes,
  tier boundaries) must be an APR key (`config_schema` + `config_state`), never a hardcoded
  constant. The plan doc's migration already does this correctly for `alpha.rates_regime.*`,
  `alpha.equity_regime.*`, `alpha.commodity_*_regime.*`, `alpha.fx_regime.*`. Gradient column/tier
  naming should use scale qualifiers (`low/mid/high`, `steep/flat/inverted`) per the naming-system
  §7 convention — the plan doc's tier vocabulary already follows this.
- **`KafkaProducerClient.publish()` kwarg is `msg=`** — not relevant to this phase (no Kafka
  publish in the dispatcher or `ic_engine.py` routing changes).
- **D-06 oneshot contract**: `cross_sectional_regime_model.py` must emit
  `job_completed_total{job, status}` at exit via `JOB_COMPLETED_TOTAL` + `flush_and_shutdown_metrics()`.
  Plan doc's `main()` already does this. **Verified: no dedicated systemd unit exists for
  `equity_regime_model.py`** — it runs only as a step inside
  `scripts/ops/corpus/ops_corpus_pipeline_run.sh` (a bash orchestrator, not a systemd-managed
  daemon), so `job` label should match the pipeline step's job name
  (`"cross-sectional-regime-model"`), not a literal `%n` systemd suffix — there is no unit to
  match.
- **`No ProcessPoolExecutor` writes from workers** — moot for this phase; the plan doc explicitly
  scopes `cross_sectional_regime_model.py` to be single-process (label assignment is vectorized
  numpy, DB fetch is the bottleneck) — no `ProcessPoolExecutor` at all in the new service.
- **Never log per-row inside a loop over the full corpus** — the dispatcher's per-(group, tf)
  logging (not per-row) already complies.
- **File/class renames require a test sweep**: `grep -r "asset_class" tests/` after the migration,
  not just `grep -r "asset_class" services/`. See Common Pitfalls.
- **Migrate-as-you-go**: any new numeric threshold introduced anywhere in this phase's new files
  must be APR-backed in the same session, not left as a module constant. The plan doc's `_DEFAULT_GROUPS_JSON`
  fallback constant in `cross_sectional_regime_model.py` is acceptable — it's a *fallback default*
  for `cfg.get_sync()`, matching the established pattern elsewhere in the codebase (e.g.
  `ICEngineConfig.from_apr()`'s inline defaults), not a hardcoded operational constant.

## Standard Stack

This phase uses only libraries already vendored in the project — no new dependencies.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| psycopg2 | already in use | DB connectivity, matches every other batch service | Existing project convention |
| pandas | already in use | Rolling-window signal computation | Existing project convention |
| numpy | already in use | Vectorized label bucketing (`_bucket`), z-scores | Existing project convention |
| structlog | already in use | `setup_service_logging()` | Existing project convention |

**No package legitimacy audit required** — this phase installs zero new external packages.
`## Package Legitimacy Audit` section is intentionally omitted per that section's own
applicability gate (only required "whenever this phase installs external packages").

### Alternatives Considered
None — this is an internal architectural refactor of already-standard project infrastructure;
there is no external-library decision to make.

## Architecture Patterns

### System Architecture Diagram

```
market_data_ohlcv (raw bars)
        │
        ▼
instrument_tags ──────► [tag_filter resolution] ──► peer_symbols per regime_group
        │                                                    │
        ▼                                                    ▼
cross_sectional_regime_model.py (dispatcher, batch, single-process)
        │
        ├─ for each enabled group in alpha.regime.groups:
        │     ├─ fetch peer (+ reference) symbol bars for this TF
        │     ├─ REGISTRY[signal_type].compute(bars, params) → (sig1, sig2)
        │     ├─ _assign_labels(...) → [(regime_group, tf, ts, label, prob), ...]
        │     └─ _write_rows() → market_regimes (upsert)
        ▼
market_regimes (regime_group, tf, ts, regime_label, regime_prob_vector)
        │
        ▼
ic_engine.py main()
        ├─ load alpha.regime.groups → enabled_groups
        ├─ _build_symbol_regime_class(tags_by_symbol, enabled_groups) → symbol→group map
        │     (raises AmbiguousRegimeGroupError if a symbol matches >1 enabled group;
        │      OMITS symbols matching 0 enabled groups — no silent default)
        ├─ mr_dicts_by_group: {group_name → {tf → {ts → label}}}  (loaded once, picklable)
        ├─ per-symbol pass (ProcessPoolExecutor): worker gets
        │     mr_dicts_by_group.get(symbol_regime_class.get(symbol))  — its OWN group's dict
        │     → _compute_symbol_tf(..., mr_dict=that_dict) → regime-stratified IC per symbol
        └─ cross-sectional pass (main process, serial):
              for each enabled group: pool ONLY that group's peer symbols
              (symbol_list filter — THE FIX for the contamination bug) →
              _compute_cross_sectional_tf(..., regime_group=g, symbol_list=peers)
              → POOLED cross-sectional IC per (regime_group, tf, regime_label)
        ▼
feature_ic_scores (regime column carries the group-specific label string;
                    group identity is implicit in label vocabulary uniqueness —
                    see Common Pitfalls, "no regime_group column on feature_ic_scores")
```

### Recommended Project Structure
```
src/intelligence/regime_signals/
├── __init__.py                    # REGISTRY: dict[str, module]
├── breadth_vol.py                 # equity signal — PORT causal-rank + _tf_window from
│                                   # services/equity_regime_model.py, do NOT copy plan
│                                   # doc's compute() literally (see Pitfall 1)
├── curve_credit.py                # rates signal — new, plan doc code is fine as-is
├── commodity_momentum_ts.py       # ships disabled; plan doc code fine as-is
└── fx_dollar_carry.py             # ships disabled; plan doc code fine as-is

services/
├── cross_sectional_regime_model.py  # new generic dispatcher (Task 4)
├── equity_regime_model.py           # kept, deprecation header only (Task 6/rollback fallback)
└── ic_engine.py                     # modified — routing added (Task 5, see touch-point table)

production/migrations/
└── 229_regime_group.sql             # renumbered from plan doc's "189"
```

### Pattern 1: Tag-based peer-group resolution with fail-loud ambiguity
**What:** `_build_symbol_regime_class()` maps each symbol to exactly one enabled `regime_group`
by prefix-matching `instrument_tags`. A symbol matching >1 enabled group's `tag_filter` raises
`AmbiguousRegimeGroupError` (config-authoring error, never silently resolved by array order). A
symbol matching 0 enabled groups is **omitted**, not defaulted to `"equity"`.
**When to use:** Any place symbol→peer-group routing happens (both `cross_sectional_regime_model.py`
and `ic_engine.py` need their own copy of this logic — the plan doc duplicates it intentionally
since one is a service module and one is embedded in `ic_engine.py`; consider whether to import
one from the other in the actual plan, since the logic is byte-identical between the two spec'd
implementations — `[LOW confidence / open question, see below]`).
**Example (plan doc's `ic_engine.py` version, already unit-tested in the plan doc):**
```python
# services/ic_engine.py — new function, Task 5 Step 3
def _build_symbol_regime_class(
    tags_by_symbol: dict[str, set[str]],
    group_configs: list[dict],
) -> dict[str, str]:
    prefixes_by_group = [
        (g["name"], [p.rstrip("*") for p in g.get("tag_filter", [])])
        for g in group_configs if g.get("enabled", True)
    ]
    result: dict[str, str] = {}
    for symbol, tags in tags_by_symbol.items():
        matches = [name for name, prefixes in prefixes_by_group
                   if any(any(t.startswith(pfx) for t in tags) for pfx in prefixes)]
        if len(matches) > 1:
            raise AmbiguousRegimeGroupError(...)
        if matches:
            result[symbol] = matches[0]
    return result
```

### Pattern 2: Frozen `ICEngineConfig`-compatible group loading (current `ic_engine.py` shape)
**What:** `ic_engine.py` no longer loads APR into a loose dict (`_load_apr` does not exist as a
function). Config is bound once into a frozen `ICEngineConfig` dataclass via `ICEngineConfig.from_apr(cfg)`
at the top of `main()` (line 2615), which every downstream function receives as a single
`config: ICEngineConfig` object (not `apr: dict`).
**When to use:** Wherever the plan doc's Task 5 refers to "add `groups_json` to the `_load_apr`
returned dict" — that pattern is stale. Instead:
```python
# Add a new field to ICEngineConfig (near equity_model_enabled, line ~332):
regime_groups_json: str = "[]"

# In from_apr() (line ~385), add:
regime_groups_json=str(cfg.get_sync("alpha.regime.groups", _DEFAULT_GROUPS_JSON_FALLBACK)),

# In main(), after config = ICEngineConfig.from_apr(_cfg_svc) (line 2615):
from services.cross_sectional_regime_model import _parse_group_configs
group_configs = _parse_group_configs(config.regime_groups_json)
enabled_groups = [g for g in group_configs if g.get("enabled", True)]
```
This keeps the existing "bind once, frozen for the whole run" invariant the Phase 143.1
refactor established — do not add a second, separately-timed config load path.

### Pattern 3: Cross-sectional pooling MUST filter by peer symbol list (the actual bug fix)
**What:** The current `_compute_cross_sectional_tf`'s `chunk_sql` (line ~1591-1601) has no
`fv.symbol` filter at all — every symbol in the corpus flows into whatever regime timestamps were
pre-fetched (currently always `asset_class='equity'`). Fixing this requires threading a
`symbol_list: list[str]` parameter through to the SQL:
```python
# Add to chunk_sql WHERE clause (services/ic_engine.py, ~line 1599):
WHERE fv.tf = %(tf)s
  AND fv.bar_ts = ANY(%(ts_chunk)s)
  AND fv.symbol = ANY(%(symbol_list)s)      # <-- new, THE fix
```
Also update the regime-timestamp pre-fetch query (line ~1556-1571) and the `_assert_prerequisites`/
`mr_dict` loading queries to filter `WHERE regime_group = %s` instead of the hardcoded
`WHERE asset_class = 'equity'` (4 occurrences total — confirmed via
`grep -n "asset_class" services/ic_engine.py`: lines 503, 1559, 2722, 2834 as of this research date).
**When to use:** Task 5, all 4 `asset_class='equity'` sites plus the new `symbol_list` filter in
`_compute_cross_sectional_tf`.

### Pattern 4: Causal expanding rank (must reuse, not reinvent)
**What:** `equity_regime_model.py._compute_vix_pct_rank()` already implements a causal
bisect-based expanding percentile rank (no look-ahead), fixed under Phase 141's P0-T2/V1
mandate. Port this function's logic into `breadth_vol.py`, replacing the plan doc's
`vix_z.rank(pct=True, na_option="keep")` line.
**Example (the CORRECT logic to port, from live `services/equity_regime_model.py:186-251`):**
```python
# Causal bisect-based expanding rank (no look-ahead bias).
sorted_window: list[float] = []
causal_ranks: list[float] = []
for val in vix_z:
    if math.isnan(val):
        causal_ranks.append(float("nan"))
        continue
    if not sorted_window:
        bisect.insort(sorted_window, val)
        causal_ranks.append(1.0)
        continue
    left = bisect.bisect_left(sorted_window, val)
    right = bisect.bisect_right(sorted_window, val)
    rank = (left + right) / 2 / len(sorted_window)
    bisect.insort(sorted_window, val)
    causal_ranks.append(rank)
```

### Pattern 5: TF-window scaling (must reuse `_tf_window`, not treat APR ints as raw bars)
**What:** `equity_regime_model.py._tf_window(daily_window, tf)` converts a day-denominated
window (e.g. `ma_window=200` meaning "200 calendar days") into the correct bar count per TF
(`_tf_window(200, '5m') == 15600`, `_tf_window(200, '1d') == 200`). Without this, `breadth_vol.py`'s
compute() would apply the same absolute bar count across all 4 TFs, making the signal
non-comparable and miscalibrated at intraday TFs.
**When to use:** `breadth_vol.py`'s `compute()`, for `realized_vol_window`, `vix_z_window`,
`ma_window`. **Open question for the planner:** should `curve_credit.py` (new, not extracted
from a bug-fixed predecessor) also apply `_tf_window` scaling to `curve_window`/`credit_window`,
or is a literal bar-count window (matching the plan doc's default `60`) an intentional, simpler
initial design for a brand-new signal? Flagged in Open Questions — not resolved here since it's a
genuine design choice, not a verified bug like Pattern 4.

### Anti-Patterns to Avoid
- **Copying plan-doc code verbatim without diffing against the current file it claims to modify
  or extract from.** This research exists specifically because that diff surfaces real,
  non-cosmetic bugs (Patterns 4/5) that a literal port would silently reintroduce.
- **Treating `equity_model_enabled` boolean gates in `ic_engine.py` as needing full removal.**
  They can mostly be *generalized* (`equity_model_enabled` → `bool(enabled_groups)`) rather than
  deleted — `_persist_corpus_results`'s `equity_model_enabled and corpus_cs_rows` gate, for
  example, only needs the boolean semantics preserved, not group-awareness.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Causal percentile rank | A new "look-ahead safe" rank implementation | Port `equity_regime_model.py._compute_vix_pct_rank`'s bisect logic verbatim | Already fixed once (Phase 141 P0-T2), already unit-tested; reinventing risks a subtly different (and possibly still-biased) implementation |
| APR config loading | A bespoke `dict`-returning loader | `services/_batch_utils.py::load_config_service_sync` + `ConfigService.get_sync()` | Established pattern used by every batch service including `equity_regime_model.py` itself |
| D-06 oneshot completion signal | Custom exit-code/metric plumbing | `JOB_COMPLETED_TOTAL.add(1, {"job": ..., "status": ...})` + `flush_and_shutdown_metrics()` | OTel health contract is mandatory (D-06, non-negotiable per CLAUDE.md) |
| TF-to-bar-count scaling | A new day↔bar conversion helper local to `breadth_vol.py` | Port `equity_regime_model.py._tf_window()` | Single source of truth for the `_BARS_PER_DAY` mapping; duplicating it risks the two implementations drifting |

**Key insight:** Nearly everything this phase needs already exists in the codebase in
bug-fixed, unit-tested form (`equity_regime_model.py`'s two look-ahead/scaling fixes). The
highest-value planning work here is *porting known-good logic*, not writing new signal math.

## Common Pitfalls

### Pitfall 1: Look-ahead bias reintroduction via literal breadth_vol.py port
**What goes wrong:** `pd.Series.rank(pct=True)` on a full column ranks every element against the
*entire* series, including future timestamps — this is look-ahead bias in a regime label that
`ic_engine.py` uses to stratify IC measurement, which would then silently overstate cross-sectional
IC for the equity group in exactly the way Phase 141's V1 fix was created to prevent.
**Why it happens:** The plan doc was written/last-revised 2026-07-01, concurrently with or just
before Phase 141 (completed 2026-06-29 — actually the plan doc predates Phase 141's V1 fix
landing in `equity_regime_model.py`, or was never synced back to it after).
**How to avoid:** Port `_compute_vix_pct_rank`'s bisect-based logic (Pattern 4) instead of the
plan doc's `Step 4` code block verbatim.
**Warning signs:** If `tests/unit/test_regime_signals_breadth_vol.py::TestComputeReturnShape::test_warmup_bars_are_nan`
passes but a look-ahead-specific test (not present in the plan doc's test file — add one,
mirroring `test_vix_pct_rank_causal_property` from `test_equity_regime_model_causal.py`) is
missing, the regression can ship undetected.

### Pitfall 2: `_compute_cross_sectional_tf` signature/call-site drift
**What goes wrong:** The plan doc's Task 5 Step 10/11 diffs assume a function signature
`(conn, tf, regime_label, regime_group, symbol_list, training_window_end, existing_keys, apr, tracer, run_ts, feature_status_map)`.
The live signature (as of this research) is
`(conn, tf, regime_label, training_window_end, existing_keys, config, tracer, run_ts, rng, feature_status_map)`
— it takes a frozen `config: ICEngineConfig` object (not `apr: dict`) and a `rng: np.random.Generator`
(circular block bootstrap CI, Component A/todo 091, added Phase 143.1) that the plan doc's version
predates entirely. A literal patch-apply will fail immediately (`TypeError` on call, or silent
`apr` attribute errors).
**Why it happens:** Phase 143.1's Fisher-z bootstrap CI work (todo 091) added the `rng` threading
after the plan doc was written.
**How to avoid:** Add `regime_group: str` and `symbol_list: list[str]` as two *additional*
parameters onto the current signature (not a wholesale signature replacement), and thread
`config` through unchanged (do not revert to a plain `apr` dict — that would itself be a
regression against the Phase 143.1 refactor).
**Warning signs:** `.venv/bin/pytest tests/unit/ -q` failing broadly on `ic_engine` collection
errors after Task 5 is a signal the diff was applied against the wrong baseline.

### Pitfall 3: `_persist_corpus_results` gate uses `equity_model_enabled` as a plain bool
**What goes wrong:** Line 2034's `if equity_model_enabled and corpus_cs_rows:` gate still needs
to fire whenever *any* group is enabled, not specifically "equity." A naive rename to
`regime_group_enabled` without checking every call site risks missing one and leaving a stale
`equity_model_enabled` reference that silently no-ops the cross-sectional write path once
`equity_model_enabled` (the specific APR flag, migration 174) is retired/superseded by the new
`alpha.regime.groups` JSON.
**How to avoid:** After Task 5, run `grep -n "equity_model_enabled" services/ic_engine.py` and
verify every remaining hit is either (a) intentionally kept as a narrow "is the equity group among
enabled_groups" check, or (b) generalized to `bool(enabled_groups)`. Do not leave the old
`alpha.regime.equity_model_enabled` APR key as a second, independent kill-switch alongside the
new `alpha.regime.groups[].enabled` flag — that's two sources of truth for the same on/off
decision (a discretion call for the planner: recommend deprecating
`alpha.regime.equity_model_enabled` in favor of `alpha.regime.groups` entirely, since keeping both
risks them drifting out of sync).

### Pitfall 4: No `regime_group` column on `feature_ic_scores`
**What goes wrong:** `feature_ic_scores`'s PK is `(feature_name, symbol, tf, regime, lookahead_bars, training_window_end)`
— there is no `regime_group` column. Group identity is implicit in `regime_label` string
uniqueness across groups (equity uses `{low,mid,high}_{bear,neutral,bull}`; rates uses
`{steep,flat,inverted}_{wide,tight}` — currently non-overlapping by construction). If a future
group's `build_tiers()` ever reuses a tier name from another enabled group, two semantically
different regimes would collide under the same `regime` string in `feature_ic_scores`, corrupting
downstream ensemble eligibility queries silently.
**Why it happens:** The plan doc doesn't add a `regime_group` column to `feature_ic_scores` — it
relies on label-vocabulary uniqueness as an implicit invariant, not an enforced one.
**How to avoid:** Not a blocker for this phase (equity/rates/commodity/fx label vocabularies are
already non-overlapping by design), but the planner should note this as a documented invariant
(e.g., a comment in the migration or `_assign_labels`) rather than leave it silently assumed. Not
severe enough to warrant a schema change in this phase — flagged as a known constraint for future
group additions.

### Pitfall 5: Migration internal comment vs. filename number drift
**What goes wrong:** `production/migrations/228_instrument_tag_vocabulary_v2.sql`'s internal SQL
comment header reads `"-- Migration 121: instrument tag vocabulary v2"` — a leftover from a prior
renumbering pass that was never corrected. This confirms migration renumbering has happened
multiple times in this repo's history without every internal comment being kept in sync.
**How to avoid:** When creating `229_regime_group.sql`, ensure the internal `-- Migration 229: ...`
comment matches the filename number exactly at creation time — don't copy the plan doc's `-- Migration 189: ...`
header verbatim.

### Pitfall 6: Pipeline script edit is smaller than the plan doc assumes
**What goes wrong:** The plan doc's Task 6 assumes a 6-step pipeline needing a new step 4
insertion (shifting old steps 4-6 to 5-7). The live `scripts/ops/corpus/ops_corpus_pipeline_run.sh`
is already an **8-step** pipeline (`feature_factory` → `regime_writer` → `forward_return_writer`
→ `equity_regime_model` → `ic_engine` → `ic_shrinkage` → `ensemble_trainer` → `alpha_publisher`),
and `equity_regime_model` already occupies its own step-4 slot immediately before `ic_engine`.
**How to avoid:** Task 6 reduces to a same-slot script-name swap at lines ~323-324:
```bash
# Before:
run_step 4 "equity_regime_model" \
    "$PYTHON" services/equity_regime_model.py
# After:
run_step 4 "cross_sectional_regime_model" \
    "$PYTHON" services/cross_sectional_regime_model.py
```
No step renumbering, no banner/count update (`printf " Step %d/8 — %s\n"` is already correct).

## Code Examples

### Verified live `ic_engine.py` `asset_class` touch points (all 4, exact line numbers as of this research)
```
$ grep -n "asset_class" services/ic_engine.py
503:                    "SELECT count(*) FROM market_regimes WHERE asset_class='equity' AND tf=%s",
1559:            WHERE asset_class = 'equity'
2722:                            "SELECT ts, regime_label FROM market_regimes WHERE asset_class='equity' AND tf=%s",
2834:                            "WHERE asset_class='equity' AND tf=%s ORDER BY regime_label",
```
Source: live grep against `services/ic_engine.py`, 2026-07-12.

### Current `_assert_prerequisites` signature (line 461) — extend, don't replace
```python
# Live, current (services/ic_engine.py:461-462):
def _assert_prerequisites(
    conn: Any, tfs: list[str] | None = None, equity_model_enabled: bool = True
) -> None:
```
The plan doc's Task 5 Step 5 replaces this with a `group_configs: list[dict] | None` param —
that intent is correct; apply it as an *additional/replacement* param on the current 3-arg
signature, not against the plan doc's already-stale expectation of the function's prior shape.

### Confirmed reusable APR loading pattern (unaffected by drift)
```python
# services/_batch_utils.py:38 — verified live, matches plan doc's usage exactly
def load_config_service_sync(conn: Any) -> ConfigService: ...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `ic_engine.py` config as loose dict (`_load_apr`) | Frozen `ICEngineConfig` dataclass, `from_apr()` classmethod | Phase 143.1 (2026-07-02 through 07-12 window) | Task 5's config-loading diffs must target `ICEngineConfig`, not a dict |
| Cross-sectional IC computed with a fixed per-worker seed only | Deterministic bootstrap RNG threaded through every compute call (`_derive_worker_rng_seed`) | Phase 143.1-01 (todo 091, Component A) | `_compute_cross_sectional_tf` now requires an `rng` param the plan doc's version doesn't have |
| `equity_regime_model.py` used a naive whole-series rank | Causal bisect-based expanding rank | Phase 141 P0-T2 (V1 look-ahead fix, ~2026-06-29) | `breadth_vol.py` must port this, not the plan doc's rank-based code |
| 6-step corpus pipeline | 8-step pipeline (added `ic_shrinkage` E1 step + already-present `equity_regime_model` at step 4) | Multiple phases since 2026-07-01 | Task 6's edit is a same-slot swap, not an insertion |

**Deprecated/outdated:**
- The plan doc's literal `_load_apr` dict pattern — superseded by `ICEngineConfig`.
- The plan doc's `breadth_vol.py compute()` rank implementation — superseded by the causal
  bisect rank already live in `equity_regime_model.py`.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `curve_credit.py`'s window params (`curve_window`, `credit_window`, default 60) are intentionally left as literal bar counts rather than `_tf_window`-scaled, since it's a brand-new signal with no prior bug-fixed precedent to match | Pattern 5 / Architecture | If wrong, the rates group's regime tiers would be miscalibrated per-TF the same way breadth_vol would have been — low practical risk since `curve_window`/`credit_window` are `[conventional]`-tagged and subject to the same future calibration path as everything else in this phase, but worth an explicit planner decision rather than silent inheritance of the plan doc's choice |
| A2 | `job` label for `cross_sectional_regime_model.py`'s D-06 `job_completed_total` emission should be `"cross-sectional-regime-model"` even though no systemd unit exists to match a `%n` suffix against | Project Constraints | Low risk — this only affects an observability label's exact string; verified no systemd unit exists for the sibling service (`equity_regime_model.py`) it replaces, so there's no unit-name precedent being violated |
| A3 | The plan doc's duplicate "Task 6" numbering (two sections both titled "## Task 6" — "Pipeline Update + Deprecate" and "commodity_momentum_ts Signal Module") is a doc-authoring artifact, not a signal that two different things are meant to happen under one task | File Map / plan doc structure | If the planner treats these as literally task-numbered dependencies, sequencing could get confused; low risk since the actual task CONTENT is unambiguous even if the numbers collide |

**If this table is empty:** N/A — see entries above. All three are low-risk documentation/design
decisions, not verified-vs-assumed factual claims about the codebase's current state (which are
all tagged `[VERIFIED]` inline above via direct grep/read against the live files).

## Open Questions

1. **Should `_build_symbol_regime_class` logic be shared between `cross_sectional_regime_model.py`
   and `ic_engine.py`, or intentionally duplicated?**
   - What we know: the plan doc's Task 4 (`_resolve_group_symbols` in the dispatcher) and Task 5
     (`_build_symbol_regime_class` in `ic_engine.py`) implement functionally near-identical
     tag-prefix-matching logic, once as "which symbols belong to group G" (dispatcher) and once as
     "which group does symbol S belong to" (ic_engine) — these are inverse views of the same
     routing table.
   - What's unclear: whether importing one from the other (e.g., `ic_engine.py` imports
     `_resolve_group_symbols` from `cross_sectional_regime_model.py` and derives the inverse
     mapping) is cleaner than the plan doc's two independent implementations, given
     `AmbiguousRegimeGroupError` only needs to exist on the `ic_engine.py` side (the dispatcher
     doesn't need to detect ambiguity the same way — it resolves one group's peers at a time, not
     a global routing table).
   - Recommendation: keep them separate as the plan doc specifies (both are already unit-tested
     independently in the plan doc) unless the planner judges the duplication meaningfully
     violates DRY — this is a minor code-organization call, not a correctness risk.

2. **Should `alpha.regime.equity_model_enabled` (migration 174, the current live kill-switch) be
   retired in favor of `alpha.regime.groups[].enabled` entirely, or kept as a secondary gate?**
   - What we know: keeping both risks the two flags drifting out of sync (Pitfall 3).
   - What's unclear: whether any other live consumer besides `ic_engine.py` reads
     `alpha.regime.equity_model_enabled` directly (a grep before Task 5 should confirm this is
     safe to retire).
   - Recommendation: grep for `equity_model_enabled` and `alpha.regime.equity_model_enabled`
     project-wide before deciding; if `ic_engine.py` is the sole consumer, retire it as part of
     Task 5 rather than carrying two overlapping flags forward.

3. **D-05's acceptance-gate query — exact SQL not pre-registered anywhere yet.**
   - What we know: `docs/research/fable-2026-07-07-phase144-conditioning-decision.md` §6 Input 1
     says to pre-register "the same per-symbol query shape as SPY's Step 2(c)" from
     `.planning/todos/deferred/026-hmm-regime-audit-optimization.md`, comparing TLT's per-symbol
     HMM regime separation (`feature_ic_scores` rows with `regime_scope='symbol_hmm'`) against
     the new `rates` cross-sectional group's separation (`regime_scope='cross_sectional'`,
     `regime_group`-equivalent label set from the `rates` group), using the existing 0.01/0.05
     gap bands.
   - What's unclear: the exact SQL wasn't written out in either todo 026 or the Fable decision
     doc — only the query *shape* (per-symbol, not pooled) and the comparison target (TLT vs.
     rates group) are specified.
   - Recommendation: the plan's final acceptance-gate task should write this query fresh against
     `feature_ic_scores.regime_scope` + `regime` columns, filtering `symbol='TLT'` for the
     per-symbol side and `symbol='POOLED' AND is_pooled=true` for the cross-sectional `rates`
     group side (both already exist as columns per the live schema check in this research), rather
     than assuming a pre-existing query file to reuse.

## Environment Availability

Skipped — this phase has no external dependencies beyond the already-live PostgreSQL/TimescaleDB
instance and Python packages already vendored in `.venv`. All infrastructure (`ConfigService`,
`JOB_COMPLETED_TOTAL`, `init_otel_providers`) was `[VERIFIED]` present and importable via direct
grep against the live source tree (see Don't Hand-Roll section).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (`.venv/bin/pytest`) |
| Config file | none dedicated — project-wide `tests/unit/` convention |
| Quick run command | `.venv/bin/pytest tests/unit/test_regime_signals_breadth_vol.py tests/unit/test_regime_signals_curve_credit.py tests/unit/test_cross_sectional_regime_model.py tests/unit/test_ic_engine_routing.py -v` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |

### Phase Requirements → Test Map
No formal `REQ-XX` IDs exist for this phase (phase_req_ids null). Mapping instead to the plan
doc's own Task structure, since that's this phase's actual acceptance surface:

| Task | Behavior | Test Type | Automated Command | File Exists? |
|------|----------|-----------|-------------------|-------------|
| Task 1 (migration) | `market_regimes.regime_group` column exists, data preserved | manual SQL verification | `psql ... -c "\d market_regimes"` | N/A (SQL, not pytest) |
| Task 2 (breadth_vol) | Causal rank property (no look-ahead), TF-window scaling correctness | unit | `.venv/bin/pytest tests/unit/test_regime_signals_breadth_vol.py -v` | ❌ Wave 0 — **also needs a new causal-rank regression test not in the plan doc's original test file** (mirror `test_vix_pct_rank_causal_property` from `tests/unit/services/test_equity_regime_model_causal.py`) |
| Task 3 (curve_credit) | Signal direction correctness, tier bucketing | unit | `.venv/bin/pytest tests/unit/test_regime_signals_curve_credit.py -v` | ❌ Wave 0 (plan doc's tests are complete as written) |
| Task 4 (dispatcher) | Group config parsing, symbol resolution, label assignment | unit | `.venv/bin/pytest tests/unit/test_cross_sectional_regime_model.py -v` | ❌ Wave 0 |
| Task 5 (ic_engine routing) | Symbol→group routing, ambiguity detection, unrouted-symbol exclusion | unit | `.venv/bin/pytest tests/unit/test_ic_engine_routing.py -v` | ❌ Wave 0 |
| Task 5 (ic_engine cross-sectional pooling fix) | `symbol_list` filter correctly scopes pooled IC to peer group only | **integration/manual** — plan doc has no unit test for this specific SQL fix | `psql` row-count spot check post-run (plan doc's Verification §1-2) | N/A — requires live DB with populated `market_regimes` for both groups |
| Acceptance gate (D-05) | TLT vs. `rates` group separation gap, bands 0.01/0.05 | manual SQL analysis, queued behind 143.1-07 | ad hoc SQL against `feature_ic_scores` (query not yet written, see Open Question 3) | N/A |

### Sampling Rate
- **Per task commit:** run that task's own new test file (`tests/unit/test_regime_signals_*.py`,
  `tests/unit/test_cross_sectional_regime_model.py`, `tests/unit/test_ic_engine_routing.py`).
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -q` (full suite — must stay green; 5695 passing
  as of Phase 143 completion, 1 pre-existing unrelated failure tolerated).
- **Phase gate:** full suite green + the plan doc's own Verification section (dry-run routing log
  checks, `market_regimes` label-distribution spot check) + D-05's acceptance gate (queued behind
  143.1-07).

### Wave 0 Gaps
- [ ] `tests/unit/test_regime_signals_breadth_vol.py` — covers Task 2, **plus one new test not in
      the plan doc**: a causal-rank regression test asserting a later-window value change does not
      alter an earlier rank (mirror `test_vix_pct_rank_causal_property`).
- [ ] `tests/unit/test_regime_signals_curve_credit.py` — covers Task 3, plan doc's version is complete.
- [ ] `tests/unit/test_cross_sectional_regime_model.py` — covers Task 4, plan doc's version is complete.
- [ ] `tests/unit/test_ic_engine_routing.py` — covers Task 5's `_build_symbol_regime_class`, plan
      doc's version is complete.
- [ ] No test framework install needed — pytest already configured and green project-wide.

## Security Domain

Not applicable — `security_enforcement` config key not checked, but this phase has zero
authentication/authorization/network-input surface (internal batch pipeline over a
locally-trusted DB connection, no user input, no external API). Omitting per the section's own
scope (ASVS categories target request-handling/auth surfaces this phase does not have).

## Sources

### Primary (HIGH confidence — direct file reads/greps against the live repo, 2026-07-12)
- `docs/plans/2026-07-01-cross-sectional-regime-model.md` (2687 lines, read in full) — the
  canonical implementation plan this phase executes.
- `services/ic_engine.py` (3020 lines, targeted reads of all `asset_class`/`mr_dict`/
  `ICEngineConfig`/`main()` regions) — ground truth for what has drifted since the plan doc.
- `services/equity_regime_model.py` (full read of `_compute_vix_pct_rank`, `_tf_window`,
  `_compute_breadth_fraction`) — ground truth for what Task 2's breadth_vol.py must port.
- `scripts/ops/corpus/ops_corpus_pipeline_run.sh` (targeted read of steps 1-5) — ground truth for
  Task 6's actual scope.
- `production/migrations/` directory listing — ground truth for next-free migration number (229).
- Live PostgreSQL queries (`\d market_regimes`, `\d feature_ic_scores`, `instrument_tags` tag
  census, `config_state` APR key census) via `psql` — ground truth for schema state and tag
  vocabulary coverage.
- `.planning/phases/144-cross-sectional-regime-model-regime-group-planned/144-CONTEXT.md` — locked
  scope decisions from `/gsd:discuss-phase`.
- `docs/research/fable-2026-07-07-phase144-conditioning-decision.md` — acceptance-gate protocol
  and falsifiers (F1-F5).
- `tests/unit/services/test_equity_regime_model_causal.py` — confirms the causal-rank fix was a
  deliberate, tested Phase 141 P0-T2 change, not incidental.

### Secondary (MEDIUM confidence)
- `.planning/todos/deferred/026-hmm-regime-audit-optimization.md` — Step 1/2 query shape and
  band thresholds for the acceptance gate (exact SQL not present, shape is).

### Tertiary (LOW confidence)
None — every claim in this document traces to a direct file read, grep, or live DB query
performed during this research session.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies, entirely internal refactor.
- Architecture: HIGH — every structural claim about `ic_engine.py`'s current shape is a direct
  read against the live 3020-line file, not an inference.
- Pitfalls: HIGH for Pitfalls 1/2/5/6 (directly verified via diff against live files); MEDIUM for
  Pitfalls 3/4 (correctly identified design risks, but the "right" resolution is a planner
  judgment call, not a verified fact).

**Research date:** 2026-07-12
**Valid until:** This research is tightly coupled to `ic_engine.py`'s exact current structure,
which has changed 3 times in the last 2 weeks (Phase 143, 143.1, and ongoing 143.1-07 rebuild
work touch this file). **Re-verify line numbers and `ICEngineConfig` field list against the live
file immediately before executing Task 5** if more than a few days elapse between this research
and plan execution — treat the specific line numbers cited here as a snapshot, not a permanent
contract.
