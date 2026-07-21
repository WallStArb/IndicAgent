# Regime-Stratified OOS Promotion Gate + Per-Timeframe Ensemble Eligibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix todo 165 (promotion gates blind to regime) and todo 164's `1h` portion
(global ensemble-eligibility thresholds miscalibrated for `1h`'s smaller-but-not-weaker
population), then file 164's `1d` portion as its own follow-up todo.

**Architecture:** Generalize the existing day-clustered bootstrap gate
(`evaluate_frame_gate` in `services/counterfactual_tracker.py`) to accept an arbitrary
grouping key and an optional day-cluster coverage floor, then reuse it for a new
regime-stratified OOS evaluation path in `scripts/analysis/phase143_1_08_shadow_validation.py`.
Separately, extend `services/ensemble_trainer.py`'s three global APR-backed thresholds to
resolve per-timeframe (exact precedent: `alpha.frame.hold_max_bars.<regime>.<tf>`), with a
startup feasibility assertion guarding the `min_passing_features * max_feature_weight >= 1.0`
constraint.

**Tech Stack:** Python 3.14, asyncpg, numpy, scipy.stats.bootstrap, pytest.

## Global Constraints

- All new/changed numeric thresholds go through the Adaptive Parameter Registry
  (`config_schema`/`config_state`/`config_history` migration triple) — no hardcoded
  constants in `src/` or `services/`.
- Every new APR key's `description` must state provenance (`[initial_estimate]` for both
  new keys here) per this project's APR convention.
- `alpha.validation.regime_gate_min_clusters` is pre-registered and must never be tuned in
  response to a specific promotion decision's outcome (same discipline as
  `bootstrap_random_state`, WR-01) — its migration description must say so explicitly.
- Never read in-sample (`bar_ts < oos_start`) data for the new OOS regime-stratified gate —
  only `bar_ts >= oos_start` rows.
- Exception variable name is `error`, not `exc` (`except X as error:`).
- Full spec: `docs/superpowers/specs/2026-07-21-regime-stratified-promotion-and-per-timeframe-eligibility-design.md`.

---

## Part A — Todo 165: Regime-Stratified OOS Promotion Gate

### Task A1: Generalize `evaluate_frame_gate` with a grouping key and coverage floor

**Files:**
- Modify: `services/counterfactual_tracker.py:906-952` (`evaluate_frame_gate`)
- Test: `tests/unit/test_counterfactual_tracker.py`

**Interfaces:**
- Produces: `evaluate_frame_gate(rows, min_n, bootstrap_max_n, bootstrap_batch, bootstrap_random_state=_DEFAULT_BOOTSTRAP_RANDOM_STATE, group_key=None, min_clusters=None)` — `group_key: Callable[[dict], tuple] | None` defaults to `lambda row: (row["tf"], row["regime"])`; `min_clusters: int | None` defaults to `None` (no coverage floor, current behavior). Each returned verdict dict gains one field: `"coverage"` — `"insufficient"` when `min_clusters` is set and `n_clusters < min_clusters`, else `"evaluated"`. When `coverage == "insufficient"`, `"passes"` is forced to `None` (neither pass nor fail) regardless of what `frame_gate_passes` returned.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_counterfactual_tracker.py` (near the existing `evaluate_frame_gate` tests around line 340):

```python
def test_evaluate_frame_gate_custom_group_key():
    """A custom group_key (e.g. direction+regime) groups independently of tf/regime."""
    rows = [
        {"direction": "short", "regime": "high_bear", "cluster_id": "2026-01-01", "pnl_r": 0.1},
        {"direction": "short", "regime": "high_bear", "cluster_id": "2026-01-02", "pnl_r": 0.2},
        {"direction": "long", "regime": "high_bear", "cluster_id": "2026-01-01", "pnl_r": -0.1},
    ]
    verdicts = evaluate_frame_gate(
        rows,
        min_n=1,
        bootstrap_max_n=5000,
        bootstrap_batch=1000,
        group_key=lambda row: (row["direction"], row["regime"]),
    )
    cells = {(v["tf"], v["regime"]) for v in verdicts}
    assert cells == {("short", "high_bear"), ("long", "high_bear")}


def test_evaluate_frame_gate_default_group_key_unchanged():
    """Omitting group_key preserves today's (tf, regime) grouping byte-for-byte."""
    rows = [
        {"tf": "5m", "regime": "trending_up", "cluster_id": "2026-01-01", "pnl_r": 0.5},
        {"tf": "1h", "regime": "trending_up", "cluster_id": "2026-01-01", "pnl_r": 0.3},
    ]
    verdicts = evaluate_frame_gate(rows, min_n=1, bootstrap_max_n=5000, bootstrap_batch=1000)
    cells = {(v["tf"], v["regime"]) for v in verdicts}
    assert cells == {("5m", "trending_up"), ("1h", "trending_up")}
    assert all(v["coverage"] == "evaluated" for v in verdicts)


