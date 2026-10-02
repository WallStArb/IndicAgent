#!/usr/bin/env python3
"""IC Measure: the fresh IC engine's one writer (phase 186, D-17, D-20, D-23, D-24).

Runs the pure measure jobs of src/intelligence/measure/ (proposer with its term structure across
the tf's horizons, regime_volatility disclosure, member monitoring) and writes
feature_ic_scores_v2 only through bulk_load(), one provenance batch per unit. A unit is
(job, tf): it owns every row of its scope (unstratified, regime_volatility or member_window) in
that tf, so the replace DELETE and the provenance supersede flip share one definition, the
BulkLoadSpec unit_key, and a change of family, symbols or window replaces the unit. A real run
also records .planning/corpus_manifests/ic_measure.json (CorpusManifest: inputs plus the table's
per-tf coverage after the run) so the corpus verification gate can check step completeness; a
dry run writes no rows and records no manifest.

Blocking is a memory matter only. The feature family of a tf is fetched and measured in blocks of
alpha.ic.feature_block_columns, but the row completeness, the bootstrap draws and the
Benjamini-Hochberg family are whole-family, as in ic_engine (a cell is masked over all its
features before its feature_block_columns chunks; one block-start matrix per cell is shared by
every block; one BH family is corrected after every block). The bootstrap generator is not
ic_engine's: each cell seeds its own, so a CI matches ic_engine's in distribution but not bit
for bit (see measure.ic.block_bootstrap_ci); IC and p-value are comparable. The BH family of the proposer is every feature of the tf at the proposer horizon
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
run refuses while any symbol the panels use has no bar_content_digest row (phase 185 writes them), since
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
import math
import sys
import tempfile
import time
from collections import Counter
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
    BAR_DIGEST_ABSENT_SYMBOL,
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
    table_column_types,
)
from src.config.settings import Settings  # noqa: E402
from src.core.canonical_json import canonical_json  # noqa: E402
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
from src.observability.corpus_manifest import CorpusManifest  # noqa: E402
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
_LABEL_SOURCE = f"feature_vectors.{_LABEL_COLUMN}"

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


def feature_names(read_conn: Any, feature_table: str) -> list[str]:
    """FeatureVector field names that are numeric columns of the table (types from
    information_schema, never inferred from data; a missing table raises), in FeatureVector
    order. The names the table lacks or holds as a non-numeric type are logged as a count."""
    types = table_column_types(read_conn, feature_table)
    wanted = [f.name for f in dataclasses.fields(FeatureVector)]
    names = [n for n in wanted if types.get(n) in _NUMERIC_TYPES]
    if len(names) < len(wanted):
        _logger.warning(
            "ic_measure.feature_names_missing",
            table=feature_table,
            missing=len(wanted) - len(names),
        )
    return names


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


@dataclasses.dataclass(frozen=True)
class TfContext:
    tf: str
    panels: list[research_panel.Panel]
    grid: StackGrid
    slots: SlotMap
    present: np.ndarray  # [n, m] bool: slots that received a feature_vectors row
    # Targets per horizon, built on first use; a cache, so it is not part of a context's value.
    _stacks: dict[int, TargetStack] = dataclasses.field(
        default_factory=dict, repr=False, compare=False
    )

    def stack(self, horizon: int) -> TargetStack:
        if horizon not in self._stacks:
            self._stacks[horizon] = stack_at_horizon(self.grid, self.panels, horizon)
        return self._stacks[horizon]


def make_tf_context(
    panels: list[research_panel.Panel],
    end_exclusive: str | np.datetime64,
    bar_ts: np.ndarray,
    symbols: np.ndarray,
) -> TfContext:
    """Union grid of the panels and the slot map of the feature rows' (bar_ts, symbol) keys."""
    grid = stack_grid(panels, end_exclusive)
    slots = map_slots(grid, bar_ts, symbols)
    return TfContext(
        tf=panels[0].tf,
        panels=panels,
        grid=grid,
        slots=slots,
        present=slots.present(len(grid.timestamps), len(grid.symbols)),
    )


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
        canonical_json({"names": sorted(names), "params": computational}).encode()
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


