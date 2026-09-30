#!/usr/bin/env python3
"""IC Measure: the fresh IC engine's one writer (phase 186, D-17, D-20, D-23, D-24).

Runs the pure measure jobs of src/intelligence/measure/ (proposer with its term structure across
the tf's horizons, regime_volatility disclosure, member monitoring) and writes
feature_ic_scores_v2 only through bulk_load(), one provenance batch per unit. A unit is
(job, tf, feature block).

Identity of a unit (the provenance batch key): the per-job code key (kernel_code_key over the
modules that compute it), every APR value the job read, and an input digest of the per-symbol
bar content digests, the aligned feature block (and labels or members where used). A rerun with
the same identity is skipped before any IC is computed; a changed identity replaces the unit's
rows atomically (bulk_load replace_where). The writer refuses any row whose
training_window_end is at or after alpha.validation.oos_start before it reaches bulk_load.

A NaN IC is written as NULL, never as NaN or zero. A traded bar with no feature_vectors row for
a symbol is not an observation: every job receives the `present` slot mask.

Compute stays in the pure measure package; this module fetches, aligns, builds rows and writes.
The legacy feature_ic_scores table is never touched.

Usage:
    python services/ic_measure.py --tf 1d --dry-run
    python services/ic_measure.py --tf 15m --jobs proposer,regime_volatility
    python services/ic_measure.py --tf 1d --jobs monitoring --members momentum_z_fast,hurst
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import math
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import structlog
from psycopg import sql

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import (  # noqa: E402
    BulkLoadResult,
    BulkLoadSpec,
    bar_content_digests,
    bulk_load,
    completed_provenance_batch,
    compressed_hypertable_write_session,
    kernel_code_key,
    load_config_service_sync,
    short_lived_conn,
)
from src.config.settings import Settings  # noqa: E402
from src.core.service_utils import format_iso_ts, setup_service_logging  # noqa: E402
from src.intelligence.measure.ic import (  # noqa: E402
    IcCell,
    SlotMap,
    map_slots,
    scatter_features,
)
from src.intelligence.measure.monitoring import (  # noqa: E402
    MemberIcSeries,
    member_ic_over_time,
)
from src.intelligence.measure.params import MeasureParams  # noqa: E402
from src.intelligence.measure.proposer import ProposerResult, propose  # noqa: E402
from src.intelligence.measure.regime_disclosure import (  # noqa: E402
    regime_volatility_disclosure,
)
from src.intelligence.measure.targets import (  # noqa: E402
    StackGrid,
    TargetStack,
    build_target_panels,
    check_horizon,
    stack_at_horizon,
    stack_grid,
)
from src.intelligence.measure.term_structure import TermStructure, term_structure  # noqa: E402
from src.intelligence.research import panel as research_panel  # noqa: E402
from src.intelligence.research import snapshot  # noqa: E402
from src.intelligence.schemas import FeatureVector  # noqa: E402
from src.observability.metrics import (  # noqa: E402
    JOB_COMPLETED_TOTAL,
    flush_and_shutdown_metrics,
)
from src.observability.otel import OTelInitError, init_otel_providers  # noqa: E402

_logger = structlog.get_logger(__name__)

# Service identity and schema identifiers: APR-exempt (CLAUDE.md exempt list).
_JOB = "ic-measure"
TARGET_TABLE = "feature_ic_scores_v2"
_WRITER = "ic_measure"
POOLED_SYMBOL = "POOLED"
ALL_REGIMES = "_all"
VECTOR_DOMAIN = "quant"
_LABEL_COLUMN = "regime_volatility"
_LABEL_SOURCE = "feature_vectors.regime_volatility"

SCOPE_UNSTRATIFIED = "unstratified"
SCOPE_REGIME_VOLATILITY = "regime_volatility"
SCOPE_MEMBER_WINDOW = "member_window"

JOB_PROPOSER = "proposer"
JOB_REGIME_VOLATILITY = "regime_volatility"
JOB_MONITORING = "monitoring"
_ALL_JOBS = (JOB_PROPOSER, JOB_REGIME_VOLATILITY, JOB_MONITORING)
_DEFAULT_JOBS = (JOB_PROPOSER, JOB_REGIME_VOLATILITY)

COLUMNS: tuple[str, ...] = (
    "feature_name",
    "vector_domain",
    "symbol",
    "tf",
    "regime",
    "lookahead_bars",
    "training_window_end",
    "is_pooled",
    "n_independent",
    "reliable",
    "ic_value",
    "ic_sign",
    "p_value",
    "ic_ci_lower",
    "ic_ci_upper",
    "passes_ci_gate",
    "bh_adjusted_p",
    "passes_fdr",
    "ic_sharpe",
    "ic_sharpe_n_windows",
    "ic_sharpe_hac",
    "regime_label_source",
    "regime_scope",
)
_COL = {name: i for i, name in enumerate(COLUMNS)}

# ---------------------------------------------------------------------------
# APR: every MeasureParams field maps to exactly one key (migration 414 seeds the new ones)
# ---------------------------------------------------------------------------

HORIZONS_KEY = "alpha.ic_measure.horizons"
_BLOCK_COLUMNS_KEY = "alpha.ic.feature_block_columns"
_FETCH_CHUNK_KEY = "infra.ic_measure.fetch_chunk_rows"
_OOS_START_KEY = "alpha.validation.oos_start"
_BARS_PER_DAY_KEY = "alpha.ic.broadcast_max_bars_per_day.{tf}"

# MeasureParams field -> APR key ("{tf}" is replaced by the timeframe).
MEASURE_PARAM_KEYS: dict[str, str] = {
    "min_stride": "alpha.ic.subsample_min_stride",
    "bootstrap_block_size": "alpha.ic.bootstrap_block_size.{tf}",
    "bootstrap_resamples": "alpha.ic.bootstrap_resamples",
    "rng_seed": "alpha.ic.bootstrap_seed",
    "fdr_alpha": "alpha.ic.fdr_alpha",
    "min_obs": "alpha.ic.min_reliable_n",
    "symbol_chunk_size": "infra.ic_measure.symbol_chunk_size",
    "monitor_window_sessions": "alpha.ic_measure.monitor_window_sessions",
    "hac_max_lag": "alpha.ic.hac_max_lag",
    "degenerate_std": "alpha.ic_measure.degenerate_std",
    "monitor_degenerate_std": "alpha.ic_measure.monitor_degenerate_std",
}
_INT_FIELDS = frozenset(
    {
        "min_stride",
        "bootstrap_block_size",
        "bootstrap_resamples",
        "rng_seed",
        "min_obs",
        "symbol_chunk_size",
        "monitor_window_sessions",
        "hac_max_lag",
    }
)


def param_keys(tf: str) -> dict[str, str]:
    """The APR key of every MeasureParams field for this timeframe."""
    return {field: key.format(tf=tf) for field, key in MEASURE_PARAM_KEYS.items()}


def load_params(apr: Mapping[str, Any], tf: str) -> MeasureParams:
    """MeasureParams from APR values. A missing key raises KeyError naming it: no default here,
    the measure package has none either (APR mandate)."""
    values: dict[str, Any] = {}
    for field, key in param_keys(tf).items():
        if key not in apr:
            raise KeyError(f"APR key {key!r} (MeasureParams.{field}) is not set")
        values[field] = int(apr[key]) if field in _INT_FIELDS else float(apr[key])
    return MeasureParams(**values)


def horizons_for(apr: Mapping[str, Any], tf: str) -> tuple[int, ...]:
    """The tf's configured horizons, each checked against the session length (so a
    cross-session intraday horizon aborts the tf before any fetch, D-18)."""
    configured = apr[HORIZONS_KEY]
    if tf not in configured:
        raise KeyError(f"{HORIZONS_KEY} has no entry for tf {tf!r}")
    horizons = tuple(int(h) for h in configured[tf])
    if not horizons:
        raise ValueError(f"{HORIZONS_KEY}[{tf!r}] is empty")
    bars_per_session = 1 if tf == "1d" else int(apr[_BARS_PER_DAY_KEY.format(tf=tf)])
    for horizon in horizons:
        check_horizon(tf, bars_per_session, horizon)
    return horizons


def apr_keys_read(tf: str) -> list[str]:
    """Every APR key the writer reads for one tf (also the unit's apr_snapshot keys)."""
    keys = [*param_keys(tf).values(), HORIZONS_KEY, _BLOCK_COLUMNS_KEY, _FETCH_CHUNK_KEY]
    if tf != "1d":
        keys.append(_BARS_PER_DAY_KEY.format(tf=tf))
    return keys


# ---------------------------------------------------------------------------
# Feature reads
# ---------------------------------------------------------------------------

_NUMERIC_TYPES = frozenset({"real", "double precision", "integer", "bigint", "smallint", "numeric"})
_COLUMN_TYPES_SQL = (
    "SELECT column_name, data_type FROM information_schema.columns "
    "WHERE table_schema = current_schema() AND table_name = %s"
)
_TABLE_EXISTS_SQL = (
    "SELECT 1 FROM information_schema.tables "
    "WHERE table_schema = current_schema() AND table_name = %s"
)


def validate_feature_table(read_conn: Any, table: str) -> None:
    """A schema identifier must name a real table (it is composed into SQL as an Identifier)."""
    with read_conn.cursor() as cur:
        cur.execute(_TABLE_EXISTS_SQL, (table,))
        if cur.fetchone() is None:
            raise ValueError(f"feature table {table!r} does not exist")


def feature_names(read_conn: Any, feature_table: str) -> tuple[list[str], list[str]]:
    """FeatureVector field names that are numeric columns of the table (types from
    information_schema, never inferred from data), in FeatureVector order, and the names the
    table lacks or holds as a non-numeric type."""
    with read_conn.cursor() as cur:
        cur.execute(_COLUMN_TYPES_SQL, (feature_table,))
        types = dict(cur.fetchall())
    wanted = [f.name for f in dataclasses.fields(FeatureVector)]
    names = [n for n in wanted if types.get(n) in _NUMERIC_TYPES]
    missing = [n for n in wanted if types.get(n) not in _NUMERIC_TYPES]
    if missing:
        _logger.warning(
            "ic_measure.feature_names_missing", table=feature_table, missing=len(missing)
        )
    return names, missing


def feature_block_sql(table: str, names: Sequence[str]) -> sql.Composed:
    """symbol, bar_ts and exactly the named columns (never a star select), in (bar_ts, symbol) order."""
    columns = [sql.Identifier("symbol"), sql.Identifier("bar_ts"), *map(sql.Identifier, names)]
    return sql.SQL(
        "SELECT {cols} FROM {table} WHERE tf = %s AND symbol = ANY(%s) "
        "AND bar_ts >= %s AND bar_ts < %s ORDER BY bar_ts, symbol"
    ).format(cols=sql.SQL(", ").join(columns), table=sql.Identifier(table))


@dataclasses.dataclass(frozen=True)
class LongForm:
    bar_ts: np.ndarray  # [N] naive UTC datetime64[ns] (the session date's 00:00 on 1d)
    symbols: np.ndarray  # [N] str
    values: np.ndarray  # [N, k] float64 (NaN for NULL), or [N, 1] str for labels


def fetch_long_form(
    read_conn: Any,
    table: str,
    tf: str,
    symbols: Sequence[str],
    start: datetime,
    end_exclusive: datetime,
    columns: Sequence[str],
    chunk_rows: int,
    *,
    text: bool = False,
) -> LongForm:
    """Stream (symbol, bar_ts, columns...) rows with a server-side cursor into arrays."""
    stmt = feature_block_sql(table, columns)
    params = (tf, list(symbols), start, end_exclusive)
    ts_parts: list[np.ndarray] = []
    sym_parts: list[np.ndarray] = []
    val_parts: list[np.ndarray] = []
    with read_conn.transaction():
        with read_conn.cursor(name="ic_measure_fetch") as cur:
            cur.execute(stmt, params)
            while True:
                rows = cur.fetchmany(chunk_rows)
                if not rows:
                    break
                cols = list(zip(*rows, strict=True))
                stamps = pd.DatetimeIndex(cols[1]).tz_convert("UTC").tz_localize(None)
                if tf == "1d":
                    stamps = stamps.normalize()
                ts_parts.append(stamps.values.astype("datetime64[ns]"))
                sym_parts.append(np.asarray(cols[0], dtype=str))
                if text:
                    labels = ["" if v is None else str(v) for v in cols[2]]
                    val_parts.append(np.asarray(labels, dtype=str)[:, None])
                elif len(cols) > 2:
                    val_parts.append(np.array(cols[2:], dtype=float).T)
                else:
                    val_parts.append(np.zeros((len(rows), 0)))
    if not ts_parts:
        return LongForm(
            np.zeros(0, dtype="datetime64[ns]"),
            np.zeros(0, dtype=str),
            np.zeros((0, len(columns))),
        )
    return LongForm(np.concatenate(ts_parts), np.concatenate(sym_parts), np.concatenate(val_parts))


# ---------------------------------------------------------------------------
# Timeframe context: panels, union grid, slot map, `present` mask
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class TfContext:
    tf: str
    panels: list[research_panel.Panel]
    grid: StackGrid
    slots: SlotMap
    present: np.ndarray  # [n, m] bool: slots that received a feature_vectors row
    _stacks: dict[int, TargetStack] = dataclasses.field(default_factory=dict)

    def stack(self, horizon: int) -> TargetStack:
        if horizon not in self._stacks:
            self._stacks[horizon] = stack_at_horizon(self.grid, self.panels, horizon)
        return self._stacks[horizon]


def make_tf_context(
    panels: list[research_panel.Panel],
    end_exclusive: str | np.datetime64,
    bar_ts: np.ndarray,
    symbols: np.ndarray,
    slot_horizon: int = 1,
) -> TfContext:
    """Union grid of the panels and the slot map of the feature rows' (bar_ts, symbol) keys.
    `slot_horizon` only supplies a stack to the slot mapper (which reads timestamps and symbols,
    never targets); it never enters a value."""
    grid = stack_grid(panels, end_exclusive)
    context = TfContext(
        tf=panels[0].tf,
        panels=panels,
        grid=grid,
        slots=SlotMap(
            np.zeros(0, dtype=bool), np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
        ),
        present=np.zeros((0, 0), dtype=bool),
    )
    slots = map_slots(context.stack(slot_horizon), bar_ts, symbols)
    context.slots = slots
    context.present = slots.present(len(grid.timestamps), len(grid.symbols))
    return context


def block_digest(names: Sequence[str], grid: np.ndarray, present: np.ndarray) -> str:
    """sha256 of the block's names, its aligned float values in (bar_ts, symbol, feature) order
    and the `present` mask. Alignment by slot makes it independent of the fetch row order."""
    hasher = hashlib.sha256()
    hasher.update("\x1f".join(names).encode() + b"\x00")
    hasher.update(np.ascontiguousarray(grid, dtype=np.float64))
    hasher.update(np.packbits(present).tobytes())
    return hasher.hexdigest()


def labels_digest(labels: np.ndarray) -> str:
    hasher = hashlib.sha256()
    hasher.update(labels.dtype.str.encode() + str(labels.shape).encode())
    hasher.update(np.ascontiguousarray(labels))
    return hasher.hexdigest()


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def _null_if_nan(value: float) -> float | None:
    value = float(value)
    return None if math.isnan(value) else value


def _sign(value: float | None) -> int | None:
    if value is None:
        return None
    return 1 if value > 0 else -1 if value < 0 else 0


def _row(**fields: Any) -> tuple:
    base: dict[str, Any] = {
        "vector_domain": VECTOR_DOMAIN,
        "symbol": POOLED_SYMBOL,
        "is_pooled": True,
        "regime": ALL_REGIMES,
        "regime_label_source": "none",
    }
    base.update(fields)
    unknown = set(base) - set(COLUMNS)
    if unknown:
        raise ValueError(f"unknown row fields {sorted(unknown)}")
    return tuple(base.get(name) for name in COLUMNS)


def _ci_gate(lower: float | None, upper: float | None) -> bool | None:
    if lower is None or upper is None:
        return None
    return lower > 0 or upper < 0


def _window_end(stack: TargetStack) -> datetime:
    """The latest target exit bar of the stack as a UTC datetime; a stack with no finite
    target cannot be measured and raises (a silent empty result would hide a data problem)."""
    end = stack.max_target_end()
    if end is None:
        raise ValueError(f"{stack.tf} horizon {stack.horizon} has no finite target")
    return _to_utc(end)


def _to_utc(value: np.datetime64) -> datetime:
    converted: datetime = pd.Timestamp(value).to_pydatetime().replace(tzinfo=UTC)
    return converted


def proposer_rows(
    tf: str,
    term: TermStructure,
    result: ProposerResult,
    proposer_horizon: int,
    horizon_ends: Mapping[int, datetime],
) -> list[tuple]:
    """One 'unstratified' row per (feature, horizon) from the term structure; the CI and FDR
    columns come from the proposer's cell at the proposer horizon and are NULL elsewhere."""
    rows = []
    cell_ci = {
        name: (
            result.cell.ci_lower[i],
            result.cell.ci_upper[i],
            result.bh_adjusted_p[i],
            result.passes_fdr[i],
        )
        for i, name in enumerate(result.cell.features)
    }
    for j, horizon in enumerate(term.horizons):
        for i, name in enumerate(term.features):
            ic = _null_if_nan(term.ic[i, j])
            lower = upper = adjusted = None
            fdr = None
            if horizon == proposer_horizon:
                lo, hi, adj, passes = cell_ci[name]
                lower, upper, adjusted = _null_if_nan(lo), _null_if_nan(hi), _null_if_nan(adj)
                fdr = bool(passes) if adjusted is not None else None
            rows.append(
                _row(
                    feature_name=name,
                    tf=tf,
                    lookahead_bars=int(horizon),
                    training_window_end=horizon_ends[horizon],
                    n_independent=int(term.n_obs[i, j]),
                    reliable=ic is not None,
                    ic_value=ic,
                    ic_sign=_sign(ic),
                    p_value=_null_if_nan(term.p_value[i, j]),
                    ic_ci_lower=lower,
                    ic_ci_upper=upper,
                    passes_ci_gate=_ci_gate(lower, upper),
                    bh_adjusted_p=adjusted,
                    passes_fdr=fdr,
                    regime_scope=SCOPE_UNSTRATIFIED,
                )
            )
    return sorted(rows, key=lambda r: r[_COL["training_window_end"]])


def disclosure_rows(
    tf: str,
    names: Sequence[str],
    cells: Mapping[str, IcCell],
    horizon: int,
    window_end: datetime,
) -> list[tuple]:
    rows = []
    for label, cell in cells.items():
        for i, name in enumerate(names):
            ic = _null_if_nan(cell.ic[i])
            lower, upper = _null_if_nan(cell.ci_lower[i]), _null_if_nan(cell.ci_upper[i])
            rows.append(
                _row(
                    feature_name=name,
                    tf=tf,
                    regime=label,
                    lookahead_bars=int(horizon),
                    training_window_end=window_end,
                    n_independent=int(cell.n_independent[i]),
                    reliable=ic is not None and bool(cell.reliable[i]),
                    ic_value=ic,
                    ic_sign=_sign(ic),
                    p_value=_null_if_nan(cell.p_value[i]),
                    ic_ci_lower=lower,
                    ic_ci_upper=upper,
                    passes_ci_gate=_ci_gate(lower, upper),
                    regime_label_source=_LABEL_SOURCE,
                    regime_scope=SCOPE_REGIME_VOLATILITY,
                )
            )
    return rows


def _window_ends(stack: TargetStack, per_window: int) -> list[datetime]:
    """Latest target exit bar of each monitoring window (the same whole-session windows
    member_ic_over_time uses); a window without a finite target falls back to its last bar."""
    n_sessions = int(stack.session[-1]) + 1 if len(stack.session) else 0
    firsts = np.arange(0, n_sessions, per_window)
    lasts = np.minimum(firsts + per_window, n_sessions)
    lows, highs = (np.searchsorted(stack.session, edge) for edge in (firsts, lasts))
    finite_rows = np.isfinite(stack.targets).any(axis=1)
    ends = []
    for lo, hi in zip(lows.tolist(), highs.tolist(), strict=True):
        found = np.flatnonzero(finite_rows[lo:hi])
        row = lo + int(found[-1]) + 1 + stack.horizon if found.size else hi - 1
        ends.append(_to_utc(stack.timestamps[row]))
    return ends


def member_rows(
    tf: str, series: MemberIcSeries, horizon: int, window_ends: Sequence[datetime]
) -> list[tuple]:
    if len(window_ends) != len(series.ic):
        raise ValueError(f"{len(window_ends)} window ends for {len(series.ic)} windows")
    n_windows = int(np.isfinite(series.ic).sum())
    sharpe, sharpe_hac = _null_if_nan(series.ic_sharpe), _null_if_nan(series.ic_sharpe_hac)
    rows = []
    for w, end in enumerate(window_ends):
        ic = _null_if_nan(series.ic[w])
        rows.append(
            _row(
                feature_name=series.member,
                tf=tf,
                lookahead_bars=int(horizon),
                training_window_end=end,
                n_independent=int(series.n_obs[w]),
                reliable=ic is not None,
                ic_value=ic,
                ic_sign=_sign(ic),
                ic_sharpe=sharpe,
                ic_sharpe_n_windows=n_windows,
                ic_sharpe_hac=sharpe_hac,
                regime_scope=SCOPE_MEMBER_WINDOW,
            )
        )
    return rows


def refuse_reaching_oos(rows: Sequence[tuple], oos_start: datetime) -> None:
    """D-19: no fresh row may carry training_window_end at or after alpha.validation.oos_start."""
    bad = [r for r in rows if r[_COL["training_window_end"]] >= oos_start]
    if bad:
        raise ValueError(
            f"{len(bad)} row(s) reach oos_start {format_iso_ts(oos_start)} "
            f"(first training_window_end {format_iso_ts(bad[0][_COL['training_window_end']])}); "
            "refusing the unit before any write"
        )


# ---------------------------------------------------------------------------
# Jobs: fetch-free orchestration of the pure measure functions
# ---------------------------------------------------------------------------


def compute_proposer_rows(
    ctx: TfContext,
    names: Sequence[str],
    features: np.ndarray,
    params: MeasureParams,
    horizons: Sequence[int],
) -> list[tuple]:
    names = tuple(names)
    horizons = tuple(horizons)
    term = term_structure(
        features,
        names,
        ctx.panels,
        horizons,
        np.datetime_as_string(ctx.grid.end_exclusive, unit="s"),
        params,
        present=ctx.present,
    )
    proposer_horizon = horizons[0]
    result = propose(features, names, ctx.stack(proposer_horizon), params, present=ctx.present)
    ends = {h: _window_end(ctx.stack(h)) for h in horizons}
    return proposer_rows(ctx.tf, term, result, proposer_horizon, ends)


def compute_disclosure_rows(
    ctx: TfContext,
    names: Sequence[str],
    features: np.ndarray,
    labels: np.ndarray,
    params: MeasureParams,
    horizons: Sequence[int],
) -> list[tuple]:
    names = tuple(names)
    rows: list[tuple] = []
    for horizon in horizons:
        stack = ctx.stack(horizon)
        cells, _n_unlabelled = regime_volatility_disclosure(
            features, names, stack, labels, params, present=ctx.present
        )
        rows.extend(disclosure_rows(ctx.tf, names, cells, horizon, _window_end(stack)))
    return sorted(rows, key=lambda r: r[_COL["training_window_end"]])


def compute_monitoring_rows(
    ctx: TfContext,
    member_grids: Mapping[str, np.ndarray],
    params: MeasureParams,
    horizon: int,
) -> list[tuple]:
    stack = ctx.stack(horizon)
    ends = _window_ends(stack, params.monitor_window_sessions)
    rows: list[tuple] = []
    for member, grid in member_grids.items():
        series = member_ic_over_time(grid, member, stack, params, present=ctx.present)
        rows.extend(member_rows(ctx.tf, series, horizon, ends))
    return sorted(rows, key=lambda r: r[_COL["training_window_end"]])


# ---------------------------------------------------------------------------
# Units: skip, replace, dry run
# ---------------------------------------------------------------------------

_PRIOR_COMPLETED_SQL = (
    "SELECT 1 FROM provenance_batch WHERE writer = %s AND target_table = %s AND tf = %s "
    "AND range_start = %s AND range_end = %s AND symbols_hash = %s "
    "AND status = 'completed' AND batch_key <> %s LIMIT 1"
)


@dataclasses.dataclass(frozen=True)
class UnitPlan:
    job: str
    spec: BulkLoadSpec
    replace_where: Mapping[str, Any]
    compute: Callable[[], list[tuple]]


@dataclasses.dataclass(frozen=True)
class UnitOutcome:
    job: str
    writer: str
    status: str  # skipped | loaded | replaced | would_skip | would_load | would_replace
    rows: int


def prior_completed_batch(read_conn: Any, spec: BulkLoadSpec) -> bool:
    """True when a completed batch of the same unit (writer, target, tf, range, symbols) exists
    under a different key: the new identity replaces it."""
    with read_conn.cursor() as cur:
        cur.execute(
            _PRIOR_COMPLETED_SQL,
            (
                spec.writer,
                spec.target_table,
                spec.tf,
                spec.range_start,
                spec.range_end,
                spec.symbols_hash,
                spec.batch_key,
            ),
        )
        return cur.fetchone() is not None


def execute_unit(
    unit: UnitPlan,
    read_conn: Any,
    write_session: Any,
    oos_start: datetime,
    *,
    dry_run: bool,
) -> UnitOutcome:
    """Skip a completed identity before computing anything; otherwise compute, refuse rows
    reaching oos_start, and write (append, or replace a prior identity of the same unit).
    `write_session.connection()` yields the write connection inside the compressed write session
    and is only called when a write actually happens."""
    spec = unit.spec
    if completed_provenance_batch(read_conn, spec) is not None:
        return UnitOutcome(unit.job, spec.writer, "would_skip" if dry_run else "skipped", 0)
    rows = unit.compute()
    refuse_reaching_oos(rows, oos_start)
    replacing = prior_completed_batch(read_conn, spec)
    if dry_run:
        status = "would_replace" if replacing else "would_load"
        return UnitOutcome(unit.job, spec.writer, status, len(rows))
    result: BulkLoadResult = bulk_load(
        write_session.connection(),
        spec,
        COLUMNS,
        rows,
        replace_where=dict(unit.replace_where) if replacing else None,
    )
    if result.status == "skipped":  # completed by another session between the check and the lock
        return UnitOutcome(unit.job, spec.writer, "skipped", 0)
    return UnitOutcome(
        unit.job, spec.writer, "replaced" if replacing else "loaded", result.row_count
    )


def check_bar_digests(
    before: Mapping[str, str], after: Mapping[str, str], *, allow_absent: bool
) -> list[str]:
    """The bar digests bracketing the panel build must agree (the panels saw the digested
    bars). Returns the symbols with no digest at all ("absent"): revision detection is blind for
    them, so a real run refuses unless `allow_absent`."""
    changed = sorted(s for s in before if before[s] != after.get(s))
    if changed:
        raise ValueError(f"bar content changed during the panel build for {changed[:10]}")
    absent = sorted(s for s, d in before.items() if d == "absent")
    if absent and not allow_absent:
        raise ValueError(
            f"{len(absent)} symbol(s) have no bar_content_digest rows (first {absent[:5]}); "
            "revision detection would be blind for them. Run the digest writer (phase 185) or "
            "pass --allow-absent-digests to accept that explicitly"
        )
    return absent


def active_jobs(jobs: Sequence[str], members: Sequence[str]) -> list[str]:
    """Jobs that have work: monitoring needs members (frozen books arrive in phase 188)."""
    unknown = [j for j in jobs if j not in _ALL_JOBS]
    if unknown:
        raise ValueError(f"unknown job(s) {unknown}; choose from {list(_ALL_JOBS)}")
    return [j for j in jobs if j != JOB_MONITORING or members]


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

_COMMON_MODULES = (
    "services.ic_measure",
    "src.intelligence.measure.params",
    "src.intelligence.measure.targets",
    "src.intelligence.measure.ic",
    "src.intelligence.research.panel",
    "src.intelligence.research.snapshot",
    "src.intelligence.statistics.ic_math",
)
_JOB_MODULES: dict[str, tuple[str, ...]] = {
    JOB_PROPOSER: (
        "src.intelligence.measure.proposer",
        "src.intelligence.measure.term_structure",
    ),
    JOB_REGIME_VOLATILITY: ("src.intelligence.measure.regime_disclosure",),
    JOB_MONITORING: ("src.intelligence.measure.monitoring",),
}
_JOB_SCOPE = {
    JOB_PROPOSER: SCOPE_UNSTRATIFIED,
    JOB_REGIME_VOLATILITY: SCOPE_REGIME_VOLATILITY,
    JOB_MONITORING: SCOPE_MEMBER_WINDOW,
}
_EARLIEST_BAR_SQL = (
    "SELECT min(timestamp) FROM market_data_ohlcv_tradeable "
    "WHERE timeframe = %s AND symbol = ANY(%s)"
)


def job_code_key(job: str) -> str:
    """The per-job code key: only the modules that compute that job (D-23)."""
    return kernel_code_key((*_COMMON_MODULES, *_JOB_MODULES[job]))


class _WriteSession:
    """The write connection inside the compressed write session, opened on first use so a
    rerun that skips every unit never decompresses anything. close() recompresses and VACUUMs."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._stack: ExitStack | None = None
        self._conn: Any = None

    def connection(self) -> Any:
        if self._conn is None:
            self._stack = ExitStack()
            self._conn = self._stack.enter_context(short_lived_conn(self._dsn))
            self._stack.enter_context(compressed_hypertable_write_session(self._conn, TARGET_TABLE))
        return self._conn

    def close(self) -> None:
        if self._stack is not None:
            self._stack.close()
            self._stack = None
            self._conn = None


def _parse_oos(value: Any) -> datetime:
    if value is None:
        raise ValueError(f"APR key {_OOS_START_KEY} is not set")
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


class IcMeasure:
    def __init__(self, args: argparse.Namespace, dsn: str) -> None:
        self.args = args
        self.dsn = dsn
        self.outcomes: list[UnitOutcome] = []
        self.failures: list[str] = []

    # -- setup ---------------------------------------------------------------

    def run(self) -> None:
        with short_lived_conn(self.dsn) as read_conn:
            read_conn.autocommit = True
            cfg = load_config_service_sync(read_conn)
            missing = object()
            tfs = self.args.tf or list(cfg.get_sync(HORIZONS_KEY, {}).keys())
            keys = {_OOS_START_KEY, *(k for tf in tfs for k in apr_keys_read(tf))}
            apr = {k: v for k in keys if (v := cfg.get_sync(k, missing)) is not missing}
            oos_start = _parse_oos(apr.get(_OOS_START_KEY))
            validate_feature_table(read_conn, self.args.feature_table)
            jobs = active_jobs(self.args.jobs, self.args.members)
            if not jobs:
                _logger.warning("ic_measure.no_active_jobs", jobs=self.args.jobs)
            write = _WriteSession(self.dsn)
            try:
                for tf in tfs:
                    self._run_tf(read_conn, write, apr, tf, jobs, oos_start)
            finally:
                write.close()

    def _symbols(self, tf: str) -> list[str]:
        if self.args.symbols:
            return sorted(self.args.symbols)
        dimension = "compute_eligible_1d" if tf == "1d" else "compute_eligible"
        return asyncio.run(snapshot.universe_symbols(self.dsn, dimension))

    def _start(self, read_conn: Any, tf: str, symbols: Sequence[str]) -> datetime:
        if self.args.start:
            return datetime.fromisoformat(self.args.start).astimezone(UTC)
        with read_conn.cursor() as cur:
            cur.execute(_EARLIEST_BAR_SQL, (tf, list(symbols)))
            (earliest,) = cur.fetchone()
        if earliest is None:
            raise ValueError(f"no tradeable {tf} bars for the requested symbols")
        first_bar: datetime = earliest.astimezone(UTC)
        return first_bar

    # -- one timeframe ---------------------------------------------------------

    def _run_tf(
        self,
        read_conn: Any,
        write: _WriteSession,
        apr: Mapping[str, Any],
        tf: str,
        jobs: list[str],
        oos_start: datetime,
    ) -> None:
        t0 = time.monotonic()
        horizons = horizons_for(apr, tf)  # aborts a cross-session horizon before any fetch
        params = load_params(apr, tf)
        symbols = self._symbols(tf)
        start = self._start(read_conn, tf, symbols)
        chunk_rows = int(apr[_FETCH_CHUNK_KEY])
        before = bar_content_digests(read_conn, tf, symbols, start, oos_start)
        counts: dict[str, int] = {}
        with tempfile.TemporaryDirectory(prefix="ic_measure_") as tmp:
            paths = asyncio.run(
                build_target_panels(
                    self.dsn,
                    Path(tmp),
                    symbols,
                    tf,
                    start.isoformat(),
                    oos_start.isoformat(),
                    oos_start.isoformat(),
                    params,
                )
            )
            after = bar_content_digests(read_conn, tf, symbols, start, oos_start)
            absent = check_bar_digests(before, after, allow_absent=self.args.allow_absent_digests)
            if absent:
                _logger.warning("ic_measure.bar_digests_absent", tf=tf, symbols=len(absent))
            panels = [research_panel.load(p) for p in paths]
            used = tuple(s for p in panels for s in p.symbols)
            keys = fetch_long_form(
                read_conn, self.args.feature_table, tf, used, start, oos_start, [], chunk_rows
            )
            ctx = make_tf_context(
                panels, oos_start.replace(tzinfo=None).isoformat(), keys.bar_ts, keys.symbols
            )
            names, _missing = feature_names(read_conn, self.args.feature_table)
            bar_digests = {s: before[s] for s in used}
            for unit in self._units(
                read_conn,
                apr,
                tf,
                jobs,
                ctx,
                names,
                keys,
                params,
                horizons,
                start,
                oos_start,
                chunk_rows,
                bar_digests,
            ):
                try:
                    outcome = execute_unit(
                        unit, read_conn, write, oos_start, dry_run=self.args.dry_run
                    )
                except Exception as error:
                    self.failures.append(f"{unit.spec.writer}: {error}")
                    _logger.error(
                        "ic_measure.unit_failed", tf=tf, writer=unit.spec.writer, error=str(error)
                    )
                    counts["failed"] = counts.get("failed", 0) + 1
                    continue
                self.outcomes.append(outcome)
                counts[outcome.status] = counts.get(outcome.status, 0) + 1
                counts["rows"] = counts.get("rows", 0) + outcome.rows
        _logger.info(
            "ic_measure.tf_complete",
            tf=tf,
            dry_run=self.args.dry_run,
            seconds=round(time.monotonic() - t0, 1),
            symbols=len(used),
            **counts,
        )

    def _units(
        self,
        read_conn: Any,
        apr: Mapping[str, Any],
        tf: str,
        jobs: list[str],
        ctx: TfContext,
        names: list[str],
        keys: LongForm,
        params: MeasureParams,
        horizons: tuple[int, ...],
        start: datetime,
        oos_start: datetime,
        chunk_rows: int,
        bar_digests: Mapping[str, str],
    ):
        """Yield units one at a time (a block's grid is freed before the next is fetched)."""
        snapshot_keys = {k: apr[k] for k in apr_keys_read(tf) if k in apr}
        snapshot_keys["alpha.validation.oos_start"] = format_iso_ts(oos_start)
        snapshot_keys[f"{HORIZONS_KEY}[{tf}]"] = list(horizons)
        n, m = len(ctx.grid.timestamps), len(ctx.grid.symbols)
        labels: np.ndarray | None = None
        labels_key = ""
        blocks: list[tuple[str, list[str], list[str]]] = []  # (job group, names, jobs)
        size = int(apr[_BLOCK_COLUMNS_KEY])
        block_jobs = [j for j in jobs if j != JOB_MONITORING]
        if block_jobs:
            for first in range(0, len(names), size):
                blocks.append(("features", names[first : first + size], block_jobs))
        if JOB_MONITORING in jobs:
            blocks.append(("members", list(self.args.members), [JOB_MONITORING]))
        for idx, (_kind, block, block_job_list) in enumerate(blocks):
            fetched = fetch_long_form(
                read_conn,
                self.args.feature_table,
                tf,
                ctx.grid.symbols,
                start,
                oos_start,
                block,
                chunk_rows,
            )
            if not (
                np.array_equal(fetched.bar_ts, keys.bar_ts)
                and np.array_equal(fetched.symbols, keys.symbols)
            ):
                raise ValueError(f"{tf} feature rows changed between fetches; rerun")
            grid, _unmatched = scatter_features(ctx.stack(horizons[0]), ctx.slots, fetched.values)
            features_key = block_digest(block, grid, ctx.present)
            for job in block_job_list:
                extra: dict[str, Any] = {}
                if job == JOB_REGIME_VOLATILITY:
                    if labels is None:
                        label_rows = fetch_long_form(
                            read_conn,
                            self.args.feature_table,
                            tf,
                            ctx.grid.symbols,
                            start,
                            oos_start,
                            [_LABEL_COLUMN],
                            chunk_rows,
                            text=True,
                        )
                        label_slots = map_slots(
                            ctx.stack(horizons[0]), label_rows.bar_ts, label_rows.symbols
                        )
                        width = max((len(v) for v in label_rows.values[:, 0]), default=1) or 1
                        labels = np.full((n, m), "", dtype=f"<U{width}")
                        labels[label_slots.rows, label_slots.cols] = label_rows.values[
                            label_slots.ok, 0
                        ]
                        labels_key = labels_digest(labels)
                    extra["labels"] = labels_key
                if job == JOB_MONITORING:
                    extra["members"] = list(block)
                identity = _canonical(
                    {
                        "job": job,
                        "bars": dict(bar_digests),
                        "features": features_key,
                        "names": list(block),
                        **extra,
                    }
                )
                spec = BulkLoadSpec(
                    writer=f"{_WRITER}.{job}.b{idx:03d}",
                    target_table=TARGET_TABLE,
                    time_column="training_window_end",
                    tf=tf,
                    range_start=start,
                    range_end=oos_start,
                    symbols=tuple(ctx.grid.symbols),
                    code_key=job_code_key(job),
                    apr_snapshot=snapshot_keys,
                    input_digest=hashlib.sha256(identity.encode()).hexdigest(),
                )
                yield UnitPlan(
                    job=job,
                    spec=spec,
                    replace_where={
                        "tf": tf,
                        "symbol": POOLED_SYMBOL,
                        "regime_scope": _JOB_SCOPE[job],
                        "feature_name": list(block),
                    },
                    compute=self._compute(job, ctx, block, grid, labels, params, horizons),
                )

    @staticmethod
    def _compute(
        job: str,
        ctx: TfContext,
        block: list[str],
        grid: np.ndarray,
        labels: np.ndarray | None,
        params: MeasureParams,
        horizons: tuple[int, ...],
    ) -> Callable[[], list[tuple]]:
        if job == JOB_PROPOSER:
            return lambda: compute_proposer_rows(ctx, block, grid, params, horizons)
        if job == JOB_REGIME_VOLATILITY:
            assert labels is not None
            return lambda: compute_disclosure_rows(ctx, block, grid, labels, params, horizons)
        members = {name: grid[:, :, i] for i, name in enumerate(block)}
        return lambda: compute_monitoring_rows(ctx, members, params, horizons[0])


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fresh IC jobs -> feature_ic_scores_v2")
    parser.add_argument(
        "--tf", action="append", help="timeframe (repeatable); default: every tf in APR"
    )
    parser.add_argument(
        "--jobs",
        type=lambda v: [j for j in v.split(",") if j],
        default=list(_DEFAULT_JOBS),
        help="comma list of proposer, regime_volatility, monitoring",
    )
    parser.add_argument(
        "--members",
        type=lambda v: [m for m in v.split(",") if m],
        default=[],
        help="monitoring only: comma list of feature names",
    )
    parser.add_argument("--symbols", nargs="+", help="override the universe (tests and smoke)")
    parser.add_argument("--start", help="ISO start of the window (default: earliest tradeable bar)")
    parser.add_argument("--feature-table", default="feature_vectors")
    parser.add_argument("--dry-run", action="store_true", help="compute and report, write nothing")
    parser.add_argument(
        "--allow-absent-digests",
        action="store_true",
        help="accept symbols with no bar_content_digest rows (revision detection blind for them)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    setup_service_logging("logs/ic_measure.log")
    args = _parse_args(argv)
    try:
        init_otel_providers(service_name=_JOB)
    except OTelInitError as error:
        _logger.warning("ic_measure.otel_init_failed", error=str(error))
    status = "success"
    try:
        runner = IcMeasure(args, Settings().database_url)
        runner.run()
        for outcome in runner.outcomes:
            print(f"{outcome.status:14s} {outcome.writer:40s} rows={outcome.rows}")
        if runner.failures:
            status = "failure"
            for failure in runner.failures:
                print(f"FAILED {failure}", file=sys.stderr)
    except Exception as error:
        status = "failure"
        _logger.error("ic_measure.fatal_error", error=str(error))
        raise
    finally:
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()
        if status == "failure":
            sys.exit(1)


if __name__ == "__main__":
    main()