def test_evaluate_frame_gate_min_clusters_marks_insufficient():
    """A cell below min_clusters day-clusters is reported insufficient, not failed --
    even though it clears the (much lower) min_n frame-count floor."""
    rows = [
        {"tf": "1h", "regime": "high_neutral", "cluster_id": f"day-{i}", "pnl_r": 0.1}
        for i in range(5)
    ] + [
        {"tf": "1h", "regime": "low_bull", "cluster_id": f"day-{i}", "pnl_r": 0.1}
        for i in range(25)
    ]
    verdicts = evaluate_frame_gate(
        rows, min_n=1, bootstrap_max_n=5000, bootstrap_batch=1000, min_clusters=20
    )
    by_regime = {v["regime"]: v for v in verdicts}
    assert by_regime["high_neutral"]["coverage"] == "insufficient"
    assert by_regime["high_neutral"]["passes"] is None
    assert by_regime["low_bull"]["coverage"] == "evaluated"
    assert by_regime["low_bull"]["passes"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_counterfactual_tracker.py -k "group_key or min_clusters" -v`
Expected: FAIL — `evaluate_frame_gate() got an unexpected keyword argument 'group_key'`

- [ ] **Step 3: Implement the generalized function**

Replace `services/counterfactual_tracker.py:906-952` with:

```python
def evaluate_frame_gate(
    rows: Iterable[dict[str, Any]],
    min_n: int,
    bootstrap_max_n: int,
    bootstrap_batch: int,
    bootstrap_random_state: int = _DEFAULT_BOOTSTRAP_RANDOM_STATE,
    group_key: Callable[[dict[str, Any]], tuple[Any, Any]] | None = None,
    min_clusters: int | None = None,
) -> list[dict[str, Any]]:
    """Pure grouping/aggregation core for day-clustered bootstrap gate evaluation.

    Takes an in-memory iterable of dicts with keys tf, regime, cluster_id, pnl_r -- pnl_r is
    the GROSS realized counterfactual_pnl_r (D-01); this function applies no adjustment to
    it whatsoever. Groups rows by group_key (default: (tf, regime), the FRAME-04 in-sample
    exit gate's original grouping -- omitting group_key preserves that behavior byte-for-byte).
    A second caller (the OOS regime-stratified promotion gate, todo 165) reuses this same
    core with group_key=lambda row: (row["direction"], row["regime"]) rather than
    duplicating the day-clustered bootstrap machinery.

    Passes each cell's per-frame calendar-date cluster_id straight into frame_gate_passes
    unmodified (day-clustered, review H4), and respects the min_n frame-count sufficiency
    floor via that same call.

    min_clusters (optional): a day-cluster coverage floor distinct from min_n's frame-count
    floor -- a cell can clear min_n on frame count alone while resting on too few
    independent day-observations for the bootstrap CI to mean anything (todo 165). When set,
    a cell with n_clusters < min_clusters is marked coverage="insufficient" and its "passes"
    field is forced to None (neither pass nor fail) regardless of frame_gate_passes' own
    verdict -- never silently counted as a failure. Cells at/above the floor (or when
    min_clusters is None, preserving current callers' behavior) get coverage="evaluated".

    Returns one verdict dict per group_key cell: tf, regime, n_frames, n_clusters, ci_lower,
    ci_upper, passes, coverage. (tf/regime keys are populated from the group_key tuple's two
    elements regardless of what group_key actually groups by, so existing callers that group
    by (tf, regime) see unchanged field names.)
    """
    if group_key is None:
        group_key = lambda row: (row["tf"], row["regime"])  # noqa: E731

    groups: dict[tuple[Any, Any], dict[str, list[Any]]] = {}
    for row in rows:
        key = group_key(row)
        bucket = groups.setdefault(key, {"pnl_r": [], "cluster_id": []})
        bucket["pnl_r"].append(row["pnl_r"])
        bucket["cluster_id"].append(row["cluster_id"])

    verdicts: list[dict[str, Any]] = []
    for (dim_a, dim_b), bucket in groups.items():
        passes, ci_lower, ci_upper = frame_gate_passes(
            bucket["pnl_r"],
            bucket["cluster_id"],
            min_n,
            bootstrap_max_n,
            bootstrap_batch,
            bootstrap_random_state,
        )
        n_clusters = len(set(bucket["cluster_id"]))
        coverage = "evaluated"
        if min_clusters is not None and n_clusters < min_clusters:
            coverage = "insufficient"
            passes = None
        verdicts.append(
            {
                "tf": dim_a,
                "regime": dim_b,
                "n_frames": len(bucket["pnl_r"]),
                "n_clusters": n_clusters,
                "ci_lower": ci_lower,
                "ci_upper": ci_upper,
                "passes": passes,
                "coverage": coverage,
            }
        )
    return verdicts
```

`services/counterfactual_tracker.py:51` currently reads
`from collections.abc import Iterable, Sequence`. Change it to:

```python
from collections.abc import Callable, Iterable, Sequence
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_counterfactual_tracker.py -k "group_key or min_clusters or evaluate_frame_gate" -v`
Expected: PASS (all, including the 3 pre-existing `evaluate_frame_gate` tests — confirms
default behavior is unchanged)

- [ ] **Step 5: Commit**

```bash
git add services/counterfactual_tracker.py tests/unit/test_counterfactual_tracker.py
git commit -m "feat(165): generalize evaluate_frame_gate with grouping key + coverage floor"
```

---

### Task A2: Migration for `alpha.validation.regime_gate_min_clusters`

**Files:**
- Create: `production/migrations/244_regime_gate_min_clusters.sql`

- [ ] **Step 1: Write the migration**

```sql
-- Migration 244: alpha.validation.regime_gate_min_clusters APR key (todo 165)
--
-- Day-cluster coverage floor for the new regime-stratified OOS promotion gate
-- (evaluate_frame_gate's min_clusters parameter, services/counterfactual_tracker.py).
-- Distinct from alpha.scoring.min_strategy_n (a frame-COUNT floor) -- a (direction,
-- regime) cell can clear that floor on raw frame count while resting on too few
-- independent day-clusters for a day-clustered bootstrap CI to mean anything (e.g. a
-- live-observed OOS cell: 261 frames, only 8 days). Below this floor, the cell is
-- reported coverage="insufficient" and excluded from the promotion verdict combination
-- -- never silently counted as a pass or a fail.
--
-- PRE-REGISTERED, NOT TUNABLE POST-HOC: this value must be frozen at the moment it is
-- committed and never adjusted in response to seeing whether a specific promotion
-- decision passes or fails under it -- same "no post-hoc gate renegotiation" discipline
-- already established for frame_gate_passes' bootstrap_random_state (WR-01,
-- SHADOW-REVIEW.md). Any future change to this key must cite new empirical evidence
-- about coverage-floor calibration in general, never a specific pending verdict.
--
-- Seed 20 is [initial_estimate]: no empirical calibration performed yet (todo 165 filed
-- this alongside the mechanism, not a tuned number) -- chosen as meaningfully smaller
-- than the existing pooled 60-day floor (alpha.scoring.min_strategy_n's day-equivalent
-- for a single-window gate) while still large enough for a day-clustered BCa bootstrap
-- to be non-degenerate.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.validation.regime_gate_min_clusters',
    'int',
    '20',
    5, 60,
    '[initial_estimate] Day-cluster coverage floor for the regime-stratified OOS '
    'promotion gate (todo 165). A (direction, regime) cell below this many distinct '
    'day-clusters is reported coverage=insufficient and excluded from the promotion '
    'verdict combination, rather than silently counted as pass or fail. PRE-REGISTERED: '
    'must not be tuned in response to any specific promotion decision''s outcome (same '
    'discipline as alpha.scoring.bootstrap_random_state, WR-01). Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.validation.regime_gate_min_clusters', '20', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.validation.regime_gate_min_clusters', 1, '20', 'migration_244',
     'Seed regime-stratified OOS gate day-cluster coverage floor, todo 165 [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
```

- [ ] **Step 2: Apply the migration**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/244_regime_gate_min_clusters.sql`
Expected: `BEGIN` / `INSERT 0 1` (x3, or `INSERT 0 0` if already applied) / `COMMIT`

- [ ] **Step 3: Verify the key is readable**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT config_key, config_value FROM config_state WHERE config_key = 'alpha.validation.regime_gate_min_clusters'"`
Expected: one row, `config_value = 20`

- [ ] **Step 4: Commit**

```bash
git add production/migrations/244_regime_gate_min_clusters.sql
git commit -m "feat(165): seed alpha.validation.regime_gate_min_clusters APR key"
```

---

### Task A3: Wire the regime-stratified gate into `phase143_1_08_shadow_validation.py`

**Files:**
- Modify: `scripts/analysis/phase143_1_08_shadow_validation.py`

**Interfaces:**
- Consumes: `evaluate_frame_gate(rows, min_n, bootstrap_max_n, bootstrap_batch, bootstrap_random_state, group_key=..., min_clusters=...)` from Task A1.

- [ ] **Step 1: Add `regime` to the OOS query and load the new APR key**

Modify `_OOS_QUERY_SQL` (line 31-40) to also select `regime`:

```python
_OOS_QUERY_SQL = """
    SELECT bar_ts, direction, regime, bar_ts::date AS cluster_id, counterfactual_pnl_r AS pnl_r
    FROM alpha_frames
    WHERE weight_epoch = $1
      AND frame_variant = 'primary'
      AND status != 'open'
      AND bar_ts >= $2
      AND counterfactual_pnl_r IS NOT NULL
    ORDER BY bar_ts ASC
"""
```

Modify `_load_apr` (line 70-82) to also return `regime_gate_min_clusters`:

```python
async def _load_apr(conn: asyncpg.Connection) -> tuple[int, int, int, int, int]:
    apr_rows = await conn.fetch(
        "SELECT config_key, config_value FROM config_state WHERE config_key LIKE ANY($1::text[])",
        ["alpha.scoring.%", "alpha.validation.regime_gate_min_clusters"],
    )
    apr_cfg = {row["config_key"]: row["config_value"] for row in apr_rows}
    min_n = _cfg(apr_cfg, "alpha.scoring.min_strategy_n", 30)
    bootstrap_max_n = _cfg(apr_cfg, "alpha.scoring.bootstrap_max_n", 5000)
    bootstrap_batch = _cfg(apr_cfg, "alpha.scoring.bootstrap_batch", 1000)
    bootstrap_random_state = _cfg(
        apr_cfg, "alpha.scoring.bootstrap_random_state", _DEFAULT_BOOTSTRAP_RANDOM_STATE
    )
    regime_gate_min_clusters = _cfg(apr_cfg, "alpha.validation.regime_gate_min_clusters", 20)
    return min_n, bootstrap_max_n, bootstrap_batch, bootstrap_random_state, regime_gate_min_clusters
```

Update the import at the top of the file to bring in the generalized `evaluate_frame_gate`:

```python
from services.counterfactual_tracker import (  # noqa: E402
    _DEFAULT_BOOTSTRAP_RANDOM_STATE,
    evaluate_frame_gate,
    frame_gate_passes,
)
```

- [ ] **Step 2: Add the regime-stratified evaluation to `evaluate_epoch`**

Modify `evaluate_epoch`'s signature (line 85-93) to accept `regime_gate_min_clusters: int`,
and add the stratified evaluation inside the function body (after the existing `rows = ...`
line, before the `c2_passes` computation):

```python
async def evaluate_epoch(
    conn: asyncpg.Connection,
    weight_epoch: str,
    oos_start: Any,
    min_n: int,
    bootstrap_max_n: int,
    bootstrap_batch: int,
    bootstrap_random_state: int,
    regime_gate_min_clusters: int,
) -> dict[str, Any]:
    rows = [dict(r) for r in await conn.fetch(_OOS_QUERY_SQL, weight_epoch, oos_start)]
    n_days = len({r["cluster_id"] for r in rows})
    pnl_r = [r["pnl_r"] for r in rows]
    cluster_ids = [r["cluster_id"] for r in rows]
    bar_ts = [r["bar_ts"] for r in rows]

    c2_passes, ci_lower, ci_upper = frame_gate_passes(
        pnl_r, cluster_ids, min_n, bootstrap_max_n, bootstrap_batch, bootstrap_random_state
    )

    sharpe = _annualized_sharpe(pnl_r, bar_ts) if pnl_r else None
    dd, dd_fails = _max_drawdown(np.array(pnl_r)) if pnl_r else (None, True)

    # Regime-stratified re-evaluation of C2/C7 (todo 165) -- groups by (direction, regime),
    # never reaches into in-sample data (rows are already OOS-only from _OOS_QUERY_SQL).
    # Scope-narrowed to C2/C7 only: C1 (day floor)/C3 (Sharpe)/C4 (drawdown)/C6
    # (non-regression) stay pooled, since Sharpe/drawdown are multi-day path statistics
    # that are not meaningful on an 8-25 day regime slice.
    regime_cells = evaluate_frame_gate(
        rows,
        min_n=1,  # frame-count floor not meaningful here; min_clusters is the real floor
        bootstrap_max_n=bootstrap_max_n,
        bootstrap_batch=bootstrap_batch,
        bootstrap_random_state=bootstrap_random_state,
        group_key=lambda row: (row["direction"], row["regime"]),
        min_clusters=regime_gate_min_clusters,
    )
    evaluated_cells = [c for c in regime_cells if c["coverage"] == "evaluated"]
    c2_regime_stratified_passes = all(c["passes"] for c in evaluated_cells) if evaluated_cells else None
    c7_regime_stratified_no_confident_loss = not any(
        c["ci_upper"] is not None and not np.isnan(c["ci_upper"]) and c["ci_upper"] < 0
        for c in evaluated_cells
    )

    short_rows = [r for r in rows if r["direction"] == "short"]
    n_short = len(short_rows)
    short_ci_lower, short_ci_upper = float("nan"), float("nan")
    if n_short >= 2:
        _, short_ci_lower, short_ci_upper = frame_gate_passes(
            [r["pnl_r"] for r in short_rows],
            [r["cluster_id"] for r in short_rows],
            1,  # no min_n floor for the informational short-side check
            bootstrap_max_n,
            bootstrap_batch,
            bootstrap_random_state,
        )
    confident_loss = n_short > 0 and not np.isnan(short_ci_upper) and short_ci_upper < 0

    return {
        "weight_epoch": weight_epoch,
        "n_rows": len(rows),
        "n_days": n_days,
        "c1_min_60_days": n_days >= 60,
        "c2_ci_lower": ci_lower,
        "c2_ci_upper": ci_upper,
        "c2_passes": c2_passes,
        "c3_sharpe": sharpe,
        "c3_passes": sharpe is not None and sharpe > 0.5,
        "c4_max_dd": dd,
        "c4_passes": not dd_fails,
        "n_short": n_short,
        "c7_short_ci_lower": short_ci_lower,
        "c7_short_ci_upper": short_ci_upper,
        "c7_confident_loss": confident_loss,
        "regime_cells": regime_cells,
        "c2_regime_stratified_passes": c2_regime_stratified_passes,
        "c7_regime_stratified_no_confident_loss": c7_regime_stratified_no_confident_loss,
    }
```

- [ ] **Step 3: Update `main()` to load/pass the new APR value, print the coverage report, and use the stratified criteria in the verdict**

Replace the `main()` body's APR-loading line and the two `evaluate_epoch(...)` calls (lines
144-170), the printing loop (lines 176-179), and the verdict computation (lines 183-197):

