# Phase 190: Provider history plane unification - Pattern Map

**Mapped:** 2026-10-09
**Files analyzed:** 13 (4 new, 9 modified)
**Analogs found:** 13 / 13 (10 exact self-analogs - this phase generalizes code that exists and works; 2 role-match for the new tests; 1 partial)

The dominant fact for the planner: this phase is a refactor of proven machinery, not a greenfield build. `IbkrHistoryFetcher`, `_fetch_queue.py`, `_fetcher_lock.py`, `ohlcv_coverage_writer.py` and migration 432/354/355 are the analogs for nearly everything. The genuinely new code is the `HistoryProvider` protocol surface, the leaf conformance test, and the provider-import boundary test.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/providers/base.py` (modify: add batch history protocol + verdict object) | protocol / model | request-response (batch) | itself: `DataProvider` :50-109, `EmptyHistory` :175-191, `RequestRecord` :194-223 | exact |
| `src/providers/ibkr.py` (modify: implement history surface) | provider leaf | request-response (batch) | itself (role unchanged); leaf-facing callers in `_history_fetch_item.py` | exact |
| `scripts/infrastructure/backfill/ohlcv_history_fetcher.py` (new, rename+generalize) | service (BaseBatch oneshot) | batch / queue-driven | `ibkr_history_fetcher.py` | exact |
| `scripts/infrastructure/backfill/_fetch_queue.py` (modify: provider dimension) | service (pure ranking + reads) | batch | itself | exact |
| `scripts/infrastructure/backfill/_fetcher_lock.py` (modify or keep name) | utility (advisory lock) | request-response | itself | exact |
| `scripts/infrastructure/backfill/_history_fetch_item.py` (modify: leaf-facing seam) | service (item mechanics) | batch / streaming-paged | itself: `FetchContext` :193-236, `fetch_item_with_retries` :772-784 | exact |
| `scripts/infrastructure/backfill/_history_fetch.py` (modify: overlays to leaf-owned) | utility (APR overlays, helpers) | batch | itself: `_load_ibkr_*_config` :421-585 | exact |
| `services/ohlcv_coverage_writer.py` (modify: provider labeling, per-provider rebuild inputs) | service (single-writer persistence) | CRUD (upsert in-transaction) | itself | exact |
| `production/migrations/<n>_*.sql` (new family) | migration | batch (DDL + backfill) | `432_ohlcv_coverage.sql`, `354_ohlcv_empty_history.sql`, `355_ohlcv_provider_head.sql` | exact |
| `tests/unit/providers/test_history_conformance.py` (new) | test (protocol conformance) | request-response | `tests/unit/scripts/test_fetch_queue.py` fake style; no direct protocol-conformance analog exists | role-match |
| `tests/unit/...` boundary test (new, protocol-not-leaf import fence) | test (grep allow-list guard) | batch | `tests/unit/test_market_data_ohlcv_boundary.py` | role-match (same pattern, new target) |
| migration contract tests (new, one per migration) | test (source-level contract) | batch | `tests/unit/test_ohlcv_coverage_migration_contract.py` | role-match (same pattern) |
| `production/systemd/indicagent-ohlcv-history-fetcher.{service,timer}` + `services/service_auditor.py` edits | config / registry | event-driven (timer) | `indicagent-ibkr-history-fetcher.{service,timer}`, `service_auditor.py:99-101,168-173` | exact |

## Pattern Assignments

### `src/providers/base.py` (protocol, batch request-response)

**Analog:** itself - the sibling-protocol precedent already in the file. Note there are already TWO protocols side by side (`DataProvider` streaming :50-109 and `DataProviderAdapter` :112-165); a third, `HistoryProvider`, is the established shape here, not a novelty.

**Protocol declaration pattern** (lines 50-64):
```python
@runtime_checkable
class DataProvider(Protocol):
    """Protocol that every data provider must implement.

    Adding a new provider:
    1. Create src/providers/<name>.py
    2. Implement all methods below
    3. Pass instance to the daemon — nothing else changes.
    """

    name: str  # "ibkr", "alpaca", "tradestation"
```

**The too-narrow method it supersedes/wraps** (lines 101-109) - the new surface replaces this signature (no adjustment/window/verdict); check streaming-path callers before touching it:
```python
    async def fetch_historical_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[OHLCVBar]:
        """Fetch historical OHLCV bars. timeframe: '1m', '5m', '15m', '1h'."""
        ...
