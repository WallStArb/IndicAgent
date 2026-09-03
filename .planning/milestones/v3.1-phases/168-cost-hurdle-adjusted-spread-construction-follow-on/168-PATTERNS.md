# Phase 168: Cost-Hurdle-Adjusted Spread Construction (cross_sectional_relative_value Follow-On) - Pattern Map

**Mapped:** 2026-07-31
**Files analyzed:** 5 (1 primary extension target, 2 test files extended, 1 new migration, 0 new
service/module files — D-02 mandates in-place extension, not a new file)
**Analogs found:** 5 / 5 (all patterns sourced from within the same file being extended, or its
one direct sibling — this is a same-codebase, same-module extension with no cross-domain reach)

This phase has an unusual shape for pattern mapping: the "closest analog" for nearly every new
piece of code is a different function *inside the same file* being extended
(`services/cross_sectional_spread_tracker.py`), because Phase 167 already built the exact
class of machinery (pure leg-selection functions, day-clustered bootstrap gate wiring, verdict
persistence, APR-validated batch service) this phase reuses. `services/counterfactual_tracker.py`
supplies the one piece of shared statistical infrastructure (`frame_gate_passes`/
`evaluate_frame_gate`) that both phases draw from. No file in this phase is being created from
a blank slate with an unrelated analog — every new function has a near-identical sibling to
copy the shape, docstring conventions, and error-handling discipline from.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `services/cross_sectional_spread_tracker.py` — new `hysteresis_legs()` pure function | utility (pure compute) | transform | `decile_legs()` (same file, lines 114-169) | exact — same input contract, same file, same module-docstring conventions |
| `services/cross_sectional_spread_tracker.py` — `CrossSectionalSpreadTracker.__init__`/`_execute_inner` extended with `construction_variant` param + hysteresis state threading | service (batch daemon) | CRUD (streaming panel scan → batch insert) | `CrossSectionalSpreadTracker._execute_inner`'s existing `process_bar` closure + prior-leg seeding (same file, lines 850-1062) | exact — literally the same method, parameterized, not a new class |
| `services/cross_sectional_spread_tracker.py` — new `--evaluate-delta-gate` CLI mode + `_run_evaluate_delta_gate()` | service (read-only reporting branch) | request-response (one-shot CLI invocation, read-only query → verdict artifact) | `_run_evaluate_gate()` (same file, lines 1195-1300+) | exact — same shape: bare `asyncpg.connect`, no pool, `write_verdict_artifact` at the end |
| `services/cross_sectional_spread_tracker.py` — new delta-series construction (align two `construction_name` partitions on `bar_ts`, build paired series) | utility (pure compute, SQL+Python wiring) | transform | `_flatten_gate_rows()` / `_build_panel_by_bar()` (same file, lines 1070-1117) | role-match — same "flatten persisted rows into a bootstrap-ready series" shape, but new pairing logic (no direct precedent for a two-partition join) |
| `services/cross_sectional_spread_tracker.py` — new stateful shuffled-null for the hysteresis construction | utility (pure compute, simulation loop) | transform | `shuffled_ranking_null_p()` (same file, lines 318-391) for the null-loop shape; `CrossSectionalSpreadTracker._execute_inner`'s `process_bar` closure (lines 958-1000) for the stateful `nonlocal prior_long, prior_short` threading pattern | role-match — needs both analogs combined (memoryless-null shape + stateful-carry shape), no single existing function does both |
| `services/cross_sectional_spread_tracker.py` — new `gross_spread_not_degraded()` wrapper | utility (pure compute) | transform | `evaluate_spread_gate()` (same file, lines 394-443) | role-match — same "wrap `evaluate_frame_gate`/`frame_gate_passes`, reinterpret the CI" shape, different pass condition |
| `production/migrations/27X_construction_cost_gated_apr.sql` | migration | batch (idempotent DDL/DML) | `production/migrations/261_construction_null_p_threshold.sql` (single-APR-key addition) and `260_construction_spreads_schema.sql` §2 (APR seed triad pattern) | exact |
| `tests/unit/test_cross_sectional_spread_tracker.py` (extended) | test | transform (pure-function unit tests) | Existing tests in the same file: `test_decile_split()`, `test_turnover_across_run_boundary()`, `test_cost_hurdle_sweep()` | exact |
| `tests/integration/test_cross_sectional_spread_tracker.py` (extended) | test | CRUD (DB-backed integration test) | Existing fixtures/tests in the same file (`_reset_panel_tables`, `_seed_bars`, the watermark/crash-recovery tests) | exact |

