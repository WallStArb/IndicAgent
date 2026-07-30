# Per-Timeframe IC Lookahead Grid Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Note (2026-07-30):** This plan shipped (migration 269, applied 2026-07-29) and its grid
> is live. But the grid's own premise for 5m/15m/1h — that the same-ET-session completeness
> gate is a correct constraint to design around, e.g. 1h's "no viable slow/extended tier" —
> is now an open question, not settled fact; see
> `.planning/todos/pending/208-intraday-same-session-forward-return-gate-inconsistent-with-trade-construction.md`.
> `1d`'s row is unaffected. Do not read this plan's rationale text below as still-current
> justification for the session gate itself.

**Goal:** Replace the single global `alpha.ic.lookahead.{fast,mid,slow,extended}` bar-count grid (currently `1/5/20/60`, identical across all four timeframes) with per-timeframe values, using the grid confirmed by todo 146's full-corpus, stride-corrected diagnostic (`5m`=1/6/12/39, `15m`=1/2/5/10, `1h`=1/2/20/60 unchanged-slow-extended, `1d`=1/2/5/10).

**Architecture:** Three independent config surfaces (`ic_engine.py`'s `ICEngineConfig`, `ensemble_ic_engine.py`'s `EnsembleICConfig`, `forward_return_writer.py`'s inline APR loader) each currently read 4 flat scalar `alpha.ic.lookahead.{scale}` keys and reuse the same values for every timeframe. Each becomes tf-keyed (`dict[str, int]` per scale, matching the existing `bootstrap_block_size: dict[str, int]` precedent already in `ICEngineConfig`). A fourth site — `ic_engine.py`'s `_run_lifecycle_hook` — filters `feature_ic_scores` by a single global `lookahead_bars` value and must become tf-scoped too, since "mid" no longer means the same bar count on every timeframe.

**Scope boundary (explicit, load-bearing):** This plan does NOT restructure `ic_engine.py`'s fixed `_SCALES = ("fast","mid","slow","extended")` tuple or the ~13 call sites that use it to build fixed-width SQL column lists and positionally-indexed numpy arrays (`returns_mat`/`complete_mat` are always shape `[n, 4]`). `1h`'s `slow`/`extended` keys stay at their current unchanged values (20/60) — todo 146's "no slow/extended tier for `1h`" finding is real, but implementing it means shrinking that array width for one timeframe only, which touches every one of those 13 sites in hot per-symbol/cross-sectional compute loops. That is a separate, higher-risk follow-up (file as its own todo at the end of this plan), not bundled into a change riding an imminent full-corpus `ic_engine` pass.

**Tech Stack:** Python 3.14, PostgreSQL/TimescaleDB (`psycopg2`), `pytest`.

## Global Constraints

- Every new/changed APR key follows the existing `config_schema`/`config_state`/`config_history` triple-insert migration pattern (see `production/migrations/252_ic_refresh_min_new_fraction.sql` for the exact template).
- `ICEngineConfig` and `EnsembleICConfig` are both frozen, picklable dataclasses shipped to `ProcessPoolExecutor` workers — no non-primitive types, no methods that can't survive pickling (plain `dict[str, int]` fields are fine; this is the same shape as the existing `bootstrap_block_size` field).
- Do NOT touch `_SCALES`, `returns_mat`/`complete_mat` shape, or any of the ~13 fixed-4-scale iteration sites in `ic_engine.py`'s per-symbol/cross-sectional compute loops (`_compute_one_regime_cell`, `_compute_symbol_tf`, `_compute_cross_sectional_tf`, and their SQL-building sections). These stay exactly as they are today.
- Do NOT run `backfill_feature_factory.py` or touch anything in that process while it's running (confirmed live PID group, started 09:48, `--compute-only --refresh --workers 3` — this plan's changes are in `ic_engine.py`/`ensemble_ic_engine.py`/`forward_return_writer.py`/migrations only, none of which that process reads).
- Full `tests/unit/` suite must be green before this is considered done — not just the touched test files.

---

## Task 1: Migration seeding per-tf `alpha.ic.lookahead.{tf}.{scale}` APR keys

**Files:**
- Create: `production/migrations/269_per_tf_ic_lookahead_grid.sql`

**Interfaces:**
- Produces: 16 new `config_state`/`config_schema` rows, keys of the form `alpha.ic.lookahead.{tf}.{scale}` for `tf in (5m, 15m, 1h, 1d)` × `scale in (fast, mid, slow, extended)`. Consumed by Tasks 2-4's `from_apr()` rewrites.

- [ ] **Step 1: Write the migration**

