#!/usr/bin/env python3
"""IC Measure: the fresh IC engine's one writer (phase 186, D-17, D-20, D-23, D-24).

Runs the pure measure jobs of src/intelligence/measure/ (proposer with its term structure across
the tf's horizons, regime_volatility disclosure, member monitoring) and writes
feature_ic_scores_v2 only through bulk_load(), one provenance batch per unit. A unit is
(job, tf): it owns every row of its scope (unstratified, regime_volatility or member_window) in
that tf, so the replace DELETE and the provenance supersede flip share one definition, the
BulkLoadSpec unit_key, and a change of family, symbols or window replaces the unit.

Blocking is a memory matter only. The feature family of a tf is fetched and measured in blocks of
alpha.ic.feature_block_columns, but the row completeness, the bootstrap draws and the
Benjamini-Hochberg family are whole-family, exactly as in ic_engine (a cell is masked over all
its features before its feature_block_columns chunks; one BH family is corrected after every
block). The BH family of the proposer is every feature of the tf at the proposer horizon
(src/intelligence/measure/proposer.py `family_fdr` cites ic_engine's wider corpus family).
Every value and every FDR decision is bit-identical for any block size; tests assert it.

Identity of a unit (the provenance batch key):
- the per-job code key: entry modules, their first-party import closure and this file
  (kernel_code_key);
- the computational APR values (identity_snapshot); operational knobs (block, fetch and symbol
  chunk sizes, the session-length guard) are read and logged but are never part of it, following
  ic_engine's computational/operational split (services/ic_engine.py 997-1070);
- an input digest: the per-symbol bar content digests, the S0 panel content digest (the bars as
  the panels loaded them, which the month-granular bar digest cannot see), a per-column digest
  of every feature of the family, the family digest (sorted names and computational params), and
  the regime labels or the member set where used.
A rerun with the same identity is skipped before any IC is computed; a changed identity replaces
the unit's rows atomically. Adding or removing a feature changes the family digest and replaces
every unit of the tf, which is correct: the BH family and the completeness mask changed. A real
run refuses while any symbol has no bar_content_digest row (phase 185 writes them), since
revision detection would be blind. The writer refuses any row whose training_window_end is at or
after alpha.validation.oos_start before it reaches bulk_load.

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
from collections.abc import Callable, Iterator, Mapping, Sequence
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
    kernel_code_modules,
    load_config_service_sync,
    prior_completed_unit,
    short_lived_conn,
)
from src.config.settings import Settings  # noqa: E402
from src.core.code_identity import code_key  # noqa: E402
from src.core.service_utils import format_iso_ts, setup_service_logging  # noqa: E402
from src.intelligence.measure.ic import (  # noqa: E402
    FamilyCompleteness,
    IcCell,
    SlotMap,
    existing_rows,
    map_slots,
    scatter_features,
)
from src.intelligence.measure.monitoring import (  # noqa: E402
    MemberIcSeries,
    member_ic_over_time,
)
from src.intelligence.measure.params import (  # noqa: E402
    COMPUTATIONAL,
    OPERATIONAL,
    MeasureParams,
    field_type,
    fields_of_kind,
)
from src.intelligence.measure.proposer import (  # noqa: E402
    family_fdr,
)
from src.intelligence.measure.regime_disclosure import (  # noqa: E402
    label_row_masks,
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
from src.intelligence.measure.term_structure import (  # noqa: E402
    TermStructure,
    merge_term_structures,
    term_structure,
)
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
# APR: every MeasureParams field maps to exactly one key (migrations 414 and 417 seed the new ones).
# Keys are split as ic_engine splits its config (services/ic_engine.py
# `_COMPUTATIONAL_CONFIG_FIELDS`, `_OPERATIONAL_CONFIG_FIELDS`, lines 997-1070): a computational
# key moves stored values and is part of a unit's identity and apr_snapshot; an operational key
# is read and logged but never enters either, so tuning a memory knob re-keys nothing.
# ---------------------------------------------------------------------------

HORIZONS_KEY = "alpha.ic_measure.horizons"
_OOS_START_KEY = "alpha.validation.oos_start"
# Operational keys that are not MeasureParams fields: the feature block width is only a memory
# chunk (every measure result is bit-identical for any width, asserted by
# tests/unit/test_ic_measure.py), the fetch chunk is a cursor round-trip size, and the session
# length only lets a cross-session intraday horizon be refused before any fetch.
_BLOCK_COLUMNS_KEY = "alpha.ic.feature_block_columns"
_FETCH_CHUNK_KEY = "infra.ic_measure.fetch_chunk_rows"
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
    "bootstrap_threads": "infra.ic_measure.bootstrap_threads",
    "bootstrap_chunk_resamples": "infra.ic_measure.bootstrap_chunk_resamples",
    "monitor_window_sessions": "alpha.ic_measure.monitor_window_sessions",
    "hac_max_lag": "alpha.ic.hac_max_lag",
    "degenerate_std": "alpha.ic_measure.degenerate_std",
    "monitor_degenerate_std": "alpha.ic_measure.monitor_degenerate_std",
}


def param_keys(tf: str) -> dict[str, str]:
    """The APR key of every MeasureParams field for this timeframe."""
    return {field: key.format(tf=tf) for field, key in MEASURE_PARAM_KEYS.items()}


def computational_keys(tf: str) -> list[str]:
    """APR keys whose value moves stored values: the identity and the unit's apr_snapshot."""
    keys = param_keys(tf)
    return [keys[f] for f in fields_of_kind(COMPUTATIONAL)]


