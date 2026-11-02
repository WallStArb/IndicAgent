"""Reproduce the regime HMM walk-forward for chosen names, timeframes and component counts, and
report how many segments the occupation gate refuses (todo 583).

It calls the rebuild's own entry (`compute_regime_columns`) on bars from
`market_data_ohlcv_tradeable`, dropping bars after --end and fitting on all earlier history, so
a run reproduces what the rebuild writes on those bars (stored coverage matched exactly on six
names, 2026-11-02, with --end at the stage panel end). Nothing is written to the database. `--n-components` overrides the family's APR
component count so the same names can be compared across K.

`--stored` (which implies --within-panel, and assumes the stored K is the current APR K) reads
what the rebuild already stored in feature_vectors_v2 (the family's regime column
non-null = segment written) and lays the same segments over the bars without fitting, so the
stored K arm costs one query per name; `--summarize` checks stored against computed where both
exist and prefers stored in the table, naming the source of each cell.

Per (symbol, tf, K) one JSON line is appended to --out; rerunning the same command resumes, skipping
cells already recorded without an error. `--summarize FILE ...` aggregates lines
into one row per (tf, K): the refused-segment share, the share of modeled names with zero output,
the median written share, and the K the decision rule picks per timeframe (lowest refused share;
among K within TIE_PP percentage points of the best, the smallest; fixed 2026-11-02, todo 583).

The sibling scripts/infrastructure/features_regime_kernel_coverage_sweep.py sweeps HmmConfig
schedule fields over many names with worker processes and classifies cells; this script is the
K-per-timeframe instrument (per-name zero-output and written shares, seeded name samples, the
decision rule) and is the place to fold into that sweep once K is an APR schedule.

Run: .venv/bin/python scripts/ops/ops_hmm_refusal_screen.py --tf 1d --n-components 3 4 5
         --symbols-file names.txt [--sample 100 --seed 20261102] [--shard 0/3] --out run.jsonl
     .venv/bin/python scripts/ops/ops_hmm_refusal_screen.py --summarize run_*.jsonl
"""

from __future__ import annotations

import argparse
import bisect
import dataclasses
import json
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import psycopg
from psycopg import sql

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from services._batch_utils import load_config_service_sync  # noqa: E402
from services.regime_writer import _fetch_bars  # noqa: E402
from src.config.settings import get_settings  # noqa: E402
from src.intelligence.features.kernels._hmm import (  # noqa: E402
    EVENT_CONVERGENCE,
    EVENT_SEGMENT_SKIPPED,
    FAMILY_SPECS,
    STATUS_WRITTEN,
    HmmConfig,
    RegimeFamilySpec,
    load_rolling_block_rows,
)
from src.intelligence.features.kernels.regime import (  # noqa: E402
    _finite_prefix_rows,
    compute_regime_columns,
)

DEFAULT_END = "2026-09-30"
TIE_PP = 2.0


def summarize_run(status: np.ndarray, events: list, from_row: int = 0) -> dict:
    """One name's counts from the kernel's per-row segment status and its events. A segment is
    one convergence event, or one skipped event with reason fit_failed (no fit ran). With
    `from_row`, only segments whose first row is at or after it count, and so do the rows from the
    first of them on (the rows a stored panel can hold); a segment's first row is its seg_start
    plus the offset of the first modeled row over the first boundary."""
    skipped = [e.fields for e in events if e.kind == EVENT_SEGMENT_SKIPPED]
    fits = [e.fields for e in events if e.kind == EVENT_CONVERGENCE]
    modeled_rows = np.flatnonzero(status != 0.0)  # rows at or after the first model
    offset = 0
    if len(modeled_rows) and (skipped or fits):
        offset = int(modeled_rows[0]) - min(e["seg_start"] for e in skipped + fits)
    skipped = [e for e in skipped if offset + e["seg_start"] >= from_row]
    fits = [e for e in fits if offset + e["seg_start"] >= from_row]
    counted = skipped + fits
    start = offset + min(e["seg_start"] for e in counted) if counted else len(status)
    window = status[start:]  # rows from the first counted segment, so rows match segments
    return {
        "n": len(status),
        "modeled": int(np.count_nonzero(window != 0.0)),
        "written": int(np.count_nonzero(window == STATUS_WRITTEN)),
        "segments": len(fits) + sum(1 for s in skipped if s.get("reason") == "fit_failed"),
        "refused": len(skipped),
        "reasons": dict(Counter(s.get("reason") for s in skipped)),
        "hit_cap": sum(1 for f in fits if f["iters_used"] >= f["n_iter_cap"]),
    }


