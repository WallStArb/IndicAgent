"""Live parity replay of stored POOLED cross-sectional feature_ic_scores cells (phase 186-20).

Replays each sampled stored cell's observation set through `measure.ic.pooled_rank_ic` with the
table's targets (must reproduce the stored ic_value to the float32 pipeline's error bound and the
stored n_independent exactly) and with kernel targets (every difference attributed to a cause and
counted). Read-only: one connection, `set_read_only`, no write session. Writes the parity report.

Not part of any suite run: `pytest tests/integration/test_ic_parity_replay.py -m parity -q -s`.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import math
import random
import re
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg
import pytest

from services._batch_utils import load_config_service_sync
from services.ic_measure import (
    apr_keys_read,
    fetch_long_form,
    load_params,
    make_tf_context,
)
from src.config.settings import dimension_where_clause
from src.intelligence.measure.ic import (
    align_features,
    existing_rows,
    map_slots,
    observation_rows,
    pooled_rank_ic,
    scatter_features,
)
from src.intelligence.measure.params import MeasureParams
from src.intelligence.measure.targets import (
    build_target_panels,
    stack_at_horizon,
    stack_grid,
)
from src.intelligence.measure.targets import stride as target_stride
from src.intelligence.research import panel as research_panel
from src.intelligence.schemas import FeatureVector
from tests.unit.measure.parity_replay import (
    ObservationRows,
    classify_target_diffs,
    compare_point_ic,
    float32_pipeline_tolerance,
    legacy_arithmetic_ic,
    rebuild_observation_set,
    replay_kernel_targets,
    replay_table_targets,
)

pytestmark = [pytest.mark.integration, pytest.mark.requires_db, pytest.mark.parity]

REPORT_PATH = (
    Path(__file__).resolve().parents[2]
    / ".planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope"
    / "186-20-PARITY-REPORT.md"
)
WRITER_BEGIN = "<!-- BEGIN writer-path parity cell -->"
WRITER_END = "<!-- END writer-path parity cell -->"

# The live database, not the suite's indicagent_test: under pytest `Settings` points at the test
# database, and the stored cells being replayed exist only in production. Read-only throughout.
LIVE_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent"

SAMPLE_SEED = 18620
N_FEATURES = 30
N_LABELS = 3
CHUNK_TS = 5000  # ic_engine cs_chunk_ts; a fetch size, never enters a value
PAIRS: dict[str, tuple[int, ...]] = {
    "5m": (6, 12, 39),
    "15m": (2, 5, 10),
    "1h": (1, 2),
    "1d": (1, 2, 5, 10),
}
EXCLUDED_HORIZONS: dict[str, tuple[int, ...]] = {"1h": (20, 60)}
SCALES = ("fast", "mid", "slow", "extended")
STRICT_TOL = 1e-9
KERNEL_ATOL = 1e-12
_REGIME_COLUMN = re.compile(r"regime|hmm")
_ROUTING_LABEL = "market_regimes"


@pytest.fixture(scope="session", autouse=True)
def migrated_test_database() -> None:
    """Overrides the suite's indicagent_test rebuild: this module reads the live database only."""


# ---------------------------------------------------------------------------
# Live reads
# ---------------------------------------------------------------------------


def _connect() -> psycopg.Connection:
    conn = psycopg.connect(LIVE_DB_URL)
    conn.set_read_only(True)
    return conn


def candidate_features(conn: psycopg.Connection) -> tuple[list[str], dict[str, int]]:
    """FeatureVector fields that are numeric feature_vectors columns (dtype from
    information_schema), minus concept_registry broadcast features and regime columns."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'feature_vectors' "
            "AND data_type IN ('real', 'double precision')"
        )
        numeric = {r[0] for r in cur.fetchall()}
        cur.execute(
            "SELECT name FROM concept_registry WHERE domain = 'feature' "
            "AND metadata->>'broadcast' = 'true'"
        )
        broadcast = {r[0] for r in cur.fetchall()}
    fields = {f.name for f in dataclasses.fields(FeatureVector)}
    numeric_fields = fields & numeric
    regime = {n for n in numeric_fields if _REGIME_COLUMN.search(n)}
    broadcast_excluded = numeric_fields & broadcast
    candidates = sorted(numeric_fields - broadcast_excluded - regime)
    return candidates, {
        "feature_fields": len(fields),
        "numeric_fields": len(numeric_fields),
        "broadcast_excluded": len(broadcast_excluded),
        "regime_excluded": len(regime - broadcast_excluded),
        "candidates": len(candidates),
    }


def sampled_labels(conn: psycopg.Connection, tf: str) -> list[tuple[str, int]]:
    """The tf's top-3 stored cross_sectional POOLED labels by row count, ties alphabetical."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT regime, count(*) FROM feature_ic_scores WHERE symbol = 'POOLED' AND is_pooled "
            "AND regime_scope = 'cross_sectional' AND tf = %s GROUP BY regime "
            "ORDER BY count(*) DESC, regime LIMIT %s",
            (tf, N_LABELS),
        )
        return [(r[0], r[1]) for r in cur.fetchall()]


