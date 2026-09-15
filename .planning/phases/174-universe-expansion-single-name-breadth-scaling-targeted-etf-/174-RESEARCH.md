# Phase 174: Universe Expansion — Single-Name Breadth Scaling + Targeted ETF Gap-Fill - Research

**Researched:** 2026-09-15
**Domain:** Internal batch-compute memory engineering (ic_engine OOM fix) + instrument governance schema (PostgreSQL/TimescaleDB) + data-sourcing methodology (Russell 3000 stratified sampling, ETF gap-fill). No new external libraries.
**Confidence:** MEDIUM-HIGH (code paths verified by direct reading + live DB queries; sampling data source and ETF specifics carry WebSearch-sourced claims tagged accordingly)

## Summary

This phase has three largely independent workstreams that share one onboarding surface
(`instruments`/`instrument_tags`/`instrument_metadata`/`backfill_status`): (1) a structural
memory fix to `services/ic_engine.py`'s cross-sectional cell compute path — the actual
hard prerequisite for everything else, (2) a 3-way instrument-governance schema split
replacing the single `is_active` boolean, and (3) sourcing + backfilling a market-cap-
stratified Russell 3000 sample plus a small set of gap-fill ETFs. All three were
research-verified directly against the running codebase and live database (not just the
CONTEXT.md session's prior findings), and one of CONTEXT.md's factual premises was found to
be **wrong** — see the "Critical correction" callout below before planning D-06.

The ic_engine OOM fix (D-04) has a concrete, code-grounded design: a cheap pre-flight
row-count estimate (`len(regime_timestamps) * len(symbol_list)`, both already known before
the chunked fetch loop starts) makes `_check_cell_size` reachable before any memory is
allocated, and replacing `Float32ChunkAccumulator`'s in-RAM chunk-list + `np.vstack` finalize
with a disk-backed `np.memmap` bounds peak anonymous RSS to one chunk's worth of data
regardless of total cell size. Reading the actual function found a **second, previously
undocumented defeat point** beyond the one named in todo 371: a boolean-column-index copy
(`X_nd = X_raw[:, cluster_input_mask]`, line 3630) that re-materializes most of the cell in
RAM even after the accumulator fix — the planner needs to account for this, not just the
`finalize()` step.

Instrument governance (D-07/D-08) can be built as an additive, non-breaking schema change:
keep `is_active` meaning what it already implicitly means today (backfill-eligible AND
compute-eligible, conflated), add two new boolean columns (`compute_eligible`,
`live_tradeable`), and give `get_active_contracts()` an optional `dimension` parameter that
defaults to today's exact behavior — this avoids touching any of the ~25 existing call sites
while giving new consumers (and the Russell 3000 sample itself) a real 3-way split.

**Primary recommendation:** Sequence D-04 (ic_engine memory fix) strictly first — it is
untestable-in-isolation prerequisite infrastructure, not parallelizable with the backfill
work it gates. Build D-07/D-08's schema additively (new columns, not a breaking rename).
Before finalizing D-06's ETF list, resolve the momentum/quality discrepancy below — it may
eliminate half of that decision's scope.

## Critical correction to CONTEXT.md (verify before planning D-06)

**CONTEXT.md states "momentum and quality factor-tilt ETFs currently zero representation."
This is factually wrong, verified live against the database in this research session:**

```sql
SELECT symbol, is_active, created_at FROM instruments WHERE symbol IN ('MTUM','QUAL','USMV');
--  MTUM | t | 2026-05-15   QUAL | t | 2026-05-15   USMV | t | 2026-05-15
SELECT symbol, count(*) FROM market_data_ohlcv WHERE symbol IN ('MTUM','QUAL','USMV') GROUP BY symbol;
--  MTUM: 2,194,069 rows   QUAL: 2,156,803 rows   USMV: 2,417,375 rows
```

`MTUM` (iShares MSCI USA Momentum Factor ETF), `QUAL` (iShares MSCI USA Quality Factor ETF),
and `USMV` (iShares MSCI USA Min Volatility Factor ETF — the low-vol factor CONTEXT.md
separately "dropped from scope") were all added 2026-05-15, are `is_active=true`, and are
already fully backfilled with millions of OHLCV rows across all four timeframes. They already
carry `instrument_tags.tag='eq_factor'` (a generic factor tag also shared by `BTAL`/`SPHB`).
`instrument_metadata` even has correct `listing_date`/`underlying_index` rows for all three.

**What this means for planning:** D-06's premise that momentum/quality need *new* tickers is
wrong — those exposures already exist in the corpus and are backfilled. `[VERIFIED: live DB
query, this session]`. What may still be a real (smaller) gap: `eq_factor` is a single coarse
tag shared across 5 structurally different strategies (momentum, quality, low-vol, market-
neutral, high-beta) — if the planner wants factor-specific IC stratification, the fix is
**adding `eq_momentum`/`eq_quality`/`eq_low_vol` rows to `tag_vocabulary` and re-tagging
`MTUM`/`QUAL`/`USMV`**, not buying new instruments. This is a tag-taxonomy task, not a
sourcing/backfill task, and should not consume any of D-04's newly-freed compute headroom.

**What IS still a confirmed real gap** (re-verified live, matches CONTEXT.md):
- Zero `fx_em`-tagged symbols; existing `fx_*` tags only cover developed-market pairs
  (`UUP`, `FXE`, `FXY`, `FXA`, `FXC`). No `CEW`/`EMLC` or equivalent registered.
- Zero VIX-linked or vol-proxy ETF/ETN registered at all (`VXX`, `VIXY`, `UVXY`, `SVXY`,
  `VIXM` all absent from `instruments`).

So D-06's actual remaining scope, once corrected, is **EM-FX + vol proxy only** — see the ETF
Gap-Fill section below for concrete ticker recommendations. Surface this correction to the
user before locking final scope; it was not something CONTEXT.md's decision explicitly
depended on being true (the decision was "bundle ETF work into this phase," which still
holds), but the specific ticker list changes materially.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Target universe & sourcing**
- **D-01:** Do not lock a target instrument count in this phase. Research determines the
  largest feasible count under whatever the todo-371 OOM fix (D-04) actually supports.
- **D-02:** Russell 3000 is the definitional target population (systematic, no
  cherry-picking). Actual Phase 174 backfill scope is a **market-cap-stratified random
  sample** from that population, sized against D-04's supported scale.
- **D-03:** Survivorship bias (todo 376) does not gate this phase's pilot. Source the pilot
  sample active-only (today's Russell 3000 constituents); research delisted-constituent
  feasibility in parallel, non-blocking.

**ic_engine OOM fix (todo 371)**
- **D-04:** Build (1) a pre-flight cell-size estimate that makes `_check_cell_size` reachable
  before whole-cell materialization, AND (2) disk-bounded incremental processing so peak
  memory is bounded by chunk size, not total cell size. Explicitly reject silent subsampling
  as a default degrade path. Subsampling may exist only as an explicit, pre-registered,
  visibly logged escape hatch — never automatic. The 96GB swapfile stopgap does not survive
  further scale-up and is not a substitute for this structural fix.

**ETF gap-fill**
- **D-05:** Bundle ETF gap-fill into Phase 174 (same instrument-onboarding machinery being
  built/exercised anyway).
- **D-06:** Add momentum and quality factor-tilt ETFs (currently zero representation —
  **see Critical Correction above, this premise is false**). Low-vol dropped from scope.
  EM-FX and vol exposure (a VIX-linked ETF/ETN proxy) stay in scope. Exact tickers are a
  research/planning decision — screen for liquidity, expense ratio, inception date/history
  depth.

**Instrument governance schema (todo 274)**
- **D-07:** Build the backfill-eligible / compute-eligible / live-tradeable 3-way split
  (replacing the single `instruments.is_active` boolean) now, applied to new instruments as
  added. `get_active_contracts()` is read by every consumer — if the Russell 3000 pilot
  sample is marked `is_active=true` under the current single-flag model, that's correct for
  backfill/compute but silently also makes those names eligible for a future live-trading
  code path. The 80-subscription cap only binds live streaming (confirmed dormant, not a
  blocker for backfill at any scale) but a future restart against an unsplit universe would
  silently fail to honor that cap.
- **D-08:** Fold in todo 282's process fix while touching instrument onboarding anyway: the
  "add an instrument" workflow should write a stub `instrument_metadata` row (or explicitly
  and visibly skip it).

### Claude's Discretion
- Exact ETF tickers for the momentum/quality/EM-FX/vol gap-fill (D-06) — research/planning
  screens for liquidity, expense ratio, history depth. **(Momentum/quality now moot per
  Critical Correction — only EM-FX/vol tickers actually need selecting.)**
- Exact stratification scheme for the market-cap-stratified sample (D-02) — number of
  cap-deciles, sample size per decile, sized against whatever count D-01/D-04 land on.
- Schema shape for D-07 — separate boolean columns on `instruments` vs. `instrument_tags`
  entries per dimension; default semantics for existing rows.

### Deferred Ideas (OUT OF SCOPE)
- Nautilus Trader (OSS execution/backtest-parity engine) — future execution-layer phase
  candidate, not this phase.
- Qlib, Vectorbt — evaluated and rejected for current needs.
- Full futures backfill (todo 377) — explicitly out of scope. If pursued later, target only
  CL/NG/HG/ZC/ZS/ZW/VX/GBPUSD/USDCHF (9 instruments), after a separate continuous-contract
  construction design.
</user_constraints>

## Project Constraints (from CLAUDE.md)

These are non-negotiable, verified against this phase's actual touch points:

- **APR mandate (Migrate-as-you-go):** every new numeric constant this phase introduces
  (memmap chunk-activation threshold, scratch-dir path, stratification bucket count,
  sample-size-per-bucket, RNG seed) MUST be inserted into `config_schema`/`config_state` via
  migration and read through `ConfigService.get()`/`get_sync()` — never a Python module
  constant. Valid namespace prefixes are a fixed allowlist (`ConfigService.OPS_PREFIXES`,
  `src/config/config_service.py` line 39): `regime.`, `swarm.`, `alert.`, `ai.`, `feature.`,
  `threshold.`, `roll.`, `cross_asset.`, `macro.`, `ui.`, `weights.`, `alpha.`, `infra.` —
  **there is no `universe.` prefix**; sampling-methodology keys must live under `alpha.*`
  (e.g. `alpha.universe.*`), OOM-fix keys under `infra.*` (e.g. `infra.ic_engine.*`).
- **Seeds that affect algorithm output → APR, category 1 of the 4 APR-extension categories**
  (root CLAUDE.md): the stratified-sample RNG seed is exactly this case — must be an APR key
  (e.g. `alpha.universe.stratified_sample_random_state`), not a hardcoded `42`, with a
  description warning that changing it invalidates the sample's reproducibility.
- **Ring rule:** any new module goes in the correct ring — a stratified-sampling script is a
  one-off `scripts/` tool (not `src/core`/`src/intelligence`), the disk-backed accumulator
  variant belongs beside `Float32ChunkAccumulator` in `services/_batch_utils.py` (Ring 2,
  already where the class lives — no ring violation, it's a `services/` internal, not
  imported by `src/core`).
- **DAG invariant 3 (compute daemon never writes its own output):** N/A here — `ic_engine.py`
  is itself the writer of `feature_ic_scores`, that invariant governs the feature-compute
  daemons, not the measurement/IC engine. No change to this phase.
- **`except X as error:`** — any new exception handling in the memmap fix or onboarding
  scripts must use `error`, not `exc`.
- **`bulk_update_by_key`'s `col_types` load-bearing note** — not directly touched by this
  phase (no `real`-typed column changes), but any migration adding columns to `instruments`
  must not silently narrow an existing column's declared width.
- **`INDICAGENT_ENV` consistency** — any new backfill/onboarding script must not hardcode a
  topic prefix; N/A for pure-SQL onboarding but relevant if any new Kafka-publishing code is
  added (unlikely — this phase's D-04/D-07/D-08 work is DB + batch-script, not streaming).
- **Never log per-row inside a full-corpus loop** — the stratified-sampling script and any
  bulk instrument-onboarding script processing hundreds-to-thousands of symbols must
  accumulate a counter and log once per run, matching `ic_engine.py`'s `n_skipped` pattern.
- **A migration applied live via `psql -f` has no forcing function to get committed** —
  commit each migration in the same breath as applying it live, not "later."
- **Corpus Pipeline Gotcha** (`.planning/STATE.md`): `--compute-only` silently skips all
  symbols if `backfill_status` is empty. Every newly onboarded symbol (Russell 3000 sample +
  2 new ETFs) MUST get a `backfill_status` seed row per timeframe or it silently vanishes
  from compute — this is D-08's exact failure class, one table over.
</project_context>

<phase_requirements>
## Phase Requirements

No phase requirement IDs were assigned (`phase_req_ids` is null in ROADMAP.md — this phase
was scoped directly via `/gsd-discuss-phase`, not derived from a pre-existing requirements
list). Per the orchestrator's instruction, this does not block planning. CONTEXT.md's
decisions (D-01 through D-08) function as the requirement set for planning purposes; see the
User Constraints section above.
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| ic_engine cross-sectional cell memory bound (D-04) | API/Backend (batch compute, `services/ic_engine.py`) | Database/Storage (disk-backed memmap scratch files) | Pure in-process compute fix; the "storage" role here is a local scratch filesystem, not TimescaleDB itself |
| Instrument governance schema (D-07/D-08) | Database/Storage (`instruments`/`instrument_tags`/`instrument_metadata` DDL) | API/Backend (`get_active_contracts()` and siblings in `src/config/settings.py`) | Schema is the source of truth; `settings.py` is the sole read API every consumer uses — no consumer queries the tables directly |
| Russell 3000 stratified sampling (D-02) | API/Backend (one-off `scripts/` sourcing script) | Database/Storage (writes to `instruments`/`instrument_metadata`/`backfill_status`) | Sourcing logic (fetch population, stratify, sample) is pure compute; persistence is a thin write step reusing existing onboarding tables |
| Historical backfill (D-01/D-02 execution) | API/Backend (`scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py`, `src/providers/ibkr.py`) | — | Existing IBKR provider pipeline, no new tier |
| ETF gap-fill onboarding (D-06) | Database/Storage (same onboarding tables) | API/Backend (same backfill script, `instrument_tags` writes) | Identical shape to D-02's onboarding, just 1-2 symbols instead of hundreds |
| APR keys for new thresholds | Database/Storage (`config_schema`/`config_state`) | API/Backend (`ConfigService.get_sync()` call sites in `ic_engine.py`) | Standard APR read/write split already established project-wide |

No Browser/Client or CDN/Static tier involvement — this phase has no UI surface (confirmed by
CONTEXT.md: "No UI/visual specifics — this is a data-sourcing and infrastructure phase").

## Standard Stack

No new external packages. This phase is internal Python (numpy/psycopg/asyncpg, all already
project dependencies) plus SQL migrations plus a one-off data-sourcing script that downloads
a public CSV/XLSX (Russell 3000 constituent list). `numpy` 2.4.6 is the installed version in
`.venv` (verified this session via `python -c "import numpy; print(numpy.__version__)"`),
already supports `np.memmap` — no version bump needed.

### Core (already in the project, reused)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| numpy | 2.4.6 (installed, verified) | `np.memmap` for the disk-backed accumulator | Already the array backend for `Float32ChunkAccumulator`; `np.memmap` is stdlib-numpy, zero new dependency |
| psycopg | (existing, `settings.py` already imports it) | `get_active_contracts()` sibling functions, migration execution | Already the project's sync Postgres driver for this exact module |
| pandas or plain `csv` module | (pandas already a project dependency) | Parsing the downloaded Russell 3000 constituent CSV/XLSX | Standard for one-off data-wrangling scripts in `scripts/` |

### Package Legitimacy Audit

**Not applicable — no new external packages are installed by this phase.** All library usage
(`numpy`, `psycopg`, `pandas`) is pre-existing in the project's dependency tree. The only new
external artifact this phase consumes is a data file (Russell 3000 constituent list), not a
package — see "Don't Hand-Roll" and "Open Questions" for sourcing details.

## Architecture Patterns

### System Architecture Diagram — D-04 (ic_engine memory fix)

```
_compute_cross_sectional_tf(tf, regime_label, regime_group, symbol_list, dsn, config, ...)
  │
  ├─ Step 1: fetch regime_timestamps from market_regimes         (existing, cheap, ~120K rows)
  │
  ├─ [NEW] Pre-flight estimate:
  │     n_estimated = len(regime_timestamps) * len(symbol_list)
  │     _check_cell_size(n_estimated, config, "...pre-flight estimate...")
  │     → raises CellTooLargeError here, BEFORE any chunk fetch, if the cell
  │       is already known to exceed alpha.ic.max_cell_rows
  │
  ├─ Step 2: chunked fetch loop (existing cs_chunk_ts-sized chunks)
  │     for chunk_start in range(0, len(regime_timestamps), cs_chunk_ts):
  │         fetch chunk from feature_vectors JOIN forward_returns
  │         [CHANGED] X_acc.append_chunk(batch)  → now writes DIRECTLY into
  │                     a pre-sized np.memmap file on disk at the correct
  │                     row offset, instead of appending to an in-RAM list
  │         ret_chunks / cmp_chunks / bar_ts_chunks: SAME in-RAM lists as
  │                     today — these are (n_rows, n_scales) or (n_rows,)
  │                     shaped, orders of magnitude smaller than X (250 cols)
  │
  ├─ [CHANGED] X_acc.finalize() → returns the memmap array directly
  │     (no np.vstack; memmap IS already the finalized (n_rows, n_features)
  │     array, backed by disk not anonymous RAM)
  │
  ├─ _compute_one_cross_sectional_cell(...)
  │     ├─ n_raw = len(X_raw)                                    (cheap — memmap shape)
  │     ├─ _check_cell_size(n_raw, ...)                           (existing, now redundant-but-safe
  │     │                                                          exact-count confirmation)
  │     ├─ feature_stds = np.std(X_raw, axis=0)                   (read-through reduction over
  │     │                                                          memmap — OK, no full copy)
  │     ├─ [FLAG FOR PLANNER] X_nd = X_raw[:, cluster_input_mask] (boolean column index —
  │     │                                                          ALWAYS COPIES even on a
  │     │                                                          memmap; second defeat point,
  │     │                                                          not named in todo 371)
  │     └─ per-scale loop: X_sub = X_raw[0:n_raw:scale_stride]    (existing basic-slice VIEW,
  │                                                                 already correct, 2026-07-19
  │                                                                 fix — no change needed)
  │
  └─ [NEW] cleanup: delete the memmap scratch file (finally block) — must not
        accumulate scratch files across a multi-day, thousands-of-cells corpus run
```

### Recommended file/module changes
```
services/_batch_utils.py
├── Float32ChunkAccumulator          # existing — add disk_backed=True constructor mode
│                                       (estimated_rows, n_cols, scratch_dir params);
│                                       existing append_row/append_chunk/finalize() API
│                                       unchanged for the in-RAM (default) mode — no
│                                       breaking change to the per-symbol streaming-cursor
│                                       caller (_compute_symbol_tf), which is out of D-04's
│                                       stated scope but shares this class.
services/ic_engine.py
├── _compute_cross_sectional_tf       # add pre-flight estimate call; swap accumulator mode
├── _compute_one_cross_sectional_cell # no signature change; X_raw may now be a memmap —
│                                       flag the X_nd boolean-index copy as a follow-up
│                                       mitigation point (see Common Pitfalls)
src/config/settings.py
├── get_active_contracts(settings, dimension="compute")  # NEW optional param, default
│                                       preserves EXACT current query (is_active AND
│                                       asset_class != 'futures') — zero behavior change
│                                       for any of the ~25 existing call sites that don't
│                                       pass dimension=
├── get_backfill_eligible_contracts() # NEW sibling, OR dimension="backfill" — planner's
│                                       call which shape fits the codebase's existing
│                                       sibling-function convention (get_active_contracts
│                                       already has a documented sibling at line 605 for
│                                       futures-without-front-month-filter)
scripts/<new>_universe_expansion_sourcing.py   # one-off: fetch Russell 3000 population,
│                                       stratify, sample, write instruments/
│                                       instrument_metadata/backfill_status rows
production/migrations/336_*.sql        # instruments: + compute_eligible, + live_tradeable
production/migrations/337_*.sql        # APR keys: infra.ic_engine.*, alpha.universe.*
production/migrations/338_*.sql        # tag_vocabulary: + fx_em (if not present as a
│                                       usable tag already), + vol_proxy exposure tag
```

### Pattern 1: Additive schema split (D-07), not a breaking rename
**What:** Add `compute_eligible boolean NOT NULL DEFAULT true` and
`live_tradeable boolean NOT NULL DEFAULT false` to `instruments`. Leave `is_active` exactly
as-is (semantically documented as "backfill-eligible", matching its current real-world
usage — every one of today's 231 active rows is both backfilled AND compute-consumed).
**When to use:** Whenever a 3-way split needs to be layered onto a widely-read single flag
with ~25 call sites, none of which should need to change.
**Default semantics for existing 231 rows (recommended, addresses CONTEXT.md's open
question):** `is_active=true` (unchanged) → `compute_eligible=true` (matches today's actual
behavior — `is_active` already gates every compute consumer), `live_tradeable=false` (correct
today: live IBKR streaming is confirmed dormant, and no explicit ≤80-symbol whitelist has
ever been chosen — leaving this `false` for all 231 is honest, not a regression, since nothing
reads `live_tradeable` yet).
**New Russell 3000 sample + ETF rows:** `is_active=true`, `compute_eligible=true` (or `false`
initially if the planner wants a maturation window before compute — CONTEXT.md's todo 274
excerpt flags this as a real, plausible state), `live_tradeable=false` always this phase.
**Example:**
```sql
-- Source: migration pattern already used in this codebase, e.g. 307/311/324 — additive
-- ALTER TABLE, backfilled default, no data migration of existing semantics needed.
ALTER TABLE instruments
    ADD COLUMN compute_eligible boolean NOT NULL DEFAULT true,
    ADD COLUMN live_tradeable boolean NOT NULL DEFAULT false;

-- Explicit backfill statement (redundant with DEFAULT but explicit per CLAUDE.md's
-- "silent wrong answers are worse than loud crashes" — makes the semantic mapping
-- decision a visible, reviewable SQL statement, not an implicit column default):
UPDATE instruments SET compute_eligible = true, live_tradeable = false WHERE is_active = true;
```

```python
# src/config/settings.py — Source: existing get_active_contracts() signature, extended
def get_active_contracts(
    settings: Settings | None = None,
    dimension: str = "compute",  # NEW — "backfill" | "compute" | "live"
) -> list[Instrument]:
    ...
    dimension_clause = {
        "backfill": "is_active = true",
        "compute": "is_active = true AND compute_eligible = true",
        "live": "is_active = true AND compute_eligible = true AND live_tradeable = true",
    }[dimension]
    # NOTE: default="compute" changes behavior for every existing caller versus the
    # literal current query ("is_active = true" only) UNLESS compute_eligible defaults
    # true for all existing rows (which the migration above guarantees) — verify this
    # equivalence with a test before merging, per this project's Nyquist validation gate.
```

### Anti-Patterns to Avoid
- **Renaming or repurposing `is_active`:** every one of the ~25 call sites (see grep results
  in Code Context below) would need review; there is no need, since `is_active` already means
  "backfill-eligible" in practice.
- **Automatic subsampling on `CellTooLargeError`:** D-04 explicitly rejects this as a default.
  Do not add a `try/except CellTooLargeError: subsample()` fallback anywhere — the correct
  response to a cell still too large after the disk-bound fix is a human-reviewed, explicitly
  logged, pre-registered config override for that one cell, not automatic code.
- **A separate `universe_expansion` one-off script that bypasses `instrument_metadata`
  stub-writing (D-08):** every new instrument this phase adds — Russell 3000 sample AND
  ETFs — must write (or explicitly, visibly skip with a logged reason) an `instrument_metadata`
  row at onboarding time, not defer it the way the 111→231 expansion did (todo 282's exact
  failure, 0% coverage for 151 symbols).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Russell 3000 constituent list + market cap | A scraper against a brokerage/exchange site, or a hand-maintained ticker list | iShares IWV (Russell 3000 ETF) public holdings export — official issuer data, updated ~daily, free, no API key | `[CITED: ishares.com/us/products/239714/ishares-russell-3000-etf]` — this is the standard, free, authoritative source institutional researchers use for Russell 3000 membership; alternatives (Barchart, StockAnalysis.com, Intrinio) are third-party re-publications of the same underlying holdings file. **Not yet hands-on verified in this research session** — the actual file's column schema (does it expose market cap directly, or only portfolio weight + shares held, requiring a derived market-cap calc?) needs live verification at execution time. See Open Questions. |
| Chunked-array-to-single-array accumulation with bounded memory | A new bespoke streaming/memmap wrapper from scratch | Extend the existing `Float32ChunkAccumulator` (`services/_batch_utils.py`) with a disk-backed mode | Don't fork a parallel accumulator class; the per-symbol path (`_compute_symbol_tf`) shares this exact class and a divergent implementation would reintroduce the "copy-pasted at both call sites" problem migration 249 already fixed once (see `_check_cell_size`'s own docstring, line 1023) |
| Instrument onboarding validation (symbol exists, contract qualifies) | A new validation layer | `src/providers/ibkr.py`'s existing `qualify_instrument()` | Already handles asset-class-specific contract construction (`Stock`, `Forex`, etc.) and IBKR's ambiguous-contract error surface; re-implementing this for the stratified sample risks missing the `tradingClass` edge cases already documented in `src/providers/CLAUDE.md` |
| Cap-decile bucketing / stratified random sampling | A custom binning algorithm | `pandas.qcut()` (quantile-based discretization) + `numpy.random.Generator` (APR-seeded) for the actual draw | `pandas.qcut` is the standard, well-tested tool for equal-population decile bucketing on a continuous variable (market cap); no reason to hand-roll quantile boundary logic |

**Key insight:** Every "don't hand-roll" item in this phase already has a standing pattern
in this exact codebase (the accumulator, the IBKR qualification layer) or a well-known
external free data source (IWV holdings) — this phase is assembly of existing primitives
into a new onboarding pathway, not net-new infrastructure design, except for the memmap mode
itself (which is new but small — see Code Examples).

## Common Pitfalls

### Pitfall 1: Fixing only `Float32ChunkAccumulator.finalize()` and declaring D-04 done
**What goes wrong:** The disk-backed accumulator fix alone stops `X_raw` from being a full
in-RAM copy, but `_compute_one_cross_sectional_cell`'s `X_nd = X_raw[:, cluster_input_mask]`
(line 3630) is a **boolean column index**, which numpy always materializes as a fresh
anonymous-RAM copy — even when `X_raw` is a memmap. For the largest known cell
(`5m/high_bear`, ~64M rows × ~250 features), `X_nd` after dropping degenerate/broadcast
columns is still likely tens of GB.
**Why it happens:** Fancy indexing (boolean masks, integer arrays) never returns a numpy
view; only basic slices (`start:stop:step`) do. The codebase already knows this pattern (the
2026-07-19 comment at line 3646-3651 explicitly calls out choosing a slice over fancy
indexing for `X_sub` for exactly this reason) — but it wasn't applied to `X_nd`.
**How to avoid:** At minimum, measure whether `X_nd`'s copy alone (smaller than the original
whole-`X_raw` copy, since it drops some columns) still risks OOM at the largest cell size
before treating D-04 as complete. If it does, chunk the column-copy itself — this codebase
already has a precedent for exactly this shape of fix (`feature_block_columns: int = 32`,
line 637, "bounds peak transient memory to O(n_sub x block) instead of O(n_sub x
n_features)" — apply the identical block-column-chunking idea to build `X_nd` as a second
memmap, written column-block-by-column-block, rather than one boolean-index call).
**Warning signs:** Re-running the 2026-09-07 OOM scenario (182 symbols, `5m/high_bear`) under
the disk-bound fix and still seeing anon RSS spike near the full cell size during the
clustering step, not just during the fetch/accumulate step.

### Pitfall 2: Pre-flight estimate uses a stale/wrong symbol count
**What goes wrong:** The pre-flight estimate `len(regime_timestamps) * len(symbol_list)`
assumes every symbol has a row for every regime timestamp (full density). For a newly-added
Russell 3000 sample symbol with a shorter backfill history than its peers, this overestimates
— which is safe direction (fails loud slightly early) but could produce false-positive
`CellTooLargeError`s for cells that would actually fit once sparse symbols are accounted for.
**Why it happens:** `symbol_list` (the regime group's full peer set) is fixed regardless of
individual symbol data density.
**How to avoid:** Treat the pre-flight estimate as a conservative upper bound by design (per
D-04's explicit preference for crash-loud over silent degrade) — do not "fix" this by trying
to make it exact; document the estimate as intentionally an upper bound in the code comment,
so future readers don't try to tighten it and reintroduce the OOM risk from an
underestimate. If false-positive `CellTooLargeError`s become operationally annoying at
Russell-3000 scale (many sparse-history symbols), that is itself useful information: it
argues for backfilling a maturation window before marking a symbol `compute_eligible=true`
(D-07's exact 3-way-split rationale).

### Pitfall 3: `alpha.ic.max_cell_rows`'s prior recalibration history repeating
**What goes wrong:** This exact APR key was already bumped once purely to route around the
symptom (migration 332, 10M → 15M) without fixing the underlying unreachable-guard bug —
todo 371's own file documents this as "a ceiling recalibration, same class as migration 259,
not a fix for this todo's actual finding." At Russell-3000 sample scale, the temptation to
just raise the ceiling again (rather than land the structural fix) will recur.
**Why it happens:** Raising a config value is a one-line, zero-risk-seeming operational
change under time pressure during a running corpus job; the structural fix is real
engineering work.
**How to avoid:** The plan should treat D-04 as blocking — no stratified-sample backfill/
compute run proceeds until the disk-bound fix (not just a ceiling bump) is landed and
verified against a synthetic cell sized comparably to the eventual Russell-3000-scale
largest cell.
**Warning signs:** A plan or execution step that says "bump `max_cell_rows` to N and proceed"
without a corresponding code change to `_compute_cross_sectional_tf`/`Float32ChunkAccumulator`.

### Pitfall 4: `ib-gateway` container is currently stopped
**What goes wrong:** Any backfill work (Russell 3000 sample, EMLC, VIXY) will silently have
nothing to fetch from if `ib-gateway` isn't running — `reqHistoricalDataAsync` requires a live
Gateway/TWS connection even though it is not subject to the 80-subscription live-streaming
cap.
**Why it happens:** `ib-gateway` was intentionally stopped 2026-09-07 as part of the
todo-371 OOM workaround ("Stopped ib-gateway + ollama containers: dead weight... `ib-gateway`'s
`JTS-DeadlockMon` was what invoked the OOM killer"). Verified still `Exited (1) 7 days ago`
as of this research session (`docker ps -a`).
**How to avoid:** The plan's backfill tasks must include restarting `ib-gateway` as an
explicit first step, not assume it's already up. Cross-check paper-trading-account symbol
availability (`src/providers/CLAUDE.md`: `BZJ6`, `NGJ6`, `SR1H6` return Error 200 on paper —
unlikely to affect equity/ETF symbols in scope here, but worth a spot-check for the new ETFs).
**Warning signs:** Backfill script runs, exits cleanly, zero rows written — the exact silent
failure shape `docs/foundation/performance-investigation-sop.md` and CLAUDE.md's Corpus
Pipeline Gotcha both warn about generally.

## Code Examples

### Disk-backed accumulator mode (design sketch, not yet implemented)
```python
# Source: extends services/_batch_utils.py's existing Float32ChunkAccumulator
# (read directly this session, lines 1029-1074). New disk_backed mode, additive —
# existing append_row()/append_chunk()/finalize() callers (per-symbol path) unaffected.
import tempfile
import numpy as np

class Float32ChunkAccumulator:
    def __init__(
        self,
        flush_at: int | None = None,
        *,
        disk_backed: bool = False,
        estimated_rows: int | None = None,
        n_cols: int | None = None,
        scratch_dir: str | None = None,
    ) -> None:
        self._flush_at = flush_at
        self._chunks: list[np.ndarray] = []
        self._buf: list = []
        self._disk_backed = disk_backed
        self._write_offset = 0
        if disk_backed:
            if not estimated_rows or not n_cols:
                raise ValueError("disk_backed mode requires estimated_rows and n_cols")
            self._tmpfile = tempfile.NamedTemporaryFile(
                dir=scratch_dir, suffix=".memmap", delete=False
            )
            self._memmap = np.memmap(
                self._tmpfile.name, dtype=np.float32, mode="w+",
                shape=(estimated_rows, n_cols),
            )

    def append_chunk(self, rows: Any) -> None:
        if not len(rows):
            return
        if self._disk_backed:
            arr = np.array(rows, dtype=np.float32)
            n = len(arr)
            self._memmap[self._write_offset : self._write_offset + n] = arr
            self._write_offset += n
        else:
            self._chunks.append(np.array(rows, dtype=np.float32))  # existing behavior

    def finalize(self) -> np.ndarray | None:
        if self._disk_backed:
            if self._write_offset == 0:
                self._memmap._mmap.close()
                Path(self._tmpfile.name).unlink(missing_ok=True)
                return None
            # Truncate the view to actual rows written (estimate may overcount
            # for symbols with sparser history than the peer group's densest member).
            return self._memmap[: self._write_offset]
        self._flush_buf()
        if not self._chunks:
            return None
        result = np.vstack(self._chunks)
        self._chunks = []
        return result
```

### Pre-flight cell-size check (design sketch)
```python
# Source: services/ic_engine.py, _compute_cross_sectional_tf, insert immediately after
# the existing regime_timestamps fetch (current line ~4398-4407, right before the
# "if not regime_timestamps: return" early-exit check already there).
n_estimated = len(regime_timestamps) * len(symbol_list)
_check_cell_size(
    n_estimated, config,
    f"Cross-sectional cell (pre-flight estimate) tf={tf} regime={regime_label}",
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `_check_cell_size` called only after whole-cell materialization | Pre-flight estimate + disk-bounded incremental accumulation | This phase (D-04) | Makes the crash-loud guard actually reachable at Russell-3000 scale; eliminates the recurring "bump the ceiling" workaround pattern (migrations 259, 332) |
| Single `instruments.is_active` boolean | 3-way `is_active` (backfill) / `compute_eligible` / `live_tradeable` split | This phase (D-07) | Prevents a future live-trading restart from silently violating IBKR's 80-subscription cap against a Russell-3000-scale "active" universe |
| Universe grown by hand-picked/ad-hoc symbol additions (111→231, migrations 296/299/301) | Systematic Russell 3000 population + market-cap-stratified random sampling | This phase (D-02) | Removes selection bias from the down-cap hypothesis test; makes the sample's composition auditable/reproducible via an APR-seeded RNG |
| 96GB swapfile stopgap (`/swapfile_iceng`, applied 2026-09-07) | Structural memory fix, swapfile reverted | This phase (D-04), swapfile still present as of this research session (`swapon --show` confirms 96GB at prio 10, 3.5GB currently used) | D-04's own text: "does not survive further scale-up... not a substitute" — the plan should include reverting this after the structural fix lands and is verified |

**Deprecated/outdated:**
- `alpha.ic.max_cell_rows` recalibration-only fixes (migrations 259, 332) — superseded by
  D-04's actual root-cause fix; the key itself stays (it's still the correct final ceiling),
  but it should no longer be the *only* lever touched when a cell grows.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | iShares IWV holdings export is downloadable without authentication and includes (or can derive) per-constituent market cap, not just portfolio weight | Don't Hand-Roll, Open Questions | If the file only exposes weight/shares-held without a market-cap field, the stratification script needs an extra data source (e.g. shares outstanding × price) or a different provider — adds a task, doesn't block the phase |
| A2 | MTUM's expense ratio is ~0.15% (WebSearch results returned AUM/inception cleanly but not expense ratio directly; QUAL confirmed 0.15% from the same iShares factor-suite family) | ETF Gap-Fill (below) — informational only, since momentum/quality no longer need NEW tickers per Critical Correction | Low — this number is not load-bearing for any decision in this phase now that momentum/quality are already in the universe |
| A3 | EMLC (VanEck JPM EM Local Currency Bond ETF) is an acceptable proxy for "EM-FX exposure" despite carrying EM sovereign credit + duration risk layered on top of the currency exposure, versus CEW's purer but much thinner ($15-18M AUM) direct-FX-basket structure | ETF Gap-Fill (below) | If the planner/user wants a currency-only signal free of credit/duration contamination, CEW is the correct pick despite its liquidity risk — this is a real tradeoff requiring a human call, not something research can resolve unilaterally |
| A4 | VIXY (ETF, ProShares) is preferable to VXX (ETN, iPath) as the vol-proxy pick, because VXX's issuer stopped creating new shares in March 2022 and it now persistently trades above fair value | ETF Gap-Fill (below) | If the planner weights raw liquidity/volume more heavily than structural cleanliness, VXX still has the deeper options market and higher daily volume per the WebSearch findings — a reasonable alternative choice |
| A5 | The `dimension="compute"` default proposed for `get_active_contracts()` is behaviorally identical to today's `is_active=true` filter for all 231 existing rows, given the migration sets `compute_eligible=true` for all of them | Architecture Patterns, Pattern 1 | If any existing row exists where `is_active=true` but the row is NOT actually compute-ready (unverified — not checked row-by-row in this session beyond the aggregate count), the new default silently excludes it from every consumer that doesn't pass `dimension=` explicitly; must be covered by a regression test before merging (see Validation Architecture) |

**If this table is empty:** N/A — see rows above; the ic_engine code-path claims (Summary,
Common Pitfalls) and the schema/APR claims (Architecture Patterns, Project Constraints) are
all `[VERIFIED]` via direct code reading and live `psql` queries in this session, not
assumptions.

## Open Questions

1. **Does the iShares IWV holdings file actually expose market cap, or only weight/shares?**
   - What we know: Multiple third-party sources (Barchart, StockAnalysis.com, official
     iShares product page) confirm the full ~2,587-constituent holdings list is downloadable
     as CSV/XLSX, updated near-daily.
   - What's unclear: The exact column schema was not opened/inspected in this research
     session (WebSearch surfaced the sources but did not fetch/parse the file).
   - Recommendation: First execution-time task under D-02 should download the file and
     confirm column availability before designing the stratification script's data-loading
     step. If market cap isn't a direct column, derive it from `weight_pct × fund_AUM /
     shares_held`, or fall back to a secondary free source (e.g. a public market-cap API) for
     just the cap figure while still using IWV for membership.

2. **What is the actual largest feasible instrument count once D-04 ships?**
   - What we know: D-04 removes the RAM ceiling as the binding constraint (peak anon RSS
     becomes chunk-sized, not cell-sized). The remaining known constraints are (a)
     `alpha.ic.max_cell_rows` (currently 15M, itself just a config value, recalibratable),
     and (b) wall-clock runtime — a full `ic_engine` recompute already runs 66-77+ hours at
     231 symbols (`.planning/STATE.md`), and cross-sectional cell row count scales
     roughly linearly with symbol count for a fixed lookback window.
   - What's unclear: Whether wall-clock becomes the new binding constraint before disk I/O
     or the `max_cell_rows` ceiling does, at what symbol count, and whether that's acceptable
     given this is a research/measurement corpus (no live-trading latency requirement).
   - Recommendation: Do not pick a final N_target in planning. Instead, plan for D-04's fix
     to be verified first against the already-known-problematic cell (182-symbol
     `5m/high_bear`, previously OOM-killed), then run one incremental scale-up test (e.g. 400
     symbols) measuring both memory (should now be flat/bounded) and wall-clock delta, before
     committing to the Russell-3000-sample's final size. This directly answers D-01's
     "largest feasible count" empirically rather than by estimate.

3. **Does `instruments.is_active=true` for all 231 rows genuinely mean "compute-ready" for
   every row, or are there rows mid-onboarding / still accumulating history?**
   - What we know: `get_active_contracts()`'s current single query is the only gate every
     compute consumer uses today, so by definition nothing downstream currently distinguishes
     these states.
   - What's unclear: Whether any of the 231 have a data-quality/history-depth issue that
     would make `compute_eligible=true` (the proposed default) actually wrong for a specific
     row.
   - Recommendation: A one-time audit query (row count / earliest bar_ts per symbol vs. some
     minimum-history threshold) as a verification step before the D-07 migration ships,
     rather than assuming uniformity.

4. **Should `eq_factor` be split into `eq_momentum`/`eq_quality`/`eq_low_vol` given the
   Critical Correction above, or is the existing coarse tag sufficient?**
   - What we know: `MTUM`, `QUAL`, `USMV` currently share the single `eq_factor` tag, along
     with `BTAL` (market-neutral) and `SPHB` (high-beta) — 5 structurally different
     strategies under one label.
   - What's unclear: Whether any live consumer needs factor-specific stratification (checked
     ITR doc's three live readers — `equity_regime_model.py`, `cross_sectional_regime_model.py`,
     `ic_engine.py` — all key off `eq_*`/`intl_*` prefixes generically, not `eq_factor`
     specifically; no evidence a finer split is currently load-bearing).
   - Recommendation: Treat as optional hygiene, not required for this phase's core goal
     (breadth scaling). If the planner wants it, it's a 3-row `tag_vocabulary` INSERT + a
     few `instrument_tags` re-tags, trivially cheap to bundle in with D-08's other
     onboarding-hygiene work.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL/TimescaleDB | All of D-02/D-04/D-07/D-08 | ✓ | live, verified via `psql` this session | — |
| Disk headroom (scratch space for memmap files + new backfill data) | D-04 (memmap scratch), D-02 (new OHLCV rows) | ✓ | 568GB free (`df -h /`, verified this session, matches STATE.md's 569GB claim) | — |
| RAM | D-04 (should become less binding after the fix) | ✓ (partial) | 29GB total, 3GB free / 23GB available (buff/cache-reclaimable), verified this session | 96GB swapfile still present as stopgap (`/swapfile_iceng`, 3.5GB currently used) — D-04's fix should reduce reliance on this, not require more of it |
| `ib-gateway` Docker container | D-02/D-06 backfill (historical data fetch requires a live Gateway/TWS connection even though not subject to the 80-subscription streaming cap) | ✗ | `Exited (1) 7 days ago` (verified via `docker ps -a` this session) | Restart before any backfill task: `docker compose up -d` from `production/` per root CLAUDE.md's Infrastructure section |
| iShares IWV holdings download | D-02 (Russell 3000 population sourcing) | Not verified live this session (WebSearch only) | — | If unavailable/rate-limited, third-party re-publications exist (Barchart, StockAnalysis.com) as fallback sources for the same underlying data |
| numpy `np.memmap` | D-04 | ✓ | 2.4.6 installed, stdlib feature, no version constraint | — |

**Missing dependencies with no fallback:** None — `ib-gateway` has a clear, cheap fallback
(restart the container).

**Missing dependencies with fallback:**
- `ib-gateway` container (restart via `docker compose up -d`).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 6.0+, `pytest-asyncio` (`asyncio_mode=auto`), config at `pytest.ini` |
| Config file | `/home/bg/dev/indicagent/pytest.ini` |
| Quick run command | `.venv/bin/pytest tests/unit/test_batch_utils.py tests/unit/test_ic_engine_compute_split.py -v` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| D-04a | Pre-flight estimate raises `CellTooLargeError` before any chunk fetch when `len(regime_timestamps) * len(symbol_list) > max_cell_rows` | unit | `pytest tests/unit/test_ic_engine_checkpoint_key.py -k cell_size -x` (new test file likely needed — see Wave 0 Gaps) | ❌ Wave 0 |
| D-04b | `Float32ChunkAccumulator(disk_backed=True)` produces row-identical output to the existing in-RAM mode for the same input chunks | unit | `pytest tests/unit/test_batch_utils.py -k disk_backed -x` | ❌ Wave 0 |
| D-04c | Peak process RSS during a synthetic large-cell accumulation stays bounded (≈ chunk size, not cell size) | integration/performance | a `tracemalloc`/`resource.getrusage(RUSAGE_SELF).ru_maxrss` assertion around a synthetic accumulation of N chunks | ❌ Wave 0 — needs a new perf-marked test, `@pytest.mark.performance` |
| D-07a | `get_active_contracts(dimension="compute")` returns the identical symbol set as today's unparameterized call, for all 231 existing rows | unit/regression | `pytest tests/unit/test_settings_active_contracts.py -x` (file does not yet exist — check `tests/unit/` for the current settings test file name at execution time) | ❌ Wave 0 |
| D-07b | `get_active_contracts(dimension="live")` returns empty (no `live_tradeable=true` rows exist yet by design) | unit | same new test file | ❌ Wave 0 |
| D-08 | Newly onboarded instrument writes a non-null `instrument_metadata` row, or an explicit skip is logged | unit | new test asserting the onboarding script's write path | ❌ Wave 0 |
| D-02 | Stratified sample RNG is reproducible given the same APR seed | unit | new test seeding `alpha.universe.stratified_sample_random_state` and asserting identical output symbol list across two runs | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** the relevant narrow test file(s) from the map above.
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -q` (must stay green — this project's
  standing CI gate).
- **Phase gate:** Full suite green before `/gsd:verify-work`, plus a manual execution-time
  re-run of the previously-OOM'd 182-symbol `5m/high_bear` cell under the new disk-bound path
  to empirically confirm D-04's fix before any Russell-3000-scale backfill/compute proceeds.

### Wave 0 Gaps
- [ ] A new unit test file for the pre-flight `_check_cell_size` estimate path (no existing
      test targets this specific code path — confirmed via `tests/unit/` listing this
      session; closest existing coverage, `test_ic_engine_compute_split.py`, tests the
      post-materialization check only).
- [ ] `tests/unit/test_batch_utils.py` needs new `disk_backed=True` cases added alongside its
      existing `Float32ChunkAccumulator` coverage.
- [ ] A test file (new or extending an existing `settings.py` test, name TBD at execution
      time — grep `tests/unit/` for `get_active_contracts` coverage first) for the
      `dimension=` parameter and its default-equivalence guarantee (Assumption A5 above).
- [ ] A test for the stratified-sampling script's reproducibility given a fixed APR-seeded RNG.
- [ ] No perf/memory-bounded test infrastructure currently exists for ic_engine's memory
      behavior (`@pytest.mark.performance` marker is registered in `pytest.ini` but not
      currently exercised for this module) — Wave 0 should add one.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | This phase has no auth surface — internal batch/schema work only |
| V3 Session Management | No | N/A |
| V4 Access Control | No | N/A — no new API endpoints |
| V5 Input Validation | Yes | New instrument symbols sourced from the Russell 3000 file must be validated against IBKR's existing `qualify_instrument()` contract-resolution path before any DB write, not inserted directly from the downloaded file's raw ticker strings — a malformed or unexpected ticker string should fail loud at qualification, not silently corrupt `instruments`/`contract_details` JSONB |
| V6 Cryptography | No | N/A — no secrets/crypto touched by this phase |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via a downloaded-CSV-sourced ticker string interpolated into a migration or onboarding script | Tampering | Existing project convention already uses parameterized queries everywhere touched by this research (`chunk_sql`'s `%(...)s` placeholders in `ic_engine.py`, confirmed via direct code read) — the new onboarding script must follow the same pattern, never f-string-interpolate a symbol into raw SQL |
| Untrusted external file (IWV holdings export) used to drive bulk DB writes | Tampering | Parse defensively (schema/type validation on each row before use), and route every new symbol through `qualify_instrument()`'s existing IBKR-contract-resolution check as a de facto allowlist — a ticker that doesn't resolve to a real IBKR contract is rejected before it reaches `instruments` |

## Sources

### Primary (HIGH confidence — direct code/DB verification this session)
- `services/ic_engine.py` (read directly, lines 250-260, 620-650, 1000-1030, 3540-3700,
  4280-4600) — `_check_cell_size`, `_compute_one_cross_sectional_cell`,
  `_compute_cross_sectional_tf`'s fetch/accumulate loop.
- `services/_batch_utils.py` (read directly, lines 1029-1074) — `Float32ChunkAccumulator`.
- `src/config/settings.py` (read directly, lines 460-560) — `get_active_contracts()`.
- `src/providers/CLAUDE.md` (read directly) — 80-subscription cap scope, IBKR backfill
  mechanics, chunk-size/rate-limit APR keys.
- `docs/foundation/adaptive-parameter-registry.md`, `docs/foundation/instrument-tag-registry.md`,
  `docs/foundation/performance-investigation-sop.md` (all read directly).
- Live PostgreSQL queries this session (`psql -U postgres -h localhost -d indicagent`):
  `instruments`, `instrument_tags`, `tag_vocabulary`, `backfill_status`, `instrument_metadata`
  schemas and row counts; MTUM/QUAL/USMV verification; `fx_*`/vol-ETF absence verification;
  hypertable-membership check (none of the touched tables are hypertables).
- `docker ps -a`, `swapon --show`, `free -h`, `df -h /` (run directly this session) —
  environment availability.
- `.planning/todos/pending/{371,274,282,376,377}-*.md` (read in full).
- `.planning/phases/174-.../174-CONTEXT.md`, `174-DISCUSSION-LOG.md`, `.planning/STATE.md`
  (read in full).

### Secondary (MEDIUM confidence — WebSearch, cross-referenced across multiple results)
- iShares IWV holdings download sources (ishares.com official page, Barchart, StockAnalysis.com,
  Intrinio) — membership/methodology existence confirmed by multiple independent sources;
  exact file schema not hands-on verified this session.
- MTUM/QUAL inception dates and AUM (iShares fact sheets, multiple aggregator sites) —
  informational only now, given the Critical Correction moots the need to add these tickers.
- QUAL expense ratio (0.15%) — multiple sources agree.
- VXX/VIXY/UVXY structural comparison (ETN vs ETF, VXX's March-2022 share-creation halt) —
  multiple independent sources (etfdb.com, projectfinance.com) agree on the structural facts.
- EMLC vs CEW expense ratio (0.30% vs 0.55%) and AUM comparison — cross-referenced across
  2 WebSearch queries, consistent.

### Tertiary (LOW confidence — single-pass WebSearch, not independently cross-verified)
- VIXY's exact expense ratio (0.85%) and AUM ($202.7M) — sourced from a single ProShares
  fact-sheet-derived search result; directionally reasonable (matches known VIX-ETF expense
  ratios generally) but not cross-verified against a second independent source this session.

## Metadata

**Confidence breakdown:**
- ic_engine OOM fix design (D-04): HIGH — verified by direct code reading against the actual
  running module, not description-only; found an additional defeat point beyond what todo
  371 documented.
- Instrument governance schema (D-07/D-08): HIGH — verified against live DB schema, confirmed
  no hypertable/compression concerns, confirmed all ~25 call sites via grep.
- Critical Correction (momentum/quality): HIGH — directly falsified via live DB query, not
  inference.
- ETF ticker recommendations (EM-FX, vol proxy): MEDIUM — WebSearch-sourced financial
  specifics (expense ratios, AUM), cross-referenced across 2+ sources where noted, single-
  source where flagged; the underlying absence-of-existing-coverage claim itself is HIGH
  (live DB verified).
- Russell 3000 sourcing methodology (D-02): MEDIUM — the IWV-holdings-as-source approach is
  standard practice, multiply-corroborated by search, but not hands-on file-schema-verified
  this session (see Open Question 1).
- Stratification scheme specifics (decile count, sample-size formula): MEDIUM — reasoned from
  first principles per CONTEXT.md's own "council of senior engineers" instruction, not
  benchmarked against an external stratified-sampling methodology reference.

**Research date:** 2026-09-15
**Valid until:** 14 days for the ic_engine/schema findings (stable, code-verified, low churn
risk); 7 days for the ETF ticker specifics (expense ratios/AUM drift, though structural facts
like ETN-vs-ETF and inception dates are stable) — re-verify live pricing/liquidity data
immediately before finalizing ticker selection in planning, don't rely on this document's
numbers if planning happens more than a week out.