def segment_layout(n_obs: int, boundary: int, refit: int) -> list[tuple[int, int]]:
    """The walk-forward's [start, end) observation ranges: the first boundary, then one segment
    every `refit` observations to the end of the series (`_walk_forward_hmm_full`)."""
    layout = []
    while boundary < n_obs:
        end = min(boundary + refit, n_obs)
        layout.append((boundary, end))
        boundary = end
    return layout


def summarize_stored(
    timestamps: list,
    stored_ts: set,
    n_obs: int,
    offset: int,
    boundary: int,
    refit: int,
    from_row: int = 0,
) -> dict:
    """summarize_run's fields for the stored arm. Observation j is bar row `offset + j`; a
    segment was written when its first row has stored output (segments are written whole).
    With `from_row`, segments starting before it are outside the stored panel and not counted,
    and rows count from the first counted segment, as in summarize_run."""
    layout = [
        (start, end)
        for start, end in segment_layout(n_obs, boundary, refit)
        if offset + start >= from_row
    ]
    rows = timestamps[offset + layout[0][0] : offset + n_obs] if layout else []
    refused = sum(1 for start, _ in layout if timestamps[offset + start] not in stored_ts)
    return {
        "n": len(timestamps),
        "modeled": len(rows),
        "written": sum(1 for t in rows if t in stored_ts),
        "segments": len(layout),
        "refused": refused,
        "reasons": {"stored_null": refused} if refused else {},
        "hit_cap": 0,
    }


def aggregate(records: list[dict]) -> list[dict]:
    """One row per (tf, K): refused-segment share, zero-output share and median written share
    over the names that have a model (modeled > 0)."""
    cells: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for record in records:
        cells[(record["tf"], record["k"])].append(record)
    rows = []
    for (tf, k), cell in sorted(cells.items()):
        segments = sum(r["segments"] for r in cell)
        modeled = [r for r in cell if r["modeled"] > 0]
        row = {
            "tf": tf,
            "k": k,
            "names": len(cell),
            "names_modeled": len(modeled),
            "segments": segments,
            "refused_share": sum(r["refused"] for r in cell) / segments if segments else None,
            "zero_output_share": None,
            "median_written_share": None,
            "hit_cap": sum(r["hit_cap"] for r in cell),
            "sources": sorted({r.get("source", "computed") for r in cell}),
        }
        if modeled:
            row["zero_output_share"] = sum(1 for r in modeled if r["written"] == 0) / len(modeled)
            row["median_written_share"] = statistics.median(
                r["written"] / r["modeled"] for r in modeled
            )
        rows.append(row)
    return rows


def decide(rows: list[dict]) -> dict[str, int]:
    """Per timeframe, the smallest K whose refused share is within TIE_PP percentage points of
    the lowest share on that timeframe."""
    chosen: dict[str, int] = {}
    for tf in sorted({r["tf"] for r in rows}):
        scored = [r for r in rows if r["tf"] == tf and r["refused_share"] is not None]
        if scored:
            best = min(r["refused_share"] for r in scored)
            chosen[tf] = min(
                r["k"] for r in scored if round((r["refused_share"] - best) * 100, 9) <= TIE_PP
            )
    return chosen


def _names(args: argparse.Namespace) -> list[str]:
    names = list(args.symbols or [])
    if args.symbols_file:
        names += [
            ln.strip() for ln in Path(args.symbols_file).read_text().splitlines() if ln.strip()
        ]
    names = sorted(set(names))
    if args.sample is not None:
        if not 0 < args.sample <= len(names):
            raise SystemExit(f"--sample {args.sample} needs 0 < n <= {len(names)} names")
        names = sorted(random.Random(args.seed).sample(names, args.sample))
    try:
        index, count = (int(x) for x in args.shard.split("/"))
    except ValueError:
        raise SystemExit(f"--shard must be i/n, got {args.shard!r}") from None
    if not 0 <= index < count:
        raise SystemExit(f"--shard must be i/n with 0 <= i < n, got {args.shard}")
    return names[index::count]


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{100 * value:.1f}"


def _panel_from_row(conn: psycopg.Connection, symbol: str, tf: str, timestamps: list) -> int:
    """Index of the first bar at or after the name's first stored feature row."""
    first = conn.execute(
        "SELECT min(bar_ts) FROM feature_vectors_v2 WHERE symbol = %s AND tf = %s", (symbol, tf)
    ).fetchone()[0]
    return 0 if first is None else bisect.bisect_left(timestamps, first)


