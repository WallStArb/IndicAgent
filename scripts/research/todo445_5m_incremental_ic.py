"""Todo 445: does a 5m-computed feature carry cross-sectional information the same
feature's 15m value does not, at matched clock horizons, net of the personal cost
hurdle? Answers the question before the phase 186 rebuild's timeframe set is fixed
(design section 14.2): 5m holds about 69% of feature_vectors rows and no active
family reads 5m today, so this gates the most expensive part of the rebuild.

Per R-08 (the phase 183 runner has no exploration mode and S0 does not read
feature_vectors), this runs as a committed script, in-sample only, recorded as one
counted look. It is a scoping measurement, not a verdict: no concept_registry row,
no research_run row.

Pre-stated design and decision rule (fixed before any run; D-18, R-08):

- Universe: compute_eligible (233 names).
- Window: 15m S0 panel, start default 2016-01-01, end_exclusive = oos_start read
  from config_state (alpha.validation.oos_start). build_panel refuses anything later.
- Horizons (15m bars, matched clock): 10 (2.5h, 30 5m bars) and 13 (half session,
  39 5m bars). Targets: forward_returns(panel.open, horizon, session=panel.session),
  no closes -- every target is a fixed-length intraday window inside one session;
  a window crossing a session boundary is NaN.
- Alignment: the 15m feature row at bar_ts == panel.timestamps[t] (known at the 15m
  close); the 5m feature row whose bar ends at that same close, i.e. bar_ts = t + 10
  minutes (verified at runtime against bar_close_ts on a live 5m sample). Never the
  5m row with bar_ts = t.
- Feature set: real columns non-null at both 5m and 15m in the window, minus hmm_*,
  canary_*, regime*, text/uuid columns and the nine todo 421 partial-coverage
  columns. A feature whose 5m and 15m cross-sectional ranks agree on over 99% of
  (bar, name) cells is reported as identical_across_tf and not tested.
- Statistic per (feature, horizon): per bar, cross-sectional ranks (0..1) of the 5m
  value, the 15m value and the target over names with all three finite (bars under
  30 names skipped); partial rank IC of the 5m rank on the target rank, controlling
  for the 15m rank (per-bar OLS residualization, residual correlation). Also report
  the plain 5m and 15m ICs. Average bar ICs to one value per session; t = HAC IC
  Sharpe over sessions (Newey-West Bartlett, max_lag 5) times sqrt(sessions);
  two-sided p from the normal. Benjamini-Hochberg at q = 0.05 over every tested
  (feature, horizon) cell.
- Cost: for each BH-significant cell, IC_min over the 2x2 (library rank, breadth)
  grid using the 5m feature's own rank turnover at that horizon on the 15m-close
  grid, bars per year = 252 * 26; the cell clears if the incremental IC magnitude
  exceeds IC_min at the most lenient grid point. Statistics are gross; costs decide
  only (E18).
- Decision: keep_5m if at least one (feature, horizon) cell is BH-significant and
  clears the cost hurdle; the 5m name set is exactly the passing features, and 5m
  features stay at the 233 names that already have them (the 931-name extension is
  a separate decision after todo 449 and the R-09 disk guard). Otherwise drop_5m:
  the rebuild covers 15m, 1h and 1d; raw 5m bars keep ingesting either way.

    .venv/bin/python scripts/research/todo445_5m_incremental_ic.py <out.json>
        [--start 2016-01-01] [--block-size 32] [--workers 6] [--no-record]
        [--features name,name] [--symbols-limit N]

--features and --symbols-limit are debug-only: they must be recorded in the output
and refuse to combine with recording (--no-record required alongside either).

Fetch is a block of --block-size feature columns, one timeframe, streamed via a
single server-side cursor straight into their destination arrays
(fetch_feature_columns) -- never a materialized row list, at any block size.
Three earlier designs conflated two separate questions and got the first one
wrong: an exact-timestamp array bind hit Postgres's 1GB per-value buffer limit;
a whole-block Record list (pool.fetch()) measured 10-19GB RSS for one block of
the real ~283-feature run; a single-column stream fixed the memory question but
was too slow to finish a 48-feature smoke test in 10 minutes (per-row Python
dict-lookup overhead, not memory). Streaming makes "how is a query's result
consumed" a structurally safe non-question at any block size -- peak memory
from a query is one cursor prefetch batch, never the full result. --block-size
is now purely a throughput knob on top of that (N columns cost exactly N x 2
timeframes x ~58MB, a fixed, predictable number), safe to raise or lower
freely. Compute is sequential numpy, not a ProcessPoolExecutor: the fetch stage
(I/O-bound) dominates wall-clock, not compute, and pickling large rank arrays
across a process boundary would be its own version of the same mistake.
--workers is accepted for interface stability but currently unused.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import warnings
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import asyncpg
import numpy as np
from scipy.stats import norm

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config.settings import Settings  # noqa: E402
from src.intelligence.research import panel as panel_mod  # noqa: E402
from src.intelligence.research.snapshot import (  # noqa: E402
    build_panel,
    read_only_pool,
    universe_symbols,
)
from src.intelligence.statistics.ic_math import _hac_sharpe_nd, apply_bh_fdr  # noqa: E402

# ---------------------------------------------------------------------------
# Cost model constants, copied from scripts/analysis/personal_cost_hurdle_by_tf.py
# (0b, validated against live quotes); script constants, not APR keys -- the APR
# mandate (CLAUDE.md) covers src/ and services/, not a one-shot research script.
# ---------------------------------------------------------------------------
_LIVE_SPREAD_ANCHOR = 0.00014  # 1.4bp
_COMMISSION_PER_SHARE = 0.0035
_ASSUMED_PRICE = 50.0
_COMMISSION_FRAC = _COMMISSION_PER_SHARE / _ASSUMED_PRICE
_SIGMA_TARGET = 0.16
_TRADING_DAYS_PER_YEAR = 252
_BARS_PER_SESSION_15M = 26
_LIBRARY_RANKS = (3.0, 10.0)
_UNIVERSE_BREADTHS = (4.5, 8.4)
_BH_ALPHA = 0.05
_IDENTICAL_ACROSS_TF_SHARE = 0.99
_MIN_NAMES_PER_BAR = 30
_HAC_MAX_LAG = 5
_HORIZONS_15M_BARS = (10, 13)
_DEFAULT_START = "2016-01-01"

# feature_vectors columns excluded from the tested feature set: identity/text/uuid
# columns are already dropped by the real-dtype filter below; these are the
# remaining classes that pass the dtype filter but are not eligible feature values.
_EXCLUDED_PREFIXES = ("hmm_", "canary_", "regime")
_EXCLUDED_TODO421_COLUMNS = frozenset(
    {
        "rsi_velocity_fast",
        "rsi_velocity_mid",
        "rsi_velocity_slow",
        "ofi_z_velocity",
        "cvd_slope_z_velocity",
        "volume_z_velocity",
        "momentum_rank_z",
        "volume_rank_z",
        "volatility_rank_z",
    }
)

_OOS_START_SQL = (
    "SELECT config_value::timestamptz FROM config_state "
    "WHERE config_key = 'alpha.validation.oos_start'"
)
_SCHEMA_SQL = (
    "SELECT column_name, data_type FROM information_schema.columns "
    "WHERE table_schema = current_schema() AND table_name = 'feature_vectors' "
    "ORDER BY column_name"
)
_ALIGN_CHECK_SQL = (
    "SELECT bar_close_ts - bar_ts AS gap FROM feature_vectors "
    "WHERE tf = '5m' ORDER BY bar_ts LIMIT 1000"
)
# A block of feature columns, one timeframe, streamed. Three earlier designs
# failed on two DIFFERENT axes that got conflated:
#   (1) HOW a query's result is consumed: pool.fetch() materializes every
#       matching row as a Python Record object before returning -- first an
#       exact-timestamp array bind (hit Postgres's per-value 1GB buffer
#       limit), then a whole-block Record list (measured 10-19GB RSS for one
#       block of the real feature count). Fixed unconditionally by streaming:
#       personal_cost_hurdle_by_tf.py's _fetch_ranks already does this for the
#       same problem shape ("far too many to fetchall" per its own
#       docstring), and fetch_feature_columns below follows the same idiom --
#       `async for row in conn.cursor(...)` inside a transaction never holds
#       more than one prefetch batch, regardless of how many rows match.
#   (2) HOW MANY columns' destination arrays are held at once: a single-column
#       stream (block=1) fixed (1) but was too slow to finish even a 48-
#       feature smoke test in 10 minutes -- per-row Python dict-lookup
#       overhead, not memory, was the cost. This axis is now a plain,
#       precisely predictable throughput knob with NO safety implication at
#       any value: N columns cost exactly N x 2 timeframes x ~58MB
#       ([65234, 233] float32), a fixed number with no hidden multiplier,
#       because (1) already guarantees no intermediate result is ever
#       materialized. --block-size tunes throughput only.
_FEATURE_COLUMNS_SQL_TEMPLATE = (
    "SELECT bar_ts, symbol, {cols} FROM feature_vectors "
    "WHERE tf = $1 AND symbol = ANY($2) AND bar_ts >= $3 AND bar_ts < $4"
)
_CURSOR_PREFETCH = 5000


# ---------------------------------------------------------------------------
# Pure functions (unit tested, no DB)
# ---------------------------------------------------------------------------


def aligned_5m_bar_ts(ts_15m: np.ndarray) -> np.ndarray:
    """The 5m bar whose bar_close_ts equals a 15m slot's close: bar_ts = t + 10
    minutes, never the 5m row with bar_ts = t (that row's close is the slot start,
    not its close -- an N1 lookahead leak)."""
    return ts_15m + np.timedelta64(10, "m")


def feature_columns(schema_rows: list[tuple[str, str]]) -> list[str]:
    """schema_rows: (column_name, data_type) from information_schema.columns for
    feature_vectors. Keeps only real-typed columns (this alone drops every
    identity/text/uuid column), minus hmm_*/canary_*/regime* and the nine todo 421
    partial-coverage columns."""
    out = []
    for name, dtype in schema_rows:
        if dtype != "real":
            continue
        if name.startswith(_EXCLUDED_PREFIXES):
            continue
        if name in _EXCLUDED_TODO421_COLUMNS:
            continue
        out.append(name)
    return sorted(out)


def ranks_by_row(x: np.ndarray) -> np.ndarray:
    """[n, m] -> [n, m] NaN-aware per-row average rank scaled to 0..1. A row with
    fewer than 2 finite values is all-NaN in the output (no cross-section to rank)."""
    from scipy.stats import rankdata

    n, m = x.shape
    out = np.full((n, m), np.nan)
    for i in range(n):
        row = x[i]
        finite = np.isfinite(row)
        cnt = int(finite.sum())
        if cnt < 2:
            continue
        r = rankdata(row[finite])  # 1..cnt, ties get the average rank
        out[i, finite] = (r - 1) / (cnt - 1)
    return out


def partial_rank_ic_per_bar(
    x5: np.ndarray, x15: np.ndarray, y: np.ndarray, min_names: int = _MIN_NAMES_PER_BAR
) -> np.ndarray:
    """x5, x15, y: [n, m] cross-sectional rank arrays (0..1, NaN allowed). Returns
    [n]: per bar, residualize x5's rank and y's rank on x15's rank via closed-form
    per-bar simple OLS (over the names axis), then the Pearson correlation of the
    two residual vectors. NaN for a bar with fewer than min_names names finite in
    all three of x5, x15, y. Fully vectorized over bars; no per-bar Python loop."""
    finite = np.isfinite(x5) & np.isfinite(x15) & np.isfinite(y)
    counts = finite.sum(axis=1)
    valid_bars = counts >= min_names

    x5m = np.where(finite, x5, np.nan)
    x15m = np.where(finite, x15, np.nan)
    ym = np.where(finite, y, np.nan)

    with (
        np.errstate(invalid="ignore", divide="ignore"),
        warnings.catch_warnings(),
    ):
        # An all-excluded bar (every name masked by `finite`) is an expected,
        # already-handled case (valid_bars masks it out below), not a bug --
        # silence numpy's "Mean of empty slice" for it rather than let a
        # hundreds-of-features real run flood stderr with it per bar.
        warnings.simplefilter("ignore", category=RuntimeWarning)
        mean15 = np.nanmean(x15m, axis=1, keepdims=True)
        var15 = np.nanmean((x15m - mean15) ** 2, axis=1, keepdims=True)

        def _residualize(target: np.ndarray) -> np.ndarray:
            meant = np.nanmean(target, axis=1, keepdims=True)
            cov = np.nanmean((target - meant) * (x15m - mean15), axis=1, keepdims=True)
            b = np.where(var15 > 1e-12, cov / var15, 0.0)
            a = meant - b * mean15
            return target - (a + b * x15m)

        r5 = _residualize(x5m)
        ry = _residualize(ym)

        mean_r5 = np.nanmean(r5, axis=1, keepdims=True)
        mean_ry = np.nanmean(ry, axis=1, keepdims=True)
        cov_r = np.nanmean((r5 - mean_r5) * (ry - mean_ry), axis=1)
        std_r5 = np.sqrt(np.nanmean((r5 - mean_r5) ** 2, axis=1))
        std_ry = np.sqrt(np.nanmean((ry - mean_ry) ** 2, axis=1))
        denom = std_r5 * std_ry
        ic = np.where(denom > 1e-12, cov_r / denom, np.nan)

    return np.where(valid_bars, ic, np.nan)


def session_hac_t(
    bar_ics: np.ndarray, session: np.ndarray, max_lag: int = _HAC_MAX_LAG
) -> tuple[float, float, float, int]:
    """bar_ics: [n] per-bar IC (NaN allowed and ignored). session: [n] 0-based
    session index (Panel.session). Returns (mean, t, p, n_sessions): the per-session
    average of the finite bar ICs, HAC IC Sharpe over the session series (Newey-West
    Bartlett, _hac_sharpe_nd), t = sharpe * sqrt(n_sessions), two-sided p from the
    normal. A session with zero finite bars is excluded from n_sessions."""
    if len(session) == 0:
        return float("nan"), float("nan"), float("nan"), 0
    n_sessions_total = int(session.max()) + 1
    sums = np.zeros(n_sessions_total)
    counts = np.zeros(n_sessions_total)
    finite = np.isfinite(bar_ics)
    np.add.at(sums, session[finite], bar_ics[finite])
    np.add.at(counts, session[finite], 1)
    with np.errstate(invalid="ignore"):
        session_means = np.where(counts > 0, sums / counts, np.nan)
    vals = session_means[np.isfinite(session_means)]
    n_sessions = len(vals)
    if n_sessions < 2:
        return float("nan"), float("nan"), float("nan"), n_sessions
    sharpe = float(_hac_sharpe_nd(vals.reshape(-1, 1), max_lag)[0])
    t = sharpe * np.sqrt(n_sessions)
    p = float(2.0 * (1.0 - norm.cdf(abs(t))))
    return float(vals.mean()), float(t), p, n_sessions


def rank_turnover(ranks: np.ndarray, horizon_bars: int) -> float | None:
    """ranks: [n, m] cross-sectional rank array (0..1, NaN allowed) for one feature.
    Mean absolute per-name rank change over horizon_bars, ignoring NaN (same formula
    as personal_cost_hurdle_by_tf.py's _turnover, generic over a numpy array instead
    of a pandas DataFrame). None when too few bars or nothing finite to average."""
    n = ranks.shape[0]
    if n <= horizon_bars + 5:
        return None
    diff = np.abs(ranks[horizon_bars:] - ranks[:-horizon_bars])
    vals = diff[np.isfinite(diff)]
    if len(vals) == 0:
        return None
    return float(vals.mean())


def ic_min(
    turnover: float, horizon_bars: int, bars_per_year: float, lib_rank: float, breadth: float
) -> float:
    """Reproduces personal_cost_hurdle_by_tf.py's 0b formula: one_way = half-spread
    + commission fraction; drag = rebalances/year * 2 * turnover * one_way;
    ic_min = drag / (sigma_target * sqrt(lib_rank * breadth))."""
    one_way = _LIVE_SPREAD_ANCHOR / 2 + _COMMISSION_FRAC
    rebal_per_year = bars_per_year / horizon_bars
    drag = rebal_per_year * 2 * turnover * one_way
    return drag / (_SIGMA_TARGET * np.sqrt(lib_rank * breadth))


def assert_within_oos_start(manifest: dict) -> None:
    """Refuse if the panel manifest's end_exclusive is later than its recorded
    oos_start. Defense in depth: snapshot.build_panel already enforces this at
    fetch time (D-02: it is never re-implemented here), this just fails loudly if
    a manifest reaches this script's compute stage having somehow violated it."""
    end_exclusive = datetime.fromisoformat(manifest["end_exclusive"])
    oos_start = datetime.fromisoformat(manifest["oos_start"])
    if end_exclusive.tzinfo is None:
        end_exclusive = end_exclusive.replace(tzinfo=UTC)
    if oos_start.tzinfo is None:
        oos_start = oos_start.replace(tzinfo=UTC)
    if end_exclusive > oos_start:
        raise ValueError(
            f"panel end_exclusive {manifest['end_exclusive']} is past oos_start "
            f"{manifest['oos_start']}"
        )