def regime_group_of(conn: psycopg.Connection, label: str, tf: str) -> str:
    """The one regime_group that owns the label (the label-vocabulary-uniqueness invariant)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT regime_group FROM market_regimes WHERE regime_label = %s AND tf = %s",
            (label, tf),
        )
        groups = [r[0] for r in cur.fetchall()]
    assert (
        len(groups) == 1
    ), f"label {label} on {tf} belongs to {groups}, expected exactly one group"
    return groups[0]


def peer_symbols(conn: psycopg.Connection, group: str, cutoff: datetime) -> list[str]:
    """The group's peer symbols as ic_engine routes them (services/ic_engine.py 5951-5979 and
    `_build_symbol_regime_class` 296): compute-eligible instruments, human tags only, first enabled
    group whose tag_filter prefix matches a tag and whose exclude_symbols omits the symbol. Read-only
    replica so this test survives the deletion of ic_engine (186-23). Point in time: instruments
    created after the stored run (`cutoff`) were not in its universe."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT config_value FROM config_state WHERE config_key = 'alpha.regime.groups'"
        )
        groups = [g for g in json.loads(cur.fetchone()[0]) if g.get("enabled", True)]
        cur.execute(
            "SELECT i.symbol, array_remove(array_agg(t.tag), NULL::text) FROM instruments i "
            "LEFT JOIN instrument_tags t ON t.symbol = i.symbol AND t.source = 'human' "
            f"WHERE {dimension_where_clause('compute', 'i')} AND i.created_at <= %s "
            "GROUP BY i.symbol",
            (cutoff,),
        )
        tags = {r[0]: set(r[1]) for r in cur.fetchall()}
    prefixes = [
        (
            g["name"],
            [p.rstrip("*") for p in g.get("tag_filter", [])],
            set(g.get("exclude_symbols", [])),
        )
        for g in groups
    ]
    peers = []
    for symbol, symbol_tags in tags.items():
        matches = [
            name
            for name, pfx, exclude in prefixes
            if symbol not in exclude and any(any(t.startswith(p) for t in symbol_tags) for p in pfx)
        ]
        assert len(matches) <= 1, f"{symbol} matches several groups {matches}"
        if matches == [group]:
            peers.append(symbol)
    return sorted(peers)


def label_bars(
    conn: psycopg.Connection, group: str, tf: str, label: str, end: datetime
) -> np.ndarray:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ts FROM market_regimes WHERE regime_group = %s AND tf = %s AND regime_label = %s "
            "AND ts <= %s ORDER BY ts",
            (group, tf, label, end),
        )
        stamps = (
            pd.DatetimeIndex([r[0] for r in cur.fetchall()]).tz_convert("UTC").tz_localize(None)
        )
    return stamps.values.astype("datetime64[ns]")


def _naive_utc(stamps: Any, tf: str) -> np.ndarray:
    out = pd.DatetimeIndex(stamps).tz_convert("UTC").tz_localize(None)
    if tf == "1d":
        out = out.normalize()
    return out.values.astype("datetime64[ns]")


def make_fetcher(conn: psycopg.Connection, tf: str, features: list[str]):
    """ic_engine's chunk SQL (services/ic_engine.py 4902-4915), all four scales."""
    feature_cols = ", ".join(f'fv."{f}"' for f in features)
    return_cols = ", ".join(f"fr.return_{s}" for s in SCALES)
    complete_cols = ", ".join(f"fr.complete_{s}" for s in SCALES)
    stmt = f"""
        SELECT fv.bar_ts, fv.symbol, {feature_cols}, {return_cols}, {complete_cols},
               fr.has_gap_before_entry
        FROM feature_vectors fv
        INNER JOIN forward_returns fr
            ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
            AND fr.return_type = 'executable_open_to_open'
        WHERE fv.tf = %(tf)s
          AND fv.bar_ts BETWEEN %(ts_min)s AND %(ts_max)s
          AND fv.bar_ts = ANY(%(ts_chunk)s)
          AND fv.symbol = ANY(%(symbols)s)
        ORDER BY fv.bar_ts, fv.symbol
    """
    k, s = len(features), len(SCALES)

    def fetch(ts_chunk: list, symbols: list[str]) -> ObservationRows:
        aware = [pd.Timestamp(t).tz_localize("UTC").to_pydatetime() for t in ts_chunk]
        with conn.cursor() as cur:
            cur.execute(
                stmt,
                {
                    "tf": tf,
                    "ts_min": aware[0],
                    "ts_max": aware[-1],
                    "ts_chunk": aware,
                    "symbols": symbols,
                },
            )
            rows = cur.fetchall()
        if not rows:
            empty = np.zeros(0)
            return ObservationRows(
                np.zeros(0, dtype="datetime64[ns]"),
                np.zeros(0, dtype=str),
                np.zeros((0, k)),
                np.zeros((0, s)),
                np.zeros((0, s), dtype=bool),
                empty.astype(bool),
            )
        cols = list(zip(*rows, strict=True))
        return ObservationRows(
            bar_ts=_naive_utc(cols[0], tf),
            symbols=np.asarray(cols[1], dtype=str),
            X=np.array(cols[2 : 2 + k], dtype=float).T,
            returns=np.array(cols[2 + k : 2 + k + s], dtype=float).T,
            complete=np.array([[bool(v) for v in c] for c in cols[2 + k + s : 2 + k + 2 * s]]).T,
            has_gap=np.array([bool(v) for v in cols[-1]]),
        )

    return fetch


def stored_cells(
    conn: psycopg.Connection, tf: str, label: str, features: list[str], horizons: tuple[int, ...]
) -> dict[tuple[str, int], tuple[float | None, int]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT feature_name, lookahead_bars, ic_value, n_independent FROM feature_ic_scores "
            "WHERE symbol = 'POOLED' AND is_pooled AND regime_scope = 'cross_sectional' "
            "AND tf = %s AND regime = %s AND feature_name = ANY(%s) AND lookahead_bars = ANY(%s)",
            (tf, label, features, list(horizons)),
        )
        return {(r[0], r[1]): (r[2], r[3]) for r in cur.fetchall()}


