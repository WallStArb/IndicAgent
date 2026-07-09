# Phase 142B: Frame Simulation + Counterfactual Tracking - Research

**Researched:** 2026-07-09
**Domain:** TimescaleDB batch compute (BaseBatch oneshots), counterfactual P&L simulation, bootstrap statistics
**Confidence:** HIGH (all load-bearing claims verified directly against live DB schema, live row counts, and current source code — no library/framework unknowns; this phase is 100% internal-codebase pattern replication)

## Summary

Phase 142B builds two `BaseBatch` oneshot services (`AlphaFrameWriter`, `CounterfactualTracker`)
that together turn `alpha_events` rows into hypothetical stop/target/hold positions and score
their counterfactual outcome. Every piece of "how do I build this" is answered by a sibling
service already in this codebase — there is no new library, no new architecture, and no external
API to learn. The two open technical questions flagged in CONTEXT.md are both now resolved by
direct verification: (1) `sr_support_dist`/`sr_resist_dist` are still 100% NULL across all
36,719,598 `feature_vectors` rows — the 142.5 Renaissance primitives work did not touch these
columns, so the schema doc's "ATR fallback is the primary path" note is current fact, not stale;
(2) the `alpha_frames` table does not exist yet in the live DB (confirmed via `\dt`), so this
phase's migration is the only thing that creates it — there is no pre-existing table shape to
reconcile against, only the 2026-06-25 design doc's DDL (as corrected by CONTEXT.md D-04).

The scale this phase must handle is concrete and already measured: 12,258,206 `alpha_events`
rows across 78 (symbol, tf) partitions, spanning 2007-07-25 to 2026-07-07. This is the same
order of magnitude `alpha_publisher.py` already writes (its target table) and `ic_engine.py`/
`ensemble_ic_engine.py` already read at (their source tables) — both of those services hit real
OOM/deadlock bugs at this scale in the last two weeks and both fixes are now committed code,
not folklore. `AlphaFrameWriter` should copy `alpha_publisher.py`'s chunk-accumulate-flush
pattern almost verbatim (it is a DB→DB batch writer at the same row-count order of magnitude).
`CounterfactualTracker` should copy `ensemble_ic_engine.py`'s `ProcessPoolExecutor`
per-symbol-dispatch + read-only-worker-connections + single-serial-write pattern, and must use a
**named (server-side) psycopg2 cursor**, never a plain `conn.cursor()`, for any per-symbol bar
scan — the plain-cursor OOM bug was independently discovered and fixed twice in the last 48 hours
in `ic_engine.py` (commit `e9b3bcde`) and was already avoided in `ensemble_ic_engine.py`'s pooled
fetch (migration 209). A third occurrence of this exact bug shape in `CounterfactualTracker`
would be a known, avoidable regression.

