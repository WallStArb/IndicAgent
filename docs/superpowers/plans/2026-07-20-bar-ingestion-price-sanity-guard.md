# Bar-Ingestion Price-Sanity Guard (todo 149) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every consumer of `market_data_ohlcv`/`market_data_ohlcv_tradeable` inherits protection
from bar-level price corruption (a corrupt IBKR print like `open=1000` on a $25 ETF) without code
changes — the same way the existing `volume > 0` filter already protects against synthetic
calendar-fill bars. Detection and cross-symbol corroboration reuse todo 151/152's already-shipped,
already-live-verified logic; the check runs as a bounded task inside the existing `BarAuditor`
daemon, not a new service.

**Architecture:** A new nullable `price_sanity_status` column on `market_data_ohlcv` acts as both
the classification result and the audit watermark (`NULL` = unaudited). `BarAuditor` gains a
bounded, APR-paced async task that finds unaudited bars whose next bar has landed, classifies
them via a shared, promoted `classify_candidate_bar()`, corroborates cross-symbol via a new
batched primitive, and writes the verdict back. `market_data_ohlcv_tradeable`'s predicate is
extended to exclude only `confirmed_corrupt` rows, NULL-safely. Todo 151's `--apply` step is
updated to use the same column going forward, and its 18 already-corrected rows are reconciled
onto it in the same migration.

**Tech Stack:** Python 3.14, asyncpg, PostgreSQL/TimescaleDB (compressed hypertable), pytest.

**Design doc:** `docs/superpowers/specs/2026-07-20-bar-ingestion-price-sanity-guard-design.md`
(informed by a Fable 5 architectural review — read it for the full reasoning behind the decisions
below; this plan implements it as specified.)

## Global Constraints

- All tunable numeric thresholds/weights/periods/batch-sizes go through the Adaptive Parameter
  Registry (APR) — never a hardcoded Python constant. `classify_candidate_bar()`'s
  `magnitude_threshold`/`neighbor_agreement_threshold` become APR-backed as part of this plan
  (they were acceptable as CLI-only overrides for a human-invoked ad hoc script, but are now
  embedded in an always-on daemon, which CLAUDE.md's "migrate-as-you-go" rule requires fixing in
  the same session).
- Never drop data. Flag, don't delete. `market_data_ohlcv_tradeable`'s new predicate must be
  NULL-safe (`IS DISTINCT FROM`, never a bare `!=`/`<>`) — a plain inequality against a NULL
  column evaluates to NULL (falsy in `WHERE`), which would make every newly-inserted live bar
  invisible until audited, injecting unintended read-latency into the real-time pipeline.
- Never log per-row inside a loop over a batch — accumulate counts per status per audit tick,
  log once.
- Exception variable name is `error`, not `exc`.
- `market_data_ohlcv` reads for compute/measurement use `market_data_ohlcv_tradeable`
  (`WHERE volume > 0 ...`), not the raw table, per CLAUDE.md's boundary rule — the one exception
  is the price-sanity audit's own candidate-discovery query, which must read the raw table
  (candidates are unaudited rows, which by definition might not yet be excluded/included
  correctly by the view) — this is an intentional, documented exception, not a violation.
- **Scope decision, stated explicitly:** the new batched cross-symbol-corroboration primitive
  (Task 3) is built and proven for THIS plan's own caller (`BarAuditor`'s price-sanity task,
  exact-timestamp match mode — raw bars are the event itself, per todo 151's own established
  precedent). `forward_return_writer.py`'s existing, already-twice-battle-tested window-mode
  corroboration pass (todo 152) is **not** refactored onto this primitive in this plan — that is
  higher-risk work on already-proven production code with no forcing need right now, and is left
  as a documented future opportunity once this primitive has itself been proven live. The
  primitive's `match_mode` parameter is a required, explicit `Literal["exact", "window"]` with no
  default (per the design doc — an abstraction that silently picks a mode is how both prior
  corroboration bugs happened), but only `"exact"` is implemented in this plan; `"window"` raises
  `NotImplementedError` pointing at `forward_return_writer.py`'s existing implementation as the
  reference for whoever builds it later.

---

## File Structure

- **Create:** `production/migrations/242_price_sanity_status_bar_ingestion.sql` — schema,
  view-predicate update, partial index, 3 APR keys, one-time reconciliation of 151's 18 rows.
- **Create:** `src/intelligence/statistics/price_sanity.py` — promoted `classify_candidate_bar`,
  `CandidateVerdict`, `apply_cross_symbol_downgrade`, `build_subject_key` (moved verbatim from
  `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py`), plus the new batched corroboration
  primitive.
- **Create:** `tests/unit/intelligence/test_price_sanity.py` — tests for everything in the new
  module (moved + new).
- **Modify:** `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py` — import from the shared
  module instead of defining locally; `--apply` stamps `price_sanity_status` instead of `volume`.
- **Modify:** `tests/unit/test_known_corrupt_print_cleanup.py` — update imports; update the
  correction-SQL test for the new UPDATE target.
- **Modify:** `services/bar_auditor.py` — new bounded price-sanity audit task, own connection
  pool, wired into the existing `_run_audit` cycle.
- **Modify:** `tests/unit/services/test_bar_auditor.py` — tests for the new task.

---

### Task 1: Migration — schema, view predicate, index, APR keys, reconciliation

**Files:**
- Create: `production/migrations/242_price_sanity_status_bar_ingestion.sql`

**Interfaces:**
- Produces: `market_data_ohlcv.price_sanity_status` (nullable text), the updated
  `market_data_ohlcv_tradeable` view, a partial index, APR keys
  `alpha.quant.price_sanity.magnitude_threshold` (default `10.0`),
  `alpha.quant.price_sanity.neighbor_agreement_threshold` (default `2.0`),
  `infra.bar_auditor.price_sanity_batch_size` (default `500`) — all consumed by later tasks.

- [ ] **Step 1: Write the migration**

