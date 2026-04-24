# Phase 72: Signal Transform Log — Unified Alpha Modifier Architecture

**Gathered:** 2026-04-24
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-04-24-signal-transform-log-design.md)

<domain>
## Phase Boundary

Phase 72 delivers **Phase 1 of a 4-phase migration**: dual-write infrastructure for the unified transform log. This phase adds the DB tables, the `TransformRecorder`, the `graduation.py` validation module, the `GraduationComputeAgent`, the `GraduationWriterAgent`, the new Kafka topics, and wires one-line recorder calls into each existing transform stage. Existing behavior is **unchanged** — transforms still mutate confidence in-place; the log is write-only and the graduation pipeline runs in shadow.

**Out of scope for this phase:**
- Phase 2: Replace in-place confidence mutation with `compose_confidence()` (requires 30 days of dual-write data)
- Phase 3: Absorb `alpha_multiplier_shadow` table
- Phase 4: Drop deprecated columns from signal_ledger

</domain>

<decisions>
## Implementation Decisions

### Schema: signal_transform_log (LOCKED)

```sql
CREATE TABLE signal_transform_log (
    ts                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    signal_id         UUID NOT NULL,
    transform_id      TEXT NOT NULL,
    transform_version TEXT NOT NULL DEFAULT 'v1',
    dag_order         SMALLINT NOT NULL,
    segment_key       TEXT NOT NULL DEFAULT '__global__',
    multiplier        FLOAT NOT NULL,
    metadata          JSONB,
    is_shadow         BOOLEAN NOT NULL DEFAULT TRUE
);

SELECT create_hypertable('signal_transform_log', 'ts');

CREATE UNIQUE INDEX idx_stl_identity
    ON signal_transform_log (signal_id, transform_id, transform_version);

CREATE INDEX idx_stl_eval
    ON signal_transform_log (transform_id, segment_key, ts);
```

- TimescaleDB hypertable (same pattern as intelligence_features)
- Unique index on (signal_id, transform_id, transform_version) — one row per signal per transform per version
- Evaluation index on (transform_id, segment_key, ts) for graduation queries
- **is_shadow=TRUE by default** — write-time snapshot, not read at composition time

### Schema: transform_graduation (LOCKED)

```sql
CREATE TABLE transform_graduation (
    transform_id      TEXT NOT NULL,
    transform_version TEXT NOT NULL,
    segment_key       TEXT NOT NULL,
    n                 INT NOT NULL,
    spearman_rho      FLOAT,
    spearman_p        FLOAT,
    calibration_max_error FLOAT,
    cvar_bottom_decile FLOAT,
    mde               FLOAT,
    val_rho           FLOAT,
    overfitting_risk  BOOLEAN,
    sharpe_delta      FLOAT,
    is_graduated      BOOLEAN NOT NULL DEFAULT FALSE,
    evaluated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at        TIMESTAMPTZ NOT NULL,
    UNIQUE (transform_id, transform_version, segment_key)
);
```

- NOT a hypertable (analytical table, not time-series partitioned)
- All 6 dimensions as first-class columns — queryable, no JSONB for graduation decisions
- Unique constraint (transform_id, transform_version, segment_key) — UPSERT pattern

### Migration numbering (LOCKED)

Last migration is `068_gap_retry_tracking.sql`. New migrations:
- `production/migrations/069_signal_transform_log.sql` — creates signal_transform_log
- `production/migrations/070_transform_graduation.sql` — creates transform_graduation

### TransformRecorder (LOCKED)

**File:** `src/core/ml/transform_recorder.py`

Follows the same batch pattern as `ShadowRecorder` in `src/core/ml/shadow.py`. Key differences:
- Writes to `signal_transform_log` instead of `alpha_multiplier_shadow`
- Accepts one row per transform call (not one row per signal+agent combination)
- Must support batch executemany with asyncpg
- Async interface — all DB writes are async

Interface:
```python
class TransformRecorder:
    async def record(
        self,
        signal_id: str,
        transform_id: str,
        dag_order: int,
        multiplier: float,
        segment_key: str = "__global__",
        metadata: dict | None = None,
        transform_version: str = "v1",
        is_shadow: bool = True,
    ) -> None: ...

    async def flush(self) -> None: ...
```

Buffer rows in memory, flush on each call to `flush()` via asyncpg `executemany`. This keeps the hot path non-blocking.

### graduation.py validation module (LOCKED)

**File:** `src/intelligence/swarm/graduation.py`

Pure functions — DB-ignorant, testable, reusable by both `GraduationComputeAgent` and `scripts/validate_skeptic.py`.

**Gate constants** (LOCKED — sign change from validate_skeptic.py is intentional):

```python
GATE_SPEARMAN_RHO = 0.15          # positive: high multiplier → high pnl_r
GATE_CALIBRATION_MAX_ERROR = 0.10
GATE_CVAR_BOTTOM_DECILE = -0.5
GATE_SEGMENT_MIN_N = 30
GATE_SEGMENT_RHO = 0.15
GATE_SEGMENT_POWER = 0.80
EVAL_RESOLUTION_THRESHOLD = 20
EVAL_ROLLING_WINDOW_DAYS = 90
EVAL_EXPIRY_DAYS = 90
EVAL_WALK_FORWARD_FRACTION = 0.7
```

