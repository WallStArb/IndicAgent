"""S0's pure feature-read decisions (todo 435 gap closures, phase 184 B1).

S0 is the only research node that reads stored data. It fetches rows; this module decides. Every
way a stored feature can be silently wrong for a run is a loud `FeatureInputRefused` naming its
rule id:

- B1d: a 15m or 1h bar that is not the derived 5m-grid aggregate (`check_intraday_vendors`).
- B1e: a column outside the registry allow-list never reaches SQL (`check_columns`,
  `feature_select_sql`); values land on the grid by exact (bar_ts, symbol) match
  (`scatter_rows`).
- B1f: provenance. Every (symbol, span) must be covered by completed batches that share one
  code_key and one FeatureFactoryConfig projection, and the spec's hash pin must equal that
  projection's hash (`provenance_pin`). The one config every downstream memory reads is rebuilt
  from that verified projection (`feature_config`); defaults and live APR are never used.
- B1g: warmup. The first declared-memory rows of each symbol are masked (`warmup_mask`); a
  path-dependent column has no finite memory and is refused (`refuse_path_dependent`).
- B1h: coverage below the pinned floor, by the one definition in
  `statistics.feature_coverage` (`coverage_check`).
- B1j: HMM regime columns before the walk-forward rebuild (todo 248, `refuse_regime_columns`).

No I/O and no database driver: the SQL text is pinned here and executed by S0. Manifest blocks
are JSON-able and deterministically ordered, in the shape of `data_quality.snapshot_manifest`.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import types
import typing
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import numpy as np

from src.intelligence.feature_factory import FeatureFactoryConfig
from src.intelligence.features.contract.registry import (
    KernelRegistry,
    default_registry,
    feature_memory_bars,
)
from src.intelligence.statistics.feature_coverage import SymbolCounts, feature_tf_quality


class FeatureInputRefused(ValueError):
    """A stored feature input S0 must not use; the message names the rule id."""


# Schema identifiers. 186-27 keeps the rebuilt rows under the `_v2` name in provenance, so both
# target names are read (RESEARCH Pattern 5).
FEATURE_TABLE = "feature_vectors"
PROVENANCE_TARGET_TABLES = ("feature_vectors", "feature_vectors_v2")
# The 186-26 rebuild's provenance identity (services/backfill_feature_factory.py `_JOB` and
# `_V2_TABLE`). Only its batches carry walk-forward HMM regime columns; earlier regime labels were
# fit on the whole series and leak the future (todo 248).
REBUILD_WRITER = "backfill-feature-factory"
REBUILD_TARGET_TABLE = "feature_vectors_v2"
# The only (vendor, kind) a 15m or 1h research bar may come from: the derived 5m-grid aggregate.
DERIVED_INTRADAY = ("derived", "5m_grid")
INTRADAY_DERIVED_TFS = ("15m", "1h")

PROVENANCE_SQL = (
    "SELECT batch_key, writer, target_table, tf, range_start, range_end, symbols, code_key, "
    "apr_hash, apr_snapshot, input_digest, generation, status FROM provenance_batch "
    "WHERE status = 'completed' AND target_table = ANY($1) AND tf = $2 "
    "AND range_start < $4 AND range_end > $3 "
    "ORDER BY batch_key, generation"
)


# ---------------------------------------------------------------------------
# B1e: columns and SQL
# ---------------------------------------------------------------------------


def check_columns(names: Iterable[str], registry: KernelRegistry) -> tuple[str, ...]:
    """The names, each checked against the registry's feature columns (the SQL-injection
    control: only an allow-listed identifier is ever quoted into SQL)."""
    allowed = set(registry.feature_columns())
    out = tuple(names)
    if not out:
        raise FeatureInputRefused("no feature columns requested (B1e)")
    unknown = sorted(n for n in out if n not in allowed)
    if unknown:
        raise FeatureInputRefused(f"unknown feature columns {unknown} (B1e)")
    if len(set(out)) != len(out):
        raise FeatureInputRefused(f"duplicate feature columns in {list(out)} (B1e)")
    return out


def feature_select_sql(names: Sequence[str], registry: KernelRegistry | None = None) -> str:
    """The pinned feature read: $1 tf, $2 symbols, $3 start, $4 end (exclusive)."""
    columns = check_columns(names, registry if registry is not None else default_registry())
    quoted = ", ".join(f'"{c}"' for c in columns)
    return (
        f"SELECT symbol, bar_ts, {quoted} FROM {FEATURE_TABLE} "
        "WHERE tf = $1 AND symbol = ANY($2) AND bar_ts >= $3 AND bar_ts < $4 "
        "ORDER BY bar_ts, symbol"
    )


# ---------------------------------------------------------------------------
# B1e: long-form rows to the [t, i] grid (body follows measure.ic.map_slots/scatter_features;
# research must not import measure)
# ---------------------------------------------------------------------------


def _slot_map(
    rows: Sequence[Sequence[Any]], timestamps: np.ndarray, symbols: Sequence[str]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(ok, grid rows, grid cols) for rows shaped (symbol, bar_ts, ...); exact match only."""
    m = len(symbols)
    if len(rows) == 0:
        empty = np.zeros(0, dtype=np.int64)
        return np.zeros(0, dtype=bool), empty, empty
    stamps = np.asarray(timestamps).astype("datetime64[ns]")
    ts = np.array([_ns(r[1]) for r in rows], dtype="datetime64[ns]")
    if len(stamps):
        pos = np.clip(np.searchsorted(stamps, ts), 0, len(stamps) - 1)
        ts_ok = stamps[pos] == ts
    else:
        pos = np.zeros(len(ts), dtype=np.int64)
        ts_ok = np.zeros(len(ts), dtype=bool)
    col_of = {s: j for j, s in enumerate(symbols)}
    col = np.fromiter((col_of.get(str(r[0]), -1) for r in rows), dtype=np.int64, count=len(rows))
    ok = ts_ok & (col >= 0)
    grid_rows, grid_cols = pos[ok].astype(np.int64), col[ok]
    flat = grid_rows * m + grid_cols
    if len(np.unique(flat)) != len(flat):
        raise FeatureInputRefused("duplicate (bar_ts, symbol) rows in the feature read (B1e)")
    return ok, grid_rows, grid_cols