def scale_of(cfg: Any, tf: str, horizon: int) -> str:
    """The scale whose `alpha.ic.lookahead.<tf>.<scale>` APR value equals the stored lookahead."""
    hits = [s for s in SCALES if cfg.get_sync(f"alpha.ic.lookahead.{tf}.{s}", None) == horizon]
    assert len(hits) == 1, f"{tf} horizon {horizon} matches scales {hits}"
    return hits[0]


def measure_params(conn: psycopg.Connection, tf: str) -> tuple[MeasureParams, Any, datetime]:
    cfg = load_config_service_sync(conn)
    apr = {k: cfg.get_sync(k, None) for k in apr_keys_read(tf)}
    oos = datetime.fromisoformat(str(cfg.get_sync("alpha.validation.oos_start", None)))
    oos = oos.astimezone(UTC) if oos.tzinfo else oos.replace(tzinfo=UTC)
    return load_params(apr, tf), cfg, oos


# ---------------------------------------------------------------------------
# One timeframe
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CellResult:
    tf: str
    label: str
    group: str
    feature: str
    horizon: int
    stored_ic: float | None
    stored_n: int
    table_ic: float
    table_n: int
    legacy_ic: float
    kernel_ic: float
    kernel_n: int
    bound: float
    n_strided: int
    n_target_invalid: int  # strided rows whose target is incomplete or non-finite
    n_feature_missing: int  # strided rows whose feature value is non-finite


@dataclasses.dataclass
class LabelDiffs:
    tf: str
    label: str
    horizon: int
    n_rows: int
    n_equal: int
    n_end_of_window: int
    n_gap: int
    n_other: int
    n_session_cross: int
    n_open_missing: int
    n_unmatched_slots: int


@dataclasses.dataclass
class TfOutcome:
    cells: list[CellResult]
    diffs: list[LabelDiffs]
    missing_stored: list[str]
    seconds: float
    peer_counts: dict[str, int]


def run_tf(conn: psycopg.Connection, tf: str, features: list[str]) -> TfOutcome:
    started = datetime.now(UTC)
    params, cfg, oos = measure_params(conn, tf)
    stored_run = datetime(
        2026, 9, 24, 23, 59, tzinfo=UTC
    )  # the run's corpus date, for point in time
    labels = sampled_labels(conn, tf)
    assert len(labels) == N_LABELS, f"{tf}: {len(labels)} labels"
    cells: list[CellResult] = []
    diffs: list[LabelDiffs] = []
    missing: list[str] = []
    peer_counts: dict[str, int] = {}
    fetch = make_fetcher(conn, tf, features)
    horizons = PAIRS[tf]
    for label, _count in labels:
        group = regime_group_of(conn, label, tf)
        peers = peer_symbols(conn, group, stored_run)
        peer_counts[f"{group}/{label}"] = len(peers)
        bars = label_bars(conn, group, tf, label, oos)
        obs = rebuild_observation_set(bars, peers, fetch, chunk_ts=CHUNK_TS)
        stored = stored_cells(conn, tf, label, features, horizons)
        used = sorted(set(obs.symbols.tolist()))
        with tempfile.TemporaryDirectory(prefix="parity_") as tmp:
            earliest = obs.bar_ts.min().astype("datetime64[s]").astype(datetime).replace(tzinfo=UTC)
            paths = asyncio.run(
                build_target_panels(
                    LIVE_DB_URL,
                    Path(tmp),
                    used,
                    tf,
                    earliest.isoformat(),
                    oos.isoformat(),
                    oos.isoformat(),
                    params,
                )
            )
            panels = [research_panel.load(p) for p in paths]
        grid = stack_grid(panels, oos.replace(tzinfo=None).isoformat())
        slots = map_slots(grid, obs.bar_ts, obs.symbols)
        feature_grid, n_unmatched = scatter_features(grid, slots, obs.X)
        present = slots.present(len(grid.timestamps), len(grid.symbols))
        open_grid = np.full((len(grid.timestamps), len(grid.symbols)), np.nan)
        col = 0
        for panel, rows in zip(panels, grid.chunk_rows, strict=True):
            open_grid[rows, col : col + len(panel.symbols)] = np.asarray(panel.open)
            col += len(panel.symbols)
        slots_cols = np.zeros(len(obs.bar_ts), dtype=np.int64)
        slots_cols[slots.ok] = slots.cols
        for horizon in horizons:
            scale = scale_of(cfg, tf, horizon)
            scale_idx = SCALES.index(scale)
            stack = stack_at_horizon(grid, panels, horizon)
            kernel_rows = np.full(len(obs.bar_ts), np.nan)
            kernel_rows[slots.ok] = stack.targets[slots.rows, slots.cols]
            grid_row = np.full(len(obs.bar_ts), -1, dtype=np.int64)
            grid_row[slots.ok] = slots.rows
            session_cross = None
            if grid.bars_per_session > 1:  # the kernel's own rule (panel.forward_returns, session=)
                n_rows_grid = len(grid.timestamps)
                entry = np.clip(grid_row + 1, 0, n_rows_grid - 1)
                exit_ = grid_row + 1 + horizon
                inside = slots.ok & (exit_ < n_rows_grid)
                session_cross = inside & (
                    stack.session[np.clip(exit_, 0, n_rows_grid - 1)] != stack.session[entry]
                )
            entry_nan = np.isnan(
                open_grid[np.clip(grid_row + 1, 0, len(grid.timestamps) - 1), slots_cols]
            )
            exit_nan = np.isnan(
                open_grid[np.clip(grid_row + 1 + horizon, 0, len(grid.timestamps) - 1), slots_cols]
            )
            open_missing = (
                slots.ok & (grid_row + 1 + horizon < len(grid.timestamps)) & (entry_nan | exit_nan)
            )
            counts = classify_target_diffs(
                obs.returns[:, scale_idx],
                obs.complete[:, scale_idx],
                kernel_rows,
                has_gap=obs.has_gap,
                in_grid=slots.ok,
                grid_row=grid_row,
                n_grid=len(grid.timestamps),
                horizon=horizon,
                atol=KERNEL_ATOL,
                session_cross=session_cross,
                open_missing=open_missing,
            )
            diffs.append(
                LabelDiffs(
                    tf,
                    label,
                    horizon,
                    counts.n_rows,
                    counts.n_equal,
                    counts.n_end_of_window,
                    counts.n_gap,
                    counts.n_other,
                    counts.n_session_cross,
                    counts.n_open_missing,
                    n_unmatched,
                )
            )
            for j, feature in enumerate(features):
                key = (feature, horizon)
                if key not in stored:
                    missing.append(f"{tf}/{label}/{feature}/{horizon}")
                    continue
                stored_ic, stored_n = stored[key]
                one = dataclasses.replace(obs, X=obs.X[:, [j]])
                table = replay_table_targets(
                    one,
                    scale_idx=scale_idx,
                    horizon=horizon,
                    params=params,
                    feature_names=(feature,),
                )
                legacy = legacy_arithmetic_ic(
                    one, scale_idx=scale_idx, horizon=horizon, params=params
                )
                kernel = replay_kernel_targets(
                    feature_grid[:, :, [j]],
                    stack.targets,
                    stack.valid_grid(),
                    present,
                    horizon=horizon,
                    params=params,
                    feature_names=(feature,),
                )
                stride = max(params.min_stride, horizon)
                strided = slice(0, None, stride)
                y_all = np.where(obs.complete[:, scale_idx], obs.returns[:, scale_idx], np.nan)
                n_strided = len(y_all[strided])
                cells.append(
                    CellResult(
                        tf,
                        label,
                        group,
                        feature,
                        horizon,
                        stored_ic,
                        stored_n,
                        float(table.ic[0]),
                        int(table.n_independent[0]),
                        float(legacy[0]),
                        float(kernel.ic[0]),
                        int(kernel.n_independent[0]),
                        float32_pipeline_tolerance(stored_n),
                        n_strided,
                        int(np.isnan(y_all[strided]).sum()),
                        int((~np.isfinite(obs.X[strided, j])).sum()),
                    )
                )
        del obs, feature_grid, grid
    seconds = (datetime.now(UTC) - started).total_seconds()
    print(f"parity {tf}: {len(cells)} cells, {len(missing)} missing stored, {seconds:.0f}s")
    return TfOutcome(cells, diffs, missing, seconds, peer_counts)


