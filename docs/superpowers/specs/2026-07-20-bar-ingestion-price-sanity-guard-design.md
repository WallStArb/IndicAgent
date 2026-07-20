# Bar-Ingestion Price-Sanity Guard — Design (todo 149)

**Informed by:** a Fable 5 architectural review (2026-07-20) of this design's second draft, which
found two correctness/consistency gaps addressed in sections 2 and 4 below — the boolean
tri-state's inability to represent an inconclusive verdict, and a mechanism collision with
todo 151's already-shipped correction tool. Full review preserved in this session's transcript;
not re-derived here.

## Problem

Corrupt IBKR prints (e.g. `open=1000` on a ~$25 ETF, or `high=99999.99`) flow completely
unguarded through the sole raw-OHLCV table, `market_data_ohlcv`, into every downstream consumer.
Todo 148 (shipped) added a magnitude-ceiling suspect flag, but only on `forward_returns` — a
derived table computed from `open` alone. That protects `forward_returns`' own mean-based
consumers but does nothing for the 5+ services that read raw OHLCV directly for high/low/close-
based features (momentum, volatility, regime models): a corrupted `high` that doesn't happen to
distort the `open`-based return sails through completely unguarded.

The fix needs to live at the bar level, upstream of every consumer, so protection is inherited
for free rather than reinvented per-consumer (as `forward_returns` already had to do for its own
narrow slice).

## Goals

- Every consumer of `market_data_ohlcv`/`market_data_ohlcv_tradeable` inherits protection from
  bar-level price corruption without code changes, the same way `market_data_ohlcv_tradeable`'s
  existing `volume > 0` filter already protects against synthetic calendar-fill bars.