def _ns(value: Any) -> np.datetime64:
    """A tz-aware datetime as UTC datetime64[ns]; numpy datetimes pass through."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise FeatureInputRefused(f"naive bar_ts {value!r} in the feature read (B1e)")
        return np.datetime64(value.astimezone(UTC).replace(tzinfo=None), "ns")
    return np.datetime64(value, "ns")


def scatter_rows(
    rows: Sequence[Sequence[Any]],
    timestamps: np.ndarray,
    symbols: Sequence[str],
    names: Sequence[str],
) -> tuple[dict[str, np.ndarray], int]:
    """Rows shaped (symbol, bar_ts, *values in `names` order) to float32 [t, i] arrays.

    A (bar_ts, symbol) pair lands on its grid slot by exact equality; a duplicate pair raises;
    rows matching no slot are counted and returned, never silently dropped. Cells no row
    reached, and NULL values, are NaN."""
    ok, grid_rows, grid_cols = _slot_map(rows, timestamps, symbols)
    shape = (len(timestamps), len(symbols))
    out: dict[str, np.ndarray] = {}
    for k, name in enumerate(names):
        grid = np.full(shape, np.nan, dtype=np.float32)
        if len(rows):
            raw = np.array(
                [np.nan if r[2 + k] is None else float(r[2 + k]) for r in rows], dtype=np.float64
            )
            grid[grid_rows, grid_cols] = raw[ok].astype(np.float32)
        out[name] = grid
    return out, int((~ok).sum())


def present_mask(
    rows: Sequence[Sequence[Any]], timestamps: np.ndarray, symbols: Sequence[str]
) -> np.ndarray:
    """bool [t, i]: the slots that received a stored row (a NULL value is still a present row).
    `warmup_mask` and `coverage_check` count rows by this mask, not by finite values."""
    _ok, grid_rows, grid_cols = _slot_map(rows, timestamps, symbols)
    out = np.zeros((len(timestamps), len(symbols)), dtype=bool)
    out[grid_rows, grid_cols] = True
    return out


# ---------------------------------------------------------------------------
# B1f: provenance pin and the one config
# ---------------------------------------------------------------------------


def _config_field_names() -> tuple[str, ...]:
    return tuple(f.name for f in dataclasses.fields(FeatureFactoryConfig))


def config_projection(apr_snapshot: Mapping[str, Any] | str) -> dict[str, Any]:
    """The snapshot restricted to the FeatureFactoryConfig fields; a missing field refuses."""
    snapshot = json.loads(apr_snapshot) if isinstance(apr_snapshot, str) else apr_snapshot
    if not isinstance(snapshot, Mapping):
        raise FeatureInputRefused(f"apr_snapshot is not an object: {type(snapshot)} (B1f)")
    names = _config_field_names()
    missing = sorted(n for n in names if n not in snapshot)
    if missing:
        raise FeatureInputRefused(f"apr_snapshot lacks FeatureFactoryConfig fields {missing} (B1f)")
    return {n: snapshot[n] for n in sorted(names)}


def config_projection_hash(projection: Mapping[str, Any]) -> str:
    """sha256 of the projection's canonical JSON (sorted keys, no whitespace)."""
    canonical = json.dumps(projection, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _field(batch: Mapping[str, Any], name: str) -> Any:
    try:
        return batch[name]
    except KeyError as error:
        raise FeatureInputRefused(f"provenance row lacks {name!r} (B1f)") from error


def _covers(ranges: list[tuple[datetime, datetime]], start: datetime, end: datetime) -> bool:
    """Whether the union of half-open ranges contains [start, end)."""
    reached = start
    for lo, hi in sorted(ranges):
        if lo > reached:
            break
        reached = max(reached, hi)
        if reached >= end:
            return True
    return reached >= end


def provenance_pin(
    batches: Iterable[Mapping[str, Any]],
    *,
    symbols: Sequence[str],
    span_start: datetime,
    span_end: datetime,
    pinned_config_projection_hash: str,
) -> dict:
    """The provenance manifest block for one (tf, span), or a B1f refusal.

    Covering batches are the completed ones overlapping [span_start, span_end) that hold at least
    one requested symbol (a superseded batch never covers). Each symbol's span must be inside the
    union of its covering ranges; the covering batches must share one code_key and one
    FeatureFactoryConfig projection (every field, pinned or not); and the pin must equal that
    projection's hash. The pin is hash-only, so no partial pin can exist."""
    if span_start >= span_end:
        raise FeatureInputRefused("provenance span is empty (B1f)")
    wanted = set(symbols)
    covering = []
    for batch in batches:
        if _field(batch, "status") != "completed":
            continue
        lo, hi = _field(batch, "range_start"), _field(batch, "range_end")
        if lo >= span_end or hi <= span_start:
            continue
        if wanted.isdisjoint(_field(batch, "symbols")):
            continue
        covering.append(batch)
    ranges: dict[str, list[tuple[datetime, datetime]]] = {s: [] for s in wanted}
    for batch in covering:
        for s in set(batch["symbols"]) & wanted:
            ranges[s].append((batch["range_start"], batch["range_end"]))
    uncovered = sorted(s for s in wanted if not _covers(ranges[s], span_start, span_end))
    if uncovered:
        raise FeatureInputRefused(
            f"no completed provenance covers [{span_start.isoformat()}, {span_end.isoformat()}) "
            f"for {len(uncovered)} symbols, first {uncovered[:5]} (B1f)"
        )
    code_keys = sorted({_field(b, "code_key") for b in covering})
    if len(code_keys) != 1:
        raise FeatureInputRefused(f"covering batches mix code keys {code_keys} (B1f)")
    projections = {b["batch_key"]: config_projection(_field(b, "apr_snapshot")) for b in covering}
    distinct = {config_projection_hash(p): p for p in projections.values()}
    if len(distinct) != 1:
        first, *rest = distinct.values()
        differing = sorted({k for p in rest for k in first if p[k] != first[k]})
        raise FeatureInputRefused(
            f"covering batches disagree on FeatureFactoryConfig fields {differing} (B1f)"
        )
    ((projection_hash, projection),) = distinct.items()
    if pinned_config_projection_hash != projection_hash:
        raise FeatureInputRefused(
            f"config_projection_hash pin {pinned_config_projection_hash} differs from the "
            f"stored projection hash {projection_hash} (B1f)"
        )
    return {
        "span": [span_start.isoformat(), span_end.isoformat()],
        "batch_keys": sorted({b["batch_key"] for b in covering}),
        "code_key": code_keys[0],
        "apr_hashes": sorted({str(_field(b, "apr_hash")) for b in covering}),
        "input_digests": {
            b["batch_key"]: _field(b, "input_digest")
            for b in sorted(covering, key=lambda b: b["batch_key"])
        },
        "writers": sorted({_field(b, "writer") for b in covering}),
        "target_tables": sorted({_field(b, "target_table") for b in covering}),
        "projection": projection,
        "projection_hash": projection_hash,
    }


def _coerce(value: Any, annotation: Any) -> Any:
    """A JSON-decoded value back to the annotated container type: lists to tuples, dicts to
    nested dataclasses. Scalars are returned as stored, so the projection hash is unchanged."""
    if value is None:
        return None
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        members = [a for a in typing.get_args(annotation) if a is not type(None)]
        for member in members:
            if (
                isinstance(member, type)
                and dataclasses.is_dataclass(member)
                and isinstance(value, Mapping)
            ):
                return _build(member, value)
        for member in members:
            if (typing.get_origin(member) or member) is tuple and isinstance(value, list | tuple):
                return _coerce(value, member)
        return value
    if isinstance(annotation, type) and dataclasses.is_dataclass(annotation):
        if not isinstance(value, Mapping):
            raise FeatureInputRefused(f"{annotation.__name__} stored as {type(value)} (B1f)")
        return _build(annotation, value)
    if (origin or annotation) is tuple and isinstance(value, list | tuple):
        args = typing.get_args(annotation)
        if not args:
            return tuple(value)
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_coerce(v, args[0]) for v in value)
        return tuple(_coerce(v, a) for v, a in zip(value, args, strict=True))
    if origin is dict and isinstance(value, Mapping):
        args = typing.get_args(annotation)
        return {k: _coerce(v, args[1]) for k, v in value.items()} if args else dict(value)
    return value