# ---------------------------------------------------------------------------
# Verdict and report
# ---------------------------------------------------------------------------


def judge(cell: CellResult) -> tuple[bool, bool, bool]:
    """(n_independent agrees, ic within the float32 bound, ic within the strict 1e-9)."""
    degenerate = cell.table_n == 0  # a column pooled_rank_ic dropped: no n_independent to compare
    n_ok = degenerate or cell.table_n == cell.stored_n
    cmp = compare_point_ic(cell.table_ic, cell.stored_ic, tol=cell.bound)
    strict = compare_point_ic(cell.table_ic, cell.stored_ic, tol=STRICT_TOL)
    return n_ok, cmp.match, strict.match


def legacy_matches(cell: CellResult) -> bool:
    """The legacy-arithmetic replica reproduces the stored cell: NaN pattern and float32 bound."""
    return compare_point_ic(cell.legacy_ic, cell.stored_ic, tol=cell.bound).match


REPRODUCED = "reproduced"
LEGACY_ZERO = "legacy_zero_ic_for_non_finite_feature"
RANK_SCOPE = "legacy_ranks_before_the_target_mask"
FLOAT32_NOISE = "float32_noise_beyond_the_committed_bound"
UNEXPLAINED = "unexplained"


def cause(cell: CellResult) -> str:
    """Why the fresh function and the stored cell agree or differ.

    - reproduced: n_independent equal, NULL pattern equal, within the float32 bound.
    - legacy_zero: stored 0.0 and a non-finite feature value among the strided rows. ic_engine ranks
      with `rankdata(axis=0)`, which returns NaN for a whole column holding one NaN, and
      `_vectorized_ic` turns a NaN denominator into 0.0; the fresh function drops the non-finite rows.
    - rank_scope: no non-finite feature value, strided rows with an incomplete target, and the legacy
      replica reproduces the stored cell: ic_engine ranks X over every strided row and masks the ranks
      afterwards, the fresh function ranks the valid rows only (the textbook Spearman).
    - float32_noise: the legacy replica fails the bound but agrees with the fresh value within it, so
      the stored value carries float32 summation noise above the pre-committed bound (the old
      pipeline sums naively down a block of columns). Reported as a miss of the committed bound.
    - unexplained: anything else."""
    n_ok, within, _ = judge(cell)
    if n_ok and within:
        return REPRODUCED
    if not legacy_matches(cell):
        fresh_vs_legacy = compare_point_ic(cell.table_ic, cell.legacy_ic, tol=cell.bound)
        if n_ok and cell.n_feature_missing == 0 and fresh_vs_legacy.match:
            return FLOAT32_NOISE
        return UNEXPLAINED
    if cell.stored_ic == 0.0 and cell.n_feature_missing > 0:
        return LEGACY_ZERO
    if cell.n_feature_missing == 0 and cell.n_target_invalid > 0 and n_ok:
        return RANK_SCOPE
    return UNEXPLAINED


