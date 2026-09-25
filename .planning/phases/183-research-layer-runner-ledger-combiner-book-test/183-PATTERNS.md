# Phase 183: Research layer: runner, ledger, combiner, book test - Pattern Map

**Mapped:** 2026-09-25
**Files analyzed:** 24 (10 new src/scripts modules, 2 spec YAML, 1 migration, 13 test files; portfolio.py and evaluate.py modified in place)
**Analogs found:** 22 / 24 (2 have no close analog, listed at the end)

RESEARCH.md already contains exact target-file sketches (code examples 1-4, patterns 1-9) with
line-cited seams in `evaluate.py`/`portfolio.py`. This file maps each target file to its closest
existing **analog** elsewhere in the codebase (schema/migration precedent, sole-writer test
precedent, CLI precedent) so new code matches house style, not just the design doc's sketch.

## File Classification

| New/Modified file | Role | Data flow | Closest analog | Match quality |
|---|---|---|---|---|
| `production/migrations/366_research_run_ledger.sql` | migration | CRUD (append-only) | `production/migrations/357_concept_evaluation_ledger.sql` (append-only ledger DDL) + `283_concept_registry_feature_domain_schema.sql` (advisory-lock contract, trigger style) + `340_ic_engine_streaming_correlation_apr_key.sql` (APR seed) | exact (composite) |
| `src/intelligence/research/spec.py` | utility (parser/schema) | transform | `scripts/analysis/sleeve_walk_forward/config.py` (frozen dataclass config) + RESEARCH.md code example 1 | role-match |
| `src/intelligence/research/runner.py` | controller/orchestrator | event-driven (pipeline) | `scripts/analysis/sleeve_walk_forward/run.py` (staged CLI harness, git/content-hash checks) | exact |
| `src/intelligence/research/ledger.py` | service (sole DB writer) | CRUD | `src/core/database_manager.py` (`connect_with_codecs`) + migration 283's advisory-lock contract + `tests/integration/test_concept_parent_lineage.py`'s insert/cleanup pattern | exact |
| `src/intelligence/research/combiner.py` | service (compute) | transform (batch) | `src/intelligence/research/portfolio.py` (`plan_covariance`/`_calibrate`, walk-forward refit over rows) | exact |
| `src/intelligence/research/book.py` | service (compute) | transform (batch) | `src/intelligence/research/evaluate.py` (`evaluate()`, `Construction` protocol) + `portfolio.py` (`fixed_sign_returns`) | exact |
| `src/intelligence/research/synthetic.py` | utility (generator) | transform | `scripts/analysis/sleeve_walk_forward/synthetic.py` (V2/V3 planting shape only, per D-04/research "don't hand-roll") | role-match |
| `src/intelligence/research/families/__init__.py` | module init | n/a | `src/intelligence/research/__init__.py` | exact |
| `src/intelligence/research/families/intraday_periodicity.py` | model (signal functions) | transform | `src/intelligence/research/signals.py` (`SignalSource` dataclass, dotted-path/`evaluate_kwargs` shape) + `factors.py` (`residual_returns`) | exact |
| `scripts/research/run_spec.py` | CLI entrypoint | request-response (one-shot) | `scripts/analysis/sleeve_walk_forward/run.py` (DSN/Settings wiring, `make_worker_pool`, `_code_key`/`_git`) | exact |
| `research/specs/family1_intraday_periodicity.yaml` | config/data | n/a | `scripts/analysis/sleeve_walk_forward/config.py` (`DEFAULT_CONFIG` values, as the source of pinned constants) | partial (no YAML analog exists; values-only match) |
| `research/specs/book_v1.yaml` | config/data | n/a | same as above | partial |
| `src/intelligence/research/portfolio.py` (add `rank_vol_neutral_returns`, R1) | service (compute), modified | transform | same file's `fixed_sign_returns` (lines 184-200) | exact |
| `src/intelligence/research/evaluate.py` (add `session_scoring`, R2) | service (compute), modified | transform | same file's `evaluate()`/`_run_shifts` (lines 177-292) | exact |
| `tests/unit/research/test_spec.py` | test | n/a | `tests/unit/research/test_factors.py` (synthetic-panel unit test style) | role-match |
| `tests/unit/research/test_runner_git.py` | test | n/a | none in-repo for git-plumbing-in-tmp_path; pattern verified fresh this research session (RESEARCH.md pattern 5) | no analog |
| `tests/unit/research/test_runner_order.py` | test | n/a | `tests/unit/research/test_evaluate_intraday.py` (fake/synthetic harness style) | role-match |
| `tests/unit/research/test_runner_evidence.py` | test | n/a | same | role-match |
| `tests/unit/research/test_combiner.py` | test | n/a | `tests/unit/research/test_portfolio.py` (slow-loop reference vs. vectorized implementation) | exact |
| `tests/unit/research/test_book.py` | test | n/a | `tests/unit/research/test_evaluate_intraday.py` | exact |
| `tests/unit/research/test_power.py` | test | n/a | none (new statistical procedure); reuse pytest style from `test_evaluate.py` | role-match |
| `tests/unit/research/test_synthetic.py` | test | n/a | `scripts/analysis/sleeve_walk_forward/synthetic.py`'s own test (if any) or `test_panel.py` synthetic-generator style | role-match |
| `tests/unit/research/test_families_intraday.py` | test | n/a | `tests/unit/research/test_factors.py` + `test_guards.py` (synthetic `FactorSpec`, `run_guards` on synthetic panel) | exact |
| `tests/unit/research/test_ledger_sole_writer.py` | test (repo-grep CI guard) | n/a | `tests/unit/test_market_data_ohlcv_boundary.py` (allow-list grep-as-test pattern via `_source_grep_helpers.py`) | exact |
| `tests/unit/research/test_portfolio_r1.py` | test | n/a | `tests/unit/research/test_portfolio.py` | exact |
| `tests/unit/research/test_evaluate_session_scoring.py` | test | n/a | `tests/unit/research/test_evaluate_intraday.py` | exact |
| `tests/integration/test_research_ledger.py` | test (integration, DB) | CRUD | `tests/integration/test_concept_parent_lineage.py` (fixture/cleanup/trigger-assertion pattern) | exact |