def _build(cls: type, values: Mapping[str, Any]) -> Any:
    """`cls` through its own constructor from a stored dict, every field present."""
    hints = typing.get_type_hints(cls)
    names = [f.name for f in dataclasses.fields(cls)]
    missing = sorted(n for n in names if n not in values)
    extra = sorted(k for k in values if k not in hints)
    if missing or extra:
        raise FeatureInputRefused(
            f"{cls.__name__} projection: missing {missing}, unknown {extra} (B1f)"
        )
    return cls(**{n: _coerce(values[n], hints[n]) for n in names})


def feature_config(block: Mapping[str, Any]) -> FeatureFactoryConfig:
    """The one FeatureFactoryConfig for a (tf, column set), built from the verified provenance
    block's projection only. Its hash is re-checked here, so a hand-edited block refuses."""
    projection = block["projection"]
    if config_projection_hash(projection) != block["projection_hash"]:
        raise FeatureInputRefused("provenance block projection does not match its hash (B1f)")
    return typing.cast(FeatureFactoryConfig, _build(FeatureFactoryConfig, projection))


# ---------------------------------------------------------------------------
# B1g: memory and warmup
# ---------------------------------------------------------------------------


def refuse_path_dependent(column: str, registry: KernelRegistry) -> None:
    if registry.is_path_dependent(column):
        raise FeatureInputRefused(
            f"{column} is path dependent: no finite memory, so its stored value depends on the "
            "series start (B1g)"
        )