```

**Evidence-carrying verdict object pattern (frozen dataclass)** (lines 175-191) - `EmptyHistory` is the precedent the normalized no-data verdict generalizes; the new verdict type follows exactly this shape (per-vendor evidence fields instead of IBKR-only chunk counts):
```python
@dataclass(frozen=True)
class EmptyHistory:
    """A fetch's backward walk ended in IBKR's definitive "no data" answers.
    ...
    """
    verified_from: datetime
    empty_through: datetime
    n_confirming_chunks: int
    reached_request_start: bool
```

**Request record pattern** (lines 194-223) - `RequestRecord` is the normalized per-request capture; the batch surface's observation/request types should extend this shape with the provider dimension, and its `Literal` outcome vocabulary is the one to keep:
```python
@dataclass(frozen=True)
class RequestRecord:
    request_id: str
    fetch_run_id: str
    symbol: str
    timeframe: str
    route: str
    what_to_show: str
    ...
    outcome: Literal["bars", "no_data", "timeout", "failed"]
```

Ring rule: this file is Ring 1 (`src/providers/`); the new protocol must not import from `services/` or `scripts/`.

---

### `scripts/infrastructure/backfill/ohlcv_history_fetcher.py` (BaseBatch oneshot, queue-driven batch)

**Analog:** `scripts/infrastructure/backfill/ibkr_history_fetcher.py` (the file being renamed/generalized; 1,309 lines).

**Imports pattern** (lines 86-139) - script-path bootstrap then explicit symbol imports; this block is copied nearly verbatim by the rename:
```python
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.infrastructure.backfill._fetch_queue import (...)
from scripts.infrastructure.backfill._fetcher_lock import (
    FETCHER_LOCK_NAME, LOCK_HELD_MESSAGE, FetcherLock,
)
from scripts.infrastructure.backfill._history_fetch_item import (
    FetchContext, ItemOutcome, fetch_item_with_retries,
)
from services.ohlcv_coverage_writer import (
    rebuild_from_stored_state, record_fetch_outcome, refresh_1d_bounds, reset_failures,
)
from services.ohlcv_observation_writer import ObservationSink, new_fetch_run_id
from src.core.agent.base_batch import BaseBatch
from src.providers import IBKRProvider  # <- becomes the protocol / provider registry
```

**Constructor seam pattern** (lines 507-566) - the established extension style; the provider registry/config mapping slots in at `provider_factory`. Copy this docstring's seam inventory discipline ("replace exactly one dependency each"):
```python
class IbkrHistoryFetcher(BaseBatch):
    """...
    Constructor seams exist for tests and replace exactly one dependency each: the provider
    factory (IBKRProvider), the lock name or the whole lock, the item fetch
    (fetch_item_with_retries), ...
    """

    job_name = JOB
    compute_version = "189.1"

    def __init__(self, db_dsn: str, args: argparse.Namespace, *, settings=None,
                 provider_factory: Callable[[], Any] | None = None,
                 lock_name: str = FETCHER_LOCK_NAME, ...):
        super().__init__(db_dsn)
        self._provider_factory = provider_factory or self._default_provider
```

**Provider construction (the IBKR-specific leaf construction to generalize)** (lines 570-573):
```python
    def _default_provider(self) -> Any:
        return IBKRProvider(
            host=self.settings.ib_host, port=self.settings.ib_port, client_id=self.args.client_id
        )
```

**Connect gate + status raising** (lines 819-823) - the "IBKR gateway" semantics move into the leaf; the loop keeps only `provider.connect()` failing:
```python
        provider = self._provider_factory()
        if not await provider.connect():
            raise RuntimeError("IBKR gateway unreachable at startup")
```

**The item loop with per-item budget, visited set and watchdog** (lines 859-900, abridged) - lanes are already priorities inside one loop; the provider dimension threads through `item_lane`, the visited key and the outcome recording:
```python
        deadline = time.monotonic() + budget_min * 60
        visited: set[tuple[str, str]] = set()
        while True:
            if time.monotonic() >= deadline:
                state.budget_exhausted = True
                break
            row = await plan.queue.next(pool, visited)
            ...
            visited.add(key)
            lane, full_scan, overlap_days = item_lane(plan, row, full_scan=self.args.full_scan)
            outcome = await self._fetch_one(plan, ctx, provider, row, ...)
            self._notify()
            if outcome.gateway_lost:
                state.gateway_lost = f"{row.symbol}/{row.timeframe}"
                break
            self._record_outcome(ctx, outcome)