def build_targets(
    opens: np.ndarray, session: np.ndarray, horizons: tuple[int, ...]
) -> dict[int, np.ndarray]:
    """Every target: forward_returns(opens, horizon, session=session), a market-on-
    open exit only, no close-exit override -- every target is a fixed-length
    intraday window inside one session; a window crossing a session boundary is
    NaN (D-18)."""
    return {h: panel_mod.forward_returns(opens, horizon=h, session=session) for h in horizons}


def decide(cells: list[dict]) -> tuple[str, list[str]]:
    """cells: dicts with 'feature', 'bh_reject' (bool), 'cost_clears' (bool). keep_5m
    with the sorted, de-duplicated set of features that have at least one cell both
    BH-significant and cost-clearing; drop_5m with an empty set otherwise."""
    passing = sorted({c["feature"] for c in cells if c.get("bh_reject") and c.get("cost_clears")})
    if passing:
        return "keep_5m", passing
    return "drop_5m", []


# ---------------------------------------------------------------------------
# DB layer (async, read-only)
# ---------------------------------------------------------------------------


async def load_schema(pool: asyncpg.Pool) -> list[tuple[str, str]]:
    rows = await pool.fetch(_SCHEMA_SQL)
    return [(r["column_name"], r["data_type"]) for r in rows]


