# Phase 186: Old ensemble chain retirement and ic_engine re-scope - Pattern map

**Mapped:** 2026-09-27
**Files analyzed:** 30 new or modified file groups
**Analogs found:** 27 / 30 (3 have no close analog: remapping unpickler, rebuild precondition checker as a whole, per-kernel code key as a registry field)

Scope note: R-01..R-13 in 186-CONTEXT.md override D-xx where they conflict. All line numbers are
at HEAD e7326a42f. Every plan works in a git worktree (R-11); `scripts/research/` is inside the
research runner's first-party provenance scope (`src/intelligence/research/provenance.py:28`,
`_FIRST_PARTY = ("src", "services", "scripts/research")`), so an untracked or dirty file there in
the shared main checkout blocks the research lane's real runs.

## File classification

| New/modified file | Role | Data flow | Closest analog | Match quality |
|---|---|---|---|---|
| `docs/research/summary-cards/*.md` | doc record | static | `.planning/todos/pending/448-*.md` front matter; ledger rows `docs/research/construction-verdict-ledger.md:104-122` | role-match |
| `tests/unit/test_summary_cards.py` | test (CI lint) | file-I/O | `tests/unit/test_todo_priorities_link_integrity.py` | exact |
| `production/migrations/NNN_lineage_batch.sql` | migration (new table) | CRUD | `production/migrations/366_research_run_ledger.sql` | exact |
| `production/migrations/NNN_bulk_load_apr_keys.sql` (and every APR seed in the phase) | migration (APR seed) | config | `production/migrations/375_ibkr_rate_limit_by_timeframe.sql`, `362_compressed_write_session_disk_headroom.sql` | exact |
| `services/_batch_utils.py` (add `bulk_load()`, lineage helpers) | utility | batch / file-I/O (COPY) | same file: `bulk_update_by_key` (93-168), `check_decompress_headroom` (319-354), compress SQL (386-390) | exact |
| `tests/unit/test_bulk_load.py` | test | batch | `tests/unit/test_batch_utils.py` (`TestBulkUpdateByKeyRealClamping`, 1068-1100); `tests/unit/_compressed_hypertable_write_session_fakes.py` | exact |
| `tests/integration/test_bulk_load.py` | test (DB) | batch | `tests/integration/test_research_ledger.py` | exact |
| `src/intelligence/measure/{proposer,term_structure,monitoring}.py` | pure compute | transform | `src/intelligence/statistics/ic_math.py` (441-570); `src/intelligence/research/panel.py` (93-130) | role-match |
| `services/ic_measure.py` (the one writer during the strangler) | batch writer service | batch | `services/dividend_event_writer.py` (BaseBatch, 280-575); `services/feature_lifecycle.py` (550-600) | exact |
| `tests/unit/measure/test_{proposer,term_structure,monitoring}.py` | test | transform | `tests/unit/research/test_families_overnight_intraday.py` | role-match |
| Parity harness (`scripts/research/ic_parity/...` or test-scoped) + `tests/unit/measure/test_parity_harness.py` | script + test | batch / transform | `services/ic_engine.py` `_compute_one_cross_sectional_cell` (3836+), `_subsample_and_rank` (2062); `scripts/ops/corpus/ops_ic_fingerprint_equivalence.py` | role-match |
| `production/migrations/NNN_*_drop.sql` (chain tables, ctx tables, `construction_spreads`, `feature_ic_scores_history`, later `forward_returns`) | migration (drop) | CRUD | `production/migrations/311_retire_feature_registry.sql` | exact |
| `production/migrations/NNN_market_regimes_duplicate_index.sql` (D-36) | migration (index) | DDL | `production/migrations/193_db_hygiene_pass.sql` (1-46) | exact |
| Old-grid delete + D-19 purge on `feature_ic_scores` | migration or ops script | batch delete | `production/migrations/175_cross_sectional_ic_index.sql:9-10`; `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py` (dry-run / `--apply`) | role-match |
| `production/migrations/NNN_feature_vectors_v2.sql` (rebuilt table) | migration (hypertable) | DDL | `production/migrations/300_feature_ic_scores_history_hypertable.sql` (47-73), `295_feature_ic_scores_hypertable.sql` | exact |
| `services/service_auditor.py` (remove entries) | config registry | n/a | itself: `_DAG_ORDER` 80, 108-116; `_AGENT_ID_TO_UNIT` 167; `_ONESHOT_UNITS` 205-214 | exact |
| `services/feature_lifecycle.py` (D-30 shrink) | batch service | batch | itself (BaseBatch shape 550-600, `LifecycleConfig.from_apr` 93-127) | exact |
| `src/intelligence/features/registry.py` | registry | transform | `src/intelligence/regime_signals/__init__.py` | role-match |
| `src/intelligence/features/kernels/{price,volume,smc,vp_sr,calendar,macro,regime}.py` | pure compute | transform | `src/intelligence/feature_factory.py` `_*_series_full` (2154-2930), `_precompute_series` (3558) | exact (code moves) |
| `src/intelligence/features/kernels/regime.py` (HMM as kernel, R-10) | pure compute | transform | `services/regime_writer.py` `_walk_forward_hmm_labels` (724), `_compute_symbol_tf_walk_forward` (1003) | exact (code moves) |
| `src/intelligence/features/causality_probe.py` | utility | transform | `src/intelligence/research/guards.py` `causality_probe_array` (193-222), `memory_check_array` (225-257) | exact (import, do not copy) |
| `tests/unit/intelligence/test_kernel_registry_parity.py` | test | transform | `tests/unit/intelligence/test_feature_factory_batch_parity.py` | exact |
| `tests/unit/intelligence/test_causality_probe.py` | test | transform | `tests/unit/research/test_families_overnight_intraday.py:78-104` | exact |
| `services/backfill_feature_factory.py` (rebuild writer, todo 339) | batch service | batch | itself: compute stage 1215-1325, worker 1326 | exact |
| Rebuild precondition checker + `tests/unit/test_rebuild_preconditions.py` | utility | request-response (refusal) | `src/intelligence/research/provenance.py` (refusal exception), `_batch_utils.check_decompress_headroom` (319-335), `snapshot.build_panel` oos refusal (234-241) | partial |
| `scripts/research/determinism/*` (promoted repro_frozen) | script | file-I/O | `scripts/analysis/sleeve_walk_forward/repro_frozen.py`, `run.py` (`_save` 93-102, `_stage_s2sig` 191-206), `snapshot.py` (249-276) | exact (code moves) |
| `tests/unit/research_tools/test_repro_frozen.py` (unpickler remap) | test | file-I/O | none | no analog |
| `scripts/research/todo445_*.py` (R-08) | script | batch | `scripts/research/e17_null_battery.py` | role-match |
| Sole-writer guard for the new IC writer / `lineage_batch` | test (CI lint) | file-I/O | `tests/unit/research/test_ledger_sole_writer.py` | exact |
| `scripts/ops/corpus/ops_corpus_pipeline_run.sh` (remove steps 6-8, later 3) | orchestrator | batch | itself: steps 346-440 | exact |