```

**Per-item outcome write under the writer role** (lines 1084-1091) - the fetcher never writes coverage itself; it goes through the writer module under `SET LOCAL ROLE`:
```python
    def _record_outcome(self, ctx: Any, outcome: ItemOutcome) -> None:
        conn = ctx.get_conn()
        with conn.transaction():
            cur = conn.cursor()
            cur.execute(f"SET LOCAL ROLE {_WRITER_ROLE}")
            record_fetch_outcome(
                cur, outcome.symbol, outcome.timeframe, outcome.status, datetime.now(UTC)
            )
```

**Module-global APR overlay loading at run start (the pattern that must become leaf-owned or per-provider-plan-owned)** (lines 1166-1176):
```python
    def _load_provider_overlays(self) -> None:
        settings = self.settings
        _history_fetch._load_ibkr_chunk_days_config(settings)
        _history_fetch._load_ibkr_hist_timeout_config(settings)
        _history_fetch._load_ibkr_retry_config(settings)
        _history_fetch._load_ibkr_venue_fallback_config(settings)
        _history_fetch._load_ibkr_rate_limit_config(settings)
        _history_fetch._load_ohlcv_insert_batch_size_config(settings)
        _history_fetch._load_gap_cluster_max_days_config(settings)
```

**Externally parsed strings - byte-identical or move all consumers in one commit** (lines 817, 727):
```python
        # Exact format the pipeline prints: ops_head_rerun parses it.
        print(f"  fetch_run_id: {fetch_run_id}")
        ...
            logger.info("ibkr_history_fetcher.lock_held", lock=self._lock_name)
```
`LOCK_HELD_MESSAGE` (`_fetcher_lock.py:34`) and the status-file payload (`_write_status`, :1178-1196) are the other two parsed surfaces. `ops_head_rerun.py:73` matches the fetch_run_id regex; `ops_head_rerun.py:316` matches `LOCK_HELD_MESSAGE` exactly; `services/bar_reconciliation_audit.py:736` reads `NIGHTLY_STATUS_FILE` and checks only `status == "success"`.

**Metric + status identity** (lines 143, 1151):
```python
JOB = "ibkr-history-fetcher"
...
    OHLCV_COVERAGE_SLA_BREACHED_SERIES.set(n, {"job": JOB})
```

**Watchdog ping** (lines 497-503):
```python
def _sd_notify_watchdog() -> None:
    if not os.getenv("NOTIFY_SOCKET"):
        return
    import sdnotify
    sdnotify.SystemdNotifier().notify("WATCHDOG=1")
```

**Dry-run TSV columns** (lines 171-188) - add a `provider` column; note consumers of the TSV (`ops_head_rerun`) must be checked in the same task:
```python
_TSV_COLUMNS = (
    "position", "symbol", "timeframe", "excluded", "sla_breach", "tf_class",
    "gap_days", "staleness_days", "earliest_timestamp", "latest_timestamp",
    "last_fetch_status", "consecutive_failures", "last_fetched_at",
    "held_reason", "lane", "due_reason",
)
```

---

### `scripts/infrastructure/backfill/_fetch_queue.py` (pure ranking + ledger reads, batch)

**Analog:** itself. Everything IBKR-specific is already concentrated and enumerable; the provider dimension extends these exact sites.

**IBKR-specific constants and APR keys** (lines 90, 100-104):
```python
PROVIDER = "ibkr"
...
_KEY_REQUEST_TIMEOUT = "infra.ibkr.history_request_timeout"
_KEY_REQUEST_RETRIES = "infra.ibkr.history_request_retries"
_KEY_RATE_LIMIT_WINDOW = "infra.ibkr.rate_limit_window_sec"
_KEY_CONFIRMATION_CHUNKS = "infra.ibkr.no_data_confirmation_chunks"
```

**Frozen config dataclass pattern** (lines 123-133) - the model for the per-provider `ProviderPlan`:
```python
@dataclass(frozen=True)
class QueueConfig:
    max_consecutive_failures: int
    max_staleness_days_before_preempt: int
    priority_tf_order: tuple[str, ...]
    depth_days: Mapping[str, int]
    history_request_timeout_s: float
    history_request_retries: int
    run_budget_minutes: int
    default_scopes: Mapping[str, tuple[str, ...]]