## Pattern Assignments

### `production/migrations/366_research_run_ledger.sql` (migration)

**Analogs:** `production/migrations/357_concept_evaluation_ledger.sql` (append-only ledger shape),
`production/migrations/283_concept_registry_feature_domain_schema.sql` (advisory-lock contract
language, trigger-comment style), `production/migrations/340_ic_engine_streaming_correlation_apr_key.sql`
(APR seed idiom), `production/migrations/329_concept_registry_construction_domain.sql` (domain
CHECK-widening + `ON CONFLICT (domain, name) DO NOTHING` identity-row idiom).

**Header/rationale comment style** (357, lines 1-23 and 283, lines 1-79): a multi-paragraph
`-- ` comment block before `BEGIN;` stating: what the table is, why it deviates from an existing
sibling mechanism (357's `concept_evaluation` explicitly is not reused, per D-06 — say so with
the same candor 357 uses for why it replaced `concept_gate` counters), idempotency claim, and
whether it is a hypertable (357: "Plain table... about 300 rows"; 366's own comment should state
row-count order of magnitude and "Not a hypertable; no VACUUM step" the same way 340 and 357 both
do it explicitly).

**Table DDL pattern** (357 lines 27-48):
```sql
CREATE TABLE IF NOT EXISTS concept_evaluation (
    concept_id       uuid        NOT NULL REFERENCES concept_registry (concept_id),
    ...
    PRIMARY KEY (concept_id, window_end, evidence_key),
    CONSTRAINT concept_evaluation_domain_check
        CHECK (domain = ANY (ARRAY['feature', 'ensemble_strategy', 'construction'])),
    ...
);
CREATE INDEX IF NOT EXISTS concept_evaluation_domain_window_idx
    ON concept_evaluation (domain, window_end);
COMMENT ON TABLE concept_evaluation IS '...';
```
`research_run`'s DDL sketch is already fully worked out in RESEARCH.md code example 4 (`run_id
uuid PRIMARY KEY DEFAULT gen_random_uuid()`, `status` CHECK, partial unique index on
`(spec_hash, concept_id) WHERE mode = 'real'`, budget index). Follow 357's naming convention for
indexes (`<table>_<purpose>_idx`) and constraints (`<table>_<column>_check`).

**Advisory-lock / append-only contract comment** (283 lines 24-34, verbatim pattern to imitate for
`research_run`'s writer contract):
```sql
-- CONTRACT for any future writer: any component that writes concept_parent outside a
-- single-transaction seed MUST take pg_advisory_xact_lock() on a fixed key covering the table
-- first, or the cycle guard is best-effort for that writer.
```
`ledger.py`'s header comment and this migration's header should both restate the equivalent
contract for `research_run` + identity rows + `concept_parent` edges (D-05/D-07/D-08, pitfall 9).

**Trigger pattern to imitate** (283 lines 112-153, `fn_concept_parent_cycle_guard` +
`trg_concept_parent_cycle_guard`): `CREATE OR REPLACE FUNCTION ... RETURNS TRIGGER AS $$ ... RAISE
EXCEPTION ... USING ERRCODE = 'check_violation'; ... $$ LANGUAGE plpgsql;` followed by `DROP
TRIGGER IF EXISTS ...` then `CREATE TRIGGER ... BEFORE INSERT OR UPDATE ... FOR EACH ROW EXECUTE
FUNCTION ...`. Use the same shape for the terminal-once trigger (`BEFORE UPDATE`, reject any OLD
row whose status is not `'started'`, reject any column change outside
`status`/`snapshot_hash`(NULL→value only)/`evidence`/`finished_at`) and the `BEFORE DELETE OR
TRUNCATE` guard (raise unconditionally, same `RAISE EXCEPTION ... USING ERRCODE` idiom).

**APR seed pattern** (340, full file, lines 35-58 — canonical idempotent seed idiom):
```sql
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'infra.ic_engine.corr_row_block',
    'int',
    '1000000',
    1000, NULL,
    '[initial_estimate] ... Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('infra.ic_engine.corr_row_block', '1000000', 1)
