# Phase 184: Multi-timeframe research inputs - Research

**Researched:** 2026-10-27
**Domain:** research DAG S0 to S8 (`src/intelligence/research/`), kernel registry (`src/intelligence/features/contract/`), causal alignment, E17 battery
**Confidence:** HIGH on current code state and sequencing; MEDIUM on the recommended spec shapes (design choices within Claude's discretion)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Scope and order (owner 2026-10-27)
- Plan now, in parallel with 191 and 186. Execution runs on the rebuilt `feature_vectors` after
  186-27 swaps it in; planning and the align node's code need no rebuilt data.
- `feature_vectors` is the basis of the research layer (owner 2026-09-26, todo 435). Features
  enter books as members of pre-registered families at 5m, 15m, 1h and 1d. No parallel feature
  implementation in research; design D5 revision 3 already says this.
- Todo 435's gap closures are in scope for B1: pin APR window values in the spec at freeze and
  refuse on mismatch; mask warmup to NaN by declared memory; refuse a feature below a pinned
  populated-symbol coverage floor; feature columns as `[t, i]` arrays content-hashed in the
  snapshot; the S3 causality probe covers them.
- HMM-derived columns (`hmm_*`, regime labels) may not enter any family until the 186-26
  rebuild produces clean walk-forward columns (todo 248).
- B8 (economic series through the same causal alignment) needs todo 482 first; todo 482 is
  pending and deferred behind its consumers. B8 is planned as its own plan that names 482 as a
  prerequisite, not silently dropped.

#### Coordination with the research lane (indicagent-5b, 2026-10-27)
- Plans only edit `.planning/phases/184-*` during planning. Code touching
  `src/intelligence/research/` executes only after 5b's go.
- Construction goes through `src/intelligence/research/construction.py`
  `resolve_rule(spec, bars_per_session)`; the runner refuses non-R1 rules for now.
- Attempts record series through S6 (`research_run_series`); selection is `select_books.py`
  with its gates. Build against these, not around them.
- 187-08 adds `HorizonRule` and `book_memory()`; 187-09 adds in-fold signs and calendar refits.
  Both change `book`/`combiner`/`spec.py`. Any 184 plan that touches spec.py's canonical form
  or the combiner is sequenced after 187-09.
- New spec fields go through spec.py's `_OPTIONAL_*_FIELDS`;
  `tests/unit/research/test_spec_hashes_pinned.py` gates the seven recorded hashes.
- 187-15 (`generated_family`) adds point-in-time sector lookups from
  `instrument_classification`. If the align node builds sector or classification inputs, it
  shares that one reader.

#### Project invariants that bind every plan
- `repro_frozen.py` bit-identical after each item (B7, design D7 guard 8).
- Executable targets from `panel.forward_returns` only; compute reads
  `market_data_ohlcv_tradeable`, never the raw table.
- APR for every tunable number; UTC only; no fill (missing is NaN).

### Claude's Discretion
- Plan granularity, wave layout, and test design, within the constraints above.

### Deferred Ideas (OUT OF SCOPE)
- First feature family pre-registration (todo 435 step 4) follows this phase; it is a research
  run, not a phase 184 build item.
</user_constraints>

<phase_requirements>
## Phase Requirements

No IDs were assigned (ROADMAP: "Requirements: TBD"). Derived here from design section 7 (B1-B8), D7 guards and todo 435's gap closures. Plans should cite these.

| ID | Description | Research support |
|----|-------------|------------------|
| MTF-B1a | S0 captures `high` and `low` on request, through the same optional-field mechanism 187-15 adds (`PanelSpec.fields`), never a second one | Finding F4; 187-15 Task 2 |
| MTF-B1b | S0 adds `closes_at` per grid row (UTC, from the NYSE calendar: early closes, both DST transitions, short last 1h bucket); NaT on a row no symbol traded. D7 guard 3 fixtures | `src/intelligence/bars/sessions.nyse_sessions`; Pitfall 3 |
| MTF-B1c | S0 fetches a warmup prefix of the largest member memory before `start`; the scored span is unchanged and the prefix is recorded in the manifest | Pattern 4 |
| MTF-B1d | Intraday 15m and 1h panels read only the derived grid (`vendor = 'derived'`, `kind = '5m_grid'`); S0 refuses any other vendor at those tfs and records the vendor/kind set in the manifest | Verified live: 15m/1h rows are all `derived/5m_grid` back to 2006 |
| MTF-B1e | S0 reads named `feature_vectors` columns at 5m/15m/1h/1d as `[t, i]` float32 arrays on the source tf's grid, content-hashed in the snapshot (todo 435 step 3) | `ic_measure.feature_block_sql` / `measure.ic.map_slots` pattern |
| MTF-B1f | Provenance pin: the spec pins the APR values (and S0 checks the batch `apr_snapshot`) that computed each read column; S0 refuses a row range with no completed `provenance_batch`, with a different APR value, or with mixed `code_key`s (todo 435 2a) | `provenance_batch` schema (verified) |
| MTF-B1g | Warmup mask: S0 sets each column's first `feature_memory_bars()` present rows per symbol (from the symbol's series start) to NaN, idempotent with the rebuild writer's own mask; refuses path-dependent columns (todo 435 2b) | `registry.feature_memory_bars`, `backfill_feature_factory.column_warmup_bars` |
| MTF-B1h | Coverage floor: S0 refuses a column whose populated-symbol coverage over the span is below the spec-pinned floor, computed by `statistics.feature_coverage.feature_tf_quality` (todo 435 2c) | 186-09's shared statistic |
| MTF-B1i | S3 covers feature members: the member transform and the align node pass `causality_probe_array`/`memory_check_array` on the feature input; the stored column's own causality is the registry probe, cited by code key | runner.real_guards; D-27 |
| MTF-B1j | `hmm_*` and regime-label columns (registry origin `regime`) are refused as members unless every covering batch is from the 186-26 rebuild | CONTEXT; todo 248 |
| MTF-B1k | (recommended) CI read boundary for `feature_vectors`, the `market_data_ohlcv` boundary-test pattern (unified design 12.2, "uncounted backtests") | `tests/unit/test_market_data_ohlcv_boundary.py` |
| MTF-B2a | Research kernels under the registry contract: vectorized rolling percentile and rolling max (52-week), parity-tested against `_price_percentile_series_full` / `_high_52w_dist_series_full` after warmup; a rolling-window VWAP deviation kernel (bounded memory) | Finding F6 |
| MTF-B2b | `kernel_source`: runs registry kernels on an S0 panel per symbol over present rows at spec-pinned windows, float32, NaN until declared memory, gap rule pinned | `registry.compute_kernels` |
| MTF-B2c | D7 guard 5: a path-dependent (expanding) kernel is refused by `kernel_source`; a masked kernel emits NaN until its declared memory; research adopts the truncation probe (`features.contract.causality_probe`) for kernel members (D-27 handoff) | causality_probe.py docstring |
| MTF-B3a | `align(src_values, src_avail, dst_avail, max_age_rows)` pure node: per destination row and symbol, latest finite source value with availability `<=` destination close, NaN beyond `max_age_rows` source rows; supports a one-column (market-wide) source | Design D4 |
| MTF-B3b | D7 guard 1: a planted leak routed through `align` (source bar closing after the destination row) is rejected or produces no edge | Design D7 |
| MTF-B3c | D7 guard 2: a daily value on the intraday clock equals the previous session's value on every slot except the last, which carries the same session's value; across a half day and both DST transitions | Design D7 |
| MTF-B4 | Every recorded run's evidence carries each member's IC term structure by lag (lags 1..60 on the daily clock, in-session lags on an intraday clock) on the one-row S1 residual target, with a joint band from the run's own session shifts; nothing reads it; the record states the book's pinned kappa | Finding F7 (glossary vs measure) |
| MTF-B5 | Fixed smoothing menu: an input member (one with `input` set) may pin `smoothing_half_life`, and a member without `input` that sets it is refused at spec load; in {5, 21, 63} sessions (daily clock); the smoother is causal with a declared finite memory that enters book memory | Pattern 6 |
| MTF-B6 | E17 H0 battery cells for persistent predictors (AR(1) at several autocorrelation times, routed through `align` and `kernel_source`); the feature family module exposes `NULL_BATTERY` so `runner.static_gate` admits it | Finding F8 |
| MTF-B7 | After each item: `repro_frozen` bit-identical, `test_spec_hashes_pinned.py` green, `backfill_attempt_series.py --compare-all` all equal, `panel_81fa9178ca4ad603` verifies | Validation section |
| MTF-B8a | (after todo 482) S0 economic block: `economic_series_observation` filtered on `available_at <= K` (knowledge cutoff in the manifest), joined on decision time through `align` with age and per-series max age; refuses rows whose `availability_basis` is not a measured or declared basis | Finding F9 |
| MTF-B8b | (after todo 482) Shift test: every book using the block is rerun with every `available_at` one session later; the delta is recorded with the attempt | `docs/ideas/signal-macro-context-layer.md` |
</phase_requirements>