def render_report(
    sample: list[str],
    counts: dict[str, int],
    outcomes: dict[str, TfOutcome],
    labels: dict[str, list[tuple[str, int]]],
    stored_total: int,
) -> str:
    cells = [c for o in outcomes.values() for c in o.cells]
    missing = [m for o in outcomes.values() for m in o.missing_stored]
    verdicts = [judge(c) for c in cells]
    n_fail = sum(not (v[0] and v[1]) for v in verdicts)
    causes = [cause(c) for c in cells]
    by_cause = Counter(causes)
    n_differ = len(cells) - by_cause[REPRODUCED]
    n_legacy_ok = sum(legacy_matches(c) for c in cells)
    max_delta: dict[str, float] = {}
    lost_ic: dict[str, float] = {}
    for name in (REPRODUCED, LEGACY_ZERO, RANK_SCOPE, FLOAT32_NOISE, UNEXPLAINED):
        picked = [c for c, k in zip(cells, causes, strict=True) if k == name]
        both = [
            abs(c.table_ic - c.stored_ic)
            for c in picked
            if c.stored_ic is not None and not math.isnan(c.table_ic)
        ]
        max_delta[name] = max(both) if both else 0.0
        zeros = [
            abs(c.table_ic) for c in picked if c.stored_ic == 0.0 and not math.isnan(c.table_ic)
        ]
        lost_ic[name] = max(zeros) if zeros else 0.0
    differ_by_tf = dict(
        Counter(c.tf for c, k in zip(cells, causes, strict=True) if k != REPRODUCED)
    )
    legacy_zero_all_missing = sum(
        1 for c, k in zip(cells, causes, strict=True) if k == LEGACY_ZERO and math.isnan(c.table_ic)
    )
    n_strict = sum(v[2] for v in verdicts)
    deltas = [
        abs(c.table_ic - c.stored_ic)
        for c in cells
        if c.stored_ic is not None and not math.isnan(c.table_ic)
    ]
    stored_null = sum(c.stored_ic is None for c in cells)
    both_null = sum(c.stored_ic is None and math.isnan(c.table_ic) for c in cells)
    null_mismatch = [
        f"{c.tf}/{c.label}/{c.feature}/{c.horizon}"
        for c in cells
        if (c.stored_ic is None) != math.isnan(c.table_ic)
    ]
    n_mismatch = [
        f"{c.tf}/{c.label}/{c.feature}/{c.horizon} stored {c.stored_n} replay {c.table_n}"
        for c, v in zip(cells, verdicts, strict=True)
        if not v[0]
    ]
    n_mismatch_clean = sum(
        1 for c, v in zip(cells, verdicts, strict=True) if not v[0] and c.n_feature_missing == 0
    )
    diffs = [d for o in outcomes.values() for d in o.diffs]
    agg = Counter()
    for d in diffs:
        agg["rows"] += d.n_rows
        agg["equal"] += d.n_equal
        agg["end_of_window"] += d.n_end_of_window
        agg["gap"] += d.n_gap
        agg["other"] += d.n_other
        agg["session_cross"] += d.n_session_cross
        agg["open_missing"] += d.n_open_missing
    worst = sorted(diffs, key=lambda d: d.n_other, reverse=True)[:5]
    kernel_n_equal = sum(c.kernel_n == c.table_n for c in cells)
    kernel_delta = [
        abs(c.kernel_ic - c.table_ic)
        for c in cells
        if not math.isnan(c.kernel_ic) and not math.isnan(c.table_ic)
    ]
    excluded = sum(
        len(sample) * len(h) * N_LABELS for tf, h in EXCLUDED_HORIZONS.items() if tf in labels
    )
    if by_cause[UNEXPLAINED] or missing:
        verdict = "FAIL (unexplained differences or missing stored rows)"
    elif n_legacy_ok != len(cells) - by_cause[FLOAT32_NOISE]:
        verdict = "FAIL (the legacy-arithmetic replica does not reproduce every stored cell)"
    else:
        verdict = (
            "PASS under the restated criterion (owner decision 2026-10-01): the legacy-arithmetic "
            f"replica reproduces the stored cells ({n_legacy_ok} of {len(cells)}; the "
            f"{by_cause[FLOAT32_NOISE]} others are float32 summation noise in the stored value) and "
            f"every fresh-versus-stored difference ({n_differ} cells) is attributed to a named cause: "
            f"{by_cause[LEGACY_ZERO]} NaN-denominator zeros, {by_cause[RANK_SCOPE]} rank-scope, "
            f"{by_cause[FLOAT32_NOISE]} float32 noise. pooled_rank_ic is unchanged"
        )
    lines = [
        "# 186-20 parity report: stored POOLED cells versus the fresh IC function",
        "",
        f"Verdict: {verdict}. Generated {datetime.now(UTC).isoformat(timespec='seconds')} by "
        "`tests/integration/test_ic_parity_replay.py` (read-only).",
        "",
        "## Stated sample (fixed before running)",
        "",
        f"- Features: {N_FEATURES}, chosen once with `random.Random({SAMPLE_SEED}).sample(sorted(candidates), "
        f"{N_FEATURES})`. Candidates are the FeatureVector fields that are numeric `feature_vectors` "
        "columns (dtype from information_schema), excluding concept_registry broadcast-flagged "
        "features and regime columns.",
        f"- Candidate accounting: {json.dumps(counts)}. Broadcast-excluded count: "
        f"{counts['broadcast_excluded']}.",
        "- Sampled features: " + ", ".join(f"`{f}`" for f in sample),
        "- Timeframes and horizons: 5m {6,12,39}, 15m {2,5,10}, 1h {1,2}, 1d {1,2,5,10}. The 1h "
        "horizons 20 and 60 cross a session, have no kernel counterpart, and are excluded: "
        f"{excluded} cells excluded ({N_FEATURES} features x 2 horizons x {N_LABELS} labels).",
        "- Labels per tf (the 3 `regime_scope = 'cross_sectional'` labels with the most stored "
        "POOLED rows, ties alphabetical): "
        + "; ".join(
            f"{tf}: "
            + ", ".join(
                f"{lab} ({n} rows, group {_group_of(outcomes[tf], lab)})" for lab, n in labs
            )
            for tf, labs in labels.items()
        ),
        f"- Cells: {N_FEATURES} features x 12 (tf, horizon) pairs x {N_LABELS} labels = "
        f"{N_FEATURES * 12 * N_LABELS} per replay pass; replayed: {len(cells)}. POOLED earnings_season "
        "cells share the machinery but are out of the sample.",
        "- Point IC only; confidence intervals are RNG-dependent and out of parity scope (D-21).",
        f"- Peer symbols per (group/label): {json.dumps({k: v for o in outcomes.values() for k, v in o.peer_counts.items()})}",
        "",
        "## Pass criterion (committed with the harness before any live result was read)",
        "",
        "ic_engine stores `ic_value` as the result of `_vectorized_ic` on float32 ranks: every stored "
        "value is a float32 number, so 1e-9 absolute cannot hold for a faithful replay (float32 spacing "
        "at 0.0080 is 9.3e-10 and at 0.25 is 3e-8). The harness holds each cell to: stored "
        "`n_independent` equal exactly (a different row set cannot pass), stored NULL if and only if "
        "replay NaN, and `|replayed - stored| <= 2 * eps32 * ceil(log2(n_independent))` (the float32 "
        "pipeline's summation error bound, `float32_pipeline_tolerance`). The strict 1e-9 count is "
        "reported alongside. The writer-path cell below is float64 against float64 and is held to 1e-9.",
        "",
        "## Table-target result",
        "",
        f"- Stored POOLED cross_sectional rows replayed: {len(cells)}; missing stored rows: {len(missing)}.",
        f"- Cells matched (n_independent equal, NULL pattern equal, within the float32 bound): "
        f"{by_cause[REPRODUCED]} of {len(cells)}; within the strict 1e-9: {n_strict}.",
        f"- Cells that differ: {n_differ}; unexplained: {by_cause[UNEXPLAINED]}.",
        f"- Max abs delta over cells where both sides are finite: "
        f"{max(deltas) if deltas else float('nan'):.3e}.",
        f"- n_independent mismatches: {len(n_mismatch)}, of which {n_mismatch_clean} are in cells whose "
        "feature has no non-finite value among the strided rows. The peer set, label bars, stride and "
        "target mask reproduce ic_engine's row set exactly where that count is zero; the other "
        "mismatches are partly-missing features, whose fresh count excludes the non-finite rows.",
        f"- Legacy-arithmetic replica (float32 features, a column with a non-finite value ranks NaN and "
        f"stores 0.0, ranks before the target mask, float32 ranks, `_vectorized_ic`) reproduces the "
        f"stored cell in {n_legacy_ok} of {len(cells)} cells (n_independent is not part of that check).",
        "",
        "| Cause | Cells | Max abs delta, fresh vs stored | Max abs fresh IC where stored 0.0 |",
        "|---|---|---|---|",
    ]
    for name in (REPRODUCED, LEGACY_ZERO, RANK_SCOPE, FLOAT32_NOISE, UNEXPLAINED):
        lines.append(
            f"| {name} | {by_cause[name]} | {max_delta[name]:.3e} | " f"{lost_ic[name]:.3e} |"
        )
    lines += [
        "",
        f"Cells that differ by tf: {json.dumps(differ_by_tf)}.",
        f"The legacy-zero cells are {legacy_zero_all_missing} all-missing columns (no finite value in the "
        f"cell) and {by_cause[LEGACY_ZERO] - legacy_zero_all_missing} partly-missing columns whose "
        "stored IC is 0.0 although a finite IC exists on the valid rows (the last column of the table).",
        f"Stored-NULL handling: {stored_null} stored NULL, {both_null} replayed NaN; "
        f"NULL-pattern mismatches: {len(null_mismatch)}.",
    ]
    for tag, rows in (
        ("NULL mismatches", null_mismatch),
        ("n_independent mismatches", n_mismatch),
        ("missing stored rows", missing),
    ):
        if rows:
            lines.append(f"- First {tag}: " + "; ".join(rows[:10]))
    lines += [
        "",
        "## Kernel-target attribution",
        "",
        "Kernel targets are `panel.forward_returns` on S0 panels built with `end_exclusive = oos_start`, "
        "stacked as the 186-14 writer stacks them; the stride runs over `existing_rows(valid_grid, present)`.",
        "",
        f"- Target rows compared: {agg['rows']}; equal {agg['equal']}; end-of-window {agg['end_of_window']}; "
        f"gap {agg['gap']}; session-crossing {agg['session_cross']}; absent tradeable open "
        f"{agg['open_missing']}; other {agg['other']}. "
        "Session-crossing is an added cause: the kernel refuses an intraday return whose entry and exit "
        "opens sit in different sessions (D-18); the table keeps it. Absent tradeable open is an added "
        "cause too: the kernel's panel is built from `market_data_ohlcv_tradeable` (volume > 0), so an "
        "entry or exit open of a placeholder bar is NaN there while the table priced it.",
        f"- Cells where the kernel row set gives the table's n_independent: {kernel_n_equal} of {len(cells)}.",
        f"- Max |kernel IC - table IC| over cells: {max(kernel_delta) if kernel_delta else float('nan'):.3e}.",
        "- Worst (tf, label, horizon) by differing rows: "
        + "; ".join(
            f"{d.tf}/{d.label}/{d.horizon} eow {d.n_end_of_window} gap {d.n_gap} "
            f"session {d.n_session_cross} open {d.n_open_missing} other {d.n_other} of {d.n_rows}"
            for d in worst
        ),
        "",
        "## Conclusion",
        "",
        f"Row-set parity holds: {n_mismatch_clean} cells whose feature is finite on the strided rows "
        "disagree on n_independent, so the peer set, label bars, stride and target mask rebuild "
        "ic_engine's cells exactly, and the legacy-arithmetic replica reproduces "
        f"{n_legacy_ok} of {len(cells)} stored values within the float32 bound.",
        f"Value parity as written (every sampled cell within tolerance) is NOT met: {n_differ} of "
        f"{len(cells)} cells differ, all attributed. {by_cause[LEGACY_ZERO]} stored ICs are 0.0 where a "
        "feature has a non-finite value among the strided rows (ic_engine's `rankdata` returns NaN for the "
        "column and `_vectorized_ic` maps a NaN denominator to 0.0; the fresh function drops the "
        f"non-finite rows and the finite IC reaches {lost_ic[LEGACY_ZERO]:.3e}); {by_cause[RANK_SCOPE]} "
        "differ because ic_engine ranks X over every strided row before the target mask while the fresh "
        f"function ranks the complete rows (max {max_delta[RANK_SCOPE]:.3e}); {by_cause[FLOAT32_NOISE]} "
        "exceed the committed float32 bound by float32 summation noise (fresh and replica agree).",
        "Owner decision, 2026-10-01: the restated criterion is accepted (the replica reproduces every stored "
        "cell, every fresh-versus-stored difference has a named cause) and `pooled_rank_ic` is not changed. "
        "The differences are defects of the stored legacy values, not of the fresh function, so the "
        "unstratified pooled cell is justified per R-06. Kernel-target differences: "
        f"{agg['end_of_window']} end-of-window, {agg['gap']} gap, {agg['session_cross']} session-crossing "
        f"exits refused by design, {agg['open_missing']} entry or exit opens absent from the tradeable "
        f"panel, {agg['other']} other.",
        "",
        "## Relay for the research lane",
        "",
        "Stored `feature_ic_scores` POOLED rows hold `ic_value` 0.0 for any feature with a non-finite value "
        f"among the strided rows ({by_cause[LEGACY_ZERO]} of the {len(cells)} sampled cells; a finite IC up to "
        f"{lost_ic[LEGACY_ZERO]:.3e} existed on the complete rows). This can only produce false negatives "
        "(a real IC shown as zero), never a false positive. Any research claim that cites a pooled row "
        "should check that the feature is finite across the cell. The table is dropped whole by 186-28.",
        "",
        "## Re-deriving the stored numbers",
        "",
        "```",
        'PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "select count(*) from feature_ic_scores"',
        f"-- {stored_total} at the time of this run",
        "select tf, regime, count(*) from feature_ic_scores where symbol='POOLED' and is_pooled "
        "and regime_scope='cross_sectional' group by 1,2 order by tf, count(*) desc, regime;",
        "select ic_value, n_independent from feature_ic_scores where symbol='POOLED' and is_pooled "
        "and regime_scope='cross_sectional' and tf=:tf and regime=:label and feature_name=:feature "
        "and lookahead_bars=:horizon;",
        "```",
        "",
        "## Writer-path parity cell",
        "",
        WRITER_BEGIN,
        "(not yet computed)",
        WRITER_END,
        "",
    ]
    return "\n".join(lines)