ON CONFLICT (config_key) DO NOTHING;
```
Apply this exact two-INSERT shape for each of `alpha.research.vintage_id` (string
`'vintage_1'`), `alpha.research.budget_m` (int 30), `alpha.research.screen_alpha` (float 0.05),
`infra.research_runner.workers` (int, matching `infra.ic_engine.workers`'s live value 8 per
CLAUDE.md). Description tag per D-08: `[user_preference]` + "a change needs a
methodology-change-ledger entry" (not `[initial_estimate]` — these are locked framework
constants, not throughput knobs).

**Identity-row seeding idiom** (329, full file — `ON CONFLICT (domain, name) DO NOTHING` insert of
a `concept_registry` row with `domain`, `name`, `description`, `status`, `enabled`, `metadata`
jsonb via `jsonb_build_object(...)`): this is the shape `ledger.start_run`'s identity-row upsert
should mirror in Python (`INSERT ... ON CONFLICT (domain, name) DO NOTHING`), not a shape the
migration itself needs (166 seeds no `concept_registry` rows — D-06 says the runner does that at
first real run, not migration time — unlike 329 which seeds a row directly in SQL).

---

### `src/intelligence/research/ledger.py` (service, sole DB writer)

**Analog:** `src/core/database_manager.py` (`connect_with_codecs`) for the connection; migration
283's advisory-lock contract for the transaction shape; `tests/integration/test_concept_parent_lineage.py`
for how a caller of this module will be tested.

**Bare-connection-with-codecs pattern** (`database_manager.py` lines 33-41):
```python
async def connect_with_codecs(database_url: str) -> asyncpg.Connection:
    """Bare `asyncpg.connect()` with JSONB codecs registered (todo 187) -- for short-lived,
    read-only connections (evaluation/reporting branches) that don't warrant a full pool.
    A bare `asyncpg.connect()` has no codec, so jsonb columns come back as raw JSON text
    instead of `dict`; this is the one place that fact needs handling instead of every
    caller remembering to call `_setup_codecs` itself."""
    conn = await asyncpg.connect(database_url)
    await _setup_codecs(conn)
    return conn
```
`ledger.py`'s `start_run`/`finish_run` take a connection from this function (CLAUDE.md asyncpg
rule; per RESEARCH.md "don't hand-roll" table, use `connect_with_codecs`, not a bespoke codec
setup or a pool for a short-lived write).

**Transaction + advisory lock shape** (pattern to write, no single exact precedent uses
`pg_advisory_xact_lock` for a lineage-writing transaction yet, but 283's contract comment plus
asyncpg's plain transaction API give the shape):
```python
async with conn.transaction():
    await conn.execute("SELECT pg_advisory_xact_lock($1)", _RESEARCH_LEDGER_LOCK_KEY)
    # refuse if a real-mode row exists for spec_hash (SELECT ... FOR the check, raise before INSERT)
    # for book_test: SELECT count(*) ... WHERE kind='book_test' AND vintage=$1
    #                AND status NOT IN ('refused','guard_failed')
    await conn.execute(
        "INSERT INTO concept_registry (domain, name, description, status, enabled, metadata) "
        "VALUES ('construction', $1, $2, 'candidate', false, $3::jsonb) "
        "ON CONFLICT (domain, name) DO NOTHING",
        name, description, metadata,
    )
    await conn.execute(
        "INSERT INTO concept_parent (child_concept_id, parent_concept_id) VALUES ($1, $2) "
        "ON CONFLICT DO NOTHING",
        child_id, parent_id,
    )
    run_id = await conn.fetchval(
        "INSERT INTO research_run (...) VALUES (...) RETURNING run_id", ...
    )