async def check_5m_alignment(pool: asyncpg.Pool) -> None:
    """Refuse to proceed if the live 5m grid does not have a 5-minute bar_ts to
    bar_close_ts gap on a sample -- the alignment this whole measurement depends on."""
    rows = await pool.fetch(_ALIGN_CHECK_SQL)
    bad = [r["gap"] for r in rows if r["gap"] != timedelta(minutes=5)]
    if bad:
        raise SystemExit(
            f"{len(bad)}/{len(rows)} sampled 5m feature_vectors rows have a "
            f"bar_close_ts - bar_ts gap other than 5 minutes; refusing (the 5m/15m "
            f"alignment this measurement depends on does not hold live)"
        )


async def build_target_panel(dsn: str, out_dir: Path, start: str) -> tuple[panel_mod.Panel, str]:
    pool = await read_only_pool(dsn)
    try:
        oos_start = await pool.fetchval(_OOS_START_SQL)
    finally:
        await pool.close()
    if oos_start is None:
        raise SystemExit("alpha.validation.oos_start is not set in config_state")
    symbols = await universe_symbols(dsn, "compute_eligible")
    path = await build_panel(
        dsn,
        out_dir,
        symbols=symbols,
        tf="15m",
        start=start,
        end_exclusive=oos_start.isoformat(),
        manifest_extra={"universe_dimension": "compute_eligible"},
    )
    return panel_mod.load(path), oos_start.isoformat()