def _group_of(outcome: TfOutcome, label: str) -> str:
    for key in outcome.peer_counts:
        group, lab = key.split("/", 1)
        if lab == label:
            return group
    return "?"


def preserved_writer_block() -> str | None:
    if not REPORT_PATH.exists():
        return None
    text = REPORT_PATH.read_text()
    if WRITER_BEGIN not in text:
        return None
    block = text.split(WRITER_BEGIN, 1)[1].split(WRITER_END, 1)[0]
    return None if "(not yet computed)" in block else block


@pytest.mark.parity
def test_table_targets_reproduce_stored_pooled_cells() -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM feature_ic_scores")
            before = cur.fetchone()[0]
        candidates, counts = candidate_features(conn)
        sample = random.Random(SAMPLE_SEED).sample(candidates, N_FEATURES)
        labels = {tf: sampled_labels(conn, tf) for tf in PAIRS}
        outcomes = {tf: run_tf(conn, tf, sample) for tf in PAIRS}
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM feature_ic_scores")
            after = cur.fetchone()[0]
    assert before == after, "feature_ic_scores changed during a read-only replay"
    report = render_report(sample, counts, outcomes, labels, after)
    kept = preserved_writer_block()
    if kept is not None:
        report = report.replace("\n(not yet computed)\n", kept)
    REPORT_PATH.write_text(report)
    cells = [c for o in outcomes.values() for c in o.cells]
    missing = [m for o in outcomes.values() for m in o.missing_stored]
    assert not missing, f"sampled stored rows missing: {missing[:10]}"
    unexplained = [c for c in cells if cause(c) == UNEXPLAINED]
    assert not unexplained, f"{len(unexplained)} cells differ for no known cause: {unexplained[:3]}"
    n_legacy_ok = sum(legacy_matches(c) for c in cells)
    noise = sum(cause(c) == FLOAT32_NOISE for c in cells)
    assert n_legacy_ok == len(cells) - noise, "the legacy-arithmetic replica misses stored cells"