```

**APR load with validation + fallback logging** (lines 182-230, abridged) - the coupling check at :214-219 is an IBKR-limiter invariant that becomes a per-provider check:
```python
    timeout_s = float(get(_KEY_REQUEST_TIMEOUT))
    window_s = float(get(_KEY_RATE_LIMIT_WINDOW))
    if timeout_s <= window_s:
        raise ValueError(
            f"{_KEY_REQUEST_TIMEOUT}={timeout_s} must exceed "
            f"{_KEY_RATE_LIMIT_WINDOW}={window_s}: the stall bound would cancel healthy "
            "items during a rate-limit sleep"
        )
```

**The rank tuple to generalize** (lines 463-472):
```python
    key = (
        row.consecutive_failures > config.max_consecutive_failures,  # per-provider
        row.timeframe != DAILY_TF,                                   # per-provider (IBKR-only 1d)
        not sla_breach,
        tf_class,
        -gap,
        -effective_stale,
        row.symbol,
        row.timeframe,                                               # + provider, or key by (provider, ...)
    )
```

**Per-provider ledger reads (already provider-parameterized in SQL; the Python side hardcodes PROVIDER)** (lines 508-530):
```python
_COVERAGE_SQL = (
    "SELECT symbol, timeframe, earliest_timestamp, latest_timestamp, last_fetch_status, "
    "consecutive_failures, last_fetched_at FROM ohlcv_coverage WHERE symbol = ANY($1::text[])"
)
_HEADS_SQL = (
    "SELECT symbol, head_ts FROM ohlcv_provider_head WHERE provider = $1 "
    "AND symbol = ANY($2::text[]) AND verified_at > NOW() - make_interval(days => $3)"
)
_EMPTY_SQL = (
    "SELECT symbol, timeframe, empty_through FROM ohlcv_empty_history WHERE provider = $1 "
    "AND symbol = ANY($2::text[]) AND verified_at > NOW() - make_interval(days => $3) "
    "AND n_confirming_chunks >= $4"
)
_LATEST_DAILY_ANSWER_SQL = (
    "SELECT symbol, max(answered_at) AS answered_at FROM ohlcv_request "
    "WHERE source = $1 AND timeframe = '1d' AND route = 'SMART' AND what_to_show = 'TRADES' "
    "AND outcome IN ('bars', 'no_data') AND caller NOT LIKE 'test-%' "
    "AND symbol = ANY($2::text[]) GROUP BY symbol"
)
```
The `_LATEST_DAILY_ANSWER_SQL` filter (`route='SMART' AND what_to_show='TRADES'`) and the whole `DailyRule` are per-provider planner data; the Alpaca lane has no 1d items at all.

**Coverage row + floor computation** (lines 136-144, 584-593):
```python
@dataclass(frozen=True)
class CoverageRow:
    symbol: str
    timeframe: str
    earliest_timestamp: datetime | None
    latest_timestamp: datetime | None
    last_fetch_status: str | None
    consecutive_failures: int
    floor_timestamp: datetime | None
    last_fetched_at: datetime | None = None
```
```python
        def floor(symbol: str, timeframe: str) -> datetime | None:
            found = [
                ts
                for ts in (head_by_symbol.get(symbol), empty_by_series.get((symbol, timeframe)))
                if ts is not None
            ]
            return max(found) if found else None
```
Todo 526's surviving edit: `_HEADS_SQL` gains `timeframe` in the select and PK; the `floor()` closure reads the per-(symbol, provider, timeframe) row.

---

### `scripts/infrastructure/backfill/_fetcher_lock.py` (utility, fail-fast singleton)

**Analog:** itself. Decision owed at plan time: keep `FETCHER_LOCK_NAME` stable (recommended - the sha256 key is shared by 6+ manual tools) or rename every consumer in one commit.

**Lock name + key derivation** (lines 31-43):
```python
FETCHER_LOCK_NAME = "ibkr_history_fetcher"
...
def fetcher_lock_key(name: str = FETCHER_LOCK_NAME) -> int:
    """Stable 64-bit signed key: the first 8 bytes of sha256(name), big-endian, signed (the
    ResourceLease derivation). Never Python's hash(), which is salted per process."""
    return int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big", signed=True)