```python
async def main() -> None:
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(db_dsn)
    try:
        (
            min_n,
            bootstrap_max_n,
            bootstrap_batch,
            bootstrap_random_state,
            regime_gate_min_clusters,
        ) = await _load_apr(conn)
        oos_start = await conn.fetchval(
            "SELECT config_value::timestamptz FROM config_state "
            "WHERE config_key = 'alpha.validation.oos_start'"
        )
        if oos_start is None:
            raise RuntimeError("alpha.validation.oos_start is not set in config_state")

        champion = await evaluate_epoch(
            conn,
            "143.1-08-champion",
            oos_start,
            min_n,
            bootstrap_max_n,
            bootstrap_batch,
            bootstrap_random_state,
            regime_gate_min_clusters,
        )
        challenger = await evaluate_epoch(
            conn,
            "143.1-08-challenger",
            oos_start,
            min_n,
            bootstrap_max_n,
            bootstrap_batch,
            bootstrap_random_state,
            regime_gate_min_clusters,
        )
    finally:
        await conn.close()

    c6_passes = challenger["c2_ci_lower"] >= champion["c2_ci_lower"]

    for label, result in (("CHAMPION", champion), ("CHALLENGER", challenger)):
        print(f"\n=== {label} ({result['weight_epoch']}) ===")
        for key, value in result.items():
            if key == "regime_cells":
                continue
            print(f"  {key}: {value}")
        print(f"  --- regime coverage (min_clusters={regime_gate_min_clusters}) ---")
        for cell in sorted(result["regime_cells"], key=lambda c: (c["tf"], c["regime"])):
            print(
                f"    direction={cell['tf']} regime={cell['regime']} "
                f"n_frames={cell['n_frames']} n_clusters={cell['n_clusters']} "
                f"coverage={cell['coverage']} passes={cell['passes']} "
                f"ci_lower={cell['ci_lower']} ci_upper={cell['ci_upper']}"
            )

    print(f"\n=== CRITERION 6 (non-regression vs champion) ===\n  passes: {c6_passes}")

    verdict = (
        "PROMOTE"
        if all(
            [
                challenger["c1_min_60_days"],
                challenger["c2_regime_stratified_passes"] is True,
                challenger["c3_passes"],
                challenger["c4_passes"],
                c6_passes,
                challenger["c7_regime_stratified_no_confident_loss"],
            ]
        )
        else "HOLD"
    )
    print(
        "\n=== VERDICT (criteria 1, 3, 4, 6 pooled; 2, 7 regime-stratified per todo 165) "
        f"===\n  {verdict}"
    )
    if challenger["c2_regime_stratified_passes"] is None:
        print(
            "  NOTE: no (direction, regime) cell had sufficient OOS day-cluster coverage "
            f"(floor={regime_gate_min_clusters}) -- verdict is inconclusive on regime-conditional "
            "edge, not a clean HOLD."
        )


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Commit**

```bash
git add scripts/analysis/phase143_1_08_shadow_validation.py
git commit -m "feat(165): regime-stratify 143.1-08's OOS promotion gate (C2/C7)"
```

---

### Task A4: Live verification — re-run against real 143.1-08 data

**Files:** none (verification only; one doc update)

- [ ] **Step 1: Run the updated script against the real champion/challenger data**

Run: `.venv/bin/python scripts/analysis/phase143_1_08_shadow_validation.py`

Record the full output (verdict, per-cell coverage table for both champion and challenger).

- [ ] **Step 2: Append the result to the phase's shadow-validation record**

Read `.planning/phases/143.1-measurement-and-eligibility-integrity-fisher-z-ci-bootstrap-/143.1-08-SHADOW-VALIDATION.md`,
then append a new `## 7. Regime-stratified re-evaluation (todo 165)` section after its
existing `## 6. Measured results` section, containing: the date, the actual verdict output
from Step 1 (verbatim), and one sentence noting whether it changed from section 6's original
verdict and why (coverage-floor exclusions, if any cells were insufficient).