```sql
-- Migration 269: per-timeframe alpha.ic.lookahead.{tf}.{scale} APR keys
--
-- Replaces the single global alpha.ic.lookahead.{fast,mid,slow,extended} grid
-- (1/5/20/60, identical across all four timeframes) with per-tf values, confirmed
-- by todo 146's full-corpus, stride-corrected IC-vs-horizon diagnostic
-- (docs/research/fable-2026-07-19-lookahead-and-target-calibration-review.md Q1,
-- scripts/ops/alpha/ops_lookahead_horizon_response.py --max-symbols 80):
--
--   5m:  fast=1  mid=6  slow=12 extended=39
--   15m: fast=1  mid=2  slow=5  extended=10
--   1h:  fast=1  mid=2  slow=20 extended=60  (slow/extended UNCHANGED -- todo 146
--        found 1h has no viable slow/extended tier at all, session-bounded
--        completeness collapses to 0% by horizon=6; restructuring the code to
--        actually drop those tiers is deferred to a separate follow-up todo, not
--        done here -- these two values are seeded unchanged so existing code that
--        still reads them keeps working exactly as today, i.e. producing the same
--        near-zero-valid-row cells it already produces)
--   1d:  fast=1  mid=2  slow=5  extended=10  (1d's old extended=60 "near-optimal"
--        finding was a pre-fix flat-CI artifact, withdrawn by todo 146; every 1d
--        horizon >=20 has a stride-corrected CI half-width exceeding the point
--        estimate itself -- indistinguishable from noise)
--
-- Old global alpha.ic.lookahead.{fast,mid,slow,extended} keys are NOT deleted (still
-- read by any not-yet-updated code path / historical config_history provenance) but
-- their descriptions are updated to note supersession.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    ('alpha.ic.lookahead.5m.fast', 'int', '1', 1, 500, '[rca_analysis] 5m fast-scale lookahead in bars. Confirmed by todo 146''s full-corpus stride-corrected horizon-response diagnostic (2026-07-20). ML learning target: yes.'),
    ('alpha.ic.lookahead.5m.mid', 'int', '6', 1, 500, '[rca_analysis] 5m mid-scale lookahead in bars. Same source as 5m.fast.'),
    ('alpha.ic.lookahead.5m.slow', 'int', '12', 1, 500, '[rca_analysis] 5m slow-scale lookahead in bars. Same source as 5m.fast.'),
    ('alpha.ic.lookahead.5m.extended', 'int', '39', 1, 500, '[rca_analysis] 5m extended-scale lookahead in bars. Same source as 5m.fast.'),
    ('alpha.ic.lookahead.15m.fast', 'int', '1', 1, 500, '[rca_analysis] 15m fast-scale lookahead in bars. Confirmed by todo 146''s full-corpus stride-corrected horizon-response diagnostic (2026-07-20).'),
    ('alpha.ic.lookahead.15m.mid', 'int', '2', 1, 500, '[rca_analysis] 15m mid-scale lookahead in bars. Same source as 15m.fast.'),
    ('alpha.ic.lookahead.15m.slow', 'int', '5', 1, 500, '[rca_analysis] 15m slow-scale lookahead in bars. Same source as 15m.fast.'),
    ('alpha.ic.lookahead.15m.extended', 'int', '10', 1, 500, '[rca_analysis] 15m extended-scale lookahead in bars. Same source as 15m.fast.'),
    ('alpha.ic.lookahead.1h.fast', 'int', '1', 1, 500, '[rca_analysis] 1h fast-scale lookahead in bars. Confirmed by todo 146''s full-corpus stride-corrected horizon-response diagnostic (2026-07-20).'),
    ('alpha.ic.lookahead.1h.mid', 'int', '2', 1, 500, '[rca_analysis] 1h mid-scale lookahead in bars. Same source as 1h.fast.'),
    ('alpha.ic.lookahead.1h.slow', 'int', '20', 1, 500, '[initial_estimate, known-degenerate] UNCHANGED from the old global default. Todo 146 found 1h has no viable slow tier at all -- same-session completeness collapses to 0% well before this horizon. Structurally removing this tier requires touching ic_engine.py''s fixed _SCALES-indexed compute loops; deferred to a separate follow-up todo. This value intentionally left as-is so existing code keeps producing the same near-zero-valid-row cells it already produces today -- not a calibrated number.'),
    ('alpha.ic.lookahead.1h.extended', 'int', '60', 1, 500, '[initial_estimate, known-degenerate] UNCHANGED from the old global default. Same rationale as alpha.ic.lookahead.1h.slow.'),
    ('alpha.ic.lookahead.1d.fast', 'int', '1', 1, 500, '[rca_analysis] 1d fast-scale lookahead in bars. Confirmed by todo 146''s full-corpus stride-corrected horizon-response diagnostic (2026-07-20); supersedes the withdrawn pre-fix flat-CI "extended=60 near-optimal" finding.'),
    ('alpha.ic.lookahead.1d.mid', 'int', '2', 1, 500, '[rca_analysis] 1d mid-scale lookahead in bars. Same source as 1d.fast.'),
    ('alpha.ic.lookahead.1d.slow', 'int', '5', 1, 500, '[rca_analysis] 1d slow-scale lookahead in bars. Same source as 1d.fast.'),
    ('alpha.ic.lookahead.1d.extended', 'int', '10', 1, 500, '[rca_analysis] 1d extended-scale lookahead in bars. Same source as 1d.fast. Every 1d horizon >=20 under the stride-corrected estimator has a CI half-width exceeding its own point estimate -- 60 was never a real optimum, it was a flat-CI artifact.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.ic.lookahead.5m.fast', '1', 1),
    ('alpha.ic.lookahead.5m.mid', '6', 1),
    ('alpha.ic.lookahead.5m.slow', '12', 1),
    ('alpha.ic.lookahead.5m.extended', '39', 1),
    ('alpha.ic.lookahead.15m.fast', '1', 1),
    ('alpha.ic.lookahead.15m.mid', '2', 1),
    ('alpha.ic.lookahead.15m.slow', '5', 1),
    ('alpha.ic.lookahead.15m.extended', '10', 1),
    ('alpha.ic.lookahead.1h.fast', '1', 1),
    ('alpha.ic.lookahead.1h.mid', '2', 1),
    ('alpha.ic.lookahead.1h.slow', '20', 1),
    ('alpha.ic.lookahead.1h.extended', '60', 1),
    ('alpha.ic.lookahead.1d.fast', '1', 1),
    ('alpha.ic.lookahead.1d.mid', '2', 1),
    ('alpha.ic.lookahead.1d.slow', '5', 1),
    ('alpha.ic.lookahead.1d.extended', '10', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.ic.lookahead.5m.fast', 1, '1', 'migration_269', 'Seed per-tf lookahead grid (todo 146, confirmed 2026-07-20 full-corpus diagnostic).'),
    (NOW(), 'alpha.ic.lookahead.5m.mid', 1, '6', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.5m.slow', 1, '12', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.5m.extended', 1, '39', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.15m.fast', 1, '1', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.15m.mid', 1, '2', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.15m.slow', 1, '5', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.15m.extended', 1, '10', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.1h.fast', 1, '1', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.1h.mid', 1, '2', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.1h.slow', 1, '20', 'migration_269', 'Unchanged placeholder -- 1h slow tier is known-degenerate, structural fix deferred (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.1h.extended', 1, '60', 'migration_269', 'Unchanged placeholder -- 1h extended tier is known-degenerate, structural fix deferred (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.1d.fast', 1, '1', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.1d.mid', 1, '2', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.1d.slow', 1, '5', 'migration_269', 'Seed per-tf lookahead grid (todo 146).'),
    (NOW(), 'alpha.ic.lookahead.1d.extended', 1, '10', 'migration_269', 'Seed per-tf lookahead grid (todo 146), supersedes withdrawn extended=60 finding.')
ON CONFLICT DO NOTHING;

UPDATE config_schema
SET description = description || ' [SUPERSEDED 2026-07-29 by migration 269''s per-tf alpha.ic.lookahead.{tf}.{scale} keys -- kept for historical config_history provenance, no longer read by ic_engine.py/ensemble_ic_engine.py/forward_return_writer.py after this migration''s code changes land.]'
WHERE config_key IN (
    'alpha.ic.lookahead.fast', 'alpha.ic.lookahead.mid',
    'alpha.ic.lookahead.slow', 'alpha.ic.lookahead.extended'
);

COMMIT;
```