def _cell_row(
    *,
    feature: str,
    tf: str,
    horizon: int,
    window_end: datetime,
    n_independent: int,
    ic: float | None,
    reliable: bool,
    **extra: Any,
) -> tuple:
    """One feature_ic_scores_v2 row in COLUMNS order: the fields every job writes, the pooled
    defaults, and the job's own columns in `extra` (an unknown column name raises)."""
    fields: dict[str, Any] = {
        "vector_domain": VECTOR_DOMAIN,
        "symbol": POOLED_SYMBOL,
        "is_pooled": True,
        "regime": ALL_REGIMES,
        "regime_label_source": "none",
        "feature_name": feature,
        "tf": tf,
        "lookahead_bars": int(horizon),
        "training_window_end": window_end,
        "n_independent": int(n_independent),
        "reliable": reliable,
        "ic_value": ic,
        "ic_sign": _sign(ic),
    }
    fields.update(extra)
    unknown = set(fields) - set(COLUMNS)
    if unknown:
        raise ValueError(f"unknown row fields {sorted(unknown)}")
    return tuple(fields.get(name) for name in COLUMNS)


def _ci_gate(lower: float | None, upper: float | None) -> bool | None:
    if lower is None or upper is None:
        return None
    return lower > 0 or upper < 0


def _to_utc(value: np.datetime64) -> datetime:
    converted: datetime = pd.Timestamp(value).to_pydatetime().replace(tzinfo=UTC)
    return converted