def _stored_record(
    conn: psycopg.Connection,
    spec: RegimeFamilySpec,
    params: HmmConfig,
    tf: str,
    symbol: str,
    series: dict,
    block_rows: int,
    from_row: int,
) -> dict:
    """The stored arm for one name: the segments the rebuild would lay out over these bars, each
    counted written when its first row has stored output in feature_vectors_v2."""
    close, volume = series["close"], series["volume"]
    prefix = _finite_prefix_rows(close, volume) if spec.needs_volume else _finite_prefix_rows(close)
    obs, valid_start = spec.build_observations(
        close[:prefix], volume[:prefix] if spec.needs_volume else volume, params, block_rows
    )
    refit, warmup = params.walk_forward_schedule(tf)
    boundary = max(warmup, spec.model_fields(params)[0] * params.hmm_min_obs_factor)
    query = sql.SQL(
        "SELECT bar_ts FROM feature_vectors_v2 WHERE symbol = %s AND tf = %s AND {} IS NOT NULL"
    ).format(sql.Identifier(spec.regime_column))
    stored_ts = {row[0] for row in conn.execute(query, (symbol, tf))}
    if stored_ts and stored_ts.isdisjoint(series["timestamps"]):
        raise ValueError(f"{symbol} {tf}: stored bar_ts values match none of the bar timestamps")
    # observation j is bar row valid_start + j + 1 (the log return's row)
    return summarize_stored(
        series["timestamps"], stored_ts, len(obs), valid_start + 1, boundary, refit, from_row
    )


def _cell_key(record: dict) -> tuple:
    return (
        record["symbol"],
        record["tf"],
        record["family"],
        record["k"],
        record.get("source", "computed"),
    )


def _read_records(paths: list[str]) -> tuple[list[dict], int]:
    """Records of the JSONL files, the last line per (symbol, tf, family, k, source) winning (a resumed
    shard appends again), and the count of unreadable lines (a run killed mid-write)."""
    latest: dict[tuple, dict] = {}
    unreadable = 0
    for path in paths:
        for line in Path(path).read_text().splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                unreadable += 1
                continue
            latest[_cell_key(record)] = record
    return list(latest.values()), unreadable


CHECKED_FIELDS = ("modeled", "written", "segments", "refused")


def _prefer_stored(records: list[dict]) -> list[dict]:
    """One record per (symbol, tf, family, k): the stored arm where it exists and agrees with the
    computed arm (or there is none to check against), else the computed record. Prints the
    agreement; a stored cell is only as good as the K values it was checked against."""
    by_cell: dict[tuple, dict[str, dict]] = defaultdict(dict)
    for r in records:
        by_cell[_cell_key(r)[:4]][r.get("source", "computed")] = r
    chosen, pairs, bad = [], 0, []
    for key, cell in by_cell.items():
        stored, computed = cell.get("stored"), cell.get("computed")
        if stored and computed:
            pairs += 1
            if any(stored[f] != computed[f] for f in CHECKED_FIELDS):
                bad.append((key[0], key[1], key[3]))
                stored = None
        chosen.append(stored or computed)
    if pairs:
        print(
            f"stored vs computed: {pairs} pairs, {pairs - len(bad)} identical; "
            f"differing (computed used): {bad}"
        )
    return chosen