```

**Parsed message** (lines 33-34):
```python
# Exact string: plan 08's ops_head_rerun matches it in subprocess output.
LOCK_HELD_MESSAGE = "ibkr history fetcher lock held by another process; exiting"
```

---

### `scripts/infrastructure/backfill/_history_fetch_item.py` (item mechanics, batch)

**Analog:** itself. IBKR mechanics (`_ensure_qualified` :371, `_head_floor` :386, FX/crypto derive :696/:731, venue fallback, `what_to_show`/`route` on every RequestRecord) stay behind the leaf seam; the loop must not see them.

**Outcome object** (lines 100-127) - gains a provider field in the refactor:
```python
@dataclass(frozen=True)
class ItemOutcome:
    """How one queue item ended. The fetcher writes `status` to ohlcv_coverage through
    record_fetch_outcome unless `gateway_lost` is set (a lost gateway is not charged)."""
    symbol: str
    timeframe: str
    status: str
    n_bars: int = 0
    n_grid_source_rows: int = 0
    attempts: int = 1
    gateway_lost: bool = False
    ...
    def __post_init__(self) -> None:
        if self.status not in FETCH_STATUSES:
            raise ValueError(f"unknown item status {self.status!r}; expected {FETCH_STATUSES}")
```

**Run-scoped context dataclass** (lines 193-236, abridged) - `provider: Any` becomes the protocol-typed leaf (or per-item resolved leaf):
```python
@dataclass
class FetchContext:
    provider: Any
    settings: Any
    connect: Callable[[], Any]
    sink: Any
    fetch_run_id: str
    tf_fetch_config: Mapping[str, tuple[int, bool]]
    end_dt: datetime
    ...
    def get_conn(self) -> Any:
        """A live connection: the pipeline's SELECT 1 probe and reconnect, in one place."""
```

**Retry wrapper with stall bound** (lines 772-799, abridged) - the budget interface the design's "leaf owns its native rate-limit model behind a common budget interface" wraps; `config.history_request_timeout_s`/`history_request_retries` are exactly the per-provider budget fields:
```python
async def fetch_item_with_retries(
    ctx: Any, instrument: Any, row: Any, *,
    full_scan: bool, config: Any,
    reconnect: Callable[[], Awaitable[bool]],
    on_tick: Callable[[], None] | None = None,
    overlap_days: int = 0, refetch: bool = False, waived: bool = False,
) -> ItemOutcome:
```

---

### `scripts/infrastructure/backfill/_history_fetch.py` (APR overlays, batch)

**Analog:** itself, lines 421-585. The module-global overlay pattern (documented in `docs/reference/gotchas.md` as the migrate-as-you-go pattern) must become leaf-owned or per-provider-plan-owned; this is the concrete code to move:
```python
def _load_ibkr_chunk_days_config(settings: Settings) -> None:
    """Overlay APR-configured chunk-size limits (infra.ibkr.chunk_days.*) onto
    ibkr._MAX_CHUNK_DAYS in place (migration 197). ..."""
    try:
        conn = connect_db(settings)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT config_key, config_value FROM config_state "
                    "WHERE config_key LIKE 'infra.ibkr.chunk_days.%'"
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        for key, value in rows:
            tf = key.rsplit(".", 1)[-1]
            if tf in ibkr._MAX_CHUNK_DAYS:
                ibkr._MAX_CHUNK_DAYS[tf] = int(value)
    except Exception as error:
        print(f"  (APR chunk-days lookup failed, using hardcoded defaults: {error})")