```sql
-- Migration 242: price_sanity_status bar-ingestion guard (todo 149)
--
-- Corrupt IBKR prints (e.g. open=1000 on a ~$25 ETF) flow completely unguarded through
-- market_data_ohlcv into every consumer that reads OHLCV directly (feature computation,
-- regime models) -- todo 148's return_{scale}_suspect guard only protects forward_returns,
-- a derived table computed from open alone, and does nothing for a corrupted high/low/close
-- that doesn't happen to distort the open-based return. This migration adds the bar-level
-- signal so protection is inherited by every consumer for free, mirroring how
-- market_data_ohlcv_tradeable's existing volume > 0 filter already protects against
-- synthetic calendar-fill bars.
--
-- price_sanity_status is a nullable STATUS column, not a boolean -- classify_candidate_bar()
-- (todo 151) returns 4 states (PLAUSIBLE/AMBIGUOUS/CONFIRMED_CORRUPT/MARKET_EVENT), and
-- AMBIGUOUS is explicitly a "cannot conclude" state that must never be silently collapsed
-- into "checked, fine" (a silent wrong answer) nor left forever NULL (an infinite-rescan
-- bug that would defeat the NULL-as-watermark design below). NULL = not yet audited; this
-- IS the watermark -- no separate table needed, and unlike a MAX(bar_ts)-based watermark
-- (which silently failed to backfill a historical gap earlier in this same project, costing
-- an unplanned 17-minute full recompute to fix), a NULL doesn't care whether it arrived via
-- live trickle or a bulk historical backfill landing anywhere in history. Values:
-- 'plausible' | 'confirmed_corrupt' | 'market_event' | 'ambiguous'.
--
-- The view predicate uses IS DISTINCT FROM, not a bare inequality: NOT is_suspect-style
-- boolean logic (or a plain != 'confirmed_corrupt') evaluates to NULL against a NULL column,
-- which is falsy in a WHERE clause -- that would make every newly-inserted LIVE bar
-- invisible to every downstream consumer until the audit gets to it (5-10 min later),
-- injecting unintended read-latency into the real-time pipeline. IS DISTINCT FROM passes
-- NULL, 'plausible', 'market_event', and 'ambiguous' through unchanged; only a confirmed
-- verdict excludes. Never drop data on an unaudited or inconclusive signal.
--
-- The partial index only covers unaudited rows (WHERE price_sanity_status IS NULL) --
-- it self-shrinks as the backlog clears (rows exit the NULL set permanently once classified),
-- bounding the audit task's candidate-discovery query cost independent of total table size
-- (market_data_ohlcv is a 215M+ row hypertable; an unindexed full-table NULL scan every
-- 5-minute audit tick would be a real, unbounded cost).
--
-- Reconciliation: todo 151's --apply step (run earlier the same day this migration was
-- written) corrected 18 confirmed-corrupt rows by zeroing volume, reusing the view's
-- PRE-EXISTING volume > 0 filter (a pragmatic "no new schema" choice at the time, before
-- this column existed). Shipping price_sanity_status as a SECOND, independent signal for
-- the same job without reconciling those 18 rows would permanently blind this migration's
-- own audit task to them -- its candidate-discovery query only sees rows the tradeable view
-- includes (volume > 0), and those 18 rows are now excluded from that view by volume=0, so
-- their price_sanity_status would sit NULL forever. This UPDATE closes that gap once.
-- Going forward (see todo-149 plan Task 4), the correction tool stamps price_sanity_status
-- directly and no longer touches volume, so this reconciliation is a one-time event, not a
-- pattern.
--
-- APR thresholds carry forward classify_candidate_bar()'s existing, already-tuned CLI
-- defaults (10.0x magnitude, 2.0x neighbor-agreement) verbatim -- these were validated
-- against the Flash Crash cluster and real corrupt prints earlier the same day; this
-- migration only changes WHERE the default lives (APR, not a hardcoded Python constant),
-- not the value, since classify_candidate_bar() is now embedded in an always-on daemon
-- (CLAUDE.md's migrate-as-you-go rule). infra.bar_auditor.price_sanity_batch_size is new --
-- [initial_estimate] 500, small enough to keep one audit tick's classification + writeback
-- well under BarAuditor's 300s cycle interval even on a cold-start backlog, generous enough
-- that a normal live trickle (a handful of new bars per symbol per cycle) clears in one tick.

BEGIN;

-- Invalidation contract (documented, not enforced by a trigger in this migration --
-- no code path today mutates OHLC on an already-audited row, so this is a stated rule
-- for future correction tools, not an active bug): any process that mutates a bar's
-- open/high/low/close after price_sanity_status has been set MUST reset that column
-- to NULL in the same transaction, so the row re-enters the audit queue rather than
-- carrying a stale verdict computed against since-changed values.
ALTER TABLE market_data_ohlcv
    ADD COLUMN IF NOT EXISTS price_sanity_status text;

CREATE INDEX IF NOT EXISTS idx_market_data_ohlcv_price_sanity_unaudited
    ON market_data_ohlcv (symbol, timeframe, timestamp)
    WHERE price_sanity_status IS NULL;

CREATE OR REPLACE VIEW market_data_ohlcv_tradeable AS
SELECT *
FROM market_data_ohlcv
WHERE volume > 0
  AND price_sanity_status IS DISTINCT FROM 'confirmed_corrupt';

-- Drives from integrity_monitor (18 rows for this monitor_type), NOT from
-- market_data_ohlcv WHERE volume=0 -- volume=0 also matches every synthetic-fill/
-- flat-carry-forward placeholder bar in the ENTIRE table (~82% of intraday rows,
-- tens of millions of rows), and a per-row correlated EXISTS subquery driven from
-- that population is a catastrophic, unbounded full-table operation. Extracting
-- symbol/tf/ts from integrity_monitor's own subject string and joining directly on
-- market_data_ohlcv's primary-key columns bounds this to exactly 18 index lookups.
UPDATE market_data_ohlcv m
SET price_sanity_status = 'confirmed_corrupt'
FROM (
    SELECT
        substring(subject FROM 'symbol=([^|]+)') AS symbol,
        substring(subject FROM 'tf=([^|]+)') AS tf,
        substring(subject FROM 'ts=(.+)$')::timestamptz AS ts
    FROM integrity_monitor
    WHERE monitor_type = 'price_sanity_ohlcv_correction'
) corrected
WHERE m.symbol = corrected.symbol
  AND m.timeframe = corrected.tf
  AND m.timestamp = corrected.ts;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.quant.price_sanity.magnitude_threshold',
    'float',
    '10.0',
    2.0, 100.0,
    '[initial_estimate] Order-of-magnitude ratio vs. neighbor reference price to flag an '
    'OHLC field implausible (todo 149/151). Carries forward classify_candidate_bar()''s '
    'existing CLI default verbatim, validated against real corrupt prints and the Flash '
    'Crash cluster. Used by src/intelligence/statistics/price_sanity.py '
    'classify_candidate_bar() -- both the BarAuditor live audit task and the ad hoc '
    '(CLI-overridable) ops_known_corrupt_print_cleanup.py script. Not an ML learning target.'
),
(
    'alpha.quant.price_sanity.neighbor_agreement_threshold',
    'float',
    '2.0',
    1.1, 10.0,
    '[initial_estimate] Max ratio between prev_close and next_open for the two neighbor '
    'bars to be trusted as a reference (todo 149/151). Carries forward '
    'classify_candidate_bar()''s existing CLI default verbatim. Not an ML learning target.'
),
(
    'infra.bar_auditor.price_sanity_batch_size',
    'int',
    '500',
    50, 5000,
    '[initial_estimate] Max unaudited bars BarAuditor''s price-sanity task classifies per '
    'audit tick (todo 149). Bounds per-cycle cost independent of total backlog size -- a '
    'large backlog (e.g. after a bulk historical backfill) drains over multiple ticks '
    'rather than blocking one cycle. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.quant.price_sanity.magnitude_threshold', '10.0', 1),
    ('alpha.quant.price_sanity.neighbor_agreement_threshold', '2.0', 1),
    ('infra.bar_auditor.price_sanity_batch_size', '500', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.quant.price_sanity.magnitude_threshold', 1, '10.0', 'migration_242',
     'Seed bar-ingestion price-sanity magnitude threshold, todo 149 [initial_estimate]'),
    (NOW(), 'alpha.quant.price_sanity.neighbor_agreement_threshold', 1, '2.0', 'migration_242',
     'Seed bar-ingestion price-sanity neighbor-agreement threshold, todo 149 [initial_estimate]'),
    (NOW(), 'infra.bar_auditor.price_sanity_batch_size', 1, '500', 'migration_242',
     'Seed BarAuditor price-sanity audit batch size, todo 149 [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
```