def operational_keys(tf: str) -> list[str]:
    """APR keys the run reads for throughput and guards only; never in an identity."""
    keys = param_keys(tf)
    out = [keys[f] for f in fields_of_kind(OPERATIONAL)]
    out += [_BLOCK_COLUMNS_KEY, _FETCH_CHUNK_KEY]
    if tf != "1d":
        out.append(_BARS_PER_DAY_KEY.format(tf=tf))
    return out


def load_params(apr: Mapping[str, Any], tf: str) -> MeasureParams:
    """MeasureParams from APR values. A missing key raises KeyError naming it: no default here,
    the measure package has none either (APR mandate). Each value is cast to its field's declared
    type, so a new field needs no list kept here."""
    values: dict[str, Any] = {}
    for field, key in param_keys(tf).items():
        if key not in apr:
            raise KeyError(f"APR key {key!r} (MeasureParams.{field}) is not set")
        values[field] = field_type(field)(apr[key])
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
    """Every APR key the writer reads for one tf."""
    return [*computational_keys(tf), HORIZONS_KEY, *operational_keys(tf)]


def identity_snapshot(
    apr: Mapping[str, Any], tf: str, horizons: Sequence[int], oos_start: datetime
) -> dict[str, Any]:
    """The unit's apr_snapshot: computational values only. The horizons are this tf's own list
    (the full `alpha.ic_measure.horizons` mapping would re-key a tf when another tf's horizons
    change); operational keys are deliberately absent."""
    snapshot_keys = {k: apr[k] for k in computational_keys(tf)}
    snapshot_keys[_OOS_START_KEY] = format_iso_ts(oos_start)
    snapshot_keys[f"{HORIZONS_KEY}[{tf}]"] = list(horizons)
    return snapshot_keys


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


def column_digest(name: str, column: np.ndarray) -> str:
    """sha256 of one feature's name and its aligned float values in (bar_ts, symbol) order.
    Alignment by slot makes it independent of the fetch row order, and a per-column digest makes
    the family digest independent of how the family is blocked."""
    hasher = hashlib.sha256()
    hasher.update(name.encode() + b"\x00")
    hasher.update(np.ascontiguousarray(column, dtype=np.float64))
    return hasher.hexdigest()


def features_digest(columns: Mapping[str, str], present: np.ndarray) -> str:
    """sha256 over the sorted (name, column digest) pairs and the `present` mask."""
    hasher = hashlib.sha256()
    for name in sorted(columns):
        hasher.update(f"{name}:{columns[name]}\n".encode())
    hasher.update(np.packbits(present).tobytes())
    return hasher.hexdigest()


def family_digest(names: Sequence[str], params: MeasureParams) -> str:
    """sha256 of the sorted feature names of the family and the computational parameters: what
    defines the FDR family and everything a family-wide decision depends on. Operational fields
    (block and chunk sizes) are not part of it."""
    computational = {f: getattr(params, f) for f in fields_of_kind(COMPUTATIONAL)}
    return hashlib.sha256(
        _canonical({"names": sorted(names), "params": computational}).encode()
    ).hexdigest()