```
Note the soft-fallback contract (log and keep module defaults) versus `_fetch_queue.load_lane_config` (:272-291) which raises on missing keys. The refactor should pick one contract per key class deliberately: planner inputs raise (526 floor lookup), leaf-native limits keep module-default fallbacks.

---

### `services/ohlcv_coverage_writer.py` (single-writer persistence, CRUD in-transaction)

**Analog:** itself. Every function takes a cursor whose transaction already ran `SET LOCAL ROLE`; DB-only, no network, no commits of its own. The provider dimension extends these four functions and two SQL constants.

**Role-scoped writer + status vocabulary** (lines 34-44):
```python
FETCH_STATUSES = ("ok", "no_data", "error")
_ERROR_STATUS = "error"
...
DESTINATION_TABLES = {
    DESTINATION_ARCHIVE: "ohlcv_intraday_raw_archive",
    DESTINATION_GRID: "market_data_ohlcv",
}
```

**Upsert with LEAST/GREATEST bounds, on the PK that gains `provider`** (lines 46-58):
```python
_UPSERT_SQL = """
INSERT INTO ohlcv_coverage (
    symbol, timeframe, earliest_timestamp, latest_timestamp, row_count,
    last_fetched_at, last_fetch_status, consecutive_failures
) VALUES (%s, %s, %s, %s, %s, %s, 'ok', 0)
ON CONFLICT (symbol, timeframe) DO UPDATE SET
    earliest_timestamp = LEAST(ohlcv_coverage.earliest_timestamp, EXCLUDED.earliest_timestamp),
    latest_timestamp = GREATEST(ohlcv_coverage.latest_timestamp, EXCLUDED.latest_timestamp),
    row_count = ohlcv_coverage.row_count + EXCLUDED.row_count,
    last_fetched_at = EXCLUDED.last_fetched_at,
    last_fetch_status = 'ok',
    consecutive_failures = 0
"""
```

**Failure counting rule (only 'error' increments)** (lines 60-71, 129-141):
```python
_OUTCOME_SQL = """... ON CONFLICT (symbol, timeframe) DO UPDATE SET
    ...
    consecutive_failures = CASE
        WHEN EXCLUDED.last_fetch_status = 'error' THEN ohlcv_coverage.consecutive_failures + 1
        ELSE 0
    END
"""
...
def record_fetch_outcome(cur, symbol, timeframe, status, fetched_at) -> None:
    if status not in FETCH_STATUSES:
        raise ValueError(f"unknown fetch status {status!r}; expected one of {FETCH_STATUSES}")
    initial_failures = 1 if status == _ERROR_STATUS else 0
```

**The IBKR-specific rebuild filter to generalize into per-provider rebuild inputs** (lines 245-248):
```python
_REQUEST_FILTER = (
    "WHERE route = 'SMART' AND what_to_show = 'TRADES' "
    "AND outcome IN ('bars', 'no_data', 'timeout', 'failed')"
)
```

---

### Migrations (new family; migration, batch DDL)

**Analogs:** `production/migrations/432_ohlcv_coverage.sql`, `354_ohlcv_empty_history.sql`, `355_ohlcv_provider_head.sql`.

**Migration file conventions** (all three exemplify): numbered prefix `<n>_<snake_name>.sql`; long header comment stating design provenance, single-writer module, backfill semantics, and explicitly whether the compressed-hypertable VACUUM rule applies; `BEGIN; ... COMMIT;`; `COMMENT ON TABLE/COLUMN` for every column; plain tables where row counts are small.

**Provider-dimension table shape** (355:24-30 and 354:31-43) - `provider_head` gains `timeframe` in its PK; the provider column + PK pattern to copy:
```sql
CREATE TABLE IF NOT EXISTS ohlcv_provider_head (
    symbol       text        NOT NULL,
    provider     text        NOT NULL,
    head_ts      timestamptz NOT NULL,
    verified_at  timestamptz NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, provider)
);
```
```sql
CREATE TABLE IF NOT EXISTS ohlcv_empty_history (
    ...
    PRIMARY KEY (symbol, timeframe, provider),
    CHECK (empty_from <= verified_from AND verified_from <= empty_through)
);
```

**The coverage PK and CHECK constraints that change** (432:41-58):
```sql
CREATE TABLE IF NOT EXISTS ohlcv_coverage (
    symbol text NOT NULL,
    timeframe text NOT NULL,
    ...
    consecutive_failures integer NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, timeframe),
    CONSTRAINT ohlcv_coverage_status_check
        CHECK (last_fetch_status IS NULL OR last_fetch_status IN ('ok', 'no_data', 'error')),
    ...
);
```

**Grant pattern** (432:88-96) - role-creation guard + SELECT/INSERT/UPDATE only, no DELETE/TRUNCATE:
```sql
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bar_derivation_writer') THEN
        CREATE ROLE bar_derivation_writer NOLOGIN;
    END IF;
END
$$;