- [ ] **Step 2: Apply the migration**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/269_per_tf_ic_lookahead_grid.sql`
Expected: `BEGIN`/`INSERT 0 16` (x2, schema+state)/`INSERT 0 16` (history)/`UPDATE 4`/`COMMIT`, no errors.

- [ ] **Step 3: Verify**

Run:
```
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT config_key, config_value FROM config_state WHERE config_key LIKE 'alpha.ic.lookahead.%.%' ORDER BY config_key;"
```
Expected: 16 rows matching the table above.

- [ ] **Step 4: Commit**

```bash
git add production/migrations/269_per_tf_ic_lookahead_grid.sql
git commit -m "feat(ic_engine): seed per-tf alpha.ic.lookahead.{tf}.{scale} APR keys (todo 146)"
```

---

## Task 2: `ICEngineConfig` (ic_engine.py) reads per-tf lookaheads

**Files:**
- Modify: `services/ic_engine.py:456-459` (field declarations), `:566-574` (`.lookaheads` property), `:605-609` (`from_apr()`), `:1742`, `:2087`, `:2690` (call sites), `:3911-3935` (`_run_lifecycle_hook`'s tf-agnostic SQL filter)
- Test: `tests/unit/test_hac_ic_sharpe.py`, `tests/unit/test_ic_engine_lifecycle_hook.py`, `tests/unit/test_ic_engine_compute_split.py:397-400`, `tests/unit/test_ic_engine_dual_write_symbol_hmm.py:66-69`, `tests/unit/test_ic_engine_fingerprint.py:64-67` (three more direct `ICEngineConfig(...)` constructions, found via a full repo-wide grep, not just the two files originally scoped)

**Interfaces:**
- Consumes: nothing new from other tasks.
- Produces: `ICEngineConfig.lookaheads_for(tf: str) -> dict[str, int]` — replaces the old `.lookaheads` property. `_run_lifecycle_hook` internals unchanged in shape (still keyed by `cell["tf"]` per row), only its SQL filter changes.

- [ ] **Step 1: Write the failing test for `lookaheads_for`**

Add to `tests/unit/test_hac_ic_sharpe.py` (near the existing `ICEngineConfig(...)` construction at line ~140):

```python
def test_lookaheads_for_returns_per_tf_values():
    """lookaheads_for(tf) must resolve each scale from that tf's own dict entry,
    not a single global scalar -- the whole point of todo 146's per-tf grid fix."""
    config = ICEngineConfig(
        min_observations=500,
        fdr_alpha=0.05,
        walk_forward_folds=3,
        sharpe_window_size=50,
        sharpe_window_size_subsampled=50,
        sharpe_min_windows=3,
        subsample_min_stride=5,
        min_reliable_n=100,
        cluster_max_corr=0.70,
        lookahead_fast={"5m": 1, "15m": 1, "1h": 1, "1d": 1},
        lookahead_mid={"5m": 6, "15m": 2, "1h": 2, "1d": 2},
        lookahead_slow={"5m": 12, "15m": 5, "1h": 20, "1d": 5},
        lookahead_extended={"5m": 39, "15m": 10, "1h": 60, "1d": 10},
        equity_model_enabled=True,
        min_obs_daily=1000,
        hac_max_lag=3,
        cs_chunk_ts=5000,
        symbol_fetch_chunk_rows=5000,
        n_workers=1,
    )
    assert config.lookaheads_for("5m") == {"fast": 1, "mid": 6, "slow": 12, "extended": 39}
    assert config.lookaheads_for("15m") == {"fast": 1, "mid": 2, "slow": 5, "extended": 10}
    assert config.lookaheads_for("1d") == {"fast": 1, "mid": 2, "slow": 5, "extended": 10}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_hac_ic_sharpe.py::test_lookaheads_for_returns_per_tf_values -v`
Expected: FAIL — `ICEngineConfig.__init__() got an unexpected keyword argument` (fields are still scalars) or `AttributeError: 'ICEngineConfig' object has no attribute 'lookaheads_for'`.

- [ ] **Step 3: Update every existing `ICEngineConfig(...)` construction site to the new dict shape**

Four files construct `ICEngineConfig` directly with scalar `lookahead_fast=1, lookahead_mid=5, lookahead_slow=20, lookahead_extended=60` (found via `grep -rn "lookahead_fast=" tests/unit/*.py`, not just the one file originally scoped — three more turned up on a full repo-wide pass):

- `tests/unit/test_hac_ic_sharpe.py` (line ~140, already read)
- `tests/unit/test_ic_engine_compute_split.py:397-400`
- `tests/unit/test_ic_engine_dual_write_symbol_hmm.py:66-69`
- `tests/unit/test_ic_engine_fingerprint.py:64-67`

In each, replace the 4-line scalar block:

```python
        lookahead_fast=1,
        lookahead_mid=5,
        lookahead_slow=20,
        lookahead_extended=60,
```

with:

```python
        lookahead_fast={"5m": 1, "15m": 1, "1h": 1, "1d": 1},
        lookahead_mid={"5m": 6, "15m": 2, "1h": 2, "1d": 2},
        lookahead_slow={"5m": 12, "15m": 5, "1h": 20, "1d": 5},
        lookahead_extended={"5m": 39, "15m": 10, "1h": 60, "1d": 10},
```

Verify each of the four sites uses this exact 4-line, 4-space-indented form before replacing (`test_hac_ic_sharpe.py`'s is already confirmed at this indentation; confirm the other three match before applying the same replacement, since a differently-indented or differently-ordered match would silently no-op or corrupt the surrounding call).

- [ ] **Step 4: Update `ICEngineConfig`'s field declarations**

In `services/ic_engine.py`, replace lines 456-459:

```python
    lookahead_fast: int
    lookahead_mid: int
    lookahead_slow: int
    lookahead_extended: int
```

with:

```python
    lookahead_fast: dict[str, int]
    lookahead_mid: dict[str, int]
    lookahead_slow: dict[str, int]
    lookahead_extended: dict[str, int]
```

- [ ] **Step 5: Replace the `.lookaheads` property with `.lookaheads_for(tf)`**

Replace lines 566-574:

```python
    @property
    def lookaheads(self) -> dict[str, int]:
        """Gradient-scale lookahead mapping — built once; frozen after construction."""
        return {
            "fast": self.lookahead_fast,
            "mid": self.lookahead_mid,
            "slow": self.lookahead_slow,
            "extended": self.lookahead_extended,
        }
```

with:

```python
    def lookaheads_for(self, tf: str) -> dict[str, int]:
        """Gradient-scale lookahead mapping for ONE timeframe (todo 146: bar counts
        differ per tf -- 60 bars is ~3 months at 1d but ~5 hours at 5m, so a single
        global grid was measuring a different real-world horizon per tf under the
        same scale name)."""
        return {
            "fast": self.lookahead_fast[tf],
            "mid": self.lookahead_mid[tf],
            "slow": self.lookahead_slow[tf],
            "extended": self.lookahead_extended[tf],
        }
```

- [ ] **Step 6: Update `from_apr()` to load per-tf**

Replace lines 605-609:

```python
            # Lookaheads per scale -- column names are gradient-scale identifiers
            lookahead_fast=int(cfg.get_sync("alpha.ic.lookahead.fast", 1)),
            lookahead_mid=int(cfg.get_sync("alpha.ic.lookahead.mid", 5)),
            lookahead_slow=int(cfg.get_sync("alpha.ic.lookahead.slow", 20)),
            lookahead_extended=int(cfg.get_sync("alpha.ic.lookahead.extended", 60)),
```

with:

```python
            # Lookaheads per (tf, scale) -- todo 146: a single global grid measured
            # a different real-world horizon per tf under the same scale name.
            lookahead_fast={
                tf: int(cfg.get_sync(f"alpha.ic.lookahead.{tf}.fast", 1))
                for tf in ("5m", "15m", "1h", "1d")
            },
            lookahead_mid={
                tf: int(cfg.get_sync(f"alpha.ic.lookahead.{tf}.mid", fb))
                for tf, fb in {"5m": 6, "15m": 2, "1h": 2, "1d": 2}.items()
            },
            lookahead_slow={
                tf: int(cfg.get_sync(f"alpha.ic.lookahead.{tf}.slow", fb))
                for tf, fb in {"5m": 12, "15m": 5, "1h": 20, "1d": 5}.items()
            },
            lookahead_extended={
                tf: int(cfg.get_sync(f"alpha.ic.lookahead.{tf}.extended", fb))
                for tf, fb in {"5m": 39, "15m": 10, "1h": 60, "1d": 10}.items()
            },
```

- [ ] **Step 7: Update the three `config.lookaheads` call sites**

Three occurrences, all inside functions that already have `tf` as a parameter (verified by reading each — `_compute_one_regime_cell` line 1712, `_compute_symbol_tf` docstring context, `_compute_cross_sectional_tf` line ~2670s):

`services/ic_engine.py:1742`: `lookaheads = config.lookaheads` → `lookaheads = config.lookaheads_for(tf)`
`services/ic_engine.py:2087`: `lookaheads = config.lookaheads` → `lookaheads = config.lookaheads_for(tf)`
`services/ic_engine.py:2690`: `lookaheads = config.lookaheads` → `lookaheads = config.lookaheads_for(tf)`

- [ ] **Step 8: Run test to verify Step 1's test now passes**

Run: `.venv/bin/pytest tests/unit/test_hac_ic_sharpe.py tests/unit/test_ic_engine_compute_split.py tests/unit/test_ic_engine_dual_write_symbol_hmm.py tests/unit/test_ic_engine_fingerprint.py -v`
Expected: All PASS, including `test_lookaheads_for_returns_per_tf_values`.

- [ ] **Step 9: Update `_make_config`'s lookahead defaults to dict form**

`tests/unit/test_ic_engine_lifecycle_hook.py`'s `_make_config` factory (line 289) has its own scalar defaults independent of `test_hac_ic_sharpe.py`. Replace lines 299-302:

```python
        lookahead_fast=1,
        lookahead_mid=5,
        lookahead_slow=20,
        lookahead_extended=60,
```

with:

```python
        lookahead_fast={"5m": 1, "15m": 1, "1h": 1, "1d": 1},
        lookahead_mid={"5m": 5, "15m": 5, "1h": 5, "1d": 5},
        lookahead_slow={"5m": 20, "15m": 20, "1h": 20, "1d": 20},
        lookahead_extended={"5m": 60, "15m": 60, "1h": 60, "1d": 60},
```

(Deliberately keeping every tf at the SAME value here, unlike the real migration 269 grid — every existing test in this file constructs cells at a single tf and asserts on the exact `lookahead_bars` values 1/5/20/60 baked into `_cell(...)` calls throughout the file; changing `_make_config`'s defaults to genuinely different per-tf numbers would silently break every other test in this file that doesn't override `lookahead_mid`. Only the one test updated in Step 11 below needs a real per-tf-varying override.)

- [ ] **Step 10: Fix the existing test that exercises tf-agnostic lookahead pinning to use per-tf values, and watch it fail against the still-scalar production code**

`test_lookahead_pinning_uses_only_mid_lookahead_rows` (line 845) is the ONE existing test that already exercises this exact gate query, currently with all cells on a single tf (`"5m"`) and `config = _make_config(lookahead_mid=5, ...)`. Extend it to prove the tf-scoping actually works — add a second tf whose mid lookahead is a DIFFERENT bar count, and a same-bar-count-but-wrong-tf row that must NOT be picked up:

Replace lines 849-872:

```python
    config = _make_config(lookahead_mid=5, meta_fdr_min_fraction=0.50)
    cells = []
    for tf, regime in [("5m", "r0"), ("5m", "r1"), ("5m", "r2"), ("5m", "r3")]:
        for lookahead in (1, 5, 20, 60):
            cells.append(
                _cell(
                    "featB",
                    tf,
                    regime,
                    ic_ci_lower=0.03,
                    passes_fdr=True,
                    n_independent=1000,
                    status="shadow_only",
                    lookahead_bars=lookahead,
                )
            )
    conn = _FakeLifecycleConn(cells)
    registry = _FakeRegistryService({"featB": {"status": "shadow_only", "eligible": False}})

    _run_lifecycle_hook(conn, registry, config, _T1, _make_manifest(tmp_path))

    assert registry.advance_calls == [
        ("featB", True, 4000)
    ]  # 4 mid-lookahead cells * 1000, not 16*1000
```

with:

```python
    config = _make_config(
        lookahead_mid={"5m": 5, "15m": 2, "1h": 2, "1d": 2},
        meta_fdr_min_fraction=0.50,
    )
    cells = []
    for tf, regime in [("5m", "r0"), ("5m", "r1"), ("5m", "r2"), ("5m", "r3")]:
        for lookahead in (1, 5, 20, 60):
            cells.append(
                _cell(
                    "featB",
                    tf,
                    regime,
                    ic_ci_lower=0.03,
                    passes_fdr=True,
                    n_independent=1000,
                    status="shadow_only",
                    lookahead_bars=lookahead,
                )
            )
    # A 15m row at lookahead_bars=5 -- same bar count as 5m's mid, but 15m's real mid
    # is 2. This row must NOT be picked up by the gate query; if it were, it would
    # prove the filter is still matching on lookahead_bars alone, ignoring tf.
    cells.append(
        _cell(
            "featB",
            "15m",
            "r0",
            ic_ci_lower=0.03,
            passes_fdr=True,
            n_independent=9999,
            status="shadow_only",
            lookahead_bars=5,
        )
    )
    conn = _FakeLifecycleConn(cells)
    registry = _FakeRegistryService({"featB": {"status": "shadow_only", "eligible": False}})

    _run_lifecycle_hook(conn, registry, config, _T1, _make_manifest(tmp_path))

    assert registry.advance_calls == [
        ("featB", True, 4000)
    ]  # 4 real 5m-mid cells * 1000; the mis-tf'd 15m/lookahead=5 row (n=9999) must be excluded
```

- [ ] **Step 11: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_ic_engine_lifecycle_hook.py::test_lookahead_pinning_uses_only_mid_lookahead_rows -v`
Expected: FAIL — with the production SQL still unchanged (`fis.lookahead_bars = %s` alone, single scalar param `config.lookahead_mid` which is now a dict, not an int), this will actually fail at the `cur.execute(..., (..., config.lookahead_mid))` call inside `_run_lifecycle_hook` itself (passing a dict where psycopg2/the fake cursor expects a scalar param) before it even gets to the assertion — confirming the old code path is broken by Task 2 Step 4's type change, which is the correct failure mode to see here.

- [ ] **Step 12: Fix `_run_lifecycle_hook`'s SQL filter**

In `services/ic_engine.py`, replace the query at lines 3915-3936:

```python
    with write_conn.cursor() as cur:
        cur.execute(
            """
            SELECT fis.feature_name, fis.tf, fis.regime, fis.ic_ci_lower, fis.ic_ci_upper,
                   fis.ic_sign, fis.passes_fdr,
                   fis.reliable, fis.n_independent, fis.feature_status_at_eval,
                   fis.ic_sharpe_hac, COALESCE(ew.weight, 0.0) AS standing_weight
            FROM feature_ic_scores fis
            LEFT JOIN ensemble_weights ew
                   ON ew.symbol = 'UNIVERSE'
                  AND ew.tf = fis.tf
                  AND ew.regime = fis.regime
                  AND ew.feature_name = fis.feature_name
                  AND ew.weight_version = %s
            WHERE fis.symbol = 'POOLED'
              AND fis.is_pooled = true
              AND fis.regime != '_pooled'
              AND fis.training_window_end = %s
              AND fis.lookahead_bars = %s
            """,
            (config.ensemble_weight_version, training_window_end, config.lookahead_mid),
        )
```

with:

```python
    # Todo 146: lookahead_mid is now tf-specific (5m=6, 15m=2, 1h=2, 1d=2) -- a bare
    # `lookahead_bars = %s` scalar can no longer correctly pin "the mid scale" across
    # all 4 timeframes in one filter, since "mid" means a different bar count per tf.
    # Match (tf, lookahead_bars) pairs explicitly instead of a single scalar.
    tf_bars_conditions = " OR ".join(
        "(fis.tf = %s AND fis.lookahead_bars = %s)" for _ in config.lookahead_mid
    )
    tf_bars_params: list[Any] = []
    for tf_key, bars in config.lookahead_mid.items():
        tf_bars_params.extend([tf_key, bars])

    with write_conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT fis.feature_name, fis.tf, fis.regime, fis.ic_ci_lower, fis.ic_ci_upper,
                   fis.ic_sign, fis.passes_fdr,
                   fis.reliable, fis.n_independent, fis.feature_status_at_eval,
                   fis.ic_sharpe_hac, COALESCE(ew.weight, 0.0) AS standing_weight
            FROM feature_ic_scores fis
            LEFT JOIN ensemble_weights ew
                   ON ew.symbol = 'UNIVERSE'
                  AND ew.tf = fis.tf
                  AND ew.regime = fis.regime
                  AND ew.feature_name = fis.feature_name
                  AND ew.weight_version = %s
            WHERE fis.symbol = 'POOLED'
              AND fis.is_pooled = true
              AND fis.regime != '_pooled'
              AND fis.training_window_end = %s
              AND ({tf_bars_conditions})
            """,
            (config.ensemble_weight_version, training_window_end, *tf_bars_params),
        )
```

- [ ] **Step 13: Update `_FakeLifecycleCursor.execute()`'s fake filtering to match the new variable-length, tf-aware params**

The fake cursor (`tests/unit/test_ic_engine_lifecycle_hook.py:58-108`) currently destructures exactly 3 params and filters on a single scalar `lookahead_bars`. It must be updated to mirror the real SQL's new shape — a `weight_version`, a `training_window_end`, then a variable-length flattened `(tf, bars, tf, bars, ...)` tail. Replace lines 73-108:

```python
        if "FROM feature_ic_scores fis" in sql:
            weight_version, training_window_end, lookahead_bars = params
            weight_lookup = {
                (r["tf"], r["regime"], r["feature_name"]): r["weight"]
                for r in self.conn.ensemble_weight_rows
                if r["weight_version"] == weight_version
            }
            cols = [
                "feature_name",
                "tf",
                "regime",
                "ic_ci_lower",
                "ic_ci_upper",
                "ic_sign",
                "passes_fdr",
                "reliable",
                "n_independent",
                "feature_status_at_eval",
                "ic_sharpe_hac",
                "standing_weight",
            ]
            result_rows = []
            for r in self.conn.corpus_rows:
                if r["training_window_end"] != training_window_end:
                    continue
                if r["lookahead_bars"] != lookahead_bars:
                    continue
                standing_weight = weight_lookup.get((r["tf"], r["regime"], r["feature_name"]), 0.0)
                result_rows.append(
                    tuple(
                        standing_weight if col == "standing_weight" else r.get(col) for col in cols
                    )
                )
            self._rows = result_rows
            self._description = [(c,) for c in cols]
            return
```

with:

```python
        if "FROM feature_ic_scores fis" in sql:
            weight_version, training_window_end, *tf_bars_flat = params
            # Todo 146: lookahead_mid is tf-specific now -- the real query's WHERE
            # clause is a flattened (tf, bars, tf, bars, ...) OR-chain instead of one
            # scalar lookahead_bars. Rebuild it as a set of (tf, bars) pairs to match
            # the same way the production SQL's OR-of-ANDs does.
            tf_bars_pairs = {
                (tf_bars_flat[i], tf_bars_flat[i + 1]) for i in range(0, len(tf_bars_flat), 2)
            }
            weight_lookup = {
                (r["tf"], r["regime"], r["feature_name"]): r["weight"]
                for r in self.conn.ensemble_weight_rows
                if r["weight_version"] == weight_version
            }
            cols = [
                "feature_name",
                "tf",
                "regime",
                "ic_ci_lower",
                "ic_ci_upper",
                "ic_sign",
                "passes_fdr",
                "reliable",
                "n_independent",
                "feature_status_at_eval",
                "ic_sharpe_hac",
                "standing_weight",
            ]
            result_rows = []
            for r in self.conn.corpus_rows:
                if r["training_window_end"] != training_window_end:
                    continue
                if (r["tf"], r["lookahead_bars"]) not in tf_bars_pairs:
                    continue
                standing_weight = weight_lookup.get((r["tf"], r["regime"], r["feature_name"]), 0.0)
                result_rows.append(
                    tuple(
                        standing_weight if col == "standing_weight" else r.get(col) for col in cols
                    )
                )
            self._rows = result_rows
            self._description = [(c,) for c in cols]
            return
```

- [ ] **Step 14: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_ic_engine_lifecycle_hook.py -v`
Expected: All PASS, including the extended `test_lookahead_pinning_uses_only_mid_lookahead_rows` (Step 10) proving the mis-tf'd 15m/lookahead=5 row (n=9999) is correctly excluded — if `registry.advance_calls` shows `13999` instead of `4000`, the tf-scoping isn't actually working and the fake/production filtering logic disagree somewhere.

- [ ] **Step 15: Commit**

```bash
git add services/ic_engine.py tests/unit/test_hac_ic_sharpe.py tests/unit/test_ic_engine_lifecycle_hook.py tests/unit/test_ic_engine_compute_split.py tests/unit/test_ic_engine_dual_write_symbol_hmm.py tests/unit/test_ic_engine_fingerprint.py
git commit -m "feat(ic_engine): per-tf lookahead grid in ICEngineConfig + tf-scoped lifecycle-hook gate query"
```

---

## Task 3: `ensemble_ic_engine.py`'s parallel config class

**Files:**
- Modify: `services/ensemble_ic_engine.py:165-168` (fields), `:192-200` (`.lookaheads` property), `:214-217` (`from_apr()`), `:919-920` and `:1309` (two call sites)
- Test: `tests/unit/test_ensemble_ic_decay.py` (new test, no existing `EnsembleICConfig` construction there), `tests/unit/test_ensemble_ic_worker_fetch.py:58-61`, `tests/unit/test_ensemble_ic_stop_target_calibration.py:203-206`

**Interfaces:**
- Consumes: nothing new.
- Produces: `EnsembleICConfig.lookaheads_for(tf: str) -> dict[str, int]`, same shape as Task 2's `ICEngineConfig` method.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_ensemble_ic_decay.py` (find the existing `EnsembleICConfig(...)` construction pattern first: `grep -n "EnsembleICConfig(" tests/unit/test_ensemble_ic_decay.py`):

```python
def test_ensemble_ic_config_lookaheads_for_returns_per_tf_values():
    """Same per-tf resolution as ICEngineConfig.lookaheads_for -- todo 146."""
    config = EnsembleICConfig(
        fdr_alpha=0.05,
        walk_forward_folds=3,
        sharpe_window_size=2000,
        sharpe_min_windows=30,
        subsample_min_stride=5,
        min_reliable_n=100,
        hac_max_lag=3,
        lookahead_fast={"5m": 1, "15m": 1, "1h": 1, "1d": 1},
        lookahead_mid={"5m": 6, "15m": 2, "1h": 2, "1d": 2},
        lookahead_slow={"5m": 12, "15m": 5, "1h": 20, "1d": 5},
        lookahead_extended={"5m": 39, "15m": 10, "1h": 60, "1d": 10},
        n_workers=1,
        pooled_fetch_itersize=50_000,
        decay_threshold=0.05,
        min_qualifying_fraction=0.60,
        wf_stability_ratio=3.0,
        gate_lookahead="fast",
        wf_stability_metric="ic_ratio",
        min_obs_per_regime=3000,
    )
    assert config.lookaheads_for("5m") == {"fast": 1, "mid": 6, "slow": 12, "extended": 39}
    assert config.lookaheads_for("1h") == {"fast": 1, "mid": 2, "slow": 20, "extended": 60}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_ensemble_ic_decay.py::test_ensemble_ic_config_lookaheads_for_returns_per_tf_values -v`
Expected: FAIL (fields still scalar, no `lookaheads_for` method).

- [ ] **Step 3: Update the two OTHER test files that construct `EnsembleICConfig(...)` directly with scalar lookahead fields**

`test_ensemble_ic_decay.py` itself does not construct `EnsembleICConfig` anywhere (verified: it tests `_select_hold_bars_from_decay` as a pure function, taking a plain `scale_to_bars: dict[str, int]` argument that is already single-tf-shaped and needs no change). The real construction sites are two DIFFERENT files:

`tests/unit/test_ensemble_ic_worker_fetch.py:58-61`, replace:

```python
        lookahead_fast=1,
        lookahead_mid=5,
        lookahead_slow=20,
        lookahead_extended=60,
```

with:

```python
        lookahead_fast={"5m": 1, "15m": 1, "1h": 1, "1d": 1},
        lookahead_mid={"5m": 5, "15m": 5, "1h": 5, "1d": 5},
        lookahead_slow={"5m": 20, "15m": 20, "1h": 20, "1d": 20},
        lookahead_extended={"5m": 60, "15m": 60, "1h": 60, "1d": 60},
```

`tests/unit/test_ensemble_ic_stop_target_calibration.py:203-206`, same replacement (identical scalar values at the same 4 lines).

(Same reasoning as Task 2 Step 9: kept uniform across tf here since neither test file varies its cell data by tf in a way that depends on real per-tf differences — only the two new/updated tests in Steps 1 and 5 below need genuinely different per-tf values.)

- [ ] **Step 4: Update `EnsembleICConfig`'s field declarations**

In `services/ensemble_ic_engine.py`, replace lines 165-168:

```python
    lookahead_fast: int
    lookahead_mid: int
    lookahead_slow: int
    lookahead_extended: int
```

with:

```python
    lookahead_fast: dict[str, int]
    lookahead_mid: dict[str, int]
    lookahead_slow: dict[str, int]
    lookahead_extended: dict[str, int]
```

- [ ] **Step 5: Replace the `.lookaheads` property**

Replace lines 192-200:

```python
    @property
    def lookaheads(self) -> dict[str, int]:
        """Gradient-scale lookahead mapping -- built once; frozen after construction."""
        return {
            "fast": self.lookahead_fast,
            "mid": self.lookahead_mid,
            "slow": self.lookahead_slow,
            "extended": self.lookahead_extended,
        }
```

with:

```python
    def lookaheads_for(self, tf: str) -> dict[str, int]:
        """Gradient-scale lookahead mapping for ONE timeframe (todo 146)."""
        return {
            "fast": self.lookahead_fast[tf],
            "mid": self.lookahead_mid[tf],
            "slow": self.lookahead_slow[tf],
            "extended": self.lookahead_extended[tf],
        }
```

- [ ] **Step 6: Update `from_apr()`**

Replace lines 214-217:

```python
            lookahead_fast=_cfg(cfg, "alpha.ic.lookahead.fast", 1),
            lookahead_mid=_cfg(cfg, "alpha.ic.lookahead.mid", 5),
            lookahead_slow=_cfg(cfg, "alpha.ic.lookahead.slow", 20),
            lookahead_extended=_cfg(cfg, "alpha.ic.lookahead.extended", 60),
```

with:

```python
            lookahead_fast={
                tf: _cfg(cfg, f"alpha.ic.lookahead.{tf}.fast", 1)
                for tf in ("5m", "15m", "1h", "1d")
            },
            lookahead_mid={
                tf: _cfg(cfg, f"alpha.ic.lookahead.{tf}.mid", fb)
                for tf, fb in {"5m": 6, "15m": 2, "1h": 2, "1d": 2}.items()
            },
            lookahead_slow={
                tf: _cfg(cfg, f"alpha.ic.lookahead.{tf}.slow", fb)
                for tf, fb in {"5m": 12, "15m": 5, "1h": 20, "1d": 5}.items()
            },
            lookahead_extended={
                tf: _cfg(cfg, f"alpha.ic.lookahead.{tf}.extended", fb)
                for tf, fb in {"5m": 39, "15m": 10, "1h": 60, "1d": 10}.items()
            },
```

Note: `_cfg` here is this file's existing raw-dict config helper (already used unchanged for every other key on these lines) — confirm its signature is `_cfg(cfg: dict, key: str, default: Any) -> Any` by reading its definition before this step; it is NOT `ConfigService.get_sync` (that's `ic_engine.py`'s helper, a different object type).

- [ ] **Step 7: Update the call site at line 919-920**

`tf` is already in scope in the enclosing loop (verified — it's used at line 891's `cur.execute(_WORKER_FETCH_SQL, (symbol, tf, ...))`). Replace:

```python
                for scale in _SCALES:
                    lookahead_bars = config.lookaheads[scale]
```

with:

```python
                for scale in _SCALES:
                    lookahead_bars = config.lookaheads_for(tf)[scale]
```

- [ ] **Step 8: Update the second call site at line 1309 — `_calibrate_hold_max_bars`**

This call site was missed in the original scoping pass; found by grepping `config.lookaheads` after Steps 4-5 renamed the property, which correctly breaks this line too (`AttributeError: 'EnsembleICConfig' object has no attribute 'lookaheads'`). `tf` is already in scope — this line is inside the loop `for (_symbol, tf, regime), cells in groups.items():` (`services/ensemble_ic_engine.py:1308`). Replace line 1309:

```python
            result = _select_hold_bars_from_decay(cells, config.decay_threshold, config.lookaheads)
```

with:

```python
            result = _select_hold_bars_from_decay(
                cells, config.decay_threshold, config.lookaheads_for(tf)
            )
```

- [ ] **Step 9: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_ensemble_ic_decay.py tests/unit/test_ensemble_ic_worker_fetch.py tests/unit/test_ensemble_ic_stop_target_calibration.py -v`
Expected: All PASS.

- [ ] **Step 10: Commit**

```bash
git add services/ensemble_ic_engine.py tests/unit/test_ensemble_ic_decay.py tests/unit/test_ensemble_ic_worker_fetch.py tests/unit/test_ensemble_ic_stop_target_calibration.py
git commit -m "feat(ensemble_ic_engine): per-tf lookahead grid in EnsembleICConfig (todo 146)"
```

---

## Task 4: `forward_return_writer.py` loads per-tf lookaheads

**Files:**
- Modify: `services/forward_return_writer.py:81-84` (`_SCALE_FALLBACKS`), `:710-715` (lookahead loading), `:751-761` (`max_abs_return_by_tf_scale`), `:769-771` (SQL building)
- Test: `tests/unit/test_forward_return_writer.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: a `lookaheads_by_tf: dict[str, dict[str, int]]` local replacing the single shared `lookaheads` dict that was previously reused across every tf.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_forward_return_writer.py` (near existing `_LOOKAHEADS` fixture at line 176):

```python
def test_scale_fallbacks_differ_per_tf():
    """_SCALE_FALLBACKS_BY_TF must have distinct values per todo 146's confirmed grid --
    a single shared fallback dict would silently apply 1d's numbers to 5m/15m/1h."""
    assert _SCALE_FALLBACKS_BY_TF["5m"] == {"fast": 1, "mid": 6, "slow": 12, "extended": 39}
    assert _SCALE_FALLBACKS_BY_TF["15m"] == {"fast": 1, "mid": 2, "slow": 5, "extended": 10}
    assert _SCALE_FALLBACKS_BY_TF["1h"] == {"fast": 1, "mid": 2, "slow": 20, "extended": 60}
    assert _SCALE_FALLBACKS_BY_TF["1d"] == {"fast": 1, "mid": 2, "slow": 5, "extended": 10}
```

Add the import at the top of the test file if `_SCALE_FALLBACKS_BY_TF` isn't already imported from `services.forward_return_writer` (check the existing import block first).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_forward_return_writer.py::test_scale_fallbacks_differ_per_tf -v`
Expected: FAIL — `ImportError: cannot import name '_SCALE_FALLBACKS_BY_TF'`.

- [ ] **Step 3: Replace `_SCALE_FALLBACKS` with a per-tf structure**

In `services/forward_return_writer.py`, replace line 84:

```python
_SCALE_FALLBACKS: dict[str, int] = {"fast": 1, "mid": 5, "slow": 20, "extended": 60}
```

with:

```python
_SCALE_FALLBACKS_BY_TF: dict[str, dict[str, int]] = {
    "5m": {"fast": 1, "mid": 6, "slow": 12, "extended": 39},
    "15m": {"fast": 1, "mid": 2, "slow": 5, "extended": 10},
    "1h": {"fast": 1, "mid": 2, "slow": 20, "extended": 60},
    "1d": {"fast": 1, "mid": 2, "slow": 5, "extended": 10},
}
```

- [ ] **Step 4: Load lookaheads per-tf instead of once globally**

Replace lines 710-715:

```python
                # Load lookahead periods from APR (alpha.ic.lookahead.{scale})
                lookaheads = {
                    scale: int(cfg.get_sync(f"alpha.ic.lookahead.{scale}", fb))
                    for scale, fb in _SCALE_FALLBACKS.items()
                }
                _logger.info("forward_return_writer.lookaheads", lookaheads=lookaheads)
```

with:

```python
                # Load lookahead periods from APR, per tf (alpha.ic.lookahead.{tf}.{scale})
                # -- todo 146: a single global grid was measuring a different real-world
                # horizon per tf under the same scale name (60 bars is ~3 months at 1d,
                # ~5 hours at 5m).
                lookaheads_by_tf = {
                    tf: {
                        scale: int(cfg.get_sync(f"alpha.ic.lookahead.{tf}.{scale}", fb))
                        for scale, fb in _SCALE_FALLBACKS_BY_TF[tf].items()
                    }
                    for tf in args.tf
                }
                _logger.info(
                    "forward_return_writer.lookaheads_by_tf", lookaheads_by_tf=lookaheads_by_tf
                )
```

Note: `args.tf` is used here instead of the later-assigned `tfs` local (defined at line 738, after this block) — read lines 706-738 before this step to confirm `args.tf` is available at this point in `main()` (it is the same value `tfs = args.tf` is assigned from three lines later); using `args.tf` directly here avoids reordering the function.

- [ ] **Step 5: Update `max_abs_return_by_tf_scale` to use the per-tf dict**

Replace lines 751-761:

```python
                max_abs_return_by_tf_scale = {
                    tf: scale_max_abs_return(
                        float(
                            cfg.get_sync(
                                f"alpha.quant.max_abs_return.{tf}", _MAX_ABS_RETURN_FALLBACKS[tf]
                            )
                        ),
                        lookaheads,
                    )
                    for tf in tfs
                }
```

with:

```python
                max_abs_return_by_tf_scale = {
                    tf: scale_max_abs_return(
                        float(
                            cfg.get_sync(
                                f"alpha.quant.max_abs_return.{tf}", _MAX_ABS_RETURN_FALLBACKS[tf]
                            )
                        ),
                        lookaheads_by_tf[tf],
                    )
                    for tf in tfs
                }
```

- [ ] **Step 6: Update `forward_return_sql_by_tf` construction**

Replace lines 769-771:

```python
                forward_return_sql_by_tf = {
                    tf: _build_forward_return_sql(lookaheads, tf) for tf in tfs
                }
```

with:

```python
                forward_return_sql_by_tf = {
                    tf: _build_forward_return_sql(lookaheads_by_tf[tf], tf) for tf in tfs
                }
```

- [ ] **Step 7: Check for any other bare `lookaheads` reference in `main()` after this point**

Run: `grep -n "\blookaheads\b" services/forward_return_writer.py` after Steps 3-6 land, and confirm every remaining reference is either `lookaheads_by_tf[...]` or a local parameter name inside a helper function (e.g. `_build_forward_return_sql(lookaheads: dict[str, int], ...)`'s own parameter, which stays unchanged — only `main()`'s call-site variable was renamed).

- [ ] **Step 8: Run test to verify Step 1 passes, plus the full file**

Run: `.venv/bin/pytest tests/unit/test_forward_return_writer.py -v`
Expected: All PASS (existing tests unaffected since `_build_forward_return_sql`/`_build_insert_sql`/`scale_max_abs_return` signatures are unchanged — only `main()`'s caller-side variable construction changed).

- [ ] **Step 9: Commit**

```bash
git add services/forward_return_writer.py tests/unit/test_forward_return_writer.py
git commit -m "feat(forward_return_writer): load per-tf lookahead grid instead of one shared dict (todo 146)"
```

---

## Task 5: Full-suite verification

- [ ] **Step 1: Run the complete unit test suite**

Run: `.venv/bin/pytest tests/unit/ -q`
Expected: 0 failures. If anything outside the 4 files touched above fails, it means another call site references `.lookaheads` (the old property) or a scalar `lookahead_fast`/etc. field that wasn't caught by the greps in Tasks 2-4 — search again with `grep -rn "\.lookaheads\b" services/ src/ tests/` and `grep -rn "lookahead_fast=\|lookahead_mid=\|lookahead_slow=\|lookahead_extended=" tests/` before declaring this task done.

- [ ] **Step 2: Run `/simplify` on the changed files**

Per this project's Done-Coding SOP, invoke `/simplify` on `services/ic_engine.py`, `services/ensemble_ic_engine.py`, `services/forward_return_writer.py` before review.

- [ ] **Step 3: Run `/review`**

Per this project's Done-Coding SOP.

- [ ] **Step 4: Final commit / branch merge**

Follow CLAUDE.md's Done-Coding SOP steps 4-6 (commit on feature branch → `git checkout main && git merge --ff-only <branch>` → prune worktree). Do NOT push unless explicitly asked.

---

## Explicitly out of scope — file as a follow-up todo, do not implement here

1. Restructuring `ic_engine.py`'s fixed `_SCALES` tuple and its ~13 positionally-indexed call sites (`_compute_one_regime_cell`, `_compute_symbol_tf`, `_compute_cross_sectional_tf`, and the SQL/array-building sections feeding them) to give `1h` a true 2-scale-only world (dropping `slow`/`extended` entirely rather than leaving them at unchanged, known-degenerate values). This plan deliberately leaves `1h`'s `slow`/`extended` APR values unchanged (20/60) specifically to avoid touching that hot-path array-shape assumption under time pressure ahead of an imminent full-corpus `ic_engine` run.

2. `scripts/ops/alpha/ops_ensemble_ablation.py`'s `AblationConfig` (todo 084) — a fourth, independent copy of the same `lookahead_fast/mid/slow/extended` scalar-field + `.lookaheads` property pattern, plus `tests/unit/test_ensemble_ablation.py`'s direct construction of it. Confirmed this is a standalone, on-demand ablation-forensics tool (not in `_DAG_ORDER`, not called by `ops_corpus_pipeline_run.sh`) — not touched by todo 176 Step 5's imminent corpus pass, so left on the old global grid for now. Whoever next runs this script for real ensemble-degradation forensics should be aware its lookahead grid is stale relative to the per-tf values this plan seeds.

3. `src/observability/corpus_manifest_verifier.py`'s separate `alpha.ic.lookaheads` APR key (plural, a JSON list `[1,5,20,60]`, apparently never actually seeded in any migration — falls back to that hardcoded default) — used to sanity-check expected row counts per lookahead value across the corpus. Once the real per-tf grid lands, this verifier's expectation is stale (it'll keep expecting rows at bar-counts like 60 for every tf, including ones where the real grid no longer produces them). Read-only, post-hoc verification tool, not on the critical path either.

File all three as one follow-up todo once this plan lands, referencing todo 146's "1h has no slow/extended tier by design" finding and this plan's Task 1 migration as the starting point.
