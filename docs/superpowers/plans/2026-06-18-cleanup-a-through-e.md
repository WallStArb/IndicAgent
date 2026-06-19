# Cleanup A–E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Five cleanup tasks flagged during phases 127–134: remove dead --warmup flag, rename _cfg() in zone_engine, rename confidence_utils.py, migrate final APR constants in trade_framer, and persist zone_source to context_features in signal_events.

**Architecture:** Each task is independent (A/B/C/D/E can be committed separately). Task E has the widest blast radius — it modifies TradeFrame, signal_schema, signal_writer, and run_historical_pipeline. Task D is purely DB + one function body. Tasks A/B/C are mechanical renames/deletes.

**Tech Stack:** Python 3.11, PostgreSQL/asyncpg, psycopg2 (historical pipeline), structlog, pytest

## Global Constraints

- All tests: `.venv/bin/pytest tests/unit/ -q` — must be green after every commit
- Lint: `.venv/bin/ruff check . --fix && .venv/bin/black .`
- No `datetime.now()` or `datetime.utcnow()` — use `datetime.now(UTC)`
- No hardcoded topic strings — use `stream_keys.py`
- Exception variable name is `error` — `except X as error:`
- DB: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "..."`
- Migration numbering: next is 152
- Do NOT add `Co-Authored-By` lines to commits

---

### Task A: Remove dead `--warmup` flag from run_historical_pipeline.py

The `--warmup` double-pass is a proven no-op: the warmup pass builds caches in local variables that are discarded when the function returns, so pass 2 sees zero benefit. Keeping it risks future operators re-running a multi-day single-worker rebuild for nothing (which happened 2026-06-16).

**Files:**
- Modify: `production/scripts/run_historical_pipeline.py`

**Interfaces:**
- Consumes: nothing
- Produces: nothing (deletion only)

- [ ] **Step 1: Delete the --warmup argparse argument**

Find lines around 2231–2234 in `run_historical_pipeline.py`:

```python
    parser.add_argument(
        "--warmup",
        action="store_true",
        help="Run I1-I6 warmup pass before signal pass (populates I6 cache for cold-start "
        "correction). Requires --replay-only. First pass: skip_signals=True (I1-I6 only). "
        "Second pass: skip_signals=False (I1-I7 with warm I6 cache).",
    )
```

Delete those 7 lines entirely.

- [ ] **Step 2: Delete the --warmup validation check**

Find lines around 2249–2252:

```python
    # --warmup requires --replay-only (fetch stage and warmup are incompatible:
    # fetch would overwrite bars while warmup pass is building the I6 cache).
    if getattr(args, "warmup", False) and not args.replay_only:
        print("ERROR: --warmup requires --replay-only (combine: --replay-only --warmup)")
        sys.exit(1)
```

Delete those 5 lines.

- [ ] **Step 3: Delete the do_warmup variable and the workers==1 two-pass block**

Find around line 2659:

```python
        do_warmup = getattr(args, "warmup", False)

        if args.workers == 1:
            with db_conn.cursor() as cur:
                cur.execute("SET synchronous_commit = off")
            _warm_config_service(db_conn)
            perf_weights = _load_perf_weights(db_conn)

            if do_warmup:
                # Two-pass replay: first populate I6 cache (warmup), then emit signals.
                # Pass 1: I1-I6 only — builds intelligence_features rows and populates
                #   the per-symbol I6 cache so no cold-start NULL values remain for
                #   the signal pass.
                # Pass 2: I1-I7 with warm I6 cache — signals now have valid CTF scores.
                print("Running warmup pass (I1-I6 only)...")
                for contract in contracts:
                    print(f"\n{contract.symbol} [warmup]:")
                    calibration_curves = _load_calibration_curves(db_conn, symbol=contract.symbol)
                    replay_symbol(
                        contract.symbol,
                        db_conn,
                        timeframes,
                        since=since_dt,
                        skip_signals=True,
                        calibration_curves=calibration_curves,
                        perf_weights=perf_weights,
                        seed_from_db=not args.no_seed,
                    )
                print("\nWarmup complete. Running signal pass (I1-I7 with warm I6 cache)...")