def column_memory_bars(column: str, config: FeatureFactoryConfig, registry: KernelRegistry) -> int:
    """Declared memory in bars of `column` under the verified config (the registry's one
    definition, `feature_memory_bars`)."""
    refuse_path_dependent(column, registry)
    return feature_memory_bars(column, config, registry)


def warmup_mask(
    values: np.ndarray, memory_bars: int, *, present: np.ndarray
) -> tuple[np.ndarray, dict[str, int]]:
    """NaN for each symbol's first `memory_bars` present rows; returns (array, counts).

    Rows are counted from the symbol's first present row in the fetched span, by row presence
    (`present_mask`), not by finite value, so a second application, or the rebuild's own mask
    already in the stored rows, changes nothing."""
    if memory_bars < 0:
        raise ValueError("memory_bars must be non-negative")
    if values.shape != present.shape:
        raise ValueError("values and present must share the [t, i] shape")
    out = np.array(values, copy=True)
    masked_cells = 0
    finite_masked = 0
    if memory_bars:
        for j in range(out.shape[1]):
            rows = np.flatnonzero(present[:, j])[:memory_bars]
            finite_masked += int(np.isfinite(out[rows, j]).sum())
            masked_cells += len(rows)
            out[rows, j] = np.nan
    return out, {
        "memory_bars": int(memory_bars),
        "masked_rows": masked_cells,
        "masked_finite": finite_masked,
    }