GRANT SELECT, INSERT, UPDATE ON ohlcv_coverage TO bar_derivation_writer;
```

**APR seed triple pattern** (432:102-195) - every key appears in `config_schema` + `config_state` + `config_history`, with a provenance tag and "Not an ML learning target" in the description. New `infra.<provider>.*` keys with `[measured]` provenance follow this exactly:
```sql
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.ibkr.history_request_timeout',
    'float',
    '900',
    120, NULL,
    '[initial_estimate] Per-queue-item stall bound in seconds: ... Not an ML learning target.'
), ...
INSERT INTO config_state (config_key, config_value, version) VALUES (...)
INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (NOW(), 'infra.ibkr.history_request_timeout', 1, '900', 'migration_432', '... [initial_estimate]')
```

**Backfill labeling rule for the coverage migration (pitfall 3 guard)** - state in migration comments that pre-existing rows are canonical-tier stored-state rollups, not per-vendor provenance claims (Tradier-era 1d bounds and 449-lane bars ride under the `ibkr` label).

---

### `production/systemd/` units + `services/service_auditor.py` (config / registry, timer-driven)

**Analogs:** `production/systemd/indicagent-ibkr-history-fetcher.service` and `.timer`; `services/service_auditor.py`.

**Unit facts to preserve in any rename** (service file, verbatim structure):
```ini
[Service]
Type=exec
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
ExecStart=/home/bg/dev/indicagent/.venv/bin/python scripts/infrastructure/backfill/ibkr_history_fetcher.py
NotifyAccess=main
WatchdogSec=1200
RuntimeMaxSec=18000
Restart=no
```
```ini
[Timer]
OnBootSec=15min
OnUnitInactiveSec=15min
Unit=indicagent-ibkr-history-fetcher.service
```

**Registry edits** (`service_auditor.py:99-101, 168-173`) - a renamed fetcher updates both the DAG order and the oneshot set; no `alert.lag.*` key exists or is owed (oneshot with `job_completed_total` only):
```python
    "indicagent-ibkr-history-fetcher": 8,  # Type=exec oneshot run; inactive between fires is correct
```
```python
        "indicagent-ibkr-history-fetcher",  # Type=exec run per 15-min timer fire (phase 189); inactive between fires is correct
```

---

### `tests/unit/providers/test_history_conformance.py` (new; protocol conformance)

**Analog:** none exists. Two role-match patterns to copy mechanically:

1. **Fake-leaf parameterization:** `tests/unit/scripts/test_ibkr_history_fetcher.py` builds the fetcher with `provider_factory`/`fetch_fn` seams (constructor above); the conformance suite should define the contract assertions once and parameterize over leaf implementations (fake first, real `IBKRProvider` and the future Alpaca leaf as they land). Asserts: normalized verdict object and evidence fields, observation shape, page boundaries, budget interface.
2. **Fixture parameterization style:** `tests/unit/scripts/test_fetch_queue.py` exercises the pure functions with synthetic `CoverageRow`s - the conformance test's page-boundary/budget cases follow this "pure function in, verdict out" style.

### Provider import-boundary test (new; grep allow-list guard)

**Analog:** `tests/unit/test_market_data_ohlcv_boundary.py` - copy the whole mechanism (lines 20-33, 122-148): a compiled regex over `services/`, `src/`, `scripts/`, a `_ALLOW_LIST: dict[str, str]` where every entry carries a real reason, and the two tests (`assert_no_unlisted_references` + `assert_allow_list_has_no_stale_entries`) from `tests/unit/_source_grep_helpers.py`. New pattern: `(from|import)\s+src\.providers\.(ibkr|alpaca)\b` - allow-list seeded with today's legitimate concrete-leaf importers (the fetcher family: `ibkr_history_fetcher.py`, `_history_fetch.py`, `_history_fetch_item.py`, plus the manual ops tools that keep concrete access), shrinking over time to zero in services/scripts except through the protocol.

### Migration contract tests (new, one per migration)

**Analog:** `tests/unit/test_ohlcv_coverage_migration_contract.py` - source-level, CI-clean (reads the .sql as text, strips line comments so header prose cannot satisfy DDL assertions), asserting: PK shape, all CHECK constraints, the single grant row and its absence of DELETE/TRUNCATE, every APR key in all three config tables with a provenance tag, no DROP, no hypertable. Replicate per migration in the family, with `PRIMARY KEY (symbol, timeframe, provider)`-style assertions for the re-keyed tables.

## Shared Patterns

### APR seeding in a migration (config_schema + config_state + config_history triple)
**Source:** `production/migrations/432_ohlcv_coverage.sql:102-195`
**Apply to:** every new `infra.<provider>.*` key. Description carries a provenance tag (`[measured]` per the design's Enforcement) and ends "Not an ML learning target"; `changed_by` = the migration name; reason restates the value's derivation.
The sibling validation contract test (`test_ohlcv_coverage_migration_contract.py:66-73`) is what CI enforces; copy it.

### Role-scoped single-writer persistence
**Source:** `services/ohlcv_coverage_writer.py:20-22` (docstring contract) and `ibkr_history_fetcher.py:1084-1091` (call site)
**Apply to:** all new/changed ledger writes.
```python
        with conn.transaction():
            cur = conn.cursor()
            cur.execute(f"SET LOCAL ROLE {_WRITER_ROLE}")
            record_fetch_outcome(cur, ...)