def _chunk(seq: list, size: int) -> list[list]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


async def fetch_feature_columns(
    conn: asyncpg.Connection,
    tf: str,
    columns: list[str],
    symbols: list[str],
    timestamps: list[datetime],
    ts_index: dict[datetime, int],
    oos_start: datetime,
) -> dict[str, np.ndarray]:
    """A block of feature columns, one timeframe: one preallocated float32
    [n, m] array per column, filled by streaming a SINGLE server-side cursor
    row by row -- never a materialized Record list, regardless of block size
    (see the module comment above _FEATURE_COLUMNS_SQL_TEMPLATE). Peak memory
    is exactly len(columns) destination arrays plus one _CURSOR_PREFETCH
    batch, a fixed and precisely predictable cost. Caller must hold `conn`
    inside a single connection for the run (a server-side cursor needs a
    transaction, which read_only_pool's autocommit connections don't provide
    directly)."""
    n, m = len(timestamps), len(symbols)
    out = {col: np.full((n, m), np.nan, dtype=np.float32) for col in columns}
    sym_idx = {s: j for j, s in enumerate(symbols)}
    lo, hi = min(timestamps), min(max(timestamps) + timedelta(minutes=1), oos_start)
    cols_sql = ", ".join(columns)
    sql = _FEATURE_COLUMNS_SQL_TEMPLATE.format(cols=cols_sql)
    async with conn.transaction():
        async for row in conn.cursor(sql, tf, symbols, lo, hi, prefetch=_CURSOR_PREFETCH):
            t = ts_index.get(row["bar_ts"])
            j = sym_idx.get(row["symbol"])
            if t is None or j is None:
                continue
            for col in columns:
                val = row[col]
                if val is not None:
                    out[col][t, j] = val
    return out