def panels_digest(grid: StackGrid, panels: Sequence[research_panel.Panel]) -> str:
    """sha256 of the S0 panels as the measure loaded them: the union grid (timestamps, traded
    mask) and, per symbol in sorted order, its open, close and volume placed on that grid.

    This is what the month-granular bar digest cannot see: the tradeable filter (volume > 0) and
    the calendar's session assembly are applied between the stored bars and these arrays. It is
    independent of how the symbols were split into panels (`symbol_chunk_size`). Dividends are
    not part of it on purpose: the targets are price-only executable open-to-open returns and
    `build_target_panels` never asks S0 for the dividend grid, so a dividend revision cannot
    change an IC."""
    hasher = hashlib.sha256()
    hasher.update(f"{grid.tf}|{grid.bars_per_session}\n".encode())
    hasher.update(np.ascontiguousarray(np.asarray(grid.timestamps).astype("datetime64[ns]")))
    hasher.update(np.packbits(grid.valid).tobytes())
    per_symbol: dict[str, str] = {}
    n = len(grid.timestamps)
    for panel, rows in zip(panels, grid.chunk_rows, strict=True):
        for j, symbol in enumerate(panel.symbols):
            column = hashlib.sha256()
            for field in ("open", "close", "volume"):
                placed = np.full(n, np.nan)
                placed[rows] = np.asarray(getattr(panel, field))[:, j]
                column.update(placed)
            per_symbol[symbol] = column.hexdigest()
    for symbol in sorted(per_symbol):
        hasher.update(f"{symbol}:{per_symbol[symbol]}\n".encode())
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
    bh_adjusted_p: np.ndarray,
    passes_fdr: np.ndarray,
    horizon_ends: Mapping[int, datetime],
) -> list[tuple]:
    """One 'unstratified' row per (feature, horizon) from the term structure; the CI and FDR
    columns come from the proposer cell (the term structure's first horizon, where it alone is
    bootstrapped) and the family's BH result, and are NULL at the other horizons."""
    rows = []
    cell = term.proposer_cell
    proposer_horizon = term.horizons[0]
    for j, horizon in enumerate(term.horizons):
        for i, name in enumerate(term.features):
            ic = _null_if_nan(term.ic[i, j])
            lower = upper = adjusted = None
            fdr = None
            if horizon == proposer_horizon:
                lower, upper = _null_if_nan(cell.ci_lower[i]), _null_if_nan(cell.ci_upper[i])
                adjusted = _null_if_nan(bh_adjusted_p[i])
                fdr = bool(passes_fdr[i]) if adjusted is not None else None
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


ALL_ROWS = "all"  # the row set of the unstratified jobs: every existing row
_LABEL_PREFIX = "label:"


def feature_blocks(names: Sequence[str], size: int) -> list[tuple[str, ...]]:
    """Consecutive blocks of `size` names. A trailing block of one name joins the previous one:
    numpy sums a single column pairwise but several columns row by row, so a one-column block
    would not reproduce the multi-column results bit for bit (ic._column_blocks, same rule).
    Blocking decides memory only; no value and no identity depends on it."""
    if size < 1:
        raise ValueError(f"block size must be >= 1, got {size}")
    blocks = [tuple(names[i : i + size]) for i in range(0, len(names), size)]
    if len(blocks) > 1 and len(blocks[-1]) == 1:
        tail = blocks.pop()
        blocks[-1] = (*blocks[-1], *tail)
    return blocks


@dataclasses.dataclass(frozen=True)
class FeatureSource:
    """The feature family as the measure jobs see it: blocks of names and a fetch of one block
    as an aligned [n, m, k] grid. The fetch is the only place a block size matters."""

    blocks: tuple[tuple[str, ...], ...]
    fetch: Callable[[Sequence[str]], np.ndarray]


@dataclasses.dataclass(frozen=True)
class FamilyInputs:
    """What one pass over the family yields: a digest per column, the family's features digest,
    and the row completeness of every row set a job measures (ALL_ROWS, and one per regime
    label for the disclosure)."""

    column_digests: Mapping[str, str]
    features_key: str
    complete: Mapping[str, np.ndarray]


def scan_family(
    source: FeatureSource, ctx: TfContext, params: MeasureParams, row_sets: Mapping[str, np.ndarray]
) -> FamilyInputs:
    """One pass over the blocks: digest every column and accumulate the family-wide row
    completeness of each row set. Blocks are freed as it goes."""
    accumulators = {key: FamilyCompleteness(params) for key in row_sets}
    digests: dict[str, str] = {}
    for block in source.blocks:
        grid = source.fetch(block)
        for i, name in enumerate(block):
            digests[name] = column_digest(name, grid[:, :, i])
        flat = grid.reshape(-1, grid.shape[2])
        for key, mask in row_sets.items():
            accumulators[key].add(flat[mask.reshape(-1)])  # observation_rows' row order
    return FamilyInputs(
        column_digests=digests,
        features_key=features_digest(digests, ctx.present),
        complete={key: acc.complete for key, acc in accumulators.items()},
    )