- [ ] **Step 2: Apply the migration**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/242_price_sanity_status_bar_ingestion.sql`
Expected: `BEGIN` / `ALTER TABLE` / `CREATE INDEX` / `CREATE VIEW` / `UPDATE 18` (the
reconciliation — verify this count matches; if it's not 18, stop and investigate before
continuing, don't assume) / 3× `INSERT 0 1` / `COMMIT`.

- [ ] **Step 3: Verify the reconciliation and view predicate**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT count(*) FROM market_data_ohlcv WHERE price_sanity_status = 'confirmed_corrupt';"`
Expected: `18`.

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT count(*) FROM market_data_ohlcv_tradeable WHERE price_sanity_status = 'confirmed_corrupt';"`
Expected: `0` (the view correctly excludes them).

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT count(*) FROM market_data_ohlcv_tradeable WHERE price_sanity_status IS NULL;"`
Expected: a large nonzero number (every not-yet-audited, real-volume bar still passes through
— confirms the NULL-safe predicate works as designed).

- [ ] **Step 4: Verify the APR keys and index**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT config_key, config_value FROM config_state WHERE config_key LIKE 'alpha.quant.price_sanity.%' OR config_key = 'infra.bar_auditor.price_sanity_batch_size' ORDER BY config_key;"`
Expected: 3 rows, values `10.0`, `2.0`, `500`.

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d idx_market_data_ohlcv_price_sanity_unaudited"`
Expected: index exists, partial (`WHERE price_sanity_status IS NULL`).

- [ ] **Step 5: Commit**

```bash
git add production/migrations/242_price_sanity_status_bar_ingestion.sql
git commit -m "feat(todo-149): price_sanity_status schema, view predicate, APR keys"
```

---

### Task 2: Promote classification logic to a shared module

**Files:**
- Create: `src/intelligence/statistics/price_sanity.py`
- Create: `tests/unit/intelligence/test_price_sanity.py`
- Modify: `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py`
- Modify: `tests/unit/test_known_corrupt_print_cleanup.py`

**Interfaces:**
- Produces: `CandidateVerdict` (dataclass), `classify_candidate_bar(...)`,
  `apply_cross_symbol_downgrade(...)`, `build_subject_key(...)` — all moved verbatim (same
  signatures, same docstrings, same logic) from `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py`
  into `src/intelligence/statistics/price_sanity.py`.

- [ ] **Step 1: Read the current source to move verbatim**

The four items being moved (`CandidateVerdict`, `classify_candidate_bar`,
`apply_cross_symbol_downgrade`, `build_subject_key`) currently live in
`scripts/ops/corpus/ops_known_corrupt_print_cleanup.py` at lines 94-208 (the block between
the `# Pure classification logic` comment and the `# SQL builders` comment). Copy this block
verbatim — do not paraphrase, do not "improve" anything as part of the move, this is a pure
relocation gated on the existing test suite passing unchanged afterward.

- [ ] **Step 2: Create the shared module**

Create `src/intelligence/statistics/price_sanity.py`:

```python
"""Bar-level price-sanity classification and cross-symbol corroboration.

Shared by services/bar_auditor.py's live audit task (todo 149) and
scripts/ops/corpus/ops_known_corrupt_print_cleanup.py's ad hoc cleanup tool (todo 151).
Both consumers classify OHLC bars against their immediate neighbors to distinguish
genuine corrupt prints (an isolated spike-and-immediate-revert with no economic basis)
from real market-wide events (a Flash-Crash-shaped move corroborated across multiple
symbols) -- see docs/superpowers/specs/2026-07-20-bar-ingestion-price-sanity-guard-design.md
for the full design rationale.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Any, Literal

import asyncpg

_MAGNITUDE_THRESHOLD_DEFAULT = 10.0
_NEIGHBOR_AGREEMENT_THRESHOLD_DEFAULT = 2.0


@dataclass(frozen=True)
class CandidateVerdict:
    verdict: str  # "CONFIRMED_CORRUPT" | "AMBIGUOUS" | "PLAUSIBLE" | "MARKET_EVENT"
    implausible_fields: tuple[str, ...]
    max_ratio: float
    neighbor_ratio: float | None
    reason: str


def classify_candidate_bar(
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    prev_close: float | None,
    next_open: float | None,
    magnitude_threshold: float = _MAGNITUDE_THRESHOLD_DEFAULT,
    neighbor_agreement_threshold: float = _NEIGHBOR_AGREEMENT_THRESHOLD_DEFAULT,
) -> CandidateVerdict:
    """Classify a candidate bar against its immediate neighbors (LAG close / LEAD open).

    Reference price is the average of the previous bar's close and the next bar's
    open. Each of this bar's open/high/low/close is checked independently (a corrupt
    print can taint only SOME OHLC fields -- e.g. the UUP row has a corrupted
    open/high but a plausible low/close) against that reference via a symmetric
    magnitude factor (max(ratio, 1/ratio), so both a 1000x-too-high and a 1000x-too-
    low value are caught the same way).

    CONFIRMED_CORRUPT requires BOTH: at least one field off by
    >= magnitude_threshold, AND the two neighbors agreeing closely with each other
    (<= neighbor_agreement_threshold apart) -- confirming they are a trustworthy
    reference for an isolated spike-and-immediate-revert. If the neighbors
    themselves disagree beyond that threshold, the reference is untrustworthy and
    the verdict is AMBIGUOUS instead of forcing a call. Missing neighbor data (series
    boundary) is always AMBIGUOUS -- there is no reference to check against at all.
    """
    if prev_close is None or next_open is None or prev_close <= 0 or next_open <= 0:
        return CandidateVerdict(
            verdict="AMBIGUOUS",
            implausible_fields=(),
            max_ratio=float("nan"),
            neighbor_ratio=None,
            reason="insufficient_neighbor_data",
        )

    reference_price = (prev_close + next_open) / 2.0
    fields = {"open": open_, "high": high, "low": low, "close": close}
    magnitude_factors: dict[str, float] = {}
    for name, value in fields.items():
        if value is None or value <= 0:
            magnitude_factors[name] = float("inf")
            continue
        ratio = value / reference_price
        magnitude_factors[name] = max(ratio, 1.0 / ratio)

    implausible_fields = tuple(
        name for name, factor in magnitude_factors.items() if factor >= magnitude_threshold
    )
    max_ratio = max(magnitude_factors.values())
    neighbor_ratio = max(prev_close, next_open) / min(prev_close, next_open)

    if not implausible_fields:
        return CandidateVerdict(
            verdict="PLAUSIBLE",
            implausible_fields=(),
            max_ratio=max_ratio,
            neighbor_ratio=neighbor_ratio,
            reason="within_magnitude_threshold",
        )
    if neighbor_ratio <= neighbor_agreement_threshold:
        return CandidateVerdict(
            verdict="CONFIRMED_CORRUPT",
            implausible_fields=implausible_fields,
            max_ratio=max_ratio,
            neighbor_ratio=neighbor_ratio,
            reason="isolated_spike_neighbors_agree",
        )
    return CandidateVerdict(
        verdict="AMBIGUOUS",
        implausible_fields=implausible_fields,
        max_ratio=max_ratio,
        neighbor_ratio=neighbor_ratio,
        reason="implausible_but_neighbors_disagree",
    )


def apply_cross_symbol_downgrade(
    verdict: CandidateVerdict, n_corroborating_symbols: int, min_symbols: int
) -> CandidateVerdict:
    """Downgrade CONFIRMED_CORRUPT -> MARKET_EVENT when the subject symbol plus
    n_corroborating_symbols OTHER symbols (total >= min_symbols) show a similarly
    implausible move at/near the same (tf, timestamp) -- todo 152's cross-symbol
    corroboration signal applied to a single-symbol classification.
    classify_candidate_bar's single-symbol neighbor-agreement check cannot
    distinguish a genuine V-shaped flash-crash recovery from an isolated bad print
    (both show "isolated spike, neighbors agree"); this is the missing signal. Only
    CONFIRMED_CORRUPT is checked -- AMBIGUOUS/PLAUSIBLE verdicts are unaffected by
    corroboration.
    """
    if verdict.verdict != "CONFIRMED_CORRUPT":
        return verdict
    total_symbols = n_corroborating_symbols + 1
    if total_symbols < min_symbols:
        return verdict
    return replace(
        verdict,
        verdict="MARKET_EVENT",
        reason=f"cross_symbol_corroborated_n={total_symbols}",
    )


def build_subject_key(symbol: str, tf: str, timestamp_iso: str) -> str:
    """integrity_monitor.subject shape for price-sanity monitor types (todo 149/151)."""
    return f"symbol={symbol}|tf={tf}|ts={timestamp_iso}"
```

