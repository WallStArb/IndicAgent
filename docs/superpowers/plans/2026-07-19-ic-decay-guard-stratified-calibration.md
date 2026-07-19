# IC Decay Regime-Shift Guard: Stratified, Self-Calibrating, Two-Sided — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `services/ic_engine.py`'s `_run_lifecycle_hook` regime-shift guard, which currently pools every timeframe and regime_group into one flat fraction compared against a guessed, empirically-unvalidated threshold (`alpha.decay.regime_shift_fraction = 0.60`) that sits ~35 points below this corpus's own known-normal failure rate (~96-98%, per the already-established EIC-04 gate). The guard will trip on effectively every future run, permanently freezing feature lifecycle promotion/demotion. This plan replaces it with a per-`(tf, regime_group)` stratified, self-calibrating, two-sided guard.

**Architecture:** A new pure function `evaluate_guard_fraction()` in `src/intelligence/statistics/ic_math.py` takes a stratum's current fail-fraction plus its own rolling history and returns a verdict (`ok` / `hold_high` / `alert_low` / `insufficient_cells`) against a band that starts as seeded, empirically-grounded rails and narrows toward a robust (median/MAD) empirical band once enough history exists — never widening past the rails. `_run_lifecycle_hook` does all I/O: stratify active cells by `(tf, regime_group)` via a one-shot `market_regimes` lookup, read each stratum's history from `integrity_monitor` (reusing the existing `subject` column — already precedented by `src/config/vocabulary_drift.py`), call the pure function once per stratum, and write one row per stratum every run (not just on hold) so calibration history actually accumulates.

**Tech Stack:** Python 3.14, psycopg2 (sync, matches existing `_run_lifecycle_hook` connection style), numpy (median/MAD), pytest, PostgreSQL/TimescaleDB (`integrity_monitor`, `market_regimes`, `config_schema`/`config_state`/`config_history`).

## Global Constraints