Note: `validate_skeptic.py` has `GATE_SPEARMAN_RHO = -0.15` (negative: failure_prob up → pnl_r down). The sign flips in `graduation.py` because the column is `multiplier` (high = confident), not `failure_probability` (high = worried). This is an intentional semantic change.

**Functions** (LOCKED):
```python
def compute_spearman(df: pd.DataFrame) -> dict       # columns: multiplier, pnl_r
def compute_calibration(df: pd.DataFrame) -> dict
def compute_expected_shortfall(df: pd.DataFrame) -> dict
def compute_segment_power(n: int, alpha: float = 0.05, power: float = 0.80) -> float
def compute_walk_forward(df: pd.DataFrame, train_fraction: float = 0.7) -> dict
def compute_value_add(df: pd.DataFrame) -> dict
def evaluate_all(df: pd.DataFrame) -> dict           # orchestrates all 6
```

DataFrame input always has columns `multiplier` (float) and `pnl_r` (float). Never binarized. `evaluate_all()` returns a dict matching the GraduationResult Kafka payload schema.

### validate_skeptic.py refactoring (LOCKED)

`scripts/validate_skeptic.py` becomes a thin CLI wrapper:
- Import from `src.intelligence.swarm.graduation` for all gate constants and compute functions
- Remove all inline computation logic (no duplication)
- Keep CLI argument parsing and DB fetch logic
- Sign change: adapt to new `multiplier`-positive semantics (was `failure_probability`-negative)

### Transform recorder wiring (LOCKED — one-line per stage)

Each pipeline stage adds exactly one `await recorder.record(...)` call after its existing logic. The `TransformRecorder` instance is passed in as a parameter (not constructed inside each function). Transform registry:

| dag_order | transform_id | File | segment_key formula |
|-----------|-------------|------|---------------------|
| 0 | `hurst_quality` | src/intelligence/pipeline/quality_gate.py | `{regime_type}.{tf}` |
| 1 | `drift_penalty` | src/intelligence/pipeline/quality_gate.py | `{regime_type}.{tf}` |
| 2 | `regime_gate` | src/intelligence/pipeline/regime_gate.py | `{regime_type}` |
| 3 | `tod` | src/intelligence/pipeline/tod_adjuster.py | `{regime_type}.{tf}.{hour_et}` |
| 4 | `isotonic` | src/intelligence/pipeline/calibrator.py | `{plugin_name}.{tf}` |
| 5 | `perf_weight` | src/intelligence/pipeline/ranker.py | `{plugin_name}.{tf}` |
| 6 | `swarm_skeptic` | src/intelligence/swarm/agents/skeptic_agent.py | `{hmm_regime}.{tf}` |
| 7 | `swarm_correlation` | src/intelligence/swarm/agents/correlation_agent.py | `{hmm_regime}.{tf}` |
| 8 | `swarm_volume` | src/intelligence/swarm/agents/volume_agent.py | `{hmm_regime}.{tf}` |

The recorder is **not** instantiated inside each transform — it is constructed once per pipeline run and passed in. If `recorder` is None, the call is a no-op (safe for tests without DB).

### New Kafka topics (LOCKED)

Add to `src/core/stream_keys.py`:

```python
def topic_transform_graduation(env_name: str) -> str:
    """Graduation evaluation results from GraduationComputeAgent."""
    return f"{env_prefix(env_name)}intelligence.transform.graduation"

def topic_transform_graduation_dlq(env_name: str) -> str:
    """DLQ for graduation writer."""
    return f"{env_prefix(env_name)}intelligence.transform.graduation.dlq"
```

Also add to `production/scripts/kafka_init_topics.py` with `_BUFFER_MS` retention (1 day — graduation results are persisted to DB).

### GraduationComputeAgent (LOCKED)

**File:** `services/graduation_compute_agent.py`
**Systemd unit:** `indicagent-graduation-compute.service`
**Consumer group:** `graduation_compute_group`
**Metrics port:** 9135
**Input topic:** `topic_lifecycle_transitions` (existing, different consumer group)
**Output topic:** `topic_transform_graduation`
**DLQ:** `topic_transform_graduation_dlq`

Internal logic:
1. On startup: query `transform_graduation` for last `evaluated_at` per (transform_id, segment_key). Count resolved signals since then. Set initial counters.
2. On each consumed EXIT transition: parse `signal_id`, query `signal_transform_log` for all transform rows for that signal_id, increment in-memory counters per (transform_id, segment_key). If any counter >= 20: trigger evaluation.
3. Evaluation: query `signal_transform_log JOIN signal_ledger` for rolling 90d for that (transform_id, segment_key). Run `evaluate_all()`. Publish GraduationResult to Kafka. Reset counter.
4. On teardown: flush pending evaluations.

State recovery: re-counts from `transform_graduation.evaluated_at` on restart. In-memory counters are ephemeral.

