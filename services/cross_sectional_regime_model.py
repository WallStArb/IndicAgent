#!/usr/bin/env python3
"""Cross-Sectional Regime Model — generic dispatcher that populates market_regimes.

Generalizes the original single-asset-class equity regime model (Phase 144; the
predecessor module was deleted as dead code, todo 381 -- its causal-rank/tf-window
logic lives on in src/intelligence/regime_signals/): instead of a single hardcoded
'equity' label, this dispatcher iterates every enabled group in APR key alpha.regime.groups
(JSON array) and writes group-scoped regime labels to market_regimes.regime_group
(migration 222 renamed asset_class -> regime_group).

Groups are defined in APR key alpha.regime.groups (JSON array). Each group:
  - name: string key written to market_regimes.regime_group
  - tag_filter: list of tag patterns (prefix match, * stripped) to resolve peer symbols
  - signal_tag_filter: optional narrower filter for PEER (signal-input) resolution --
    peers resolve from this when present, from tag_filter otherwise. Routing to
    measurement (ic_engine._build_symbol_regime_class) always uses tag_filter, so a
    group can measure a wider symbol set than feeds its regime signal, freezing the
    signal input (and therefore every label it produces) against membership growth
  - signal_type: key in src/intelligence/regime_signals/REGISTRY
  - params_prefix: APR namespace for signal thresholds
  - enabled: bool

Signal modules (src/intelligence/regime_signals/) implement:
  - compute(ref_bars, params) -> (pd.Series, pd.Series) | None
  - build_tiers(params) -> (tiers1, tiers2)
  - PROB_KEYS: tuple[str, str]

Data flow per group per TF:
  1. Resolve peer symbols from instrument_tags (startup, once)
  2. Fetch all peer (+ reference) symbol bars for this TF (fresh connection, avoids
     idle termination)
  3. Pre-scale the group's daily-bar-denominated window params to this TF via
     _tf_window() (RESEARCH.md Pattern 5 — window params in alpha.*_regime.* APR
     keys are always DAILY-bar counts; every signal module stays TF-agnostic)
  4. Call signal_module.compute(ref_bars, scaled_params) -> (sig1, sig2)
  5. Align signals, drop NaN warmup rows
  6. Call _assign_labels(...) -> list[tuple]
  7. Replace the (regime_group, tf) history atomically (`_replace_group_tf`): COPY the rows into
     a temp stage, diff it against the stored rows (orphaned, changed, new), refuse an
     unexpected shrink or rewrite, then delete the orphans and upsert the changed and new rows in
     one transaction (todo 420). A stored row the run no longer produces (an orphan from an older
     writer, a weekend bar) is deleted instead of surviving an upsert forever.

Not a real-time daemon — this is a batch/oneshot labeling tool exempt from the
"only writer subclasses touch DB" rule, same as backfill_feature_factory.py.
Single-process, no worker pool: DB fetch is the
bottleneck, label assignment is vectorized numpy (a pool would add no throughput).

Usage:
    python services/cross_sectional_regime_model.py
    python services/cross_sectional_regime_model.py --tf 5m 1h
    python services/cross_sectional_regime_model.py --dry-run
    python services/cross_sectional_regime_model.py \
        --accept-orphan-delete 2500000 --accept-changed 400000 --reason "todo 420 cleanup"

`--dry-run` stages and diffs without touching market_regimes (orphans split by weekday and
weekend, and how many orphaned, changed and new timestamps join a feature_vectors row), and
prints one JSON report. A write takes the cell's advisory lock, deletes only the orphans and
upserts only the changed and new rows. A cell whose orphans exceed APR
`alpha.regime.cross_sectional.max_orphan_delete_fraction`, or whose changed rows exceed
`alpha.regime.cross_sectional.max_changed_fraction`, of its stored rows refuses; the override is a
reviewed count per limit (`--accept-orphan-delete=N`, `--accept-changed=N`, with `--reason`), and
the decision is appended to `market_regimes_override` in the same transaction.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
import pandas as pd
import psycopg
import structlog

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import connect_db_from_url
from services._batch_utils import load_config_service_sync as _load_config_service
from src.config.settings import Settings
from src.core.service_utils import setup_service_logging
from src.intelligence.regime_signals import REGISTRY
from src.intelligence.regime_signals.tf_window import _tf_window
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers

setup_service_logging("logs/cross_sectional_regime_model.log")

_logger = structlog.get_logger(__name__)

_JOB = "cross-sectional-regime-model"
_DEFAULT_TFS: list[str] = ["5m", "15m", "1h", "1d"]

# Fallback default for cfg.get_sync("alpha.regime.groups", ...) — matches migration
# 222's seeded config exactly. Only used if the APR key is somehow unset (should not
# happen post-migration; this is a defensive fallback, not the source of truth).
_DEFAULT_GROUPS_JSON = json.dumps(
    [
        {
            "name": "equity",
            "tag_filter": ["eq_*", "intl_*"],
            "signal_type": "breadth_vol",
            "params_prefix": "alpha.equity_regime",
            "enabled": True,
        },
        {
            "name": "rates",
            "tag_filter": ["fi_*"],
            "signal_type": "curve_credit",
            "params_prefix": "alpha.rates_regime",
            "enabled": True,
        },
        {
            "name": "commodity_energy",
            "tag_filter": [
                "commodity_energy_crude",
                "commodity_energy_natgas",
                "commodity_energy_pipeline",
            ],
            "signal_type": "commodity_momentum_ts",
            "params_prefix": "alpha.commodity_energy_regime",
            "enabled": False,
        },
        {
            "name": "commodity_metals",
            "tag_filter": ["commodity_metals_precious", "commodity_metals_industrial"],
            "signal_type": "commodity_momentum_ts",
            "params_prefix": "alpha.commodity_metals_regime",
            "enabled": False,
        },
        {
            "name": "commodity_agri",
            "tag_filter": ["commodity_agri"],
            "signal_type": "commodity_momentum_ts",
            "params_prefix": "alpha.commodity_agri_regime",
            "enabled": False,
        },
        {
            "name": "fx",
            "tag_filter": ["fx_*", "crypto"],
            "signal_type": "fx_dollar_carry",
            "params_prefix": "alpha.fx_regime",
            "enabled": False,
        },
    ]
)

# Window-param keys treated as DAILY-bar counts, pre-scaled to the target TF via
# _tf_window() before being passed to a signal module's compute(). Every group's
# window-denominated APR key (see migration 222's config_schema descriptions) is
# named with a "_window" suffix by convention — this set enumerates the exact keys
# accepted by each signal module today (breadth_vol/curve_credit/commodity_momentum_ts/
# fx_dollar_carry all read one of these from `params`, per their compute() signatures).
_WINDOW_PARAM_KEYS: frozenset[str] = frozenset(
    {
        "realized_vol_window",
        "vix_z_window",
        "ma_window",
        "curve_window",
        "credit_window",
        "momentum_window",
    }
)

# ---------------------------------------------------------------------------
# Pure helpers — exported for unit tests
# ---------------------------------------------------------------------------


def _parse_group_configs(raw: str | list[dict]) -> list[dict]:
    """Parse and filter group config JSON from APR. Returns only enabled groups.

    Accepts EITHER a raw JSON string OR an already-parsed list[dict].

    The JSON-typed APR key alpha.regime.groups returns an ALREADY-PARSED list[dict]
    once cached: ConfigService._parse_value() calls json.loads() at cache-load time
    for value_type='json' keys (src/config/config_service.py:94-95), and
    load_config_service_sync() (services/_batch_utils.py) populates the cache via
    that same _parse_value() path. Calling json.loads() again on an already-parsed
    list, or str()-ing it first, are both bugs: str(list_of_dicts) produces a
    Python-repr string (single quotes, True/False) that is NOT valid JSON and raises
    inside a second json.loads() call. The isinstance(raw, list) branch below is what
    actually fires for the live cached value; the json.loads() branch exists for
    callers passing a raw string directly (tests, or a string-typed fallback default).
    """
    if isinstance(raw, list):
        configs = raw
    else:
        try:
            configs = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as error:
            raise ValueError(f"alpha.regime.groups contains invalid JSON: {error}") from error
    return [g for g in configs if g.get("enabled", True)]


def _resolve_group_symbols(
    tags_by_symbol: dict[str, set[str]],
    tag_filter: list[str],
) -> list[str]:
    """Return sorted list of symbols whose tags match any pattern in tag_filter.

    Pattern matching: strip trailing '*' and test if any tag starts with that prefix.
    """
    prefixes = [p.rstrip("*") for p in tag_filter]
    matched = [
        sym
        for sym, tags in tags_by_symbol.items()
        if any(any(t.startswith(pfx) for t in tags) for pfx in prefixes)
    ]
    return sorted(matched)


def _assert_ascending_tiers(
    tiers: list[tuple[str, float]], group_name: str = "<unknown>", tier_label: str = "<unknown>"
) -> None:
    """Crash-loud guard (todo 335, hardened in code review): _bucket() silently
    mis-labels a malformed tiers list instead of raising -- confirmed live in
    commodity_momentum_ts and fx_dollar_carry, where a descending list caused the
    last-applied (widest) where() clause to overwrite every narrower bucket,
    collapsing half of both modules' label vocabularies to permanently-unreachable
    dead states. Requires STRICTLY ascending bounds (ties are also rejected -- a
    repeated bound reproduces the same overwrite-collapse bug even though the list
    is technically non-decreasing) and at least 2 tuples (a single-entry list is
    the exact shape of fx_dollar_carry's original tiers2 bug: every _bucket() call
    falls through to the sole catch-all tuple, and every other label is
    permanently unreachable without _bucket() ever raising).
    """
    if len(tiers) < 2:
        raise ValueError(
            f"{group_name}.{tier_label} has only {len(tiers)} tuple(s): {tiers} -- "
            f"_bucket() needs at least one real threshold plus a catch-all; a single-entry "
            f"list makes every OTHER label permanently unreachable without raising (todo 335)."
        )
    bounds = [upper for _, upper in tiers[:-1]]
    if bounds != sorted(set(bounds)):
        raise ValueError(
            f"{group_name}.{tier_label} is not STRICTLY ascending-sorted by upper_bound: "
            f"{tiers} -- _bucket() requires strictly ascending order with no ties (last "
            f"tuple's bound is ignored, only its name is used as the catch-all default); a "
            f"descending or tied list silently collapses buckets instead of raising (todo 335)."
        )


def _assert_ascending_timestamps(ts_arr: list, group_name: str, tf: str) -> None:
    """Crash-loud guard (todo 005/335-shaped): _smooth_labels' hysteresis logic assumes
    ts_arr is strictly causally ordered -- a min-hold-bars smoother computed over an
    out-of-order or duplicate-timestamp sequence would confirm transitions against the
    wrong neighbors, silently producing a plausible-looking but wrong label sequence.
    Never assume sortedness from an upstream signal_mod.compute() call (todo 335's own
    lesson: two of four regime_signals modules violated a similar ascending-order
    contract undetected until this project started asserting it explicitly). Cheap
    (O(n), no allocation) relative to the smoothing pass itself.
    """
    if len(ts_arr) < 2:
        return
    for i in range(1, len(ts_arr)):
        if ts_arr[i] <= ts_arr[i - 1]:
            raise ValueError(
                f"cross_sectional_regime_model: ts_arr not strictly ascending for "
                f"group={group_name!r} tf={tf!r} at index {i} ({ts_arr[i - 1]!r} -> "
                f"{ts_arr[i]!r}) -- _smooth_labels requires causal time order; a "
                f"signal_mod.compute() implementation likely returned an unsorted or "
                f"duplicate-timestamp index."
            )


def _smooth_labels(raw_labels: np.ndarray, min_hold: int) -> np.ndarray:
    """Minimum holding-period smoother for string tier labels (todo 005).

    Requires min_hold consecutive bars of the same new label before confirming a
    transition -- causal, no look-ahead. Ports regime_writer.py's _smooth_states
    (the per-symbol HMM path's existing, tested pattern) to string/object-dtype
    label arrays instead of integer HMM state indices; the confirmation logic is
    otherwise identical.

    Fixes a real measurement-integrity gap (todo 005): _bucket() alone does pure
    per-bar threshold bucketing with zero hysteresis -- a value oscillating around
    a tier boundary flips regime_label on literally the next bar with nothing
    smoothing it, contaminating which stratum's IC a boundary-adjacent bar
    contributes to in every regime-stratified measurement downstream. Unlike
    regime_writer.py's HMM path (which already has this protection via
    _smooth_states), market_regimes -- the label source ic_engine.py actually
    stratifies on when equity_model_enabled=true -- had none until this fix.
    """
    if min_hold <= 1:
        return raw_labels.copy()
    n = len(raw_labels)
    smoothed = raw_labels.copy()
    current = raw_labels[0]
    for t in range(1, n):
        if t < min_hold:
            smoothed[t] = current
            continue
        window = raw_labels[t - min_hold + 1 : t + 1]
        if np.all(window == raw_labels[t]):
            current = raw_labels[t]
        smoothed[t] = current
    return smoothed


def _bucket(
    vals: np.ndarray,
    tiers: list[tuple[str, float]],
    *,
    group_name: str = "<unknown>",
    tier_label: str = "<unknown>",
) -> np.ndarray:
    """Assign tier names by threshold. tiers sorted ascending by upper_bound; last = inf.

    A value is assigned to the first tier whose upper_bound STRICTLY exceeds the value.
    Validates tiers on every call (code review, todo 335) rather than relying on callers
    to remember _assert_ascending_tiers -- scripts/analysis/regime_boundary_churn_check.py
    calls this directly without going through main()'s explicit guard, so the contract has
    to live here to cover every caller, not just main()'s.
    """
    _assert_ascending_tiers(tiers, group_name, tier_label)
    result = np.full(len(vals), tiers[-1][0], dtype=object)
    for name, upper in reversed(tiers[:-1]):
        result = np.where(vals < upper, name, result)
    return result


def _assign_labels(
    group_name: str,
    tf: str,
    ts_arr: list,
    sig1_arr: np.ndarray,
    sig2_arr: np.ndarray,
    tiers1: list[tuple[str, float]],
    tiers2: list[tuple[str, float]],
    prob_keys: tuple[str, str],
    min_hold_bars: int = 1,
) -> list[tuple]:
    """Vectorized label assignment. No DB, no pandas.

    Returns list of (regime_group, tf, ts, regime_label, prob_dict) — regime_group is
    set on EVERY emitted row (column renamed from asset_class per migration 222).
    regime_label = "{tier1}_{tier2}".

    LABEL-VOCABULARY-UNIQUENESS INVARIANT (RESEARCH.md Pitfall 4): feature_ic_scores
    has no regime_group column — group identity is implicit in regime_label string
    uniqueness across all enabled groups. Every signal module's build_tiers() tier
    vocabulary MUST stay non-overlapping with every other enabled group's vocabulary
    (breadth_vol/curve_credit/commodity_momentum_ts/fx_dollar_carry document this
    invariant in their own module docstrings). If a future group's build_tiers() ever
    reuses a tier name from another enabled group, two semantically different regimes
    would collide under the same regime_label string in downstream feature_ic_scores
    rows, silently corrupting ensemble eligibility queries. Not schema-enforced —
    verify manually when adding a new group's signal module.

    min_hold_bars (todo 005, default 1 = no-op, preserving every pre-existing direct
    caller's exact behavior including scripts/analysis/regime_boundary_churn_check.py's
    single-value _bucket() calls which never go through this function anyway): applies
    _smooth_labels independently to each tier dimension (labels1, labels2) BEFORE
    combining into the final "{tier1}_{tier2}" string -- the two signals can transition
    at unrelated times with different noise characteristics, so smoothing them jointly
    post-combination would conflate two independent hysteresis decisions into one.
    regime_prob_vector still reports the RAW (unsmoothed) sig1_arr/sig2_arr values at
    each bar regardless of min_hold_bars -- it is a continuous diagnostic of the
    underlying signal, not a restatement of the (possibly-smoothed) discrete label.
    ts_arr must be strictly ascending (_assert_ascending_timestamps) whenever
    min_hold_bars > 1 -- the smoother's causal-confirmation logic depends on true
    temporal order, which no upstream signal_mod.compute() call is trusted to
    guarantee without an explicit check (todo 335's own lesson).
    """
    if min_hold_bars > 1:
        _assert_ascending_timestamps(ts_arr, group_name, tf)
    labels1 = _bucket(sig1_arr, tiers1, group_name=group_name, tier_label="tiers1")
    labels2 = _bucket(sig2_arr, tiers2, group_name=group_name, tier_label="tiers2")
    labels1 = _smooth_labels(labels1, min_hold_bars)
    labels2 = _smooth_labels(labels2, min_hold_bars)
    return [
        (
            group_name,
            tf,
            ts_arr[i],
            f"{labels1[i]}_{labels2[i]}",
            {prob_keys[0]: float(sig1_arr[i]), prob_keys[1]: float(sig2_arr[i])},
        )
        for i in range(len(ts_arr))
    ]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _load_tags_by_symbol(conn: Any) -> dict[str, set[str]]:
    """source='human' only -- an interim stopgap (todo 379), NOT the same reasoning as
    ic_engine.py's _build_symbol_regime_class fix (commit b8af2b749). That fix was a
    categorical-identity question (exactly one regime group); this is a sensitivity/
    behavioral-similarity question ("does this symbol trade like its peer group"), where
    an empirical tag is arguably philosophically more correct evidence, not less. It's
    filtered out here anyway because TagCalibrator's empirical tags are currently
    drowning in common-beta noise (confirmed: significance alone does not separate
    signal from noise -- filtering by passes_fdr=true instead of by source resolved 0 of
    the ic_engine.py bug's 144 collisions), and confirmed live to contaminate this path
    too (GLD/AGG/EMB/EMLC/DBC/FXA/FXE mislabeled eq_*). This is a bigger hammer than the
    underlying question calls for -- it discards empirical sensitivity data that may have
    genuine value once properly filtered for real economic meaning, not just presence.
    See docs/plans/2026-09-17-itr-source-filter-breadth-peer-grouping-design.md and todo
    379 for the deferred materiality-filtered design (option b) this stopgap does not
    implement. Cross-AI reviewed (Codex + Fable + AGY) before landing.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, array_agg(tag) FROM instrument_tags "
            "WHERE source = 'human' GROUP BY symbol"
        )
        return {row[0]: set(row[1]) for row in cur.fetchall()}


def _fetch_group_bars(dsn: str, tf: str, symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Fetch close prices for all symbols in one query. Returns dict[symbol, DataFrame].

    Uses a fresh connection to avoid idle-connection termination during long fetches
    (the 2026-07-08 idle-connection data-loss incident rationale, originally worked
    around in the now-deleted equity_regime_model.py -- todo 381).
    """
    sql = """
        SELECT symbol, timestamp, close
        FROM market_data_ohlcv_tradeable
        WHERE symbol = ANY(%s) AND timeframe = %s
        ORDER BY symbol, timestamp ASC
    """
    fresh_conn = psycopg.connect(dsn)
    fresh_conn.autocommit = True
    try:
        with fresh_conn.cursor() as cur:
            cur.execute(sql, (symbols, tf))
            rows = cur.fetchall()
    finally:
        fresh_conn.close()

    result: dict[str, list] = {}
    for sym, ts, close in rows:
        result.setdefault(sym, []).append((ts, float(close)))

    return {
        sym: pd.DataFrame(entries, columns=["timestamp", "close"])
        for sym, entries in result.items()
    }


def _scale_window_params(params: dict[str, str], tf: str) -> dict[str, Any]:
    """Pre-scale every DAILY-bar-denominated window param to the target TF's bar count.

    RESEARCH.md Pattern 5: window params in alpha.*_regime.* APR keys are always
    daily-bar counts (see migration 222's config_schema descriptions); every signal
    module's compute() treats params it receives as ALREADY bar-scaled and stays
    TF-agnostic. This is the dispatcher's sole responsibility to apply — signal
    modules never call _tf_window() themselves.

    Non-window params (thresholds) pass through unscaled, as raw config_state
    string values — signal modules cast them (float()/int()) internally.
    """
    scaled: dict[str, Any] = dict(params)
    for key in _WINDOW_PARAM_KEYS:
        if key in params:
            scaled[key] = _tf_window(int(params[key]), tf)
    return scaled


class ReplaceResult(NamedTuple):
    """Counts of one (regime_group, tf) replace. `orphaned` are stored timestamps the run no
    longer produces, `changed` share a timestamp but differ in label or probability vector, `new`
    are produced and not stored. A write deletes exactly the orphans and upserts exactly the
    changed and new rows (`rows_deleted`, `rows_upserted`); a dry run (`wrote` False) writes
    nothing and carries the weekday split and feature_vectors joins in `extras`."""

    stored: int
    produced: int
    orphaned: int
    changed: int
    new: int
    wrote: bool
    extras: dict[str, Any]

    @property
    def rows_deleted(self) -> int:
        return self.orphaned if self.wrote else 0

    @property
    def rows_upserted(self) -> int:
        return self.changed + self.new if self.wrote else 0


class ReplaceRefused(RuntimeError):
    """A replace the guards (or the cell lock) refused; nothing was written."""


_STAGE_TABLE = "_market_regimes_stage"
_FV_STAGE_TABLE = "_market_regimes_fv_ts"

# The full outer join of a cell's stored rows (m) against the staged run (s), shared by the diff
# counts and the dry-run extras so they cannot disagree about what orphaned, changed and new mean.
_DIFF_SOURCE = f"""
    FROM (SELECT ts, regime_label, regime_prob_vector FROM market_regimes
          WHERE regime_group = %s AND tf = %s) m
    FULL OUTER JOIN {_STAGE_TABLE} s ON s.ts = m.ts
"""
_ROW_CHANGED = (
    "m.ts IS NOT NULL AND s.ts IS NOT NULL AND "
    "(m.regime_label IS DISTINCT FROM s.regime_label "
    "OR m.regime_prob_vector IS DISTINCT FROM s.regime_prob_vector)"
)
_STAGE_DIFF_SQL = f"""
    SELECT count(m.ts) AS stored,
           count(s.ts) AS produced,
           count(*) FILTER (WHERE s.ts IS NULL) AS orphaned,
           count(*) FILTER (WHERE {_ROW_CHANGED}) AS changed,
           count(*) FILTER (WHERE m.ts IS NULL) AS new
    {_DIFF_SOURCE}
"""
# Dry run only: per category (orphaned, changed, new) the rows, rows on a UTC weekend, and rows
# whose timestamp joins a feature_vectors row of the same tf (the cells ic_engine and 186-20's
# parity harness replay are stratified by these labels).
_DRY_RUN_EXTRAS_SQL = f"""
    SELECT category,
           count(*) AS n,
           count(*) FILTER (WHERE extract(isodow FROM x.ts) IN (6, 7)) AS weekend,
           count(*) FILTER (WHERE f.bar_ts IS NOT NULL) AS joins_feature_vectors
    FROM (
        SELECT COALESCE(m.ts, s.ts) AS ts,
               CASE WHEN s.ts IS NULL THEN 'orphaned'
                    WHEN m.ts IS NULL THEN 'new'
                    ELSE 'changed' END AS category
        {_DIFF_SOURCE}
        WHERE s.ts IS NULL OR m.ts IS NULL OR ({_ROW_CHANGED})
    ) x
    LEFT JOIN {_FV_STAGE_TABLE} f ON f.bar_ts = x.ts
    GROUP BY category
"""
_DELETE_ORPHANS_SQL = f"""
    DELETE FROM market_regimes m
    WHERE m.regime_group = %s AND m.tf = %s
      AND NOT EXISTS (SELECT 1 FROM {_STAGE_TABLE} s WHERE s.ts = m.ts)
"""
_UPSERT_DIFF_SQL = f"""
    INSERT INTO market_regimes (regime_group, tf, ts, regime_label, regime_prob_vector)
    SELECT regime_group, tf, ts, regime_label, regime_prob_vector FROM {_STAGE_TABLE} ORDER BY ts
    ON CONFLICT (regime_group, tf, ts) DO UPDATE
    SET regime_label = EXCLUDED.regime_label, regime_prob_vector = EXCLUDED.regime_prob_vector
    WHERE (market_regimes.regime_label, market_regimes.regime_prob_vector)
          IS DISTINCT FROM (EXCLUDED.regime_label, EXCLUDED.regime_prob_vector)
"""
_OVERRIDE_INSERT_SQL = """
    INSERT INTO market_regimes_override
        (decided_at, regime_group, tf, stored, orphaned, changed,
         accepted_orphans, accepted_changed, operator, reason)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


class ReplaceGuards(NamedTuple):
    """The limits of one replace: APR fractions of the stored rows a run may delete as orphans
    and may rewrite as changed, and the operator's reviewed override (counts, never booleans, so
    an approval cannot cover more rows than were reviewed; `operator` and `reason` are recorded
    with the decision)."""

    max_orphan_fraction: float
    max_changed_fraction: float
    accept_orphans: int = 0
    accept_changed: int = 0
    operator: str = ""
    reason: str = ""


def _lock_cell(cur: Any, group: str, tf: str) -> None:
    """Hold the cell's advisory lock until the transaction ends; refuse when another run holds it,
    so no row of the cell moves between the stage diff and the write."""
    cur.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))", (f"market_regimes|{group}|{tf}",))
    if not cur.fetchone()[0]:
        raise ReplaceRefused(
            f"market_regimes replace refused for ({group}, {tf}): another run holds the cell lock"
        )


def _stage_and_diff(
    cur: Any, group: str, tf: str, rows: list[tuple]
) -> tuple[int, int, int, int, int]:
    """COPY the run into the temp stage and return (stored, produced, orphaned, changed, new)."""
    cur.execute(
        f"CREATE TEMP TABLE {_STAGE_TABLE} (LIKE market_regimes INCLUDING DEFAULTS) "
        "ON COMMIT DROP"
    )
    with cur.copy(
        f"COPY {_STAGE_TABLE} (regime_group, tf, ts, regime_label, regime_prob_vector) FROM STDIN"
    ) as copy:
        for r in rows:
            copy.write_row((r[0], r[1], r[2], r[3], json.dumps(r[4])))
    cur.execute(f"CREATE INDEX ON {_STAGE_TABLE} (ts)")
    cur.execute(f"ANALYZE {_STAGE_TABLE}")
    cur.execute(_STAGE_DIFF_SQL, (group, tf))
    stored, produced, orphaned, changed, new = cur.fetchone()
    return stored, produced, orphaned, changed, new


def _dry_run_extras(
    cur: Any,
    group: str,
    tf: str,
    timeout_ms: int,
    fv_ts_cache: dict[str, list[Any]],
) -> dict[str, Any]:
    """Weekday split and feature_vectors joins of the diff. The distinct feature_vectors
    timestamps of a tf are read once per run (`fv_ts_cache`) and COPYed into a temp table; a
    failure here leaves the counts standing and is reported, not raised."""
    extras: dict[str, Any] = {}
    try:
        cur.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
        if tf not in fv_ts_cache:
            cur.execute("SELECT DISTINCT bar_ts FROM feature_vectors WHERE tf = %s", (tf,))
            fv_ts_cache[tf] = [row[0] for row in cur.fetchall()]
        cur.execute(f"CREATE TEMP TABLE {_FV_STAGE_TABLE} (bar_ts timestamptz) ON COMMIT DROP")
        with cur.copy(f"COPY {_FV_STAGE_TABLE} (bar_ts) FROM STDIN") as copy:
            for ts in fv_ts_cache[tf]:
                copy.write_row((ts,))
        cur.execute(f"CREATE INDEX ON {_FV_STAGE_TABLE} (bar_ts)")
        cur.execute(_DRY_RUN_EXTRAS_SQL, (group, tf))
        for category, n, weekend, joins in cur.fetchall():
            extras[category] = {"rows": n, "weekend": weekend, "joins_feature_vectors": joins}
    except Exception as error:  # the transaction is aborted; the caller rolls back
        extras["extras_error"] = str(error)
    return extras


def _guard_verdict(
    group: str, tf: str, counts: tuple[int, int, int, int, int], guards: ReplaceGuards
) -> tuple[str, bool]:
    """(refusal message, override used). A limit is exceeded when the cell's orphaned (or
    changed) rows exceed their fraction of the stored rows; an exceeded limit is covered only by
    an override whose count is at least the rows affected. The message is empty unless refused."""
    stored, produced, orphaned, changed, new = counts
    refusals: list[str] = []
    used = False
    for what, n, fraction, accepted, flag in (
        (
            "orphaned",
            orphaned,
            guards.max_orphan_fraction,
            guards.accept_orphans,
            "--accept-orphan-delete",
        ),
        (
            "changed",
            changed,
            guards.max_changed_fraction,
            guards.accept_changed,
            "--accept-changed",
        ),
    ):
        if not stored or n / stored <= fraction:
            continue
        if n <= accepted:
            used = True
        else:
            refusals.append(
                f"{n} of {stored} stored rows ({n / stored:.4f}) would be {what}, above the "
                f"{fraction} limit and the accepted count {accepted} (rerun after a --dry-run "
                f"review with {flag}=N covering {n} and --reason)"
            )
    if refusals:
        return (
            f"market_regimes replace refused for ({group}, {tf}): "
            + "; ".join(refusals)
            + f"; produced {produced}, new {new}.",
            False,
        )
    return "", used


def _replace_group_tf(
    conn: Any,
    group: str,
    tf: str,
    rows: list[tuple],
    *,
    guards: ReplaceGuards,
    dry_run: bool,
    fv_probe_timeout_ms: int = 600_000,
    fv_ts_cache: dict[str, list[Any]] | None = None,
) -> ReplaceResult:
    """Replace one (regime_group, tf) history with `rows` in a single transaction.

    market_regimes is a plain table (not a hypertable). The run takes the cell's advisory lock,
    COPYs into a temp stage and diffs it against the stored rows, applies the guards, then
    deletes only the orphans and upserts only the changed and new rows (rows already equal to the
    stage are not touched), so the write volume equals the diff and the end state is exactly the
    staged run. A guard-exceeding replace needs a reviewed override whose counts cover the diff;
    the decision is recorded in `market_regimes_override` in the same transaction. `conn` is a
    psycopg connection with autocommit off; any error rolls everything back. A dry run writes
    nothing and reports the same counts plus `extras`.
    """
    try:
        with conn.cursor() as cur:
            _lock_cell(cur, group, tf)
            counts = _stage_and_diff(cur, group, tf, rows)
            stored, produced, orphaned, changed, new = counts
            if dry_run:
                extras = _dry_run_extras(
                    cur,
                    group,
                    tf,
                    fv_probe_timeout_ms,
                    fv_ts_cache if fv_ts_cache is not None else {},
                )
                refusal, _used = _guard_verdict(group, tf, counts, guards)
                extras["would_refuse"] = bool(refusal)
                conn.rollback()
                return ReplaceResult(*counts, False, extras)
            refusal, override_used = _guard_verdict(group, tf, counts, guards)
            if refusal:
                raise ReplaceRefused(refusal)
            cur.execute(_DELETE_ORPHANS_SQL, (group, tf))
            deleted = cur.rowcount
            cur.execute(_UPSERT_DIFF_SQL)
            upserted = cur.rowcount
            if (deleted, upserted) != (orphaned, changed + new):
                raise ReplaceRefused(
                    f"market_regimes replace for ({group}, {tf}) wrote {deleted} deletes and "
                    f"{upserted} upserts, the diff said {orphaned} and {changed + new}"
                )
            if override_used:
                cur.execute(
                    _OVERRIDE_INSERT_SQL,
                    (
                        datetime.now(UTC),
                        group,
                        tf,
                        stored,
                        orphaned,
                        changed,
                        guards.accept_orphans,
                        guards.accept_changed,
                        guards.operator,
                        guards.reason,
                    ),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return ReplaceResult(*counts, True, {})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cross-Sectional Regime Model — populate market_regimes for all enabled groups"
    )
    parser.add_argument("--tf", nargs="*", default=_DEFAULT_TFS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--accept-orphan-delete",
        type=int,
        default=0,
        metavar="N",
        help="approve deleting up to N orphaned rows per (group, tf) above the APR shrink guard",
    )
    parser.add_argument(
        "--accept-changed",
        type=int,
        default=0,
        metavar="N",
        help="approve rewriting up to N changed rows per (group, tf) above the APR rewrite guard",
    )
    parser.add_argument("--reason", default="", help="required with an override; recorded")
    args = parser.parse_args()
    if (args.accept_orphan_delete or args.accept_changed) and not args.reason.strip():
        parser.error("--accept-orphan-delete and --accept-changed need a --reason")
    if args.accept_orphan_delete < 0 or args.accept_changed < 0:
        parser.error("override counts must be >= 0")

    try:
        init_otel_providers(service_name=_JOB)
    except OTelInitError as error:
        _logger.warning("cross_sectional_regime_model.otel_init_failed", error=str(error))

    t0 = time.monotonic()
    status = "success"
    exit_code = 0
    settings = Settings()
    conn = None

    try:
        dsn = settings.database_url
        conn = connect_db_from_url(settings.database_url)
        cfg = _load_config_service(conn)

        raw_groups = cfg.get_sync("alpha.regime.groups", _DEFAULT_GROUPS_JSON)
        group_configs = _parse_group_configs(raw_groups)

        # Todo 005, migration 326: causal min-hold-bars hysteresis on the raw
        # per-bar threshold-bucketed labels -- one run-level value, loaded once
        # (mirrors regime_writer.py's own min_hold_bars being a single value per
        # HMM fit rather than per-cell). [initial_estimate]=3, same provenance
        # discipline and same default value as regime_writer.py's own min_hold_bars,
        # not independently calibrated for this signal family -- see the migration's
        # own description for why reusing that precedent rather than a fresh study is
        # the right call here.
        min_hold_bars = int(cfg.get_sync("alpha.regime.cross_sectional.min_hold_bars", 3))
        # Todo 420, migrations 419 and 421: the shrink and rewrite limits of the replace. The
        # fallbacks repeat the seeded values (the repo's get_sync pattern); a seeded key wins.
        guards = ReplaceGuards(
            max_orphan_fraction=float(
                cfg.get_sync("alpha.regime.cross_sectional.max_orphan_delete_fraction", 0.01)
            ),
            max_changed_fraction=float(
                cfg.get_sync("alpha.regime.cross_sectional.max_changed_fraction", 0.05)
            ),
            accept_orphans=args.accept_orphan_delete,
            accept_changed=args.accept_changed,
            operator=getpass.getuser(),
            reason=args.reason,
        )
        fv_probe_timeout_ms = int(
            cfg.get_sync("infra.regime_cross_sectional.feature_vectors_probe_timeout_ms", 600_000)
        )
        fv_ts_cache: dict[str, list[Any]] = {}
        dry_run_report: list[dict[str, Any]] = []

        if not group_configs:
            _logger.error("cross_sectional_regime_model.no_enabled_groups")
            status = "failure"
            exit_code = 1
            return

        tags_by_symbol = _load_tags_by_symbol(conn)

        for group in group_configs:
            group_name = group["name"]
            signal_type = group["signal_type"]
            params_prefix = group["params_prefix"]

            signal_mod = REGISTRY.get(signal_type)
            if signal_mod is None:
                # Fail loud: an unknown signal_type is a config-authoring error
                # (operator-authored alpha.regime.groups JSON), never a silent skip.
                raise RuntimeError(
                    f"Unknown signal_type '{signal_type}' for group '{group_name}'. "
                    f"Available: {list(REGISTRY.keys())}"
                )

            _signal_filter = group.get("signal_tag_filter") or group["tag_filter"]
            _signal_exclude = set(group.get("signal_exclude_symbols", []))
            peer_symbols = [
                s
                for s in _resolve_group_symbols(tags_by_symbol, _signal_filter)
                if s not in _signal_exclude
            ]
            if not peer_symbols:
                _logger.warning(
                    "cross_sectional_regime_model.no_peer_symbols",
                    group=group_name,
                    tag_filter=group["tag_filter"],
                )
                continue

            _logger.info(
                "cross_sectional_regime_model.group_start",
                group=group_name,
                signal_type=signal_type,
                n_symbols=len(peer_symbols),
            )

            # Load raw APR params for this group's signal (string values — scaled/cast below)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT config_key, config_value FROM config_state WHERE config_key LIKE %s",
                    (f"{params_prefix}.%",),
                )
                raw_params = cur.fetchall()
            prefix_len = len(params_prefix) + 1
            params = {row[0][prefix_len:]: row[1] for row in raw_params}

            tiers1, tiers2 = signal_mod.build_tiers(params)
            _assert_ascending_tiers(tiers1, group_name, "tiers1")
            _assert_ascending_tiers(tiers2, group_name, "tiers2")

            total_written = 0
            for tf in args.tf:
                # Pre-scale daily-bar window params to this TF's bar count BEFORE compute()
                # (RESEARCH.md Pattern 5) — signal modules stay TF-agnostic.
                scaled_params = _scale_window_params(params, tf)

                # Reference symbols a signal module needs regardless of peer-group
                # membership (e.g. fx_dollar_carry anchors on UUP/HYG) — fetch alongside
                # peer symbols so compute() always sees them in ref_bars.
                reference_symbols = list(getattr(signal_mod, "REFERENCE_SYMBOLS", ()))
                fetch_symbols = sorted(set(peer_symbols) | set(reference_symbols))

                _logger.info(
                    "cross_sectional_regime_model.fetching_bars",
                    group=group_name,
                    tf=tf,
                    n_symbols=len(fetch_symbols),
                )

                ref_bars = _fetch_group_bars(dsn, tf, fetch_symbols)

                if not ref_bars:
                    _logger.warning(
                        "cross_sectional_regime_model.no_bars",
                        group=group_name,
                        tf=tf,
                    )
                    continue

                result = signal_mod.compute(ref_bars, scaled_params)
                if result is None:
                    _logger.warning(
                        "cross_sectional_regime_model.signal_returned_none",
                        group=group_name,
                        tf=tf,
                    )
                    continue

                sig1, sig2 = result
                combined = pd.DataFrame({"s1": sig1, "s2": sig2.reindex(sig1.index)}).dropna()

                if combined.empty:
                    _logger.warning(
                        "cross_sectional_regime_model.no_valid_rows",
                        group=group_name,
                        tf=tf,
                    )
                    continue

                rows = _assign_labels(
                    group_name=group_name,
                    tf=tf,
                    ts_arr=combined.index.tolist(),
                    sig1_arr=combined["s1"].to_numpy(),
                    sig2_arr=combined["s2"].to_numpy(),
                    tiers1=tiers1,
                    tiers2=tiers2,
                    prob_keys=signal_mod.PROB_KEYS,
                    min_hold_bars=min_hold_bars,
                )

                # Log per (group, tf) — never per row (CLAUDE.md hot-path logging rule).
                distinct_labels = {r[3] for r in rows}
                _logger.info(
                    "cross_sectional_regime_model.tf_computed",
                    group=group_name,
                    tf=tf,
                    n_rows=len(rows),
                    distinct_labels=sorted(distinct_labels),
                )

                # Reconnect before the replace (a dry run stages and diffs too): bar fetch can
                # take minutes for 5m TF, and the original conn may have gone idle long enough
                # for the server to close it.
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                conn = connect_db_from_url(settings.database_url)

                result_counts = _replace_group_tf(
                    conn,
                    group_name,
                    tf,
                    rows,
                    guards=guards,
                    dry_run=args.dry_run,
                    fv_probe_timeout_ms=fv_probe_timeout_ms,
                    fv_ts_cache=fv_ts_cache,
                )
                total_written += result_counts.rows_upserted + result_counts.rows_deleted
                # One line per (group, tf), never per row.
                _logger.info(
                    "cross_sectional_regime_model.tf_replaced",
                    group=group_name,
                    tf=tf,
                    dry_run=args.dry_run,
                    **{
                        k: v
                        for k, v in result_counts._asdict().items()
                        if k not in ("extras", "wrote")
                    },
                )
                if args.dry_run:
                    dry_run_report.append(
                        {"group": group_name, "tf": tf, **result_counts._asdict()}
                    )

            _logger.info(
                "cross_sectional_regime_model.group_complete",
                group=group_name,
                total_written=total_written,
            )

        if args.dry_run:
            _logger.info("cross_sectional_regime_model.dry_run_complete")
            print(json.dumps(dry_run_report, indent=1, default=str))

        elapsed = time.monotonic() - t0
        _logger.info(
            "cross_sectional_regime_model.complete",
            elapsed_s=round(elapsed, 2),
            status=status,
        )

    except Exception as error:
        _logger.error("cross_sectional_regime_model.run_failed", error=str(error))
        status = "failure"
        exit_code = 1
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