- All new tunable numeric values MUST be APR-backed (`config_state` via `ConfigService.get_sync()`), never module constants — CLAUDE.md APR mandate.
- Every new APR key needs a provenance tag in its `config_schema.description`: use `[rca_analysis]` for the two hard rails (grounded in this session's RCA against the EIC-04 base rate) and `[conventional]` for the statistical-convention constants (z-score, window size, floors) — **never** `[initial_estimate]`, since that provenance is what caused the original defect.
- `ICEngineConfig` is `@dataclasses.dataclass(frozen=True)` (`services/ic_engine.py:405-406`) — every field needs a default value, because direct-construction test sites elsewhere in the suite (`tests/unit/test_hac_ic_sharpe.py`) construct it without the full field list and must not break on field-count growth.
- No new database table. Reuse `integrity_monitor` (already has a `subject` text column, currently written as `NULL` by this guard) and its existing unique constraint `(monitor_type, training_window_end, metric_name, COALESCE(subject, ''), evaluated_at)`.
- `_evaluate_staleness()` (`services/ic_engine.py:2935`) stays untouched — it is already a pure, diagnostic-only, wall-clock function with no coupling to this guard. Only its call site's position changes (must run even when the guard holds).
- Migration file goes in `production/migrations/` as `237_ic_decay_guard_stratified_calibration.sql` (236 is the current highest migration number, confirmed via `ls production/migrations/ | grep -oE "^[0-9]+" | sort -n | tail -1`).
- Exception variable name is `error`, not `exc` (CLAUDE.md).
- Never use `datetime.now()` or `datetime.utcnow()` — `datetime.now(UTC)` only (not touched in this plan, but don't introduce a violation).

---

## File Structure

| File | Responsibility |
|---|---|
| `production/migrations/237_ic_decay_guard_stratified_calibration.sql` | Create (new) — seeds 6 new APR keys, marks the retired key's schema description superseded |
| `src/intelligence/statistics/ic_math.py` | Modify — add `GuardVerdict` dataclass + `evaluate_guard_fraction()` pure function |
| `tests/unit/test_ic_math_guard_fraction.py` | Create (new) — unit tests for the pure function in isolation |
| `services/ic_engine.py` | Modify — `ICEngineConfig` (remove 1 field, add 6), `_run_lifecycle_hook` Step 3 rewrite + Step 0 idempotency key + Step 6 ordering fix |
| `tests/unit/test_ic_engine_lifecycle_hook.py` | Modify — fake cursor gains 2 new query branches, `_make_config` field swap, obsolete overrides removed, regime-shift tests rewritten for the stratified/self-calibrating design |

---

## Task 1: `evaluate_guard_fraction()` pure function in `ic_math.py`

**Files:**
- Modify: `src/intelligence/statistics/ic_math.py` (add near the bottom, after `_compute_ic_rolling_metrics` — the file's existing organization groups related statistics together; this is a new, independent section)
- Test: `tests/unit/test_ic_math_guard_fraction.py` (new file)

**Interfaces:**
- Produces: `GuardVerdict` (frozen dataclass), `evaluate_guard_fraction(fail_fraction: float, n_cells: int, history: Sequence[float], *, min_cells: int, min_history: int, band_z: float, rail_lo: float, rail_hi: float) -> GuardVerdict` — this is what Task 4 (`_run_lifecycle_hook`) calls once per stratum.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_ic_math_guard_fraction.py`:

```python
"""Unit tests: evaluate_guard_fraction (ic_decay guard stratified calibration, todo 144).

Pure Python -- no DB, no Kafka. Exercises the decision logic in isolation: cold-start
rails, empirical-band takeover at min_history, MAD-zero degeneracy guard, rail
intersection clamping, the min-cells floor, and both guard tails.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.intelligence.statistics.ic_math import GuardVerdict, evaluate_guard_fraction

_RAILS = dict(min_cells=100, min_history=8, band_z=3.0, rail_lo=0.85, rail_hi=0.995)


def test_below_min_cells_is_insufficient_cells():
    """A stratum with fewer active cells than the floor is never hold-authoritative."""
    verdict = evaluate_guard_fraction(0.99, n_cells=50, history=[], **_RAILS)
    assert verdict.status == "insufficient_cells"


def test_min_cells_boundary_is_inclusive():
    """Exactly min_cells active cells IS evaluated (>=, not >)."""
    verdict = evaluate_guard_fraction(0.50, n_cells=100, history=[], **_RAILS)
    assert verdict.status != "insufficient_cells"


def test_cold_start_within_seeded_rails_is_ok():
    """No history yet: the live-incident fraction (0.9618) sits inside the seeded
    rails [0.85, 0.995] -- this is the exact regression case for the original bug,
    where the old 0.60 threshold incorrectly held on ordinary variation."""
    verdict = evaluate_guard_fraction(0.9618, n_cells=57000, history=[], **_RAILS)
    assert verdict.status == "ok"
    assert verdict.band_source == "seeded"


def test_cold_start_above_rail_hi_holds():
    verdict = evaluate_guard_fraction(0.999, n_cells=57000, history=[], **_RAILS)
    assert verdict.status == "hold_high"
    assert verdict.band_source == "seeded"


def test_cold_start_below_rail_lo_alerts():
    verdict = evaluate_guard_fraction(0.50, n_cells=57000, history=[], **_RAILS)
    assert verdict.status == "alert_low"
    assert verdict.band_source == "seeded"


def test_history_below_min_history_still_uses_seeded_rails():
    """7 prior evaluations (one short of min_history=8) must not activate the
    empirical band yet."""
    history = [0.96] * 7
    verdict = evaluate_guard_fraction(0.9618, n_cells=57000, history=history, **_RAILS)
    assert verdict.band_source == "seeded"


def test_empirical_band_activates_at_min_history():
    """8 prior evaluations activates the empirical (median/MAD) band."""
    history = [0.96, 0.97, 0.96, 0.98, 0.95, 0.97, 0.96, 0.97]
    verdict = evaluate_guard_fraction(0.9618, n_cells=57000, history=history, **_RAILS)
    assert verdict.band_source == "empirical"
    assert verdict.status == "ok"


def test_empirical_band_can_tighten_but_never_widen_past_rails():
    """History clustered very tightly around 0.96 would (via median +/- 3*1.4826*MAD)
    produce a band narrower than the seeded rails -- confirm it's clamped INSIDE
    [rail_lo, rail_hi], never wider."""
    history = [0.960, 0.961, 0.960, 0.962, 0.959, 0.961, 0.960, 0.961]
    verdict = evaluate_guard_fraction(0.9618, n_cells=57000, history=history, **_RAILS)
    assert verdict.band_lo >= _RAILS["rail_lo"]
    assert verdict.band_hi <= _RAILS["rail_hi"]
    assert verdict.band_hi < _RAILS["rail_hi"]  # actually tightened, not just clamped to rail


def test_zero_mad_degenerate_history_falls_back_to_seeded_band():
    """All 8 history values identical -> MAD=0 -> a naive band would collapse to a
    single point and flag nearly anything. Must fall back to the seeded rails
    instead of a zero-width band."""
    history = [0.96] * 8
    verdict = evaluate_guard_fraction(0.9618, n_cells=57000, history=history, **_RAILS)
    assert verdict.status == "ok"
    assert verdict.band_lo <= 0.9618 <= verdict.band_hi
    assert verdict.band_hi - verdict.band_lo > 0.001  # not degenerate


def test_empirical_band_flags_genuine_excursion_above_recent_history():
    """History steady at ~0.96; a genuine spike to 0.999 must hold even though
    0.999 < rail_hi (0.995 is exceeded here, so this also trips the rail -- use a
    value between the tightened empirical band and the rail to isolate the
    empirical-band effect specifically)."""
    history = [0.960, 0.961, 0.960, 0.962, 0.959, 0.961, 0.960, 0.961]
    # Empirical hi from this history is well under 0.99; 0.994 is inside the rail
    # (0.995) but should still exceed the tightened empirical band.
    verdict = evaluate_guard_fraction(0.994, n_cells=57000, history=history, **_RAILS)
    assert verdict.status == "hold_high"
    assert verdict.band_source == "empirical"


def test_verdict_is_frozen_dataclass():
    verdict = evaluate_guard_fraction(0.90, n_cells=57000, history=[], **_RAILS)
    assert isinstance(verdict, GuardVerdict)
    import dataclasses

    assert dataclasses.is_dataclass(verdict)
    try:
        verdict.status = "ok"  # type: ignore[misc]
        raised = False
    except dataclasses.FrozenInstanceError:
        raised = True
    assert raised
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_ic_math_guard_fraction.py -v`
Expected: FAIL — `ImportError: cannot import name 'GuardVerdict' from 'src.intelligence.statistics.ic_math'`

- [ ] **Step 3: Implement `GuardVerdict` and `evaluate_guard_fraction()`**

Add to `src/intelligence/statistics/ic_math.py`. First, add the needed imports at the top of the file (near the existing `from typing import Protocol` line):

```python
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol
```

(`Sequence` comes from `collections.abc`, not `typing` — this project's ruff config enables pyupgrade's UP035, which flags `typing.Sequence` as deprecated; `collections.abc.Sequence` is the correct modern import and works identically for the type hint here.)

Then append this new section at the end of the file (after `_compute_ic_rolling_metrics`):

```python
# ---------------------------------------------------------------------------
# Stratified regime-shift guard (todo 144): pure decision, no DB/clock/config.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GuardVerdict:
    """Verdict for one (tf, regime_group) stratum's fail-fraction this run.

    band_source distinguishes a cold-start decision (seeded rails only, no
    history yet) from a calibrated one (empirical median/MAD band, intersected
    with the rails) -- callers can log/alert differently on "seeded" verdicts
    to signal the guard hasn't self-calibrated yet for that stratum.
    """

    status: Literal["ok", "hold_high", "alert_low", "insufficient_cells"]
    band_lo: float
    band_hi: float
    band_source: Literal["seeded", "empirical"]
    n_history: int


def evaluate_guard_fraction(
    fail_fraction: float,
    n_cells: int,
    history: Sequence[float],
    *,
    min_cells: int,
    min_history: int,
    band_z: float,
    rail_lo: float,
    rail_hi: float,
) -> GuardVerdict:
    """Decide whether one stratum's fail-fraction is ordinary or anomalous.

    Two layers, always intersected so the empirical layer can only TIGHTEN the
    seeded rails, never widen past them (a slowly-drifting baseline cannot
    self-normalize an emerging problem into "ok"):

    1. Seeded rails [rail_lo, rail_hi] -- always active, empirically grounded
       against this corpus's known base rate (not a guess).
    2. Empirical band (median +/- band_z * 1.4826*MAD over `history`) -- only
       once len(history) >= min_history. Falls back to the seeded rails if the
       history is degenerate (MAD == 0), since a zero-width band would flag
       almost any value.

    A stratum with fewer than min_cells active cells is never hold-authoritative
    (status="insufficient_cells") -- its fraction is too noisy (small-N binomial
    variance) to trust either as a hold trigger or as history for other strata.
    """
    if n_cells < min_cells:
        return GuardVerdict(
            status="insufficient_cells",
            band_lo=rail_lo,
            band_hi=rail_hi,
            band_source="seeded",
            n_history=len(history),
        )

    n_history = len(history)
    if n_history >= min_history:
        history_arr = np.asarray(history, dtype=np.float64)
        median = float(np.median(history_arr))
        mad = float(np.median(np.abs(history_arr - median)))
        if mad > 0.0:
            robust_std = 1.4826 * mad
            band_lo = max(median - band_z * robust_std, rail_lo)
            band_hi = min(median + band_z * robust_std, rail_hi)
            band_source: Literal["seeded", "empirical"] = "empirical"
        else:
            # Degenerate history (zero spread) -- fall back to the rails rather
            # than collapse to a single point.
            band_lo, band_hi = rail_lo, rail_hi
            band_source = "seeded"
    else:
        band_lo, band_hi = rail_lo, rail_hi
        band_source = "seeded"

    if fail_fraction > band_hi:
        status: Literal["ok", "hold_high", "alert_low"] = "hold_high"
    elif fail_fraction < band_lo:
        status = "alert_low"
    else:
        status = "ok"

    return GuardVerdict(
        status=status,
        band_lo=band_lo,
        band_hi=band_hi,
        band_source=band_source,
        n_history=n_history,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_ic_math_guard_fraction.py -v`
Expected: All 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/statistics/ic_math.py tests/unit/test_ic_math_guard_fraction.py
git commit -m "feat(ic_math): add evaluate_guard_fraction pure decision function (todo 144)"
```

---

## Task 2: Migration 237 — new APR keys, retire the broken one

**Files:**
- Create: `production/migrations/237_ic_decay_guard_stratified_calibration.sql`

**Interfaces:**
- Produces: 6 new `config_state`/`config_schema` rows Task 3's `ICEngineConfig.from_apr()` reads by exact key name: `alpha.decay.guard_fail_rate_max`, `alpha.decay.guard_fail_rate_min`, `alpha.decay.guard_band_z`, `alpha.decay.guard_min_cells`, `alpha.decay.guard_min_history`, `alpha.decay.guard_history_window`.

- [ ] **Step 1: Write the migration**

```sql
-- Migration 237: stratified, self-calibrating regime-shift guard (todo 144)
--
-- Replaces the single flat alpha.decay.regime_shift_fraction threshold (0.60,
-- [initial_estimate], never empirically validated) with per-(tf, regime_group)
-- stratified rails + an empirical band that self-calibrates once history exists.
--
-- The RCA (2026-07-19 session) found the old 0.60 threshold sits ~35 points below
-- this corpus's own known-normal failure rate: EIC-04 already established a 2-4%
-- pass rate (35/1585=2.21%, 54/1425=3.79%) as this corpus's steady state under
-- proper FDR correction, i.e. 96-98% failure is NORMAL, not a regime shift. The old
-- threshold trips on effectively every run.
--
-- guard_fail_rate_max/guard_fail_rate_min are [rca_analysis], not [initial_estimate]
-- -- deliberately not repeating the mistake being fixed. guard_band_z/min_cells/
-- min_history/history_window are [conventional] statistical constants.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.decay.guard_fail_rate_max',
    'float',
    '0.995',
    0.5, 1.0,
    '[rca_analysis] Upper rail for the per-(tf, regime_group) lifecycle regime-shift '
    'guard (todo 144). Above this fraction of active cells failing simultaneously, '
    'even historical survivors are dying together -- hold all lifecycle transitions. '
    'Grounded in the 2026-07-19 RCA against EIC-04''s established 96-98%% normal '
    'failure-rate base (35/1585=2.21%%, 54/1425=3.79%% pass rates). Not an ML '
    'learning target.'
),
(
    'alpha.decay.guard_fail_rate_min',
    'float',
    '0.85',
    0.0, 0.99,
    '[rca_analysis] Lower rail for the per-(tf, regime_group) lifecycle regime-shift '
    'guard (todo 144). Below this fraction failing (i.e. a suspiciously HIGH pass '
    'rate, 4-7x the known ~2-4%% base), alert (do not hold) -- likely CI '
    'overconfidence (see todo 091, _fisher_z_ci may be too narrow) or a measurement '
    'bug, not genuine mass recovery. Not an ML learning target.'
),
(
    'alpha.decay.guard_band_z',
    'float',
    '3.0',
    1.0, 6.0,
    '[conventional] Z-multiplier (three-sigma) on the robust-scaled (1.4826*MAD) '
    'empirical band for the regime-shift guard (todo 144), once a stratum has '
    'enough history (see guard_min_history). Not an ML learning target.'
),
(
    'alpha.decay.guard_min_cells',
    'int',
    '100',
    10, 10000,
    '[conventional] Minimum active POOLED cells a (tf, regime_group) stratum needs '
    'before its fail-fraction is trusted as hold-authoritative (todo 144). Binomial '
    'standard error of a fraction at p~0.9, n=100 is ~0.03 -- tight enough to trust. '
    'Below this floor the stratum is diagnostic-only. Not an ML learning target.'
),
(
    'alpha.decay.guard_min_history',
    'int',
    '8',
    3, 100,
    '[conventional] Minimum prior evaluations a (tf, regime_group) stratum needs '
    'before the empirical median/MAD band takes over from the seeded rails (todo '
    '144) -- minimum sane N for a robust scale estimate. Not an ML learning target.'
),
(
    'alpha.decay.guard_history_window',
    'int',
    '20',
    5, 500,
    '[conventional] Rolling window (most recent evaluations) used to compute each '
    'stratum''s empirical median/MAD band for the regime-shift guard (todo 144). '
    'Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.decay.guard_fail_rate_max', '0.995', 1),
    ('alpha.decay.guard_fail_rate_min', '0.85', 1),
    ('alpha.decay.guard_band_z', '3.0', 1),
    ('alpha.decay.guard_min_cells', '100', 1),
    ('alpha.decay.guard_min_history', '8', 1),
    ('alpha.decay.guard_history_window', '20', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.decay.guard_fail_rate_max', 1, '0.995', 'migration_237',
     'RCA-grounded upper rail replacing the miscalibrated flat regime_shift_fraction threshold [rca_analysis]'),
    (NOW(), 'alpha.decay.guard_fail_rate_min', 1, '0.85', 'migration_237',
     'RCA-grounded lower rail, new two-sided guard tail [rca_analysis]'),
    (NOW(), 'alpha.decay.guard_band_z', 1, '3.0', 'migration_237',
     'Three-sigma robust band multiplier [conventional]'),
    (NOW(), 'alpha.decay.guard_min_cells', 1, '100', 'migration_237',
     'Minimum active cells for hold authority, binomial SE argument [conventional]'),
    (NOW(), 'alpha.decay.guard_min_history', 1, '8', 'migration_237',
     'Minimum history before empirical band activates [conventional]'),
    (NOW(), 'alpha.decay.guard_history_window', 1, '20', 'migration_237',
     'Rolling window for empirical band calculation [conventional]')
ON CONFLICT DO NOTHING;

-- Retire the broken flat threshold. Keep the config_state/config_history rows for
-- provenance/lineage (per todo 144's explicit instruction) -- only mark the schema
-- description as superseded so a future reader doesn't mistake it for live.
UPDATE config_schema
SET description = '[SUPERSEDED by todo 144, migration 237 -- see alpha.decay.guard_* '
    'keys] Was: fraction of (feature, symbol, tf) cells simultaneously showing decay '
    'that classifies an event as a market regime shift. No longer read by '
    'ic_engine.py as of migration 237 -- the flat 0.60 threshold sat ~35 points '
    'below this corpus''s known-normal 96-98%% failure rate and tripped on '
    'effectively every run.'
WHERE config_key = 'alpha.decay.regime_shift_fraction';

COMMIT;
```

- [ ] **Step 2: Apply the migration**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/237_ic_decay_guard_stratified_calibration.sql`
Expected output: `BEGIN` / six `INSERT 0 1` (or `INSERT 0 0` on conflict) pairs / `UPDATE 1` / `COMMIT`

- [ ] **Step 3: Verify the new keys**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -A -c "SELECT config_key, config_value FROM config_state WHERE config_key LIKE 'alpha.decay.guard_%' ORDER BY config_key;"`
Expected: 6 rows matching the seeded values above.

- [ ] **Step 4: Commit**

```bash
git add production/migrations/237_ic_decay_guard_stratified_calibration.sql
git commit -m "feat(migration): seed stratified regime-shift guard APR keys (todo 144)"
```

---

## Task 3: `ICEngineConfig` — remove the broken field, add the new ones

**Files:**
- Modify: `services/ic_engine.py:439-442` (field removal/addition), `services/ic_engine.py:565-567` (from_apr read removal/addition)
- Test: `tests/unit/test_ic_engine_lifecycle_hook.py:236-265` (`_make_config` helper — updated in Task 5, not here, since Task 5 owns the full test-file rewrite; this task only needs the production code to import cleanly)

**Interfaces:**
- Consumes: nothing new.
- Produces: `ICEngineConfig` instances now expose `guard_fail_rate_max: float`, `guard_fail_rate_min: float`, `guard_band_z: float`, `guard_min_cells: int`, `guard_min_history: int`, `guard_history_window: int` — Task 4's `_run_lifecycle_hook` rewrite reads these via `config.guard_*`. `decay_regime_shift_fraction` no longer exists on the class.

- [ ] **Step 1: Remove the broken field**

In `services/ic_engine.py`, remove this line (currently line 440):

```python
    decay_regime_shift_fraction: float = 0.60
```

- [ ] **Step 2: Add the 6 new fields**

Immediately after the line that was `decay_materiality_threshold: float = 0.005` (line 439, now directly followed by `decay_recovery_min_observations`), add:

```python
    # Todo 144: stratified, self-calibrating regime-shift guard, replacing the flat
    # decay_regime_shift_fraction (removed above). Rails are RCA-grounded against
    # EIC-04's established 96-98% normal failure-rate base, not guesses -- see
    # migration 237. Defaulted for the same reason as every other post-143 field:
    # pre-existing direct ICEngineConfig(...) construction sites must not break on
    # this dataclass's field-count growth.
    guard_fail_rate_max: float = 0.995
    guard_fail_rate_min: float = 0.85
    guard_band_z: float = 3.0
    guard_min_cells: int = 100
    guard_min_history: int = 8
    guard_history_window: int = 20
```

- [ ] **Step 3: Remove the broken `from_apr()` read**

Remove these lines (currently 565-567):

```python
            decay_regime_shift_fraction=float(
                cfg.get_sync("alpha.decay.regime_shift_fraction", 0.60)
            ),
```

- [ ] **Step 4: Add the 6 new `from_apr()` reads**

Immediately after the `decay_materiality_threshold=float(...)` block (which now directly precedes `decay_recovery_min_observations=...`), add:

```python
            # Todo 144: stratified regime-shift guard rails (migration 237).
            guard_fail_rate_max=float(cfg.get_sync("alpha.decay.guard_fail_rate_max", 0.995)),
            guard_fail_rate_min=float(cfg.get_sync("alpha.decay.guard_fail_rate_min", 0.85)),
            guard_band_z=float(cfg.get_sync("alpha.decay.guard_band_z", 3.0)),
            guard_min_cells=int(cfg.get_sync("alpha.decay.guard_min_cells", 100)),
            guard_min_history=int(cfg.get_sync("alpha.decay.guard_min_history", 8)),
            guard_history_window=int(cfg.get_sync("alpha.decay.guard_history_window", 20)),
```

- [ ] **Step 5: Verify the module still imports**

Run: `.venv/bin/python -c "from services.ic_engine import ICEngineConfig; c = ICEngineConfig(min_observations=500, fdr_alpha=0.05, walk_forward_folds=3, sharpe_window_size=2000, sharpe_min_windows=10, subsample_min_stride=5, min_reliable_n=100, cluster_max_corr=0.70, lookahead_fast=1, lookahead_mid=5, lookahead_slow=20, lookahead_extended=60, equity_model_enabled=True, min_obs_daily=1000, hac_max_lag=3, cs_chunk_ts=5000, symbol_fetch_chunk_rows=5000, n_workers=1); print(c.guard_fail_rate_max, c.guard_min_cells)"`
Expected: `0.995 100` — confirms the new fields exist with correct defaults and the old field is gone (this construction doesn't pass `decay_regime_shift_fraction`, so it can't mask a leftover reference).

Also run: `.venv/bin/python -c "import services.ic_engine"` — Expected: no `AttributeError`/`NameError` (this only catches import-time errors; `_run_lifecycle_hook` itself isn't touched yet in this task, so its still-present references to `config.decay_regime_shift_fraction` are fixed in Task 4, not here — don't be surprised if grep still shows them at this point).

- [ ] **Step 6: Commit**

```bash
git add services/ic_engine.py
git commit -m "refactor(ic_engine): replace decay_regime_shift_fraction with stratified guard rails (todo 144)"
```

---

## Task 4: Rewrite `_run_lifecycle_hook` Step 3 (the guard itself)

**Files:**
- Modify: `services/ic_engine.py:2654-2935` (`_run_lifecycle_hook` — Step 0 idempotency IN-list, Step 3 replacement, Step 6 ordering)

**Interfaces:**
- Consumes: `evaluate_guard_fraction`, `GuardVerdict` from `src.intelligence.statistics.ic_math` (Task 1); `config.guard_fail_rate_max/min/band_z/min_cells/min_history/history_window` (Task 3).
- Produces: no new public interface — this is the hook's internal behavior. `integrity_monitor` now receives one `guard_fail_fraction` row per `(tf, regime_group)` stratum EVERY run (not just on hold), `subject = f"tf={tf}|group={group}"`.

- [ ] **Step 1: Add the import**

At the top of `services/ic_engine.py`, find the existing import from `ic_math` (search for `from src.intelligence.statistics.ic_math import`) and add `GuardVerdict` and `evaluate_guard_fraction` to it. If no such import exists yet (the file may import ic_math functions individually inline near their call sites — check first with `grep -n "from src.intelligence.statistics.ic_math import" services/ic_engine.py`), add a new top-level import line:

```python
from src.intelligence.statistics.ic_math import GuardVerdict, evaluate_guard_fraction
```

- [ ] **Step 2: Update Step 0's idempotency IN-list**

Find (currently lines 2673-2678):

```python
        cur.execute(
            """
            SELECT 1 FROM integrity_monitor
            WHERE monitor_type = 'ic_lifecycle'
              AND training_window_end = %s
              AND metric_name IN ('decay_cells_flagged', 'regime_shift_fraction')
            LIMIT 1
            """,
            (training_window_end,),
        )
```

Replace with:

```python
        cur.execute(
            """
            SELECT 1 FROM integrity_monitor
            WHERE monitor_type = 'ic_lifecycle'
              AND training_window_end = %s
              AND metric_name IN ('decay_cells_flagged', 'guard_fail_fraction')
            LIMIT 1
            """,
            (training_window_end,),
        )
```

(`regime_shift_fraction` retired along with the flat threshold; `guard_fail_fraction` is the new per-stratum metric name written every run, so the idempotency check now correctly recognizes a run that only wrote stratum facts and held.)

- [ ] **Step 3: Replace Step 3 through Step 6 as one block**

A Fable review of this plan (2026-07-19) caught a real atomicity bug in an earlier draft of this step: committing the guard-fact inserts immediately, before Step 4/5 run, opens a crash window where a process death between that commit and Step 5's commit permanently marks `training_window_end` as "already evaluated" (via Step 0's IN-list, which now includes `guard_fail_fraction`) while Step 4's promotions/demotions never actually ran — silently freezing that window's lifecycle forever with no retry. The fix restructures Steps 3-6 so there is exactly ONE commit point covering the guard facts AND Step 4/5's writes together (atomic: either the whole run's lifecycle decision landed, or none of it did), and Step 6 (staleness gauge) appears exactly once instead of being duplicated across a hold/non-hold branch.

Find the whole block from the `# Step 3: REGIME-SHIFT GUARD FIRST` comment (currently line 2783) through the end of the function, including the existing Step 4 (per-feature aggregation, currently ~2818-2892), Step 5 (currently ~2894-2913), and Step 6 (currently ~2917-2934, ending at the `if alert:` block just before `_evaluate_staleness`'s own `def`). Replace that entire span with:

```python
    # Step 3: REGIME-SHIFT GUARD (todo 144) -- stratified per (tf, regime_group),
    # self-calibrating, two-sided. Evaluated over cells with
    # feature_status_at_eval='active' only. A stratum's fraction is compared
    # against seeded rails (empirically grounded, migration 237) that narrow
    # toward a robust empirical band once enough history exists for that stratum.
    # hold_high in ANY hold-authoritative stratum holds ALL transitions for this
    # training_window_end (conservative: one dislocated market/horizon is enough
    # reason to distrust the whole run's lifecycle decisions). alert_low never
    # holds -- promotion is already multi-run-gated by recovery_min_observations/
    # recovery_min_passes, so a single anomalously-high pass rate cannot itself
    # flip a feature's status.
    active_cells = [c for c in cell_rows if c["feature_status_at_eval"] == "active"]
    any_hold = False
    if active_cells:
        with write_conn.cursor() as cur:
            cur.execute("SELECT DISTINCT regime_group, regime_label FROM market_regimes")
            regime_label_to_group = {row[1]: row[0] for row in cur.fetchall()}

        strata: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for cell in active_cells:
            group = regime_label_to_group.get(cell["regime"], "_unmapped")
            strata[(cell["tf"], group)].append(cell)

        for (tf, group), stratum_cells in strata.items():
            subject = f"tf={tf}|group={group}"
            fail_fraction = sum(1 for c in stratum_cells if c["_failed"]) / len(stratum_cells)

            with write_conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT metric_value FROM integrity_monitor
                    WHERE monitor_type = 'ic_lifecycle'
                      AND metric_name = 'guard_fail_fraction'
                      AND subject = %s
                    ORDER BY evaluated_at DESC
                    LIMIT %s
                    """,
                    (subject, config.guard_history_window),
                )
                history = [row[0] for row in cur.fetchall()]

            verdict: GuardVerdict = evaluate_guard_fraction(
                fail_fraction,
                len(stratum_cells),
                history,
                min_cells=config.guard_min_cells,
                min_history=config.guard_min_history,
                band_z=config.guard_band_z,
                rail_lo=config.guard_fail_rate_min,
                rail_hi=config.guard_fail_rate_max,
            )

            # Always write a fact -- this is what builds calibration history.
            # threshold_value records whichever bound is nearer the current
            # fraction (the one a small drift would next violate); passed is
            # false for both guard tails, true for "ok" and "insufficient_cells"
            # (the latter made no claim to violate -- its rail-derived bounds are
            # informational only, never evaluated against this stratum).
            #
            # NOTE: deliberately no commit() here. These inserts ride in the same
            # transaction as Step 4/5 below (or, on a hold, the single commit at
            # the end of this function) -- see the atomicity note above this block.
            nearer_bound = (
                verdict.band_hi
                if abs(fail_fraction - verdict.band_hi) <= abs(fail_fraction - verdict.band_lo)
                else verdict.band_lo
            )
            passed = verdict.status not in ("hold_high", "alert_low")
            with write_conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO integrity_monitor
                        (monitor_type, subject, metric_name, metric_value,
                         threshold_value, passed, training_window_end)
                    VALUES ('ic_lifecycle', %s, 'guard_fail_fraction', %s, %s, %s, %s)
                    ON CONFLICT (monitor_type, training_window_end, metric_name,
                                 COALESCE(subject, ''), evaluated_at) DO NOTHING
                    """,
                    (subject, fail_fraction, nearer_bound, passed, training_window_end),
                )

            if verdict.status == "hold_high":
                log.warning(
                    "ic_engine.regime_shift_hold",
                    tf=tf,
                    regime_group=group,
                    fraction=fail_fraction,
                    band_lo=verdict.band_lo,
                    band_hi=verdict.band_hi,
                    band_source=verdict.band_source,
                    training_window_end=str(training_window_end),
                )
                any_hold = True
            elif verdict.status == "alert_low":
                log.warning(
                    "ic_engine.guard_suspicious_pass_rate",
                    tf=tf,
                    regime_group=group,
                    fraction=fail_fraction,
                    band_lo=verdict.band_lo,
                    band_hi=verdict.band_hi,
                    band_source=verdict.band_source,
                    training_window_end=str(training_window_end),
                )

    if not any_hold:
        # Step 4: per-feature aggregation (GROUP BY feature_name) -- demotion/promotion.
        # Unchanged from the pre-todo-144 code, just gated behind `if not any_hold:`
        # instead of being unreachable via early return.
        cells_by_feature: dict[str, list[dict]] = defaultdict(list)
        for cell in cell_rows:
            cells_by_feature[cell["feature_name"]].append(cell)

        demotion_fraction_floor = 1.0 - config.meta_fdr_min_fraction
        registry_status_by_feature = {
            f["feature_name"]: f["status"] for f in registry_svc.get_all_features()
        }

        for feature_name, cells in cells_by_feature.items():
            status = registry_status_by_feature.get(feature_name)

            if status == "active":
                active_feature_cells = [c for c in cells if c["feature_status_at_eval"] == "active"]
                if not active_feature_cells:
                    continue
                material_fail_cells = [c for c in active_feature_cells if c["_material_fail"]]
                demote_fraction = len(material_fail_cells) / len(active_feature_cells)
                if demote_fraction >= demotion_fraction_floor:
                    worst_cell = min(
                        active_feature_cells,
                        key=lambda c: c["_signed_margin"] if c["_signed_margin"] is not None else 0.0,
                    )
                    ic_n = sum(c["n_independent"] for c in active_feature_cells)
                    worst_cell_ic_value = (
                        worst_cell["ic_ci_upper"]
                        if config.sign_symmetric and worst_cell["ic_sign"] == -1
                        else worst_cell["ic_ci_lower"]
                    )
                    transitioned = registry_svc.record_transition_sync(
                        write_conn,
                        feature_name,
                        "active",
                        "shadow_only",
                        "ic_demotion",
                        ic_value=worst_cell_ic_value,
                        ic_sharpe=worst_cell["ic_sharpe_hac"],
                        ic_n=ic_n,
                    )
                    if transitioned:
                        ALPHA_DECAY_ENSEMBLE_REBUILD_TOTAL.add(1, {"feature_name": feature_name})

            elif status == "shadow_only":
                passes_fdr_count = sum(1 for c in cells if c["passes_fdr"])
                pass_fraction = passes_fdr_count / len(cells)
                passed = pass_fraction >= config.meta_fdr_min_fraction
                new_observations = sum(c["n_independent"] for c in cells)
                registry_svc.advance_shadow_counters_sync(
                    write_conn, feature_name, passed, new_observations
                )
                if registry_svc.is_promotion_eligible(
                    feature_name,
                    config.decay_recovery_min_observations,
                    config.decay_recovery_min_passes,
                ):
                    transitioned = registry_svc.record_transition_sync(
                        write_conn,
                        feature_name,
                        "shadow_only",
                        "active",
                        "ic_promotion",
                    )
                    if transitioned:
                        ALPHA_DECAY_ENSEMBLE_REBUILD_TOTAL.add(1, {"feature_name": feature_name})

        # Step 5: one integrity_monitor gate-evaluation fact per (non-hold) run.
        with write_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO integrity_monitor
                    (monitor_type, subject, metric_name, metric_value,
                     threshold_value, passed, training_window_end)
                VALUES ('ic_lifecycle', NULL, 'decay_cells_flagged', %s, %s, true, %s)
                ON CONFLICT (monitor_type, training_window_end, metric_name,
                             COALESCE(subject, ''), evaluated_at) DO NOTHING
                """,
                (
                    float(material_fail_count),
                    config.decay_materiality_threshold,
                    training_window_end,
                ),
            )

    # Single commit point for the whole hook: guard facts (Step 3) + either Step
    # 4/5's writes (non-hold) or nothing further (hold) -- atomic either way, no
    # crash window where guard facts land without Step 4/5 having run.
    write_conn.commit()

    # Step 6: IC staleness gauge (LIFECYCLE-05). Runs exactly once, regardless of
    # hold -- todo 144 fix: previously skipped entirely on hold (via early return),
    # which was incidental, not intended -- the gauge is diagnostic-only and
    # unrelated to whether lifecycle transitions ran this cycle.
    prior_completion = _get_prior_ic_engine_completion(write_conn, manifest, training_window_end)
    age_days, alert = _evaluate_staleness(
        prior_completion, datetime.now(UTC), config.ic_staleness_alert_days
    )
    IC_ENGINE_LAST_RUN_AGE_DAYS.set(age_days)
    if alert:
        log.warning(
            "ic_engine.stale",
            age_days=age_days,
            threshold=config.ic_staleness_alert_days,
        )
```

Note one expected, intentional side effect: the live 2025-12-24 hold (written under the old `regime_shift_fraction` metric name) no longer matches Step 0's updated IN-list (`'decay_cells_flagged', 'guard_fail_fraction'`), so that specific window becomes re-evaluable on a future run instead of permanently short-circuited — this is correct, not a regression: that window's original hold was itself the bug this todo fixes.

- [ ] **Step 4: Verify the module still imports and no stale references remain**

Run: `grep -n "decay_regime_shift_fraction\|regime_shift_fraction'" services/ic_engine.py`
Expected: no output (both the old field name and the old metric-name string literal are gone; `regime_shift_hold` as a log event name is fine to keep, it's just a log event label, not a metric_name string).

Run: `.venv/bin/python -c "import services.ic_engine"`
Expected: no error.

- [ ] **Step 5: Commit**

```bash
git add services/ic_engine.py
git commit -m "feat(ic_engine): stratified self-calibrating two-sided regime-shift guard (todo 144)"
```

---

## Task 5: Rewrite `tests/unit/test_ic_engine_lifecycle_hook.py` for the new guard

**Files:**
- Modify: `tests/unit/test_ic_engine_lifecycle_hook.py` (fake cursor, `_make_config`, obsolete overrides, regime-shift tests)

**Interfaces:**
- Consumes: `ICEngineConfig` (Task 3's new field set), `_run_lifecycle_hook` (Task 4's rewritten Step 3), `evaluate_guard_fraction`/`GuardVerdict` (Task 1, not called directly by these tests — they exercise the hook end-to-end, not the pure function again, since Task 1 already covers that in isolation).

- [ ] **Step 1: Extend `_FakeLifecycleCursor.execute` with the two new query branches**

In `tests/unit/test_ic_engine_lifecycle_hook.py`, inside `_FakeLifecycleCursor.execute`, add these two branches (place them before the final `self._rows = []` fallback at the end of the method, alongside the existing `if "FROM feature_ic_scores fis"` branch):

```python
        if "FROM market_regimes" in sql:
            self._rows = [
                (r["regime_group"], r["regime_label"]) for r in self.conn.market_regime_rows
            ]
            self._description = [("regime_group",), ("regime_label",)]
            return

        if "metric_name = 'guard_fail_fraction'" in sql:
            subject, _limit = params
            matching = [
                r["metric_value"]
                for r in self.conn.guard_history_rows
                if r["subject"] == subject
            ]
            self._rows = [(v,) for v in matching]
            self._description = [("metric_value",)]
            return

        if "INSERT INTO integrity_monitor" in sql and "guard_fail_fraction" in sql:
            self.conn.guard_fact_inserts.append(params)
            self._rows = []
            self._description = None
            return
```

Note: this new `INSERT ... guard_fail_fraction` branch must be checked **before** the existing generic `if "INSERT INTO integrity_monitor" in sql:` branch (which currently appends to `self.conn.integrity_inserts`) — Python `if`/`elif` order matters here; since these are separate `if` statements (not `elif`) in the existing code, and this new one returns first when it matches, place it directly above the pre-existing generic one so the more specific match wins. Re-check the method after editing: the generic `if "INSERT INTO integrity_monitor" in sql:` branch will now only ever catch inserts that do NOT mention `guard_fail_fraction` (there are none of those left after Task 4, but keep both branches for defense/clarity).

- [ ] **Step 2: Extend `_FakeLifecycleConn.__init__` with the new fixture inputs**

Replace the `__init__` method with:

```python
    def __init__(
        self,
        corpus_rows: list[dict],
        ensemble_weight_rows: list[dict] | None = None,
        existing_integrity_rows: list[dict] | None = None,
        market_regime_rows: list[dict] | None = None,
        guard_history_rows: list[dict] | None = None,
    ):
        self.corpus_rows = corpus_rows
        self.ensemble_weight_rows = ensemble_weight_rows or []
        self.existing_integrity_rows = existing_integrity_rows or []
        self.market_regime_rows = market_regime_rows or []
        self.guard_history_rows = guard_history_rows or []
        self.integrity_inserts: list[tuple] = []
        self.guard_fact_inserts: list[tuple] = []
        self.executed_sql: list[str] = []
        self.executed_params: list[tuple] = []
        self.committed = False
```

- [ ] **Step 3: Update `_make_config`**

Replace the `_make_config` function's `defaults` dict — remove the `decay_regime_shift_fraction=0.60,` line and add the 6 new fields (matching Task 3's new `ICEngineConfig` fields and the migration's seeded values):

```python
def _make_config(**overrides) -> ICEngineConfig:
    defaults = dict(
        min_observations=500,
        fdr_alpha=0.05,
        walk_forward_folds=3,
        sharpe_window_size=2000,
        sharpe_min_windows=10,
        subsample_min_stride=5,
        min_reliable_n=100,
        cluster_max_corr=0.70,
        lookahead_fast=1,
        lookahead_mid=5,
        lookahead_slow=20,
        lookahead_extended=60,
        equity_model_enabled=True,
        min_obs_daily=1000,
        hac_max_lag=3,
        cs_chunk_ts=5000,
        symbol_fetch_chunk_rows=5000,
        n_workers=1,
        decay_materiality_threshold=0.005,
        guard_fail_rate_max=0.995,
        guard_fail_rate_min=0.85,
        guard_band_z=3.0,
        guard_min_cells=100,
        guard_min_history=8,
        guard_history_window=20,
        decay_recovery_min_observations=2000,
        decay_recovery_min_passes=2,
        meta_fdr_min_fraction=0.50,
        ic_staleness_alert_days=5,
        ensemble_weight_version="v1",
        sign_symmetric=False,
    )
    defaults.update(overrides)
    return ICEngineConfig(**defaults)
```

- [ ] **Step 4: Remove the now-unnecessary `decay_regime_shift_fraction=0.99` overrides**

These 8 call sites passed `decay_regime_shift_fraction=0.99` purely to prevent the OLD flat guard from tripping in unrelated demotion/promotion/sign-symmetric tests (all of which use ~10 cells total). Under the new design, 10 cells never reaches `guard_min_cells=100`, so every stratum in these tests is automatically `insufficient_cells` (never hold-authoritative) — the override is no longer needed and the parameter no longer exists. Remove `decay_regime_shift_fraction=0.99, ` (or `, decay_regime_shift_fraction=0.99` depending on position) from each of these `_make_config(...)` calls:

- `test_demotion_triggers_on_materially_failing_active_feature` (was line 279): `config = _make_config(meta_fdr_min_fraction=0.50, decay_regime_shift_fraction=0.99)` → `config = _make_config(meta_fdr_min_fraction=0.50)`
- `test_demotion_boundary_below_threshold_not_demoted` (was line 320): same change
- `test_demotion_boundary_at_threshold_demoted` (was line 355): same change
- `test_zero_standing_weight_not_demoted` (was line 391): same change
- `test_weight_version_pinning_to_champion` (was line 589): `config = _make_config(ensemble_weight_version="v1", decay_regime_shift_fraction=0.99)` → `config = _make_config(ensemble_weight_version="v1")`
- `test_sign_symmetric_significant_contrarian_not_demoted` (was line 719): `config = _make_config(meta_fdr_min_fraction=0.50, decay_regime_shift_fraction=0.99, sign_symmetric=True)` → `config = _make_config(meta_fdr_min_fraction=0.50, sign_symmetric=True)`
- `test_sign_symmetric_ci_straddling_contrarian_is_demoted` (was line 760): same pattern
- `test_sign_symmetric_positive_cell_still_demoted` (was line 804): same pattern
- `test_sign_symmetric_off_positive_cell_decision_is_byte_identical` (was line 849): `config = _make_config(meta_fdr_min_fraction=0.50, decay_regime_shift_fraction=0.99, sign_symmetric=False)` → `config = _make_config(meta_fdr_min_fraction=0.50, sign_symmetric=False)`

- [ ] **Step 5: Rewrite the regime-shift guard section entirely**

Replace the whole `# Regime-shift guard` section (was `test_regime_shift_guard_holds_all_weights`, lines ~475-517) with:

```python
# ---------------------------------------------------------------------------
# Regime-shift guard (todo 144: stratified, self-calibrating, two-sided)
# ---------------------------------------------------------------------------


def _stratum_cells(feature_name: str, tf: str, group_regimes: list[str], n_fail: int) -> list[dict]:
    """n_fail failing + (len(group_regimes) - n_fail) passing cells, one per
    regime label in group_regimes, all at the given tf, all feature_name."""
    cells = []
    for i, regime in enumerate(group_regimes):
        failing = i < n_fail
        cells.append(
            _cell(
                feature_name,
                tf,
                regime,
                ic_ci_lower=-0.02 if failing else 0.03,
                passes_fdr=not failing,
                n_independent=1000,
                status="active",
            )
        )
    return cells


def test_regime_shift_cold_start_within_seeded_rails_does_not_hold(tmp_path):
    """Regression for the exact live incident (fraction=0.9618): 100 active cells
    in one (tf, regime_group) stratum, 96 failing, NO history yet. 0.9618 sits
    inside the seeded rails [0.85, 0.995] -- must NOT hold. This is the case the
    old flat 0.60 threshold got wrong."""
    regimes = [f"r{i}" for i in range(100)]
    cells = _stratum_cells("featA", "5m", regimes, n_fail=96)
    ew = [
        {"tf": "5m", "regime": r, "feature_name": "featA", "weight_version": "v1", "weight": 0.5}
        for r in regimes
    ]
    market_regimes = [{"regime_group": "equity", "regime_label": r} for r in regimes]
    conn = _FakeLifecycleConn(cells, ensemble_weight_rows=ew, market_regime_rows=market_regimes)
    registry = _FakeRegistryService({"featA": {"status": "active"}})

    _run_lifecycle_hook(conn, registry, _make_config(meta_fdr_min_fraction=0.50), _T1, _make_manifest(tmp_path))

    # Did not hold: Step 4 ran, so featA's material-fail fraction (96/100=96% >=
    # 50% floor) demoted it -- proving the run proceeded past the guard, unlike
    # the old code which would have held here.
    assert len(registry.transition_calls) == 1
    assert registry.transition_calls[0][:4] == ("featA", "active", "shadow_only", "ic_demotion")
    # One guard fact was still written for calibration history.
    assert len(conn.guard_fact_inserts) == 1
    subject, fraction, threshold, passed, window = conn.guard_fact_inserts[0]
    assert subject == "tf=5m|group=equity"
    assert fraction == 0.96
    assert passed is True


def test_regime_shift_cold_start_above_rail_holds(tmp_path):
    """100 active cells, all 100 failing (fraction=1.0, above the 0.995 rail) ->
    hold_high -> zero transitions, Step 4/5 skipped."""
    regimes = [f"r{i}" for i in range(100)]
    cells = _stratum_cells("featA", "5m", regimes, n_fail=100)
    ew = [
        {"tf": "5m", "regime": r, "feature_name": "featA", "weight_version": "v1", "weight": 0.5}
        for r in regimes
    ]
    market_regimes = [{"regime_group": "equity", "regime_label": r} for r in regimes]
    conn = _FakeLifecycleConn(cells, ensemble_weight_rows=ew, market_regime_rows=market_regimes)
    registry = _FakeRegistryService({"featA": {"status": "active"}})

    _run_lifecycle_hook(conn, registry, _make_config(meta_fdr_min_fraction=0.50), _T1, _make_manifest(tmp_path))

    assert registry.transition_calls == []
    assert len(conn.guard_fact_inserts) == 1
    _, fraction, _, passed, _ = conn.guard_fact_inserts[0]
    assert fraction == 1.0
    assert passed is False


def test_regime_shift_small_stratum_never_hold_authoritative(tmp_path):
    """10 active cells (below guard_min_cells=100), all failing -- must NOT hold
    (insufficient_cells is never authoritative), even though the fraction (1.0)
    would trip the rail if it were evaluated. Demotion still proceeds normally."""
    regimes = [f"r{i}" for i in range(10)]
    cells = _stratum_cells("featA", "5m", regimes, n_fail=10)
    ew = [
        {"tf": "5m", "regime": r, "feature_name": "featA", "weight_version": "v1", "weight": 0.5}
        for r in regimes
    ]
    market_regimes = [{"regime_group": "equity", "regime_label": r} for r in regimes]
    conn = _FakeLifecycleConn(cells, ensemble_weight_rows=ew, market_regime_rows=market_regimes)
    registry = _FakeRegistryService({"featA": {"status": "active"}})

    _run_lifecycle_hook(conn, registry, _make_config(meta_fdr_min_fraction=0.50), _T1, _make_manifest(tmp_path))

    assert len(registry.transition_calls) == 1  # demotion proceeded, guard didn't block it
    assert len(conn.guard_fact_inserts) == 1
    _, _, _, passed, _ = conn.guard_fact_inserts[0]
    assert passed is True  # insufficient_cells is not a violation


def test_regime_shift_suspiciously_low_fail_rate_alerts_not_holds(tmp_path):
    """100 active cells, only 10 failing (fraction=0.10, below the 0.85 rail) ->
    alert_low -> a fact is written with passed=False, but transitions still
    proceed normally (no hold on the low tail, per design)."""
    regimes = [f"r{i}" for i in range(100)]
    cells = _stratum_cells("featB", "15m", regimes, n_fail=10)
    market_regimes = [{"regime_group": "equity", "regime_label": r} for r in regimes]
    conn = _FakeLifecycleConn(cells, market_regime_rows=market_regimes)
    registry = _FakeRegistryService({"featB": {"status": "active"}})

    _run_lifecycle_hook(conn, registry, _make_config(meta_fdr_min_fraction=0.50), _T1, _make_manifest(tmp_path))

    assert len(conn.guard_fact_inserts) == 1
    _, fraction, _, passed, _ = conn.guard_fact_inserts[0]
    assert fraction == 0.10
    assert passed is False
    # Did not hold: Step 4 ran (90/100 = 90% pass, well below the 50% demote floor
    # applied to the 10% material-fail fraction -- no demotion, but that's Step 4
    # logic proceeding normally, not the guard blocking it).
    assert registry.transition_calls == []


def test_regime_shift_unmapped_regime_label_buckets_to_unmapped_stratum(tmp_path):
    """A cell whose regime label isn't found in the market_regimes lookup (e.g.
    market_regime_rows is empty, or genuinely missing that label) must bucket into
    a ('<tf>', '_unmapped') stratum -- and that stratum must still be evaluated
    (not silently dropped), just under the '_unmapped' group key. This is a real
    code path (services/ic_engine.py's `.get(cell["regime"], "_unmapped")`
    fallback) that every OTHER test in this file exercises incidentally (they all
    pass empty or non-matching market_regime_rows unless testing the mapping
    itself), so it needs its own explicit assertion rather than staying
    accidentally-covered."""
    regimes = [f"r{i}" for i in range(100)]
    cells = _stratum_cells("featA", "5m", regimes, n_fail=100)
    ew = [
        {"tf": "5m", "regime": r, "feature_name": "featA", "weight_version": "v1", "weight": 0.5}
        for r in regimes
    ]
    # No market_regime_rows at all -- every regime label fails the lookup.
    conn = _FakeLifecycleConn(cells, ensemble_weight_rows=ew, market_regime_rows=[])
    registry = _FakeRegistryService({"featA": {"status": "active"}})

    _run_lifecycle_hook(conn, registry, _make_config(meta_fdr_min_fraction=0.50), _T1, _make_manifest(tmp_path))

    assert len(conn.guard_fact_inserts) == 1
    subject = conn.guard_fact_inserts[0][0]
    assert subject == "tf=5m|group=_unmapped"
    # Still evaluated (100 cells >= min_cells=100, 100% fail >= 0.995 rail) -> held.
    assert registry.transition_calls == []


def test_regime_shift_two_independent_strata_only_failing_one_holds(tmp_path):
    """(5m, equity) at 100% fail holds; (1h, equity) at 90% fail (within rails)
    does not -- but ANY hold-authoritative stratum holding holds the ENTIRE run
    (all transitions), proving strata are evaluated independently but the hold
    decision is global."""
    regimes = [f"r{i}" for i in range(100)]
    hot_cells = _stratum_cells("featA", "5m", regimes, n_fail=100)
    cold_cells = _stratum_cells("featB", "1h", regimes, n_fail=90)
    market_regimes = [{"regime_group": "equity", "regime_label": r} for r in regimes]
    conn = _FakeLifecycleConn(
        hot_cells + cold_cells,
        ensemble_weight_rows=[
            {"tf": "5m", "regime": r, "feature_name": "featA", "weight_version": "v1", "weight": 0.5}
            for r in regimes
        ],
        market_regime_rows=market_regimes,
    )
    registry = _FakeRegistryService(
        {"featA": {"status": "active"}, "featB": {"status": "active"}}
    )

    _run_lifecycle_hook(conn, registry, _make_config(meta_fdr_min_fraction=0.50), _T1, _make_manifest(tmp_path))

    assert registry.transition_calls == []  # global hold, even though only one stratum tripped
    assert len(conn.guard_fact_inserts) == 2  # both strata still wrote calibration facts


def test_regime_shift_empirical_band_takes_over_after_min_history(tmp_path):
    """A stratum with 8 prior evaluations all near 0.96 develops a tight empirical
    band; a new fraction of 0.994 (inside the seeded rail 0.995, but outside the
    tightened empirical band) now holds -- proving the empirical layer, not just
    the rails, is live."""
    regimes = [f"r{i}" for i in range(100)]
    cells = _stratum_cells("featA", "5m", regimes, n_fail=99)  # 0.99 fraction this run
    ew = [
        {"tf": "5m", "regime": r, "feature_name": "featA", "weight_version": "v1", "weight": 0.5}
        for r in regimes
    ]
    market_regimes = [{"regime_group": "equity", "regime_label": r} for r in regimes]
    history_rows = [
        {"subject": "tf=5m|group=equity", "metric_value": v}
        for v in [0.960, 0.961, 0.960, 0.962, 0.959, 0.961, 0.960, 0.961]
    ]
    conn = _FakeLifecycleConn(
        cells,
        ensemble_weight_rows=ew,
        market_regime_rows=market_regimes,
        guard_history_rows=history_rows,
    )
    registry = _FakeRegistryService({"featA": {"status": "active"}})

    _run_lifecycle_hook(conn, registry, _make_config(meta_fdr_min_fraction=0.50), _T1, _make_manifest(tmp_path))

    assert registry.transition_calls == []  # held: 0.99 is far outside the tight empirical band
```

- [ ] **Step 6: Fix the old assertion in `test_idempotency_short_circuit_on_existing_fact`**

This test is unaffected by field/metric-name changes (it only checks that `feature_ic_scores` isn't queried when `existing_integrity_rows` already has a matching `training_window_end`) — verify it still passes as-is; no edit needed unless Step 7's full run finds otherwise.

- [ ] **Step 7: Run the full lifecycle-hook test file**

Run: `.venv/bin/pytest tests/unit/test_ic_engine_lifecycle_hook.py -v`
Expected: All tests PASS (the original demotion/promotion/idempotency/sign-symmetric/structural tests unchanged in behavior, minus their now-removed obsolete override kwarg; the new/rewritten regime-shift tests pass per their assertions above).

- [ ] **Step 8: Commit**

```bash
git add tests/unit/test_ic_engine_lifecycle_hook.py
git commit -m "test(ic_engine): rewrite lifecycle-hook regime-shift tests for stratified guard (todo 144)"
```

---

## Task 6: Full suite verification and todo closure

**Files:**
- Modify: `.planning/todos/pending/144-ic-decay-regime-shift-guard-miscalibrated.md` → move to `.planning/todos/completed/`

- [ ] **Step 1: Run the full unit suite**

Run: `.venv/bin/pytest tests/unit/ -q`
Expected: all tests pass, zero failures, zero errors (this also catches any other test file that might construct `ICEngineConfig` directly and reference the removed `decay_regime_shift_fraction` field — if any surface here, fix them the same way as Task 5 Step 4).

- [ ] **Step 2: Search for any other reference to the retired field/metric name**

Run: `grep -rn "decay_regime_shift_fraction\|'regime_shift_fraction'" --include="*.py" /home/bg/dev/indicagent`
Expected: no output.

- [ ] **Step 3: Move the todo to completed**

```bash
git mv .planning/todos/pending/144-ic-decay-regime-shift-guard-miscalibrated.md .planning/todos/completed/144-ic-decay-regime-shift-guard-miscalibrated.md
```

Add a closing note at the top of the moved file (after the frontmatter, before the `# Title` line):

```markdown
**Closed 2026-07-19:** implemented per `docs/superpowers/plans/2026-07-19-ic-decay-guard-stratified-calibration.md`. Stratified per-(tf, regime_group), self-calibrating (seeded rails + empirical MAD band), two-sided (hold_high/alert_low). `evaluate_guard_fraction()` in `ic_math.py`; migration 237.
```

- [ ] **Step 4: Commit**

```bash
git add .planning/todos/completed/144-ic-decay-regime-shift-guard-miscalibrated.md
git commit -m "docs: close todo 144, IC decay regime-shift guard now stratified and self-calibrating"
```

---

## Self-Review Notes (per writing-plans skill)

**Spec coverage against todo 144's Fix section:**
- Stratification per (tf, regime_group), min-cell floor, no rollup → Task 4 Step 3, Task 1 pure function's `insufficient_cells` status. ✓
- Cold-start rails + empirical band, gated on history, intersection clamping → Task 1 (`evaluate_guard_fraction`), Task 2 (APR keys). ✓
- History store reusing `integrity_monitor.subject`, write every run → Task 4 Step 3 (always-insert). ✓
- Two-sided, one code path, asymmetric consequences → Task 1 (single function, both tails) + Task 4 (differentiated `hold_high`/`alert_low` handling). ✓
- Purity: `evaluate_guard_fraction` as a pure function in `ic_math.py` → Task 1. ✓
- APR keys named and grounded → Task 2. ✓
- Retire `alpha.decay.regime_shift_fraction`, keep row for lineage → Task 2 (UPDATE description, no DELETE). ✓
- Step 6 staleness gauge runs even on hold → Task 4 Step 3 (fall-through, not early return). ✓
- `_evaluate_staleness` untouched → confirmed, no task modifies it. ✓

**Placeholder scan:** none found — every step has complete, runnable code.

**Type consistency:** `evaluate_guard_fraction`'s signature (Task 1) matches its call site in Task 4 exactly (`fail_fraction, n_cells, history, *, min_cells, min_history, band_z, rail_lo, rail_hi`); `GuardVerdict.status` literal values (`ok`/`hold_high`/`alert_low`/`insufficient_cells`) match the branches Task 4 checks against (`verdict.status == "hold_high"`, `elif verdict.status == "alert_low"`). `ICEngineConfig` field names introduced in Task 3 (`guard_fail_rate_max`, `guard_fail_rate_min`, `guard_band_z`, `guard_min_cells`, `guard_min_history`, `guard_history_window`) match both Task 4's `config.guard_*` reads and Task 5's `_make_config` defaults exactly.

**Fable review pass (2026-07-19):** an independent Fable agent reviewed this plan against the live codebase (verified all cited line numbers current, no drift from Phase 162's unrelated parallel work) and found three real issues, now fixed inline above:

1. **Atomicity bug (most severe):** an earlier draft committed the guard-fact inserts immediately after the strata loop, before Step 4/5 ran -- a crash in between would permanently mark `training_window_end` "already evaluated" (Step 0's IN-list now includes `guard_fail_fraction`) while Step 4's promotions/demotions never actually happened, with no retry path. Fixed by restructuring Task 4 Step 3 to wrap Step 4/5 in `if not any_hold:` and use a single commit point covering everything, plus a single (not duplicated) Step 6 staleness-gauge block.
2. **Ruff violation:** `from typing import Sequence` would fail this project's UP035 lint rule. Fixed to `from collections.abc import Sequence`.
3. **Test coverage gap:** the `_unmapped` regime-label fallback path (production code's `.get(cell["regime"], "_unmapped")`) had no explicit test, only incidental coverage. Added `test_regime_shift_unmapped_regime_label_buckets_to_unmapped_stratum`.

The reviewer also confirmed several things as correct without changes needed: fake-cursor branch ordering (the new `guard_fail_fraction` INSERT branch is unambiguous since no other branch's SQL contains that substring), the `insufficient_cells` stratum's rail-derived `threshold_value` being harmless (paired with `passed=true`), the `any_hold` control flow correctly gating all of Step 4 with no leak path, and all band-math test assertions (median/MAD/band values) being numerically correct.