@pytest.mark.parity
def test_writer_path_cell_matches_the_harness_replay() -> None:
    """One frozen stored pooled cell through ic_measure's own assembly versus the harness replay.

    The writer-side calls are the writer's: `build_target_panels`, `make_tf_context` (its
    `stack_grid`, `map_slots`, `SlotMap.present`), `fetch_long_form`, `ctx.stack`, `scatter_features`
    (what `align_features` composes), `existing_rows`, `observation_rows`, `pooled_rank_ic`. The
    only addition is the cell's label-bar row mask, which the writer's unstratified job lacks."""
    tf = "1d"
    with _connect() as conn:
        candidates, _ = candidate_features(conn)
        sample = random.Random(SAMPLE_SEED).sample(candidates, N_FEATURES)
        harness = run_tf(conn, tf, sample)
        reproduced = [
            c for c in harness.cells if c.horizon == 1 and cause(c) == REPRODUCED and c.table_n > 0
        ]
        cell = max(reproduced, key=lambda c: (c.stored_n, c.feature, c.label))
        params, cfg, oos = measure_params(conn, tf)
        group = cell.group
        bars = label_bars(conn, group, tf, cell.label, oos)
        peers = peer_symbols(conn, group, datetime(2026, 9, 24, 23, 59, tzinfo=UTC))
        start = datetime(1990, 1, 1, tzinfo=UTC)
        keys = fetch_long_form(
            conn, "feature_vectors", tf, peers, start, oos, [cell.feature], 200_000
        )
        used = sorted(set(keys.symbols.tolist()))
        with tempfile.TemporaryDirectory(prefix="parity_writer_") as tmp:
            first = keys.bar_ts.min().astype("datetime64[s]").astype(datetime).replace(tzinfo=UTC)
            paths = asyncio.run(
                build_target_panels(
                    LIVE_DB_URL,
                    Path(tmp),
                    used,
                    tf,
                    first.isoformat(),
                    oos.isoformat(),
                    oos.isoformat(),
                    params,
                )
            )
            panels = [research_panel.load(p) for p in paths]
        ctx = make_tf_context(
            panels, oos.replace(tzinfo=None).isoformat(), keys.bar_ts, keys.symbols
        )
        stack = ctx.stack(1)
        grid_a, _ = scatter_features(ctx.grid, ctx.slots, keys.values)
        grid_b, _ = align_features(ctx.grid, keys.bar_ts, keys.symbols, keys.values)
        assert np.array_equal(grid_a, grid_b, equal_nan=True)
        in_label = np.isin(np.asarray(ctx.grid.timestamps), bars)
        row_mask = existing_rows(stack.valid_grid(), ctx.present) & in_label[:, None]
        x, y = observation_rows(grid_a, stack.targets, row_mask)
        writer = pooled_rank_ic(
            x,
            y,
            stride=target_stride(stack, params),
            params=params,
            feature_names=(cell.feature,),
            bootstrap=False,
        )
    delta = float(writer.ic[0]) - cell.kernel_ic
    verdict = abs(delta) <= STRICT_TOL and int(writer.n_independent[0]) == cell.kernel_n
    key = f"{tf} / {cell.label} (group {group}) / {cell.feature} / horizon {cell.horizon}"
    block = "\n".join(
        [
            f"Frozen stored cell (verbatim): `{key}`; stored ic_value {cell.stored_ic!r}, "
            f"n_independent {cell.stored_n}.",
            "",
            "Production-assembly call sequence (landed signatures): "
            "`build_target_panels(dsn, out_dir, symbols, tf, start, end_exclusive, oos_start, params)` -> "
            "`research_panel.load` -> `make_tf_context(panels, end_exclusive, bar_ts, symbols)` "
            "(`stack_grid`, `map_slots`, `SlotMap.present`) -> `fetch_long_form` for the feature -> "
            "`ctx.stack(horizon)` (`stack_at_horizon`) -> `scatter_features` (checked equal to "
            "`align_features(stack_grid, bar_ts, symbols, values)`) -> "
            "`existing_rows(stack.valid_grid(), ctx.present)` and the cell's label-bar mask -> "
            "`observation_rows` -> `pooled_rank_ic(X, y, stride=max(min_stride, horizon), params)`.",
            "",
            f"- Writer-path value: {float(writer.ic[0])!r} (n_independent {int(writer.n_independent[0])}).",
            f"- Harness kernel replay (`replay_kernel_targets`): {cell.kernel_ic!r} "
            f"(n_independent {cell.kernel_n}).",
            f"- Delta {delta:.3e} against the float64 tolerance {STRICT_TOL:.0e}: "
            f"{'PASS' if verdict else 'FAIL'}.",
            f"- For reference: table-target replay {cell.table_ic!r}; stored {cell.stored_ic!r}.",
            "- Peer-symbol source: labels and peers come from `market_regimes` plus "
            "`alpha.regime.groups` (value `"
            + _regime_groups_value()
            + "`), both confirmed live at this "
            "run. `alpha.regime.groups` must survive 186-21's APR deletion.",
        ]
    )
    text = REPORT_PATH.read_text()
    head, rest = text.split(WRITER_BEGIN, 1)
    tail = rest.split(WRITER_END, 1)[1]
    REPORT_PATH.write_text(head + WRITER_BEGIN + "\n" + block + "\n" + WRITER_END + tail)
    assert verdict, f"writer path {writer.ic[0]!r} vs harness {cell.kernel_ic!r}, delta {delta:.3e}"


def _regime_groups_value() -> str:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT config_value FROM config_state WHERE config_key = 'alpha.regime.groups'"
        )
        value = cur.fetchone()[0]
    return json.dumps(json.loads(value), separators=(",", ":"))[:240] + "..."