def _verified_block(
    source: FeatureSource, block: Sequence[str], inputs: FamilyInputs
) -> np.ndarray:
    """The block's grid, refusing a column that differs from the one the identity was built on."""
    grid = source.fetch(block)
    for i, name in enumerate(block):
        if column_digest(name, grid[:, :, i]) != inputs.column_digests[name]:
            raise ValueError(f"feature {name!r} changed between fetches; rerun")
    return grid


def _sorted_rows(rows: list[tuple]) -> list[tuple]:
    """Total order on the primary key's identifying columns (time first, as bulk_load requires),
    so the stored order is the same for any blocking."""
    return sorted(
        rows,
        key=lambda r: (
            r[_COL["training_window_end"]],
            r[_COL["feature_name"]],
            r[_COL["regime"]],
            r[_COL["lookahead_bars"]],
        ),
    )


def compute_proposer_rows(
    ctx: TfContext,
    source: FeatureSource,
    inputs: FamilyInputs,
    params: MeasureParams,
    horizons: Sequence[int],
) -> list[tuple]:
    """Term structure per block (its first horizon's cell is the proposer cell, the only one
    bootstrapped), then Benjamini-Hochberg once over the whole family: blocking bounds memory and
    never reaches a value or an FDR decision."""
    horizons = tuple(horizons)
    end = np.datetime_as_string(ctx.grid.end_exclusive, unit="s")
    complete = inputs.complete[ALL_ROWS]
    terms: list[TermStructure] = []
    for block in source.blocks:
        grid = _verified_block(source, block, inputs)
        terms.append(
            term_structure(
                grid,
                block,
                ctx.panels,
                horizons,
                end,
                params,
                present=ctx.present,
                complete=complete,
            )
        )
    term = merge_term_structures(terms)
    adjusted, passes = family_fdr(term.proposer_cell.p_value, params.fdr_alpha)
    ends = {h: _window_end(ctx.stack(h)) for h in horizons}
    return _sorted_rows(proposer_rows(ctx.tf, term, adjusted, passes, ends))


def compute_disclosure_rows(
    ctx: TfContext,
    source: FeatureSource,
    inputs: FamilyInputs,
    labels: np.ndarray,
    params: MeasureParams,
    horizons: Sequence[int],
) -> list[tuple]:
    complete = {
        key.removeprefix(_LABEL_PREFIX): mask
        for key, mask in inputs.complete.items()
        if key.startswith(_LABEL_PREFIX)
    }
    rows: list[tuple] = []
    for block in source.blocks:
        grid = _verified_block(source, block, inputs)
        for horizon in horizons:
            stack = ctx.stack(horizon)
            cells, _n_unlabelled = regime_volatility_disclosure(
                grid, block, stack, labels, params, present=ctx.present, complete=complete
            )
            rows.extend(disclosure_rows(ctx.tf, block, cells, horizon, _window_end(stack)))
    return _sorted_rows(rows)


def compute_monitoring_rows(
    ctx: TfContext,
    source: FeatureSource,
    inputs: FamilyInputs,
    params: MeasureParams,
    horizon: int,
) -> list[tuple]:
    stack = ctx.stack(horizon)
    ends = _window_ends(stack, params.monitor_window_sessions)
    rows: list[tuple] = []
    for block in source.blocks:
        grid = _verified_block(source, block, inputs)
        for i, member in enumerate(block):
            series = member_ic_over_time(grid[:, :, i], member, stack, params, present=ctx.present)
            rows.extend(member_rows(ctx.tf, series, horizon, ends))
    return _sorted_rows(rows)


# ---------------------------------------------------------------------------
# Units: skip, replace, dry run
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class UnitPlan:
    job: str
    spec: BulkLoadSpec  # carries replace_where: the unit owns the rows it names
    compute: Callable[[], list[tuple]]


@dataclasses.dataclass(frozen=True)
class UnitOutcome:
    job: str
    writer: str
    status: str  # skipped | loaded | replaced | would_skip | would_load | would_replace
    rows: int