## Summary

None of B1-B8 exists in the research package today. `Panel` carries `open`, `close`, `volume` only; `snapshot.build_grid` builds float64 arrays from `market_data_ohlcv_tradeable`; `src/intelligence/research/` has zero references to `feature_vectors`; members are dotted-path functions over the S1 residual bar returns array (`member(resid_bar, *, bars_per_session, coverage_floor, **params)`). The dependencies the design waited on have landed. Phase 185's derived 15m and 1h grid is in canonical (`vendor = 'derived'`, `kind = '5m_grid'`, back to 2006-07-06; checked live). Phase 186's kernel registry (`src/intelligence/features/contract/registry.py`: `Kernel`, `compute_kernels`, `feature_memory_bars`, `path_dependent`, a truncation causality probe) and the provenance table (`provenance_batch`, full `apr_snapshot` jsonb per unit) exist. `feature_vectors_v2` (wide, 307 `real` columns, key `(symbol, tf, bar_ts)`) exists but is empty, with zero provenance rows: the 186-26 rebuild has not run. The current 89 GB `feature_vectors` has no provenance and its 1h rows sit on the old defective `:00` grid. Under B1f it can never be read, so all real-data execution waits for 186-27 as the CONTEXT says.

Four findings change how the phase should be planned. (1) 187-15 Task 2 already adds an optional `PanelSpec.fields` with `high`, `low`, `sector_pit` to panel.py, snapshot.py and spec.py. B1a must extend that mechanism, so B1's S0 work is sequenced after 187-15 Task 2. (2) A feature member does not fit today's member contract or `_check_spec`'s memory rule (slot history plus S1 reach). It needs new optional `MemberSpec` fields; spec.py has no `_OPTIONAL_MEMBER_FIELDS` yet, which is a canonical-form change and must come after 187-09 (and 187-10 and 187-15, which also edit spec.py). (3) Adding a kernel to the auto-discovered `kernels/` package adds a stored column: it breaks `test_feature_vectors_v2_schema.py` and the registry/schema equality test, and it touches the rebuild's import closure while 186-26 is live or resumable. B2's research kernels therefore belong in a separate package that `default_registry()` does not discover. (4) The "IC term structure the shrunk ic_engine computes" (`measure.term_structure`) is a cumulative-horizon ladder with in-session horizons only. The glossary's `IC term structure` and design D2 define lag-k ICs on the one-row residual return and explicitly exclude the cumulative ladder. B4 needs a lag-IC function, and `measure` imports `research`, so it must not be imported back. Put it in `src/intelligence/statistics/`.

**Primary recommendation:** Wave 1 builds the pure, new-file pieces that touch no shared research file: the `closes_at` function, the `align` node, the smoother, the research kernels with `kernel_source`, the lag term-structure function, and B6's battery cells. Wave 2, after 187-09 and 187-15 Task 2 and on 5b's go, wires them into spec.py, snapshot.py, panel.py and runner.py with optional fields that leave every recorded hash and frozen output unchanged. B8 is a separate plan blocked on todo 482. Run real data only after 186-27.