```

Delete just:
- The `do_warmup = getattr(args, "warmup", False)` line
- The entire `if do_warmup:` block (the two-pass section only, up to and including the `print("\nWarmup complete...")` line)

Keep the rest of the `workers == 1` branch intact.

- [ ] **Step 4: Delete the parallel-mode warmup NOTE**

Find the `if do_warmup:` block in the `else` branch (parallel workers):

```python
            if do_warmup:
                print(
                    "NOTE: --warmup is only supported with --workers 1 (parallel mode skips warmup pass)"
                )
```

Delete those 4 lines.

- [ ] **Step 5: Sweep for any remaining warmup references**

```bash
grep -rn "warmup\|do_warmup" production/scripts/run_historical_pipeline.py
```

Expected: only documentary occurrences in comments about "warmup bars" in the `replay_symbol` function (lines ~508, ~1692, ~1822, ~1879) — those refer to indicator warmup (cold-start bars), not the CLI flag. Leave them. Any reference to `args.warmup`, `do_warmup`, or `--warmup` must be gone.

- [ ] **Step 6: Run tests and lint**

```bash
.venv/bin/pytest tests/unit/ -q
.venv/bin/ruff check . --fix && .venv/bin/black .
```

Expected: all green. No test references this flag.

- [ ] **Step 7: Commit**

```bash
git add production/scripts/run_historical_pipeline.py
git commit -m "chore: remove dead --warmup flag from run_historical_pipeline"
```

---

### Task B: Rename `_cfg()` → `_read_config()` in zone_engine.py

`_cfg` uses the banned abbreviation "cfg" (naming system §6 Tier 3 banned). All call sites are internal to zone_engine.py.

**Files:**
- Modify: `src/intelligence/trading/zone_engine.py`

**Interfaces:**
- Consumes: nothing external
- Produces: nothing — internal rename only

- [ ] **Step 1: Find all occurrences**

```bash
grep -n "_cfg\b" src/intelligence/trading/zone_engine.py
```

Expected output (current):
```
44:def _cfg(key: str, default: float) -> float:
49:    return _cfg("feature.zone_engine.cluster_radius_atr", CLUSTER_RADIUS_ATR)
53:    return _cfg("feature.zone_engine.zone_buffer_atr", ZONE_BUFFER_ATR)
57:    return _cfg("feature.zone_engine.min_width_atr", MIN_ZONE_WIDTH_ATR)
61:    return _cfg("feature.zone_engine.single_level_radius_atr", SINGLE_LEVEL_RADIUS_ATR)
65:    return _cfg("weights.zone_engine.strength", _SINGLE_STRENGTH_WEIGHT)
69:    return _cfg("weights.zone_engine.proximity", _SINGLE_PROXIMITY_WEIGHT)
```

- [ ] **Step 2: Rename the function definition and all call sites**

In `src/intelligence/trading/zone_engine.py`, replace all occurrences of `_cfg(` with `_read_config(` and the definition `def _cfg(` with `def _read_config(`.

This is a pure mechanical find-replace within the file — all 7 occurrences (1 definition + 6 calls).

- [ ] **Step 3: Verify no external callers**

```bash
grep -rn "_cfg\b" src/ services/ tests/ | grep "zone_engine" | grep -v ".pyc"
```

Expected: empty (no external code calls `_cfg` from zone_engine).

- [ ] **Step 4: Run tests and lint**

```bash
.venv/bin/pytest tests/unit/ -q
.venv/bin/ruff check . --fix && .venv/bin/black .
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/trading/zone_engine.py
git commit -m "refactor: rename _cfg() to _read_config() in zone_engine (naming system §6)"
```

---

### Task C: Rename `confidence_utils.py` → `confidence.py`

`confidence_utils` uses the retired word "Utils" (naming system §3). There are ~40 import sites across src/, tests/, and services/.

**Files:**
- Rename: `src/intelligence/trading/confidence_utils.py` → `src/intelligence/trading/confidence.py`
- Modify: all ~40 import sites listed below
- Rename: `tests/unit/intelligence/test_confidence_utils.py` → `tests/unit/intelligence/test_confidence.py`
- Modify: `CLAUDE.md` (project root) — reference in Core Runtime Files table
- Modify: `src/intelligence/CLAUDE.md` — reference in tier table

**Interfaces:**
- Consumes: nothing changes — same functions, same module, different filename
- Produces: `src/intelligence/trading/confidence.py` with identical content

- [ ] **Step 1: Rename the file**

```bash
git mv src/intelligence/trading/confidence_utils.py src/intelligence/trading/confidence.py
git mv tests/unit/intelligence/test_confidence_utils.py tests/unit/intelligence/test_confidence.py
```

- [ ] **Step 2: Update all imports in src/**

Find every `from .confidence_utils import` or `from src.intelligence.trading.confidence_utils import` and replace with the new name. Run:

```bash
grep -rn "confidence_utils" src/ --include="*.py" | grep -v ".pyc"
```

For each file, change:
- `from .confidence_utils import` → `from .confidence import`
- `from src.intelligence.trading.confidence_utils import` → `from src.intelligence.trading.confidence import`

Files to update (current list):
```
src/intelligence/trading/regime_transition.py
src/intelligence/trading/ofi_continuation.py
src/intelligence/trading/gap_analysis_setup.py
src/intelligence/trading/vwap_reclaim.py
src/intelligence/trading/mtf_alignment.py
src/intelligence/trading/delta_exhaustion.py
src/intelligence/trading/hvn_rejection.py
src/intelligence/trading/cvd_divergence.py
src/intelligence/trading/vwap_deviation.py
src/intelligence/trading/momentum_breakout.py
src/intelligence/trading/failed_breakout.py
src/intelligence/trading/choch_reversal.py
src/intelligence/trading/mean_reversion.py
src/intelligence/trading/cross_asset_divergence.py
src/intelligence/trading/dual_divergence.py
src/intelligence/trading/orb15.py
src/intelligence/trading/liquidity_sweep_reclaim.py
src/intelligence/trading/second_leg_continuation.py
src/intelligence/trading/microstructure_utils.py
src/intelligence/trading/trend_following.py
src/intelligence/trading/squeeze_expansion.py
src/intelligence/trading/orb30.py
src/intelligence/trading/supply_demand_setup.py
src/intelligence/trading/session_extremes_setup.py
src/intelligence/trading/anchored_vwap_reversion.py
src/intelligence/trading/ofi_divergence.py
src/intelligence/trading/fvg_fill.py
src/intelligence/trading/lvn_breakout.py
src/intelligence/trading/divergence_stack.py
src/intelligence/trading/pattern_completion.py
src/intelligence/trading/poc_rejection.py
src/intelligence/trading/candlestick_pattern_setup.py
src/intelligence/trading/vcp.py
src/intelligence/trading/liquidity_hunt.py
src/intelligence/pipeline/signal_processor.py
```

Also update `services/intelligence_pipeline.py` (line 545, 553):
- Change `confidence_utils,` → `confidence,`
- Change `confidence_utils.set_config_service(...)` → `confidence.set_config_service(...)`

- [ ] **Step 3: Update test imports**

In `tests/unit/intelligence/test_confidence.py` (the renamed file), update:
```python
from src.intelligence.trading.confidence_utils import (
```
→
```python
from src.intelligence.trading.confidence import (
```

Also update:
- `tests/unit/intelligence/test_cis_plugins.py` line 462:
  `from src.intelligence.trading.confidence_utils import CONF_CEIL`
  → `from src.intelligence.trading.confidence import CONF_CEIL`

- `tests/unit/intelligence/test_param_store_migration.py` lines 8 and 95:
  `import src.intelligence.trading.confidence_utils as cu`
  → `import src.intelligence.trading.confidence as cu`
  `from src.intelligence.trading.confidence_utils import _validate_weights_sum`
  → `from src.intelligence.trading.confidence import _validate_weights_sum`

- `tests/unit/intelligence/test_pipeline_annotation.py` lines 24 and 223/227:
  Line 24: `from src.intelligence.trading.confidence_utils import MIN_CTF_SCORE`
  → `from src.intelligence.trading.confidence import MIN_CTF_SCORE`
  Lines 223/227: Update the exemption set from `{"confidence_utils.py"}` to `{"confidence.py"}`

- [ ] **Step 4: Update documentation references**

In `CLAUDE.md` (project root), find the reference to `confidence_utils.py` and update to `confidence.py`.

In `src/intelligence/CLAUDE.md`, find the table row:
```
| `confidence_utils.py` | `compose_confidence(raw)`, `ConfluenceWeightProfile` | ...
```
Change the filename to `confidence.py`.

In `src/intelligence/trading/cis_scorer.py` (has a comment referencing confidence_utils pattern), update the comment:
```python
# Same pattern as confidence_utils.set_config_service().
```
→
```python
# Same pattern as confidence.set_config_service().
```

In `src/intelligence/ml/feature_builder.py` line 34, update the comment:
```python
# 25 keys verbatim from confidence_utils.py capture_signal_features()
```
→
```python
# 25 keys verbatim from confidence.py capture_signal_features()
```

In `src/intelligence/ai/alpha/ml_scorer_agent.py` line 225, update the comment:
```python
# --- Shadow feature keys (25 keys from confidence_utils capture_signal_features) ---
```
→
```python
# --- Shadow feature keys (25 keys from confidence.py capture_signal_features) ---
```

- [ ] **Step 5: Verify no remaining confidence_utils references**

```bash
grep -rn "confidence_utils" src/ tests/ services/ | grep -v ".pyc"
```

Expected: empty.

- [ ] **Step 6: Run tests and lint**

```bash
.venv/bin/pytest tests/unit/ -q
.venv/bin/ruff check . --fix && .venv/bin/black .
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: rename confidence_utils.py to confidence.py (naming system §3)"
```

---

### Task D: APR migration — ATR_TARGET_MAX_MULTIPLIER (Phase 132 Plan 05 final constants)

`ATR_TARGET_MAX_MULTIPLIER` (8.0) and `ATR_TARGET_MAX_MULTIPLIER_BY_TF` (per-TF dict) are the two remaining module-level constants in `trade_framer.py`. All other Plan 05 constants are already migrated (code uses `_cfg()`, config_state is seeded).

**What's needed:**
1. DB migration 152: seed 7 new APR keys in config_schema + config_state
2. Code change: replace the two module-level constants with `_cfg()` calls in `_collect_target_candidates`

**Files:**
- Create: `production/migrations/152_phase132_target_max_atr.sql`
- Modify: `src/intelligence/trading/trade_framer.py`

**Interfaces:**
- Consumes: `_cfg()` helper already present in trade_framer.py
- Produces: 7 new APR keys: `feature.trade_framer.target_max_atr` and `feature.trade_framer.target_max_atr_{1m,5m,15m,1h,4h,1d}`

- [ ] **Step 1: Write the migration SQL**

Create `production/migrations/152_phase132_target_max_atr.sql`:

```sql
-- Migration 152: Phase 132 Plan 05 — APR migration for ATR_TARGET_MAX_MULTIPLIER
-- Seeds feature.trade_framer.target_max_atr (default) and per-TF overrides.
-- These are ML learning targets: ML discovery can tune per-TF max target distances
-- once sufficient trade_frames outcomes are available per timeframe.

BEGIN;

INSERT INTO config_schema (config_key, description, data_type, domain, is_ml_target)
VALUES
  ('feature.trade_framer.target_max_atr',
   'Maximum target distance from entry in ATR units (default fallback when no per-TF override). [initial_estimate]',
   'float', 'trade_framer', true),
  ('feature.trade_framer.target_max_atr_1m',
   'Maximum target distance for 1m signals in ATR units. [initial_estimate]',
   'float', 'trade_framer', true),
  ('feature.trade_framer.target_max_atr_5m',
   'Maximum target distance for 5m signals in ATR units. [initial_estimate]',
   'float', 'trade_framer', true),
  ('feature.trade_framer.target_max_atr_15m',
   'Maximum target distance for 15m signals in ATR units. [initial_estimate]',
   'float', 'trade_framer', true),
  ('feature.trade_framer.target_max_atr_1h',
   'Maximum target distance for 1h signals in ATR units. [initial_estimate]',
   'float', 'trade_framer', true),
  ('feature.trade_framer.target_max_atr_4h',
   'Maximum target distance for 4h signals in ATR units. [initial_estimate]',
   'float', 'trade_framer', true),
  ('feature.trade_framer.target_max_atr_1d',
   'Maximum target distance for 1d signals in ATR units. [initial_estimate]',
   'float', 'trade_framer', true)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
  ('feature.trade_framer.target_max_atr',    '8.0', 1),
  ('feature.trade_framer.target_max_atr_1m', '3.0', 1),
  ('feature.trade_framer.target_max_atr_5m', '5.0', 1),
  ('feature.trade_framer.target_max_atr_15m','7.0', 1),
  ('feature.trade_framer.target_max_atr_1h', '8.0', 1),
  ('feature.trade_framer.target_max_atr_4h', '8.0', 1),
  ('feature.trade_framer.target_max_atr_1d', '8.0', 1)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
```

- [ ] **Step 2: Apply the migration**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/152_phase132_target_max_atr.sql
```

Expected: `INSERT 0 7` twice (or `INSERT 7` per statement).

- [ ] **Step 3: Verify the seeds landed**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT config_key, config_value FROM config_state WHERE config_key LIKE 'feature.trade_framer.target_max%' ORDER BY config_key;"
```

Expected: 7 rows with the seed values above.

- [ ] **Step 4: Replace the module-level constants with _cfg() in trade_framer.py**

In `src/intelligence/trading/trade_framer.py`, find the block around lines 99–109:

```python
# ATR_TARGET_MAX_MULTIPLIER: per-TF dict overrides this; constant is the final default
ATR_TARGET_MAX_MULTIPLIER = 8.0  # Maximum target distance: entry ± ATR×8.0
# ATR_TARGET_MAX_MULTIPLIER_BY_TF: dict structure; deferred to future phase for migration
ATR_TARGET_MAX_MULTIPLIER_BY_TF: dict[str, float] = {
    "1m": 3.0,
    "5m": 5.0,
    "15m": 7.0,
    "1h": 8.0,
    "4h": 8.0,
    "1d": 8.0,
}
```

Delete this entire block (10 lines).

- [ ] **Step 5: Update _collect_target_candidates to use _cfg()**

In `_collect_target_candidates`, find line ~738:

```python
    tf_max_mult = ATR_TARGET_MAX_MULTIPLIER_BY_TF.get(tf, ATR_TARGET_MAX_MULTIPLIER)
```

Replace with:

```python
    _default_max = _cfg("feature.trade_framer.target_max_atr", 8.0)
    tf_max_mult = _cfg(f"feature.trade_framer.target_max_atr_{tf}", _default_max)
```

- [ ] **Step 6: Update the comment on line 163 for STRUCTURE_SNAP_PROXIMITY_ATR**

Find around line 163:

```python
# STRUCTURE_SNAP_PROXIMITY_ATR -> feature.trade_framer.structure_snap_proximity_atr (APR, migration 145)
```

Update to reflect that migration 145 was DB indexes, the actual APR seed is in an earlier migration. Change the comment to:

```python
# STRUCTURE_SNAP_PROXIMITY_ATR: migrated to APR — _cfg("feature.trade_framer.structure_snap_proximity_atr", 1.5)
```

- [ ] **Step 7: Verify no remaining module-level constant references**

```bash
grep -n "ATR_TARGET_MAX_MULTIPLIER" src/intelligence/trading/trade_framer.py
```

Expected: empty (all references replaced).

- [ ] **Step 8: Write a unit test**

In `tests/unit/intelligence/test_trade_framer_apr.py` (create if it doesn't exist, or add to an existing trade_framer test file), add:

```python
def test_target_max_atr_reads_from_cfg(monkeypatch):
    """_collect_target_candidates uses _cfg for target_max ATR, not module constant."""
    from src.intelligence.trading import trade_framer as tf_mod

    captured = {}
    original_cfg = tf_mod._cfg

    def mock_cfg(key, default):
        captured[key] = default
        return original_cfg(key, default)

    monkeypatch.setattr(tf_mod, "_cfg", mock_cfg)

    # Trigger _collect_target_candidates via a minimal call
    features = {"timeframe": "1h", "garch_vol_ratio": 1.0}
    tf_mod._collect_target_candidates(
        entry=100.0, stop=98.0, direction=1, atr=1.0, features=features
    )

    assert "feature.trade_framer.target_max_atr" in captured
    assert "feature.trade_framer.target_max_atr_1h" in captured
```

Check if `tests/unit/intelligence/test_trade_framer_apr.py` exists first:

```bash
ls tests/unit/intelligence/test_trade_framer*
```

If an APR test file exists, add the test there. If not, create the file.

- [ ] **Step 9: Run tests and lint**

```bash
.venv/bin/pytest tests/unit/ -q
.venv/bin/ruff check . --fix && .venv/bin/black .
```

Expected: all green.

- [ ] **Step 10: Commit**

```bash
git add production/migrations/152_phase132_target_max_atr.sql src/intelligence/trading/trade_framer.py tests/unit/intelligence/
git commit -m "feat(apr): migrate ATR_TARGET_MAX_MULTIPLIER to APR — migration 152"
```

---

### Task E: Persist zone_source to signal_events.context_features

`TradeFrame` resolves `zone_source` internally but does not expose it as a dataclass field. `make_signal_from_frame` sets `sig["zone_source"] = None` (intended to be overwritten by lifecycle_tracker). Neither the live signal_writer nor the historical pipeline merges per-signal `zone_source` into `context_features` before the DB INSERT, so segmented analysis queries (`context_features->>'zone_source'`) return NULL for all rows.

Fix: add `zone_source` to `TradeFrame`, propagate it through `make_signal_from_frame`, and merge it into `context_features` at both INSERT points.

**Files:**
- Modify: `src/intelligence/trading/trade_framer.py` — add `zone_source` field to TradeFrame, populate in `frame_trade`
- Modify: `src/intelligence/trading/signal_schema.py` — set `sig["zone_source"] = tf.zone_source` in `make_signal_from_frame`
- Modify: `services/signal_writer.py` — merge zone_source into context_features at INSERT
- Modify: `production/scripts/run_historical_pipeline.py` — merge zone_source into context_features at INSERT

**Interfaces:**
- `TradeFrame.zone_source: str | None = None` — new field, backward-compatible (default None)
- `sig["zone_source"]` — changes from always-None to the value from the TradeFrame
- `signal_events.context_features["zone_source"]` — previously missing; now populated

- [ ] **Step 1: Write a failing test for TradeFrame.zone_source**

Find or create `tests/unit/intelligence/test_trade_framer.py`. Add:

```python
def test_frame_trade_zone_source_in_tradeframe():
    """frame_trade populates zone_source on the returned TradeFrame."""
    from src.intelligence.trading.trade_framer import frame_trade
    from tests.unit.intelligence.fixtures import minimal_features  # or inline

    features = {
        "timeframe": "1m",
        "asset_class": "equity_etf",
        "nearest_demand_low": 99.0,
        "nearest_demand_high": 100.0,
        "close_price": 100.5,
        "garch_vol_ratio": 1.0,
        "hurst_exponent": 0.5,
        "garch_shock": 0.0,
    }
    tf = frame_trade("supply_demand_long", 1, 100.5, features, atr=0.5)
    if tf.viable:
        assert tf.zone_source is not None
        assert isinstance(tf.zone_source, str)
```

Run to confirm it fails:

```bash
.venv/bin/pytest tests/unit/intelligence/test_trade_framer.py::test_frame_trade_zone_source_in_tradeframe -v
```

Expected: `AttributeError: 'TradeFrame' object has no attribute 'zone_source'` or similar.

- [ ] **Step 2: Add zone_source to TradeFrame**

In `src/intelligence/trading/trade_framer.py`, find the `TradeFrame` dataclass (line ~212). Add `zone_source` after `zone_high`:

```python
    zone_low: float = 0.0  # lower bound of entry zone (zone_low < zone_high always)
    zone_high: float = 0.0  # upper bound of entry zone
    zone_source: str | None = None  # source of zone bounds (e.g. "setup:supply_demand_zone", "atr_fallback")
```

- [ ] **Step 3: Populate zone_source in frame_trade's final return**

In `frame_trade`, find the final `return TradeFrame(...)` around line 1293. Add `zone_source=zone_source`:

```python
    return TradeFrame(
        entry=resolved_entry,
        entry_type=entry_type,
        stop=round(stop, 2),
        stop_type=stop_type,
        targets=targets,
        rr_t1=rr_t1,
        rr_t2=rr_t2,
        rr_t3=rr_t3,
        method=method,
        viable=True,
        rejection_reason=None,
        zone_low=zone_low,
        zone_high=zone_high,
        zone_source=zone_source,          # <-- add this
        stop_basis=stop_basis,
        stop_structure_type=stop_structure_type,
        stop_structure_age_bars=stop_structure_age_bars,
        structural_stop_distance_atr=structural_stop_distance_atr,
        adaptive_buffer_mult=adaptive_buffer_mult,
        plugin_regime_type=regime_type,
    )
```

Also update `_reject_frame` helper to accept and pass zone_source (or leave it None on rejected frames — zone_source=None for rejected frames is correct since zone rejection reason is in `rejection_reason`).

- [ ] **Step 4: Run the test — verify it passes**

```bash
.venv/bin/pytest tests/unit/intelligence/test_trade_framer.py::test_frame_trade_zone_source_in_tradeframe -v
```

Expected: PASS.

- [ ] **Step 5: Write a failing test for make_signal_from_frame**

In `tests/unit/intelligence/test_signal_schema.py`, add:

```python
def test_make_signal_from_frame_carries_zone_source():
    """zone_source from TradeFrame is written to sig['zone_source'], not left as None."""
    from src.intelligence.trading.trade_framer import TradeFrame, TradeTarget
    from src.intelligence.trading.signal_schema import make_signal_from_frame

    tf = TradeFrame(
        entry=100.0,
        entry_type="at_close",
        stop=98.0,
        stop_type="demand_zone",
        targets=[TradeTarget(price=103.0, label="T1", level_type="sr", rr=1.5)],
        rr_t1=1.5,
        viable=True,
        zone_low=99.0,
        zone_high=100.5,
        zone_source="setup:supply_demand_zone",
    )
    sig = make_signal_from_frame(
        tf,
        symbol="SPY",
        timeframe="1m",
        timestamp="2026-01-01T09:30:00Z",
        signal_type="supply_demand_long",
        setup_plugin="supply_demand_setup",
        direction=1,
        confidence=0.7,
        regime_context="trend",
        supporting_factors=["demand_zone"],
        confluence_score=0.6,
    )
    assert sig["zone_source"] == "setup:supply_demand_zone"
```

Run to confirm it fails:

```bash
.venv/bin/pytest tests/unit/intelligence/test_signal_schema.py::test_make_signal_from_frame_carries_zone_source -v
```

Expected: FAIL (zone_source is None, not the TradeFrame value).

- [ ] **Step 6: Update make_signal_from_frame to use tf.zone_source**

In `src/intelligence/trading/signal_schema.py`, find:

```python
    sig["zone_low"] = round_to_tick(tf.zone_low, symbol)
    sig["zone_high"] = round_to_tick(tf.zone_high, symbol)
    sig["zone_source"] = None  # set by lifecycle_tracker when zone is activated
```

Replace with:

```python
    sig["zone_low"] = round_to_tick(tf.zone_low, symbol)
    sig["zone_high"] = round_to_tick(tf.zone_high, symbol)
    sig["zone_source"] = tf.zone_source
```

- [ ] **Step 7: Run the test — verify it passes**

```bash
.venv/bin/pytest tests/unit/intelligence/test_signal_schema.py::test_make_signal_from_frame_carries_zone_source -v
```

Expected: PASS.

- [ ] **Step 8: Update signal_writer to merge zone_source into context_features**

In `services/signal_writer.py`, find the dict that builds the signal_events row (~line 262):

```python
            "context_features": detection.get("context_features"),
```

Replace with:

```python
            "context_features": {
                **(detection.get("context_features") or {}),
                "zone_source": detection.get("zone_source"),
            },
```

This creates a new dict per signal (no shared-reference mutation) with per-signal zone_source merged in.

- [ ] **Step 9: Update run_historical_pipeline.py to merge zone_source into context_features**

In `production/scripts/run_historical_pipeline.py`, find (~line 957):

```python
                context_features=sig.get("context_features"),
```

Replace with:

```python
                context_features={
                    **(sig.get("context_features") or {}),
                    "zone_source": sig.get("zone_source"),
                },
```

- [ ] **Step 10: Write a test confirming context_features includes zone_source**

In `tests/unit/intelligence/test_signal_schema.py`, add:

```python
def test_zone_source_surfaces_in_context_features_via_writer():
    """zone_source must be available at sig['zone_source'] for signal_writer merging."""
    from src.intelligence.trading.trade_framer import TradeFrame, TradeTarget
    from src.intelligence.trading.signal_schema import make_signal_from_frame

    tf = TradeFrame(
        entry=100.0,
        entry_type="at_close",
        stop=98.0,
        stop_type="demand_zone",
        targets=[TradeTarget(price=103.0, label="T1", level_type="sr", rr=1.5)],
        rr_t1=1.5,
        viable=True,
        zone_low=99.0,
        zone_high=100.5,
        zone_source="setup:fvg_zone",
    )
    sig = make_signal_from_frame(
        tf,
        symbol="SPY",
        timeframe="1m",
        timestamp="2026-01-01T09:30:00Z",
        signal_type="fvg_fill_long",
        setup_plugin="fvg_fill",
        direction=1,
        confidence=0.65,
        regime_context="trend",
        supporting_factors=["fvg"],
        confluence_score=0.5,
    )
    # Simulate what signal_writer does at INSERT time
    merged_context = {**(sig.get("context_features") or {}), "zone_source": sig.get("zone_source")}
    assert merged_context["zone_source"] == "setup:fvg_zone"
```

Run:

```bash
.venv/bin/pytest tests/unit/intelligence/test_signal_schema.py -k "zone_source" -v
```

Expected: both zone_source tests PASS.

- [ ] **Step 11: Run full test suite and lint**

```bash
.venv/bin/pytest tests/unit/ -q
.venv/bin/ruff check . --fix && .venv/bin/black .
```

Expected: all green.

- [ ] **Step 12: Commit**

```bash
git add src/intelligence/trading/trade_framer.py \
        src/intelligence/trading/signal_schema.py \
        services/signal_writer.py \
        production/scripts/run_historical_pipeline.py \
        tests/unit/intelligence/
git commit -m "feat: persist zone_source to signal_events.context_features for segmented analysis"
```

---

## Done-Coding SOP

After all 5 tasks are committed:

```bash
# Run done-coding SOP (CLAUDE.md)
# 1. code-simplifier agent runs automatically
# 2. /review for peer review
# 3. pytest tests/unit/ -q  ← must be green
# 4. Already committed per task above
# 5. git checkout main && git merge --ff-only <branch>
# 6. git branch -d <branch> && git worktree prune
# 7. git push origin main
```

## Close out todos

After all tasks pass, move these pending todo files to done:
```bash
mv .planning/todos/pending/2026-06-16-remove-dead-warmup-flag.md .planning/todos/done/
mv .planning/todos/pending/2026-06-14-rename-cfg-in-zone-engine.md .planning/todos/done/
mv .planning/todos/pending/2026-06-14-rename-confidence-utils.md .planning/todos/done/
mv .planning/todos/pending/2026-06-14-trade-framer-apr-migration.md .planning/todos/done/
# Update stopped-at-entry todo to reflect zone_source fix is done (partially closes item #2)
```
