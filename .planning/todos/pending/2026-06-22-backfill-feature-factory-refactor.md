# TODO: backfill_feature_factory.py — BaseBatch refactor + naming + observability

**Created:** 2026-06-22
**Scope:** Phase 138 follow-on — execute after BaseBatch exists (P1 Task 0 complete)
**Trigger:** BaseBatch built; backfill has run and feature_vectors is populated

## Context

`services/backfill_feature_factory.py` runs correctly and is intentionally not modified
in Phase 138 P1 (plan says "only run it"). When BaseBatch exists, this service is the
first candidate to extend it — and the refactor is the right time to close all naming,
observability, and taxonomy gaps identified by the council review (2026-06-22).

---

## Issue 1 — CLOSED (P0): Threshold value baked into log event name

**File:** `services/backfill_feature_factory.py` line 842

```python
# Wrong — APR threshold baked into event name; lies when threshold changes
"d06_gate_candidates_below_80pct"

# Right — threshold in payload, name is eternal
"coverage_below_threshold", pairs=[...], threshold=coverage_threshold
```

When `threshold.backfill.min_coverage_fraction` changes in APR, this event name
silently misrepresents what "below threshold" means. Log names are a permanent
taxonomy; values belong in the payload, never the name.

**Fix:** Rename event. Also rename APR key (see Issue 3).

---

## Issue 2 — HIGH: Two names for the same concept in the same file

```python
# Stage 1 has two names used interchangeably:
"fetch_stage_start"   # line 452 — used in run_fetch_stage()
"stage1_start"        # line 914 — used in main()

"fetch_stage_complete"  # line 584
"stage1_complete"       # line 923
```

A monitoring query for `stage1_start` misses `fetch_stage_start`. The log taxonomy
is forked. Canonical event names for the two stages:

```
ohlcv_ingest.started / ohlcv_ingest.completed     (Stage 1)
feature_compute.started / feature_compute.completed (Stage 2)
```

---

## Issue 3 — CLOSED (P0): `coverage_gate` is the wrong concept

A gate is binary (abort if failed). A threshold is a continuous minimum (warn and
continue). The code behavior is warn-and-continue — that is a threshold, not a gate.

**All occurrences to rename:**
- Variable `coverage_gate` → `coverage_threshold` (lines 608, 692, 719, 824, 831)
- APR key `threshold.backfill.coverage_gate` → `threshold.backfill.min_coverage_fraction`
  (config_state row + config_schema row + migration + all reads in the service)
- Log field `coverage_gate=` wherever emitted

---

## Issue 4 — HIGH: Two concerns coupled into one file

Stage 1 (IBKR → `market_data_ohlcv`) and Stage 2 (compute → `feature_vectors`) have
different failure modes, different retry strategies, and different monitoring concerns.
Coupling them in one file obscures OHLCV data provenance and makes the service registry
misleading — the name implies only feature compute, not OHLCV ownership.

**Fix:** Split into two services at refactor time:
- `services/ohlcv_backfill.py` — IBKR fetch → `market_data_ohlcv`, extends BaseBatch
- `services/feature_vector_backfill.py` — compute → `feature_vectors`, extends BaseBatch,
  depends on ohlcv_backfill completing (gate: `backfill_status.fetch_complete = true`)

Each gets its own `_JOB` name, its own D-06 emission, its own systemd unit registration
in `_DAG_ORDER` and `_ONESHOT_UNITS`.

---

## Issue 5 — PARTIALLY CLOSED (P0: _TARGET_TIMEFRAMES + coverage_threshold done; _STORE_OHLCV_SQL, _vector_to_params, run_fetch_stage, run_compute_stage still open): Naming standard violations