### GraduationWriterAgent (LOCKED)

**File:** `services/graduation_writer_agent.py`
**Systemd unit:** `indicagent-graduation-writer.service`
**Consumer group:** `graduation_writer_group`
**Metrics port:** 9136
**Input topic:** `topic_transform_graduation`
**DLQ:** `topic_transform_graduation_dlq`

Follows BaseWriterAgent pattern: consume → parse → buffer → batch upsert to `transform_graduation`. No compute — pure persistence.

### Systemd unit files (LOCKED)

**graduation-compute.service:** `services/graduation-compute.service`
**graduation-writer.service:** `services/graduation-writer.service`

Follow the same pattern as existing always-on service units. Both need `PYTHONUNBUFFERED=1` and standard `indicagent` environment.

### GraduationResult payload schema (LOCKED)

```python
{
    "transform_id": str,
    "transform_version": str,
    "segment_key": str,
    "n": int,
    "spearman_rho": float,
    "spearman_p": float,
    "calibration_max_error": float,
    "cvar_bottom_decile": float,
    "mde": float,
    "val_rho": float,
    "overfitting_risk": bool,
    "sharpe_delta": float,
    "is_graduated": bool,
    "evaluated_at": str,  # UTC ISO-8601
    "expires_at": str     # UTC ISO-8601, evaluated_at + 90 days
}
```

### Claude's Discretion

- How TransformRecorder is threaded through the intelligence_pipeline_agent to the pipeline stages (constructor injection vs. context object vs. module-level singleton)
- Whether GraduationComputeAgent queries signal_transform_log per-signal on every EXIT or batches the lookups
- Error handling for signals with no rows in signal_transform_log (e.g., signals from before this phase deployed)
- Whether to create a CLI for manually triggering graduation evaluation (useful during initial data collection)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Transform Pipeline
- `src/intelligence/pipeline/quality_gate.py` — hurst_quality and drift_penalty transforms
- `src/intelligence/pipeline/regime_gate.py` — regime_gate transform
- `src/intelligence/pipeline/tod_adjuster.py` — TOD transform
- `src/intelligence/pipeline/calibrator.py` — isotonic calibration transform
- `src/intelligence/pipeline/ranker.py` — performance weighting transform
- `src/intelligence/swarm/agents/skeptic_agent.py` — swarm_skeptic transform
- `src/intelligence/swarm/agents/correlation_agent.py` — swarm_correlation transform
- `src/intelligence/swarm/agents/volume_agent.py` — swarm_volume transform

### Pattern: ShadowRecorder (existing batch writer to copy)
- `src/core/ml/shadow.py` — TransformRecorder should follow this pattern exactly

### Existing Scripts (to be refactored)
- `scripts/validate_skeptic.py` — becomes thin CLI wrapper over graduation.py

### Infrastructure Patterns
- `src/core/stream_keys.py` — add topic_transform_graduation() and DLQ function
- `production/scripts/kafka_init_topics.py` — add new topics with retention
- `production/migrations/068_gap_retry_tracking.sql` — last migration (next = 069)

### Service Patterns
- Any existing always-on agent service file in `services/` — follow for GraduationComputeAgent/WriterAgent structure
- `src/core/service_utils.py` — `setup_service_logging()`, standard service setup

### Design Spec (source of truth)
- `docs/plans/2026-04-24-signal-transform-log-design.md` — full schema, architecture, graduation protocol

</canonical_refs>

<specifics>
## Specific Ideas

- `segment_key` for global transforms (ones that don't vary by regime/tf): `"__global__"` literal string
- `expires_at` = `evaluated_at + 90 days` — hardcoded expiry, graduation must re-prove each quarter
- Graduation threshold: 20 new resolved signals before re-evaluation (in-memory counter, not persistent)
- Rolling window: 90 days of signal_transform_log JOIN signal_ledger for each evaluation query
- Walk-forward split: 70% train / 30% validate (temporal split — no shuffling)
- EVAL_RESOLUTION_THRESHOLD = 20 lives in graduation.py as a module constant (importable by compute agent)
- The `is_shadow` column on signal_transform_log is TRUE by default for all transforms at Phase 1 — nothing graduates yet, this is the data collection phase
- Research queries from the design spec (section "What This Enables") are not deliverables — they're examples of what the schema enables post-deployment

</specifics>

<deferred>
## Deferred Ideas

- Phase 2: compose_confidence() wiring — replace in-place confidence mutation (requires 30-day data gate)
- Phase 3: alpha_multiplier_shadow absorption — swarm agents write to signal_transform_log instead (after graduation gates pass)
- Phase 4: Drop deprecated columns (calibrated_confidence, raw_cis_score, filtered_cis_score from signal_ledger, drop alpha_multiplier_shadow table)
- CLI for manually triggering graduation evaluation (useful during initial data collection, not required for Phase 1)
- Dashboard view for transform graduation status

</deferred>

---

*Phase: 72-signal-transform-log-unified-alpha-modifier-architecture-add*
*Context gathered: 2026-04-24 via PRD Express Path (docs/plans/2026-04-24-signal-transform-log-design.md)*