```
Column set and CHECK values: RESEARCH.md code example 4 (migration 366 DDL sketch) is the
authoritative source — copy the column list from there, not from any existing table.

**Cleanup/test-fixture pattern for the caller's integration test**
(`test_concept_parent_lineage.py` lines 46-86, `_TrackedConnection` + fixture teardown):
```python
class _TrackedConnection:
    """asyncpg.Connection has __slots__ (no ad-hoc attributes), so created concept_ids are
    tracked here instead of on the connection object itself."""
    def __init__(self, connection: asyncpg.Connection) -> None:
        self.connection = connection
        self.created_concept_ids: list[str] = []
    def __getattr__(self, item):
        return getattr(self.connection, item)

@pytest.fixture
async def conn() -> AsyncIterator[_TrackedConnection]:
    connection = await asyncpg.connect(_TEST_DB_URL)
    tracked = _TrackedConnection(connection)
    try:
        yield tracked
    finally:
        created_concept_ids = tracked.created_concept_ids
        if created_concept_ids:
            await connection.execute("DELETE FROM concept_parent WHERE ...")
            await connection.execute("DELETE FROM concept_transition_log WHERE ...")
            await connection.execute("DELETE FROM concept_gate WHERE ...")
            await connection.execute("DELETE FROM concept_registry WHERE ...")
        await connection.close()
```
`test_research_ledger.py` should follow this exact shape, additionally deleting created
`research_run` rows (no FK cascade from `concept_registry`, same as `concept_parent`) and using
unique names (`f"_p183_{uuid4().hex[:8]}"`) per that file's own convention (`_name()` helper,
line 42-43).

**Trigger-assertion test pattern** (`test_concept_parent_lineage.py` lines 138-152,
`test_cycle_rejected`):
```python
with pytest.raises(asyncpg.exceptions.PostgresError, match="concept_parent cycle rejected"):
    await _link(conn, child=concept_a, parent=concept_b)
with pytest.raises(asyncpg.exceptions.CheckViolationError):
    await _link(conn, child=concept_a, parent=concept_a)
```
Use the same `pytest.raises(asyncpg.exceptions.PostgresError, match="...")` idiom to assert the
terminal-once trigger rejects a second status transition and the DELETE/TRUNCATE guard rejects a
delete, plus (per lines 248-277, `test_cycle_rejected_on_update_path`) a "surviving state after a
rejected write" assertion — confirm a `research_run` row's `status` is unchanged after a rejected
second `UPDATE`.

---

### `src/intelligence/research/spec.py` (utility, parser/schema)

**Analog:** RESEARCH.md code example 1 is the primary source (already a concrete sketch, canonical
JSON + sha256); `scripts/analysis/sleeve_walk_forward/config.py`'s `HarnessConfig` frozen
dataclass shows the project's convention for "one reviewed place for constants a run depends on."

**Canonical hash pattern** (RESEARCH.md code example 1, verbatim):
```python
text = subprocess.run(["git", "-C", root, "show", f"HEAD:{rel}"], check=True,
                      capture_output=True, text=True).stdout
model = FamilySpec.model_validate(yaml.safe_load(text))           # strict, extra="forbid"
canonical = json.dumps(model.model_dump(mode="json"), sort_keys=True,
                       separators=(",", ":"), ensure_ascii=False, allow_nan=False)