# ---------------------------------------------------------------------------
# B1h: coverage
# ---------------------------------------------------------------------------


def coverage_check(
    values: np.ndarray,
    symbols: Sequence[str],
    *,
    present: np.ndarray,
    feature: str,
    tf: str,
    floor: float,
) -> dict:
    """The coverage block, by `feature_tf_quality` over per-symbol counts from the [t, i]
    array; refuses below the pinned floor or when no symbol has a row."""
    if values.shape != present.shape or values.shape[1] != len(symbols):
        raise ValueError("values, present and symbols must agree on shape")
    counts = []
    for j, symbol in enumerate(symbols):
        cells = values[present[:, j], j]
        counts.append(
            SymbolCounts(
                symbol=symbol,
                n_rows=int(present[:, j].sum()),
                n_non_null=int((~np.isnan(cells)).sum()),
                n_non_finite=int(np.isinf(cells).sum()),
            )
        )
    quality = feature_tf_quality(feature, tf, counts)
    coverage = quality.symbol_coverage
    if coverage is None or coverage < floor:
        raise FeatureInputRefused(
            f"{feature} at {tf}: symbol coverage {coverage} below the pinned floor {floor} (B1h)"
        )
    return {
        "feature": feature,
        "tf": tf,
        "symbol_coverage": coverage,
        "floor": floor,
        "n_symbols_with_rows": quality.n_symbols_with_rows,
        "n_symbols_populated": quality.n_symbols_populated,
        "n_non_finite": quality.n_non_finite,
    }


# ---------------------------------------------------------------------------
# B1j: HMM regime columns; B1d: intraday vendors
# ---------------------------------------------------------------------------


def refuse_regime_columns(
    columns: Iterable[str], registry: KernelRegistry, batches: Iterable[Mapping[str, Any]]
) -> None:
    """A regime-origin column is refused unless every completed batch is the 186-26 rebuild
    (writer and target table), whose HMM labels are walk-forward (todo 248)."""
    regime = sorted(c for c in columns if registry.by_output(c).origin == "regime")
    if not regime:
        return
    completed = [b for b in batches if b.get("status", "completed") == "completed"]
    foreign = sorted(
        {
            (str(b.get("writer")), str(b.get("target_table")))
            for b in completed
            if (b.get("writer"), b.get("target_table")) != (REBUILD_WRITER, REBUILD_TARGET_TABLE)
        }
    )
    if not completed or foreign:
        raise FeatureInputRefused(
            f"regime columns {regime} need every covering batch from the walk-forward rebuild "
            f"({REBUILD_WRITER}, {REBUILD_TARGET_TABLE}); found {foreign or 'no batches'} (B1j)"
        )


def check_intraday_vendors(tf: str, vendor_kinds: Iterable[tuple[str, str]]) -> list[list[str]]:
    """The sorted (vendor, kind) set for the manifest; at 15m and 1h anything other than the
    derived 5m-grid aggregate refuses."""
    found = sorted({(str(v), str(k)) for v, k in vendor_kinds})
    if tf in INTRADAY_DERIVED_TFS:
        bad = [pair for pair in found if pair != DERIVED_INTRADAY]
        if bad:
            raise FeatureInputRefused(f"{tf} bars must be {DERIVED_INTRADAY}, found {bad} (B1d)")
    return [list(pair) for pair in found]


def feature_array_name(tf: str, column: str) -> str:
    return f"feature__{tf}__{column}"
