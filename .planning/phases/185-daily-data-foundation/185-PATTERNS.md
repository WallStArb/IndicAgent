# Phase 185: Daily data foundation - Pattern map

**Mapped:** 2026-09-27
**Files analyzed:** 41 (29 new, 12 modified)
**Analogs found:** 38 / 41

Scope comes from 185-CONTEXT.md (D-01..D-28) and 185-RESEARCH.md ("Recommended project structure (new files only)", "Recommended plan decomposition" 185-01..185-13, "Validation architecture"). Migration numbers below are placeholders from 380 onward; the latest on disk is `379_dividend_view_ibkr_prev_close.sql`, and `tests/unit/test_migration_number_uniqueness.py` enforces uniqueness.

## File classification

| New/modified file | Role | Data flow | Closest analog | Match quality |
|---|---|---|---|---|
| `production/migrations/380_ohlcv_observation_store.sql` (D1: `ohlcv_request`, `ohlcv_observation`, append-only triggers, NOLOGIN roles + grants) | migration | append-only store | `367_classification_integrity_guards.sql` + `366_research_run_ledger.sql` (triggers), `376_dividend_events.sql` (table/CHECK/COMMENT shape) | exact for triggers; no analog for roles |
| `production/migrations/381_bar_quality_flag.sql` (flag table, tradeable view anti-join, migrate 67 status rows, drop todo 347 index, `threshold.bar_scrub.*` APR) | migration | view + APR seed | `374_former_venue_history_recovery.sql` (view rewrite + APR seed) | exact |
| `production/migrations/383_derived_grid.sql` (plan 11; 15m/1h raw archive, `bar_derivation`, `bar_content_digest`) | migration | side tables | `376_dividend_events.sql` | role-match |
| `production/migrations/400_corporate_action.sql` (plan 15; `corporate_action` append-only with supersedes; `listing_venue` ships separately as plan 24's `408_listing_venue.sql`) | migration | point-in-time append-only | `367_classification_integrity_guards.sql` (EXCLUDE gist, close-then-insert, same-UTC-day) | exact |
| APR seed migrations (survivorship `alpha.survivorship.*`, D7 thresholds, `infra.bar_derivation.overlap_sessions`) | migration | config seed | `376_dividend_events.sql` lines 89-143 | exact |
| `src/intelligence/bars/__init__.py` | package | - | `src/intelligence/research/__init__.py` | exact |
| `src/intelligence/bars/scrub_rules.py` | pure rule module | transform | `src/intelligence/statistics/price_sanity.py` + pure half of `services/dividend_event_writer.py` | exact |
| `src/intelligence/bars/seams.py` | pure rule module | transform | `derive_ibkr_events` / `join_adjustment_pairs` in `services/dividend_event_writer.py` | exact |
| `src/intelligence/bars/session_grid.py` | pure utility | transform (aggregation) | `aggregate_bars_from_1m` in `infrastructure_run_historical_pipeline.py` + `_build_daily_sessions` in `src/core/market_calendar.py` | role-match |
| `src/intelligence/bars/derivation.py` (rule vN, `RULE_VERSION`) | pure rule module | transform | `derive_ibkr_events` (dividend writer), `compute_version` convention in `BaseBatch` | role-match |
| `src/intelligence/bars/digest.py` | pure utility | transform (hash) | `BaseBatch.content_key` (`src/core/agent/base_batch.py`) | role-match |
| `src/intelligence/bars/venue_study.py` | pure statistics | transform | `reconcile` / `Reconciliation` in dividend writer | role-match |
| `src/intelligence/bars/labels.py` (D0) | pure rule module | transform | `DisputeRule` / `resolve_event` in `src/intelligence/research/dividends.py` | role-match |
| `src/intelligence/bars/corporate_actions.py` (split inference, disputed-date rule D-23) | pure rule module | transform | `reconcile` near-miss logic in dividend writer (lines 244-273) | exact |
| `services/ohlcv_observation_writer.py` (D1 COPY writer, SET ROLE) | writer | batch append (COPY) | `bulk_update_by_key` COPY block in `services/_batch_utils.py` lines 144-166; `store_bars` in historical pipeline | partial (no asyncpg COPY writer exists) |
| `services/bar_derivation.py` (D2/D2a/D2b batch job) | batch oneshot | batch transform + write | `services/dividend_event_writer.py` (`BaseBatch`, per-symbol transaction) | exact |
| `services/bar_reconciliation_audit.py` (D7) | batch oneshot (audit) | read + integrity facts | `src/config/classification_coverage.py` | exact |
| `scripts/ops/bars/ops_venue_study.py`, `ops_seam_audit.py`, `ops_d1_bootstrap.py`, `ops_head_rerun.py` | one-off script (IBKR) | fetch + report | `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py` (dry-run/apply) + `infrastructure_ibkr_chunk_and_rate_limit_probe.py` (provider setup) | role-match |
| `scripts/ops/bars/ops_data_bar_check.py` (D-28 pass/fail) | one-off script | read-only report | `ops_known_corrupt_print_cleanup.py` `render_dry_run_report` | role-match |
| `production/systemd/indicagent-bar-derivation.service`, `indicagent-bar-reconciliation-audit.service` | config | oneshot unit | `production/systemd/indicagent-dividend-event-writer@.service` | exact |
| `tests/unit/bars/test_scrub_rules.py`, `test_scrub_known_answers.py`, `test_corroboration_ceiling.py`, `test_flag_parity.py`, `test_seams.py`, `test_session_grid.py`, `test_digest.py`, `test_labels.py`, `test_venue_study.py`, `test_corporate_actions.py` | test | pure unit | `tests/unit/services/test_dividend_event_writer.py` | exact |
| `tests/unit/test_ohlcv_observation_migration_contract.py` | test | source grep of SQL | `tests/unit/test_earnings_season_migration_contract.py` | exact |
| `tests/unit/test_market_data_ohlcv_writer_boundary.py` (single writer 1d/15m/1h) | test | CI grep | `tests/unit/test_market_data_ohlcv_boundary.py` | exact |
| `tests/unit/services/test_bar_reconciliation_audit.py` | test | pure unit | `tests/unit/services/test_dividend_event_writer.py` | role-match |
| `tests/integration/test_derived_grid_live.py` | test | read-only DB | none read; use the D-15 query from RESEARCH | no analog read |
| `tests/fixtures/bars/*.csv`, `corrupt_1d.txt` | fixture | file | `tests/fixtures/golden/` (directory convention only) | partial |
| MOD `src/providers/ibkr.py` (`on_request`, `on_observation`, `fetch_run_id`, structlog venue event) | provider | request-response | its own `on_chunk` / `on_empty_history` callbacks (lines 722-876, 1073-1153) | exact (self) |
| MOD `tests/unit/providers/test_ibkr_provider.py` (`-k request_record`) | test | fake IB | `TestPreMoveHistory` (lines 517-644) | exact (self) |
| MOD `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py` | batch script | fetch + persist | its own `_persist_chunk` wiring (lines 1530-1640) | exact (self) |
| MOD `scripts/infrastructure/backfill/infrastructure_nightly_backfill.py` (chain D7, nightly-skipped fact, default tfs) | batch script | orchestration | its own `_finish` / `_run_delegate` (lines 156-231) | exact (self) |
| MOD `scripts/infrastructure/backfill/_empty_history.py` (D4 from `ohlcv_request`) | I/O helper | CRUD | its own `record` (lines 98-153) | exact (self) |
| MOD `services/dividend_event_writer.py` (`_derive` reads D1) | batch oneshot | fetch -> read D1 | its own `_derive` (lines 416-452) | exact (self) |
| MOD `tests/unit/services/test_dividend_event_writer.py` | test | pure unit | self | exact |
| MOD `tests/unit/test_market_data_ohlcv_boundary.py` (allow-list for derivation, D7) | test | CI grep | self `_ALLOW_LIST` | exact |
| MOD `tests/unit/test_compressed_hypertable_write_boundary.py` (extend to `UPDATE market_data_ohlcv`) | test | CI grep | self | exact |
| MOD `services/service_auditor.py` (`_DAG_ORDER`, `_ONESHOT_UNITS`) | config registry | - | self lines 57-70, 183-215 | exact |
| MOD `docs/foundation/glossary.md`, `docs/foundation/canonical-truth-registry.md`, `docs/foundation/instrument-onboarding-sop.md` | docs | - | - | n/a |

## Pattern assignments

### `production/migrations/380_ohlcv_observation_store.sql` (migration, append-only store)

**Analog A:** `production/migrations/367_classification_integrity_guards.sql`

Header convention (lines 1-15): a numbered title, then a prose paragraph stating what failure class the migration prevents and the live data it arrives on. Whole file inside `BEGIN; ... COMMIT;`.

Append-only trigger function with TG_OP branching (lines 32-60), then two triggers, one row-level and one statement-level for TRUNCATE (lines 62-67):
```sql
CREATE OR REPLACE FUNCTION instrument_classification_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    today date := (now() AT TIME ZONE 'UTC')::date;
BEGIN
    IF TG_OP = 'INSERT' THEN
        ...
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        ...
    ELSE
        RAISE EXCEPTION 'instrument_classification is append-only: % is not allowed', TG_OP;
    END IF;
END $$;

CREATE TRIGGER trg_instrument_classification_append_only
    BEFORE INSERT OR UPDATE OR DELETE ON instrument_classification
    FOR EACH ROW EXECUTE FUNCTION instrument_classification_append_only();
CREATE TRIGGER trg_instrument_classification_no_truncate
    BEFORE TRUNCATE ON instrument_classification
    FOR EACH STATEMENT EXECUTE FUNCTION instrument_classification_append_only();
```
For `ohlcv_request` and `ohlcv_observation` (pure append, no permitted UPDATE) the simpler shape is `fn_research_run_no_delete` in `366_research_run_ledger.sql` lines 166-190: one function that always raises `'<table> is append-only: % is not allowed', TG_OP`, attached `BEFORE UPDATE OR DELETE ... FOR EACH ROW` and `BEFORE TRUNCATE ... FOR EACH STATEMENT`, each preceded by `DROP TRIGGER IF EXISTS`.

**Analog B (table shape):** `production/migrations/376_dividend_events.sql` lines 36-57
```sql
-- LEDGER-EXCEPTION: corporate-action reference data ...
CREATE TABLE IF NOT EXISTS dividend_events (
    symbol TEXT NOT NULL REFERENCES instruments(symbol) ON DELETE RESTRICT,
    ex_date DATE NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('yahoo', 'ibkr_adjusted_last_ratio')),
    amount DOUBLE PRECISION NOT NULL CHECK (amount > 0),
    ...
    PRIMARY KEY (symbol, ex_date, source),
    -- NaN > 0 is true in Postgres, so the positivity checks alone admit it.
    CONSTRAINT dividend_events_finite CHECK (
        amount <> 'NaN' AND amount <> 'Infinity' AND prev_close <> 'NaN' AND prev_close <> 'Infinity'
    )
);
COMMENT ON TABLE dividend_events IS '...';
```
Copy: FK to `instruments(symbol) ON DELETE RESTRICT`, CHECK-enumerated `source`/`route`/`what_to_show`/`outcome` columns, the NaN/Infinity CHECK (OHLC observations are floats), a `COMMENT ON TABLE` telling readers which surface to use, and the `-- LEDGER-EXCEPTION:` comment if a ledger lint expects one. `ohlcv_request` carries `fetch_run_id` (RESEARCH finding 9: ADJUSTED_LAST pairs only within a run).

**Roles (no analog):** no migration creates a role and no Python code runs `SET ROLE` (grep of `production/migrations` and `src services scripts` for `CREATE ROLE|GRANT|SET ROLE|NOLOGIN` finds nothing relevant). Follow RESEARCH Pattern 4: `CREATE ROLE ... NOLOGIN` guarded by a `DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = ...) THEN CREATE ROLE ...; END IF; END $$;` block (migrations must be re-runnable like the `IF NOT EXISTS` tables above), then `GRANT INSERT` / `GRANT SELECT` per table, and `GRANT <role> TO postgres` is implicit for a superuser.

**Contract test:** see `tests/unit/test_ohlcv_observation_migration_contract.py` below.

---

### `production/migrations/381_bar_quality_flag.sql` (migration, view rewrite + APR)

**Analog:** `production/migrations/374_former_venue_history_recovery.sql`

View rewrite must keep the column list and order exactly (lines 82-96), adding only a predicate:
```sql
CREATE OR REPLACE VIEW market_data_ohlcv_tradeable AS
SELECT "timestamp",
       symbol,
       timeframe,
       open,
       high,
       low,
       close,
       CASE WHEN source = 'ibkr_venue' THEN NULL ELSE volume END AS volume,
       source,
       base,
       price_sanity_status
FROM market_data_ohlcv
WHERE volume > 0
  AND price_sanity_status IS DISTINCT FROM 'confirmed_corrupt';
```
Phase 185 appends `AND NOT EXISTS (SELECT 1 FROM bar_quality_flag q WHERE q.quarantine AND q.symbol = market_data_ohlcv.symbol AND q.timeframe = market_data_ohlcv.timeframe AND q.timestamp = market_data_ohlcv."timestamp")` and keeps the `confirmed_corrupt` predicate until the 67 rows are migrated (RESEARCH Pattern 2). Header must record the EXPLAIN ANALYZE before/after numbers (performance SOP).

The index drop for todo 347 is a plain `DROP INDEX IF EXISTS idx_market_data_ohlcv_price_sanity_unaudited;` (no decompression, so no VACUUM step needed; if any step decompresses, `tests/unit/test_compressed_hypertable_migration_vacuum_check.py` requires a bare `VACUUM market_data_ohlcv;`).

APR seed: copy the three-block shape from 376 (below, "APR seed").

---

### `production/migrations/400_corporate_action.sql` (plan 15; migration, point in time; `listing_venue` is plan 24's `408_listing_venue.sql`)

**Analog:** `367_classification_integrity_guards.sql` lines 21-30 (no-overlap exclusion) and 32-60 (close-then-insert, same-UTC-day rule).
```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE instrument_classification
    ADD CONSTRAINT ex_instrument_classification_no_overlap
    EXCLUDE USING gist (
        symbol WITH =,
        scheme WITH =,
        daterange(valid_from, valid_to, '[)') WITH &&
    );
```
`listing_venue(symbol, venue, valid_from, valid_to)` takes this exactly (key `symbol`). Note one deviation: 367 refuses backdated `valid_from`; `listing_venue` is inferred from historical D1 spans, so its trigger must allow historical `valid_from` on insert (history is reconstructed, not recorded forward) while still refusing UPDATE of identity columns and DELETE/TRUNCATE. State the deviation in the header. `corporate_action` is pure append (366 `fn_research_run_no_delete` shape) with a nullable `supersedes` self-reference for corrections (RESEARCH Pattern 3).

---

### APR seed blocks (all migrations adding keys)

**Analog:** `production/migrations/376_dividend_events.sql` lines 89-143
```sql
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'threshold.dividend_event.noise_margin',
        'float',
        '1.25',
        '1.0', NULL,
        '[initial_estimate] Multiple of ... Changing it changes which events are derived. Not an ML learning target.'
    ),
    ...
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('threshold.dividend_event.noise_margin', '1.25', 1),
    ...
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'threshold.dividend_event.noise_margin', 1, '1.25', 'migration_376', 'Initial value [initial_estimate]'),
    ...
ON CONFLICT DO NOTHING;
```
Every description starts with a provenance tag (`[initial_estimate]`, `[conventional]`, `[rca_analysis]`, `[user_preference]`) and ends with the ML-target statement. JSON-list keys use `value_type 'json'` (374 lines 37-43). Survivorship seeds from RESEARCH "Code examples" go in as `[conventional]`, with `[ASSUMED]` values (Shumway 1997, small-cap haircut) called out in the description. The D7 close tolerance is `[rca_analysis]` from the 2024 distribution (p99 about 15 bp).

---

### `src/intelligence/bars/scrub_rules.py` (pure rule module, transform)

**Analog A:** `src/intelligence/statistics/price_sanity.py`

Imports and frozen verdict dataclass (lines 12-31):
```python
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Any, Literal

@dataclass(frozen=True)
class CandidateVerdict:
    verdict: str  # "CONFIRMED_CORRUPT" | "AMBIGUOUS" | "PLAUSIBLE" | "MARKET_EVENT"
    implausible_fields: tuple[str, ...]
    max_ratio: float
    neighbor_ratio: float | None
    reason: str
```
Keyword-only thresholds with APR defaults supplied by the caller (lines 34-44):
```python
def classify_candidate_bar(
    *,
    open_: float, high: float, low: float, close: float,
    prev_close: float | None, next_open: float | None,
    magnitude_threshold: float = _MAGNITUDE_THRESHOLD_DEFAULT,
    neighbor_agreement_threshold: float = _NEIGHBOR_AGREEMENT_THRESHOLD_DEFAULT,
) -> CandidateVerdict:
```
The defect to wrap (lines 124-145): `apply_cross_symbol_downgrade` downgrades any CONFIRMED_CORRUPT when `n_corroborating + 1 >= min_symbols`, ignoring magnitude. Import it and `classify_candidate_bar`; do not edit `price_sanity.py` (bar_auditor and the cleanup script import it). The ceiling wrapper is RESEARCH "Corroboration with a clearing ceiling" (a `corroborated_verdict(verdict, n, *, min_symbols, max_clearable_ratio)` that returns the verdict unchanged when `verdict.max_ratio > max_clearable_ratio`).

Note: `price_sanity.py` imports `asyncpg` at module top for `count_corroborating_symbols_batch`; the new module must not (Ring 1 pure, no DB). Take neighbor arrays as inputs.

**Analog B (pure-function style, flags returned not stored):** `services/dividend_event_writer.py` lines 151-196. Counts of rejected cases are fields on the result (`n_downward_steps`, `n_unstable_steps`), never per-row logs:
```python
@dataclasses.dataclass(frozen=True)
class Derivation:
    events: list[DividendEvent]
    covered_from: date
    covered_to: date
    n_downward_steps: int = 0
    n_unstable_steps: int = 0
```
Raise `ValueError` on inputs the rule cannot judge (line 164-167) rather than guessing.

**Flag parity source (D-14):** `services/forward_return_writer.py` lines 297-309 define `has_gap_before_entry`:
```sql
(entry_ts IS NOT NULL
    AND EXTRACT(EPOCH FROM (entry_ts - bar_ts)) > %(gap_multiplier)s * %(tf_seconds)s
    AND EXTRACT(EPOCH FROM (entry_ts - bar_ts)) < %(gap_max_seconds)s
) AS has_gap_before_entry
```
and lines 257-260 the suspect ceiling `abs(return_{scale}) > max_abs_return_{scale}`, scaled by `scale_max_abs_return` in `src/intelligence/statistics/ic_math.py` line 404 (sqrt of lookahead). Port the semantics into numpy; keep the APR keys `alpha.quant.max_abs_return.{tf}`, `alpha.forward_returns.gap_multiplier`, `alpha.forward_returns.gap_max_seconds`.

---

### `src/intelligence/bars/seams.py` and `corporate_actions.py` (pure, transform)

**Analog:** `services/dividend_event_writer.py`

Series join that refuses mismatched days (lines 116-132), the model for "stored close vs fresh close per common day":
```python
def join_adjustment_pairs(
    trades: dict[date, float], adjusted: dict[date, float]
) -> list[tuple[date, float, float]]:
    if not trades or not adjusted:
        raise ValueError("empty daily series")
    lo = max(min(trades), min(adjusted))
    hi = min(max(trades), max(adjusted))
    t_days = {d for d in trades if lo <= d <= hi}
    a_days = {d for d in adjusted if lo <= d <= hi}
    if t_days != a_days:
        raise ValueError(...)
    return [(d, trades[d], adjusted[d]) for d in sorted(t_days)]
```
Ratio-step with lockstep stability on both sides (lines 172-196) is the direct template for "constant ratio over a run of at least `min_run` days" in `find_seams`.

Disputed-date rule (D-23) template, `reconcile` lines 259-261:
```python
ibkr_only = sorted(ibkr.keys() - yahoo_events.keys())
yahoo_only = sorted(yahoo_events.keys() - ibkr.keys())
near = [(i, y) for i in ibkr_only for y in yahoo_only if abs((i - y).days) <= match_days]
```
`match_days` is `threshold.dividend_event.ex_date_match_days` (APR, 376). The new rule turns each `near` pair into a disputed-date record whose span marks returns unknown instead of failing the symbol.

---

### `src/intelligence/bars/session_grid.py` (pure utility, aggregation)

**Analog A (aggregation body):** `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py` lines 980-1017 (`aggregate_bars_from_1m`):
```python
result.append(
    {
        "timestamp": window_start,
        "open": w[0]["open"],
        "high": max(b["high"] for b in w),
        "low": min(b["low"] for b in w),
        "close": w[-1]["close"],
        "volume": sum(b.get("volume", 0) or 0 for b in w),
        "source": SOURCE_DERIVED_1M,
    }
)
```
Do not copy its bucketing: it floors from midnight UTC (`ts.hour * 60 + ts.minute`), which gives :00 edges, the exact bug D-15 replaces. Bucket from the session open instead (RESEARCH Pattern 5, `k = (ts - session_open) // minutes`), vectorized in numpy, never across the session close.

**Analog B (session bounds):** `src/core/market_calendar.py` lines 43-56:
```python
def _build_daily_sessions(pmc_name: str) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    cal = mcal.get_calendar(pmc_name)
    schedule = cal.schedule(_PMC_RANGE_START, _PMC_RANGE_END)
    return dict(
        zip(
            schedule.index.strftime("%Y-%m-%d"),
            zip(schedule["market_open"], schedule["market_close"]),
        )
    )
```
`market_calendar.py` is imported by ic_engine: do not edit it. Either call `_build_daily_sessions("NYSE")` from a new helper, or inject sessions as an argument (`session_open_utc`, `session_close_utc` arrays) so the pure function stays calendar-free and tests pass fake sessions (half day 2025-11-28, DST 2025-03-10 and 2025-11-03).

---

### `src/intelligence/bars/digest.py` (pure utility, hash)

**Analog:** `src/core/agent/base_batch.py` `content_key` (lines 139-154):
```python
@staticmethod
def content_key(*parts: str) -> str:
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
```
Use `hashlib.sha256` over rows sorted by timestamp (the D-07 test requires order independence), including flag state and `RULE_VERSION`. Keep the full hex digest (a 32-character prefix is fine for keys but the digest is a content identity 186 consumes; decide once and document). Do not place it in `services/_batch_utils.py` (ic_engine import, RESEARCH finding 7).

---

### `src/intelligence/bars/labels.py`, `venue_study.py`, `derivation.py` (pure rule modules)

**Analog:** `src/intelligence/research/dividends.py` `DisputeRule` (lines 89-102), a frozen rule object that carries its APR values and is shared by the writer and the reader:
```python
class DisputeRule:
    """When two sources' yields for one ex-date disagree: ... The writer's reconciliation and
    the research reader share it, with the writer's APR values (...), which S0 records in the
    snapshot manifest."""

    rel_tolerance: float
    noise_margin: float

    def disagree(self, yahoo_yield: float, ibkr_yield: float, ibkr_prev_close: float) -> bool:
        ...
```
Model the D0 label and survivorship-bound parameters the same way (a frozen dataclass built from APR by the caller, recorded in the snapshot manifest). `research/` is owned by the phase 183 lane: import from it read-only, and put nothing new there (RESEARCH finding 6, Open question 3). `venue_study.py` returns a frozen result dataclass like `Reconciliation` (dividend writer lines 236-241) with per-criterion pass/fail.

---

### `services/ohlcv_observation_writer.py` (writer, COPY)

**Analog A (COPY mechanics, psycopg):** `services/_batch_utils.py` lines 144-162:
```python
with conn.cursor() as cur:
    ...
    buf = io.StringIO()
    writer = csv.writer(buf)
    for row in rows:
        writer.writerow("" if v is None else v for v in row)
    buf.seek(0)
    with cur.copy(
        f"COPY {temp_table} ({', '.join(all_cols)}) FROM STDIN WITH (FORMAT CSV)"
    ) as copy:
        copy.write(buf.getvalue())
```
This is the only COPY in the tree. The backfill pipeline is psycopg (sync), so a psycopg `cur.copy` path fits the capture inside `_persist_chunk`; for asyncpg callers (`BaseBatch` jobs) use `conn.copy_records_to_table(table, records=..., columns=...)` (RESEARCH standard stack). Prefer psycopg's `copy.write_row(row)` over CSV text to avoid float/None formatting drift.

**Analog B (call-site shape, connection health, commit):** `store_bars` in `infrastructure_run_historical_pipeline.py` lines 1069-1113 and `_persist_chunk` lines 1538-1562 (the `SELECT 1` reconnect guard before every write). The writer runs `SET ROLE ohlcv_observation_writer` once per connection, then appends; never UPDATE.

**Placement note:** a module under `services/` imported by a script; it is a persistence helper, not a daemon, so no `_DAG_ORDER` row. DAG invariant 3: `ibkr.py` hands records to a callback, this module persists them.

---

### `services/bar_derivation.py` (batch oneshot, D2/D2a/D2b)

**Analog:** `services/dividend_event_writer.py`

Imports (lines 43-63):
```python
from __future__ import annotations

import argparse
import asyncio
import dataclasses
from datetime import UTC, date, datetime, timedelta

import asyncpg

from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async
from src.config.settings import Settings, get_active_contracts
from src.core.agent.base_batch import BaseBatch
from src.observability.metrics import counter
from src.observability.otel import OTelInitError, init_otel_providers
```
Job identity and outcome counter, never labeled by symbol (lines 65-73):
```python
_JOB = "dividend-event-writer"
_OUTCOME_TOTAL = counter(
    "dividend_event_outcome_total",
    "... Never labeled by symbol.",
)
```
BaseBatch subclass with `job_name` and `compute_version` (lines 280-300); `compute_version` is where the derivation's `RULE_VERSION` surfaces.

APR load at the top of `execute` (lines 302-313):
```python
async with pool.acquire() as conn:
    apr = await load_apr_dict_async(
        conn,
        ["threshold.dividend_event.%", "infra.dividend_event.%", "infra.ibkr.rate_limit%"],
    )
margin = float(_cfg(apr, "threshold.dividend_event.noise_margin", 1.25))
```
Per-symbol transaction, symbol failure collected, run fails at the end (lines 331-414):
```python
try:
    async with pool.acquire() as conn, conn.transaction():
        ...
except _SymbolFailure as error:
    failed.append(f"{symbol}: {error}")
    continue
...
for outcome, n in {**totals, "failed": len(failed)}.items():
    _OUTCOME_TOTAL.add(n, {"sources": sources, "outcome": outcome})
if failed:
    raise RuntimeError(f"dividend_event_writer: {len(failed)} failures: {failed}")
```
`main()` (lines 552-571): `init_otel_providers(f"indicagent-{_JOB}")` inside `try/except OTelInitError: pass`, `Settings()`, DSN via `settings.database_url.replace("postgresql+asyncpg://", "postgresql://")`, `asyncio.run(writer.run())`. `BaseBatch.run()` emits `job_completed_total{job, status}` and flushes OTel (base_batch.py lines 105-135), so the job does not emit it itself.

Compressed-hypertable writes: the D2b per-(symbol, tf) archive, delete, insert transaction and the 1d canonical writes go through `async_compressed_hypertable_write_session(conn, "market_data_ohlcv")` / `compressed_hypertable_write_session(..., decompress=False)` (`services/_batch_utils.py` lines 474-500, 841), which documents the measured 3.9 s native upsert per 4,834-row segment. Measure first in 185-01 (A5, A7). No row-level UPDATEs on `market_data_ohlcv`; flags go to `bar_quality_flag`.

Historical scan SQL shape: `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py` `_scan_and_classify` (lines 300-347) reads per (symbol, tf) from the tradeable view with LAG/LEAD neighbors and classifies in Python. For the pass over 3.86M rows, fetch per symbol into numpy arrays (CLAUDE.md: never materialize a wide DataFrame; derive dtypes from `get_attributes()`), classify vectorized, accumulate counts, emit one integrity fact per run.

---

### `services/bar_reconciliation_audit.py` (batch oneshot, D7)

**Analog:** `src/config/classification_coverage.py`

Contract statement (module docstring lines 10-12): observability only; a finding is reported loudly (one `integrity_monitor` row, an OTel counter, `logger.error` naming symbols), never through a failing exit code; only a runtime error propagates.

Imports (lines 25-45) and pure/IO split ("Pure coverage logic -- no IO, unit-testable" section header, line 59). Emission (lines 133-157):
```python
async with pool.acquire() as conn:
    await emit_integrity_fact_async(
        conn,
        _MONITOR_TYPE,
        DEFAULT_SCHEME,
        "uncovered_active_count",
        float(n_uncovered),
        0.0,
        n_uncovered == 0,
        None,
    )
```
Signature (`src/core/integrity_monitor.py` lines 144-155): `(conn, monitor_type, subject, metric_name, metric_value, threshold_value, passed, training_window_end, *, idempotency_check=False)`, never raises. Use `idempotency_check=True` if the audit is keyed by session date and must not duplicate on a rerun. Subject key shape for per-bar facts: `build_subject_key(symbol, tf, timestamp_iso)` in `price_sanity.py` line 148 (`"symbol=...|tf=...|ts=..."`). Grafana has no Postgres datasource (RESEARCH finding 15b): each check also records an OTel gauge/counter labeled by check name only.

---

### `scripts/ops/bars/*.py` (one-off IBKR jobs and reports)

**Analog A (dry-run default, report rendering, argparse):** `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py`, docstring lines 1-60 ("defaults to --dry-run behavior ... Mutating ... REQUIRES the explicit --apply flag"), `render_dry_run_report` line 185, `_parse_args` lines 402-433, `_run` line 435, `main` line 548.

**Analog B (IBKR provider setup and fixed client id):** `services/dividend_event_writer.py` lines 321-330 and 398-400:
```python
provider = IBKRProvider(
    host=self._settings.ib_host,
    port=self._settings.ib_port,
    client_id=self._client_id,
)
if not await provider.connect():
    raise RuntimeError("dividend_event_writer: cannot connect to IBKR")
...
finally:
    if provider is not None:
        await provider.disconnect()
```
plus the rate-limit overlay (line 308): `apply_hist_rate_limit_config({k: apr[k] for k in HIST_RATE_LIMIT_KEYS if k in apr})`. Client IDs 46-49 (RESEARCH runtime inventory), all at most `_MAX_CLIENT_ID` 50. Refuse to start when a backfill is running, reusing `_is_another_backfill_running()` from `infrastructure_nightly_backfill.py` lines 80-92 (Pitfall 6).

**Analog C (paired TRADES + ADJUSTED_LAST in one run):** dividend writer `_derive` lines 438-452; the D1 bootstrap shares one `fetch_run_id` across both requests.

The D3 study commits its pre-registered thresholds before fetching (185-06); put them in the script's docstring or a committed JSON next to it, not in argparse defaults.

---

### `production/systemd/indicagent-bar-derivation.service`, `indicagent-bar-reconciliation-audit.service`

**Analog:** `production/systemd/indicagent-dividend-event-writer@.service`
```ini
[Unit]
Description=IndicAgent Dividend Event Writer (source %i) -- todo 428, services/dividend_event_writer.py
After=network.target indicagent-infrastructure.target
Requires=indicagent-infrastructure.target

[Service]
Type=oneshot
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/dividend_event_writer.py --sources %i
```
Chaining after the nightly: `indicagent-nightly-backfill.service` is a single `ExecStart` oneshot with no `ExecStartPost`/`OnSuccess` anywhere in `production/systemd/`. Either add `ExecStartPost=` lines to the nightly unit, or call the audit from `infrastructure_nightly_backfill.py` `main()` after the legs (same `subprocess.run` shape as `_run_delegate`, lines 156-171). The in-script call is the one that also sees the `skipped_concurrent_run` path (lines 187-191) and can record "nightly skipped" as a failed fact (Pitfall 7); `ExecStartPost` does not run on a skip that exits 0 differently. The `job` label must equal the unit suffix (`bar-derivation`, `bar-reconciliation-audit`). Register both in `services/service_auditor.py` `_ONESHOT_UNITS` (lines 183-215) and `_DAG_ORDER` (line 57); `tests/unit/test_service_auditor_registry_integrity.py` requires the unit files to exist.

---

### `tests/unit/bars/*` (pure unit tests)

**Analog:** `tests/unit/services/test_dividend_event_writer.py` lines 1-60

Module docstring says how synthetic series are built; constants mirror APR seeds; a small builder produces series; seeds are parametrized:
```python
from services.dividend_event_writer import (
    Derivation, DividendEvent, derive_ibkr_events, ...
)
from src.intelligence.research.dividends import DisputeRule

MARGIN = 1.25
STABLE = 3
RULE = DisputeRule(rel_tolerance=0.1, noise_margin=MARGIN)

def _series(closes, dividends):
    """dividends: {row index of ex-date: amount}. Returns (day, close, adjusted) rows."""
    ...

def _walk(n, start_price, seed):
    rng = np.random.default_rng(seed)
    return np.round(start_price * np.exp(np.cumsum(rng.normal(0, 0.012, n))), 2)

@pytest.mark.parametrize("seed", range(20))
```
Known-answer tests read `tests/fixtures/bars/*.csv` (copy `corrupt_1d.txt` out of the other session's `/tmp` scratchpad first, 185-01). `tests/unit/bars/__init__.py` is required (the tree uses packages: `tests/unit/research/__init__.py`, `tests/unit/services/__init__.py`).

---

### `tests/unit/test_ohlcv_observation_migration_contract.py` (test, SQL source grep)

**Analog:** `tests/unit/test_earnings_season_migration_contract.py` lines 1-35
```python
from tests.unit._source_grep_helpers import read_source

_SQL_LINE_COMMENT_RE = re.compile(r"--[^\n]*")

def _migration_text_no_comments() -> str:
    raw = read_source("production", "migrations", "350_earnings_season_calendar_primitive.sql")
    return _SQL_LINE_COMMENT_RE.sub("", raw)

def test_adds_both_new_columns():
    sql = _migration_text_no_comments()
    assert "ADD COLUMN IF NOT EXISTS earnings_season_flag" in sql
```
Assert: both append-only triggers (row-level UPDATE/DELETE and statement-level TRUNCATE) on each D1 table, both NOLOGIN roles, no UPDATE/DELETE grant to `ohlcv_observation_writer`, the view keeps its 11-column order. The live refusal checks (trigger raises, role refuses cross-write) are an integration test against the DB, not unit.

---

### `tests/unit/test_market_data_ohlcv_writer_boundary.py` (CI grep, single writer)

**Analog:** `tests/unit/test_market_data_ohlcv_boundary.py`
```python
from tests.unit._source_grep_helpers import (
    assert_allow_list_has_no_stale_entries,
    assert_no_unlisted_references,
    find_pattern_references,
)

_REPO_ROOT = Path(__file__).parent.parent.parent
_RAW_TABLE_PATTERN = re.compile(r"\b(?:FROM|JOIN)\s+market_data_ohlcv\b(?!_tradeable)")
_SEARCH_DIRS = ("services", "src", "scripts")

_ALLOW_LIST: dict[str, str] = {
    "services/bar_auditor.py": ("PERMANENT: ..."),
    ...
}

@functools.lru_cache(maxsize=1)
def _find_raw_table_references() -> dict[str, int]:
    return find_pattern_references(
        _REPO_ROOT, _SEARCH_DIRS, _RAW_TABLE_PATTERN, file_globs=("*.py", "*.sh")
    )

def test_every_raw_market_data_ohlcv_reference_is_on_the_allow_list(): ...
def test_allow_list_has_no_stale_entries(): ...
```
Pattern for writers: `r"\b(?:INSERT\s+INTO|UPDATE)\s+market_data_ohlcv\b"`. Known write sites today (RESEARCH finding 2): `infrastructure_run_historical_pipeline.py` (`_STORE_VALUES_SQL` line 812), `services/backfill_feature_factory.py` (`_STORE_OHLCV_SQL`), `services/bar_writer.py`, `services/bar_auditor.py` and `ops_known_corrupt_print_cleanup.py` (UPDATE `price_sanity_status`). Each allow-list reason must name the timeframes the site may write; `services/bar_derivation.py` is the only one allowed 1d/15m/1h. Every entry reason is prefixed `PERMANENT:` or `TEMPORARY:` like the analog.

Also edit the analog itself: add `services/bar_derivation.py` and `services/bar_reconciliation_audit.py` to `test_market_data_ohlcv_boundary.py` `_ALLOW_LIST` if they read the raw table (the derivation writes it; D7 counts sources other than the derivation's). Extend `test_compressed_hypertable_write_boundary.py` `_RAW_UPDATE_PATTERN` (line 30) to include `market_data_ohlcv`, which will require allow-list rows for `bar_auditor.py` and the cleanup script.

---

### MOD `src/providers/ibkr.py` (provider, request-response)

**Analog:** its own callbacks. Signature (lines 722-731):
```python
async def fetch_historical_bars(
    self,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    continuous: bool = False,
    on_chunk: Callable[[list[OHLCVBar]], Awaitable[None]] | None = None,
    on_empty_history: Callable[[EmptyHistory], None] | None = None,
) -> list[OHLCVBar]:
```
Docstring rationale to repeat for `on_request` / `on_observation` (lines 746-755): "ibkr.py stays DB-ignorant (DAG invariant 3) since the callback itself is the caller's." Thread the new callbacks through `_fetch_historical_bars_impl` (lines 782-876) and `_walk_history` (lines 878-1071). Per-request outcome points already exist inside the retry loop of `_walk_history`: success (`if result: ... break`, line 964), definitive no data (`req_id in _no_data_req_ids`, lines 970-983), outer timeout (lines 952-963), all retries failed (the `for ... else` at lines 1000-1011). Emit one request record at each. `reqId` comes from `getattr(result, "reqId", None)` (line 970).

Venue bars in verify-only mode are discarded at line 1134 (`return (best if _VENUE_FALLBACK_STORE_BARS else []), None`) and the walk is called with `on_chunk=None` (line 1113). Deliver every venue's bars to `on_observation` there, regardless of `_VENUE_FALLBACK_STORE_BARS`. The `logger.warning("ibkr.hist_venue_fallback_recovered", extra={...})` at lines 1122-1132 uses stdlib logging (`logger = logging.getLogger(__name__)`, line 69), whose `extra=` fields are dropped (RESEARCH finding 1): switch that event to structlog keyword fields, or rely on D1 for the inventory.

ADJUSTED_LAST path (lines 1184-1228): `_request_back_from_now` and `fetch_adjusted_daily_closes` also need the request record and the shared `fetch_run_id`.

---

### MOD `tests/unit/providers/test_ibkr_provider.py` (fake IB)

**Analog:** `TestPreMoveHistory` (lines 517-582). Fake `reqHistoricalDataAsync` keyed by routed exchange, producing bars, definitive no data (a `BarDataList` with a `reqId` registered in `ibkr_module._no_data_req_ids`), or `TimeoutError`:
```python
async def fake_req(contract, **kwargs):
    asked.append(contract.exchange)
    answer = answers.get(contract.exchange, "no_data")
    if answer == "timeout":
        raise TimeoutError
    if answer == "no_data":
        req["n"] += 1
        result = BarDataList()
        result.reqId = 92000 + req["n"]
        ibkr_module._no_data_req_ids.add(result.reqId)
        return result
    return answer

mock_ib.reqHistoricalDataAsync = AsyncMock(side_effect=fake_req)
provider._ib = mock_ib
contract = Stock("XYZ", "SMART", "USD", primaryExchange=primary)
contract.secType = "STK"
provider._qualified_contracts["XYZ"] = contract
with (
    patch.object(ibkr_module, "_RETRY_COUNT", 1),
    patch.object(ibkr_module, "_VENUE_FALLBACK_STORE_BARS", store),
):
    bars = await provider.fetch_historical_bars(
        "XYZ", timeframe, self.START, self.END,
        on_chunk=on_chunk, on_empty_history=reports.append,
    )
ibkr_module._no_data_req_ids.clear()
```
Add `on_request=records.append, on_observation=...` to `_fetch` and name new tests with `request_record` so `-k request_record` selects them. Cases: one record per SMART and per venue request; no-data and timeout outcomes; venue bars reach `on_observation` with `store=False` (mirror `test_verify_only_stores_nothing_but_blocks_empty_record`, lines 627-636).

---

### MOD `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py`

**Analog:** its own wiring (lines 1584-1592):
```python
ohlcv_bars = await provider.fetch_historical_bars(
    symbol=instrument.symbol,
    timeframe=tf,
    start=gap_start,
    end=gap_end,
    continuous=use_cont,
    on_chunk=_persist_chunk,
    on_empty_history=observed.append if is_oldest_window else None,
)
```
Add the D1 capture callbacks here (185-02). APR overlay for any new provider switch follows `_load_ibkr_venue_fallback_config` (lines 545-576): one `SELECT config_key, config_value FROM config_state WHERE config_key LIKE ...`, overlay module globals, fall back with a printed message on failure. In 185-09, `detect_gaps` (line 858) must read D1 for 1d, and the 1d `store_bars` path stops writing `market_data_ohlcv`. This file is on the raw-read allow-list already; its reason text must be updated when the write paths change.

---

### MOD `scripts/infrastructure/backfill/infrastructure_nightly_backfill.py`

**Analog:** its own `_finish` (lines 174-180) and skip path (lines 187-191):
```python
def _finish(status: str, message: str, returncode: int = 0) -> int:
    _logger.info(f"nightly_backfill.{status}")
    print(message)
    JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
    flush_and_shutdown_metrics()
    return returncode
```
Non-BaseBatch oneshots emit `job_completed_total` directly like this. `_NIGHTLY_CLIENT_ID = 45` (line 77) collides with the dividend writer default (`--client-id` 45, dividend writer line 559); 185 jobs use 46-49.

---

### MOD `scripts/infrastructure/backfill/_empty_history.py` (D4)

**Analog:** its own `record` (lines 98-153): psycopg upsert into `ohlcv_empty_history` keyed `(symbol, timeframe, provider)`, confirmations accumulate across runs via `prior`, `conn.commit()` at the end. D4 feeds `EmptyHistory` (`src/providers/base.py` line 169: `verified_from`, `empty_through`, `n_confirming_chunks`, `reached_request_start`) from `ohlcv_request` outcomes instead of the in-memory walk; keep the same record/merge semantics.

---

### MOD `services/dividend_event_writer.py` (D5 I/O swap)

**Analog:** its own `_derive` (lines 416-452). Only the IBKR branch changes: replace the two provider calls (lines 439-447) with a D1 read of TRADES and ADJUSTED_LAST closes for one `fetch_run_id`, then keep line 450 unchanged:
```python
return derive_ibkr_events(join_adjustment_pairs(closes, adjusted), margin, stable)
```
`join_adjustment_pairs`, `derive_ibkr_events`, `reconcile`, `vanished_ex_dates`, `DisputeRule` stay byte-identical (D-22). `_write` and `_reconcile` (lines 454-549) are unchanged. The existing tests (`tests/unit/services/test_dividend_event_writer.py`) must pass untouched; add a D1-read test that reproduces the interim writer's events on stored fixtures (JPM, KO, XLU; NVR 2004 derives nothing).

## Shared patterns

### APR loading in batch jobs
**Source:** `services/_batch_utils.py` lines 787-806 (`load_apr_dict_async`) and 955-980 (`cfg`)
**Apply to:** `bar_derivation.py`, `bar_reconciliation_audit.py`, `scripts/ops/bars/*`
```python
apr = await load_apr_dict_async(conn, ["threshold.bar_scrub.%", "infra.bar_derivation.%"])
tol = float(_cfg(apr, "threshold.bar_reconciliation.close_tolerance_bp", 15.0))
```
`load_apr_dict_async` always includes `alpha.%`. `cfg` handles bool (`"false"` text) and JSON list/dict defaults correctly; never `type(default)(val)` by hand. Import only, never edit `_batch_utils.py` (ic_engine import). Pure modules receive plain floats/ints, never a ConfigService.

### Oneshot lifecycle and D-06 metric
**Source:** `src/core/agent/base_batch.py` lines 38-135
**Apply to:** every new `services/` job
Subclass `BaseBatch`, set `job_name` (kebab-case, equal to the systemd unit suffix) and `compute_version`, implement `async def execute(self, pool)`. `run()` opens the pool with the JSONB codec, wraps `execute` in a span, emits `job_completed_total{job, status}` and `job_duration_seconds`, flushes OTel. Logs go to `logs/<job_name with _>.log` automatically.

### Integrity facts
**Source:** `src/core/integrity_monitor.py` lines 87-196
**Apply to:** D2a historical pass (one fact per run plus per-rule counts), D7 audit, 381-name re-run counts
Use `emit_integrity_fact_async` (asyncpg) or `emit_integrity_fact_sync` (psycopg, the backfill path). Never a raw INSERT into `integrity_monitor`. The helper never raises.

### Error handling
**Source:** `services/dividend_event_writer.py` lines 276-277, 353-374, 413-414
**Apply to:** all batch jobs and scripts
A private `_SymbolFailure(Exception)` for per-symbol failures; the loop collects them and the run raises `RuntimeError` at the end with the count. Exception variable is always `error` (`except _SymbolFailure as error:`); a validation `ValueError` from a pure function is caught as `except ValueError as invalid:` and re-raised `from invalid` (lines 433-434, 451-452), the one naming exception the analog uses.

### Logging and counts
**Source:** `services/dividend_event_writer.py` lines 375-409
**Apply to:** every loop over symbols or bars
structlog keyword fields (`self.logger.warning("dividend_event_writer.rejected_steps", symbol=symbol, downward=...)`), never `event=`, never stdlib `extra=`. Accumulate `totals` in a dict and log once per run; per-symbol warnings only when non-zero; never per bar.

### Timestamps and serialization
**Source:** CLAUDE.md; `format_iso_ts` used in `ops_known_corrupt_print_cleanup.py` (`timestamp=format_iso_ts(r["timestamp"])`)
**Apply to:** all new code
`datetime.now(UTC)` only; `format_iso_ts` for strings.

### Raw-table and single-writer boundaries
**Source:** `tests/unit/test_market_data_ohlcv_boundary.py`, `tests/unit/_source_grep_helpers.py`
**Apply to:** any new file that reads or writes `market_data_ohlcv`
Compute reads go through `market_data_ohlcv_tradeable`; each raw read or write needs an allow-list row with a `PERMANENT:`/`TEMPORARY:` reason in the same diff.

### ic_engine import set
**Source:** RESEARCH finding 8
**Apply to:** all plans
Do not edit `services/_batch_utils.py`, `src/core/bar_normalizer.py`, `src/core/market_calendar.py`. New constants such as a derivation source tag live in `src/intelligence/bars/`, not in `bar_normalizer.py` (where `SOURCE_IBKR_VENUE` lives today).

## No analog found

| File | Role | Data flow | Reason |
|---|---|---|---|
| Role creation and `SET ROLE` in 380 and in the writers | migration + connection setup | access control | No migration creates a role; no code runs `SET ROLE`. Use RESEARCH Pattern 4. |
| asyncpg `copy_records_to_table` writer | writer | COPY | The only COPY is psycopg `cur.copy` in `bulk_update_by_key`; asyncpg COPY has no in-repo example. |
| `tests/integration/test_derived_grid_live.py` | integration test | read-only DB | Not searched for an analog within the 3-5 analog budget; use the D-15 check query ("no symbol has 1h rows at both :00 and :30 in one session"). |

## Metadata

**Analog search scope:** `production/migrations/` (366-379), `production/systemd/`, `services/` (dividend_event_writer, _batch_utils, forward_return_writer, service_auditor), `src/core/` (integrity_monitor, agent/base_batch, market_calendar), `src/intelligence/statistics/price_sanity.py`, `src/intelligence/research/dividends.py`, `src/config/classification_coverage.py`, `src/providers/ibkr.py`, `src/providers/base.py`, `scripts/infrastructure/backfill/` (historical pipeline, nightly, _empty_history, rate-limit probe), `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py`, `tests/unit/` (boundary, compressed-write boundary, migration contract, provider, dividend writer, research)
**Files scanned:** 24
**Pattern extraction date:** 2026-09-27