## Pattern Assignments

### `hysteresis_legs()` (utility, transform)

**Analog:** `decile_legs()` — `services/cross_sectional_spread_tracker.py:114-169`

**Signature + docstring convention to copy** (lines 114-148):
```python
def decile_legs(
    ranked_symbols: Sequence[str],
    feature_values: Sequence[float],
    decile_fraction: float,
) -> tuple[list[str], list[str]] | None:
    """Split a cross-section into a dollar-neutral (short_leg, long_leg) pair.
    ...
    Raises:
        ValueError: if `len(ranked_symbols) != len(feature_values)`, or if any feature value is
            `None` or fails `math.isfinite`.

    Returns:
        `(short_leg, long_leg)` symbol lists, or `None` if the cross-section is too small to
        form two disjoint legs.
    """
```
Every pure function in this module follows this exact docstring shape: one-line summary, a
paragraph naming which prior design decision it implements/matches, an explicit `Raises:`
block, an explicit `Returns:` block. `hysteresis_legs()` must match this — RESEARCH.md's
recommended implementation already follows it structurally.

**Fail-loud input validation to copy** (lines 149-159):
```python
    if len(ranked_symbols) != len(feature_values):
        raise ValueError(
            "ranked_symbols and feature_values must be the same length, got "
            f"{len(ranked_symbols)} and {len(feature_values)}"
        )

    for symbol, value in zip(ranked_symbols, feature_values, strict=True):
        if value is None or not math.isfinite(value):
            raise ValueError(
                f"feature value for symbol {symbol!r} is missing or non-finite: {value!r}"
            )
```
`hysteresis_legs()` should delegate this exact validation to its own internal `decile_legs()`
call (RESEARCH.md's recommended implementation does this — `ideal = decile_legs(...)` as the
first line) rather than re-implementing it, per this module's "Don't Hand-Roll" discipline.

**Invariant-assertion convention to copy** — this module does not currently assert
long/short-leg disjointness anywhere (it's guaranteed by construction in `decile_legs()`), but
RESEARCH.md Pitfall 4 explicitly calls for a hard `ValueError` (not a silent pass) if
`hysteresis_legs()`'s independent long/short resolution ever produces an overlap. Follow the
same "raise, never clamp or warn-and-continue" convention `validate_construction_config` uses
(lines 261-273):
```python
    if not (0 < decile_fraction <= 0.5):
        raise ValueError(f"decile_fraction must be in (0, 0.5], got {decile_fraction}")
```

**Degeneracy/edge-case handling to copy from `one_way_turnover()`** (lines 191-217) — the
`None`-not-`0.0` discipline for "no valid predecessor" state applies directly to hysteresis: a
held symbol absent from the current panel must be force-exited, never silently retained with a
stale value:
```python
    if not prev_long and not prev_short:
        return None
    n_leg = len(cur_long)
    if n_leg == 0:
        return None
```

---

### `CrossSectionalSpreadTracker` — `construction_variant` param + hysteresis state threading (service, CRUD)

**Analog:** the class's own existing constructor, prior-leg seeding, and `process_bar` closure —
`services/cross_sectional_spread_tracker.py:815-1062`

**Constructor pattern to extend, not replace** (lines 825-827):
```python
    def __init__(self, db_dsn: str, backfill: bool = False) -> None:
        super().__init__(db_dsn)
        self.backfill = backfill
```
D-02 requires a new `construction_variant: str` parameter here (default = the existing baseline
behavior), threading through to `_CONSTRUCTION_NAME`, which per RESEARCH.md's Recommended
Project Structure section must become a per-instance attribute (`self.construction_name`), not
the current module-level constant (line 111: `_CONSTRUCTION_NAME = "ctf_momentum_decile_ls"`).
Every SQL query in `_execute_inner` that currently references the module constant must be
re-pointed at `self.construction_name` — this is the single most important mechanical change
and the exact surface Pitfall 2 (cross-construction state leakage) warns about.

**Prior-leg seeding pattern — MUST be re-scoped per construction_name** (lines 897-940, the
CRITICAL block):
```python
            if mode == "backfill":
                prior_long = frozenset()
                prior_short = frozenset()
                prior_leg_seed_bar_ts = None
                ...
            else:
                prior_row = await conn.fetchrow(
                    "SELECT bar_ts, long_leg_symbols, short_leg_symbols FROM "
                    "construction_spreads WHERE construction_name = $1 AND tf = $2 "
                    "ORDER BY bar_ts DESC LIMIT 1",
                    _CONSTRUCTION_NAME,
                    _TF,
                )
```
This query (and the watermark query immediately before it, lines 876-882) is the exact
mechanism Pitfall 2 names: it already filters by `construction_name = $1`, so the fix is
mechanical (bind `self.construction_name` instead of the module constant) — but this is the
single highest-value regression test to add (backfilling the new variant when the baseline
variant already has rows must behave identically to backfilling into an empty table).

**Stateful `process_bar` closure — the pattern the new stateful null must mirror** (lines
958-1000):
```python
            def process_bar(bar_ts: Any, rows: list[dict[str, Any]]) -> None:
                nonlocal prior_long, prior_short, n_bars_processed, n_bars_skipped_degenerate
                symbols = [r["symbol"] for r in rows]
                feature_values = [r["ctf_momentum"] for r in rows]
                legs = decile_legs(symbols, feature_values, decile_fraction)
                if legs is None:
                    n_bars_skipped_degenerate += 1
                    return
                short_leg, long_leg = legs
                cur_long = frozenset(long_leg)
                cur_short = frozenset(short_leg)
                ...
                turnover = one_way_turnover(prior_long, prior_short, cur_long, cur_short)
                ...
                prior_long, prior_short = cur_long, cur_short
```
For the cost-gated variant this becomes `legs = hysteresis_legs(prior_long, prior_short,
symbols, feature_values, decile_fraction, margin)` in place of the `decile_legs()` call — this
`nonlocal prior_long, prior_short` carry-forward pattern is also the literal structural
analogue RESEARCH.md's Pitfall 1 points to for the new stateful shuffled-null loop (each shuffle
draw needs its own independent `prior_long`/`prior_short` state threaded bar-to-bar, not the
memoryless per-draw independence `shuffled_ranking_null_p` currently has).