## Pattern assignments

### `tests/unit/test_summary_cards.py` (test, CI lint)

**Analog:** `tests/unit/test_todo_priorities_link_integrity.py` (whole file, 99 lines)

Docstring shape (lines 1-23): states the drift class, why CI enforces it, and ends with
"CI-clean: no DB, no network -- pure filesystem + regex scan."

Module constants and cached scans (lines 25-57):
```python
from __future__ import annotations

import functools
import re
from pathlib import Path

from tests.unit._allow_list_scan import stale_allow_list_entries, unexpected_violations

_REPO_ROOT = Path(__file__).parent.parent.parent
_PENDING_DIR = _REPO_ROOT / ".planning" / "todos" / "pending"
...
@functools.lru_cache(maxsize=1)
def _pending_filenames() -> set[str]:
    return {path.name for path in _PENDING_DIR.glob("*.md")}
```

Assertion shape (lines 60-69): one `assert not <set>, (message naming the fix)` per rule. Copy
for "`DROP_TABLES` minus union of card `tables` is empty" and "every required key present".

**YAML parsing:** reuse the strict loader idea from `src/intelligence/research/spec.py:317-338`
(SafeLoader with YAML 1.1 booleans removed, so `reproducible: no` cannot pass as False). Do not
import from `src/intelligence/research/` into a card test only for this; copy the 8-line loader
subclass into the test (it is a test-local parser, not shared logic).
```python
class _SpecLoader(yaml.SafeLoader):
    """SafeLoader with YAML 1.2 booleans: only true/false. ..."""

_SpecLoader.yaml_implicit_resolvers = {
    first: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:bool"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_SpecLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)
```

**Git existence check for `recipe_commit`:** copy the `_git` helper shape from
`src/intelligence/research/provenance.py:32-35` and the `cat-file -e` idiom from line 50:
```python
def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=check, capture_output=True, text=True
    )
...
    if _git(root, "cat-file", "-e", f"HEAD:{rel}", check=False).returncode != 0:
```
Use `git cat-file -e <commit>` for the commit and `git cat-file -e <commit>:<path>` for recipe
paths (paths under `scripts/analysis/` will not exist at HEAD after D-12, so check at
`recipe_commit`, not HEAD).

### `docs/research/summary-cards/*.md` (doc records)

**Analog for front matter:** `.planning/todos/pending/448-research-lane-dependencies-for-phases-186-187.md:1-6`
(`---` fenced YAML, then `# Title`, then prose). Use the schema in 186-RESEARCH.md lines 679-701.

**Source of numbers:** copy verbatim from `docs/research/construction-verdict-ledger.md` section
4 (lines 104-122, one row per verdict) and the cited docs; D-05 forbids re-scoring. Prose follows
the global style rules (sentence case, no em dashes). Doc provenance line per memory convention:
`Author:` / `Informed by:` under the title (see `docs/research/earnings-season-conditioning-null-controlled-prereg.md:3`).

### `production/migrations/NNN_lineage_batch.sql` (migration, new table)

**Analog:** `production/migrations/366_research_run_ledger.sql`