# ---------------------------------------------------------------------------
# Compute (may run in a worker pool; workers return small dicts, no DB writes)
# ---------------------------------------------------------------------------


def _plain_ic_series(x: np.ndarray, y: np.ndarray, min_names: int) -> np.ndarray:
    """[n]: per-bar plain cross-sectional IC of x on y, NaN for a bar with fewer
    than min_names names finite in x (both 1-D outputs -- no keepdims broadcast
    against _row_ic's [n] result, which produced a silent [n, n] blow-up here
    once)."""
    counts = np.isfinite(x).sum(axis=1)
    return np.where(counts >= min_names, _row_ic(x, y), np.nan)


def _compute_cell(args: tuple) -> dict:
    feature, horizon, x5_ranks, x15_ranks, y_ranks, session, bars_per_year, x5_raw_ranks = args
    plain_5m_mean, plain_5m_t, plain_5m_p, _ = session_hac_t(
        _plain_ic_series(x5_ranks, y_ranks, _MIN_NAMES_PER_BAR), session
    )
    plain_15m_mean, plain_15m_t, plain_15m_p, _ = session_hac_t(
        _plain_ic_series(x15_ranks, y_ranks, _MIN_NAMES_PER_BAR), session
    )
    partial_ic_bar = partial_rank_ic_per_bar(x5_ranks, x15_ranks, y_ranks)
    partial_mean, partial_t, partial_p, n_sessions = session_hac_t(partial_ic_bar, session)
    turnover = rank_turnover(x5_raw_ranks, horizon)
    return {
        "feature": feature,
        "horizon": horizon,
        "plain_5m_ic": plain_5m_mean,
        "plain_5m_t": plain_5m_t,
        "plain_15m_ic": plain_15m_mean,
        "plain_15m_t": plain_15m_t,
        "partial_ic": partial_mean,
        "partial_t": partial_t,
        "partial_p": partial_p,
        "n_sessions": n_sessions,
        "turnover": turnover,
    }