---

### `--evaluate-delta-gate` CLI mode + `_run_evaluate_delta_gate()` (service, request-response)

**Analog:** `_run_evaluate_gate()` — `services/cross_sectional_spread_tracker.py:1195-1300+`

**Connection/lifecycle pattern to copy** (lines 1206-1249):
```python
    conn = await _open_evaluation_connection(db_dsn)
    try:
        ctx = await _load_gate_evaluation_context(conn, "--evaluate-gate")
        ...
        oos_gate_rows = [
            dict(r) for r in await conn.fetch(_GATE_ROWS_SQL, _CONSTRUCTION_NAME, _TF, oos_start)
        ]
        ...
    finally:
        await conn.close()
```
Bare `asyncpg.connect` (via `_open_evaluation_connection`, line 1138), never a pool — matches
this module's own documented reason: "this is a read-only reporting branch." No D-06
`job_completed_total` emission (matches `_run_evaluate_gate`'s own note, line 1201-1202) since
this mode performs no persistence beyond the verdict artifact.

**CLI wiring to copy** (lines 1602-1655) — `argparse.ArgumentParser` with a
`mode_group = parser.add_mutually_exclusive_group()`:
```python
    mode_group.add_argument(
        "--evaluate-gate",
        action="store_true",
        help=(
            "Evaluate Validation Gate 1 over bar_ts >= alpha.validation.oos_start ..."
        ),
    )
    ...
    if args.evaluate_gate:
        asyncio.run(_run_evaluate_gate(db_dsn))
    elif args.evaluate_attribution:
        asyncio.run(_run_evaluate_attribution(db_dsn))
```
Add `--evaluate-delta-gate` as a fourth mutually-exclusive mode in the same group, with an
`elif args.evaluate_delta_gate: asyncio.run(_run_evaluate_delta_gate(db_dsn))` branch — matches
RESEARCH.md's Assumption A2 recommendation (same service class, not a standalone script).

**Verdict write to copy** (line 460+ helper, called as shown at line 628 in RESEARCH.md's own
excerpt):
```python
    artifact_path = write_verdict_artifact("gate_delta", payload)
```

---

### Delta-series construction / two-partition join (utility, transform)

**Analog:** `_flatten_gate_rows()` / `_build_panel_by_bar()` — `services/cross_sectional_spread_tracker.py:1070-1117`

No direct precedent exists in this codebase for joining two `construction_name` partitions of
the same table on `bar_ts` (RESEARCH.md's own Pattern 3 confirms `gate166_frame_recalibration_eval.py`
is the closest prior "compare candidate vs. baseline" gate, but it uses independent single-arm
CIs, not a paired join — explicitly the anti-pattern D-04.1 rejects). Copy `_flatten_gate_rows`'s
general shape (flatten persisted `construction_spreads` rows into a bootstrap-ready record list,
one dict per unit-of-analysis) but the join itself is new:
```python
binding_bps = max(cost_bps)  # matches Gate 1's own binding-tier convention
delta_values = []
cluster_ids = []
for bar_ts in sorted(set(cost_gated_rows) & set(baseline_rows)):
    net_gated = cost_gated_rows[bar_ts][f"net_spread_{scale}_by_cost_bps"][str(binding_bps)]
    net_base = baseline_rows[bar_ts][f"net_spread_{scale}_by_cost_bps"][str(binding_bps)]
    delta_values.append(net_gated - net_base)
    cluster_ids.append(bar_ts.date())
```
(Source: 168-RESEARCH.md Pattern 3, already validated against the live schema.) Feed directly
into `frame_gate_passes` per the Shared Patterns section below — do not reimplement the
bootstrap.

---

### Stateful shuffled-null for the hysteresis construction (utility, transform)

**Analogs (combine both):**
1. Null-loop shape — `shuffled_ranking_null_p()`, `services/cross_sectional_spread_tracker.py:318-391`
2. Stateful-carry shape — `process_bar`'s `nonlocal prior_long, prior_short` pattern (see above)

**What to copy from `shuffled_ranking_null_p`** (lines 365-390): the outer `rng =
np.random.default_rng(seed)` / `for _ in range(n_shuffles):` loop structure, the per-draw
within-bar permutation (`rng.permutation(np.asarray(feature_values, dtype=float))`), and the
`ValueError` raised if eligible-bar count varies across draws (lines 379-384) — this
invariant-check convention must be preserved for the new stateful null too.

**What must NOT be copied verbatim** — the existing loop recomputes `decile_legs` fresh per bar
per draw with no cross-bar memory (line 373: `mean_gross_spread_over_bars(permuted_panel,
decile_fraction)` — a pure function with no state). The new null must instead walk bars in
`bar_ts` order **within each draw**, threading that draw's own simulated `(prior_long,
prior_short)` forward — i.e. re-derive the `process_bar` closure's `nonlocal` state-threading
pattern inside the null-simulation loop, once per shuffle draw. This is explicitly called out
as new, non-trivial code (RESEARCH.md Pitfall 1) — there is no drop-in function to call.

---

### `gross_spread_not_degraded()` wrapper (utility, transform)

**Analog:** `evaluate_spread_gate()` — `services/cross_sectional_spread_tracker.py:394-443`

**Shape to copy** (lines 423-430):
```python
    verdicts = evaluate_frame_gate(
        list(rows),
        min_n,
        bootstrap_max_n,
        bootstrap_batch,
        bootstrap_random_state,
        group_key=lambda row: (row["scale"], row["cost_bps"]),
    )