```
Any new table in the family gets `GRANT SELECT, INSERT, UPDATE ... TO bar_derivation_writer` only (432:96), and `tests/unit/test_single_writer_registry.py` entries must be updated in the same task (:77 ohlcv_coverage, :105 ohlcv_empty_history, :111 ohlcv_provider_head).

### Constructor seams for tests (one dependency per seam)
**Source:** `ibkr_history_fetcher.py:507-566`
**Apply to:** the generalized fetcher class. The provider registry mapping (name -> leaf factory + ProviderPlan) is a new default behind the existing `provider_factory` seam; no plugin framework.

### Pure planner functions, ledger reads at the edges
**Source:** `_fetch_queue.py` docstring lines 58-59 ("No IBKR access and no writes"), `rank()` :476-480
**Apply to:** every provider-parameterized planner edit. Dry-run/real parity (pitfall 1) holds only if provider data enters all read paths symmetrically; the rank tuple stays pure.

### Advisory-lock singleton discipline
**Source:** `_fetcher_lock.py:31-43, 76-93`
**Apply to:** the fetcher and any manual tool that fetches vendor history. The lock name is sha256-keyed and shared; if renamed, every consumer moves in one commit, else keep it.

### Timestamps and logging
**Sources:** repo CLAUDE.md rules, exemplified in `ibkr_history_fetcher.py:591` (`datetime.now(UTC)`), `:1178-1196` (atomic tmp-then-replace status file write), `logger = structlog.get_logger(__name__)` (:141). Exception variable is always `error` (`except X as error:`). `setup_service_logging` derives `logs/<snake_case_class>.log`, so renaming the class changes the log path; check `production/indicagent-logrotate.conf` in the same task.

## No Analog Found

| File | Role | Data Flow | Reason | Fallback |
|------|------|-----------|--------|----------|
| `tests/unit/providers/test_history_conformance.py` | test | request-response | No protocol-conformance suite exists anywhere in the repo; the two existing protocols (`DataProvider`, `DataProviderAdapter`) are unpinned by tests | Compose the fake-leaf pattern from `test_ibkr_history_fetcher.py` with per-assertion functions; fixture mechanism is planner discretion |
| `src/providers/alpaca.py` | provider leaf | request-response (HTTP-paged) | Does not exist on main; lands via todo 521's lane before this phase's step 3 | `scripts/research/alpaca_depth_scratch_pull.py` (measured: `next_page_token`, `limit=10000`, `feed=sip`, `adjustment=split`, 429 + `retry-after`) and the leaf-contract decisions in CONTEXT.md |

## Metadata

**Analog search scope:** `scripts/infrastructure/backfill/`, `services/`, `src/providers/`, `production/migrations/`, `production/systemd/`, `tests/unit/`
**Files read in full or targeted:** 14 (`src/providers/base.py`, `_fetch_queue.py`, `ibkr_history_fetcher.py`, `_fetcher_lock.py`, `ohlcv_coverage_writer.py`, `_history_fetch.py` :400-599, `_history_fetch_item.py` :95-269 + :772-846, migrations 432/354/355, `test_market_data_ohlcv_boundary.py`, `test_ohlcv_coverage_migration_contract.py`, both systemd units, `service_auditor.py` :90-184)
**Pattern extraction date:** 2026-10-09