## Architectural Responsibility Map

| Capability | Primary tier | Secondary tier | Rationale |
|------------|-------------|----------------|-----------|
| Bars, derived 15m/1h grid | Database (`market_data_ohlcv`, phase 185/191) | - | Data layer owns derivation; research only reads the view |
| Feature values and lineage | Database (`feature_vectors`, `provenance_batch`, phase 186 writer) | - | One implementation; research reads, never recomputes stored columns |
| S0 reads, pins, masks, coverage refusal, content hash | Research S0 (`snapshot.py`, the only research node that reads Postgres) | `statistics.feature_coverage` | Read-only pool, hashed snapshot |
| `closes_at` | Research S0 (pure function over grid + `bars.sessions.nyse_sessions`) | - | Calendar facts, computed once per snapshot |
| Alignment across clocks | Research S2b (new pure module) | - | The only node that sees two clocks (design section 4) |
| Kernel members at pinned windows | Research S2 `kernel_source` | Features registry (contract and kernels) | Same `Kernel` contract; research imports features, never the reverse |
| Smoothing menu | Research S2 (pure) | - | Member transform with declared memory |
| Term structure record | `statistics/` (pure lag IC) | Research runner -> S6 ledger evidence | Feeds nothing; S6 sole writer of `research_run` |
| E17 size check | Research `null_battery*` modules + `scripts/research/e17_null_battery.py` | - | Existing battery driver |
| Economic block | Research S0 (read) + S2b (align) | `economic_series_observation` (writer is todo 480/482's) | Same align node, decision-time join |

## Standard Stack

All internal; no new external packages.

### Core
| Component | Location | Purpose | Why standard |
|-----------|----------|---------|--------------|
| `Panel`, `forward_returns`, `bar_returns`, `save`/`load` | `src/intelligence/research/panel.py` | Panel dataclass and the only target kernel | UD-25; Invariant 1 [VERIFIED: codebase] |
| `build_grid`, `build_panel`, `read_only_pool` | `src/intelligence/research/snapshot.py` | S0 | Read-only, content hashed, oos refusal [VERIFIED: codebase] |
| `store.write/verify/read_array` | `src/intelligence/research/store.py` | Content-hashed array dirs | Hash covers every array and meta.json [VERIFIED: codebase] |
| `KernelRegistry`, `compute_kernels`, `feature_memory_bars`, `discover_kernels(package=)` | `src/intelligence/features/contract/registry.py` | Kernel contract, declared memory, DAG of inputs | D-25/D-26 single source of memory [VERIFIED: codebase] |
| `causality_probe`, `memory_check`, `probe_registry` | `src/intelligence/features/contract/causality_probe.py` | Truncation probe for kernels | D-27 says research adopts it [VERIFIED: codebase] |
| `causality_probe_array`, `memory_check_array`, `integrity` | `src/intelligence/research/guards.py` | S3 over arrays | D-25 split [VERIFIED: codebase] |
| `nyse_sessions(start, end)` | `src/intelligence/bars/sessions.py` | Session open/close UTC with early closes and DST | Same mcal source as the derivation [VERIFIED: codebase] |
| `feature_tf_quality` | `src/intelligence/statistics/feature_coverage.py` | The one coverage definition | Docstring names todo 435's S0 floor [VERIFIED: codebase] |
| `timing_test`, `null_battery.NullScenario`, `e17_null_battery.py` | research + scripts | E17 statistic and H0 battery | E17 adopted [VERIFIED: codebase] |
| `numpy`, `pandas`, `pandas_market_calendars` | venv | Arrays, tz conversion, calendar | Already used by S0 and bars [VERIFIED: codebase imports] |

### Supporting
| Component | Location | When to use |
|-----------|----------|-------------|
| `measure.ic.map_slots` / `scatter_features` | `src/intelligence/measure/ic.py` | Pattern for long-form rows to grid. Research must not import `measure` (measure imports research); copy the 20-line exact-match scatter into research or move it to a shared Ring 1 module |
| `ic_measure.feature_block_sql` pattern | `services/ic_measure.py` | Column-named SELECT with `psycopg.sql.Identifier`, never `SELECT *` |
| `statistics.ic_math.compute_ic_vectorized`, `portfolio.average_ranks` | statistics / research | Rank IC per lag for B4 |
| `evaluate.session_shifts` | `src/intelligence/research/evaluate.py` | Shift set for B4's joint band |

### Alternatives considered
| Instead of | Could use | Tradeoff |
|------------|-----------|----------|
| Separate research-kernel package | Edit `kernels/price.py` in place with vectorized bodies | Renames every price-kernel unit's code key and forbidden while 186-26 is live or resumable; only after 186-27 as its own recompute. Deferred |
| Lag IC in `statistics/` | `measure.term_structure` | Wrong object (cumulative horizons), and research importing measure makes a package cycle |
| One snapshot dir per tf with a parent manifest | All tfs' arrays in one store dir | One dir is simpler but a 5m source makes it huge; recommend child dirs whose hashes the book-clock panel manifest lists (one root hash covers all) |

**Installation:** none.

## Package Legitimacy Audit

No external packages are installed by this phase. slopcheck not run (nothing to check).

| Package | Registry | Disposition |
|---------|----------|-------------|
| (none) | - | - |

**Packages removed:** none. **Packages flagged:** none.

## Architecture Patterns

### System architecture diagram

```
market_data_ohlcv_tradeable (1d; 5m; derived 15m/1h)      feature_vectors (+ provenance_batch)      economic_series_observation
            |                                                     |                                        | (B8, after 482)
            v                                                     v                                        v
 S0 snapshot (read-only pool) --------------------------------------------------------------------------------------------
   per tf: grid -> Panel(open, close, volume [+high, low]) + closes_at (calendar) + warmup prefix
   per feature column: provenance pin check -> refuse | read [t,i] float32 -> warmup mask -> coverage floor -> refuse | keep
   per series: available_at <= K -> [t] values + available_at
   -> content-hashed child dirs; book-clock manifest lists child hashes (one root hash)
            |
            v
 S1 target on the book clock: panel.forward_returns -> residual (unchanged)
            |
            v
 S2 members per source tf:  resid_bar member (today) | stored feature column | kernel_source(panel_tf, pinned windows)
            |                                 optional smoothing (menu 5/21/63) on the book clock
            v
 S2b align(src_values, src_avail = closes_at | available_at, dst_avail = book closes_at, max_age_rows)  [only node with two clocks]
            |
            v
 S3 guards (causality/memory over the member input incl. align; registry truncation probe for kernels)
            |
            v
 S7 combiner -> R1 construction -> S8 E17 timing test (memory L from book_memory)
            |                                 \
            v                                  -> term structure by lag with joint shift band (record only)
 S6 ledger (sole writer): research_run evidence + research_run_series
```

### Recommended file layout (new files marked +)

```
src/intelligence/research/
  clock.py            + closes_at(panel_timestamps, tf, bps) pure; NaT rows
  align.py            + align(...) pure; one-column broadcast
  smoothing.py        + fixed menu, FIR causal smoother, smoothing_memory_sessions()
  kernel_source.py    + panel -> kernel outputs at pinned windows (imports features.contract)
  feature_inputs.py   + S0 feature read helpers: provenance check, warmup mask, coverage refusal (pure parts)
  families/features.py + member functions over an aligned feature input; NULL_BATTERY
  null_battery_persistent.py + B6 scenarios (AR(1) at tau, aligned and kernel predictors)
  panel.py, snapshot.py, spec.py, runner.py, guards.py   (wiring, wave 2)
src/intelligence/features/research_kernels/   + Kernel tuples NOT discovered by default_registry()
src/intelligence/statistics/term_structure_lag.py + lag IC and sup-band, pure
tests/unit/research/test_clock.py, test_align.py, test_smoothing.py, test_kernel_source.py,
  test_feature_inputs.py, test_term_structure_lag.py, test_panel_mtf_fields.py, test_runner_feature_members.py
tests/unit/intelligence/test_research_kernels.py (parity + causality + memory)
```

### Pattern 1: optional fields that leave every hash unchanged
**What:** every new spec field defaults to None and is dropped from the canonical form while unset; every new Panel array defaults to absent and is written only when present.
**When:** every spec.py, panel.py, snapshot.py change in this phase.
```python
# Source: src/intelligence/research/spec.py (current)
_OPTIONAL_PANEL_FIELDS = ("transform", "members_universe", "total_return")
def _family_dump(model: FamilySpec) -> dict:
    data = model.model_dump(mode="json")
    _drop_unset(data, "panel", _OPTIONAL_PANEL_FIELDS)
    _drop_unset(data, "scoring", _OPTIONAL_SCORING_FIELDS)
    return data
```
Members are a list, so the planner adds `_OPTIONAL_MEMBER_FIELDS` and drops unset keys from each `data["members"][i]`. `panel.save` already writes `extra` arrays without changing old bytes; the B1 arrays follow that path. 187-15 states the same contract for its `fields`.

### Pattern 2: member input generalization (recommended spec shape)
Keep the member contract and the `signal:` path, and generalize only the first argument: the runner passes the member's declared input, which is the S1 residual bar returns (today) or the aligned feature or kernel array.
```yaml
members:
  - name: px_pct_252
    signal: src.intelligence.research.families.features.centred   # rank of the input, sign applied
    params: {}
    slot_history_sessions: 1        # member's own reach over its input
    declared_memory_rows: ...       # runner-derived rule (see Pattern 4)
    input:                          # NEW optional block (absent = resid_bar, today's behavior)
      kind: feature                 # feature | kernel
      column: price_percentile_slow # registry output name
      tf: 1d
      max_age_rows: 1               # source rows
      config_projection_hash: <64 hex>   # hash of the FeatureFactoryConfig projection S0 checks against the batches' apr_snapshot (superseded the dict pin, 184-REVIEWS row 15)
    smoothing_half_life: 21         # NEW optional, Literal[5, 21, 63]
```
`_check_book` requires families to agree on `panel` (the book clock), so the source tf lives on the member, not the panel.

### Pattern 3: the align node
```python
# Design D4; pure, no I/O
def align(src: np.ndarray, src_avail: np.ndarray, dst_avail: np.ndarray, max_age_rows: int) -> np.ndarray:
    """src [ns, m] or [ns, 1]; src_avail [ns] datetime64 UTC (closes_at or available_at, NaT allowed);
    dst_avail [nd] datetime64 UTC (book clock closes_at, NaT rows give NaN). Returns [nd, m]."""
    # 1. order = rows with finite src_avail; cand[t] = searchsorted(src_avail[order], dst_avail[t], side="right") - 1
    # 2. per symbol: last_finite[r] = index of latest finite src row <= r (forward max of where(finite, idx, -1))
    #    an index, never a value copy into the source array
    # 3. value[t, j] = src[last_finite[cand[t], j], j] if cand[t] - last_finite[cand[t], j] <= max_age_rows else NaN
```
Ages count source rows (sessions for a 1d source), so a weekend never ages a value. `<=` is causal because entry is the next open (D4). The output is NaN wherever no candidate exists; nothing is filled. A latest-finite lookup bounded by `max_age_rows` is the rule the design states; the age bound is what keeps it from being a carry-forward fill.

### Pattern 4: memory accounting (one function, fed to 187-08's `book_memory`)
- Feature member memory in book-clock sessions = ceil(`feature_memory_bars(column, config)` / source bars per session) + `max_age_rows` (in source sessions) + smoothing memory + the member's own `slot_history_sessions`.
- `kernel_source` memory = `registry.effective_memory_bars` (raises on path-dependent).
- Warmup prefix S0 fetches = the largest of these over members, converted to the source tf.
- `_check_spec`'s rule today (`declared_memory_rows == slot history + S1 reach`) holds for resid_bar members only. Feature members need their own branch, with one function computing their declared rows. 187-08's `book_memory(member_sessions, ...)` consumes it, and nothing computes L by hand.

### Pattern 5: provenance pin check (B1f)
For each (tf, column) read: select the `provenance_batch` rows with `status = 'completed'`, `target_table IN ('feature_vectors_v2', 'feature_vectors')` (186-27 keeps old rows named `_v2`), the tf, overlapping range and symbol membership. Refuse when any (symbol, range) of the span has no covering completed batch, when the pinned `config_projection_hash` differs from the hash of the batches' `apr_snapshot` projection, or when the covering batches carry more than one `code_key`. Record the `batch_key` set, `code_key`, `apr_hash` and `input_digest`s in the snapshot manifest, so the content hash covers them.

### Pattern 6: smoothing menu (B5)
EWMA at half-life h with weights `a(1-a)^k`, `a = 1 - 2^(-1/h)`, truncated at the declared memory where the impulse response falls below 1e-4 of peak (the `signals.py` convention): `k_max = ceil(h * log2(1e4))`, which is 67, 280 and 838 sessions for 5, 21 and 63. Implement it as a finite FIR over the trailing `k_max + 1` rows, renormalized over finite inputs and NaN where the current input is NaN. A recursion never decays to zero, and `memory_check` would then measure past the declaration. The menu values are a design constant (APR-exempt, like `MEMORY_TOLERANCE`), validated by a `Literal[5, 21, 63]`.

### Anti-patterns to avoid
- Recomputing a stored feature in research (D5): `kernel_source` is only for windows the table does not carry.
- Using `feature_vector_persistence._compute_bar_close_ts` (bar_ts + tf length) as availability: it is wrong for the short 15:30 to 16:00 1h bucket and half days. Use S0's `closes_at`.
- Importing `src.intelligence.measure` from research (measure imports research: a package cycle).
- Importing research from `src/intelligence/features/` (puts research files into the rebuild's import closure; causality_probe.py docstring).
- Float64 5m feature arrays at the full universe (Pitfall 6).
- A tf x horizon x regime grid or per-family horizon lists (design section 6).

## Don't Hand-Roll

| Problem | Don't build | Use instead | Why |
|---------|-------------|-------------|-----|
| Session open/close, half days, DST | A holiday list or fixed 16:00 | `bars.sessions.nyse_sessions` | Same mcal source as the derivation |
| Feature memory | Per-member constants | `registry.feature_memory_bars` / `effective_memory_bars` | D-26 single source; path-dependent raises |
| Running kernels | A research copy of feature code | `registry.compute_kernels` over a combined registry | One implementation (D5) |
| Kernel causality | NaN-replacement probe for kernels | `features.contract.causality_probe` truncation | Catches series-length dependence (D-27) |
| Coverage | A new ratio | `statistics.feature_coverage.feature_tf_quality` | One definition (186-09) |
| Target | Any forward return | `panel.forward_returns` via `transforms` S1 | UD-25 |
| Snapshot hashing | Ad hoc digests | `store.write/verify` | Existing verify path in `_load_panel` |
| Shift set | New shift logic | `evaluate.session_shifts` | Same shifts as the diagnostic |
| H0 size checks | A new driver | `scripts/research/e17_null_battery.py --battery <module>` | Takes any module with `scenarios()`, `simulate()`, `DIAGNOSTIC_CELLS` |

## Common Pitfalls

### Pitfall 1: shared-file collisions with phase 187
**What goes wrong:** 184 and 187 edit spec.py, panel.py, snapshot.py, runner.py, guards.py, signals.py and null_battery.py concurrently.
**Verified file map (187 plans' `files_modified`):** 08 spec/book/runner/evidence/null_battery; 09 combiner/spec/runner/book/evidence; 10 spec/ledger/runner; 11 recipe/ledger/runner; 13 ledger; 14 combiner/runner/ledger; 15 grammar/spec/panel/snapshot/recipe; 18 runner/signals/guards (rename `SignalSource` to `Predictor`, `signals.py` to `predictors.py`, explicitly "last plan so that no earlier plan rebases across a rename").
**How to avoid:** the wave 1 plans create new files only. Wiring plans depend on 187-09 (spec canonical form, combiner), 187-15 Task 2 (`PanelSpec.fields`, Panel optional arrays) and 187-08 (`book_memory`, `NullScenario` extension). Land the wiring before 187-18 so the rename sweeps 184's code, or after it using `Predictor`. B5 "on `SignalSource`" really belongs on `MemberSpec`: the runner path does not use `SignalSource` (only `run_guards` and repro_frozen's tsmom do).

### Pitfall 2: spec hashes and frozen outputs
**What goes wrong:** a new `MemberSpec` field without `_OPTIONAL_MEMBER_FIELDS` moves all seven pinned hashes. A Panel dtype change moves repro_frozen.
**How to avoid:** optional fields only; new intraday arrays float32; existing `open`, `close`, `volume` keep float64 (section 5). Run the B7 trio after every commit.

### Pitfall 3: `closes_at` traps
- The 1h grid's last bucket is 15:30 to 16:00 (verified: derived 1h has 7 rows per full session). Its close is the session close, not start + 60 minutes.
- Half days close at 13:00 ET, and the 12:30 1h bucket closes at 13:00.
- IBKR answered some early-close days with bars to 16:00 ET, and 2006-12-27 opens at 14:30 UTC against the calendar's 14:32 (bars/selection.py docstring). A 5m bar after the calendar close must be refused or counted, never given a `closes_at` past the session close.
- 1d `bar_ts` is the session date at 00:00 UTC in both bars and features (verified). Its `closes_at` is that session's close from the calendar.
- A row no symbol traded gets NaT, and align treats NaT destination rows as NaN output.

### Pitfall 4: the current `feature_vectors` is unreadable by design
It has no provenance rows, and its 1h stamps sit on the old `:00` grid (SPY 2024-03-01 1h stamps 15:00 to 20:00 UTC, verified), so they would not match the derived 14:30-anchored grid anyway. B1f refuses it. Write every test synthetic; real reads wait for 186-27. Expect HMM columns and features computed with since-changed APR values to fail the pin check (unified design 12.1).

### Pitfall 5: research kernels must not create columns
`kernels/` modules are auto-discovered. A new public output there fails `tests/unit/intelligence/test_feature_vectors_v2_schema.py` and the owned/unowned equality in `test_kernel_registry.py`, and it also changes what the rebuild writes. Put B2 kernels in a package `default_registry()` never scans, and build the combined registry for `kernel_source` with `KernelRegistry.from_kernels(default.kernels + research.kernels, default.external_inputs)`, so a research kernel may consume stored outputs.

### Pitfall 6: memory and size
`build_grid` allocates float64 (section 5). Rows from the rebuild ruling (186-26: 1,502 names at 5m, 15m, 1h, 1d): a 5m column over 2016 to 2025 is about 196k rows x 1,502 = 295M cells, 1.2 GB in float32 and 2.4 GB in float64, per column. For a daily book with a 5m member, S0 must read per symbol chunk, align inside S0's pure step, and keep only the book-clock array plus the source digest. The S3 probe of that member then runs on a bounded sub-panel, the way S1's probe does (`guards.s1_probe_sessions`). The 186-07 decision kept only `ret_autocorr_1` and `sweep_detected` at 5m [VERIFIED: 186-07-SUMMARY]; 186-26's plan text says the 2026-10-09 universe ruling widens the 5m name set to all 1,502 names. Confirm the 5m column set at execution.

### Pitfall 7: fingerprinted runs and the import freeze
Do not edit research modules while a fingerprinted research run (family 2 evidence run, 187-03 backfill replays, 187-05 battery) is live or resumable. Do not edit `registry.py`, `kernels/*`, `feature_factory.py` or anything the rebuild imports while 186-26 is live or resumable. New files are safe; edits to existing ones are not.

### Pitfall 8: smoothing and long memories eat the tested span
E17 drops sessions until `min_history_sessions` exist below `s - L`. A 63-session half-life alone gives 838 sessions of memory, and a 52-week feature adds 252. On a 2016 to 2025 span (about 2,500 sessions) that removes a third or more of the tested sessions, and the warmup prefix grows too. B6 must report size and the tested-session count at these L values. Disclose the power cost in the family pre-registration, not here.

### Pitfall 9: the design says E16, the code runs E17
D6 and B6 name E16. The runner's decision statistic is E17 (`timing.timing_test`, memory-lagged cell mean), with E16 superseded for real runs (`_check_spec_tree` refuses non-E17 specs). B6 runs E17 cells.

### Pitfall 10: VWAP and volume nulls
The tradeable view nulls volume for kinds `venue` and `fallback` (1d), so a rolling VWAP is NaN there, which is correct. Count those rows in the manifest rather than treating them as a coverage bug.

## Code Examples

### Reading named feature columns (pattern from ic_measure)
```python
# Source: services/ic_measure.py feature_block_sql
sql.SQL(
    "SELECT {cols} FROM {table} WHERE tf = %s AND symbol = ANY(%s) "
    "AND bar_ts >= %s AND bar_ts < %s ORDER BY bar_ts, symbol"
).format(cols=sql.SQL(", ").join([sql.Identifier("symbol"), sql.Identifier("bar_ts"),
                                   *map(sql.Identifier, names)]),
         table=sql.Identifier(table))
```
S0 uses asyncpg (the read-only pool). Build the column list only from registry output names (an allow-list), never from spec text passed straight through.

### Kernel memory and path dependence
```python
# Source: src/intelligence/features/contract/registry.py
reg.is_path_dependent(output)                 # refuse as a member (D5 bounded memory)
feature_memory_bars(output, config, reg)      # raises KernelRegistryError if path dependent
compute_kernels(reg, inputs, config, outputs=[...])  # inputs: ts (int64 UTC ns), open, high, low, close, volume
```

### Rebuild warmup mask (the rule S0 repeats idempotently)
```python
# Source: services/backfill_feature_factory.py (column_warmup_bars and the row builder)
warmup = warmups.get(name, 0)
if warmup:
    column[: min(warmup, n)] = np.nan   # counted from the symbol's series start
```

### Joint band for the lag term structure (B4)
For each shift s in `session_shifts(n, bps, min_shift, memory)`: compute the curve `IC_k(s)` for k in 1..K on the alpha shifted by s against the unshifted residual target. Band = the 95th percentile over s of `max_k |IC_k(s)|`. Record the observed curve, the band, the shift count and K. Nothing in the run reads it.

## State of the Art

| Old approach | Current approach | When changed | Impact |
|--------------|------------------|--------------|--------|
| D5 rev 2: research recomputes features | S0 reads rebuilt `feature_vectors` by provenance | 2026-09-26 (todo 435, rev 3) | B2 shrinks to research kernels + `kernel_source` |
| S0 aggregates 5m to 15m/1h | Data layer derives (`derived/5m_grid`) | Phase 185 (UD-25) | B1 only reads and verifies the vendor |
| `forward_returns` table | `panel.forward_returns` kernel | Phase 186 (UD-25) | No target table reads |
| E16 HAC with both-demeaned P&L | E17 memory-lagged cell mean | 2026-09-26 | B6 uses E17 |
| `SignalSource` | `Predictor` (187-18 rename) | Pending 187-18 | Name in new code depends on sequencing |

**Deprecated:** multi-day targets, per-family horizon lists, the `alpha.ic.lookahead.*` ladders (design section 6).

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|-------|---------|---------------|
| A1 | The spec shape in Pattern 2 (member `input` block, `smoothing_half_life`) is the right surface | Patterns | Rework of spec wiring; low, within discretion |
| A2 | The B4 band level (95%, sup over lags) and K = 60 are definitions, not APR keys | Code examples | If the owner wants them pinned per spec, it adds two optional scoring fields |
| A3 | `feature_vectors_v2` keys `bar_ts` like the old table (bar start intraday, session date 00:00 UTC on 1d) | Pitfall 3 | Slot mapping misses rows; caught by a fixture test once the rebuild has rows |
| A4 | The coverage floor is a spec-pinned value, with the live APR `feature.coverage.min_symbol_fraction` recorded in the manifest for disclosure | MTF-B1h | If the owner wants APR to bind, S0 refuses on a spec/APR mismatch instead |
| A5 | Smoothing is daily-clock only in this phase (the menu is in sessions on the daily clock) | Pattern 6 | An intraday-clock family wanting smoothing needs a rule |
| A6 | The rebuild's units cover all columns, so one `code_key` per unit spans every column read | Pattern 5 | If units split columns, the pin check groups by column set |
| A7 | 187-15 Task 2's `fields` literal can be extended with `closes_at` (or `closes_at` is always on for intraday as an `extra` array) without moving 187-15's tests | Pitfall 1 | Coordinate with 5b at execution |

## Open Questions (RESOLVED)

Resolved 2026-10-27 at planning; each resolution is the recommendation below, adopted by the named plan.

1. **Where the lag term structure lives and whether `measure` should change.** RESOLVED: pure function in `statistics/`, `measure` unchanged, naming todo filed (plan 184-11).
   - Known: `measure.term_structure` is cumulative horizons; the glossary and D2 define lags.
   - Recommendation: a pure function in `statistics/` used by the runner; file a todo to align `measure`'s job 2 naming with the glossary. Do not change `measure` in 184.
2. **The shift test (B8b): counted attempt or part of the same record?**
   - Recommendation: the same attempt's evidence carries the shifted rerun's statistic as a robustness field (no new spec hash, no selection universe entry). Confirm against 187-10/11's attempt model when B8 is planned.
   - RESOLVED: robustness field on the same attempt; plan 184-14 checks it against 187-10/11 at execution.
3. **Todo 482's timing.** It is P2 and deferred, and the `economic_series_observation` check constraint allows only `assumed_lag` and `fetch` today. B8's plan starts with "todo 482 complete", and its S0 refuses any basis other than the post-482 values. RESOLVED: plan 184-13 opens with a mechanical gate on todo 482.
4. **5m name and column set after the universe ruling.** Read 186-26's launch record at execution. RESOLVED: plan 184-12 reads it in its gate task.

## Environment Availability

| Dependency | Required by | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Postgres/TimescaleDB (`indicagent`) | S0 integration checks | yes | live | synthetic tests |
| Derived 15m/1h bars | B1d | yes (`derived/5m_grid` from 2006-07-06) | - | - |
| `feature_vectors_v2` rows + provenance | B1e-j real reads | no (0 rows, 0 batches) | - | synthetic only until 186-27 |
| `economic_series_observation` with release records | B8 | partial (235,212 rows, 54 series, assumed-lag basis) | - | B8 blocked on todo 482 |
| Frozen artifacts `logs/phase179`, `logs/phase181` | B7 repro_frozen | yes | - | - |
| `.venv` pytest + xdist | Validation | yes | research suite 108 s with `-n auto` | - |

**Blocking without fallback:** real-data execution of B1 feature reads (186-27) and B8 (todo 482). Neither blocks building and testing the code.

## Validation Architecture

### Test framework
| Property | Value |
|----------|-------|
| Framework | pytest with xdist (repo venv) |
| Config file | repo `pyproject.toml` / existing `tests/unit/research/` |
| Quick run | `.venv/bin/pytest tests/unit/research/<file> -q` |
| Research suite | `.venv/bin/pytest tests/unit/research tests/unit/intelligence -n auto -q` (research alone measured 108 s) |
| Full suite | `.venv/bin/pytest tests/unit/ -n auto` |
| Determinism gate | `.venv/bin/python -m scripts.research.determinism.repro_frozen <scratch> --logs /home/bg/dev/indicagent/logs` |
| Parity gate | `.venv/bin/pytest tests/unit/research/test_spec_hashes_pinned.py -q` and `.venv/bin/python scripts/research/backfill_attempt_series.py --compare-all` |

### Requirements to tests
| Req | Behavior | Type | Command | Exists |
|-----|----------|------|---------|--------|
| MTF-B1a | high/low on request; absent fields leave old snapshot bytes | unit | `pytest tests/unit/research/test_panel_mtf_fields.py -q` | no (187-15 adds `test_panel_optional_fields.py`; extend it) |
| MTF-B1b | closes_at: half day, both DST days, missing final bar, NaT row, short 1h bucket | unit | `pytest tests/unit/research/test_clock.py -q` | no |
| MTF-B1c | warmup prefix fetched, scored span unchanged | unit (fake pool) | `pytest tests/unit/research/test_feature_inputs.py -k warmup -q` | no |
| MTF-B1d | non-derived 15m/1h vendor refused | unit | `... -k vendor` | no |
| MTF-B1e | feature arrays content-hashed; edited array fails verify | unit | `... -k hash` | no |
| MTF-B1f | no batch, APR mismatch, mixed code_key each refuse | unit | `... -k provenance` | no |
| MTF-B1g | first memory rows NaN; path-dependent column refused | unit | `... -k warmup_mask` | no |
| MTF-B1h | below-floor column refused via feature_tf_quality | unit | `... -k coverage` | no |
| MTF-B1i | planted lookahead in a feature member fails S3 | unit | `pytest tests/unit/research/test_runner_feature_members.py -k causality -q` | no |
| MTF-B1j | hmm_* member refused without rebuild batches | unit | `... -k hmm` | no |
| MTF-B1k | unlisted feature_vectors reader fails CI | unit | `pytest tests/unit/test_feature_vectors_read_boundary.py -q` | no |
| MTF-B2a | vectorized percentile/rolling max bit-equal (float32) to originals after warmup; rolling VWAP memory bounded | unit | `pytest tests/unit/intelligence/test_research_kernels.py -q` | no |
| MTF-B2b | kernel_source over present rows, float32, NaN until memory, gap rule | unit | `pytest tests/unit/research/test_kernel_source.py -q` | no |
| MTF-B2c | expanding kernel refused; truncation probe passes research kernels, fails an acausal control | unit | `... -k guard5` | no |
| MTF-B3a | align semantics: latest finite, max_age in source rows, weekend not aging, NaT dst, broadcast source | unit | `pytest tests/unit/research/test_align.py -q` | no |
| MTF-B3b | planted leak rejected or no edge | unit | `... -k leak` | no |
| MTF-B3c | daily-on-intraday pattern across half day and DST | unit | `... -k daily_on_intraday` | no |
| MTF-B4 | lag curve on synthetic AR predictor matches closed form; band from shifts; record present and unread (grep) | unit | `pytest tests/unit/research/test_term_structure_lag.py -q` | no |
| MTF-B5 | menu literal; FIR weights; memory_check_array reach <= declared | unit | `pytest tests/unit/research/test_smoothing.py -q` | no |
| MTF-B6 | E17 size at 0.05/0.01/0.00167 on persistent cells | battery | `.venv/bin/python scripts/research/e17_null_battery.py <out.json> --battery src.intelligence.research.null_battery_persistent --sims 1000 --workers 6` | no (manual-length run; record to a phase BATTERY.md) |
| MTF-B7 | bit-identical, pinned hashes, compare-all | gate | commands above | yes |
| MTF-B8a | knowledge cutoff filter, decision-time join, max age NaN, basis refusal | unit | `pytest tests/unit/research/test_economic_block.py -q` | no |
| MTF-B8b | shifted rerun recorded | unit (synthetic) | `... -k shift_test` | no |

### Sampling rate
- Per task commit: the item's test file plus `test_spec_hashes_pinned.py` (seconds).
- Per plan commit touching `src/intelligence/research/`: the full unit suite, repro_frozen and compare-all (CLAUDE.md substantive class).
- Phase gate: the full suite green, the B6 battery report committed, repro_frozen bit-identical.

### Wave 0 gaps
- Shared synthetic fixtures: a small multi-tf synthetic bar set (5m to derived 15m/1h to 1d) spanning a half day (for example 2024-11-29) and both 2024 DST transitions (2024-03-11, 2024-11-04), plus a fake `provenance_batch` row set, in `tests/unit/research/conftest.py` or a fixture module.
- No framework install needed.

## Security Domain

| ASVS category | Applies | Control |
|---------------|---------|---------|
| V2/V3/V4 | no | local research code |
| V5 input validation | yes | strict pydantic spec models (`extra="forbid", strict=True`); feature column names checked against registry outputs before reaching SQL; `psycopg.sql.Identifier` or asyncpg with an allow-listed column list, never interpolated spec text |
| V6 crypto | no | sha256 content hashing only (existing `store`) |

| Threat | STRIDE | Mitigation |
|--------|--------|-----------|
| SQL identifier injection via a spec column name | Tampering | allow-list from `registry.feature_columns()` |
| Tampered snapshot | Tampering | `store.verify` content hash (existing) |
| Reading past `oos_start` | Information disclosure (lookahead) | existing `build_panel` refusal also guards feature and economic reads; warmup prefix is before `start` only |

## Project Constraints (from CLAUDE.md)

- APR for every tunable in `src/` and `services/`. Research spec constants are pinned in the spec, the one reviewed place (spec.py docstring). Definition constants (menu values, the 1e-4 memory cut, band level) are APR-exempt with a comment.
- No em dashes; no AI attribution; commit on main with `git commit -m "..." -- <paths>`; never amend.
- Substantive code: /simplify, /review, `pytest tests/unit/ -n auto`; repro_frozen bit-identical after any research or statistics edit.
- `market_data_ohlcv_tradeable` only; `panel.forward_returns` only; UTC only (`datetime.now(UTC)`); `except X as error:`; `format_iso_ts` for serialization.
- Ring rule: research and features are Ring 1; research may import features, statistics and bars; features never import research.
- Single writer: S6 ledger writes `research_run`; S0 never writes.
- ProcessPool workers compute only; never materialize a wide `SELECT *`; never log per row.
- Migrations: only if a new APR key or table is truly needed (none expected; B1h may record, not seed). Re-check the migration tail at execution (latest 525).
- Code under `src/intelligence/research/` executes only after 5b's go (CONTEXT).

## Sources

### Primary (HIGH confidence, codebase and live DB, 2026-10-27)
- `src/intelligence/research/{panel,snapshot,spec,construction,runner,guards,signals,store,book,timing,null_battery,static_sizes}.py`
- `src/intelligence/features/contract/{registry,causality_probe}.py`, `kernels/{price,volume}.py`, `services/backfill_feature_factory.py`, `services/ic_measure.py`, `src/intelligence/measure/{term_structure,ic,targets}.py`, `src/intelligence/statistics/feature_coverage.py`, `src/intelligence/bars/{sessions,session_grid,selection}.py`
- Live DB: `\d provenance_batch`, `feature_vectors_v2` columns and size, `market_data_ohlcv` vendor/kind by tf, `economic_series_observation` schema and counts, SPY 1d/1h `bar_ts` samples
- `.planning/phases/187-*/187-{08,09,10,11,13,14,15,18}-PLAN.md` files_modified and amendments; `187-REVIEWS.md` (15: sector point in time)
- `.planning/phases/186-*/186-PLAN-OUTLINE.md`, `186-07-SUMMARY.md`, `186-09-SUMMARY.md`, `186-26-PLAN.md`, `186-27-PLAN.md`
- `docs/plans/archive/2026-09-25-multi-timeframe-horizon-design.md` rev 3; unified design 4.4, 4.5, 12, 14.7; `docs/foundation/glossary.md` (predictor, clock, IC term structure)
- Todos 435 (pending), 482 (deferred); `docs/ideas/signal-macro-context-layer.md`

### Secondary / tertiary
- None used; no web sources were needed for internal code.

## Metadata

**Confidence breakdown:**
- Current state and dependencies: HIGH (read and queried directly)
- Sequencing against 187: HIGH (files_modified lists)
- Recommended spec shapes, memory rules, smoother form: MEDIUM (design choices within discretion)
- B8: MEDIUM (blocked; design in an idea doc)

**Research date:** 2026-10-27
**Valid until:** about 2026-11-10, or earlier if 187-08/09/15 or 186-26/27 land (re-check files and table state)