spec_hash = hashlib.sha256(canonical.encode()).hexdigest()
```
Pydantic model: `model_config = ConfigDict(extra="forbid", strict=True)` (RESEARCH.md pitfall 1 —
never `yaml.load`, quote dates as strings, write floats with a decimal point).

---

### `src/intelligence/research/runner.py` (controller/orchestrator)

**Analog:** `scripts/analysis/sleeve_walk_forward/run.py` — closest existing staged-pipeline CLI
with git-commit/content-hash discipline, though it lives in `scripts/` (services-adjacent) while
the new runner must live in `src/intelligence/research/` and must NOT import `services.*`
(pitfall 10; Ring rule). Use it for shape only, not for imports.

**Git/commit provenance pattern** (`run.py` lines 84-90):
```python
def _git() -> tuple[str, bool]:
    """HEAD and whether the tree is dirty, recorded for the section 12 addendum."""
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    status = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
    )
    return head.stdout.strip(), bool(status.stdout.strip())
```
`runner.py`'s refusal gate needs the more granular checks in RESEARCH.md pattern 5
(`git cat-file -e HEAD:<spec>`, `git diff --quiet HEAD -- <spec>`,
`git status --porcelain=v1 --untracked-files=all -- <paths>`) rather than this file's blunt
whole-tree `git status --porcelain`; `run.py`'s `_git()` is the wrong precedent to copy literally
for D-02's refusal semantics — RESEARCH.md pattern 5 is more precise. Copy `run.py`'s subprocess
style (list-args, `check=True`, `capture_output=True, text=True`, `.stdout.strip()`), not its
scope.

**Code-content-key pattern** (`run.py` lines 65-81) — do NOT reuse `_checkpoint_content_key` from
`services/ic_engine.py` (pitfall 10, ~300 MB import drag, Ring violation); instead hash only
`sys.modules` files under `src/`, `research/specs/`, `scripts/research/` after the family modules
import, per RESEARCH.md pattern 5's recommendation citing `services/ic_engine.py:5376-5415`'s
approach as the algorithm to imitate (not the module to import).

---

### `src/intelligence/research/combiner.py` (S7 walk-forward ridge)

**Analog:** `src/intelligence/research/portfolio.py`'s calibration refit loop
(`plan_covariance`/`_arm_blocks`/`_calibrate`, lines 80-256) — same walk-forward-refit-over-rows
shape, same "compute once, reuse across shifts" discipline for anything that does not depend on
alpha.

**Refit-loop pattern** (`portfolio.py` lines 80-103, `plan_covariance`):
```python
def plan_covariance(closes, cfg, mv_condition_max, embargo=DAILY_EMBARGO):
    n = closes.shape[0]
    log_ret = np.log(closes[1:] / closes[:-1])
    positions = np.arange(cfg.warmup_sessions, n, cfg.calibration_refit_sessions)
    ...
    for p in positions:
        b = p - embargo
        first = max(1, b - cfg.warmup_sessions + 1)
        window = pd.DataFrame(log_ret[first - 1 : b], index=range(first, b + 1))
        cov, kept = instrument_covariance(window, min_coverage_fraction=cfg.coverage_fraction)
        ...
```
`combiner.py`'s `walk_forward_ridge` follows the same shape (window ending at `p - embargo`,
refit every `cadence` rows, hold state between refits) but per RESEARCH.md code example 2 uses
closed-form moment prefix sums rather than a Python-loop `instrument_covariance` call — this is a
deliberate deviation from the portfolio.py precedent for performance (measured 0.62s vs 2.3s,
RESEARCH.md measurements table), not a different design philosophy.

**Ridge from moments** (RESEARCH.md code example 2, verbatim):
```python
ok = np.isfinite(y) & np.isfinite(X).all(axis=2)                    # complete cases only
c, sx, sxx, sxy, sy = (P[hi] - P[lo] for P in prefix)                # training window
mu = sx / c
cov = sxx / c - np.outer(mu, mu); sd = np.sqrt(np.diag(cov))
b = np.linalg.solve(cov / np.outer(sd, sd) + lam * np.eye(K),       # standardized in-fold
                    (sxy / c - mu * (sy / c)) / sd)