def _row_ic(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Per-bar plain cross-sectional Pearson IC between two rank arrays. Callers
    mask an all-NaN row's result via _plain_ic_series's min_names count, same
    expected-empty-slice case as partial_rank_ic_per_bar."""
    with (
        np.errstate(invalid="ignore", divide="ignore"),
        warnings.catch_warnings(),
    ):
        warnings.simplefilter("ignore", category=RuntimeWarning)
        mean_x = np.nanmean(x, axis=1, keepdims=True)
        mean_y = np.nanmean(y, axis=1, keepdims=True)
        cov = np.nanmean((x - mean_x) * (y - mean_y), axis=1)
        std_x = np.sqrt(np.nanmean((x - mean_x) ** 2, axis=1))
        std_y = np.sqrt(np.nanmean((y - mean_y) ** 2, axis=1))
        denom = std_x * std_y
        return np.where(denom > 1e-12, cov / denom, np.nan)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _sha256_of(text: str) -> str:
    return sha256(text.encode()).hexdigest()


async def _run(args: argparse.Namespace) -> dict:
    dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    out_dir = Path("logs/todo445/panels")
    out_dir.mkdir(parents=True, exist_ok=True)

    panel, oos_start = await build_target_panel(dsn, out_dir, args.start)
    assert_within_oos_start(panel.manifest)
    if args.symbols_limit:
        symbols = panel.symbols[: args.symbols_limit]
    else:
        symbols = panel.symbols
    sym_idx = [panel.symbols.index(s) for s in symbols]

    schema_pool = await read_only_pool(dsn)
    try:
        schema_rows = await load_schema(schema_pool)
        await check_5m_alignment(schema_pool)
    finally:
        await schema_pool.close()

    columns = feature_columns(schema_rows)
    if args.features:
        wanted = set(args.features.split(","))
        columns = [c for c in columns if c in wanted]

    ts_utc = [
        datetime.fromtimestamp(t.astype("datetime64[s]").astype(int), tz=UTC)
        for t in panel.timestamps
    ]
    aligned_5m = [
        datetime.fromtimestamp(t.astype("datetime64[s]").astype(int), tz=UTC)
        for t in aligned_5m_bar_ts(panel.timestamps)
    ]
    oos_start_dt = datetime.fromisoformat(oos_start)
    ts_index_15m = {t: i for i, t in enumerate(ts_utc)}
    ts_index_5m = {t: i for i, t in enumerate(aligned_5m)}

    opens = panel.open[:, sym_idx]
    session = panel.session
    horizons = _HORIZONS_15M_BARS
    bars_per_year = _TRADING_DAYS_PER_YEAR * _BARS_PER_SESSION_15M

    targets = build_targets(opens, session, horizons)
    y_ranks_by_h = {h: ranks_by_row(targets[h]) for h in horizons}

    # Streamed, in blocks of args.block_size columns (fetch_feature_columns):
    # streaming makes memory safety unconditional (no materialized result at
    # any block size); block size is a pure throughput knob on top of that,
    # since a single-column stream measured too slow to finish a 48-feature
    # smoke test in 10 minutes (per-row Python dict-lookup overhead, not
    # memory). Compute stays sequential -- no ProcessPoolExecutor: a worker
    # task would need to pickle a pair of [65234, 233] float64 rank arrays
    # (~121MB each) across a process boundary, and the fetch stage (I/O-bound)
    # dominates wall-clock, not compute, so parallelizing compute buys little
    # while adding a real memory-copy cost. --workers is accepted but unused;
    # kept for CLI stability if this is revisited.
    identical_across_tf: list[str] = []
    tested_cells: list[dict] = []
    fetch_pool = await read_only_pool(dsn)
    try:
        async with fetch_pool.acquire() as conn:
            for col_block in _chunk(columns, args.block_size):
                arrays_5m = await fetch_feature_columns(
                    conn, "5m", col_block, list(symbols), aligned_5m, ts_index_5m, oos_start_dt
                )
                arrays_15m = await fetch_feature_columns(
                    conn, "15m", col_block, list(symbols), ts_utc, ts_index_15m, oos_start_dt
                )
                for col in col_block:
                    x5_ranks = ranks_by_row(arrays_5m[col])
                    x15_ranks = ranks_by_row(arrays_15m[col])
                    both_finite = np.isfinite(x5_ranks) & np.isfinite(x15_ranks)
                    agree = (
                        np.isclose(x5_ranks, x15_ranks, atol=1e-9)[both_finite].mean()
                        if both_finite.sum() > 0
                        else 0.0
                    )
                    if agree > _IDENTICAL_ACROSS_TF_SHARE:
                        identical_across_tf.append(col)
                        continue
                    for h in horizons:
                        tested_cells.append(
                            _compute_cell(
                                (
                                    col,
                                    h,
                                    x5_ranks,
                                    x15_ranks,
                                    y_ranks_by_h[h],
                                    session,
                                    bars_per_year,
                                    x5_ranks,
                                )
                            )
                        )
                del arrays_15m, arrays_5m
    finally:
        await fetch_pool.close()

    p_values = [c["partial_p"] for c in tested_cells]
    if p_values:
        reject, p_corrected = apply_bh_fdr(p_values, _BH_ALPHA)
    else:
        reject, p_corrected = np.array([], dtype=bool), np.array([], dtype=float)

    cost_cells = []
    for cell, bh_reject, p_corr in zip(tested_cells, reject, p_corrected):
        cell = dict(cell)
        cell["bh_reject"] = bool(bh_reject)
        cell["bh_p_corrected"] = float(p_corr)
        margins = []
        cost_clears = False
        if bh_reject and cell["turnover"] is not None:
            for lib_rank in _LIBRARY_RANKS:
                for breadth in _UNIVERSE_BREADTHS:
                    im = ic_min(cell["turnover"], cell["horizon"], bars_per_year, lib_rank, breadth)
                    margins.append(im)
                    if abs(cell["partial_ic"]) > im:
                        cost_clears = True
        cell["cost_clears"] = cost_clears
        cell["ic_min_grid"] = margins
        cost_cells.append(cell)

    decision, name_set = decide(cost_cells)

    result = {
        "run_ts": datetime.now(UTC).isoformat(),
        "window": {"start": args.start, "end_exclusive": oos_start},
        "oos_start": oos_start,
        "panel_manifest": panel.manifest,
        "universe": "compute_eligible",
        "symbol_count": len(symbols),
        "horizons": list(horizons),
        "design_constants": {
            "spread_anchor": _LIVE_SPREAD_ANCHOR,
            "commission_per_share": _COMMISSION_PER_SHARE,
            "assumed_price": _ASSUMED_PRICE,
            "sigma_target": _SIGMA_TARGET,
            "library_ranks": list(_LIBRARY_RANKS),
            "universe_breadths": list(_UNIVERSE_BREADTHS),
            "bh_alpha": _BH_ALPHA,
            "bars_per_year": bars_per_year,
        },
        "excluded_columns": {
            "hmm_canary_regime_prefix": sorted(
                c
                for c, dtype in schema_rows
                if dtype == "real" and c.startswith(_EXCLUDED_PREFIXES)
            ),
            "todo421": sorted(_EXCLUDED_TODO421_COLUMNS),
        },
        "identical_across_tf": identical_across_tf,
        "n_features_tested": len(columns) - len(identical_across_tf),
        "cells": cost_cells,
        "decision": decision,
        "name_set_5m": name_set,
        "debug_features": args.features,
        "debug_symbols_limit": args.symbols_limit,
    }
    return result


def _write_look_log(result: dict, sql_hashes: dict) -> None:
    line = {
        "run_ts": result["run_ts"],
        "gate_id": "todo445_5m_incremental_ic_over_15m",
        "snapshot": {
            "oos_start": result["oos_start"],
            "apr_values_used": result["design_constants"],
            "input_population_row_count": result["symbol_count"],
            "fetch_sql_sha256": sql_hashes,
            "panel_hash": result["panel_manifest"].get("dropped_off_grid_bars"),
            "window": result["window"],
            "n_features_tested": result["n_features_tested"],
        },
        "result": result["decision"],
        "note": (
            "scoping measurement, not a verdict; phase 187 imports it as an "
            "exploration attempt (R-08)"
        ),
    }
    with open(".planning/gate_look_log.jsonl", "a") as f:
        f.write(json.dumps(line) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out")
    parser.add_argument("--start", default=_DEFAULT_START)
    parser.add_argument(
        "--block-size",
        type=int,
        default=32,
        help="feature columns per streamed cursor query; throughput only, no memory-safety effect at any value",
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--no-record", action="store_true")
    parser.add_argument("--features", default=None, help="debug: comma-separated feature names")
    parser.add_argument("--symbols-limit", type=int, default=None, help="debug: first N symbols")
    args = parser.parse_args()

    if (args.features or args.symbols_limit) and not args.no_record:
        raise SystemExit("--features/--symbols-limit must be combined with --no-record")

    start_wall = time.monotonic()
    result = asyncio.run(_run(args))
    result["wall_clock_seconds"] = time.monotonic() - start_wall

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2, default=str)

    if not args.no_record:
        sql_hashes = {
            "feature_columns": _sha256_of(_FEATURE_COLUMNS_SQL_TEMPLATE),
            "align_check": _sha256_of(_ALIGN_CHECK_SQL),
        }
        _write_look_log(result, sql_hashes)

    print(f"decision={result['decision']} cells={len(result['cells'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