```
Reuse `frame_gate_passes` directly on the delta-of-`gross_spread_{fast,slow}` series (not
`net_spread`), but reinterpret the returned `(passes, ci_lower, ci_upper)` tuple's semantics —
per RESEARCH.md Pattern 4, "not meaningfully degraded" is `ci_lower > -epsilon_bps` (or simply
"CI does not lie entirely below zero"), not `frame_gate_passes`'s own default `ci_lower > 0`
"improves" semantics. Implement as a small distinct wrapper function, never by mutating
`frame_gate_passes`'s own `passes` field meaning in place (RESEARCH.md is explicit: this must be
"a distinct small wrapper," not an overload).

---

### `production/migrations/27X_construction_cost_gated_apr.sql` (migration)

**Analog:** `production/migrations/261_construction_null_p_threshold.sql` (full file, single-key
addition — see below) and `260_construction_spreads_schema.sql` §2 (APR seed triad, for the
general `config_schema`/`config_state`/`config_history` pattern)

**Full pattern to copy** (261, entire file body):
```sql
BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES
(
    'alpha.construction.null_p_threshold',
    'float',
    '0.05',
    '[conventional] Phase 167: Validation Gate 1''s shuffled-ranking-null significance level -- '
    'a scale''s null_p must be strictly below this value, at BOTH lookahead scales, for the '
    'binding gate1_passes verdict to be true (alongside the bootstrap CI clearing at the most '
    'conservative cost tier). Standard 5% two-sided significance convention; not an ML learning '
    'target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
('alpha.construction.null_p_threshold', '0.05', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
(NOW(), 'alpha.construction.null_p_threshold', 1, '0.05', 'migration_261', 'Conventional: standard 5% significance level ... [conventional]');

COMMIT;
```
Apply this exact triad shape once per new APR key. Per RESEARCH.md Pattern 2/Option A, the
required new keys are (at minimum) `alpha.construction.bps_per_feature_z` (provenance
`[initial_estimate]`, per APR mandate) and, if Option B is used instead/additionally,
`alpha.construction.hysteresis_rank_buffer` (`[initial_estimate]`, integer). **Migration number
must be re-verified against `ls production/migrations/ | sort -n | tail` and the live DB
immediately before execution** — 260's own header (quoted above) documents this exact collision
class already happening once for this same file; RESEARCH.md's Assumption A4 flags today's
best-guess (275) as needing re-verification, not as a locked number.

**Idempotency convention to copy** (260's own header comment, lines 27-29): "All statements
idempotent: `CREATE TABLE IF NOT EXISTS`, `create_hypertable(if_not_exists => TRUE)`, `CREATE
INDEX IF NOT EXISTS`, `ON CONFLICT (config_key) DO NOTHING`. Safe to re-run."

---

### `tests/unit/test_cross_sectional_spread_tracker.py` (extended) (test, transform)

**Analog:** `test_decile_split()` and `test_turnover_across_run_boundary()` — same file,
`tests/unit/test_cross_sectional_spread_tracker.py:66-97, 172-194`

**Pattern to copy — direct assertion against a named edge-case regression, no mocking needed for
pure functions:**
```python
def test_turnover_across_run_boundary():
    # (a) No predecessor: turnover must be None, NOT 0.0 -- Pitfall 4's named symptom of a
    # service that treats "first bar this run" as having no predecessor.
    result = one_way_turnover(frozenset(), frozenset(), {"A", "B"}, {"C", "D"})
    assert result is None, "Pitfall 4: no-predecessor turnover must be None, never 0.0"
```
Every test in this file names the specific design decision, code-review finding, or
RESEARCH.md pitfall it regression-tests in a comment directly above the assertion (see also the
section-header comment blocks at lines 100-103, 167-170, 197-200 delimiting each test's
provenance). New tests for `hysteresis_legs()` (stickiness, displacement, force-exit,
no-overlap invariant — all four already named in 168-RESEARCH.md's own Phase Requirements →
Test Map) should follow this exact "named provenance comment + direct pure-function call, no
DB/mocking" shape, matching `test_decile_split_tied_and_missing_values`'s tie/boundary-case
density (lines 105-164) as the density bar to match for `hysteresis_legs`'s own edge cases.

**Tie/determinism-check pattern to copy** (lines 89-97):
```python
    forward = decile_legs(tie_symbols, tie_values, decile_fraction=0.10)
    reversed_order = decile_legs(
        list(reversed(tie_symbols)), list(reversed(tie_values)), decile_fraction=0.10
    )
    assert forward == reversed_order
```
Apply the same input-order-independence check to `hysteresis_legs()`.

---

### `tests/integration/test_cross_sectional_spread_tracker.py` (extended) (test, CRUD)

**Analog:** this file's own fixtures and watermark-scoping tests —
`tests/integration/test_cross_sectional_spread_tracker.py:1-167` (module docstring, fixtures)
plus the existing crash-recovery/watermark tests later in the file (not fully re-read this
session; same file, same `pytestmark`).

**Module-level pattern to copy** (lines 1-42):
```python
"""Integration tests: CrossSectionalSpreadTracker watermark scoping, run-boundary turnover,
idempotency, and crash recovery (Phase 167 Plan 03).
...
ISOLATION: this file's fixtures TRUNCATE `construction_spreads` and DELETE `feature_vectors`/
`forward_returns` rows scoped to its own 12-symbol synthetic universe + tf='15m' at the start
of every test, so tests are order-independent.
...
"""
...
pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent_test"
```
The new test for D-02/Pitfall 2 (second-construction-name backfill isolation) is the direct,
explicitly-anticipated extension of this file's own existing isolation discipline — RESEARCH.md's
Phase Requirements → Test Map names this exact test:
`test_backfill_second_construction_name_isolated`.

**Synthetic panel-seeding pattern to copy** (lines 93-136, `_seed_bars`) — deterministic,
index-controlled extreme values so leg membership is fully predictable:
```python
    for bar_idx, (bar_ts, (short_idx, long_idx)) in enumerate(
        zip(bar_timestamps, leg_index_per_bar, strict=True)
    ):
        for sym_idx, symbol in enumerate(symbols):
            if sym_idx == short_idx:
                ctf_momentum = -1000.0
            elif sym_idx == long_idx:
                ctf_momentum = 1000.0
            else:
                ctf_momentum = float(sym_idx)
```
For the new isolation test, seed and backfill the baseline `construction_name` first (asserting
it produces rows), THEN backfill the cost-gated `construction_name` against the same panel and
assert its `prior_long`/`prior_short`/turnover sequence is byte-identical to a control run where
the baseline's rows were never written — the exact CR-01 regression shape, generalized to two
partitions.

**JSONB decode helper to reuse as-is** (lines 148-151):
```python
def _decode_jsonb(value: object) -> object:
    """Plain asyncpg.connect() (unlike BaseBatch's pooled connections) has no JSONB codec
    registered, so jsonb columns come back as raw JSON text -- decode for comparison."""
    return json.loads(value) if isinstance(value, str) else value
```

## Shared Patterns

### Day-clustered bootstrap CI (single-arm and delta)
**Source:** `services/counterfactual_tracker.py:173-230` (`frame_gate_passes`) and `:907+`
(`evaluate_frame_gate`)
**Apply to:** `_run_evaluate_delta_gate` (D-04.1's delta-CI), the new `gross_spread_not_degraded`
wrapper (D-04.2), and — unchanged, already wired by Phase 167 — the existing `evaluate_spread_gate`
call inside the new `--evaluate-delta-gate` mode if a single-arm re-check is ever needed.
```python
def frame_gate_passes(
    pnl_r_values: Sequence[float],
    cluster_ids: Sequence[Any],
    min_n: int,
    bootstrap_max_n: int,
    bootstrap_batch: int,
    bootstrap_random_state: int = _DEFAULT_BOOTSTRAP_RANDOM_STATE,
) -> tuple[bool, float, float]:
    """... Returns (passes, ci_lower, ci_upper). passes iff ci_lower > 0.
    Returns (False, nan, nan) when len(pnl_r_values) < min_n ... or when fewer than 2
    day-clusters exist ..."""
```
Domain-agnostic over `(value, cluster_id)` pairs — feeding it a delta series instead of a raw
pnl series requires zero changes to this function. `_DEFAULT_BOOTSTRAP_RANDOM_STATE = 42`
(line 84) is the same seed already used everywhere else in this module via the
`alpha.scoring.bootstrap_random_state` APR key — reuse that key, do not introduce a new seed.

### Verdict artifact persistence
**Source:** `services/cross_sectional_spread_tracker.py:460-505` (`write_verdict_artifact`)
**Apply to:** `_run_evaluate_delta_gate`'s final `write_verdict_artifact("gate_delta", payload)`
call. Already handles non-finite coercion (`_coerce_non_finite`, lines 446-457), strict-JSON
(`allow_nan=False`), and accumulate-never-overwrite semantics with second-level collision
handling. Do not write a new JSON-writing helper.

### APR config loading/validation
**Source:** `services/_batch_utils.py:131-176` (`load_apr_dict_async`, `cfg`) and
`services/cross_sectional_spread_tracker.py:243-273` (`validate_construction_config`)
**Apply to:** loading the new margin/rank-buffer APR key(s) inside `_execute_inner` (extend the
existing `_load_apr(conn, extra_like_patterns=[...])` call already at line 853-855) and inside
`_load_gate_evaluation_context` for the new `--evaluate-delta-gate` mode. Extend
`validate_construction_config` (or add a parallel validator) to range-check the new key(s)
before any panel work begins — same fail-loud, no-clamping discipline:
```python
async def load_apr_dict_async(conn: Any, extra_like_patterns: list[str] | None = None) -> Any:
    """Load alpha.* (+ optional extra LIKE patterns...) APR keys via asyncpg into a raw dict."""
    patterns = ["alpha.%", *(extra_like_patterns or [])]
    rows = await conn.fetch(
        "SELECT config_key, config_value FROM config_state WHERE config_key LIKE ANY($1::text[])",
        patterns,
    )
    return {r["config_key"]: r["config_value"] for r in rows}


def cfg(cfg_dict: dict[str, Any], key: str, default: Any) -> Any:
    """Cast a raw config_value to default's type, or return default if unset. bool/list/dict
    defaults are special-cased ..."""
```

### Cross-sectional decile ranking
**Source:** `services/cross_sectional_spread_tracker.py:114-169` (`decile_legs`)
**Apply to:** `hysteresis_legs()` — call `decile_legs()` first to get the "ideal" unconditional
target leg set, then apply stickiness on top (RESEARCH.md's recommended algorithm does exactly
this: `ideal = decile_legs(ranked_symbols, feature_values, decile_fraction)` as its first line).
Never re-implement the ranking/tie-break/NaN-guard logic.

### Construction-name scoping discipline (Pitfall 2)
**Source:** `services/cross_sectional_spread_tracker.py:876-940` — every query against
`construction_spreads` (watermark, prior-leg seed, `_GATE_ROWS_SQL`, `_GATE_PANEL_SQL`,
`_GATE_ROWS_IN_SAMPLE_SQL`)
**Apply to:** every new query the cost-gated variant and the new `--evaluate-delta-gate` mode
issue. All must bind `construction_name` as an explicit `$N` parameter, never string-interpolate
it, and the two constructions' queries must never omit this filter — this is the single
cross-cutting correctness requirement every new piece of code in this phase touches.

## No Analog Found

None. Every file/function this phase touches has at least a role-match analog inside
`services/cross_sectional_spread_tracker.py` itself or its one sibling
`services/counterfactual_tracker.py`. The two places with the weakest precedent (explicitly
flagged, not hidden) are:

| Component | Role | Data Flow | Reason no exact analog exists |
|-----------|------|-----------|-------------------------------|
| Two-partition `bar_ts` join for the delta series | utility | transform | No prior "compare two `construction_name` partitions of the same table" query exists in this codebase; `gate166_frame_recalibration_eval.py` is the closest prior "candidate vs. baseline" gate but uses independent single-arm CIs, the exact shape D-04.1 rejects (confirmed via direct grep, per 168-RESEARCH.md Sources) |
| Stateful shuffled-null loop | utility | event-driven (sequential simulation) | `shuffled_ranking_null_p()` is memoryless by design (Phase 167's correct choice for a memoryless construction); no stateful/sequential null-simulation precedent exists anywhere in this codebase — the planner should size this as its own task, combining the null-loop shape from `shuffled_ranking_null_p` with the `nonlocal`-state-threading shape from `process_bar` |

## Metadata

**Analog search scope:** `services/cross_sectional_spread_tracker.py` (full file, 1657 lines,
read across two non-overlapping passes: lines 69-329 and 318-1300+ covering all named function
definitions and the CLI entrypoint), `services/counterfactual_tracker.py` (targeted grep +
read of `frame_gate_passes`/`evaluate_frame_gate` signatures, lines 84-230 and 907+),
`production/migrations/260_construction_spreads_schema.sql` and `261_construction_null_p_threshold.sql`
(header + full body), `services/_batch_utils.py` (`load_apr_dict_async`/`cfg`, lines 131-176),
`tests/unit/test_cross_sectional_spread_tracker.py` (function-name inventory + full read of
lines 66-228), `tests/integration/test_cross_sectional_spread_tracker.py` (function-name
inventory + full read of lines 1-168).

**Files scanned:** 6 (2 target-sibling service files, 2 migration files, 2 test files) — no
broader codebase search was needed since D-02/D-04's own locked decisions mandate reusing this
exact module's existing machinery rather than searching for an external pattern.

**Pattern extraction date:** 2026-07-31