def _summarize(paths: list[str]) -> None:
    records, unreadable = _read_records(paths)
    errors = [r for r in records if "error" in r]
    records = [r for r in records if "error" not in r]
    records = _prefer_stored(records)
    print(f"decision rule: lowest refused share; smallest K within {TIE_PP} points of it")
    if unreadable or errors:
        print(f"WARNING: {unreadable} unreadable lines, {len(errors)} name fits errored (excluded)")
    for family in sorted({r["family"] for r in records}):
        mine = [r for r in records if r["family"] == family]
        names_by_cell = defaultdict(set)
        for r in mine:
            names_by_cell[(r["tf"], r["k"])].add(r["symbol"])
        for tf in sorted({tf for tf, _ in names_by_cell}):
            if len({frozenset(v) for (t, _), v in names_by_cell.items() if t == tf}) > 1:
                print(
                    f"WARNING: {family} {tf}: K cells cover different names; shares not comparable"
                )
        rows = aggregate(mine)
        print(f"family {family}")
        print("tf  K  names modeled segments refused% zero_out% median_written% hit_cap source")
        for r in rows:
            print(
                f"{r['tf']:<3} {r['k']}  {r['names']:>5} {r['names_modeled']:>7} {r['segments']:>8} "
                f"{_pct(r['refused_share']):>8} {_pct(r['zero_output_share']):>9} "
                f"{_pct(r['median_written_share']):>15} {r['hit_cap']:>7} {'+'.join(r['sources'])}"
            )
        print("chosen K per timeframe:", decide(rows))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tf", default="1d")
    parser.add_argument("--family", default="trend", choices=sorted(FAMILY_SPECS))
    parser.add_argument("--n-components", type=int, nargs="+", help="K values (default: APR)")
    parser.add_argument("--symbols", nargs="+")
    parser.add_argument("--symbols-file", help="one symbol per line")
    parser.add_argument("--sample", type=int, help="draw this many names from the list, seeded")
    parser.add_argument("--seed", type=int, default=20261102)
    parser.add_argument("--shard", default="0/1", help="i/n: take every n-th name from i")
    parser.add_argument("--end", default=DEFAULT_END, help="last bar date used")
    parser.add_argument("--out", help="JSONL file appended per (symbol, K)")
    parser.add_argument("--stored", action="store_true", help="read stored output, no fit")
    parser.add_argument(
        "--within-panel",
        action="store_true",
        help="count only segments starting at or after the name's first stored feature row",
    )
    parser.add_argument("--summarize", nargs="+", metavar="JSONL")
    args = parser.parse_args(argv)

    if args.n_components and (
        min(args.n_components) < 2 or len(set(args.n_components)) != len(args.n_components)
    ):
        parser.error("--n-components needs distinct values of at least 2")
    args.within_panel = args.within_panel or args.stored  # stored rows exist only inside the panel
    if args.stored and args.n_components:
        parser.error("--stored reads the stored K; do not combine it with --n-components")
    if args.summarize:
        _summarize(args.summarize)
        return 0
    names = _names(args)
    if not names or not args.out:
        parser.error("give names (--symbols/--symbols-file) and --out")

    spec = FAMILY_SPECS[args.family]
    cutoff = datetime.combine(
        date.fromisoformat(args.end) + timedelta(days=1), datetime.min.time(), UTC
    )
    k_field = f"{spec.config_prefix}_n_components"
    out_path = Path(args.out)
    previous = _read_records([str(out_path)])[0] if out_path.exists() else []
    source = "stored" if args.stored else "computed"
    done = {_cell_key(r) for r in previous if "error" not in r}
    with psycopg.connect(get_settings().database_url) as conn, open(out_path, "a") as out:
        cfg = load_config_service_sync(conn)
        params = HmmConfig.from_values(cfg.get_sync)
        block_rows = load_rolling_block_rows(cfg.get_sync)
        apr_k = spec.model_fields(params)[0]
        ks = [apr_k] if args.stored else args.n_components or [apr_k]
        for symbol in names:
            todo = [k for k in ks if (symbol, args.tf, args.family, k, source) not in done]
            if not todo:
                continue
            try:
                bars = _fetch_bars(conn, symbol, args.tf, with_volume=spec.needs_volume)
            except psycopg.Error as error:
                conn.rollback()
                print(f"{symbol}: bar fetch failed ({error}), skipped", file=sys.stderr)
                continue
            if bars is None:
                print(f"{symbol}: no bars, skipped", file=sys.stderr)
                continue
            # Bars are time ordered, so the cut after --end is a binary search.
            cut = bisect.bisect_left(bars["timestamps"], cutoff)
            if cut == 0:
                print(f"{symbol}: no bars on or before --end, skipped", file=sys.stderr)
                continue
            close = bars["close"][:cut].copy()  # copies, so the full-length arrays are freed
            volume = bars["volume"][:cut].copy() if bars["volume"] is not None else None
            series = {
                "close": close,
                "volume": volume,
                "timestamps": bars["timestamps"][:cut],
            }
            del bars
            from_row = (
                _panel_from_row(conn, symbol, args.tf, series["timestamps"])
                if args.within_panel
                else 0
            )
            for k in todo:
                started = time.time()
                record = {
                    "symbol": symbol,
                    "tf": args.tf,
                    "family": args.family,
                    "k": k,
                    "source": source,
                }
                try:
                    if args.stored:
                        record |= _stored_record(
                            conn,
                            spec,
                            params,
                            args.tf,
                            symbol,
                            series,
                            block_rows,
                            from_row,
                        )
                    else:
                        columns, events = compute_regime_columns(
                            close,
                            volume,
                            dataclasses.replace(params, **{k_field: k}),
                            args.tf,
                            spec,
                            block_rows,
                        )
                        record |= summarize_run(columns[spec.status_output], events, from_row)
                except Exception as error:  # one name must not end a sweep; the summary counts it
                    record["error"] = f"{type(error).__name__}: {error}"
                record["secs"] = round(time.time() - started, 1)
                out.write(json.dumps(record, sort_keys=True) + "\n")
                out.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