def _window_end(stack: TargetStack) -> datetime:
    """The latest target exit bar of the stack as a UTC datetime; a stack with no finite
    target cannot be measured and raises (a silent empty result would hide a data problem)."""
    end = stack.max_target_end()
    if end is None:
        raise ValueError(f"{stack.tf} horizon {stack.horizon} has no finite target")
    return _to_utc(end)


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
                _cell_row(
                    feature=name,
                    tf=tf,
                    horizon=horizon,
                    window_end=horizon_ends[horizon],
                    n_independent=term.n_obs[i, j],
                    ic=ic,
                    reliable=ic is not None,
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
                _cell_row(
                    feature=name,
                    tf=tf,
                    horizon=horizon,
                    window_end=window_end,
                    n_independent=cell.n_independent[i],
                    ic=ic,
                    reliable=ic is not None and bool(cell.reliable[i]),
                    regime=label,
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
            _cell_row(
                feature=series.member,
                tf=tf,
                horizon=horizon,
                window_end=end,
                n_independent=series.n_obs[w],
                ic=ic,
                reliable=ic is not None,
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


@dataclasses.dataclass(frozen=True)
class FamilyScan:
    """One scan of the family for the proposer and regime_volatility units: the block source, what
    the scan yielded, and the regime labels (and their digest) when that job is active."""

    source: FeatureSource
    inputs: FamilyInputs
    labels: np.ndarray | None
    labels_key: str | None


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
    before: Mapping[str, str],
    after: Mapping[str, str],
    used: Sequence[str],
    *,
    allow_absent: bool,
) -> list[str]:
    """The bar digests of the symbols the panels used must agree across the panel build (the
    panels saw the digested bars). Returns the used symbols with no digest at all
    (`BAR_DIGEST_ABSENT_SYMBOL`): revision detection is blind for them, so a real run refuses
    unless `allow_absent`. Only `used` symbols count: a requested symbol with no tradeable bars
    has no panel column, cannot affect an IC, and must not block the run (absent stays absent,
    never zero or unchanged, for every symbol that does)."""
    changed = sorted(s for s in used if before[s] != after.get(s))
    if changed:
        raise ValueError(f"bar content changed during the panel build for {changed[:10]}")
    absent = sorted(s for s in used if before[s] == BAR_DIGEST_ABSENT_SYMBOL)
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


def _aware_utc(value: Any, what: str) -> datetime:
    """An ISO 8601 timestamp with an offset (Z included), as UTC. A naive one is refused, never
    read as UTC or as the host's zone: these timestamps bound the out-of-sample guard and the
    window, the same rule as `src.core.service_utils.parse_training_window_end`. `what` names the
    key or flag in the error."""
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError(f"{what} is not an ISO 8601 timestamp: {value!r}") from error
    if parsed.tzinfo is None:
        raise ValueError(
            f"{what} must be a timezone-aware ISO 8601 timestamp (Z or an offset), got {value!r}; "
            "a naive value is not reinterpreted as UTC"
        )
    return parsed.astimezone(UTC)


def _parse_oos(value: Any) -> datetime:
    """alpha.validation.oos_start as a UTC datetime; missing, garbled or naive raises."""
    if value is None:
        raise ValueError(f"APR key {_OOS_START_KEY} is not set")
    return _aware_utc(value, f"APR key {_OOS_START_KEY}")


@dataclasses.dataclass(frozen=True)
class TfRun:
    """What every unit of one timeframe shares, fixed before a feature is fetched."""

    tf: str
    apr: Mapping[str, Any]
    params: MeasureParams
    horizons: tuple[int, ...]
    start: datetime
    oos_start: datetime
    chunk_rows: int  # rows per server-side cursor fetch (operational)
    bar_digests: Mapping[str, str]  # per measured symbol, taken before the panel build
    snapshot: Mapping[str, Any]  # the units' computational apr_snapshot


@dataclasses.dataclass(frozen=True)
class UnitCompute:
    """What a unit computes, as plain named fields instead of a closure: calling it runs the
    job's pure measure function over the family and returns the unit's rows. The fields are
    exactly its inputs (the context's panels and stacks are the large ones, the fetch reads the
    feature table), so nothing else is kept alive with the plan. The single-process writer is
    measured to need nothing more (todo 469: the full 1d universe takes minutes); a worker
    process would need a fetch that opens its own connection, because `source.fetch` is bound
    to the parent's."""

    job: str
    run: TfRun
    ctx: TfContext
    source: FeatureSource
    inputs: FamilyInputs
    labels: np.ndarray | None

    def __call__(self) -> list[tuple]:
        params, horizons = self.run.params, self.run.horizons
        if self.job == JOB_PROPOSER:
            return compute_proposer_rows(self.ctx, self.source, self.inputs, params, horizons)
        if self.job == JOB_REGIME_VOLATILITY:
            assert self.labels is not None
            return compute_disclosure_rows(
                self.ctx, self.source, self.inputs, self.labels, params, horizons
            )
        return compute_monitoring_rows(self.ctx, self.source, self.inputs, params, horizons[0])


class IcMeasure:
    def __init__(self, args: argparse.Namespace, dsn: str) -> None:
        self.args = args
        self.dsn = dsn
        self.outcomes: list[UnitOutcome] = []
        self.failures: list[str] = []
        # Run identity for the step manifest, recorded by run() as soon as APR resolves
        # it; main() reads these only after run() returned, so they are the real values
        # there and the defaults never reach a manifest.
        self.tfs: list[str] = []
        self.jobs: list[str] = []
        self.oos_start_iso: str = ""
        # The one place the absent-digest tolerance is decided: a dry run writes nothing, so it
        # tolerates symbols with no bar_content_digest row; a real run refuses them unless the
        # flag says otherwise (186-28's acceptance forbids the flag on the live run).
        self.allow_absent_digests = bool(args.dry_run or args.allow_absent_digests)

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
            table_column_types(read_conn, self.args.feature_table)  # a missing table raises here
            jobs = active_jobs(self.args.jobs, self.args.members)
            self.tfs, self.jobs, self.oos_start_iso = (
                list(tfs),
                list(jobs),
                format_iso_ts(oos_start),
            )
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
            return _aware_utc(self.args.start, "--start")
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
        counts: Counter[str] = Counter()
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
            panels = [research_panel.load(p) for p in paths]
            used = tuple(s for p in panels for s in p.symbols)
            absent = check_bar_digests(before, after, used, allow_absent=self.allow_absent_digests)
            if absent:
                _logger.warning("ic_measure.bar_digests_absent", tf=tf, symbols=len(absent))
            keys = fetch_long_form(
                read_conn, self.args.feature_table, tf, used, start, oos_start, [], chunk_rows
            )
            ctx = make_tf_context(
                panels, oos_start.replace(tzinfo=None).isoformat(), keys.bar_ts, keys.symbols
            )
            run = TfRun(
                tf=tf,
                apr=apr,
                params=params,
                horizons=horizons,
                start=start,
                oos_start=oos_start,
                chunk_rows=chunk_rows,
                bar_digests={s: before[s] for s in used},
                snapshot=identity_snapshot(apr, tf, horizons, oos_start),
            )
            names = feature_names(read_conn, self.args.feature_table)
            for unit in self._units(read_conn, run, ctx, names, keys, jobs):
                self._run_unit(unit, read_conn, write, run, counts, t0)
        _logger.info(
            "ic_measure.tf_complete",
            tf=tf,
            dry_run=self.args.dry_run,
            seconds=round(time.monotonic() - t0, 1),
            symbols=len(used),
            **counts,
        )

    def _run_unit(
        self,
        unit: UnitPlan,
        read_conn: Any,
        write: _WriteSession,
        run: TfRun,
        counts: Counter[str],
        t0: float,
    ) -> None:
        """Execute one unit; a failure is recorded and the tf carries on with the next."""
        try:
            outcome = execute_unit(unit, read_conn, write, run.oos_start, dry_run=self.args.dry_run)
        except Exception as error:
            self.failures.append(f"{unit.spec.writer}: {error}")
            _logger.error(
                "ic_measure.unit_failed", tf=run.tf, writer=unit.spec.writer, error=str(error)
            )
            counts["failed"] += 1
            return
        self.outcomes.append(outcome)
        _logger.info(  # once per unit, never per row
            "ic_measure.unit_done",
            tf=run.tf,
            writer=outcome.writer,
            status=outcome.status,
            rows=outcome.rows,
            seconds=round(time.monotonic() - t0, 1),
        )
        counts[outcome.status] += 1
        counts["rows"] += outcome.rows

    def _block_fetcher(
        self, read_conn: Any, run: TfRun, ctx: TfContext, keys: LongForm
    ) -> Callable[[Sequence[str]], np.ndarray]:
        """Fetch one block of columns and align it to the grid; the fetched keys must be the ones
        the slot map was built on."""

        def fetch(block: Sequence[str]) -> np.ndarray:
            fetched = fetch_long_form(
                read_conn,
                self.args.feature_table,
                run.tf,
                ctx.grid.symbols,
                run.start,
                run.oos_start,
                list(block),
                run.chunk_rows,
            )
            if not (
                np.array_equal(fetched.bar_ts, keys.bar_ts)
                and np.array_equal(fetched.symbols, keys.symbols)
            ):
                raise ValueError(f"{run.tf} feature rows changed between fetches; rerun")
            grid, _unmatched = scatter_features(ctx.grid, ctx.slots, fetched.values)
            return grid

        return fetch

    def _labels(self, read_conn: Any, run: TfRun, ctx: TfContext) -> np.ndarray:
        """The regime_volatility label of every grid slot ('' where none)."""
        label_rows = fetch_long_form(
            read_conn,
            self.args.feature_table,
            run.tf,
            ctx.grid.symbols,
            run.start,
            run.oos_start,
            [_LABEL_COLUMN],
            run.chunk_rows,
            text=True,
        )
        label_slots = map_slots(ctx.grid, label_rows.bar_ts, label_rows.symbols)
        width = max((len(v) for v in label_rows.values[:, 0]), default=1) or 1
        labels = np.full((len(ctx.grid.timestamps), len(ctx.grid.symbols)), "", dtype=f"<U{width}")
        labels[label_slots.rows, label_slots.cols] = label_rows.values[label_slots.ok, 0]
        return labels

    def _units(
        self,
        read_conn: Any,
        run: TfRun,
        ctx: TfContext,
        names: list[str],
        keys: LongForm,
        jobs: list[str],
    ) -> Iterator[UnitPlan]:
        """One unit per active job (job, tf). Blocking is a memory matter of the fetch and the IC
        computation only: one pass over the blocks builds the identity (and every column's
        digest), and a unit that has to compute makes its own verifying pass (skipped units
        compute nothing, so a run that skips everything streams the family once)."""
        fetch = self._block_fetcher(read_conn, run, ctx, keys)
        common = {"bars": dict(run.bar_digests), "panels": panels_digest(ctx.grid, ctx.panels)}
        family_jobs = [j for j in jobs if j != JOB_MONITORING]
        scanned: Mapping[str, str] | None = None
        if family_jobs:
            scan = self._scan_family_jobs(read_conn, run, ctx, names, fetch, family_jobs)
            scanned = scan.inputs.column_digests
            yield from self._family_units(run, ctx, names, common, family_jobs, scan)
        if JOB_MONITORING in jobs:
            yield self._monitoring_unit(run, ctx, names, fetch, common, scanned)

    def _scan_family_jobs(
        self,
        read_conn: Any,
        run: TfRun,
        ctx: TfContext,
        names: list[str],
        fetch: Callable[[Sequence[str]], np.ndarray],
        jobs: list[str],
    ) -> FamilyScan:
        """One scan of the whole family: the proposer's and regime_volatility's shared identity
        inputs (column digests) and row completeness."""
        source = FeatureSource(
            tuple(feature_blocks(names, max(int(run.apr[_BLOCK_COLUMNS_KEY]), 1))), fetch
        )
        existing = existing_rows(ctx.grid.valid_grid(), ctx.present)
        row_sets: dict[str, np.ndarray] = {}
        labels = labels_key = None
        if JOB_PROPOSER in jobs:
            row_sets[ALL_ROWS] = existing
        if JOB_REGIME_VOLATILITY in jobs:
            labels = self._labels(read_conn, run, ctx)
            labels_key = labels_digest(labels)
            masks, _n_unlabelled = label_row_masks(existing, labels)
            row_sets.update({f"{_LABEL_PREFIX}{label}": m for label, m in masks.items()})
        inputs = scan_family(source, ctx, run.params, row_sets)
        return FamilyScan(source, inputs, labels, labels_key)

    @staticmethod
    def _family_units(
        run: TfRun,
        ctx: TfContext,
        names: list[str],
        common: Mapping[str, Any],
        jobs: list[str],
        scan: FamilyScan,
    ) -> Iterator[UnitPlan]:
        """The proposer and regime_volatility units over one family scan."""
        family = {
            "family": family_digest(names, run.params),
            "features": scan.inputs.features_key,
        }
        for job in jobs:
            extra = {"labels": scan.labels_key} if job == JOB_REGIME_VOLATILITY else {}
            identity = _identity(job, common, family, extra)
            yield UnitPlan(
                job=job,
                spec=_spec(job, run, ctx, identity),
                compute=UnitCompute(job, run, ctx, scan.source, scan.inputs, scan.labels),
            )

    def _monitoring_unit(
        self,
        run: TfRun,
        ctx: TfContext,
        names: list[str],
        fetch: Callable[[Sequence[str]], np.ndarray],
        common: Mapping[str, Any],
        scanned: Mapping[str, str] | None,
    ) -> UnitPlan:
        """The monitoring unit over the `--members` columns, each a whole block of its own. A
        column's digest does not depend on how the family is blocked, so when the family was
        scanned in this run the members' digests are taken from that scan instead of streaming
        the columns again."""
        members = tuple(dict.fromkeys(self.args.members))
        unknown = sorted(set(members) - set(names))
        if unknown:
            raise ValueError(f"monitoring members {unknown} are not numeric feature columns")
        source = FeatureSource((members,), fetch)
        if scanned is not None:
            digests = {m: scanned[m] for m in members}
            inputs = FamilyInputs(digests, features_digest(digests, ctx.present), {})
        else:
            inputs = scan_family(source, ctx, run.params, {})
        family = {"family": family_digest(members, run.params), "features": inputs.features_key}
        identity = _identity(JOB_MONITORING, common, family, {})
        return UnitPlan(
            job=JOB_MONITORING,
            spec=_spec(JOB_MONITORING, run, ctx, identity),
            compute=UnitCompute(JOB_MONITORING, run, ctx, source, inputs, None),
        )


def _identity(
    job: str, common: Mapping[str, Any], family: Mapping[str, Any], extra: Mapping[str, Any]
) -> dict[str, Any]:
    """The inputs a unit's batch key is taken over: the job, the bars and panels every unit of
    the tf shares, the family's digests, and the job's own (the regime labels)."""
    return {"job": job, **common, **family, **extra}


def _spec(job: str, run: TfRun, ctx: TfContext, identity: Mapping[str, Any]) -> BulkLoadSpec:
    """The unit owns every row of its scope in this tf (replace_where names no feature and no
    symbol), so a change to the family, the symbols or the window replaces it."""
    return BulkLoadSpec(
        writer=f"{_WRITER}.{job}",
        target_table=TARGET_TABLE,
        time_column="training_window_end",
        tf=run.tf,
        range_start=run.start,
        range_end=run.oos_start,
        symbols=tuple(ctx.grid.symbols),
        code_key=job_code_key(job),
        apr_snapshot=run.snapshot,
        input_digest=hashlib.sha256(canonical_json(identity).encode()).hexdigest(),
        replace_where={"tf": run.tf, "symbol": POOLED_SYMBOL, "regime_scope": _JOB_SCOPE[job]},
    )


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
    parser.add_argument(
        "--start",
        help="ISO 8601 start of the window with a Z or offset (default: earliest tradeable bar)",
    )
    parser.add_argument("--feature-table", default="feature_vectors")
    parser.add_argument("--dry-run", action="store_true", help="compute and report, write nothing")
    parser.add_argument(
        "--allow-absent-digests",
        action="store_true",
        help="accept symbols with no bar_content_digest rows (revision detection blind for them)",
    )
    return parser.parse_args(argv)


def table_rows_by_tf(dsn: str) -> dict[str, int]:
    """Per-tf row counts of feature_ic_scores_v2 -- the manifest's coverage numbers are
    the table's state after the run, not the run's own writes: a fully skipped tf
    (identity match on every unit) writes zero rows while its rows from the prior run
    are exactly what a completeness gate must still see."""
    with short_lived_conn(dsn) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f"SELECT tf, COUNT(*) FROM {TARGET_TABLE} GROUP BY tf")
            return {tf: int(count) for tf, count in cur.fetchall()}


def main(argv: Sequence[str] | None = None) -> None:
    setup_service_logging("logs/ic_measure.log")
    args = _parse_args(argv)
    try:
        init_otel_providers(service_name=_JOB)
    except OTelInitError as error:
        _logger.warning("ic_measure.otel_init_failed", error=str(error))
    # The corpus verification gate (ops_corpus_final_verification.py) reads
    # ic_measure.json -- the same step-manifest contract the deleted ic_engine honored.
    # A dry run writes no rows and records no manifest: one would claim a completion
    # that never happened.
    manifest = (
        None if args.dry_run else CorpusManifest("ic_measure", CorpusManifest.DEFAULT_MANIFEST_DIR)
    )
    dsn = Settings().database_url
    status = "success"
    try:
        runner = IcMeasure(args, dsn)
        runner.run()
        if manifest is not None:
            manifest.set_inputs(tfs=runner.tfs, jobs=runner.jobs, oos_start=runner.oos_start_iso)
        for outcome in runner.outcomes:
            print(f"{outcome.status:14s} {outcome.writer:40s} rows={outcome.rows}")
        if runner.failures:
            status = "failure"
            for failure in runner.failures:
                print(f"FAILED {failure}", file=sys.stderr)
                if manifest is not None:
                    manifest.add_error(failure)
    except Exception as error:
        status = "failure"
        _logger.error("ic_measure.fatal_error", error=str(error))
        if manifest is not None:
            manifest.add_error(str(error))
        raise
    finally:
        if manifest is not None and status == "success":
            counts = table_rows_by_tf(dsn)
            manifest.add_output(TARGET_TABLE, sum(counts.values()), rows_by_tf=counts)
            manifest.mark_success()
        if manifest is not None:
            manifest.write()
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()
        if status == "failure":
            sys.exit(1)


if __name__ == "__main__":
    main()