- Reuse, not reinvent: the detection logic, the cross-symbol corroboration signal, and the
  periodic-audit DAG-node pattern all already exist in this codebase (todo 151's
  `classify_candidate_bar()`, todo 152's corroboration fix, `BarAuditor`). This design's job is
  to wire them together correctly, not build parallel infrastructure.
- Survive both live operation and replay/backfill identically, with no special-casing — the
  actual bug this design exists to avoid repeating (`forward_return_writer.py`'s `MAX(bar_ts)`
  watermark silently failed to backfill a gap earlier today, costing a 17-minute unplanned full
  recompute to fix).
- Never drop data. Flag, don't delete or silently zero a field. Pass-through-by-default on an
  unaudited or inconclusive bar, not block-by-default.

## Non-Goals

- Not a new daemon. The true defect rate across the full 80-symbol universe is currently
  unknown (only ~18 bar-level corrupt prints have ever been found, across 4 heavily-scrutinized
  symbols, and only via the *different*, return-level guard — this bar-level check has never run
  once against the full corpus). Standing up dedicated deployment/monitoring infrastructure for
  an unproven-frequency defect class is accelerating ahead of evidence, in violation of this
  project's question/delete/simplify-before-accelerate mandate. Revisit as a standalone daemon
  only if the first full-corpus pass demonstrates a resourcing or cadence need `BarAuditor`
  genuinely can't absorb.
- Not real-time/synchronous. The strongest detection signal (spike-and-revert) is causally
  impossible to compute before the *next* bar exists. This is an audit, not a gate.
- Not touching `ProviderMerger` (explicitly DB-ignorant transport, no next-bar context available
  even if it had DB access) or `BarWriter` (hot batch-write path with a no-per-row-DB-lookback
  performance contract; also has no next-bar context at write time).

## Architecture

### 1. Schema: `price_sanity_status`, not a boolean

```sql
ALTER TABLE market_data_ohlcv
    ADD COLUMN price_sanity_status text;
    -- NULL = not yet audited (the watermark)
    -- 'plausible' | 'confirmed_corrupt' | 'market_event' | 'ambiguous'
```

A boolean tri-state (`NULL`/`TRUE`/`FALSE`) was the first draft of this design and is wrong:
`classify_candidate_bar()` (already shipped, todo 151) returns four states, not two, and
`AMBIGUOUS` is explicitly a "cannot conclude" state — todo 151's own script never auto-corrects
it, by design ("requires human judgment," per its module docstring). Collapsing `AMBIGUOUS` into
`FALSE` would silently auto-resolve an inconclusive verdict as "fine" — a silent wrong answer.
Leaving it `NULL` would mean it gets re-classified as `AMBIGUOUS` every audit cycle forever,
quietly inflating the "backlog" the batch-size pacing key is supposed to bound. A real status
column gives `AMBIGUOUS` its own terminal state: written once, visible for human review (a
dashboard/query surface, not built in v1), never re-scanned.

### 2. View predicate: exclude only `confirmed_corrupt`

```sql
CREATE OR REPLACE VIEW market_data_ohlcv_tradeable AS
SELECT * FROM market_data_ohlcv
WHERE volume > 0
  AND price_sanity_status IS DISTINCT FROM 'confirmed_corrupt';
```

`IS DISTINCT FROM` (not `!=` or `<> 'confirmed_corrupt'`) is required for NULL-safety — a plain
inequality against a NULL column evaluates to NULL (falsy in a `WHERE` clause), which would make
every newly-inserted live bar invisible to every downstream consumer until the audit gets to it,
injecting unintended read-latency into the real-time pipeline. `NULL`, `plausible`, `market_event`,
and `ambiguous` all pass through unchanged — only a confirmed verdict excludes. This is the
"innocent until proven guilty" posture: never drop data on an unaudited or inconclusive signal.

### 3. Watermark: `price_sanity_status IS NULL`, no separate table

The audit query is: find rows where `price_sanity_status IS NULL` and a next bar now exists to
compare against. This is agnostic to whether the NULL row arrived via live trickle or a bulk
historical backfill landing anywhere in history — same query, same logic, no special-casing for
replay. This is the direct fix for today's `MAX(bar_ts)`-tail-only watermark bug: a NULL doesn't
care where in history it lands.

**Candidate scan and neighbor references must read `market_data_ohlcv_tradeable`, not the raw
table**, and must be scoped to rows the view already includes (`volume > 0`). Two reasons:
- ~82% of intraday rows in the raw table are synthetic calendar-fill / flat-carry-forward
  placeholders. Computing `LAG(close)`/`LEAD(open)` against the raw table would corrupt the
  reference price at every gap boundary — exactly where a genuine move is most likely to occur.
  Todo 151's script already gets this right (`_NEIGHBOR_SCAN_SQL` reads the tradeable view); this
  design must state it explicitly rather than leave it implicit.
- An unscoped `price_sanity_status IS NULL` scan (no `volume > 0` filter) would inflate the
  candidate set roughly 5x with synthetic rows that can never be meaningfully classified and
  would sit `NULL` forever.

### 4. Unify with todo 151's correction mechanism — do not ship two competing signals

Todo 151's already-shipped `--apply` step corrects confirmed-corrupt bars by setting
`volume = 0`, deliberately reusing the *existing* `volume > 0` filter (a pragmatic, "no new
schema" choice at the time it was built, hours before this design existed). Shipping
`price_sanity_status` as a second, independent mechanism for the same job breaks two things:

- **Concept collision**: `volume = 0` would mean two different things — "no trade occurred" (the
  view's original, documented purpose) and "this print is corrupt" (unrelated) — exactly the
  kind of collision this project's glossary discipline exists to prevent.
- **Permanent blind spot**: the new auditor's candidate scan reads the tradeable view
  (`volume > 0`). Any bar 151 already corrected is now *excluded* from that view and therefore
  invisible to the candidate scan forever — its `price_sanity_status` would stay `NULL`
  indefinitely. The "everything eventually gets audited" invariant this whole design depends on
  would be false from day one, for exactly the 18 bars already known to be corrupt.

**Resolution — collapse to one mechanism:**
- Going forward, `ops_known_corrupt_print_cleanup.py --apply` is updated to stamp
  `price_sanity_status = 'confirmed_corrupt'` instead of zeroing `volume`. This is also the more
  conservative choice: it preserves the original (if corrupt) print for forensic/audit record
  rather than destroying the volume value, consistent with this project's flag-don't-drop
  principle.
- One-time reconciliation: backfill `price_sanity_status = 'confirmed_corrupt'` onto the 18 rows
  already corrected today via `volume = 0` (leave their `volume = 0` as-is — harmless
  redundancy, not worth reverting already-shipped, already-audited work). After this, exactly one
  query surface (`price_sanity_status`) answers "which bars are known bad."

### 5. Deployment: inside `BarAuditor`, with its own bounded resources — not a new daemon

`BarAuditor` already has the right DAG-node shape (periodic, DB-aware, self-healing, publishes
findings) — no need to re-derive it. But its existing resource sizing (`min_size=1, max_size=3`
connection pool, 300-second cycle, 3-day lookback window) was built for a cheap O(days) gap-count
query, not a classification-plus-write pass that will eventually touch up to 215.6M rows across a
mostly-compressed TimescaleDB hypertable (248/250 chunks compressed as of this design; DML
against compressed chunks is a correction-scale operation in TimescaleDB, not a bulk-backfill-
scale one, and this exact cost is unproven in this codebase at this row count).

- The price-sanity pass runs as its own bounded async task inside `BarAuditor`, with its own
  small connection pool — not competing with gap-detection's existing 3 connections.
- Batch size per audit tick is APR-governed (`infra.price_sanity_audit.batch_size`), per this
  project's infra-performance-constants mandate — never a hardcoded constant.
- **The first full-corpus pass is piloted, not run unattended.** Time a single-symbol,
  single-chunk trial first and measure actual cost before ever running this against all 80
  symbols — the same empirical-first discipline already used today for the todo-151 recompute
  (measured ~17 minutes for 4 symbols' full history before trusting the shape of the operation).
  This is a corpus-scale operation in the same sense the project's other corpus-scale operations
  (`ic_engine`, full backfills) are already treated as things to pilot and time, not launch cold.

### 6. Detection logic — reuse, with one required extension

- `classify_candidate_bar()` (todo 151, already unit-tested against real corrupt prints and the
  Flash Crash cluster) is promoted to a shared module (`src/intelligence/statistics/` or
  `src/core/`) and reused as-is for single-bar classification.
- Cross-symbol corroboration is extracted into one shared, batched primitive, used by both this
  new check and `forward_return_writer.py`'s existing corroboration pass — today's session
  already demonstrated the cost of two independent naive implementations of "is this corrupt or
  a real event" (152's two empirically-discovered bugs). **Match-mode (exact-timestamp vs.
  time-window) must be an explicit required parameter of the shared primitive, never a default**
  — the two existing implementations deliberately diverge on this for good, documented reasons
  (raw bars vs. derived, per-scale-staggered returns), and a shared abstraction that silently
  defaults one way would reintroduce the exact naive-corroboration bug both existing fixes exist
  to prevent.
- This is genuinely new engineering, not a pure refactor — todo 151's corroboration query is a
  per-candidate Python loop (cheap only because N~27), while `forward_return_writer.py`'s is
  already batched (one temp table, one `UPDATE` per scale). The shared primitive needs its own
  validation against the Flash Crash cluster before either caller trusts it, the same way both
  current implementations individually received that validation.

### 7. Future-correction invalidation rule (stated, not built in v1)

No code path today mutates a bar's OHLC values on an already-audited row (`BarWriter` is
`ON CONFLICT DO NOTHING`; todo 151's correction only ever touches `volume`/`price_sanity_status`,
never OHLC). This isn't an active bug, but the rule is stated here so a future correction tool
doesn't silently violate it: **any process that mutates OHLC on a row whose
`price_sanity_status IS NOT NULL` must reset that status to `NULL` in the same transaction**, so
the row re-enters the audit queue rather than carrying a stale verdict.

## Data Flow

```
IBKR (live or backfill) → ProviderMerger (Kafka route, no DB) → BarWriter (batch insert,
  ON CONFLICT DO NOTHING, price_sanity_status defaults NULL)
                                                                       ↓
                                          BarAuditor's existing 5-min cycle, price-sanity task:
                                          SELECT ... FROM market_data_ohlcv_tradeable
                                          WHERE price_sanity_status IS NULL
                                            AND next-bar-exists
                                          LIMIT <APR batch size>
                                                                       ↓
                                          classify_candidate_bar() + shared corroboration primitive
                                                                       ↓
                                          UPDATE market_data_ohlcv SET price_sanity_status = ...
                                                                       ↓
market_data_ohlcv_tradeable (WHERE volume > 0 AND price_sanity_status IS DISTINCT FROM 'confirmed_corrupt')
                                                                       ↓
                              every existing consumer, unchanged (feature computation, regime
                              models, forward_return_writer, counterfactual_tracker, ...)
```

## Error Handling

- `BarAuditor`'s existing OTel health contract (D-26: crash counter, DLQ counter, last-message
  gauge, watchdog notify/suppressed) is inherited for free via `BaseDaemon` — no new
  instrumentation needed since this is not a new daemon.
- A failed classification for one candidate bar (e.g. a transient DB error mid-batch) must not
  poison the rest of the batch — log and leave that row's `price_sanity_status` as `NULL` (it
  re-enters the queue next cycle), never crash the whole audit tick over one row. Mirrors the
  existing `forward_return_writer.py` per-cell failure-isolation pattern.