def execute_unit(
    unit: UnitPlan,
    read_conn: Any,
    write_session: Any,
    oos_start: datetime,
    *,
    dry_run: bool,
) -> UnitOutcome:
    """Skip a completed identity before computing anything; otherwise compute, refuse rows
    reaching oos_start, and write, replacing the rows of the unit's prior identity (the spec's
    replace_where and unit_key, one definition for the DELETE and the provenance flip).
    `write_session.connection()` yields the write connection inside the compressed write session
    and is only called when a write actually happens."""
    spec = unit.spec
    if completed_provenance_batch(read_conn, spec) is not None:
        return UnitOutcome(unit.job, spec.writer, "would_skip" if dry_run else "skipped", 0)
    rows = unit.compute()
    refuse_reaching_oos(rows, oos_start)
    replacing = prior_completed_unit(read_conn, spec)
    if dry_run:
        status = "would_replace" if replacing else "would_load"
        return UnitOutcome(unit.job, spec.writer, status, len(rows))
    result: BulkLoadResult = bulk_load(write_session.connection(), spec, COLUMNS, rows)
    if result.status == "skipped":  # completed by another session between the check and the lock
        return UnitOutcome(unit.job, spec.writer, "skipped", 0)
    replaced = replacing or result.rows_replaced > 0
    return UnitOutcome(
        unit.job, spec.writer, "replaced" if replaced else "loaded", result.row_count
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

# The code key of a job (D-23) covers its entry modules plus everything first-party they import
# (kernel_code_key walks the closure, so the research store, dividends and market calendar the
# target path reaches are in it without being listed) and this file, whose row building and unit
# identity are part of what a value is. This file's own imports are infrastructure (bulk_load,
# settings, metrics) and are not followed. Scoped per job: a proposer edit never re-keys
# monitoring.
_COMMON_ENTRIES = (
    "src.intelligence.measure.params",
    "src.intelligence.measure.targets",
    "src.intelligence.measure.ic",
)
_OWN_MODULES = ("services.ic_measure",)
_JOB_ENTRIES: dict[str, tuple[str, ...]] = {
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


def job_code_modules(job: str) -> tuple[str, ...]:
    """The modules the job's code key hashes."""
    return kernel_code_modules((*_COMMON_ENTRIES, *_JOB_ENTRIES[job]), own=_OWN_MODULES)


def job_code_key(job: str) -> str:
    """The per-job code key: the job's entry modules, their first-party import closure and this
    file (D-23)."""
    return code_key(job_code_modules(job))


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
            absent = check_bar_digests(
                before, after, allow_absent=self.args.allow_absent_digests or self.args.dry_run
            )
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
                _logger.info(  # once per unit, never per row
                    "ic_measure.unit_done",
                    tf=tf,
                    writer=outcome.writer,
                    status=outcome.status,
                    rows=outcome.rows,
                    seconds=round(time.monotonic() - t0, 1),
                )
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

    def _block_fetcher(
        self,
        read_conn: Any,
        tf: str,
        ctx: TfContext,
        keys: LongForm,
        start: datetime,
        oos_start: datetime,
        chunk_rows: int,
        slot_horizon: int,
    ) -> Callable[[Sequence[str]], np.ndarray]:
        """Fetch one block of columns and align it to the grid; the fetched keys must be the ones
        the slot map was built on."""

        def fetch(block: Sequence[str]) -> np.ndarray:
            fetched = fetch_long_form(
                read_conn,
                self.args.feature_table,
                tf,
                ctx.grid.symbols,
                start,
                oos_start,
                list(block),
                chunk_rows,
            )
            if not (
                np.array_equal(fetched.bar_ts, keys.bar_ts)
                and np.array_equal(fetched.symbols, keys.symbols)
            ):
                raise ValueError(f"{tf} feature rows changed between fetches; rerun")
            grid, _unmatched = scatter_features(ctx.stack(slot_horizon), ctx.slots, fetched.values)
            return grid

        return fetch

    def _labels(
        self,
        read_conn: Any,
        tf: str,
        ctx: TfContext,
        start: datetime,
        oos_start: datetime,
        chunk_rows: int,
        slot_horizon: int,
    ) -> np.ndarray:
        """The regime_volatility label of every grid slot ('' where none)."""
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
        label_slots = map_slots(ctx.stack(slot_horizon), label_rows.bar_ts, label_rows.symbols)
        width = max((len(v) for v in label_rows.values[:, 0]), default=1) or 1
        labels = np.full((len(ctx.grid.timestamps), len(ctx.grid.symbols)), "", dtype=f"<U{width}")
        labels[label_slots.rows, label_slots.cols] = label_rows.values[label_slots.ok, 0]
        return labels

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
    ) -> Iterator[UnitPlan]:
        """One unit per active job (job, tf). Blocking is a memory matter of the fetch and the IC
        computation only: one pass over the blocks builds the identity, and a unit that has to
        compute makes its own pass (skipped units compute nothing)."""
        snapshot_keys = identity_snapshot(apr, tf, horizons, oos_start)
        fetch = self._block_fetcher(
            read_conn, tf, ctx, keys, start, oos_start, chunk_rows, horizons[0]
        )
        common = {"bars": dict(bar_digests), "panels": panels_digest(ctx.grid, ctx.panels)}
        block_jobs = [j for j in jobs if j != JOB_MONITORING]
        if block_jobs:
            source = FeatureSource(
                tuple(feature_blocks(names, max(int(apr[_BLOCK_COLUMNS_KEY]), 1))), fetch
            )
            existing = existing_rows(ctx.grid.valid_grid(), ctx.present)
            row_sets: dict[str, np.ndarray] = {}
            labels = labels_key = None
            if JOB_PROPOSER in block_jobs:
                row_sets[ALL_ROWS] = existing
            if JOB_REGIME_VOLATILITY in block_jobs:
                labels = self._labels(read_conn, tf, ctx, start, oos_start, chunk_rows, horizons[0])
                labels_key = labels_digest(labels)
                masks, _n_unlabelled = label_row_masks(existing, labels)
                row_sets.update({f"{_LABEL_PREFIX}{label}": m for label, m in masks.items()})
            inputs = scan_family(source, ctx, params, row_sets)
            family = {"family": family_digest(names, params), "features": inputs.features_key}
            for job in block_jobs:
                extra = {"labels": labels_key} if job == JOB_REGIME_VOLATILITY else {}
                yield self._unit(
                    job,
                    tf,
                    ctx,
                    start,
                    oos_start,
                    snapshot_keys,
                    {"job": job, **common, **family, **extra},
                    self._compute(job, ctx, source, inputs, labels, params, horizons),
                )
        if JOB_MONITORING in jobs:
            members = tuple(dict.fromkeys(self.args.members))
            unknown = sorted(set(members) - set(names))
            if unknown:
                raise ValueError(f"monitoring members {unknown} are not numeric feature columns")
            source = FeatureSource((members,), fetch)
            inputs = scan_family(source, ctx, params, {})
            identity = {
                "job": JOB_MONITORING,
                **common,
                "family": family_digest(members, params),
                "features": inputs.features_key,
            }
            yield self._unit(
                JOB_MONITORING,
                tf,
                ctx,
                start,
                oos_start,
                snapshot_keys,
                identity,
                self._compute(JOB_MONITORING, ctx, source, inputs, None, params, horizons),
            )

    @staticmethod
    def _unit(
        job: str,
        tf: str,
        ctx: TfContext,
        start: datetime,
        oos_start: datetime,
        snapshot_keys: Mapping[str, Any],
        identity: Mapping[str, Any],
        compute: Callable[[], list[tuple]],
    ) -> UnitPlan:
        """The unit owns every row of its scope in this tf (replace_where names no feature and
        no symbol), so a change to the family, the symbols or the window replaces it."""
        spec = BulkLoadSpec(
            writer=f"{_WRITER}.{job}",
            target_table=TARGET_TABLE,
            time_column="training_window_end",
            tf=tf,
            range_start=start,
            range_end=oos_start,
            symbols=tuple(ctx.grid.symbols),
            code_key=job_code_key(job),
            apr_snapshot=snapshot_keys,
            input_digest=hashlib.sha256(_canonical(identity).encode()).hexdigest(),
            replace_where={"tf": tf, "symbol": POOLED_SYMBOL, "regime_scope": _JOB_SCOPE[job]},
        )
        return UnitPlan(job=job, spec=spec, compute=compute)

    @staticmethod
    def _compute(
        job: str,
        ctx: TfContext,
        source: FeatureSource,
        inputs: FamilyInputs,
        labels: np.ndarray | None,
        params: MeasureParams,
        horizons: tuple[int, ...],
    ) -> Callable[[], list[tuple]]:
        if job == JOB_PROPOSER:
            return lambda: compute_proposer_rows(ctx, source, inputs, params, horizons)
        if job == JOB_REGIME_VOLATILITY:
            assert labels is not None
            return lambda: compute_disclosure_rows(ctx, source, inputs, labels, params, horizons)
        return lambda: compute_monitoring_rows(ctx, source, inputs, params, horizons[0])


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