- [ ] **Step 3: Commit**

```bash
git add ".planning/phases/143.1-measurement-and-eligibility-integrity-fisher-z-ci-bootstrap-/143.1-08-SHADOW-VALIDATION.md"
git commit -m "docs(165): record regime-stratified re-evaluation of 143.1-08's promotion verdict"
```

---

## Part B — Todo 164 (`1h` portion): Per-Timeframe Ensemble Eligibility Thresholds

### Task B1: Add the per-tf resolver + feasibility assertion (pure, unit-testable)

**Files:**
- Modify: `services/ensemble_trainer.py` (add near `_eligibility_where`, ~line 106)
- Test: `tests/unit/test_ensemble_trainer.py`

**Interfaces:**
- Produces: `_resolve_per_tf(cfg: dict[str, Any], key_base: str, tf: str, default: Any) -> Any`
- Produces: `_assert_feasible_thresholds(cfg: dict[str, Any], tfs: Iterable[str], global_min_passing_features: int, global_max_feature_weight: float) -> None` (raises `RuntimeError`)

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_ensemble_trainer.py`:

```python
from services.ensemble_trainer import _assert_feasible_thresholds, _resolve_per_tf


class TestResolvePerTf:
    def test_falls_back_to_default_when_unset(self) -> None:
        assert _resolve_per_tf({}, "alpha.ensemble.min_passing_features", "1h", 5) == 5

    def test_uses_per_tf_override_when_set(self) -> None:
        cfg = {"alpha.ensemble.min_passing_features.1h": "3"}
        assert _resolve_per_tf(cfg, "alpha.ensemble.min_passing_features", "1h", 5) == 3

    def test_other_timeframes_unaffected_by_1h_override(self) -> None:
        cfg = {"alpha.ensemble.min_passing_features.1h": "3"}
        assert _resolve_per_tf(cfg, "alpha.ensemble.min_passing_features", "15m", 5) == 5


class TestAssertFeasibleThresholds:
    def test_raises_on_infeasible_pair(self) -> None:
        cfg = {
            "alpha.ensemble.min_passing_features.1h": "2",
            "alpha.ensemble.max_feature_weight.1h": "0.20",
        }
        with pytest.raises(RuntimeError, match="infeasible"):
            _assert_feasible_thresholds(cfg, ["1h"], global_min_passing_features=5, global_max_feature_weight=0.20)

    def test_passes_on_feasible_pair(self) -> None:
        cfg = {
            "alpha.ensemble.min_passing_features.1h": "3",
            "alpha.ensemble.max_feature_weight.1h": "0.34",
        }
        _assert_feasible_thresholds(cfg, ["1h"], global_min_passing_features=5, global_max_feature_weight=0.20)

    def test_global_default_pair_is_feasible(self) -> None:
        _assert_feasible_thresholds({}, ["5m", "15m", "1d"], global_min_passing_features=5, global_max_feature_weight=0.20)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_ensemble_trainer.py -k "ResolvePerTf or AssertFeasible" -v`
Expected: FAIL — `ImportError: cannot import name '_resolve_per_tf'`

- [ ] **Step 3: Implement both functions**

Add to `services/ensemble_trainer.py`, directly after `_eligibility_where` (before the
`EnsembleConfig` dataclass, ~line 127):

```python
def _resolve_per_tf(cfg: dict[str, Any], key_base: str, tf: str, default: Any) -> Any:
    """Resolve a per-timeframe APR override, falling back to the global default.

    Exact precedent: alpha.frame.hold_max_bars.<regime>.<tf> (services/alpha_frame_writer.py).
    Used for alpha.ensemble.min_passing_features/max_feature_weight/meta_fdr_min_cells
    (todo 164) -- 5m/15m/1d see byte-identical behavior since no per-tf key is set for them.
    """
    return _cfg(cfg, f"{key_base}.{tf}", default)