- [ ] **Step 3: Re-point `ops_known_corrupt_print_cleanup.py`'s imports**

In `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py`, delete the moved block (the
`CandidateVerdict` dataclass, `classify_candidate_bar`, `apply_cross_symbol_downgrade`,
`build_subject_key` — the same lines 94-208 identified in Step 1), and delete the now-unused
`_MAGNITUDE_THRESHOLD_DEFAULT`/`_NEIGHBOR_AGREEMENT_THRESHOLD_DEFAULT` module constants
(lines 77-78 — these move into the shared module's own defaults, per Step 2 above). Add the
import:

```python
from src.intelligence.statistics.price_sanity import (
    CandidateVerdict,
    apply_cross_symbol_downgrade,
    build_subject_key,
    classify_candidate_bar,
)
```

The script's own `--magnitude-threshold`/`--neighbor-agreement-threshold` CLI flags stay —
they remain valid ad hoc human-operator overrides — but their `default=` values now come from
APR (Task 1's seeded keys) rather than the deleted module constants. Update `_parse_args()`:
the `argparse.ArgumentParser` doesn't have APR access at parse time (APR requires an open DB
connection), so leave the CLI flags' hardcoded fallback defaults as `10.0`/`2.0` matching the
APR seed exactly (documented as "matches migration 242's seed, keep in sync" in a comment) —
this mirrors the existing fallback-constant pattern used throughout this codebase for
APR-backed values (e.g. `_MAX_ABS_RETURN_FALLBACKS` in `forward_return_writer.py`). In `_run()`,
where `min_corroborating_symbols` is already loaded via `_cfg(apr, ...)`, add loading the two
new keys the same way and use them as the argparse defaults' override when the CLI flag wasn't
explicitly passed (`args.magnitude_threshold` stays as the CLI value if given; only fall back
to the freshly-loaded APR value when `args.magnitude_threshold` still equals its hardcoded
argparse default — actually, simplest and least error-prone: change the CLI flags'
`default=None`, and after `_cfg(apr, ...)` loads, do
`magnitude_threshold = args.magnitude_threshold if args.magnitude_threshold is not None else float(_cfg(apr, "alpha.quant.price_sanity.magnitude_threshold", 10.0))`
— this is the standard operator-preference-overrides-APR-default lifecycle pattern).

- [ ] **Step 4: Update the test file's imports**

In `tests/unit/test_known_corrupt_print_cleanup.py`, change:

```python
from scripts.ops.corpus.ops_known_corrupt_print_cleanup import (
    _AUDIT_INSERT_SQL,
    _CORRECTION_UPDATE_SQL,
    _METRIC_NAME,
    _MONITOR_TYPE,
    CandidateRow,
    CandidateVerdict,
    _apply_correction,
    apply_cross_symbol_downgrade,
    build_subject_key,
    classify_candidate_bar,
    render_dry_run_report,
    render_followup_commands,
)
```

to:

```python
from scripts.ops.corpus.ops_known_corrupt_print_cleanup import (
    _AUDIT_INSERT_SQL,
    _CORRECTION_UPDATE_SQL,
    _METRIC_NAME,
    _MONITOR_TYPE,
    CandidateRow,
    _apply_correction,
    render_dry_run_report,
    render_followup_commands,
)
from src.intelligence.statistics.price_sanity import (
    CandidateVerdict,
    apply_cross_symbol_downgrade,
    build_subject_key,
    classify_candidate_bar,
)
```

- [ ] **Step 5: Create the shared module's own test file**

Create `tests/unit/intelligence/test_price_sanity.py` — copy the existing
`TestClassifyCandidateBar`-equivalent test classes and the `apply_cross_symbol_downgrade`/
`build_subject_key` tests currently in `tests/unit/test_known_corrupt_print_cleanup.py`
verbatim into this new file (same test bodies, same assertions), importing from
`src.intelligence.statistics.price_sanity` instead. This gives the shared module its own
independent test file matching its own module boundary (the file structure principle: one
clear responsibility per file, including its tests) — `tests/unit/test_known_corrupt_print_cleanup.py`
keeps only the tests for what's still actually defined in
`ops_known_corrupt_print_cleanup.py` (the SQL builders, `CandidateRow`, `_apply_correction`,
report rendering).

- [ ] **Step 6: Run both test files**

Run: `.venv/bin/pytest tests/unit/intelligence/test_price_sanity.py tests/unit/test_known_corrupt_print_cleanup.py -v`
Expected: all tests pass — this is the regression gate for the move. If anything fails, the
move introduced a behavior change; fix the move, not the test (the whole point of this task is
zero behavior change).

- [ ] **Step 7: Commit**

```bash
git add src/intelligence/statistics/price_sanity.py tests/unit/intelligence/test_price_sanity.py scripts/ops/corpus/ops_known_corrupt_print_cleanup.py tests/unit/test_known_corrupt_print_cleanup.py
git commit -m "refactor(todo-149): promote price-sanity classification to shared module"
```

---

### Task 3: Batched cross-symbol corroboration primitive

**Files:**
- Modify: `src/intelligence/statistics/price_sanity.py`
- Modify: `tests/unit/intelligence/test_price_sanity.py`

**Interfaces:**
- Consumes: `classify_candidate_bar`, `CandidateVerdict` (Task 2, same file).
- Produces: `count_corroborating_symbols_batch(pool: asyncpg.Pool, candidates: list[tuple[str, str, Any]], match_mode: Literal["exact", "window"], magnitude_threshold: float, neighbor_agreement_threshold: float, window_minutes: int | None = None) -> dict[tuple[str, str, Any], int]`
  — used by Task 5 (`BarAuditor`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/intelligence/test_price_sanity.py`:

```python
import asyncio
from unittest.mock import AsyncMock

import pytest

from src.intelligence.statistics.price_sanity import count_corroborating_symbols_batch


def _mock_pool_with_rows(rows: list[dict]) -> AsyncMock:
    pool = AsyncMock()
    pool.fetch = AsyncMock(return_value=rows)
    return pool


def test_count_corroborating_symbols_batch_window_mode_not_implemented():
    """match_mode is a required, explicit parameter with no default -- 'window' is not
    implemented in this plan (forward_return_writer.py's existing window-mode
    corroboration pass is not refactored onto this primitive here, see the plan's
    Global Constraints). Calling with 'window' must fail loudly, not silently no-op
    or silently fall back to 'exact' -- a silent mode substitution is exactly how
    both prior corroboration bugs happened."""
    pool = _mock_pool_with_rows([])
    with pytest.raises(NotImplementedError, match="window"):
        asyncio.run(
            count_corroborating_symbols_batch(
                pool,
                candidates=[("UUP", "5m", "2007-06-20T19:05:00+00:00")],
                match_mode="window",
                magnitude_threshold=10.0,
                neighbor_agreement_threshold=2.0,
                window_minutes=60,
            )
        )


def test_count_corroborating_symbols_batch_flash_crash_cluster():
    """Reproduces the live 2010-05-06 Flash Crash cluster shape (6 symbols, exact
    shared timestamp for raw bars -- todo 151's own established precedent for why
    raw-bar corroboration uses exact match, unlike forward_returns' derived,
    staggered scales) -- all 6 must corroborate each other, batched in ONE query
    regardless of candidate count."""
    ts = "2010-05-06T18:45:00+00:00"
    crash_symbols = ["CWB", "ITA", "RSP", "VTV", "VUG", "VYM"]
    rows = [
        {
            "symbol": s,
            "tf": "5m",
            "bar_ts": ts,
            "open": 10.0,
            "high": 10.5,
            "low": 0.05,  # implausible low on every symbol -- the crash's shape
            "close": 10.2,
            "prev_close": 10.3,
            "next_open": 10.25,
        }
        for s in crash_symbols
    ]
    pool = _mock_pool_with_rows(rows)
    candidates = [(s, "5m", ts) for s in crash_symbols]

    result = asyncio.run(
        count_corroborating_symbols_batch(
            pool,
            candidates=candidates,
            match_mode="exact",
            magnitude_threshold=10.0,
            neighbor_agreement_threshold=2.0,
        )
    )

    assert pool.fetch.call_count == 1  # one batched query, not one per candidate
    for symbol in crash_symbols:
        # 6 symbols total, each corroborated by the OTHER 5 (excludes itself)
        assert result[(symbol, "5m", ts)] == 5


def test_count_corroborating_symbols_batch_isolated_corruption_excludes_self():
    """A single isolated corrupt print (no other symbol implausible nearby) must
    corroborate to 0, not 1 -- the subject's own row must be excluded from its own
    count."""
    ts = "2007-06-20T19:05:00+00:00"
    rows = [
        {
            "symbol": "UUP",
            "tf": "5m",
            "bar_ts": ts,
            "open": 1000.0,
            "high": 1000.0,
            "low": 1000.0,
            "close": 1000.0,
            "prev_close": 28.97,
            "next_open": 24.08,
        }
    ]
    pool = _mock_pool_with_rows(rows)

    result = asyncio.run(
        count_corroborating_symbols_batch(
            pool,
            candidates=[("UUP", "5m", ts)],
            match_mode="exact",
            magnitude_threshold=10.0,
            neighbor_agreement_threshold=2.0,
        )
    )

    assert result[("UUP", "5m", ts)] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/intelligence/test_price_sanity.py -v -k corroborating_symbols_batch`
Expected: FAIL with `ImportError: cannot import name 'count_corroborating_symbols_batch'`.

- [ ] **Step 3: Implement the primitive**

Add to `src/intelligence/statistics/price_sanity.py` (after `build_subject_key`):

```python
_BATCHED_CANDIDATE_NEIGHBORS_SQL = """
WITH candidate_keys AS (
    SELECT * FROM unnest($1::text[], $2::timestamptz[]) AS t(tf, bar_ts)
)
SELECT
    n.symbol, n.timeframe AS tf, n.timestamp AS bar_ts,
    n.open, n.high, n.low, n.close,
    prev.close AS prev_close,
    next.open AS next_open
FROM market_data_ohlcv_tradeable n
JOIN candidate_keys ck ON ck.tf = n.timeframe AND ck.bar_ts = n.timestamp
LEFT JOIN LATERAL (
    SELECT close FROM market_data_ohlcv_tradeable p
    WHERE p.symbol = n.symbol AND p.timeframe = n.timeframe AND p.timestamp < n.timestamp
    ORDER BY p.timestamp DESC LIMIT 1
) prev ON true
LEFT JOIN LATERAL (
    SELECT open FROM market_data_ohlcv_tradeable nx
    WHERE nx.symbol = n.symbol AND nx.timeframe = n.timeframe AND nx.timestamp > n.timestamp
    ORDER BY nx.timestamp ASC LIMIT 1
) next ON true
"""


async def count_corroborating_symbols_batch(
    pool: asyncpg.Pool,
    candidates: list[tuple[str, str, Any]],
    match_mode: Literal["exact", "window"],
    magnitude_threshold: float,
    neighbor_agreement_threshold: float,
    window_minutes: int | None = None,
) -> dict[tuple[str, str, Any], int]:
    """Batched cross-symbol corroboration (todo 149) -- for each (symbol, tf, bar_ts)
    candidate, count how many OTHER symbols show an implausible bar at/near the same
    (tf, bar_ts), reusing classify_candidate_bar() symmetrically (each neighbor
    classified against its OWN prev/next reference, exactly as the subject was).

    ONE query fetches every symbol's bar (with LAG/LEAD neighbors, via a per-row
    LATERAL nearest-neighbor join rather than a full-partition window function, so
    cost scales with the candidate set's distinct timestamps, not the whole table)
    at every DISTINCT (tf, bar_ts) among the candidates -- classification then
    happens in Python, reusing classify_candidate_bar() exactly rather than
    reimplementing the magnitude check in SQL (a second, divergence-prone
    implementation is exactly the failure mode this project has already paid for
    twice with independent corroboration logic).

    match_mode is required and explicit, never defaulted -- "window" is NOT
    implemented here (forward_return_writer.py's existing, already-proven
    window-mode corroboration pass is not refactored onto this primitive in this
    plan; see the plan's Global Constraints). Only "exact" (raw bars ARE the event
    itself -- todo 151's own established precedent) is implemented and tested here.

    Returns {(symbol, tf, bar_ts): n_corroborating} for every input candidate --
    n_corroborating always excludes the candidate's own symbol.
    """
    if match_mode == "window":
        raise NotImplementedError(
            "window match-mode is not implemented in this primitive -- see "
            "forward_return_writer.py's _build_corroborated_windows_temp_table_sql "
            "for the existing, proven window-mode implementation this would need to "
            "generalize from, and the todo-149 plan's Global Constraints for why this "
            "was deliberately deferred rather than built speculatively."
        )

    distinct_keys = sorted({(tf, bar_ts) for _, tf, bar_ts in candidates})
    tfs = [k[0] for k in distinct_keys]
    bar_tss = [k[1] for k in distinct_keys]

    rows = await pool.fetch(_BATCHED_CANDIDATE_NEIGHBORS_SQL, tfs, bar_tss)

    implausible_symbols_by_key: dict[tuple[str, Any], set[str]] = defaultdict(set)
    for r in rows:
        verdict = classify_candidate_bar(
            open_=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
            prev_close=float(r["prev_close"]) if r["prev_close"] is not None else None,
            next_open=float(r["next_open"]) if r["next_open"] is not None else None,
            magnitude_threshold=magnitude_threshold,
            neighbor_agreement_threshold=neighbor_agreement_threshold,
        )
        if verdict.verdict != "PLAUSIBLE":
            implausible_symbols_by_key[(r["tf"], r["bar_ts"])].add(r["symbol"])

    return {
        (symbol, tf, bar_ts): len(implausible_symbols_by_key[(tf, bar_ts)] - {symbol})
        for symbol, tf, bar_ts in candidates
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/intelligence/test_price_sanity.py -v`
Expected: all pass (existing classification tests + 3 new corroboration tests).

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/statistics/price_sanity.py tests/unit/intelligence/test_price_sanity.py
git commit -m "feat(todo-149): batched cross-symbol corroboration primitive"
```

---

### Task 4: Update `ops_known_corrupt_print_cleanup.py`'s `--apply` to use `price_sanity_status`

**Files:**
- Modify: `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py`
- Modify: `tests/unit/test_known_corrupt_print_cleanup.py`

**Interfaces:**
- Consumes: `build_subject_key` (Task 2).
- Produces: `_CORRECTION_UPDATE_SQL` (changed target), `_apply_correction` (changed behavior).

- [ ] **Step 1: Write the failing test**

In `tests/unit/test_known_corrupt_print_cleanup.py`, find the existing test(s) covering
`_apply_correction`'s SQL execution order (audit fact written before mutation) and
`_CORRECTION_UPDATE_SQL`'s shape. Add:

```python
def test_correction_update_sql_targets_price_sanity_status_not_volume():
    """Todo 149's reconciliation migration unified corrupt-bar marking onto
    price_sanity_status -- this correction tool must not reintroduce a second,
    competing signal (volume=0) for the same job going forward."""
    assert "price_sanity_status" in _CORRECTION_UPDATE_SQL
    assert "= 'confirmed_corrupt'" in _CORRECTION_UPDATE_SQL
    assert "volume" not in _CORRECTION_UPDATE_SQL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_known_corrupt_print_cleanup.py -v -k price_sanity_status_not_volume`
Expected: FAIL — `_CORRECTION_UPDATE_SQL` still targets `volume`.

- [ ] **Step 3: Update the correction SQL and docstrings**

In `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py`, replace:

```python
_CORRECTION_UPDATE_SQL = """
UPDATE market_data_ohlcv
SET volume = 0
WHERE symbol = $1 AND timeframe = $2 AND timestamp = $3
"""
```

with:

```python
_CORRECTION_UPDATE_SQL = """
UPDATE market_data_ohlcv
SET price_sanity_status = 'confirmed_corrupt'
WHERE symbol = $1 AND timeframe = $2 AND timestamp = $3
"""
```

Update the comment immediately above `_CORRECTION_UPDATE_SQL` (previously explaining the
volume=0 reuse-the-existing-view-filter rationale) to:

```python
# Stamps price_sanity_status directly (todo 149) -- price columns are NEVER modified
# (Renaissance retention: never delete the row, never touch price data) and volume is
# no longer touched either as of todo 149's unification: a corrected row now carries
# exactly one signal (price_sanity_status), the same one BarAuditor's live audit task
# writes, so there is one query surface for "which bars are known bad" rather than two
# independent, divergence-prone mechanisms for the same fact.
```

Update `_apply_correction`'s docstring (currently "Write the integrity_monitor audit record
BEFORE mutating, then zero volume") to say "...then mark price_sanity_status" instead of
"zero volume" — same execution order, same audit-before-mutate guarantee, only the mutated
column changed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_known_corrupt_print_cleanup.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/ops/corpus/ops_known_corrupt_print_cleanup.py tests/unit/test_known_corrupt_print_cleanup.py
git commit -m "feat(todo-149): unify correction tool onto price_sanity_status"
```

---

### Task 5: `BarAuditor` — bounded price-sanity audit task

**Files:**
- Modify: `services/bar_auditor.py`
- Modify: `tests/unit/services/test_bar_auditor.py`
- Modify: `tests/unit/test_market_data_ohlcv_boundary.py`

**Interfaces:**
- Consumes: `classify_candidate_bar`, `apply_cross_symbol_downgrade`,
  `count_corroborating_symbols_batch` (Tasks 2-3, `src/intelligence/statistics/price_sanity.py`).
- Produces: `BarAuditor._run_price_sanity_audit()`, wired into `_run_audit()`'s existing cycle;
  a new, small, independent `asyncpg.Pool` (`self._price_sanity_pool`) separate from
  `self._db_pool` (gap-detection's existing pool) — per the design doc, these must not compete
  for the same 3 connections.

**Note before starting:** this project has a CI-enforced allow-list
(`tests/unit/test_market_data_ohlcv_boundary.py`) that fails the build on any new raw
`FROM market_data_ohlcv`/`JOIN market_data_ohlcv` reference in `services/`, `src/`, or `scripts/`
not registered there with a reason. `_PRICE_SANITY_CANDIDATES_SQL` below (Step 3) deliberately
reads the raw table for its `candidates` CTE — this is the Global Constraints' stated exception
(candidate discovery is the watermark itself; it must see rows regardless of the view's own
`volume > 0`/`price_sanity_status` filtering, and relies on the partial index from Task 1 for
deterministic query-plan usage rather than depending on unverified view-inlining behavior for a
query that runs every 5-minute audit cycle). Step 3 includes registering this in the allow-list;
skipping it will pass local pytest but fail CI.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/services/test_bar_auditor.py` (following this file's existing
`AsyncMock`-pool patterns — see `TestDetectGaps` for the exact mock-pool/mock-conn shape to
mirror):

```python
class TestPriceSanityAudit:
    def _make_agent_with_price_sanity_pool(self, candidate_rows, corroboration_result=None):
        agent = BarAuditor.__new__(BarAuditor)
        agent.settings = MagicMock(env_name="development")
        agent.logger = MagicMock()
        agent.logger.info = MagicMock()
        agent.logger.error = MagicMock()

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=candidate_rows)
        mock_conn.execute = AsyncMock()
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        agent._price_sanity_pool = mock_pool
        return agent, mock_conn

    def test_price_sanity_audit_empty_candidates_is_noop(self):
        agent, mock_conn = self._make_agent_with_price_sanity_pool(candidate_rows=[])

        with patch(
            "services.bar_auditor.load_apr_dict_async",
            new=AsyncMock(return_value={}),
        ):
            asyncio.run(agent._run_price_sanity_audit())

        mock_conn.execute.assert_not_called()

    def test_price_sanity_audit_writes_confirmed_corrupt_status(self):
        candidate_rows = [
            {
                "symbol": "UUP",
                "tf": "5m",
                "bar_ts": "2007-06-20T19:05:00+00:00",
                "open": 1000.0,
                "high": 1000.0,
                "low": 1000.0,
                "close": 1000.0,
                "prev_close": 28.97,
                "next_open": 24.08,
            }
        ]
        agent, mock_conn = self._make_agent_with_price_sanity_pool(candidate_rows)

        with (
            patch(
                "services.bar_auditor.load_apr_dict_async",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "services.bar_auditor.count_corroborating_symbols_batch",
                new=AsyncMock(return_value={("UUP", "5m", "2007-06-20T19:05:00+00:00"): 0}),
            ),
        ):
            asyncio.run(agent._run_price_sanity_audit())

        # One UPDATE call writing the classified status back
        assert mock_conn.execute.call_count == 1
        call_args = mock_conn.execute.call_args
        assert "confirmed_corrupt" in str(call_args)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/services/test_bar_auditor.py -v -k PriceSanityAudit`
Expected: FAIL — `_run_price_sanity_audit` doesn't exist yet.

- [ ] **Step 3: Implement the price-sanity audit task**

Add imports to `services/bar_auditor.py` (near the existing imports):

```python
from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async
from src.intelligence.statistics.price_sanity import (
    apply_cross_symbol_downgrade,
    classify_candidate_bar,
    count_corroborating_symbols_batch,
)
```

Add module-level SQL constants (near `_AUDIT_INTERVAL` etc.):

```python
_PRICE_SANITY_CANDIDATES_SQL = """
WITH candidates AS (
    SELECT symbol, timeframe, timestamp
    FROM market_data_ohlcv
    WHERE price_sanity_status IS NULL
      AND volume > 0
    ORDER BY timestamp
    LIMIT $1
)
SELECT
    c.symbol, c.timeframe AS tf, c.timestamp AS bar_ts,
    o.open, o.high, o.low, o.close,
    prev.close AS prev_close,
    next.open AS next_open
FROM candidates c
JOIN market_data_ohlcv o
  ON o.symbol = c.symbol AND o.timeframe = c.timeframe AND o.timestamp = c.timestamp
LEFT JOIN LATERAL (
    SELECT close FROM market_data_ohlcv_tradeable p
    WHERE p.symbol = c.symbol AND p.timeframe = c.timeframe AND p.timestamp < c.timestamp
    ORDER BY p.timestamp DESC LIMIT 1
) prev ON true
LEFT JOIN LATERAL (
    SELECT open FROM market_data_ohlcv_tradeable nx
    WHERE nx.symbol = c.symbol AND nx.timeframe = c.timeframe AND nx.timestamp > c.timestamp
    ORDER BY nx.timestamp ASC LIMIT 1
) next ON true
WHERE next.open IS NOT NULL
"""
# next.open IS NOT NULL: a candidate whose NEXT bar hasn't landed yet can't be
# classified (the strongest signal, spike-and-revert, is causally impossible without
# it) -- it stays NULL and is picked up next cycle once its next bar exists. This is
# the audit-lag mechanism, not a bug: ~1 bar-interval + one audit cycle, matching
# BarAuditor's existing 5-minute cadence.

_PRICE_SANITY_STATUS_UPDATE_SQL = """
UPDATE market_data_ohlcv
SET price_sanity_status = $4
WHERE symbol = $1 AND timeframe = $2 AND timestamp = $3
"""

_VERDICT_TO_STATUS: dict[str, str] = {
    "PLAUSIBLE": "plausible",
    "CONFIRMED_CORRUPT": "confirmed_corrupt",
    "MARKET_EVENT": "market_event",
    "AMBIGUOUS": "ambiguous",
}
```

Add the connection-pool field in `__init__` (alongside `self._db_pool`):

```python
        self._price_sanity_pool: asyncpg.Pool | None = None
```

Add pool creation in `_setup()` (alongside the existing `self._db_pool = await create_db_pool(...)`
line) and teardown in `_teardown()` (alongside `self._db_pool.close()`):

```python
        # Own small pool, separate from gap-detection's self._db_pool (3 connections) --
        # the price-sanity pass has a different, unproven resource shape (a
        # classification-plus-write pass over up to 215M+ rows on first run vs.
        # gap-detection's cheap O(days) bulk query) and must not starve it (todo 149).
        self._price_sanity_pool = await create_db_pool(
            self.settings.database_url, min_size=1, max_size=2
        )
```

```python
        if self._price_sanity_pool is not None:
            await self._price_sanity_pool.close()
```

Add the audit method (near `_run_audit`):

```python
    async def _run_price_sanity_audit(self) -> None:
        """Bar-level price-sanity audit task (todo 149) -- classifies unaudited bars
        (price_sanity_status IS NULL) whose next bar has landed, corroborates
        cross-symbol, and writes the verdict back. Bounded to one APR-governed batch
        per call; a large backlog (e.g. after a bulk historical backfill) drains over
        multiple audit cycles rather than blocking one.

        Isolated from gap-detection: uses self._price_sanity_pool, not self._db_pool.
        A failure here must never crash the gap-detection cycle it runs alongside
        (mirrors _run_audit's own try/except-and-continue contract).
        """
        try:
            async with self._price_sanity_pool.acquire() as conn:
                apr = await load_apr_dict_async(conn)
                batch_size = int(
                    _cfg(apr, "infra.bar_auditor.price_sanity_batch_size", 500)
                )
                magnitude_threshold = float(
                    _cfg(apr, "alpha.quant.price_sanity.magnitude_threshold", 10.0)
                )
                neighbor_agreement_threshold = float(
                    _cfg(apr, "alpha.quant.price_sanity.neighbor_agreement_threshold", 2.0)
                )
                min_corroborating_symbols = int(
                    _cfg(apr, "alpha.quant.cross_symbol_corroboration.min_symbols", 4)
                )

                candidates = await conn.fetch(_PRICE_SANITY_CANDIDATES_SQL, batch_size)
                if not candidates:
                    return

                verdicts: dict[tuple[str, str, Any], CandidateVerdict] = {}
                for row in candidates:
                    key = (row["symbol"], row["tf"], row["bar_ts"])
                    verdicts[key] = classify_candidate_bar(
                        open_=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        prev_close=float(row["prev_close"]) if row["prev_close"] is not None else None,
                        next_open=float(row["next_open"]) if row["next_open"] is not None else None,
                        magnitude_threshold=magnitude_threshold,
                        neighbor_agreement_threshold=neighbor_agreement_threshold,
                    )

                corroboration_candidates = [
                    key for key, v in verdicts.items() if v.verdict == "CONFIRMED_CORRUPT"
                ]
                if corroboration_candidates:
                    n_corroborating = await count_corroborating_symbols_batch(
                        self._price_sanity_pool,
                        candidates=corroboration_candidates,
                        match_mode="exact",
                        magnitude_threshold=magnitude_threshold,
                        neighbor_agreement_threshold=neighbor_agreement_threshold,
                    )
                    for key in corroboration_candidates:
                        verdicts[key] = apply_cross_symbol_downgrade(
                            verdicts[key],
                            n_corroborating_symbols=n_corroborating[key],
                            min_symbols=min_corroborating_symbols,
                        )

                status_counts: dict[str, int] = {}
                async with conn.transaction():
                    for (symbol, tf, bar_ts), verdict in verdicts.items():
                        status = _VERDICT_TO_STATUS[verdict.verdict]
                        await conn.execute(
                            _PRICE_SANITY_STATUS_UPDATE_SQL, symbol, tf, bar_ts, status
                        )
                        status_counts[status] = status_counts.get(status, 0) + 1

                self.logger.info(
                    "bar_auditor.price_sanity_audit_complete",
                    n_classified=len(verdicts),
                    status_counts=status_counts,
                )
        except Exception as error:
            self.logger.error(
                "bar_auditor.price_sanity_audit_error",
                error=str(error),
            )
            # Do not re-raise -- must not crash the gap-detection cycle running alongside
```

`services/bar_auditor.py` already has `from typing import NamedTuple` — change this line to
`from typing import Any, NamedTuple` (do not add a second, separate `from typing import Any`
line) so `Any` is available for the new method's type annotation, alongside the
`CandidateVerdict` import already listed above.

Wire into `_run_audit()` — add the call after the existing gap-detection logic, inside the
same `try` block so failures are still isolated per the method's own contract, but the
price-sanity task has its OWN inner try/except (above) so a price-sanity failure never
prevents gap-detection's own `_AUDITS_RUN.add(1, ...)`/logging from completing:

```python
            _AUDITS_RUN.add(1, self._agent_attrs)
            self.logger.info(
                "bar_auditor.audit_complete",
                gap_requests_published=len(gap_requests),
            )

            await self._run_price_sanity_audit()

        except Exception as error:
```

- [ ] **Step 4: Register the raw-table allow-list entry**

In `tests/unit/test_market_data_ohlcv_boundary.py`, add an entry to `_ALLOW_LIST`:

```python
    "services/bar_auditor.py": (
        "PERMANENT (todo 149): _PRICE_SANITY_CANDIDATES_SQL's `candidates` CTE reads the "
        "raw table deliberately -- this query IS the price-sanity audit watermark "
        "(`price_sanity_status IS NULL`), gated by a dedicated partial index "
        "(idx_market_data_ohlcv_price_sanity_unaudited, migration 242) for deterministic "
        "query-plan usage on a query that runs every 5-minute audit cycle, rather than "
        "relying on the tradeable view's inlining behavior for a hot path. Its LATERAL "
        "prev/next neighbor joins DO read market_data_ohlcv_tradeable, not the raw table."
    ),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/services/test_bar_auditor.py tests/unit/test_market_data_ohlcv_boundary.py -v`
Expected: all pass (existing gap-detection tests + 2 new price-sanity tests + the boundary
guard now passing with the new allow-list entry).

- [ ] **Step 6: Run the full test suite**

Run: `.venv/bin/pytest tests/unit/ -q`
Expected: all pass, same pre-existing skip count as before this plan started.

- [ ] **Step 7: Commit**

```bash
git add services/bar_auditor.py tests/unit/services/test_bar_auditor.py tests/unit/test_market_data_ohlcv_boundary.py
git commit -m "feat(todo-149): BarAuditor price-sanity audit task"
```

---

### Task 6: Live pilot — single-symbol, single-chunk timed trial

**Files:** none (operational verification step, per the design doc's mandatory-pilot-before-
full-rollout requirement — `market_data_ohlcv` is a 215M+-row, mostly-compressed hypertable;
this has never run against real data before this step)

- [ ] **Step 1: Confirm current backlog shape for one symbol**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT count(*) FROM market_data_ohlcv WHERE symbol = 'SPY' AND price_sanity_status IS NULL;"`
Expected: a large number (SPY's full history, all still unaudited).

- [ ] **Step 2: Manually invoke the price-sanity audit for a bounded trial**

Since `_run_price_sanity_audit` reads its own APR batch size (500 by default), the first
invocation naturally processes only one bounded batch — this IS the pilot, no special
"single-symbol mode" flag needed. Start `BarAuditor` (or invoke `_run_price_sanity_audit`
directly via a short Python script using the service's existing `_setup()`/`_teardown()`) and
time one cycle:

```bash
time .venv/bin/python -c "
import asyncio
from services.bar_auditor import BarAuditor

async def main():
    agent = BarAuditor()
    await agent._setup()
    try:
        await agent._run_price_sanity_audit()
    finally:
        await agent._teardown()

asyncio.run(main())
"
```

Expected: completes without error; report the actual wall-clock time (this is the empirical
per-500-row-batch cost against the real, mostly-compressed hypertable — the number this
design's mandatory pilot exists to produce before trusting the shape of a full-corpus rollout).

- [ ] **Step 3: Verify the results**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT price_sanity_status, count(*) FROM market_data_ohlcv WHERE price_sanity_status IS NOT NULL AND price_sanity_status != 'confirmed_corrupt' GROUP BY price_sanity_status;"`
Expected: nonzero rows now classified (the 18 reconciled rows from Task 1 are excluded by this
query's `!= 'confirmed_corrupt'`; this confirms the NEW batch actually ran and wrote real
verdicts, not just re-confirming Task 1's reconciliation).

- [ ] **Step 4: Report and decide on rollout pacing**

Based on the measured per-batch time from Step 2, report: at the current batch size (500) and
measured per-batch latency, how many audit cycles (at 300s/cycle) would it take to clear
`market_data_ohlcv`'s full ~215M-row backlog, and whether `infra.bar_auditor.price_sanity_batch_size`
should be tuned up/down before `BarAuditor` runs unattended in production. This is a judgment
call for the project owner to make from the empirical number, not something to decide inside
this plan — present the number, do not silently pick a new batch size and change the APR
default without that review.
