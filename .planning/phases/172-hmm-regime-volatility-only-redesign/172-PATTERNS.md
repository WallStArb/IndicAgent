# Phase 172: HMM Regime — Volatility-Only Redesign - Pattern Map

**Mapped:** 2026-08-08
**Files analyzed:** 8 (1 same-file extension, 1 schema file, 2 new migrations, 1 script — no code
change needed, 3 downstream re-wiring targets, 1 doc, 1 test file)
**Analogs found:** 8 / 8 (every file has an in-repo analog — this phase generalizes existing
mechanisms, per RESEARCH.md's "Don't Hand-Roll" table; nothing needs an external pattern)

No CONTEXT.md exists for this phase — file list and design constraints are taken from
`172-RESEARCH.md` and `171-FINAL-VERDICT.md` §5–7 (locked decisions), per the orchestrator's
`<required_reading>` scope.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `services/regime_writer.py` (new symbols: `_VOLATILITY_LABEL_VOCAB`, `_build_obs_matrix_volatility`, `_fetch_obs_matrix_volatility`, `_build_label_map` generalized, `_state_groups` generalized, `_compute_symbol_tf_volatility_walk_forward`, `_write_regime_volatility_results`, `main()` dispatch) | batch/service (oneshot CPU-bound worker) | batch (fetch → fit → decode → bulk write) | same file's existing `_build_obs_matrix`/`_build_label_map`/`_state_groups`/`_compute_symbol_tf_walk_forward`/`_write_regime_results` (self-analog — same-file extension, exact precedent for todo 248's `_compute_symbol_tf_walk_forward` addition) | exact |
| `src/intelligence/features/feature_vector_persistence.py` (new `REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES` tuple + ownership-exclusion comment) | model/schema (Ring 1 column-ownership registry) | CRUD (single source of truth for INSERT/UPDATE column lists) | same file's existing `REGIME_WRITER_OWNED_COLUMN_NAMES` (lines 467-522) | exact |
| `production/migrations/307_regime_volatility_apr_and_schema.sql` (APR keys) | migration/config | batch (one-time DDL/DML, idempotent) | `production/migrations/292_hmm_walk_forward_apr.sql` | exact |
| `production/migrations/307_regime_volatility_apr_and_schema.sql` (CVR seed rows, or a sibling migration file) | migration/config | batch (one-time DML, idempotent) | `production/migrations/233_controlled_vocabulary_seed_namespaces.sql` | exact |
| `production/migrations/307_...sql` (new `feature_vectors` columns, if not already present) | migration/schema | batch (DDL, idempotent) | `production/migrations/158_hmm_probability_vector.sql` | exact |
| `scripts/analysis/hmm_production_regime_axes_null_arm_validation.py` | analysis script (offline, CLI) | batch (no code change — already has a `volatility` axis config, `--axes volatility` CLI flag) | itself — no change needed, listed here only because RESEARCH.md names it as an execution-wave dependency | n/a (reuse as-is) |
| `services/ic_engine.py` (regime-source cutover: startup gate, `alpha.regime.groups` handling, `feature_ic_scores.regime` source) | service/batch (stratification engine) | batch (SELECT/GROUP BY on `feature_vectors.regime` → cutover to `regime_volatility`) | itself — targeted sections (lines ~1655-1680 startup gate, ~2500-2730 regime-source resolution, ~4600-5050 `alpha.regime.groups` plumbing) are the analog for the cutover shape; no external analog needed | exact (self-referential, per RESEARCH.md Pitfall 2 this must be its own scoped plan, not a one-line rename) |
| `services/ensemble_trainer.py` (`ensemble_weights` keyed `(tf, regime)`, `regime != '_pooled'` eligibility) | service/batch | batch | itself, lines 121/395/437-447/738-952/1069-1131 (regime column threading) | exact |
| `docs/foundation/glossary.md` (`regime` entry rewrite, lines ~75-148) | docs | n/a | itself — existing `regime`/`regime_group`/`conditioning layer` entries are the template for structure (Not/Banned/Status/Disambiguation/Code surface sections) | exact |
| `tests/unit/services/test_regime_writer.py` (new `test_build_obs_matrix_volatility_*`, `test_build_label_map_volatility_vocab_*`, `test_write_regime_volatility_results_*` tests) | test | unit (synthetic-data, no DB) | itself — existing `test_build_obs_matrix_*` (lines 107-170) and `test_build_label_map_*` (lines 340-420+) test groups | exact |
| `src/config/vocabulary_drift.py` (new `regime_volatility` entry in `_WINDOWED_NAMESPACE_QUERIES`) | config/service (Ring 1 drift audit) | batch (bounded SELECT DISTINCT, compared against `VocabularyService`) | itself — existing `regime_hmm` entry (lines 149-152) | exact |