Two migration-scope gaps were found that are not visible from ROADMAP.md/CONTEXT.md alone:
`alpha.frame.stop_atr_mult`, `alpha.frame.target_r_fallback` (or `target_r_multiple` — naming
conflict, see Pitfall 3), `alpha.frame.grid_stop_atr_mults`, and **all** `alpha.scoring.*` keys
(including `alpha.scoring.min_strategy_n`, which FRAME-04's gate directly depends on) do not
exist in `config_schema`/`config_state` today — only the 36 `alpha.frame.hold_max_bars.<regime>.<tf>`
keys from Phase 142A's migration 195 exist. This phase's migration must seed all of them; it
cannot assume Phase 144 will do it, because FRAME-04 (this phase's own gate) reads
`alpha.scoring.min_strategy_n` before Phase 144 exists.

**Primary recommendation:** Build both services as thin, pattern-following `BaseBatch`
subclasses — `AlphaFrameWriter` mirrors `alpha_publisher.py`'s single-pass chunked-write shape;
`CounterfactualTracker` mirrors `ensemble_ic_engine.py`'s ProcessPoolExecutor +
named-server-side-cursor shape. Use `scipy.stats.bootstrap` (already installed, v1.17.1) for
FRAME-04's bootstrap CI — do not hand-roll a bootstrap mean-CI routine; no such helper exists yet
in `ic_math.py` (which only has Fisher-z correlation CIs, a different statistic).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Frame geometry computation (entry/stop/target/hold from alpha_events + feature_vectors) | Database / Storage (batch compute) | — | Pure batch compute reading two tables, writing one; no API/UI involvement, matches `AlphaFrameWriter`'s FRAME-01 scope exactly |
| Price-path scanning + lifecycle state transitions | Database / Storage (batch compute) | — | `CounterfactualTracker` reads `market_data_ohlcv` bars and `alpha_ensemble_ic`, writes `alpha_frames` updates; no live/streaming component |
| SHADOW-REVIEW.md pre-commitment document | N/A (static doc, no runtime tier) | — | A frozen-before-data-collection markdown file, not code; must exist in git before either service's first production run |
| Bootstrap CI / gate evaluation (FRAME-04) | Database / Storage (batch compute, likely inside `CounterfactualTracker` or a small follow-on script) | — | Reads closed `alpha_frames`, no external dependency beyond scipy |
| Service registration (DAG order, lag alerting) | Ring 2 (`services/`) infra glue | — | `service_auditor.py`/`stream_keys.py` are cross-cutting registries, not domain logic |

No Browser/Client, Frontend Server, or CDN tier involvement anywhere in this phase — it is
entirely Database/Storage-tier batch compute, consistent with every other Phase 138-142A service.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FRAME-01 | `AlphaFrameWriter` (nightly oneshot, `BaseBatch`) writes one `alpha_frames` row per `alpha_events` row with frame geometry (stop/target/hold) | `BaseBatch` lifecycle documented below; `alpha_publisher.py` chunked-write pattern is the template; ATR-fallback-is-primary confirmed empirically (`sr_support_dist`/`sr_resist_dist` 100% NULL) |
| FRAME-02 | `CounterfactualTracker` (nightly oneshot, `BaseBatch`) scans price paths, writes lifecycle outcomes via range query + `ProcessPoolExecutor` | `ensemble_ic_engine.py`'s worker-dispatch + named-cursor pattern is the template; `market_data_ohlcv` schema documented below |
| FRAME-03 | Frame lifecycle state machine: `open → closed_stop \| closed_target \| closed_max_hold \| closed_ic_decay` | D-04's corrected CHECK constraint documented in full below; schema doc's literal SQL (with `closed_reversal`) is superseded on this point only |
| FRAME-04 | Exit gate: `mean(counterfactual_pnl_r) > 0` at 95% CI (bootstrap) on in-sample closed frames, N ≥ `alpha.scoring.min_strategy_n` per (tf, regime) | `scipy.stats.bootstrap` recommended (no existing helper); `alpha.scoring.min_strategy_n` does NOT yet exist in config_schema — must be seeded by this phase's migration, not deferred to Phase 144 |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `asyncpg` | already pinned in project | Async DB pool, batch writes | Every `BaseBatch` subclass in this codebase uses it exclusively for the write side |
| `psycopg2` | already pinned in project | Named (server-side) cursors inside `ProcessPoolExecutor` workers | `ic_engine.py`/`ensemble_ic_engine.py` both use psycopg2, not asyncpg, inside subprocess workers — asyncpg pools are not fork-safe across `ProcessPoolExecutor` boundaries; this is the established pattern, not a new choice |
| `scipy.stats.bootstrap` | 1.17.1 (confirmed installed) `[VERIFIED: local venv]` | FRAME-04's bootstrap CI on `mean(counterfactual_pnl_r)` | Built into already-installed scipy; a hand-rolled bootstrap-mean-CI would duplicate stdlib-grade statistics for zero benefit — see Don't Hand-Roll |
| `structlog` | already pinned | Logging (`setup_service_logging`) | Inherited automatically via `BaseBatch.__init__` |
| OTel SDK (`src/observability/metrics.py`) | already pinned | D-06 `job_completed_total`, D-10 IC-staleness gauge | Direct OTel SDK, not `prometheus_client` (CLAUDE.md invariant) |

No new third-party package is needed for this phase. **Package Legitimacy Audit is not
applicable** — zero new external dependencies are introduced.

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `numpy` | already pinned | ATR/stop-distance arithmetic, float32 arrays for chunked bar scans | Already used identically in `ic_engine.py`'s chunked-cursor fix |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `scipy.stats.bootstrap` | Hand-rolled percentile bootstrap (`np.random.choice` + loop) | No accuracy or performance benefit; scipy's implementation already handles BCa/percentile method selection and is the codebase's existing scipy dependency — hand-rolling here would be exactly the "Don't Hand-Roll" anti-pattern the project's own doctrine warns against |
| Named psycopg2 cursor for `CounterfactualTracker`'s bar scan | asyncpg `conn.cursor()` with `prefetch=` (as `alpha_publisher.py` uses) | asyncpg cursors are usable only on the main-process pool connection, not inside `ProcessPoolExecutor` subprocess workers (which use psycopg2 per `ic_engine.py`/`ensemble_ic_engine.py` precedent) — if `CounterfactualTracker` is NOT parallelized per-symbol (single-process design), asyncpg's cursor is a legitimate simpler alternative; if it IS parallelized (as ROADMAP FRAME-02 specifies via `ProcessPoolExecutor`), psycopg2 named cursors inside workers is the only proven-safe pattern in this codebase |

**Installation:** none required — no new packages.

## Package Legitimacy Audit

Not applicable. This phase introduces zero new third-party packages; every library used is
already installed and already load-bearing elsewhere in the codebase (`asyncpg`, `psycopg2`,
`scipy`, `numpy`, `structlog`). Skipping the slopcheck/registry-verification gate is correct here
per the protocol's own scope ("whenever this phase installs external packages") — none are
installed.

## Architecture Patterns

### System Architecture Diagram

```
alpha_events (12,258,206 rows, 78 symbol/tf partitions, 2007-07-25 .. 2026-07-07)
      │
      │  FRAME-01: AlphaFrameWriter (BaseBatch, nightly oneshot / --backfill)
      │  - one INSERT per alpha_events row: frame_variant='primary'
      │  - stop  = entry_price - stop_atr_mult × ATR              (feature_vectors)
      │  - target = ATR fallback only (sr_resist_dist always NULL — verified)
      │  - hold  = alpha.frame.hold_max_bars.<regime>.<tf>        (APR, 142A-calibrated)
      ▼
alpha_frames (status='open', geometry columns NULL until T+1 open observed)
      │
      │  FRAME-02: CounterfactualTracker (BaseBatch, nightly oneshot / --backfill)
      │  Wave A — geometry fill:
      │    fetch T+1 open per open frame → entry_price/stop_price/target_price/r_multiple
      │  Wave B — outcome scan (ProcessPoolExecutor, one worker per symbol):
      │    named server-side cursor over market_data_ohlcv, range-scoped per (symbol, tf,
      │    bar_ts .. bar_ts + max_hold_bars)
      │    exit triggers, priority order:
      │      1. low <= stop_price          → closed_stop
      │      2. high >= target_price       → closed_target
      │      3. bars_elapsed >= hold_max   → closed_max_hold
      │      4. alpha_ensemble_ic.ic_ci_lower < 0 (age unbounded, logged) → closed_ic_decay
      │  Workers return list[dict] (serializable) — main process does ONE serial
      │  async batch UPDATE (never a worker DB write; DAG invariant #3)
      ▼
alpha_frames (status closed_*, counterfactual_pnl_r/mfe/mae/bars/exit_reason populated)
      │
      │  FRAME-04: exit gate (bootstrap CI on mean(counterfactual_pnl_r),
      │  in-sample only: bar_ts < alpha.validation.oos_start, N >= alpha.scoring.min_strategy_n
      │  per (tf, regime) cell)
      ▼
   PASS → Phase 143 begins; OOS frames accumulate toward SHADOW-REVIEW.md criteria
   FAIL → diagnose frame geometry (stop/target/hold calibration), not signal quality
```

### Recommended Project Structure

```
services/
├── alpha_frame_writer.py         # AlphaFrameWriter(BaseBatch) — FRAME-01
├── counterfactual_tracker.py     # CounterfactualTracker(BaseBatch) — FRAME-02/03
production/migrations/
└── 214_alpha_frames_schema.sql   # alpha_frames table + alpha.frame.*/alpha.scoring.* APR keys
                                   # (next free migration number after 213)
docs/plans/
└── SHADOW-REVIEW.md              # frozen pre-commitment doc, written before first prod run
tests/unit/
├── test_alpha_frame_writer.py
├── test_alpha_frame_writer_geometry.py   # pure-fn stop/target/hold math, no DB
├── test_counterfactual_tracker.py
├── test_counterfactual_tracker_exit_priority.py  # pure-fn exit-trigger priority order
└── test_alpha_frames_schema.py           # migration/DDL assertions (mirrors test_ensemble_ic_config.py style)
```

### Pattern 1: BaseBatch lifecycle (mandatory for both new services)

**What:** `run()` template method — `_setup_pool()` → `execute(pool)` → `_emit_completion()`
(always, even on failure) → `_teardown_pool()` → `flush_and_shutdown_metrics()`.
**When to use:** Both `AlphaFrameWriter` and `CounterfactualTracker` extend `BaseBatch` directly
(ROADMAP explicitly specifies this). Set `job_name` (kebab-case, must match systemd unit `%n`)
and `compute_version` as class attributes; implement only `async def execute(self, pool)`.
**Example (from `src/core/agent/base_batch.py`, verified in full):**
```python
# Source: src/core/agent/base_batch.py (read in full 2026-07-09)
class BaseBatch(abc.ABC):
    job_name: str
    compute_version: str

    async def run(self) -> None:
        await self._setup_pool()
        t0 = time.monotonic()
        status = "success"
        try:
            await self.execute(self._pool)
        except Exception as error:
            status = "failure"
            self.logger.error("batch_computer.failed", job=self.job_name, error=str(error))
            raise
        finally:
            self._emit_completion(status, time.monotonic() - t0)
            await self._teardown_pool()
            flush_and_shutdown_metrics()

    @staticmethod
    def content_key(*parts: str) -> str:
        raw = "|".join(str(p) for p in parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]
```
`content_key()` gives a deterministic `frame_id` alternative to `gen_random_uuid()` — recommend
`AlphaFrameWriter` use `BaseBatch.content_key(event_id, str(bar_ts), frame_variant)` for `frame_id`
so a re-run of the writer against the same `alpha_events` row is naturally idempotent via
`ON CONFLICT (event_id, bar_ts, frame_variant) DO NOTHING`, mirroring `alpha_publisher.py`'s
`event_id` derivation exactly. This is the planner's call per CONTEXT.md ("content-addressable
IDs... planner's call") — recommend taking it, since every other Phase 138+ writer in this
codebase already does.

D-06 contract: `_emit_completion()` calls `JOB_COMPLETED_TOTAL.add(1, {"job": self.job_name,
"status": status})` automatically — no per-service code needed for this metric.

### Pattern 2: Chunked accumulate-and-flush batch write (AlphaFrameWriter template)

**What:** Stream source rows via a query, accumulate output tuples in a Python list, flush via
`executemany()` every N rows, avoiding one giant in-memory list for 12M+ rows.
**When to use:** `AlphaFrameWriter`'s single-pass write over the full `alpha_events` backlog.
**Example (from `services/alpha_publisher.py`, read in full):**
```python
# Source: services/alpha_publisher.py:72,225-229,345-374 (verified 2026-07-09)
_CHUNK_SIZE = 50_000
_chunk: list[tuple] = []
async for row in conn.cursor(SQL, *params, prefetch=10000):
    _chunk.append(row_to_tuple(row))
    if len(_chunk) >= _CHUNK_SIZE:
        async with pool.acquire() as wconn:
            await wconn.executemany(_INSERT_SQL, _chunk)
        _chunk.clear()
if _chunk:
    async with pool.acquire() as wconn:
        await wconn.executemany(_INSERT_SQL, _chunk)
```
Note: `conn.cursor(SQL, prefetch=10000)` here is **asyncpg's** cursor (a server-side portal under
the hood) — this is safe and already streams correctly; it is NOT the same object as psycopg2's
plain `conn.cursor()`, which is the thing that caused the OOM bug in `ic_engine.py`. Do not
conflate the two when reviewing/planning — asyncpg async cursors used from the main process are
fine as-is; the bug class is specific to unnamed psycopg2 cursors used for large fetches
(typically inside `ProcessPoolExecutor` workers, where psycopg2 rather than asyncpg is used —
see Pattern 3).

### Pattern 3: ProcessPoolExecutor per-symbol dispatch with named server-side cursors (CounterfactualTracker template)

**What:** One worker task per symbol (not per (symbol, tf) pair — amortizes connection setup
across a symbol's TFs). Each worker opens its own **read-only** `psycopg2` connection, uses a
**named (server-side) cursor** with `itersize` for any large per-symbol fetch, and returns
`list[dict]` rows. The main process does exactly one serial async batch write after all workers
complete — no worker ever opens a write connection or calls `commit()` for a write (DAG invariant
#3: "workers are compute-only").
**When to use:** `CounterfactualTracker`'s price-path scan across up to ~392K bars per symbol/tf
cell (the exact scale that OOM'd `ic_engine.py` before the fix).
**Example (from `services/ensemble_ic_engine.py`, read in full; and `ic_engine.py`'s
commit `e9b3bcde` fix):**
```python
# Source: services/ensemble_ic_engine.py:710-720 (verified 2026-07-09) — named cursor
# pattern for a per-symbol/per-tf large fetch inside a ProcessPoolExecutor worker.
conn.commit()  # clear any open transaction before declaring a named cursor (required precondition)
with conn.cursor(
    name=f"pooled_fetch_{tf}", cursor_factory=psycopg2.extras.RealDictCursor
) as cur:
    cur.itersize = config.pooled_fetch_itersize
    cur.execute(SQL, params)
    fetched = _aggregate_pooled_series(cur, tf)   # reduce-as-you-go, never fetchall()

# Source: services/ic_engine.py (post-commit e9b3bcde, verified via git show)
# Chunked conversion to typed numpy arrays — only the WIDE columns need chunking;
# scalar columns (bar_ts, regime) stay as cheap flat lists even at 400K+ rows.
X_chunks: list[np.ndarray] = []
buf_X: list = []
with conn.cursor(name=f"fv_{symbol}_{tf}") as cur:
    cur.itersize = config.symbol_fetch_chunk_rows  # APR: infra.ic_engine.symbol_fetch_chunk_rows, default 5000
    cur.execute(fv_sql, (symbol, tf, training_window_end))
    for r in cur:
        bar_ts_list.append(r[0]); regime_list.append(r[1])
        buf_X.append(r[2:])
        if len(buf_X) >= config.symbol_fetch_chunk_rows:
            X_chunks.append(np.array(buf_X, dtype=np.float32)); buf_X = []
    if buf_X:
        X_chunks.append(np.array(buf_X, dtype=np.float32))
X_raw = np.vstack(X_chunks)
```
**Critical warning (verified via `git show e9b3bcde`):** a *plain* `conn.cursor()` in psycopg2
pulls the **entire** result set across the wire into a client-side buffer at `execute()` time
regardless of how the Python side iterates it afterward — `itersize` is a no-op on an unnamed
cursor. Only a **named** cursor (`conn.cursor(name=...)`) actually streams server-side in
`itersize`-sized batches. This exact confusion (an inline comment incorrectly claiming
"itersize-based streaming" on a plain cursor) caused a 4.3 GB-per-worker OOM that crashed the
last two corpus rebuild attempts. `CounterfactualTracker`'s bar-path scan MUST use a named
cursor from the start — do not repeat this mistake a third time (todo 087 already tracks that
this idiom has now been hand-rolled three times; consider whether `CounterfactualTracker` should
be the fourth occurrence or the first consumer of a shared helper, per that todo — not blocking,
opportunistic).

### Pattern 4: --backfill mode as a query-scope switch, not a separate code path

**What:** D-05 requires a `--backfill` CLI flag on both services. The IBKR historical backfill
script's mechanics (gap-detection via `detect_gaps()`, per-chunk persistence via an `on_chunk`
callback, connection-staleness check before each symbol, idempotent `ON CONFLICT DO NOTHING`)
are the cited precedent, but that script's specific gap-detection logic is IBKR-network-fetch
specific and not directly portable. The **generalizable** pattern to replicate for these two
DB-to-DB batch services is:
1. **Anti-join for "what's missing"** instead of date-range gap detection: `AlphaFrameWriter`'s
   backfill query is `SELECT ae.* FROM alpha_events ae LEFT JOIN alpha_frames af ON af.event_id =
   ae.event_id AND af.bar_ts = ae.bar_ts AND af.frame_variant = 'primary' WHERE af.frame_id IS
   NULL` — this makes nightly-incremental and `--backfill` the *same query*, just run against a
   different pending set. This is what makes D-05's claim true ("`--backfill` is a mode switch,
   not a structurally distinct code path").
2. **Chunk and flush incrementally** (Pattern 2 above) rather than holding one long transaction —
   satisfies D-05's "must not hold long-running write transactions" constraint directly; the
   IBKR script's per-chunk persist callback is functionally the same idea applied to a different
   I/O boundary (network fetch vs. DB batch write).
3. **Idempotent writes via `ON CONFLICT DO NOTHING`/`DO UPDATE`** so a killed-and-restarted
   backfill run never double-writes or corrupts state — same idiom `alpha_publisher.py` and
   `ensemble_ic_engine.py` both already use.
4. **Connection-staleness check** before each unit of work (symbol, in the IBKR script's case) —
   directly portable: check `SELECT 1` and reconnect on failure before each per-symbol chunk in
   `CounterfactualTracker`'s worker dispatch loop, exactly as
   `infrastructure_run_historical_pipeline.py:1044-1052` does.

**When to use:** Both services' `--backfill` flag. `AlphaFrameWriter`'s backfill is a single wide
SQL statement (anti-join + chunked flush, no parallelism needed — it's a light per-row geometry
computation, not a bar scan). `CounterfactualTracker`'s backfill additionally needs
`ProcessPoolExecutor` (Pattern 3) since its workload is the heavy one (scanning up to
`hold_max_bars` subsequent bars per open frame, 12M+ frames at full backlog scale).

### Anti-Patterns to Avoid

- **Plain (unnamed) psycopg2 cursor for any fetch that could exceed a few thousand rows** — see
  Pattern 3's critical warning. This has already caused two real production OOM incidents in the
  last two weeks in sibling code.
- **Worker processes writing to the DB** — DAG invariant #3 (`CLAUDE.md`): "A compute daemon
  never writes its own computed output." `CounterfactualTracker`'s `ProcessPoolExecutor` workers
  must return `list[dict]`; the single serial write happens in the main process after
  `exe.map()` completes, exactly like `ensemble_ic_engine.py`.
- **Treating `alpha.frame.target_r_fallback` (schema doc name) and `alpha.frame.target_r_multiple`
  (ROADMAP FRAME-01 name) as two different keys** — see Pitfall 3. Pick one name in the migration
  and use it consistently; do not seed both.
- **Gating the IC-decay exit trigger on `alpha_ensemble_ic` freshness** — D-08 explicitly forbids
  this. Read the most recent row regardless of age; only log/instrument the age (D-10).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Bootstrap CI on `mean(counterfactual_pnl_r)` for FRAME-04 | A hand-rolled percentile-bootstrap loop (`for _ in range(N): np.random.choice(...)`) | `scipy.stats.bootstrap` (confirmed installed, v1.17.1) with `method='percentile'` or `'BCa'`, `alternative='greater'` for the one-tailed test | scipy's implementation is vectorized, handles edge cases (degenerate resamples, CI method selection) correctly, and is already a project dependency — this is exactly the class of "deceptively complex, existing solution available" problem the project's own doctrine (`ic_math.py`'s existence as a shared statistics module) already establishes a precedent against re-deriving |
| Named-cursor + chunked-numpy-array streaming for large per-symbol fetches | A fourth independent hand-rolled implementation of this idiom | Consider consulting/reusing the pattern already coded 3x (`ic_engine.py::_compute_cross_sectional_tf`, `ic_engine.py::_compute_symbol_tf`, `ensemble_ic_engine.py`'s pooled worker) — todo 087 already flags this as ripe for a shared `services/_batch_utils.py` helper. Not blocking for this phase, but do not add a 4th bespoke implementation without at least checking todo 087 first |
| `--backfill` checkpoint/resume logic | A custom checkpoint-file or offset-tracking mechanism | Anti-join query against the target table itself (Pattern 4) — the target table (`alpha_frames`) IS the checkpoint; no separate state file needed, and it's naturally correct after a crash (a partially-written backfill just leaves fewer anti-join misses for the next run to pick up) |

**Key insight:** Every hard sub-problem in this phase (streaming large fetches without OOM,
chunked idempotent writes, bootstrap CI, worker-pool DB-write discipline) has already been solved
correctly in this exact codebase within the last two weeks. The engineering risk in 142B is not
algorithmic — it's fidelity to precedent. Deviating from these patterns (e.g., a plain cursor, a
hand-rolled bootstrap, a worker that writes) reintroduces bugs that were expensively found and
fixed elsewhere in this same codebase.

## Common Pitfalls

### Pitfall 1: `sr_support_dist`/`sr_resist_dist` NULL assumption drift
**What goes wrong:** Assuming Phase 142.5's Renaissance primitives work populated these columns
(they didn't — they're a different set of primitives entirely) and building frame geometry logic
that reads them as a real signal, silently getting `NULL` for every row and producing wrong
targets.
**Why it happens:** The columns exist in the schema (`\d feature_vectors` shows both as
`double precision`, nullable, no default) — their mere presence in the schema invites the
assumption they're populated. They are not computed by any current pipeline stage.
**How to avoid:** Verified directly: `SELECT count(sr_support_dist), count(sr_resist_dist) FROM
feature_vectors` → both `0` out of `36,719,598` total rows (query run 2026-07-09). `AlphaFrameWriter`
must treat the ATR-based fallback as the **sole** target-price path, not a fallback branch that
sometimes doesn't fire — it always fires. Simplify the planned code accordingly: no
`IF sr_resist_dist IS NOT NULL` branch is needed; just implement the ATR path.
**Warning signs:** If `target_price` computation logic contains a conditional on `sr_resist_dist`,
that branch is dead code paths that will never execute against the current corpus — fine to leave
for future-proofing, but must not be load-bearing for FRAME-01 to function.

### Pitfall 2: `alpha_frames` table assumed to already exist
**What goes wrong:** Planning tasks that assume the table from the 2026-06-25 schema doc is
already live and only needs a small ALTER (e.g., adding `corpus_run_id`/`weight_epoch`), when in
fact the whole table must be created from scratch.
**Why it happens:** The schema doc reads as "approved" and is dated over two weeks before this
research; several other Phase 142A tables it describes (`alpha_ensemble_ic`) ARE live.
**How to avoid:** Verified via `\dt alpha_frames` → "Did not find any tables named alpha_frames."
This phase's Wave 1 migration must include the full `CREATE TABLE alpha_frames` DDL (with D-04's
corrected CHECK constraint), not an ALTER.
**Warning signs:** Any plan step phrased as "add columns to alpha_frames" rather than "create
alpha_frames" is working from a wrong premise.

### Pitfall 3: `alpha.frame.target_r_fallback` vs. `alpha.frame.target_r_multiple` naming conflict
**What goes wrong:** The 2026-06-25 schema doc's APR key table names this
`alpha.frame.target_r_fallback` (rationale: "R-multiple target when sr_resist_dist is NULL").
ROADMAP.md's FRAME-01 text (written 2026-07-03, later) names the same concept
`alpha.frame.target_r_multiple` with no "fallback" framing. Since Pitfall 1 confirms the fallback
path is the *only* path (100% NULL, always), ROADMAP's non-conditional name is actually the more
accurate one — but neither key currently exists in `config_schema` (verified: zero rows for
either name). If the migration seeds one name and the code reads the other, `ConfigService.get()`
silently returns the hardcoded Python default every time (no error, just a silent wrong-input
config gap) — the "migrate-as-you-go" APR discipline in `CLAUDE.md` requires no hardcoded
fallback constants surviving in the code, but a name mismatch between migration and call site
produces exactly that failure mode invisibly.
**Why it happens:** Two authoritative-looking docs, written 8 days apart, used different names
for a concept whose framing (conditional fallback vs. always-used multiple) changed between them
because of a fact (the NULL columns) that was true both times but only got explicitly re-verified
now.
**How to avoid:** Pick `alpha.frame.target_r_multiple` (matches ROADMAP's authoritative,
later-written, less-conditional framing and matches CONTEXT.md's own additional-context text)
and use it consistently in both the migration and `AlphaFrameWriter`'s code. Do not seed both
names "just in case."
**Warning signs:** grep for both strings before considering the migration complete;
`config_schema` should contain exactly one of them.

### Pitfall 4: `alpha.scoring.min_strategy_n` treated as "Phase 144's key, not ours"
**What goes wrong:** The 2026-06-25 schema doc files `alpha.scoring.*` keys under a
"Phase 144 scoring gates" heading, which invites deferring their migration to Phase 144. But
FRAME-04 (this phase, ROADMAP.md line 1012) directly reads `alpha.scoring.min_strategy_n` as its
own N-sufficiency gate. Verified: zero `alpha.scoring.*` rows exist in `config_schema` today.
**Why it happens:** The schema doc's own organizational heading is doc-authoring convenience, not
a phase-ownership statement — `alpha_strategy_scores` (the table) is Phase 144's, but this
particular APR key is consumed one phase earlier.
**How to avoid:** This phase's migration must seed `alpha.scoring.min_strategy_n` (default 30,
`[conventional]` per the schema doc) regardless of which phase "owns" the `alpha.scoring`
namespace conceptually. Do not gate this on Phase 144 planning.
**Warning signs:** If FRAME-04's implementation crashes or silently defaults because
`ConfigService.get()` finds no row for this key, that's this pitfall manifesting.

### Pitfall 5: Treating `topic_alpha_frames` as a required deliverable
**What goes wrong:** The 2026-06-25 schema doc's migration checklist item "Add
`topic_alpha_frames` to `stream_keys.py`" gets implemented literally, adding a Kafka topic and
publish call that nothing consumes.
**Why it happens:** The schema doc predates the actual precedent Phase 142A set:
`EnsembleICEngine` (the most similar sibling service — also a measurement-only `BaseBatch`
oneshot with no live consumer) has **no** Kafka topic at all (`grep` of `stream_keys.py` and
`ensemble_ic_engine.py` confirms zero topic-publish code) and is registered in
`_DAG_ORDER`/`_ONESHOT_UNITS` only, not `_AGENT_ID_TO_UNIT` (which is for `BaseDaemon` lag-metric
services, not oneshots).
**How to avoid:** Follow `EnsembleICEngine`'s actual precedent, not the older schema doc's
checklist: register both new services in `_DAG_ORDER` (priority 8, alongside
`indicagent-ensemble-ic-engine`) and `_ONESHOT_UNITS`, and skip `topic_alpha_frames` unless a
concrete downstream Kafka consumer is identified during planning (none is named in ROADMAP.md's
FRAME-01..04 text). This is a genuine simplification opportunity, not a corner cut — "delete"
step of the 5-step mandate applies directly: don't build a publish path with zero consumers.
**Warning signs:** If a plan task adds `topic_alpha_frames()` to `stream_keys.py` without a named
consumer for it, flag it during plan review.

### Pitfall 6: `corpus_run_id`/`weight_epoch` provenance columns treated as pre-existing concepts
**What goes wrong:** Assuming `corpus_run_id` and `weight_epoch` map onto some existing field
(e.g., `CorpusManifest`'s internal state) that just needs threading through, rather than being
introduced fresh.
**Why it happens:** `platform-canonical-simulator.md`'s Open Question 3 talks about these columns
as if the underlying concepts are established elsewhere in the system.
**How to avoid:** Verified via `grep -n "weight_epoch\|corpus_run_id"` across `services/*.py` and
`corpus_manifest.py` — **zero hits**. Neither concept exists in code today. Recommended mapping
(planner's call, not yet a locked decision): `weight_epoch` = the existing `weight_version`
string already carried on the source `alpha_events` row (copy-through, no new concept needed —
`alpha_events.weight_version` already IS the epoch identifier used everywhere else in this
codebase, e.g. `ensemble_alpha.weight_version`). `corpus_run_id` = a fresh UUID or ISO-timestamp
string generated once per `AlphaFrameWriter` invocation (mirrors `ensemble_ic_engine.py`'s
`run_ts` pinning pattern, D-142A-R2) and stamped onto every frame written in that run.
**Warning signs:** A plan task that says "read `corpus_run_id` from X" without X being a place
this research found the value already exists is working from an unverified assumption.

## Code Examples

### `alpha_frames` corrected lifecycle CHECK constraint (D-04)

```sql
-- Source: CONTEXT.md D-04, correcting docs/plans/2026-06-25-v30-alpha-lifecycle-schema.md's
-- literal DDL. The schema doc's status column has 'closed_reversal' and lacks
-- 'closed_ic_decay' -- this is SUPERSEDED on this one point by ROADMAP.md's FRAME-02/03
-- (written 2026-07-03, later, with an explicit reasoned rationale).
status text NOT NULL DEFAULT 'open'
    CHECK (status IN (
        'open',
        'closed_stop',
        'closed_target',
        'closed_max_hold',
        'closed_ic_decay'
    )),
```
Every other column, index, and the FK to `alpha_events` in the schema doc's `alpha_frames` DDL
(lines 122-193 of `docs/plans/2026-06-25-v30-alpha-lifecycle-schema.md`) still governs unchanged.
Add `corpus_run_id text` and `weight_epoch text` columns per the canonical-simulator provenance
requirement (Pitfall 6 above).

### Exit-trigger priority order (FRAME-02, pure function target)

```python
# Source: ROADMAP.md FRAME-02 text (authoritative), verified against alpha_ensemble_ic's
# actual live schema (event_row_id, symbol, tf, regime, lookahead, ic_ci_lower, scored_at columns
# confirmed via \d alpha_ensemble_ic, 2026-07-09).
# Recommend implementing this as a standalone pure function (no DB) for unit-testability,
# mirroring _select_hold_bars_from_decay's style in ensemble_ic_engine.py.
def determine_exit(
    bars_since_entry: list[Bar],   # ordered, entry-exclusive
    stop_price: float,
    target_price: float,
    hold_max_bars: int,
    ic_ci_lower: float | None,     # most recent alpha_ensemble_ic row for this (symbol, tf, regime)
) -> ExitResult | None:
    for i, bar in enumerate(bars_since_entry, start=1):
        if bar.low <= stop_price:
            return ExitResult(status="closed_stop", bars=i, exit_price=stop_price)
        if bar.high >= target_price:
            return ExitResult(status="closed_target", bars=i, exit_price=target_price)
        if i >= hold_max_bars:
            return ExitResult(status="closed_max_hold", bars=i, exit_price=bar.close)
    # IC-decay trigger (4): checked once per scan pass, not per-bar -- weekly IC engine
    # cadence, not bar-level. D-08: read regardless of ic_ci_lower's age; D-10: log the age.
    if ic_ci_lower is not None and ic_ci_lower < 0:
        return ExitResult(status="closed_ic_decay", bars=len(bars_since_entry), exit_price=bars_since_entry[-1].close if bars_since_entry else None)
    return None  # still open
```

### FRAME-04 bootstrap gate (recommended shape)

```python
# Source: scipy 1.17.1 confirmed installed via `.venv/bin/python -c "import scipy; ..."` (2026-07-09)
from scipy.stats import bootstrap
import numpy as np

def frame_gate_passes(pnl_r_values: np.ndarray, min_n: int) -> tuple[bool, float, float]:
    """Returns (passes, ci_lower, ci_upper). One-tailed: passes iff ci_lower > 0."""
    if len(pnl_r_values) < min_n:
        return False, float("nan"), float("nan")
    res = bootstrap(
        (pnl_r_values,), np.mean, confidence_level=0.95,
        alternative="greater", method="BCa",
    )
    return bool(res.confidence_interval.low > 0), res.confidence_interval.low, res.confidence_interval.high
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Plain psycopg2 cursor for large per-symbol fetches inside `ProcessPoolExecutor` workers | Named (server-side) cursor + `itersize`, chunked conversion to typed numpy arrays | 2026-07-09 (`ic_engine.py` commit `e9b3bcde`, migration 212); already correct in `ensemble_ic_engine.py`'s pooled fetch since migration 209 | `CounterfactualTracker` must be built with the named-cursor pattern from day one, not "fixed later" |
| `alpha_frames.status` CHECK includes `closed_reversal`, excludes `closed_ic_decay` | CHECK includes `closed_ic_decay`, excludes `closed_reversal` entirely | ROADMAP.md rewrite, 2026-07-03 (D-04, CONTEXT.md) | Migration DDL must be written from ROADMAP's text, not copy-pasted from the 2026-06-25 schema doc |
| `sr_support_dist`/`sr_resist_dist` assumed "will be fixed by Phase 142.5" | Confirmed still 100% NULL after Phase 142.5 shipped (2026-07-07) — Phase 142.5's 89 Renaissance primitives are a disjoint feature set from S/R levels | Verified 2026-07-09 (this research) | ATR fallback is the sole target-price path; no conditional branch is load-bearing |

**Deprecated/outdated:**
- The 2026-06-25 schema doc's 4-variant grid-calibration protocol (`Frame Calibration Protocol
  (in-sample only)` section) — explicitly out of scope for this phase per CONTEXT.md's "Out of
  scope" list. `AlphaFrameWriter` writes `frame_variant='primary'` only; do not implement the
  grid-variant loop.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `weight_epoch` should map to the existing `alpha_events.weight_version` value (copy-through, no new concept) | Pitfall 6 | Low — this is a naming/mapping recommendation, not a verified fact; if planner picks a different mapping, only the migration's column-population logic changes, not the schema shape |
| A2 | `corpus_run_id` should be a fresh identifier generated per `AlphaFrameWriter` invocation, mirroring `ensemble_ic_engine.py`'s `run_ts`-pinning pattern | Pitfall 6 | Low — same as A1; if a different provenance source is preferred (e.g., threading through `CorpusManifest`'s timestamp), the column still needs to exist and be populated, just from a different source expression |
| A3 | `topic_alpha_frames` and Kafka publish are unnecessary for this phase (no named consumer) | Pitfall 5 | Medium — if a downstream consumer is later discovered to need a live Kafka feed of frame outcomes (rather than DB polling), this would need to be added retroactively; low probability given `EnsembleICEngine`'s identical precedent has stood for 5+ days with no such need surfacing |
| A4 | `alpha.frame.target_r_multiple` (not `target_r_fallback`) is the correct key name to seed | Pitfall 3 | Low — purely a naming choice between two docs that describe the identical value; either name works as long as migration and code agree |

## Open Questions (RESOLVED)

1. **Should `AlphaFrameWriter` also be parallelized via `ProcessPoolExecutor`, or is a single
   chunked pass (like `alpha_publisher.py`) sufficient?**
   - What we know: FRAME-01's per-row work (ATR-based stop/target arithmetic, hold-bars APR
     lookup) is much lighter than FRAME-02's price-path scan; `alpha_publisher.py` handles the
     same 12M-row order of magnitude single-process with chunked flushing.
   - What's unclear: whether nightly-incremental volume alone (post-backfill) ever needs
     parallelism, versus only the one-time 12.2M-row backfill pass.
   - RESOLVED (adopted by 142B plans — Plan 01 AlphaFrameWriter is single-process chunked): start single-process (Pattern 2), matching `alpha_publisher.py` exactly;
     only add `ProcessPoolExecutor` if the one-time backfill benchmarks too slow in practice —
     this is a `--backfill`-mode-only optimization question, not a correctness one.

2. **Does `CounterfactualTracker`'s `market_data_ohlcv` range scan need a dedicated index beyond
   the existing `idx_ohlcv_symbol_tf_time (symbol, timeframe, timestamp DESC)`?**
   - What we know: the existing index covers exactly the `(symbol, tf, bar_ts_range)` query shape
     ROADMAP.md's FRAME-02 specifies ("single range query per (symbol, tf, bar_ts_range)").
   - What's unclear: whether TimescaleDB's chunk exclusion on the hypertable's time dimension
     needs any additional tuning at 250-child-table scale (confirmed: `market_data_ohlcv` has 250
     child tables today).
   - RESOLVED (adopted by 142B plans — no new index in migration 214; revisit only on EXPLAIN evidence): no new index needed a priori; if `EXPLAIN ANALYZE` on a representative range
     query during Wave 2 implementation shows a sequential scan across chunks, revisit.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL/TimescaleDB (`indicagent` DB) | Both services, migration | ✓ | live, confirmed via psql queries | — |
| scipy | FRAME-04 bootstrap CI | ✓ | 1.17.1 | — |
| psycopg2 | `CounterfactualTracker` worker connections | ✓ | already used by sibling services | — |
| asyncpg | Both services' pool/write side | ✓ | already used by `BaseBatch` | — |

No missing dependencies. This phase requires no new infrastructure provisioning.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (project-standard, `.venv/bin/pytest tests/unit/ -v`) |
| Config file | none dedicated to this phase — inherits project `pytest.ini`/`pyproject.toml` |
| Quick run command | `.venv/bin/pytest tests/unit/test_alpha_frame_writer.py tests/unit/test_counterfactual_tracker.py -x` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FRAME-01 | Frame geometry math (stop/target/hold from ATR + APR, ATR-only path since S/R is NULL) | unit (pure fn) | `pytest tests/unit/test_alpha_frame_writer_geometry.py -x` | ❌ Wave 0 |
| FRAME-01 | `AlphaFrameWriter` idempotent write via `content_key`-derived `frame_id` | unit | `pytest tests/unit/test_alpha_frame_writer.py -x` | ❌ Wave 0 |
| FRAME-02 | Exit-trigger priority order (stop > target > max_hold > ic_decay) | unit (pure fn) | `pytest tests/unit/test_counterfactual_tracker_exit_priority.py -x` | ❌ Wave 0 |
| FRAME-02 | `CounterfactualTracker` worker returns serializable rows, no DB write inside worker | unit (mirrors `test_ic_engine_compute_split.py::test_compute_symbol_tf_has_no_db_write_code`'s grep-based style) | `pytest tests/unit/test_counterfactual_tracker.py -x` | ❌ Wave 0 |
| FRAME-03 | Migration DDL asserts corrected CHECK constraint values (no `closed_reversal`, includes `closed_ic_decay`) | unit (mirrors `test_ensemble_ic_config.py` style — schema assertion) | `pytest tests/unit/test_alpha_frames_schema.py -x` | ❌ Wave 0 |
| FRAME-04 | Bootstrap gate function: passes iff `ci_lower > 0`, respects `min_strategy_n` floor | unit (pure fn) | `pytest tests/unit/test_frame_gate.py -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** quick run command above
- **Per wave merge:** full suite command
- **Phase gate:** full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/unit/test_alpha_frame_writer_geometry.py` — covers FRAME-01 geometry math
- [ ] `tests/unit/test_alpha_frame_writer.py` — covers FRAME-01 write/idempotency
- [ ] `tests/unit/test_counterfactual_tracker_exit_priority.py` — covers FRAME-02/03 exit logic
- [ ] `tests/unit/test_counterfactual_tracker.py` — covers FRAME-02 worker contract
- [ ] `tests/unit/test_alpha_frames_schema.py` — covers FRAME-03 migration DDL
- [ ] `tests/unit/test_frame_gate.py` — covers FRAME-04 bootstrap gate
- [ ] No new pytest fixtures anticipated beyond what `tests/unit/test_ensemble_ic_*.py` already
      establishes as this codebase's convention (in-memory dataclass configs, no live DB in unit
      tests — DB-touching behavior is exercised at integration-test tier, not unit)

## Security Domain

`security_enforcement` is absent from `.planning/config.json` — treated as enabled per protocol
default. This phase's threat surface is minimal: two internal batch oneshots with no external
network input, no user-facing API, no authentication/session surface, and no new external
package. ASVS categories are assessed for completeness rather than because a large surface is
expected.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No user-facing auth surface; batch oneshots run via systemd/manual invocation only |
| V3 Session Management | No | No session concept in this phase |
| V4 Access Control | No | DB access is via the existing `postgres` role already used by every sibling batch service; no new privilege boundary introduced |
| V5 Input Validation | Yes | All numeric parameters must load via `ConfigService.get_sync()`/`get()` from APR (CLAUDE.md mandate) — never hardcoded; SQL uses parameterized queries (`$1`/`%s` placeholders) throughout, matching every existing `BaseBatch` service — no raw string interpolation into SQL anywhere in this phase's planned code |
| V6 Cryptography | No | No cryptographic operation in this phase; `BaseBatch.content_key()`'s SHA-256 use is for deterministic ID generation (content-addressing), not a security control |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via unparameterized frame-geometry queries | Tampering | Parameterized queries only (`$1`, `%s`) — already the exclusive pattern in every sibling `BaseBatch` service; no plan task should introduce string-formatted SQL |
| Resource exhaustion (OOM) from unbounded fetches | Denial of Service (self-inflicted, not adversarial, but real — has already crashed production twice) | Named server-side cursors with `itersize` (Pattern 3); this is the actual, demonstrated threat in this codebase, more relevant here than classic ASVS categories |

## Sources

### Primary (HIGH confidence — direct code/DB verification, 2026-07-09)
- `src/core/agent/base_batch.py` — read in full; `BaseBatch` lifecycle, `content_key()`, D-06 contract
- `services/alpha_publisher.py` — read in full; chunked accumulate-and-flush write pattern, `content_key()`-derived `event_id`
- `services/ensemble_ic_engine.py` — read in full; `ProcessPoolExecutor` per-symbol dispatch, named-cursor pooled fetch, `_select_hold_bars_from_decay`, `ConfigService.set()` usage
- `git show e9b3bcde` (commit) — `ic_engine.py`'s named-cursor OOM fix, migration 212 DDL, exact before/after diff
- Live DB query: `SELECT count(*), count(sr_support_dist), count(sr_resist_dist) FROM feature_vectors` → 36,719,598 / 0 / 0
- Live DB query: `\dt alpha_frames` → does not exist; `\d alpha_events`, `\d alpha_ensemble_ic`, `\d market_data_ohlcv`, `\d forward_returns` → full schemas confirmed
- Live DB query: `config_schema`/`config_state` for `alpha.frame.*`, `alpha.scoring.*`, `alpha.quant.cost_hurdle.*` — 36 `hold_max_bars` keys exist (partially calibrated), zero `stop_atr_mult`/`target_r_*`/`grid_stop_atr_mults`/`scoring.*` keys exist
- `services/service_auditor.py` — read `_DAG_ORDER`/`_AGENT_ID_TO_UNIT`/`_ONESHOT_UNITS` in full; confirmed `ensemble-ic-engine` registration pattern (priority 8, oneshot set, no `_AGENT_ID_TO_UNIT` entry)
- `src/core/stream_keys.py` — read in full; confirmed zero `alpha_frames`/`counterfactual` references, zero `alpha_ensemble_ic` topic (precedent for "measurement oneshots don't need Kafka topics")
- `docs/plans/2026-06-25-v30-alpha-lifecycle-schema.md` — read in full
- `docs/research/platform-canonical-simulator.md` — read in full
- `.planning/ROADMAP.md` §"Phase 142B" — read in full (`### Phase 142B:` section)
- `.venv/bin/python -c "import scipy; ..."` → scipy 1.17.1, `scipy.stats.bootstrap` confirmed importable
- `grep -rn "weight_epoch\|corpus_run_id"` across `services/` and `corpus_manifest.py` → zero hits (confirms Pitfall 6)
- `grep -rln "bootstrap"` across `src/intelligence/statistics/` and `services/*.py` → no existing bootstrap-mean-CI helper found (only `quality_floor_bootstrap.py`, a differently-scoped service, and unrelated string matches)

### Secondary (MEDIUM confidence)
- `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py` — read the relevant `_run_fetch_stage` section (lines 1015-1194); pattern is directionally applicable but IBKR-network-fetch specific, generalized per Pattern 4 above rather than copied literally

### Tertiary (LOW confidence)
- None — every claim in this document was verified against live code or live DB state during this research session.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new packages, all verified installed and already load-bearing
- Architecture: HIGH — every pattern is a direct read of an existing, working sibling service in this codebase
- Pitfalls: HIGH — all six pitfalls verified via direct DB queries or `grep`, not inferred

**Research date:** 2026-07-09
**Valid until:** 14 days (fast-moving area — this exact codebase had 3 OOM-related migrations and one schema migration land in the 48 hours immediately preceding this research; re-verify `alpha_frames` non-existence and APR key state if planning is delayed past 2026-07-23)