Header convention (lines 1-38): number and one-line purpose, design pointer, writer contract,
volume note ("Not a hypertable; no VACUUM step."), idempotency note ("Not idempotent on purpose:
a second apply fails loudly on CREATE TABLE.").

Table with CHECK constraints and hash-format checks (lines 40-70):
```sql
BEGIN;

CREATE TABLE research_run (
    run_id        uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    ...
    spec_hash     text        NOT NULL,
    code_commit   text        NOT NULL,
    status        text        NOT NULL DEFAULT 'started',
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    CONSTRAINT research_run_spec_hash_check
        CHECK (spec_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT research_run_status_check
        CHECK (status = ANY (ARRAY['started', 'completed', 'guard_failed', 'refused', 'failed'])),
    ...
);

CREATE UNIQUE INDEX research_run_real_spec_once
    ON research_run (spec_hash, concept_id) WHERE mode = 'real';
```
For `lineage_batch`: the idempotency key (writer, target, code key, APR hash, input digest, tf,
range start/end, symbols hash) is a UNIQUE index (or the PK, per D-37); status
`started|completed|failed`; `COMMENT ON TABLE` naming the sole writer (`services/_batch_utils.py`
`bulk_load`), as at lines 76-80. The append-only guard trigger (lines 86-120,
`fn_research_run_guard`) is the model if completed rows must never be edited.

Numbering: check `ls production/migrations | sort -V | tail` immediately before numbering (latest
is 379; phase 185 writes concurrently). `tests/unit/test_migration_number_uniqueness.py` fails on
a collision. Commit the file in the same commit as `psql -f` applies it.

### APR seed migrations (every new `infra.*` / `alpha.*` key in the phase)

**Analog:** `production/migrations/375_ibkr_rate_limit_by_timeframe.sql:15-36` (schema + state +
history, all idempotent):
```sql
BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'infra.ibkr.rate_limit_max_requests_by_tf',
    'json',
    '{}',
    NULL, NULL,
    '[rca_analysis] Per-timeframe ... Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.ibkr.rate_limit_max_requests_by_tf', '{}', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (NOW(), 'infra.ibkr.rate_limit_max_requests_by_tf', 1, '{}', 'migration_375', 'Initial value: ... [rca_analysis]')
ON CONFLICT DO NOTHING;

COMMIT;
```
Multi-key form: `362_compressed_write_session_disk_headroom.sql:8-27` (one INSERT with several
VALUES rows). Descriptions start with a provenance tag (`[initial_estimate]`,
`[conventional]`, `[rca_analysis]`, `[user_preference]`) and state ML-target status.

### Drop migrations (D-14, R-01, ctx tables, `construction_spreads`, `feature_ic_scores_history`, later `forward_returns` and APR key deletion)

**Analog:** `production/migrations/311_retire_feature_registry.sql`

Header (lines 1-44): records preconditions asserted before writing (for 186: the D-08 grep
result, the card ids covering the table, D-06 lint passing), and any relaxed evidence plainly.

In-transaction guard that refuses the drop (lines 48-86):
```sql
DO $$
DECLARE
    v_transition_log_count INT;
    ...
BEGIN
    SELECT count(*) INTO v_transition_log_count FROM feature_transition_log;
    ...
    IF v_transition_log_count <> v_replayed_count THEN
        RAISE EXCEPTION 'refusing to drop: transition-log replay incomplete (% source rows, % replayed)',
            v_transition_log_count, v_replayed_count;
    END IF;
END $$;
```
For 186 guards: refuse if a row count changed since the card was written (for example
`ensemble_weights` still 358 rows, `ctx_events` still 0), or if a compression policy job is
running on the table.

Drop without IF EXISTS / CASCADE (lines 88-95): "a missing table or an unexpected dependent object
should fail loudly".

APR key deletion with history row first (lines 106-125):
```sql
INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), cs.config_key, cs.version, cs.config_value, 'migration_311',
    'Removed: sole consumer (...) deleted as dead code ...'
FROM config_state cs
WHERE cs.config_key LIKE 'alpha.feature_registry.%'
  AND NOT EXISTS (
      SELECT 1 FROM config_history ch
      WHERE ch.config_key = cs.config_key AND ch.changed_by = 'migration_311'
  );

DELETE FROM config_state WHERE config_key LIKE 'alpha.feature_registry.%';
DELETE FROM config_schema WHERE config_key LIKE 'alpha.feature_registry.%';
```
Per-key, not per-prefix, where the research warns of live readers: `alpha.ensemble.mv_condition_max`
(read by `services/tag_calibrator.py:1254`), `alpha.ic.shrinkage_k`, `alpha.ic.canary_rng_seed`
(read by `backfill_feature_factory`) must be excluded from any `LIKE` delete.

Drops of compressed hypertables need no decompress, so the VACUUM CI rule
(`tests/unit/test_compressed_hypertable_migration_vacuum_check.py`) does not trigger; any migration
that does decompress then compress (the D-19 purge if written as a migration) must end with a bare
`VACUUM <table>;` outside `BEGIN/COMMIT`.

### D-36 duplicate index migration

**Analog:** `production/migrations/193_db_hygiene_pass.sql:1-37`

Header records the evidence (`idx_scan`, sizes) and the run command. `market_regimes` is a plain
table, so `DROP INDEX CONCURRENTLY` is allowed there (it cannot run inside BEGIN/COMMIT); 193
itself used plain `DROP INDEX IF EXISTS` on hypertables because Timescale 2.27.1 rejects
CONCURRENTLY on them (lines 11-16):
```sql
DROP INDEX IF EXISTS forward_returns_content_key_idx;
```
193 lines 93-130 also record the D-37 precedent: Timescale 2.27.1 rejects `ADD CONSTRAINT ...
USING INDEX` on a hypertable, so `market_data_ohlcv` keeps `market_data_ohlcv_pkey_idx` (unique,
NOT NULL) as its PK equivalent. Cite this in the D-37 plan instead of re-testing assumption A1.

### `feature_ic_scores` old-grid delete (R-07) and D-19 purge

**Analogs:** `production/migrations/175_cross_sectional_ic_index.sql:9-10` (plain row DELETE in a
migration) and `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py:1-60` (dry-run by default,
`--apply` to write, report first). `feature_ic_scores` is a compressed hypertable (2/2 chunks):
a DELETE on compressed chunks decompresses them in place, so follow
`docs/foundation/performance-investigation-sop.md` (measure `pg_stat_activity.wait_event` first),
and if the plan decompresses/recompresses explicitly, end with bare `VACUUM feature_ic_scores;`.
Order (R-06): parity, then the D-19 purge, then D-22.

### `services/_batch_utils.py`: `bulk_load()` and lineage helpers (D-24)

**Analog:** same file.

Imports already present (lines 4-23): `csv`, `io`, `json`, `shutil`, `psycopg`, `structlog`,
`ConfigService`, `clamp_to_real_range`. Module logger `_logger = structlog.get_logger()` (25).

COPY into a temp table with the float32 clamp driven by `col_types` (lines 142-168). Reuse this
exact loop for the staging step; `col_types` stays the single source of truth for which columns are
`real` (todo 312):
```python
    all_cols = set_cols + key_cols
    col_defs = ", ".join(f"{c} {col_types[c]}" for c in all_cols)
    real_positions = frozenset(i for i, c in enumerate(all_cols) if col_types[c] == "real")

    with conn.cursor() as cur:
        cur.execute(f"CREATE TEMP TABLE IF NOT EXISTS {temp_table} ({col_defs})")
        cur.execute(f"TRUNCATE {temp_table}")

        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in rows:
            if real_positions:
                row = tuple(
                    _clamp_to_real_range(v) if i in real_positions else v for i, v in enumerate(row)
                )
            writer.writerow("" if v is None else v for v in row)
        buf.seek(0)
        with cur.copy(
            f"COPY {temp_table} ({', '.join(all_cols)}) FROM STDIN WITH (FORMAT CSV)"
        ) as copy:
            copy.write(buf.getvalue())
```
Contract to keep: "conn: caller commits; this function does not call conn.commit()" (line 112).

Per-chunk compress SQL (lines 386-390); the new primitive compresses only chunks whose range is
fully covered by completed lineage records, so filter by chunk range rather than "all":
```python
_COMPRESS_ALL_DECOMPRESSED_CHUNKS_SQL = (
    "SELECT compress_chunk(format('%%I.%%I', chunk_schema, chunk_name)::regclass, "
    "if_not_compressed => true) FROM timescaledb_information.chunks "
    "WHERE hypertable_name = %s AND NOT is_compressed"
)
```
Keep the `%%I` escaping note (lines 374-381): psycopg rejects a single `%I`; asyncpg siblings use a
single `%I` (lines 813-822).

Compression-job pause/restore (lines 301-304 SQL, `_restore_compression_jobs_sync` 449, async
825-837): "refuse to write while a compression policy job is active over the range" reuses
`_FIND_COMPRESSION_JOBS_SQL`.

Disk guard (R-09): extend, do not replace, `check_decompress_headroom` (lines 319-335). Its shape is
a pure function raising `RuntimeError` with GB figures and the APR fraction:
```python
def check_decompress_headroom(
    hypertable: str, required_bytes: int, disk_path: str, min_free_after_fraction: float
) -> None:
    usage = shutil.disk_usage(disk_path)
    reserve = int(min_free_after_fraction * usage.total)
    if usage.free - required_bytes < reserve:
        raise RuntimeError(...)
```
APR read inside a helper (lines 338-354): direct `config_state` select for 2 keys with module
constants `_DISK_PATH_KEY`/`_DISK_PATH_DEFAULT` as fallbacks. New tunables follow lines 251-254:
```python
_STATEMENT_TIMEOUT_APR_KEY = "infra.compressed_hypertable_write_session.statement_timeout_ms"
_DEFAULT_STATEMENT_TIMEOUT_MS = 14_400_000  # 4h -- see migration 314 for provenance
```
i.e. `infra.bulk_load.<param>` key constant plus a fallback constant with a migration pointer.

Content hashing for the input digest / symbols hash: `BaseBatch.content_key(*parts)`
(`src/core/agent/base_batch.py:139-153`, sha256 of `|`-joined parts). Per-kernel code key
(D-23): reuse `_normalized_source_for_hash` (`services/ic_engine.py:5329-5358`, AST-normalized,
docstrings blanked) applied to the kernel's own module source, not `_checkpoint_content_key`'s
all-`sys.modules` walk (5361-5420). Move that helper out of `ic_engine.py` (into `_batch_utils.py`
or Ring 0) before D-22 deletes the file.

Test-reset convention: module-level caches get an autouse reset fixture in the test file
(comment at lines 211-216).

### `tests/unit/test_bulk_load.py`

**Analog:** `tests/unit/test_batch_utils.py:1068-1100`
```python
class TestBulkUpdateByKeyRealClamping:
    def _written_csv(self, conn: MagicMock) -> str:
        cur = conn.cursor.return_value.__enter__.return_value
        copy_ctx = cur.copy.return_value.__enter__.return_value
        return "".join(c.args[0] for c in copy_ctx.write.call_args_list)

    def test_underflowing_value_in_a_real_column_is_clamped_before_copy(self) -> None:
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.copy.return_value.__enter__.return_value = MagicMock()
        bulk_update_by_key(conn, table="some_table", ...)
        csv_text = self._written_csv(conn)
        assert "1e-50" not in csv_text
```
For ordered multi-statement sequences (lineage lookup, COPY, INSERT SELECT, compress, lineage
complete), use the scripted fake in `tests/unit/_compressed_hypertable_write_session_fakes.py`
(`ScriptedConn`/`ScriptedCursor`, lines 22-80: records `calls`, replays `responses` in order,
counts `commits`/`rollbacks`). Assert the idempotent rerun issues no COPY when the lineage lookup
returns a completed row.

### `tests/integration/test_bulk_load.py`

**Analog:** `tests/integration/test_research_ledger.py:1-60`
```python
pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent_test"
```
Uses `src.core.database_manager.connect_with_codecs` and unique per-test names (`_name()` with a
uuid suffix) for cleanup. The session fixture in `tests/integration/conftest.py:175-183` replays
post-baseline migrations into `indicagent_test`, so the lineage migration is exercised by the
fixture itself. Create a scratch hypertable in the test (create, COPY two chunks, compress per
chunk, rerun is a no-op, drop).

### `src/intelligence/measure/{proposer,term_structure,monitoring}.py` (pure compute)

**Analogs:** `src/intelligence/statistics/ic_math.py` (module contract lines 1-18: "Pure functions
only -- no DB, no config loading, no module-global mutable state"), and the kernel
`src/intelligence/research/panel.py`.

Statistic to call (ic_math 441-458), identical math is what parity depends on:
```python
def compute_ic_vectorized(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    ranks_X = rankdata(X, axis=0)
    ranks_y = rankdata(y)
    return _vectorized_ic(ranks_X, ranks_y)
```
Multiplicity (545-568): `apply_bh_fdr(p_values, alpha) -> (reject, p_corrected)`; scatter-back
stays local to the caller (docstring 553-558). CIs: `_circular_block_bootstrap_ic` (207),
rolling metrics `_compute_ic_rolling_metrics` (1009), HAC `_hac_sharpe_nd` (967).

Targets (read-only import, D-18): `panel.forward_returns` (93-130):
```python
def forward_returns(
    opens: np.ndarray,
    horizon: int = 1,
    session: np.ndarray | None = None,
    closes: np.ndarray | None = None,
) -> np.ndarray:
    """fwd[t] = ln(open[t + 1 + horizon] / open[t + 1]) ..."""
```
Intraday: pass `session=panel.session` (`Panel.session`, 60-63) so no target crosses a session;
1d passes `session=None` (a 1d panel with `session` raises, line 116-118). `fwd_span(h) = 1 + h`
(155-157) is the embargo term. Panels come from `snapshot.build_panel(dsn, out_dir, symbols=,
tf=, start=, end_exclusive=, dividends=)` (`src/intelligence/research/snapshot.py:219-241`),
which refuses `end_exclusive > oos_start`; set `end_exclusive = oos_start` and D-19 holds by
construction. Load with `panel.load(path)` (179-190). Symbol chunks: `panel.select_symbols`
(210).

Dataclass style for results: frozen dataclasses (`panel.Panel` 24-58 with `__post_init__` shape
checks; `ic_math.GuardVerdict` 1110). Raise `ValueError` on misuse, never return a silent default.

### `services/ic_measure.py` (writer, BaseBatch oneshot)

**Analog:** `services/dividend_event_writer.py` (recent BaseBatch writer)

Imports (lines 43-63):
```python
from __future__ import annotations

import argparse
import asyncio
...
import asyncpg

from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async
from src.config.settings import Settings, get_active_contracts
from src.core.agent.base_batch import BaseBatch
from src.observability.metrics import counter
from src.observability.otel import OTelInitError, init_otel_providers

_JOB = "dividend-event-writer"
```

Class and APR load (lines 280-311):
```python
class DividendEventWriter(BaseBatch):
    job_name = _JOB
    compute_version = "1.0.0"

    def __init__(self, db_dsn: str, settings: Settings, ...) -> None:
        super().__init__(db_dsn)
        ...

    async def execute(self, pool: asyncpg.Pool) -> None:
        async with pool.acquire() as conn:
            apr = await load_apr_dict_async(
                conn,
                ["threshold.dividend_event.%", "infra.dividend_event.%", "infra.ibkr.rate_limit%"],
            )
        margin = float(_cfg(apr, "threshold.dividend_event.noise_margin", 1.25))
```
`load_apr_dict_async` (`_batch_utils.py:787-805`) loads `alpha.%` plus extra LIKE patterns;
`cfg()` (955-978) casts, including the bool and JSON special cases.

Entry point (lines 552-575):
```python
def main() -> None:
    parser = argparse.ArgumentParser(description="...")
    ...
    try:
        init_otel_providers(f"indicagent-{_JOB}")
    except OTelInitError:
        pass
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    writer = DividendEventWriter(db_dsn, ...)
    asyncio.run(writer.run())
```
`BaseBatch.run()` (`src/core/agent/base_batch.py:104-133`) already emits `job_completed_total`
and `job_duration_seconds` with `{"job": job_name, "status": ...}`, wraps `execute` in
`observed_span`, and opens the pool via `create_pool` (JSONB codecs registered, 159-173). No
per-service metric code is needed for D-06. `job_name` is kebab-case and must match the systemd
unit `%n` suffix if a unit is ever added.

Writes go through `bulk_load()` (D-20, D-24), from one serial connection in the main process;
compute runs in `make_worker_pool` workers that return rows (see shared patterns).

### `services/feature_lifecycle.py` (D-30 shrink, R-03 ordering)

**Analog:** itself. Keep the BaseBatch skeleton (550-600) and the `from_apr` classmethod pattern
(93-127):
```python
@dataclass(frozen=True)
class LifecycleConfig:
    ...
    @classmethod
    def from_apr(cls, cfg: dict[str, Any]) -> LifecycleConfig:
        return cls(
            materiality_threshold=_cfg(cfg, "alpha.decay.materiality_threshold", 0.005),
            ...
        )

    def rule_fingerprint(self) -> dict[str, Any]:
        return dataclasses.asdict(self)
```
Remove: `_CELLS_SQL`'s `LEFT JOIN ensemble_weights` (438-457), material-fail and stratum guard
logic (141-236), `alpha.ensemble.*` and `alpha.decay.*` reads. Keep: the `concept_evaluation`
upsert idempotency via `evidence_key` (311) and `ConceptRegistryService().record_transition`
(`_apply`, 845-868), the only allowed status writer (UCR rule). The new decision inputs are
computed / valid / coverage-floor statistics (one definition shared with todo 421/435 coverage).
The shrink lands before the `ensemble_weights` drop migration.

### `services/service_auditor.py` (registry edits)

**Analog:** itself. Remove, in the same commit as the module deletion:
- `_DAG_ORDER`: line 80 (`indicagent-ctx-writer`), 108 (`forward-return-writer`, at D-22), 109
  (`ic-engine`, at D-22), 112-116 (ensemble-trainer, alpha-publisher, ensemble-ic-engine,
  alpha-frame-writer, counterfactual-tracker).
- `_AGENT_ID_TO_UNIT`: line 167 (`"context_writer": "indicagent-ctx-writer"`).
- `_ONESHOT_UNITS`: lines 205-206 (D-22) and 210-214.
Checked by `tests/unit/services/test_service_auditor_registry_integrity.py` and
`tests/unit/services/test_service_auditor.py`; `tests/unit/test_counterfactual_tracker.py` also
references `_DAG_ORDER` and is deleted with the module. Seeded `alert.lag.*` keys for removed units
are deleted in a migration (311 APR pattern).

### `src/intelligence/features/registry.py` and `kernels/*.py` (D-25, D-26)

**Registry analog:** `src/intelligence/regime_signals/__init__.py` (module docstring states the
pure DB-free contract every module implements; registry is a plain dict built from explicit
imports):
```python
"""REGISTRY -- signal_type string -> regime signal module.
...
Every module implements the same pure, DB-free contract:
  - compute(ref_bars: dict[str, pd.DataFrame], params: dict[str, Any]) -> tuple[pd.Series, pd.Series] | None
  ...
"""
from src.intelligence.regime_signals import (
    breadth_vol,
    commodity_momentum_ts,
    ...
)

REGISTRY: dict[str, object] = {
    "breadth_vol": breadth_vol,
    ...
}
```
For kernels, make the entry a frozen dataclass (name, inputs, memory_bars, dtype, compute,
origin) rather than a bare module, so declared memory (D-26) and the per-kernel code key (D-23)
are fields. Explicit imports, no import-time side-effect registration (compare
`src/core/ai/registry.py:28-32`, which the YAML agent stack uses and which is dormant).

**Kernel body analog:** `src/intelligence/feature_factory.py` `_*_series_full` (index list at
995-2930), e.g. 2154-2163:
```python
def _momentum_z_series_full(closes: np.ndarray, window: int, zscore_window: int) -> np.ndarray:
    """Log-return velocity series, z-scored. result[i] == streaming momentum_z at bar i.
    Returns zeros for i < window (cold start matches streaming's 0.0).
    """
    n = len(closes)
    if n <= window:
        return np.zeros(n, dtype=float)
    log_returns = np.log(np.maximum(closes[window:], 1e-10) / np.maximum(closes[:-window], 1e-10))
    z = _fixed_window_zscore_series(log_returns, zscore_window)
    return np.concatenate([np.zeros(window, dtype=float), z])
```
Declared memory for this kernel is `window + zscore_window`. Shared intermediates computed once in
`_precompute_series` (3558-3590, e.g. `atr_padded`, `price_vol_abs_rets`) become declared inputs
of the kernels that read them. Features injected outside the factory
(`services/backfill_feature_factory._compute_symbol_tf`, 1451: cross-asset, betas, CTF, VP/SR,
cross-tf divergences) need their own kernels under `macro`/`vp_sr`. Moves are code-only commits;
behavior changes are separate commits (D-25).

**Regime kernel (R-10):** move `_walk_forward_hmm_labels` (`services/regime_writer.py:724-760`,
signature takes `obs_matrix` plus fit parameters and returns labels aligned to
`obs_matrix[initial_warmup_bars:]` plus segments). The obs matrix builders
`_fetch_obs_matrix` (1431) and `_fetch_obs_matrix_volatility` (1502) split into a DB fetch
(stays in the writer) and a pure transform (goes into the kernel). The full-history
`_compute_symbol_tf` (1568) is deleted (D-29). `alpha.hmm.random_state` stays an APR seed.

### `src/intelligence/features/causality_probe.py` (D-27)

**Analog:** `src/intelligence/research/guards.py:193-257` already implements the probe (NaN fill
and per-cell random rescale, descending t, exact equality with NaN-both-sides allowed) and the
memory check over plain arrays. D-02 forbids editing the research package, not importing its
public functions. Wrap, do not copy:
```python
def causality_probe_array(
    fn: ArrayFn, x: np.ndarray, rows: np.ndarray, *, seed: int, reach: int = 0
) -> None:
    """causality_probe over an array input: raise unless fn(x)[:t + 1] is unchanged when rows
    after t + reach are replaced, once with NaN and once with per-cell random rescaling."""
```
The feature-side wrapper adds what D-27 asks beyond the research version: float32 cast before
comparison with a 1-ulp tolerance option (`np.nextafter`), and cross-sectional kernels truncating
every symbol (the array's column axis already does this when x is `[row, symbol]`). It raises the
research `GuardFailure` or a feature-local exception; decide once and state it.

### `tests/unit/intelligence/test_causality_probe.py`

**Analog:** `tests/unit/research/test_families_overnight_intraday.py:78-104`
```python
CASES = [
    (f2.intraday_persistence, {"window_sessions": 20}, 20),
    ...
]

@pytest.mark.parametrize(("fn", "params", "history"), CASES)
def test_causal_and_within_declared_memory(fn, params, history):
    member = functools.partial(fn, bars_per_session=3, coverage_floor=FLOOR, **params)
    r = _resid(5)
    rows = np.array([3 * 40 + 1, 3 * 70 + 1, 3 * 70])
    causality_probe_array(member, r, rows, seed=1)
    declared = history * 3
    reach = memory_check_array(member, r, rows[rows < len(r) - declared - 1], declared=declared)
    assert reach <= declared
```
Parametrize over `registry.KERNELS` with each kernel's declared memory; add one injected
lookahead kernel that must raise.

### `tests/unit/intelligence/test_kernel_registry_parity.py` (D-25 byte-identical)

**Analog:** `tests/unit/intelligence/test_feature_factory_batch_parity.py`

Fixture shape (151-173): seeded `RNG = np.random.default_rng(42)` (line 28), 500 synthetic OHLCV
bars as arrays plus dict list with UTC timestamps; module-scoped fixtures (`cfg` 176, `streaming`
181). `_make_cfg()` (31+) shrinks windows so everything warms up early. Replace the 1e-8 tolerance
in `_assert_parity` (195-205) with `np.array_equal(a.astype(np.float32), b.astype(np.float32),
equal_nan=True)` against `FeatureFactory.compute_batch` (`feature_factory.py:7347`) output
captured before the split.

### `services/backfill_feature_factory.py` (rebuild writer, D-28, todo 339)

**Analog:** itself, compute stage 1215-1325.

Pool construction and main-process serial writes (1228-1235, 1260-1290):
```python
    with (
        _write_session(db_conn, "feature_vectors", decompress=False),
        _make_worker_pool(n_workers, blas_threads_per_worker) as pool,
    ):
        for result in pool.map(_run_compute_worker, worker_args, chunksize=1):
            ...
                try:
                    for i in range(0, len(rows), insert_batch_size):
                        _batch_insert(db_conn, rows[i : i + insert_batch_size], refresh=refresh)
                    with db_conn.cursor() as cur:
                        cur.execute(_MARK_COMPUTE_COMPLETE_SQL, (rows_written, theoretical, symbol, tf))
                    db_conn.commit()
                except Exception as error:
                    db_conn.rollback()
                    _logger.error("compute_cell_write_failed", symbol=symbol, tf=tf, error=str(error), ...)
                    _mark_cell_failed(db_conn, symbol, tf, str(error))
                    continue
```
Changes: the unit becomes (symbol chunk, tf, time range) keyed by the lineage record; the worker
returns one unit's rows (bounded, todo 339) instead of one symbol's 4-tf list; `_batch_insert`
(1603) is replaced by `bulk_load()`; `backfill_status` skip logic (797-833) is replaced by the
lineage lookup; the write session is dropped for the new append-only table (no decompress needed).
Per-cell isolation and "worker returns data, main writes" stay.

### Rebuild precondition checker + `tests/unit/test_rebuild_preconditions.py` (D-32, R-09)

**Partial analogs:**
- Refusal as a typed exception and small pure checks: `src/intelligence/research/provenance.py:30-58`
  (`class ProvenanceRefusal(Exception)`, `require_committed` raising with the reason).
- Disk check: `_batch_utils.check_decompress_headroom` (319-335), a pure function over
  `shutil.disk_usage`, trivially testable by monkeypatching `shutil.disk_usage`.
- DB-side refusal before any fetch: `snapshot.build_panel` (234-241) checks `oos_start` first.

Shape: each precondition is a pure function over measured inputs (coverage rows, todo 445 record,
landed-module markers, disk numbers from the pilot) returning a result; the checker runs all,
records all, and raises if any fail. Coverage query reads `market_data_ohlcv_tradeable` (never the
raw table; `tests/unit/test_market_data_ohlcv_boundary.py` allow-list otherwise) and lists
`ohlcv_empty_history` spans.

### `scripts/research/determinism/*` (promoted repro_frozen, D-11, R-05)

**Analog:** `scripts/analysis/sleeve_walk_forward/repro_frozen.py` (119 lines) and its minimal
deps. Keep the script docstring with the usage line (1-11) and the `same()` recursive exact
comparator (35-70) unchanged. Replace `run.main(["--stage", "s2sig", ...])` (96-99) with an inline
s2sig stage copied from `run.py:191-206` and `_s2_payload` (156-169), dropping `_code_key`
(payload comparison already ignores the snapshot key, lines 104-108). `snapshot_io.py` carries
only `verify_snapshot` / `load_snapshot` (`snapshot.py:249-276`, which use `store.verify` and
`np.load(..., mmap_mode="r", allow_pickle=False)`). `sessions.refit_dates` (`sessions.py:9-20`)
and `config.HarnessConfig` (`config.py:1-60`) move byte-identical. Worker pool stays
`functools.partial(make_worker_pool, blas_threads_per_worker=CFG.blas_threads_per_worker)` (line 32).

**Unpickler remap: no analog in the repo** (no `find_class` anywhere). Replace each
`pickle.loads(path.read_bytes())` (lines 86-89, 100-105) with a loader built on
`pickle.Unpickler` whose `find_class` maps exactly
`scripts.analysis.sleeve_walk_forward.evaluate` to `src.intelligence.research.evaluate` and
passes everything else through; the current shim (`evaluate.py`, 4 lines) documents why. Test with
a fixture pickle produced in the test by pickling an `EvaluationResult` and rewriting its module
path, plus a real frozen artifact check when `logs/phase179` exists (skip otherwise).

### `scripts/research/todo445_*.py` (R-08)

**Analog:** `scripts/research/e17_null_battery.py:1-60`: docstring with the exact usage command,
`sys.path.insert(0, ".")` then first-party imports with `# noqa: E402`, `argparse` in `main() ->
int`, workers through `make_worker_pool`, one JSON record written to an output path. Targets from
`panel.forward_returns` on an S0 15m panel with `end_exclusive <= oos_start`. Record the counted
look in `.planning/gate_look_log.jsonl` (R-08).

### Sole-writer guard for the new IC writer and `lineage_batch`

**Analog:** `tests/unit/research/test_ledger_sole_writer.py:1-50`
```python
from tests.unit._source_grep_helpers import (
    assert_allow_list_has_no_stale_entries,
    assert_no_unlisted_references,
    find_pattern_references,
)

_SEARCH_DIRS = ("services", "src", "scripts", "production")
_FILE_GLOBS = ("*.py", "*.sql")

_RUN_WRITE_PATTERN = re.compile(
    r"(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+research_run\b", re.IGNORECASE | re.DOTALL
)
_RUN_WRITE_ALLOW_LIST: dict[str, str] = {
    _LEDGER: "PERMANENT: the S6 sole writer of research_run (phase 183, D-05).",
}
```
Same pattern for `lineage_batch` (sole writer `services/_batch_utils.py`) and, after D-22, for
`feature_ic_scores` (sole writer the new IC writer; migrations allow-listed with a reason).

### `scripts/ops/corpus/ops_corpus_pipeline_run.sh`

**Analog:** itself. `run_step N "name" \` blocks: step 3 `forward_return_writer` (346-352, goes
at D-22), step 6 `ic_shrinkage` (386-393), step 7 `ensemble_trainer` (395-399), step 8
`alpha_publisher` (401-420) and the gate after it (423-445) go with plan 07. `--from-step`
handling (17-27, 92, 149) and `step_timings.jsonl` logging (59-69) stay. `ops_pipeline_monitor.sh`
is edited in the same commit.

## Shared patterns

### Oneshot lifecycle and D-06 metric
**Source:** `src/core/agent/base_batch.py:104-133, 193-208`
**Apply to:** `services/ic_measure.py`, the shrunk `feature_lifecycle.py`, any new batch service.
Subclass `BaseBatch`, set `job_name` (kebab) and `compute_version`, implement `async
execute(pool)`. Scripts that are not BaseBatch (psycopg-based, like `forward_return_writer.py`)
emit it by hand in `finally` (`services/forward_return_writer.py:915-920`):
```python
    finally:
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()
        if status == "failure":
            sys.exit(1)
```

### APR access
**Sources:** async dict path `services/_batch_utils.py:787-805` + `cfg()` 955-978; sync
ConfigService path `load_config_service_sync` (67-80) then `cfg.get_sync(key, fallback)`
(`services/forward_return_writer.py:720-757`, e.g.
`int(cfg.get_sync("alpha.quant.cross_symbol_corroboration.min_symbols", 4))`); JSON lists via
`get_list_config` (1148). Fallback constants sit at module level with a comment naming the
migration that seeds the key.
**Apply to:** every new tunable (`infra.bulk_load.*`, worker counts, parity sample sizes if made
tunable, coverage floor). New keys ship with a seed migration (375 pattern).

### Compute in workers, one serial writer
**Source:** `services/_batch_utils.py:759-774` (`make_worker_pool`, BLAS cap) and
`services/backfill_feature_factory.py:1228-1290` (workers return rows; main process writes and
commits per cell, rolls back and marks failed on error).
**Apply to:** fresh IC jobs, rebuild writer, parity harness, todo 445 script. Never
`ProcessPoolExecutor(...)` directly. After a kill: reap forkserver workers and
`pg_terminate_backend` leftover backends (CLAUDE.md).

### Structured logging and errors
**Source:** `services/dividend_event_writer.py` and `services/_batch_utils.py:1339-1340`:
`except Exception as error:` then `_logger.warning("<module>.<event>", error=str(error))`. Event
names are `snake_case` dotted by module; never pass `event=`. Counters accumulate and log once per
unit (CLAUDE.md "never log per-row").

### asyncpg codecs
**Source:** `src/core/database_manager.py:19-41`. Pools from `create_pool` (via BaseBatch) have
JSONB codecs; a bare connection uses `connect_with_codecs(url)`. Dtypes come from
`conn.prepare(sql).get_attributes()`, never inferred from fetched values.

### Migrations
**Sources:** 366 (new table), 375/362 (APR), 311 (drop with guard and APR history), 193 (index),
300 (hypertable). Numbering checked right before writing; applied with
`PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f <file>` and committed in the
same commit. Decompress/compress round trips end with bare `VACUUM <table>;` outside the
transaction.

### New hypertable (rebuilt `feature_vectors`)
**Source:** `production/migrations/300_feature_ic_scores_history_hypertable.sql:47-73`
```sql
SELECT create_hypertable(
    'feature_ic_scores_history',
    'archived_at',
    chunk_time_interval => INTERVAL '1 month',
    migrate_data => true,
    if_not_exists => TRUE
);

ALTER TABLE feature_ic_scores_history SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol,tf',
    timescaledb.compress_orderby = 'archived_at DESC'
);
```
For the rebuild: keep the PK (D-37), set the chunk interval from the research estimate (about 1
year), do not add a compression policy while the build runs (the writer compresses per chunk), and
do not use `timescaledb.enable_direct_compress_copy` (needs no PK).

### Test-side allow-list edits
**Sources:** `tests/unit/test_market_data_ohlcv_boundary.py:33` (`_ALLOW_LIST: dict[str, str]`,
reason per path), `tests/unit/test_compressed_hypertable_write_boundary.py`. Deleting a listed
file fails `assert_allow_list_has_no_stale_entries`; edit the list in the same commit. Run
`pytest tests/unit -q --co` after every deletion to catch dead imports at collection.

## No analog found

| File | Role | Data flow | Reason |
|---|---|---|---|
| Remapping unpickler in `scripts/research/determinism/` | utility | file-I/O | No `pickle.Unpickler`/`find_class` use anywhere in the repo; write from the stdlib docs, limited to the one known class path |
| Rebuild precondition checker (as an assembled whole) | utility | request-response | Pieces exist (typed refusal, disk guard, oos refusal) but no multi-precondition gate; compose from the partial analogs above |
| Per-kernel code key as a registry field | utility | transform | `_normalized_source_for_hash` exists but only hashes all loaded modules via `_checkpoint_content_key`; per-kernel scoping is new |

## Metadata

**Analog search scope:** `services/`, `src/core/`, `src/intelligence/{statistics,research,features,regime_signals}/`,
`scripts/{research,analysis/sleeve_walk_forward,ops/corpus}/`, `production/migrations/`,
`tests/unit/`, `tests/integration/`
**Files scanned:** about 45 (read or grepped); live DB read once for `feature_ic_scores` indexes
**Pattern extraction date:** 2026-09-27