def _assert_feasible_thresholds(
    cfg: dict[str, Any],
    tfs: Iterable[str],
    global_min_passing_features: int,
    global_max_feature_weight: float,
) -> None:
    """Fail loud if any timeframe's effective (min_passing_features, max_feature_weight)
    pair cannot produce a valid normalized weight vector under the cap.

    N features each at the cap must be able to sum to >= 1.0 (migration 164's original
    5 * 0.20 = 1.0 math) -- a silently infeasible per-tf override would otherwise produce a
    broken/degenerate weight vector instead of a clear error (todo 164, "silent wrong
    answers are worse than loud crashes").
    """
    for tf in tfs:
        n = _resolve_per_tf(cfg, "alpha.ensemble.min_passing_features", tf, global_min_passing_features)
        cap = _resolve_per_tf(cfg, "alpha.ensemble.max_feature_weight", tf, global_max_feature_weight)
        if n * cap < 1.0:
            raise RuntimeError(
                f"ensemble_trainer: infeasible thresholds for tf={tf!r}: "
                f"min_passing_features={n} * max_feature_weight={cap} = {n * cap:.4f} < 1.0 "
                "-- no normalized weight vector can satisfy both constraints simultaneously."
            )
```

`services/ensemble_trainer.py` currently has no `collections.abc` import — `Any` comes from
`from typing import Any` at line 48, but `Iterable` is not yet imported anywhere in this
file. Add a new import line directly below line 48 (`from typing import Any`):

```python
from collections.abc import Iterable
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_ensemble_trainer.py -k "ResolvePerTf or AssertFeasible" -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add services/ensemble_trainer.py tests/unit/test_ensemble_trainer.py
git commit -m "feat(164): per-tf APR resolver + feasibility assertion for ensemble thresholds"
```

---

### Task B2: Wire per-tf resolution into `_meta_eligible` and `_process_stratum`

**Files:**
- Modify: `services/ensemble_trainer.py:347-375` (`_meta_eligible`)
- Modify: `services/ensemble_trainer.py:721-920ish` (`_process_stratum`)
- Modify: `services/ensemble_trainer.py:~617-619, ~664-671, ~655` (`_execute_inner` call sites)
- Test: `tests/unit/test_ensemble_trainer.py`

**Interfaces:**
- Consumes: `_resolve_per_tf` from Task B1.
- Produces: `_meta_eligible(fdr_pass_rows, cfg, min_fraction, min_cells)` (new `cfg` param
  inserted second); `_process_stratum(..., cfg=cfg)` (new keyword-only `cfg` param).

- [ ] **Step 1: Write the failing test for `_meta_eligible`'s per-tf resolution**

Add to `tests/unit/test_ensemble_trainer.py`:

```python
from services.ensemble_trainer import _meta_eligible


class TestMetaEligiblePerTf:
    def test_per_tf_min_cells_override_relaxes_1h(self) -> None:
        """A feature with only 2 cells for 1h is excluded under the global min_cells=3
        floor, but included once alpha.ensemble.meta_fdr_min_cells.1h=2 is set."""
        rows = [
            {"feature_name": "momentum_z_fast", "tf": "1h", "fdr_pass_rate": 1.0, "n_cells": 2},
        ]
        assert _meta_eligible(rows, {}, min_fraction=0.5, min_cells=3) == {}

        cfg = {"alpha.ensemble.meta_fdr_min_cells.1h": "2"}
        result = _meta_eligible(rows, cfg, min_fraction=0.5, min_cells=3)
        assert result == {"1h": {"momentum_z_fast"}}

    def test_other_tf_unaffected_by_1h_override(self) -> None:
        rows = [
            {"feature_name": "momentum_z_fast", "tf": "15m", "fdr_pass_rate": 1.0, "n_cells": 2},
        ]
        cfg = {"alpha.ensemble.meta_fdr_min_cells.1h": "2"}
        assert _meta_eligible(rows, cfg, min_fraction=0.5, min_cells=3) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_ensemble_trainer.py -k MetaEligiblePerTf -v`
Expected: FAIL — `TypeError: _meta_eligible() takes 3 positional arguments but 4 were given`

- [ ] **Step 3: Update `_meta_eligible`'s signature and body**

Replace `services/ensemble_trainer.py:347-375` with:

```python
def _meta_eligible(
    fdr_pass_rows: list[dict], cfg: dict[str, Any], min_fraction: float, min_cells: int
) -> dict[str, set[str]]:
    """Return, per timeframe, feature names whose BH-FDR pass-rate across that
    timeframe's eligible cells meets the threshold.

    Scoped per-tf rather than pooled globally: timeframes are not exchangeable draws of
    the same experiment (different bars/day, different noise floor, different horizon),
    so pooling BH-FDR outcomes across all 4 timeframes into one fraction conflates
    cross-timeframe power differences with feature quality — a feature genuinely strong
    at 1d can get vetoed everywhere by a weak showing in 5m noise. Each row must carry
    'feature_name', 'tf', 'fdr_pass_rate', 'n_cells'.

    min_cells is the GLOBAL fallback; alpha.ensemble.meta_fdr_min_cells.<tf> (todo 164)
    resolves per-timeframe via _resolve_per_tf, falling back to min_cells when unset --
    excludes (feature, tf) pairs with too little evidence to make the fraction meaningful.

    Denominator (fdr_pass_rate) is restricted to cross-sectional cells that pass all
    ensemble eligibility filters (symbol='POOLED', is_pooled=true, regime != '_pooled',
    reliable=true, ic_sharpe_hac IS NOT NULL, passes_walkforward=true, plus the
    flag-gated significance clause -- see `_eligibility_where()`) — the same population
    consumed by _process_stratum.
    """
    result: dict[str, set[str]] = {}
    for r in fdr_pass_rows:
        effective_min_cells = _resolve_per_tf(
            cfg, "alpha.ensemble.meta_fdr_min_cells", r["tf"], min_cells
        )
        if r["n_cells"] < effective_min_cells:
            continue
        if r["fdr_pass_rate"] >= min_fraction:
            result.setdefault(r["tf"], set()).add(r["feature_name"])
    return result
```

- [ ] **Step 4: Update the `_meta_eligible` call site in `_execute_inner`**

Modify `services/ensemble_trainer.py` around line 617-619:

```python
            meta_eligible_by_tf = _meta_eligible(
                fdr_pass_rows, cfg, config.meta_fdr_min_fraction, config.meta_fdr_min_cells
            )
```

- [ ] **Step 5: Add the feasibility assertion call in `_execute_inner`**

Immediately after the strata enumeration query (around line 654, right after
`self.logger.info("ensemble_trainer.strata_found", stratum_count=len(strata_rows))`), add:

```python
            _assert_feasible_thresholds(
                cfg,
                {stratum["tf"] for stratum in strata_rows},
                config.min_passing_features,
                config.max_feature_weight,
            )
```

- [ ] **Step 6: Thread `cfg` into `_process_stratum` and resolve per-tf thresholds**

Modify `_process_stratum`'s signature (around line 721-729) to add `cfg: dict[str, Any]`:

```python
    async def _process_stratum(
        self,
        conn: asyncpg.Connection,
        tf: str,
        regime: str,
        feature_cols: list[str],
        config: EnsembleConfig,
        cfg: dict[str, Any],
        meta_eligible_features: set[str],
    ) -> bool:
```

Right after `log = self.logger.bind(tf=tf, regime=regime)` (around line 737), add:

```python
        min_passing_features = _resolve_per_tf(
            cfg, "alpha.ensemble.min_passing_features", tf, config.min_passing_features
        )
        max_feature_weight = _resolve_per_tf(
            cfg, "alpha.ensemble.max_feature_weight", tf, config.max_feature_weight
        )
```

Replace the two `config.min_passing_features` gate checks (around lines 781-787 and
804-810) with `min_passing_features` (the locally-resolved variable):

```python
        if len(selected) < min_passing_features:
            log.warning(
                "ensemble_trainer.stratum_skipped_min_features",
                n_features=len(selected),
                min_required=min_passing_features,
            )
            return False
```

```python
        if len(col_subset) < min_passing_features:
            log.warning(
                "ensemble_trainer.stratum_skipped_missing_cols",
                n_cols=len(col_subset),
                min_required=min_passing_features,
            )
            return False
```

The only remaining use of `config.max_feature_weight` inside `_process_stratum`'s body is
the `resolve_stratum_weights(...)` call (around line 910-921). Replace it:

```python
        weight_result = resolve_stratum_weights(
            config.weight_method,
            aged_quality_weights,
            cov_matrix,
            corr_matrix,
            ic_sharpes,
            ic_signs,
            max_feature_weight,
            config.max_cluster_corr,
            config.max_cluster_weight,
            config.mv_condition_max,
        )
```

(Only the 7th positional argument changes, from `config.max_feature_weight` to the
locally-resolved `max_feature_weight` variable from Step 6 above — every other argument is
unchanged.) Leave the `self.logger.info("ensemble_trainer.config_loaded", ...,
max_feature_weight=config.max_feature_weight, ...)` line (around line 518) untouched — it
logs the global startup snapshot, which is correct there.

- [ ] **Step 7: Update the `_process_stratum` call site in `_execute_inner`**

Modify the call around line 664-671:

```python
                wrote = await self._process_stratum(
                    conn=conn,
                    tf=tf,
                    regime=regime,
                    feature_cols=feature_cols,
                    config=config,
                    cfg=cfg,
                    meta_eligible_features=meta_eligible_by_tf.get(tf, set()),
                )