## Pattern Assignments

### `services/regime_writer.py` — new volatility code path (service/batch)

**Analog:** same file, existing trend-vocabulary functions (self-generalization, exactly the shape
`_compute_symbol_tf_walk_forward` was added in todo 248 alongside `_compute_symbol_tf`).

**Imports pattern** (already present, no new imports needed — `numpy`, `psycopg`, `structlog`,
`GaussianHMM`, `StandardScaler`, `_bulk_update_by_key`, `_load_config_service_shared` are already
imported at `services/regime_writer.py:52-89`):
```python
from __future__ import annotations
import numpy as np
import psycopg
import structlog
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler
from services._batch_utils import bulk_update_by_key as _bulk_update_by_key
from services._batch_utils import load_config_service_sync as _load_config_service_shared
from src.intelligence.features.feature_vector_persistence import (
    REGIME_WRITER_OWNED_COLUMN_NAMES,   # add REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES here too
)
```

**Vocabulary-parametrized label mapping — the core pattern to copy** (`_build_label_map`,
`services/regime_writer.py:497-541`, verbatim, generalize by adding a `vocab` param that defaults
to today's behavior — zero changes needed at existing call sites):
```python
def _build_label_map(means: np.ndarray) -> dict[int, str]:
    n_components = means.shape[0]
    means_ret = means[:, 0]  # log-return dimension
    order = np.argsort(means_ret)  # ascending: [most_neg, ..., most_pos]
    label_map: dict[int, str] = {}
    label_map[int(order[0])] = _LABEL_TRENDING_DOWN
    label_map[int(order[-1])] = _LABEL_TRENDING_UP
    if n_components >= 4:
        label_map[int(order[1])] = _LABEL_TRANSITION_DOWN
        label_map[int(order[-2])] = _LABEL_TRANSITION_UP
    for i in range(n_components):
        if i not in label_map:
            label_map[i] = _LABEL_RANGING
    return label_map
```
For K=2/K=3 (the only two configurations FINAL-VERDICT validates for volatility) the
`n_components >= 4` branch never fires — the volatility vocab only needs a 2- or 3-entry mapping,
no "transition" concept. Recommended vocab constants (RESEARCH.md Pattern 1):
```python
_VOLATILITY_VOCAB_K3 = {"low": "calm", "mid": "elevated", "high": "turbulent"}
_VOLATILITY_VOCAB_K2 = {"low": "calm", "high": "turbulent"}
```

**Column-0-drives-sort convention** (RESEARCH.md Assumption A3 — column 0 of the new 2-column
matrix MUST be `realized_vol`, not `vol_of_vol`, so the existing ascending-sort convention
produces calm→turbulent without inversion; confirm this at code-review time).

**Bullish/bearish state-grouping generalization to avoid** (`_state_groups`,
`services/regime_writer.py:307-318` — copy the *mechanism*, rename the *parameters*, per
RESEARCH.md's explicit Anti-Pattern warning):
```python
def _state_groups(label_map: dict[int, str]) -> tuple[list[int], list[int], list[int]]:
    """... Returns (bullish_states, ranging_states, bearish_states)."""
    bullish_states = [k for k, v in label_map.items() if v in _BULLISH_LABELS]
    ranging_states = [k for k, v in label_map.items() if v == _LABEL_RANGING]
    bearish_states = [k for k, v in label_map.items() if v in _BEARISH_LABELS]
    return bullish_states, ranging_states, bearish_states
```
Do NOT reuse `_BULLISH_LABELS`/`_BEARISH_LABELS` (trend-semantic names) for volatility bucketing —
generalize the parameter names too (`low_states`/`mid_states`/`high_states`), matching
`_alpha_history_to_regime_probs`'s existing `bullish_states`/`ranging_states`/`bearish_states`
signature shape (`services/regime_writer.py:321-361`) but renamed for the volatility axis.

**Walk-forward fitting — reuse unchanged, call unconditionally** (`_walk_forward_hmm_full`,
`services/regime_writer.py:656-824` — do not modify this function's causal-correctness logic;
`regime_volatility` calls it directly against the 2-column matrix with no
`alpha.hmm.walk_forward.enabled`-style gate, since there is no legacy corpus to protect — see
RESEARCH.md Pattern 3). Signature to call against, unchanged:
```python
def _walk_forward_hmm_full(
    obs_matrix: np.ndarray, n_components: int, covariance_type: str, n_iter: int,
    hmm_random_state: int, refit_every_bars: int, initial_warmup_bars: int,
    min_hold_bars: int, full_cov_min_obs: int, min_state_occupation: float,
    symbol: str | None = None, tf: str | None = None,
) -> list[dict[str, Any]]:
```

**New 2-column obs-matrix builder — dedicated function, not a slice** (analog:
`_build_obs_matrix`, `services/regime_writer.py:175-228` — copy the docstring shape and
`_rolling()` helper usage, build only 2 columns):
```python
def _build_obs_matrix(
    timestamps: list, closes: list[float], volumes: list[float],
    vol_window: int, momentum_window: int, vol_of_vol_window: int,
) -> tuple[np.ndarray, list]:
    """Build (n_valid, 5) observation matrix from OHLCV prices and volumes.
    Observation dimensions:
      [0] log_return   = ln(close[t] / close[t-1])
      [1] realized_vol = rolling std of log_returns over vol_window bars
      ...
    """
```
New function should mirror this docstring/return-shape convention but with signature
`_build_obs_matrix_volatility(timestamps, closes, vol_window, vol_of_vol_window) -> tuple[np.ndarray, list]`
returning `(n, 2)` with column 0 = `realized_vol`.

**Write pattern — mirror exactly, new column family** (`_write_regime_results`,
`services/regime_writer.py:1380-1462`, full function read — copy this shape verbatim for
`_write_regime_volatility_results`, changing only the `set_cols`/`col_types` dict and the
`WHERE regime_volatility IS NOT NULL`/`IS NULL` count query):
```python
def _write_regime_results(
    conn: Any, symbol: str, tf: str, update_rows: list[tuple],
    converged: bool, heldout_ll: float, tracer: Any,
) -> int:
    with tracer.start_as_current_span(
        "regime_writer.write_symbol_tf", attributes={"symbol": symbol, "tf": tf},
    ) as span:
        try:
            _bulk_update_by_key(
                conn, table="feature_vectors", temp_table="_regime_writer_staging",
                key_cols=["symbol", "tf", "bar_ts"],
                set_cols=list(REGIME_WRITER_OWNED_COLUMN_NAMES),
                col_types={...},
                rows=update_rows,
            )
            conn.commit()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FILTER (WHERE regime IS NOT NULL), "
                    "  count(*) FILTER (WHERE regime IS NULL) "
                    "FROM feature_vectors WHERE symbol = %s AND tf = %s", (symbol, tf),
                )
                ...
            return n_updated
        except Exception as error:
            from opentelemetry.trace import StatusCode
            span.set_status(StatusCode.ERROR, str(error))
            span.record_exception(error)
            raise
```
Error handling pattern: bare `except Exception as error:` (CLAUDE.md's mandated variable name),
set OTel span status + record_exception, then re-raise — no swallowing.

**`main()` CLI dispatch pattern** (`services/regime_writer.py:1647-1700+`, argparse structure to
extend — add a `--volatility-regime` flag or equivalent dispatch branch following the existing
`--walk-forward`/`--no-walk-forward` mutually-exclusive-group precedent):
```python
walk_forward_group = parser.add_mutually_exclusive_group()
walk_forward_group.add_argument("--walk-forward", action="store_true", dest="walk_forward", help="...")
walk_forward_group.add_argument("--no-walk-forward", action="store_false", dest="walk_forward", help="...")
parser.set_defaults(walk_forward=None)
```
APR-load block at `main()` lines 1736-1759 is the pattern for reading the new
`alpha.hmm_volatility.*` keys via `cfg.get_sync(key, default)` — same shape, new key names.

---

### `src/intelligence/features/feature_vector_persistence.py` — new owned-column tuple (Ring 1 schema)

**Analog:** `REGIME_WRITER_OWNED_COLUMN_NAMES`, lines 467-522 (full block read).

**Core pattern** (copy shape, new tuple name and column list):
```python
REGIME_WRITER_OWNED_COLUMN_NAMES: tuple[str, ...] = (
    "regime",
    "hmm_prob_trending_up",
    "hmm_prob_ranging",
    "hmm_prob_trending_down",
    "hmm_regime_prob",
    "hmm_entropy",
    "hmm_duration",
    "hmm_churn",
)
_EXTERNALLY_OWNED_COLUMN_NAMES = frozenset(REGIME_WRITER_OWNED_COLUMN_NAMES) | {
    "regime_label_source"
}
_UPDATE_SET_SQL = ",\n    ".join(
    f"{name} = EXCLUDED.{name}"
    for name in _ALL_COLUMN_NAMES
    if name not in _PK_COLUMN_NAMES and name not in _EXTERNALLY_OWNED_COLUMN_NAMES
)
```
**Load-bearing invariant to preserve:** the comment block immediately above this tuple
(lines 460-519) documents the exact 2026-07-30 incident this pattern exists to prevent — a
`--refresh` recompute overwriting `regime` back to NULL because it wasn't excluded from
`DO UPDATE SET`. `REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES` must be unioned into
`_EXTERNALLY_OWNED_COLUMN_NAMES` the same way, or the identical corpus-wide NULL-out incident
repeats for the new column. This is the single most important pattern in this phase to copy
exactly, not approximately.

---

### `production/migrations/307_regime_volatility_apr_and_schema.sql` — APR keys (migration/config)

**Analog:** `production/migrations/292_hmm_walk_forward_apr.sql` (full file read, reproduced above
in RESEARCH.md's Code Examples — verbatim shape confirmed correct).

**Core pattern:**
```sql
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'alpha.hmm_volatility.n_components', 'int', '3', 2, 3,
    '[rca_analysis] Phase 172: K for the volatility-only regime HMM (realized_vol, vol_of_vol). '
    'Both K=2 and K=3 cleared the null-arm block-reliability control per 171-FINAL-VERDICT.md '
    'section 3; K=3 preserves the calm/elevated/turbulent framing. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('alpha.hmm_volatility.n_components', '3', 1)
ON CONFLICT (config_key) DO NOTHING;
```
**Provenance-tag discipline to copy:** migration 292 tags every value `[rca_analysis]` or
`[initial_estimate]` per column, with a comment explaining exactly which pilot measurement backs
it (or that it's unpiloted at that tf). RESEARCH.md Pitfall 1 requires the same discipline for the
new `vol_of_vol_window` key — do not silently inherit `feature.hmm.obs_vol_of_vol_window`'s value
of 20 without a `[rca_analysis]`-tagged comment citing the FINAL-VERDICT §6 window-sensitivity
finding (thin margin at 20, solid from 60+).
**`enabled` gate — do NOT copy this part:** migration 292's `alpha.hmm.walk_forward.enabled`
default-false gate exists because that code changes an existing live column's values. Per
RESEARCH.md Pattern 3, `regime_volatility` is a brand-new column with no legacy corpus — no
equivalent enable-gate key is needed; the walk-forward path runs unconditionally.

---

### `production/migrations/307_...sql` — CVR seed (migration/config)

**Analog:** `production/migrations/233_controlled_vocabulary_seed_namespaces.sql` (full file
read).

**Core pattern** (new namespace, NOT a repoint of the existing `regime_hmm` namespace):
```sql
INSERT INTO controlled_vocabulary (namespace, code, label, description, sort_order) VALUES
('regime_volatility', 'calm',      'Calm',      'Lowest realized-vol / vol-of-vol HMM state', 1),
('regime_volatility', 'elevated',  'Elevated',  'Middle realized-vol / vol-of-vol HMM state (K=3 only)', 2),
('regime_volatility', 'turbulent', 'Turbulent', 'Highest realized-vol / vol-of-vol HMM state', 3)
ON CONFLICT (namespace, code) DO NOTHING;
```
Idempotency convention to copy: every statement `ON CONFLICT (namespace, code) DO NOTHING`,
wrapped in `BEGIN;`/`COMMIT;` (migration 233's outer transaction wrapper). If a
`vocabulary_group` is warranted for the volatility namespace (e.g. grouping calm+elevated as
"non-turbulent"), mirror migration 233's `vocabulary_group`/`vocabulary_group_member` INSERT
shape (lines for `regime_hmm`'s `trending`/`transition`/`bullish_bias`/`bearish_bias` groups) —
likely unnecessary for a 2-3-code namespace with no natural sub-grouping, but the pattern exists
if needed.

---

### `production/migrations/307_...sql` — new `feature_vectors` columns (migration/schema)

**Analog:** `production/migrations/158_hmm_probability_vector.sql` (full file read, 23 lines).

**Core pattern:**
```sql
ALTER TABLE feature_vectors
    ADD COLUMN IF NOT EXISTS regime_volatility          TEXT,
    ADD COLUMN IF NOT EXISTS hmm_vol_prob_calm           DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS hmm_vol_prob_elevated       DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS hmm_vol_prob_turbulent      DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS hmm_vol_regime_prob         DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS hmm_vol_entropy             DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS hmm_vol_duration            DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS hmm_vol_churn               DOUBLE PRECISION;
```
`IF NOT EXISTS` idempotency guard is the pattern to copy verbatim — migration 158's own comment
calls this out explicitly ("Idempotent: IF NOT EXISTS guards make re-application safe"). Column
count should mirror `REGIME_WRITER_OWNED_COLUMN_NAMES`'s existing 8-column shape (regime + 3 prob
+ regime_prob + entropy + duration + churn), minus one prob column at K=2 vs K=3 — keep all 3
prob columns regardless of K (K=2 just leaves `hmm_vol_prob_elevated` NULL) for schema stability
across a future K=2/K=3 config change.

---

### `services/ic_engine.py` — regime-source cutover (service/batch)

**Analog:** itself — no external file needed. The cutover touches four semi-independent pieces of
machinery (RESEARCH.md Pitfall 2); plan this as its own scoped wave, not folded into the
`regime_writer.py` plan.

**Startup gate to update** (`services/ic_engine.py:1664-1668`):
```python
cur.execute("SELECT count(*) FROM feature_vectors WHERE regime IS NOT NULL")
...
"IC Engine startup gate FAILED: feature_vectors.regime is all-NULL. "
```
Cutover changes this to `regime_volatility IS NOT NULL` (or checks both during the transition
window per RESEARCH.md Open Question 1's recommended phased-cutover approach: keep `regime`
readable, repoint `ic_engine.py` to read `regime_volatility` as primary).

**Regime-source resolution to update** (`services/ic_engine.py:2528-2529, 2672-2728`):
```python
# instead of feature_vectors.regime, enabling cross-symbol IC stratification.
# When None (equity_model_enabled=False), falls back to feature_vectors.regime.
...
# Regime source: market_regimes (cross-sectional) or feature_vectors.regime (per-symbol).
```
This is the per-symbol (idiosyncratic) fallback branch — repoint to `regime_volatility`.
`_POOLED_REGIME_SENTINEL = "_pooled"` (line 173) and `alpha.regime.groups` JSON-APR routing
(lines 601-671, 4600-5050 per RESEARCH.md) are separate, unaffected machinery — the cross-sectional
`market_regimes` system is untouched by this phase (FINAL-VERDICT only retires the idiosyncratic
`feature_vectors.regime`, not the systematic `market_regimes` system — confirmed via
`docs/foundation/glossary.md`'s Dual Regime System distinction).

---

### `services/ensemble_trainer.py` — regime-keyed weights (service/batch)

**Analog:** itself, lines 121 (`regime != '_pooled'` filter), 395/437-447 (`_META_COLS`-style
exclusion list — same pattern as `feature_vector_persistence.py`'s ownership tuple, applied here
to training-column exclusion), 738-952 (per-`(tf, regime)` stratum processing), 1069-1131
(`ensemble_weights` INSERT keyed `(symbol, tf, regime, weight_version, feature_name)`).

**Core pattern** (`services/ensemble_trainer.py:738-763`):
```python
SELECT DISTINCT tf, regime
FROM feature_ic_scores
WHERE ... AND regime IS NOT NULL
ORDER BY tf, regime
...
regime = stratum["regime"]
...
```
This treats `regime` as an opaque GROUP BY key (RESEARCH.md's confirmed finding — no
string-matching on specific label values anywhere in this file) — the cutover is a column-name
repoint, not a logic rewrite, once `feature_ic_scores.regime` itself is populated from
`regime_volatility` upstream by the `ic_engine.py` cutover.

---

### `docs/foundation/glossary.md` — `regime` entry rewrite (docs)

**Analog:** itself — existing `regime` entry (lines 75-97 of the read excerpt) and sibling
`regime_group`/`conditioning layer` entries as structural templates.

**Section structure to preserve** (copy this shape, replace idiosyncratic-regime content):
```markdown
### `regime`

A discrete conditioning-state label that partitions bars into groups expected to behave
differently downstream ... Two coexisting mechanisms fill this contract today ...

- **Idiosyncratic regime** (aka **symbol regime**) — per-symbol `GaussianHMM` state
  (K=2/K=3 labels: `calm`, `elevated`, `turbulent`), fit per (symbol, timeframe) from
  realized_vol/vol_of_vol observations only. Stored in `feature_vectors.regime_volatility`.
- **Systematic regime** (aka **market regime**) — cross-sectional VIX×breadth state
  (unchanged) ...

**Banned:** (reuse the existing `regime` entry's banned-synonym list unchanged — do not add or
remove entries from it as part of this rewrite)
**Status:** active

**Disambiguation:** ...
**Code surface:** `feature_vectors.regime_volatility` (idiosyncratic/symbol, `regime_writer.py`),
`market_regimes` (systematic/market, unchanged), ...
```
Per CLAUDE.md's canonical-docs-standalone rule, this entry must state what/why/alternatives on
its own — do not point at `171-FINAL-VERDICT.md`. Note per RESEARCH.md Pitfall 3: this doc update
is a phase deliverable, not optional polish — `git log docs/foundation/glossary.md` at phase close
must show a touch.

---

### `tests/unit/services/test_regime_writer.py` — volatility test coverage (unit test)

**Analog:** itself — `test_build_obs_matrix_shape`/`test_build_obs_matrix_no_nan`/
`test_build_obs_matrix_log_return_sign`/`test_build_obs_matrix_insufficient_data` (lines 107-170,
full read) and `test_build_label_map_covers_all_states`/`test_build_label_map_canonical_values`/
`test_build_label_map_trending_up_has_highest_mean` (lines 340-420+, full read).

**Fixture pattern to reuse directly** (already generic, no change needed — lines 46-99):
```python
def _make_trending_up_closes(n: int = 500, seed: int = 42) -> list[float]: ...
def _make_ranging_closes(n: int = 500, seed: int = 99) -> list[float]: ...
def _make_timestamps(n: int): ...
def _fit_simple_hmm(obs_matrix: np.ndarray, n_components: int = 3) -> GaussianHMM: ...
```
Recommend adding a `_make_volatile_closes` fixture (large-variance regime-switching series) as
the volatility-axis analog to `_make_trending_up_closes`, since a monotonic trend series doesn't
exercise the calm/turbulent boundary meaningfully.

**Shape test pattern to copy** (`test_build_obs_matrix_shape`, lines 107-125):
```python
def test_build_obs_matrix_shape():
    """obs_matrix should have shape (n-1-vol_window, 5) for 5D observation vector."""
    ...
    obs, valid_ts = _build_obs_matrix(timestamps, closes, volumes, vol_window, momentum_window, vol_of_vol_window)
    expected_rows = n - vol_window
    assert obs.shape == (expected_rows, 5), f"Expected ({expected_rows}, 5), got {obs.shape}"
```
New `test_build_obs_matrix_volatility_shape` asserts `(expected_rows, 2)` instead of `(..., 5)`.

**Label-map canonical-values test pattern to copy** (`test_build_label_map_canonical_values`,
lines 357-373):
```python
def test_build_label_map_canonical_values():
    """All label values must be one of the three canonical strings."""
    ...
    label_map = _build_label_map(model.means_)
    valid_labels = {_LABEL_TRENDING_UP, _LABEL_TRENDING_DOWN, _LABEL_RANGING}
    for state, label in label_map.items():
        assert label in valid_labels, f"State {state} has invalid label '{label}'"
```
New `test_build_label_map_volatility_vocab_k2`/`_k3` assert against `{"calm", "turbulent"}` /
`{"calm", "elevated", "turbulent"}` when `vocab=_VOLATILITY_VOCAB_K2`/`_VOLATILITY_VOCAB_K3` is
passed. Per RESEARCH.md Pitfall 4, add an explicit K=2-with-volatility-vocab test to catch a
missing-vocab-key `KeyError` before it ships.

---

### `src/config/vocabulary_drift.py` — new namespace registration (config/Ring 1)

**Analog:** itself, `_WINDOWED_NAMESPACE_QUERIES["regime_hmm"]`, lines 148-152 (full file read).

**Core pattern:**
```python
_WINDOWED_NAMESPACE_QUERIES: dict[str, str] = {
    "regime_hmm": (
        "SELECT DISTINCT regime FROM feature_vectors "
        "WHERE bar_ts > now() - ($1 || ' days')::interval AND regime <> ''"
    ),
    # ADD:
    "regime_volatility": (
        "SELECT DISTINCT regime_volatility FROM feature_vectors "
        "WHERE bar_ts > now() - ($1 || ' days')::interval AND regime_volatility <> ''"
    ),
    ...
}
```
`extract_regime_hmm_codes`'s empty-string-placeholder-drop pattern (lines 76-83) generalizes
directly — either reuse it for `regime_volatility` too (rename to a generic
`extract_regime_codes`, or just call the same function since the logic is identical: drop `''`)
or add a parallel `extract_regime_volatility_codes`. `assert_namespace_coverage` (lines 99-119)
will fail loud if the new namespace isn't also registered in `VocabularyService` via the CVR
migration — this is a real cross-check, not decorative, so the CVR migration and this file's
update must land together or `VocabularyDriftAuditor.execute()` raises `RuntimeError` at run time.
**Decision point for the planner:** whether the legacy `regime_hmm` entry gets removed from this
dict in the same phase (RESEARCH.md Open Question 1 recommends NOT dropping the legacy `regime`
column/namespace in this phase — keep both entries until the cutover is confirmed stable across
one full corpus cycle).

## Shared Patterns

### APR key provisioning
**Source:** `production/migrations/292_hmm_walk_forward_apr.sql`
**Apply to:** the new migration's `config_schema`/`config_state` INSERT pairs (n_components,
vol_window, vol_of_vol_window keys under `alpha.hmm_volatility.*`)
```sql
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (...) ON CONFLICT (config_key) DO NOTHING;
INSERT INTO config_state (config_key, config_value, version)
VALUES (...) ON CONFLICT (config_key) DO NOTHING;
```
Every value tagged `[rca_analysis]`/`[initial_estimate]` with a specific citation to the pilot or
FINAL-VERDICT section backing it — never an unexplained default.

### Controlled-vocabulary seeding
**Source:** `production/migrations/233_controlled_vocabulary_seed_namespaces.sql`
**Apply to:** the new `regime_volatility` namespace seed (new namespace, not a repoint of
`regime_hmm`)
```sql
INSERT INTO controlled_vocabulary (namespace, code, label, description, sort_order) VALUES (...)
ON CONFLICT (namespace, code) DO NOTHING;
```

### Column-ownership single-source-of-truth
**Source:** `src/intelligence/features/feature_vector_persistence.py:467-522`
**Apply to:** `REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES` — must be excluded from
`_UPDATE_SET_SQL`'s `DO UPDATE SET` list the same way `REGIME_WRITER_OWNED_COLUMN_NAMES` is,
or a `--refresh` recompute will NULL out the new column corpus-wide (repeat of the 2026-07-30
incident this exact mechanism was built to prevent).

### Error handling (OTel span + re-raise)
**Source:** `services/regime_writer.py:1457-1462` (`_write_regime_results`'s except block)
**Apply to:** `_write_regime_volatility_results` and any new write path
```python
except Exception as error:
    from opentelemetry.trace import StatusCode
    span.set_status(StatusCode.ERROR, str(error))
    span.record_exception(error)
    raise
```
Exception variable name is `error` (CLAUDE.md mandate, not `exc`).

### Bare Exception-variable / logging conventions
**Source:** `services/regime_writer.py` throughout (structlog `_logger.info(...)` with
`symbol=`/`tf=` bound context, never per-row logging in a loop over the full corpus)
**Apply to:** all new logging in the volatility path — reuse the same
`regime_writer.walk_forward_hmm_convergence_iters`-style event-naming convention
(`regime_writer.<verb>_<noun>`) for any new log events (e.g.
`regime_writer.volatility_symbol_tf_done`).

## No Analog Found

None. Every file in scope generalizes an existing in-repo mechanism per RESEARCH.md's "Don't
Hand-Roll" table — this phase is disciplined generalization plus new schema/config rows, not new
infrastructure.

## Metadata

**Analog search scope:** `services/regime_writer.py`, `src/intelligence/features/
feature_vector_persistence.py`, `production/migrations/*.sql` (233, 158, 292), `src/config/
vocabulary_drift.py`, `services/ic_engine.py`, `services/ensemble_trainer.py`,
`tests/unit/services/test_regime_writer.py`, `docs/foundation/glossary.md`,
`scripts/analysis/hmm_production_regime_axes_null_arm_validation.py`
**Files scanned:** 9 direct reads (all targeted/non-overlapping ranges except `regime_writer.py`
and `vocabulary_drift.py`, which were read in fewer, larger passes given their central role)
**Pattern extraction date:** 2026-08-08
**Next free migration number confirmed:** 307 (latest on disk: `306_commodity_regime_group_
unification.sql`; re-check at execution time per RESEARCH.md Assumption A1 — Phase 170 is running
concurrently and may claim numbers first)