combined[p:q] = ((X[p:q] - mu) / sd) @ b                             # NaN where a member is NaN
```

---

### `src/intelligence/research/book.py` (S8 book test + power estimator)

**Analog:** `src/intelligence/research/evaluate.py`'s `Construction` protocol and `evaluate()`
(lines 48, 198-292); `portfolio.py`'s `fixed_sign_returns` for the R1-in-a-construction call shape.

**Construction-wraps-combiner pattern** (RESEARCH.md pattern 4, verbatim sketch):
```python
def book_returns(alpha_flat, fwd_ret, plan, *, n_members, ridge, vol, direction, coverage_floor):
    n, mk = alpha_flat.shape
    stack = alpha_flat.reshape(n, mk // n_members, n_members)  # a view, no copy
    combined = walk_forward_ridge(stack, fwd_ret, ridge)        # S7, target = fwd_ret
    return rank_vol_neutral_returns(combined, fwd_ret, plan, vol=vol,
                                    direction=direction, coverage_floor=coverage_floor)

construction = functools.partial(book_returns, n_members=K, ridge=spec.ridge, vol=vol, ...)
res = evaluate(stack.reshape(n, m * K), fwd_resid, panel.close, panel.timestamps, cfg,
               construction=construction, memory=book_memory_rows, embargo=fwd_span(2),
               bars_per_session=26, valid=panel.valid, session_scoring=True,
               workers=w, pool_factory=pool, mv_condition_max=..., ic_shrinkage_k=...)
```
Existing `evaluate()` call sites to model the invocation on: `evaluate.py` lines 198-292 (the
function itself, showing every kwarg's meaning) and `signals.py`'s `SignalSource.evaluate_kwargs`
(lines 35-41) for how a construction's `memory`/`embargo` are packaged for the caller.

**Power estimator** (RESEARCH.md code example 3, verbatim — `replicate_passes` Besag-Clifford
early stop): no in-repo analog exists for sequential-stopping Monte Carlo; this is new procedure,
built per RESEARCH.md pattern 9, not copied from an analog.

---

### `src/intelligence/research/synthetic.py` (residual-space generator)

**Analog:** `scripts/analysis/sleeve_walk_forward/synthetic.py` — shape only (per RESEARCH.md
"don't hand-roll" table and "Anti-patterns": this module is 1d-only, equicorrelated, subsamples
shifts, and is the frozen record of phase 179/181 verdicts — NOT promotable). Reuse only the AR(1)
persistence idea; do not import from it (D-16 bit-identity risk) and do not copy its shift-set
subsampling (RESEARCH.md pattern 9 explicitly rejects that as inexact).

**What to reuse:** the general shape "planted signal = idiosyncratic noise + AR(1)-style
persistence term, cross-sectionally demeaned" — read `scripts/analysis/sleeve_walk_forward/synthetic.py`
lines 40-74 for the pattern, then write a new residual-space, low-rank-common-component version
per RESEARCH.md pattern 8 (participation ratio ~60, same-slot persistence out to 40 days).

---

### `src/intelligence/research/families/intraday_periodicity.py` (P1-P4 signal functions)

**Analog:** `src/intelligence/research/signals.py`'s `SignalSource` dataclass (dotted-path /
`evaluate_kwargs` shape) and `factors.py`'s `residual_returns` (the S1 call the family composes
around, per RESEARCH.md pattern 3).

**SignalSource shape to match** (`signals.py`, full file, lines 26-41):
```python
@dataclasses.dataclass(frozen=True)
class SignalSource:
    compute: Callable[[Panel], np.ndarray]  # panel -> alpha [n, m]
    memory: int
    direction: float
    n_tested: int
    horizon: int = 1
    arm: str = FIXED_SIGN_ARM

    def evaluate_kwargs(self) -> dict[str, Any]:
        return {
            "construction": functools.partial(fixed_sign_returns, direction=self.direction),
            "memory": self.memory + fwd_span(self.horizon),
            "embargo": fwd_span(self.horizon),
        }
```
Per RESEARCH.md pattern 3, family members should be pure functions
`same_slot_mean(resid_bar_returns, *, bars_per_session, window_sessions,
min_finite_fraction) -> alpha [n, m]`, with a thin `lambda p: member(residual_returns(bar_returns(p),
bars_per_session=bps, spec=S).residual)` composition used only for the synthetic-panel guard tests
— this composition pattern already exists in `tests/unit/research/test_factors.py` (read it for
the exact composition idiom before writing the new test file).

**Target residualization call** (`factors.py` `residual_returns`, lines 261-307 signature and
lines 265-266): `residual_returns(fwd, bars_per_session=26, horizon=2)` gives `fwd_span(2) = 3`
lag; same function, different `horizon` for bar-return residualization (`horizon=None`).

---

### `src/intelligence/research/portfolio.py` — add `rank_vol_neutral_returns` (R1)

**Analog:** same file's `fixed_sign_returns` (lines 184-200) — the construction it sits beside;
`_normalize` (lines 203-206) is the existing row-wise-sum-to-1 helper to reuse for the
positive/negative-side scaling to ±0.5.

```python
def fixed_sign_returns(
    alpha: np.ndarray, fwd_ret: np.ndarray, plan: CovariancePlan, *, direction: float
) -> dict[str, np.ndarray]:
    n = alpha.shape[0]
    out = np.full(n, np.nan)
    bounds = np.append(plan.refit_positions, n)
    state = None
    for k, p in enumerate(plan.refit_positions):
        if plan.symbol_idx[k] is not None:
            state = (plan.symbol_idx[k], plan.sigma[k])
        if state is None:
            continue
        idx, sig = state
        block = slice(p, bounds[k + 1])
        raw = direction * np.sign(np.nan_to_num(alpha[block][:, idx])) / sig
        out[block] = (_normalize(raw) * np.nan_to_num(fwd_ret[block][:, idx])).sum(axis=1)
    return {FIXED_SIGN_ARM: out}
```
`rank_vol_neutral_returns` follows the same `{arm_name: per-row-returns}` return contract and the
same "ignore `plan`, take an injected precomputed array" shape RESEARCH.md pattern 1 specifies
(precomputed `vol` array plays the role `plan.sigma` plays here, but per pitfall 3 must NOT come
from `CovariancePlan.sigma`/`instrument_covariance` — build it directly from trailing residual
bar-return stdev). Must be `functools.partial`-bindable (picklable) exactly like
`fixed_sign_returns` is bound in `signals.py` line 38.

---

### `src/intelligence/research/evaluate.py` — add `session_scoring` kwarg (R2)

**Analog:** same file's `evaluate()` (lines 198-292), specifically the three sites RESEARCH.md
pattern 2 names: observed Sharpe (lines 231-232), `_run_shifts` (lines 177-195, esp. 190-194), and
the readouts block (lines 255-291, esp. `periods_per_year` at line 221 and `rcfg.bootstrap_mean_block`
at line 277).

```python
def evaluate(
    alpha, fwd_ret, closes, dates, cfg, *,
    mv_condition_max, ic_shrinkage_k, shifts=None, workers=1, construction=None,
    memory=0, bars_per_session=1, valid=None, embargo=DAILY_EMBARGO, pool_factory=None,
) -> EvaluationResult:
    ...
    periods_per_year = SESSIONS_PER_YEAR * bars_per_session   # line 221 -- must become 252 w/ R2
    ...
    excess_ci=np.array([_bootstrap_sharpe_ci(row[trade], rcfg.bootstrap_mean_block, ...)  # line 277
                        for row in excess_daily]),
```
Add `session_scoring: bool = False` as a new keyword to `evaluate()` itself — NOT to
`EvaluationConfig` (anti-pattern explicitly called out: breaks the field-classification test
`tests/unit/research/test_evaluate_intraday.py:57-60` and the frozen `HarnessConfig`). One helper
converts `(series, trade_mask, dates)` to per-session form and is threaded through all three sites
above (RESEARCH.md pattern 2 / pitfall 4).

---

## Shared Patterns

### Sole-writer repo-grep CI guard (D-05)
**Source:** `tests/unit/_source_grep_helpers.py` (full file, 69 lines) +
`tests/unit/test_market_data_ohlcv_boundary.py` (full file, 153 lines) as the worked example.
**Apply to:** `tests/unit/research/test_ledger_sole_writer.py`.
```python
from tests.unit._source_grep_helpers import (
    assert_allow_list_has_no_stale_entries,
    assert_no_unlisted_references,
    find_pattern_references,
)

_ALLOW_LIST: dict[str, str] = {
    "production/migrations/329_concept_registry_construction_domain.sql": (
        "PERMANENT: legacy construction-domain verdict row inserted directly by the migration, "
        "before ledger.py existed (phase 183 predates this sole-writer rule). ..."
    ),
    # ... 330-335 per RESEARCH.md "phase requirements" row D-05: "legacy migrations 329-335 need
    # allow-list entries"
}

def test_every_construction_concept_registry_write_is_on_the_allow_list():
    hits = find_pattern_references(_REPO_ROOT, ("services", "src", "scripts", "production"),
                                    _PATTERN, file_globs=("*.py", "*.sql"))
    assert_no_unlisted_references(hits, _ALLOW_LIST, what="...", remedy="...")

def test_allow_list_has_no_stale_entries():
    assert_allow_list_has_no_stale_entries(hits, _ALLOW_LIST)
```
Confirm the exact set of legacy migrations 329-335 that insert `domain='construction'` rows
before writing the allow-list (grep `production/migrations/33{0,1,2,3,4,5}_*.sql` for
`domain.*construction` or `'construction'`).

### asyncpg jsonb codec (all DB-writing new modules)
**Source:** `src/core/database_manager.py` lines 19-41.
**Apply to:** `ledger.py` (write connection), `tests/integration/test_research_ledger.py` (bare
`asyncpg.connect()` is fine there only because `evidence` jsonb round-trips aren't asserted
row-for-row the way `ledger.py`'s write path needs; if the test reads `evidence` back and asserts
on nested dict structure, it must also use `connect_with_codecs`, not a bare `asyncpg.connect()` —
`test_concept_parent_lineage.py` gets away with bare `asyncpg.connect()` because it never reads a
jsonb column, `ledger.py` and its integration test do).

### Advisory-lock writer contract (D-05/D-07/D-08, pitfall 9)
**Source:** `production/migrations/283_concept_registry_feature_domain_schema.sql` lines 24-34
and 138-146 (the contract stated twice — in the migration header and in the trigger function's
`COMMENT ON FUNCTION`).
**Apply to:** migration 366's header comment, `ledger.py`'s module docstring, and
`ledger.start_run`'s implementation (`SELECT pg_advisory_xact_lock($1)` as the first statement
inside the transaction, before any read of `research_run`/`concept_parent`/`concept_registry`).

### Worker pool injection (D-17, pitfall 10)
**Source:** `services/_batch_utils.py` `make_worker_pool` (`ProcessPoolExecutor` +
`limit_blas_threads` initializer) + `src/intelligence/research/evaluate.py`'s `pool_factory`
parameter (lines 214, 242-248) + `scripts/analysis/sleeve_walk_forward/run.py` line 54's import
of `make_worker_pool` from `services._batch_utils`.
**Apply to:** `scripts/research/run_spec.py` only (the CLI, which may import `services.*`); never
`src/intelligence/research/*.py` (Ring 1, must not import `services`) — `combiner.py`/`book.py`
receive an already-constructed pool/`pool_factory` the same way `evaluate()` already does, they
never construct one themselves.

### YAML strict-schema parsing (D-01, pitfall 1)
**Source:** RESEARCH.md pitfall 1 + code example 1 (no in-repo YAML+pydantic analog exists yet;
`src/core/ai/registry.py` imports `yaml` but not through a strict pydantic schema — check it only
for the bare `yaml.safe_load` import idiom, not for schema validation style).
**Apply to:** `spec.py`'s `FamilySpec`/`BookSpec` pydantic models: `model_config =
ConfigDict(extra="forbid", strict=True)`.

## No Analog Found

| File | Role | Data flow | Reason |
|---|---|---|---|
| `tests/unit/research/test_runner_git.py` | test | n/a | No existing test exercises git plumbing (`cat-file -e`, `diff --quiet`, `status --porcelain=v1`) against a throwaway `tmp_path` repo. RESEARCH.md pattern 5 verified the commands fresh this session (no code to copy); write the test from the command table in pattern 5 directly. |
| `tests/unit/research/test_power.py` | test | n/a | Besag-Clifford sequential-stopping Monte Carlo procedure is new to this codebase (no prior exact-power-check code exists to test against); build against RESEARCH.md code example 3 and pattern 9's stated invariants (early-stop decision equals full-set decision; curtailment equals fixed-R decision; `b_max` boundary arithmetic) rather than an existing test's structure. |

## Metadata

**Analog search scope:** `src/intelligence/research/`, `src/core/database_manager.py`,
`production/migrations/{283,329,334,340,357}_*.sql`, `tests/unit/_source_grep_helpers.py`,
`tests/unit/test_market_data_ohlcv_boundary.py`, `tests/integration/test_concept_parent_lineage.py`,
`tests/unit/research/{test_portfolio,test_evaluate_intraday,test_factors,test_guards}.py`,
`scripts/analysis/sleeve_walk_forward/{run,config,synthetic}.py`, `services/_batch_utils.py`
(`make_worker_pool`).
**Files scanned:** ~20 read directly (full or targeted sections); RESEARCH.md's own line-cited
inventory (its Sources section) covers the remainder without re-reading.
**Pattern extraction date:** 2026-09-25