| Location | Current | Fix |
|---|---|---|
| line 68 | `_TARGET_TFS` | `_TARGET_TIMEFRAMES` — no abbreviations in Python identifiers |
| line 108 | `_STORE_OHLCV_SQL` | `_INSERT_OHLCV_SQL` — all SQL constants use operation prefix |
| line 320 | `_vector_to_params` | `_serialize_feature_vector` — "params" leaks psycopg2 impl |
| line 437 | `run_fetch_stage` | `_ingest_ohlcv_history` — `run_` implies top-level entry point |
| line 592 | `run_compute_stage` | `_compute_feature_vectors` — same |

---

## Issue 6 — CLOSED (P0): Phase reference in source code

```python
# line 790 — wrong: references a plan artifact
regime=None,  # Regime label assigned by HMM downstream (Phase 138)

# right: describes the invariant
regime=None,  # populated by regime_writer after batch compute completes
```

---

## Issue 7 — CLOSED (P0): No content_key on feature_vectors insert

`feature_vector_id = SHA256(symbol | tf | bar_ts_ns | pipeline_version)` is not
populated on insert. Without it:
- Rows from old algorithm versions are indistinguishable from current ones at the row level
- The IC engine cannot join feature_vectors to IC scores by a stable identifier
- Replay idempotency relies solely on the natural PK (symbol, tf, bar_ts) — which does
  not encode algorithm version

**Fix:** Add `content_key(symbol, tf, str(bar_ts_ns), pipeline_version)` call in
`_serialize_feature_vector()`, populate `feature_vector_id` column in the INSERT.
Verify the column exists in the `feature_vectors` DDL (migration 156); add it if absent.

---

## Issue 8 — MEDIUM: OTel metrics too thin for a multi-hour batch job

D-06 fires once at job exit. No Grafana visibility during a 6-hour run.

**Add to the refactored service(s):**
```
rows_written_total{symbol, tf}          counter
rows_skipped_total{symbol, tf}          counter — idempotent ON CONFLICT skips
symbols_failed_total                    counter
compute_latency_seconds{tf}             histogram — per-TF wall time
coverage_gauge{symbol, tf}             gauge — pct of theoretical_max achieved
```

**Add OTel spans:**
```python
observed_span("feature_vector_backfill.compute_symbol_tf", {"symbol": symbol, "tf": tf})
```
Wrap `_compute_feature_vectors()` per (symbol, tf). Makes per-pair latency distribution
visible in Jaeger and surfaces which (symbol, tf) pairs are slow or erroring.

---

## Issue 9 — LOW: Magic constants not in APR

```python
_INSERT_BATCH_SIZE: int = 500    # → APR threshold.backfill.insert_batch_size
_READ_CHUNK_BARS: int = 2000     # → APR threshold.backfill.read_chunk_bars
```

`_TRADING_DAYS_PER_YEAR = 252` is a statistical constant, not a tunable — acceptable
as a module-level constant.

---

## Issue 10 — LOW: No SIGTERM handler

Mid-run kill drops the in-flight INSERT batch. The checkpoint recovers on restart but
the partial work is untracked. BaseBatch inheritance resolves this if BaseBatch
registers a SIGTERM handler that flushes the current batch before teardown.

---

## Execution order

1. Build `BaseBatch` (Phase 138 P1 Task 0) — prerequisite
2. Run backfill as-is (Phase 138 P1 Task 1) — feature_vectors populated
3. Post-Phase-138: open a plan for this refactor
   - Fix Issues 1-3 first (data integrity + log taxonomy)
   - Then split into ohlcv_backfill + feature_vector_backfill (Issue 4)
   - Then wire both to BaseBatch (closes Issues 5-10 in one pass)
   - APR key rename (Issue 3) requires a migration — run alongside the refactor migration

## Done gate

- `grep -r "d06_gate_candidates\|coverage_gate\|_TARGET_TFS\|_STORE_OHLCV\|_vector_to_params\|run_fetch_stage\|run_compute_stage\|Phase 138" services/ohlcv_backfill.py services/feature_vector_backfill.py` returns empty
- `feature_vector_id` populated on every insert; verified by spot-check query
- `pytest tests/unit/ -q` green
- Coverage gauge visible in Grafana during a test run