- No per-row logging inside the batch loop (CLAUDE.md rule) — accumulate counts per status per
  tick, log once.

## Testing

- `classify_candidate_bar()` — already tested (todo 151), no new test surface for the pure
  classification logic itself.
- New: the shared corroboration primitive, parameterized by match-mode, tested against the same
  Flash Crash cluster fixture both existing implementations were validated against, for both
  match-modes.
- New: the `price_sanity_status IS DISTINCT FROM 'confirmed_corrupt'` view predicate — a
  regression test asserting `NULL`, `'plausible'`, `'market_event'`, and `'ambiguous'` all pass
  the filter and only `'confirmed_corrupt'` excludes.
- New: watermark correctness — a synthetic test inserting a "backfilled" NULL row behind an
  already-audited high-water region, asserting it gets picked up by the candidate query (the
  exact bug class this design exists to avoid).
- Pilot run (single symbol, single chunk) is itself a form of test — its timing and correctness
  against known-good rows gates the full-corpus rollout.

## Open Questions (deferred, not blocking)

- Corroboration `min_symbols` threshold at low-liquidity/overnight audit windows (fewer active
  symbols in a given window makes a fixed floor a relatively higher bar) — reuses the existing
  empirically-tunable APR key (`alpha.quant.cross_symbol_corroboration.min_symbols`); no dynamic
  adjustment in v1, flagged for future calibration if evidence warrants it.
- Whether `AMBIGUOUS` rows eventually get a dashboard/review surface — out of scope for this
  design; today they're simply queryable, matching todo 151's existing "human judgment required"
  posture.