```

- [ ] **Step 8: Run the full test suite for this file**

Run: `.venv/bin/pytest tests/unit/test_ensemble_trainer.py tests/unit/test_ensemble_trainer_weight_method.py tests/unit/test_ensemble_trainer_ic_input.py -v`
Expected: PASS — all existing tests plus the new `MetaEligiblePerTf` tests

- [ ] **Step 9: Commit**

```bash
git add services/ensemble_trainer.py tests/unit/test_ensemble_trainer.py
git commit -m "feat(164): resolve ensemble eligibility thresholds per-timeframe"
```

---

### Task B3: Migration for the two `1h` APR keys

**Files:**
- Create: `production/migrations/245_ensemble_1h_eligibility_thresholds.sql`

- [ ] **Step 1: Write the migration**

```sql
-- Migration 245: alpha.ensemble.{min_passing_features,max_feature_weight}.1h APR keys (todo 164)
--
-- 1h has comparable statistical power to 15m (median effective-N 13,754 vs 15m's 39,776;
-- CI width 0.0515 vs 0.0514 -- statistically indistinguishable) but only 1,395 total
-- base-eligible (symbol x regime x lookahead) cells vs 15m's 4,185 (~1/3 the population).
-- Live-verified via a real ensemble_trainer.py re-run (weight_version
-- debug_1h_investigation, cleaned up after): 1h strata were attempted on every regime and
-- skipped on every regime, purely because no single (1h, regime) stratum could ever
-- assemble the global min_passing_features=5 distinct qualifying features from that
-- smaller population.
--
-- Seed values are [initial_estimate], calibrated against 1h's actual achievable population
-- (~1/3 of 15m's) rather than guessed: min_passing_features=3 paired with
-- max_feature_weight=0.34 (3 * 0.34 = 1.02 >= 1.0, satisfying the same feasibility
-- constraint migration 164's original 5 * 0.20 = 1.0 pair encodes -- see
-- ensemble_trainer.py's _assert_feasible_thresholds, which enforces this at startup for
-- every configured timeframe). 5m/15m/1d are unaffected -- no per-tf key is set for them,
-- so they keep today's global-default behavior byte-for-byte.
--
-- Explicitly NOT addressed here: alpha.ensemble.meta_fdr_min_cells.1h. The live-debug
-- evidence above pins 1h's failure to min_passing_features, not this key -- seeding a
-- value for it with no supporting evidence would be undisciplined tuning. If 1h still
-- under-produces strata after this migration lands, check whether meta_fdr_min_cells is
-- now the binding constraint before setting alpha.ensemble.meta_fdr_min_cells.1h.
--
-- Also NOT addressed here: 1d's genuine small-sample power problem (median effective-N
-- 1,222, min 143, CI width 3x wider than every other timeframe) -- that needs a real
-- small-sample statistical treatment, not a threshold tweak, and is scoped as its own
-- follow-up todo, not this migration.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.ensemble.min_passing_features.1h',
    'int',
    '3',
    1, 10,
    '[initial_estimate] Per-timeframe override of alpha.ensemble.min_passing_features for '
    '1h (todo 164). 1h''s base-eligible population is ~1/3 of 15m''s despite comparable '
    'per-cell statistical power (comparable effective-N and CI width) -- the global '
    'default of 5 structurally excludes every 1h regime stratum. Paired with '
    'max_feature_weight.1h=0.34 to satisfy the n*cap>=1.0 feasibility constraint (asserted '
    'at startup by ensemble_trainer.py). Not an ML learning target.'
),
(
    'alpha.ensemble.max_feature_weight.1h',
    'float',
    '0.34',
    0.10, 1.00,
    '[initial_estimate] Per-timeframe override of alpha.ensemble.max_feature_weight for 1h '
    '(todo 164). Paired with min_passing_features.1h=3 so 3*0.34=1.02>=1.0 remains a '
    'feasible normalized-weight-vector constraint (asserted at startup by '
    'ensemble_trainer.py''s _assert_feasible_thresholds). Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.ensemble.min_passing_features.1h', '3', 1),
    ('alpha.ensemble.max_feature_weight.1h', '0.34', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.ensemble.min_passing_features.1h', 1, '3', 'migration_245',
     'Seed 1h-specific ensemble eligibility floor, todo 164 [initial_estimate]'),
    (NOW(), 'alpha.ensemble.max_feature_weight.1h', 1, '0.34', 'migration_245',
     'Seed 1h-specific concentration cap paired with min_passing_features.1h, todo 164 [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
```

- [ ] **Step 2: Apply the migration**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/245_ensemble_1h_eligibility_thresholds.sql`
Expected: `BEGIN` / `INSERT 0 2` (x3, or `INSERT 0 0` if already applied) / `COMMIT`

- [ ] **Step 3: Verify both keys are readable**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT config_key, config_value FROM config_state WHERE config_key LIKE 'alpha.ensemble.%.1h'"`
Expected: 2 rows — `min_passing_features.1h = 3`, `max_feature_weight.1h = 0.34`

- [ ] **Step 4: Commit**

```bash
git add production/migrations/245_ensemble_1h_eligibility_thresholds.sql
git commit -m "feat(164): seed 1h-specific ensemble eligibility APR keys"
```

---

### Task B3.5: Migration for `alpha.ensemble.meta_fdr_min_cells.1h` (emergent, evidence-based)

**Context (why this task exists — not in the original plan):** Task B4's live verification run
(executed after B3 shipped) confirmed `1h` still wrote **zero** strata on every regime even with
`min_passing_features.1h=3`/`max_feature_weight.1h=0.34` live — the log showed every `1h` regime
arriving at the `min_passing_features` gate with only 1-2 meta-eligible features, or zero IC rows
at all. This is the exact contingency migration 245's own comments flagged as needing a live
check before touching `meta_fdr_min_cells.1h`. That check has now been done, live, against
`feature_ic_scores` — not guessed. Evidence:

At `meta_fdr_min_cells=3` (current global default), exactly 3 features are meta-eligible for
`tf='1h'` corpus-wide: `gap_z` (n_cells=4, fdr_pass_rate=0.5), `momentum_z_fast` (n_cells=3,
rate=0.667), `dist_from_high_fast` (n_cells=3, rate=0.667). At `meta_fdr_min_cells=2`, 8 more
features clear the bar (all at n_cells=2, rate>=0.5): `vol_asymmetry_z`, `days_to_month_end`,
`month_position`, `range_to_close`, `ofi_div`, `quarter_position`, `shannon`,
`vol_skew_product` — total 11 meta-eligible names. Checking actual per-regime co-occurrence
of those 11 (query: `feature_ic_scores` filtered to the full eligibility_where, `tf='1h'`,
`feature_name IN (...)`, grouped by `regime`):

| regime | meta-eligible features present | count |
|---|---|---|
| high_bear | dist_from_high_fast, momentum_z_fast, ofi_div, vol_asymmetry_z | 4 |
| mid_bull | gap_z, quarter_position, range_to_close, shannon, vol_asymmetry_z | 5 |
| mid_bear | days_to_month_end, gap_z, month_position | 3 |
| low_bull | quarter_position, range_to_close, vol_skew_product | 3 |
| mid_neutral | dist_from_high_fast, momentum_z_fast, ofi_div | 3 |
| low_neutral | days_to_month_end, month_position | 2 (still short of 3) |
| high_neutral | (none) | 0 (zero IC rows entirely — a different, deeper population gap `meta_fdr_min_cells` cannot fix) |

5 of 7 `1h` regimes would clear the `min_passing_features.1h=3` floor at `meta_fdr_min_cells.1h=2`.
`low_neutral`/`high_neutral` would remain unfixed — an honest, acceptable partial outcome (not
every regime needs to produce alpha; the goal is unblocking `1h` at all, not universal coverage).

**min_cells=2, not 1:** `_meta_eligible`'s own docstring already documents why: "a single-cell
100% pass rate is a tautology, not replication." 2 is the minimum floor that still requires real
cross-cell agreement (mirrors `frame_gate_passes`' own >=2 day-cluster minimum for a bootstrap CI
to be formed at all).

**Files:**
- Create: `production/migrations/246_ensemble_1h_meta_fdr_min_cells.sql`

- [ ] **Step 1: Write the migration**

```sql
-- Migration 246: alpha.ensemble.meta_fdr_min_cells.1h APR key (todo 164, emergent follow-up)
--
-- Migration 245 seeded min_passing_features.1h=3/max_feature_weight.1h=0.34, but a live
-- ensemble_trainer.py re-run (weight_version debug_164_1h_verify, cleaned up after)
-- confirmed 1h STILL wrote zero strata on every regime -- the real bottleneck sits one gate
-- upstream, at meta_fdr_min_cells (global default 3), which migration 245 deliberately left
-- unseeded pending exactly this live evidence.
--
-- Live-queried against feature_ic_scores (2026-07-21): at min_cells=3, only 3 features are
-- meta-eligible for tf='1h' corpus-wide (gap_z, momentum_z_fast, dist_from_high_fast). At
-- min_cells=2, 8 more clear the bar (vol_asymmetry_z, days_to_month_end, month_position,
-- range_to_close, ofi_div, quarter_position, shannon, vol_skew_product) -- checking actual
-- per-regime co-occurrence of those 11 names confirms 5 of 7 1h regimes (high_bear: 4
-- features, mid_bull: 5, mid_bear: 3, low_bull: 3, mid_neutral: 3) would clear the
-- min_passing_features.1h=3 floor. low_neutral (2 features) and high_neutral (zero IC rows
-- entirely) remain unfixed by this key -- an honest partial outcome, not a full fix for
-- every regime.
--
-- Seed 2, not 1: _meta_eligible's own docstring warns a single-cell 100% pass rate is a
-- tautology, not replication -- 2 is the minimum floor requiring real cross-cell agreement,
-- mirroring frame_gate_passes' own >=2 day-cluster minimum for a bootstrap CI to exist.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.ensemble.meta_fdr_min_cells.1h',
    'int',
    '2',
    2, 10,
    '[initial_estimate] Per-timeframe override of alpha.ensemble.meta_fdr_min_cells for 1h '
    '(todo 164, emergent follow-up to migration 245). Live-queried against feature_ic_scores: '
    'at the global default of 3, only 3 features are meta-eligible for 1h corpus-wide; at 2, '
    '5 of 7 1h regimes assemble enough co-occurring meta-eligible features to clear '
    'min_passing_features.1h=3. Floor kept at 2 (not 1) since a single-cell pass rate is a '
    'tautology, not replication (see _meta_eligible docstring). Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.ensemble.meta_fdr_min_cells.1h', '2', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.ensemble.meta_fdr_min_cells.1h', 1, '2', 'migration_246',
     'Seed 1h-specific meta-FDR cross-cell floor, live-verified against feature_ic_scores after '
     'migration 245 alone proved insufficient to unblock 1h, todo 164 [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
```

- [ ] **Step 2: Apply the migration**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/246_ensemble_1h_meta_fdr_min_cells.sql`
Expected: `BEGIN` / `INSERT 0 1` (x3, or `INSERT 0 0` if already applied) / `COMMIT`

- [ ] **Step 3: Verify the key is readable**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT config_key, config_value FROM config_state WHERE config_key = 'alpha.ensemble.meta_fdr_min_cells.1h'"`
Expected: one row, `config_value = 2`

- [ ] **Step 4: Commit**

```bash
git add production/migrations/246_ensemble_1h_meta_fdr_min_cells.sql
git commit -m "feat(164): seed alpha.ensemble.meta_fdr_min_cells.1h, live-verified fix for 1h zero-strata blackout"
```

---

### Task B4: Live verification — confirm `1h` now writes strata

**Files:** none (verification only)

- [ ] **Step 1: Re-run `ensemble_trainer.py` under a throwaway weight_version**

Run: `.venv/bin/python services/ensemble_trainer.py --weight-version debug_164_1h_verify --sign-symmetric`

- [ ] **Step 2: Confirm `1h` strata were written**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT tf, COUNT(*) FROM ensemble_weights WHERE weight_version = 'debug_164_1h_verify' GROUP BY tf"`
Expected: a row for `tf = '1h'` with count > 0 (previously 0 for every regime, per the
todo's live-debug evidence)

- [ ] **Step 3: Clean up the throwaway weight_version**

Run:
```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
DELETE FROM ensemble_weights WHERE weight_version = 'debug_164_1h_verify';
DELETE FROM ensemble_alpha WHERE weight_version = 'debug_164_1h_verify';
"
```
Expected: `DELETE <n>` for both, confirming no residue is left in the champion/challenger
weight-version namespace.

No commit for this task — verification only, no file changes.

---

### Task B5: File the `1d` follow-up todo

**Files:**
- Create: `.planning/todos/pending/166-1d-ensemble-eligibility-small-sample-treatment.md`

- [ ] **Step 1: Write the todo**

```markdown
---
status: pending
priority: P2
filed: 2026-07-21
source: split out of todo 164 -- the 1h portion (population-scarcity, mechanical per-tf
  APR fix) shipped separately; this is 1d's genuinely different failure mode (real
  statistical power problem), explicitly scoped by todo 164 as needing its own plan
  rather than a threshold tweak.
---

# 1d ensemble eligibility needs a real small-sample statistical treatment, not a threshold tweak

## What's wrong

`1d`'s median effective-N (`n_independent`) is 1,222 (min observed: 143) -- ~32x fewer than
`15m`'s 39,776. Average CI width is 0.166, over 3x wider than every other timeframe. With
~20 years of history fragmenting to ~5,000-7,500 daily bars total, further split across
regime cells, `1d`'s `ic_ci_lower > 0` significance test runs with an order of magnitude
less statistical power than 5m/15m/1h. A real IC effect that would easily clear the bar at
higher frequencies can fail here purely from estimation noise (wide CI), not a weak point
estimate -- a Type II error risk, not evidence of absent signal.

This is a genuinely different failure mode than `1h`'s (population-scarcity, fixed via
per-timeframe APR threshold overrides -- see `alpha.ensemble.min_passing_features.1h` /
`max_feature_weight.1h`, migration 245). Do not apply the same fix here: `1d`'s problem is
real estimation noise from too few independent observations, not a miscalibrated count
threshold, and a threshold nudge would either manufacture false coverage or do nothing.

## Fix direction (needs real design, not a parameter tweak)

A properly small-sample-appropriate statistical treatment -- e.g. a Bayesian shrinkage IC
estimator that correctly widens its own uncertainty bounds rather than a frequentist CI too
wide to ever exclude zero with confidence at N~1,000-2,000, or a day-clustered bootstrap
calibrated for `1d`'s achievable cell count (mirrors FRAME-04's own day-clustered bootstrap
CI machinery in `services/counterfactual_tracker.py`, already built and reused for todo
165's regime-stratified OOS gate). This is real methodology work -- scope it as its own
plan, not a same-session follow-on to todo 164.

## References

- `services/ic_engine.py` -- where `1d`'s IC scores are computed
- `services/ensemble_trainer.py`: `_meta_eligible()`, `_process_stratum()` -- the
  eligibility gates that consume `1d`'s (thin) IC scores
- `docs/superpowers/specs/2026-07-21-regime-stratified-promotion-and-per-timeframe-eligibility-design.md`
  -- design doc that split this out of todo 164
- Live numbers above from direct queries against `feature_ic_scores`, 2026-07-21
```

- [ ] **Step 2: Add to `PRIORITIES.md`**

Read `.planning/todos/PRIORITIES.md`, find the P2 section, and add a one-line entry:
`166-1d-ensemble-eligibility-small-sample-treatment.md` with a short description matching
the todo's title, following the existing entries' format exactly.

- [ ] **Step 3: Commit**

```bash
git add .planning/todos/pending/166-1d-ensemble-eligibility-small-sample-treatment.md .planning/todos/PRIORITIES.md
git commit -m "docs(166): file 1d ensemble eligibility small-sample treatment, split from todo 164"
```

---

## Part C — Close out todos 164 and 165

### Task C1: Move todos 164 and 165 to completed, update PRIORITIES.md

**Files:**
- Modify: `.planning/todos/pending/165-regime-stratified-promotion-criteria.md` (move)
- Modify: `.planning/todos/pending/164-per-timeframe-ensemble-eligibility-thresholds.md` (move)
- Modify: `.planning/todos/PRIORITIES.md`

- [ ] **Step 1: Move both todo files to completed**

Run:
```bash
mkdir -p .planning/todos/completed
git mv .planning/todos/pending/165-regime-stratified-promotion-criteria.md .planning/todos/completed/
git mv .planning/todos/pending/164-per-timeframe-ensemble-eligibility-thresholds.md .planning/todos/completed/
```

- [ ] **Step 2: Append a closure note to each moved file**

Add a short section at the end of each moved file:

For `165-regime-stratified-promotion-criteria.md`:
```markdown
## Closed 2026-07-21

Regime-stratified OOS gate shipped: `evaluate_frame_gate` generalized with a grouping-key
+ coverage-floor parameter (`services/counterfactual_tracker.py`), wired into
`scripts/analysis/phase143_1_08_shadow_validation.py`'s C2/C7 criteria, new pre-registered
`alpha.validation.regime_gate_min_clusters` APR key (migration 244). Re-run against real
143.1-08 data; result recorded in `143.1-08-SHADOW-VALIDATION.md` section 7.
```

For `164-per-timeframe-ensemble-eligibility-thresholds.md`:
```markdown
## Closed 2026-07-21 (1h portion only)

`1h` fixed: per-timeframe APR resolution for `min_passing_features`/`max_feature_weight`/
`meta_fdr_min_cells` (`services/ensemble_trainer.py`, migration 245), plus a startup
feasibility assertion. Live-verified: `1h` now writes strata under a throwaway
weight_version re-run (previously 0 on every regime). `1d`'s genuinely different
small-sample power problem split out to todo 166 (pending), per this todo's own scoping.
```

- [ ] **Step 3: Remove both entries from `PRIORITIES.md`'s pending sections**

Read `.planning/todos/PRIORITIES.md` and delete the lines referencing
`164-per-timeframe-ensemble-eligibility-thresholds.md` and
`165-regime-stratified-promotion-criteria.md` (they were both filed same-session, so
likely near the top of the P0/P1 sections — confirm by grepping the file for `164` and
`165` before editing).

- [ ] **Step 4: Commit**

```bash
git add .planning/todos/completed/165-regime-stratified-promotion-criteria.md \
        .planning/todos/completed/164-per-timeframe-ensemble-eligibility-thresholds.md \
        .planning/todos/PRIORITIES.md
git commit -m "docs(164,165): close regime-stratified promotion gate + 1h eligibility fix"
```

---

## Final Step: Run the full unit suite

- [ ] Run: `.venv/bin/pytest tests/unit/ -q`
- [ ] Expected: all green, no regressions introduced by any task above.
