"""Read-only coverage sweep of the walk-forward HMM regime kernels over stored bars (186-18).

For each (symbol, tf, family) cell the sweep reads the bars from `market_data_ohlcv_tradeable`,
runs the regime kernels through the registry (`compute_kernels`, code and segment status outputs
only) and reports how many refit segments were written, degenerate, not converged or gated for
another reason. It reads no returns, so it adds nothing to any vintage count, and it writes
nothing to the database: the only output is one JSON report.

Used for todo 341 (why five symbols have no regime label at all: classify each cell) and todo 289
(which `hmm_refit_every_bars_1d` gives the fewest skipped segments). Parameters come from APR
through `HmmConfig.from_values`; `--override field=value` and `--sweep field=v1,v2` replace
`HmmConfig` fields for a run (an unknown field raises), so a candidate schedule is measured
without touching APR.

Usage:
    python scripts/infrastructure/features_regime_kernel_coverage_sweep.py \
        --symbols BIL ETHA --tfs 1d --families trend volatility --out report.json
    python scripts/infrastructure/features_regime_kernel_coverage_sweep.py \
        --symbols @compute_eligible_1d --tfs 1d --sweep hmm_refit_every_bars_1d=126,252,504 \
        --workers 6 --out report.json
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import itertools
import json
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, Future, wait
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.intelligence.features.kernels._hmm import (  # noqa: E402
    EVENT_SEGMENT_SKIPPED,
    FAMILY_SPECS,
    STATUS_DEGENERATE_OCCUPATION,
    STATUS_NO_MODEL,
    STATUS_NOT_CONVERGED,
    STATUS_WRITTEN,
    WALK_FORWARD_TIMEFRAMES,
    HmmConfig,
)

FAMILIES = ("trend", "volatility")
UNIVERSE_1D = "@compute_eligible_1d"

# cell classes of todo 341, decided by `classify_cell` (the rule was written before the run)
CLASS_HISTORY_SHORT = "a_history_short"
CLASS_DEGENERATE = "b_degenerate"
CLASS_NOT_CONVERGED = "c_not_converged"
CLASS_LABELS_UNDER_KERNEL = "d_labels_under_kernel"
CLASS_DEFECT = "e_other_or_error"


def summarize_segments(segment_status: np.ndarray, refit_every_bars: int) -> dict[str, Any]:
    """Segment counts of one cell from its per-row `segment_status`.

    Segments start at the first row with a status above 0 and every `refit_every_bars` rows after
    it (the last one may be shorter), as `_walk_forward_hmm_full` lays them out. Returns counts per
    status (keys "1".."4"), `attempted` (segments with a status of 1 to 4), `skip_fraction`
    ((2 + 3 + 4) / attempted, None when nothing was attempted), `labeled_rows` (rows of written
    segments) and `first_labeled_row` (None when no segment was written). A NaN status is a row
    with no model.
    """
    if refit_every_bars < 1:
        raise ValueError(f"refit_every_bars must be >= 1, got {refit_every_bars}")
    status = np.nan_to_num(np.asarray(segment_status, dtype=float), nan=STATUS_NO_MODEL)
    counts = {str(code): 0 for code in (1, 2, 3, 4)}
    attempted_rows = np.flatnonzero(status > STATUS_NO_MODEL)
    if len(attempted_rows):
        for start in range(int(attempted_rows[0]), len(status), refit_every_bars):
            if status[start] > STATUS_NO_MODEL:  # rows past a non-finite tail have no segment
                counts[str(int(status[start]))] += 1
    attempted = sum(counts.values())
    written = np.flatnonzero(status == STATUS_WRITTEN)
    return {
        "status_counts": counts,
        "attempted": attempted,
        "skip_fraction": None if attempted == 0 else (attempted - counts["1"]) / attempted,
        "labeled_rows": int(len(written)),
        "first_labeled_row": int(written[0]) if len(written) else None,
    }


def classify_cell(cell: dict[str, Any]) -> str:
    """The todo 341 class of one cell result (rule fixed before the run):
    (a) no segment attempted and the series has fewer observations than the first boundary;
    (b) attempts exist and every one is degenerate occupation; (c) every one is not converged;
    (d) at least one segment is written (the stored NULLs come from the old writer);
    (e) anything else, including an error, is a defect."""
    if cell.get("error"):
        return CLASS_DEFECT
    summary = cell["summary"]
    counts = summary["status_counts"]
    attempted = summary["attempted"]
    if counts["1"] > 0:
        return CLASS_LABELS_UNDER_KERNEL
    if attempted == 0:
        return CLASS_HISTORY_SHORT if cell["n_obs"] < cell["first_boundary_obs"] else CLASS_DEFECT
    if counts[str(int(STATUS_DEGENERATE_OCCUPATION))] == attempted:
        return CLASS_DEGENERATE
    if counts[str(int(STATUS_NOT_CONVERGED))] == attempted:
        return CLASS_NOT_CONVERGED
    return CLASS_DEFECT


def parse_override(items: list[str]) -> dict[str, Any]:
    """`field=value` strings to a dict, each value cast to the field's type in `HmmConfig`;
    ValueError for an unknown field or a malformed item."""
    types = {f.name: f.type for f in dataclasses.fields(HmmConfig)}
    casts = {"int": int, "float": float, "str": str}
    out: dict[str, Any] = {}
    for item in items:
        name, sep, raw = item.partition("=")
        if not sep or not name:
            raise ValueError(f"override must be field=value, got {item!r}")
        if name not in types:
            raise ValueError(f"unknown HmmConfig field {name!r}")
        out[name] = casts[str(types[name])](raw)
    return out


def apply_overrides(hmm: HmmConfig, overrides: dict[str, Any]) -> HmmConfig:
    """`dataclasses.replace` with a named error for an unknown field."""
    unknown = set(overrides) - {f.name for f in dataclasses.fields(HmmConfig)}
    if unknown:
        raise ValueError(f"unknown HmmConfig field(s) {sorted(unknown)}")
    return dataclasses.replace(hmm, **overrides)


def override_sets(base: dict[str, Any], sweep: list[str]) -> list[dict[str, Any]]:
    """One override dict per point of the `--sweep field=v1,v2` grid (the cross product when
    several fields are swept), each combined with `base`; `[base]` when nothing is swept."""
    if not sweep:
        return [dict(base)]
    axes: list[list[dict[str, Any]]] = []
    for item in sweep:
        name, sep, raw = item.partition("=")
        if not sep or not raw:
            raise ValueError(f"sweep must be field=v1,v2,..., got {item!r}")
        axes.append([parse_override([f"{name}={value}"]) for value in raw.split(",")])
    return [
        {**base, **{k: v for part in combo for k, v in part.items()}}
        for combo in itertools.product(*axes)
    ]


def override_label(overrides: dict[str, Any]) -> str:
    return ",".join(f"{k}={v}" for k, v in sorted(overrides.items())) or "base"


def _run_cell(job: dict[str, Any]) -> dict[str, Any]:
    """Worker: one (symbol, tf, family, override set) over arrays handed over by the main
    process. Compute only, no database."""
    from src.intelligence.features.contract.registry import compute_kernels, default_registry
    from src.intelligence.features.kernels.regime import compute_regime_columns

    spec = FAMILY_SPECS[job["family"]]
    hmm: HmmConfig = job["hmm"]
    tf = job["tf"]
    cell: dict[str, Any] = {
        "symbol": job["symbol"],
        "tf": tf,
        "family": job["family"],
        "overrides": job["override_label"],
        "n_bars": int(len(job["close"])),
    }
    try:
        refit, warmup = hmm.walk_forward_schedule(tf)
        n_components, _cov = spec.model_fields(hmm)
        obs, valid_start = spec.build_observations(job["close"], job["volume"], hmm, None)
        cell["n_obs"] = int(len(obs))
        cell["first_boundary_obs"] = int(max(warmup, n_components * hmm.hmm_min_obs_factor))
        cell["refit_every_bars"] = refit
        inputs = {
            "ts": job["ts"],
            "close": job["close"],
            "volume": job["volume"],
            "tf": np.array([tf] * len(job["close"]), dtype=object),
        }
        out = compute_kernels(
            default_registry(),
            inputs,
            cast(Any, SimpleNamespace(hmm=hmm)),  # the kernels read only .hmm
            outputs=[spec.code_output, spec.status_output],
        )
        status = out[spec.status_output]
        cell["summary"] = summarize_segments(status, refit)
        first = cell["summary"]["first_labeled_row"]
        cell["first_labeled_ts_ns"] = None if first is None else int(job["ts"][first])
        cell["post_boundary_rows"] = max(0, cell["n_obs"] - cell["first_boundary_obs"])
        cell["valid_start"] = int(valid_start)
        if cell["summary"]["attempted"] and cell["summary"]["status_counts"]["1"] == 0:
            # nothing written: keep the per-segment gate diagnostics for the todo 341 record
            events = compute_regime_columns(job["close"], job["volume"], hmm, tf, spec).events
            cell["skip_events"] = [
                dict(event.fields) for event in events if event.kind == EVENT_SEGMENT_SKIPPED
            ][:8]
    except Exception as error:
        cell["error"] = f"{type(error).__name__}: {error}"
    cell["class"] = classify_cell(cell) if "summary" in cell or "error" in cell else CLASS_DEFECT
    return cell


def pool_cells(cells: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals per (tf, family, override set): segments by status, the pooled skip fraction, the
    dominant skip reason, cell classes and the labeled fraction of rows after the first boundary."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for cell in cells:
        groups.setdefault(f"{cell['tf']}|{cell['family']}|{cell['overrides']}", []).append(cell)
    pooled: dict[str, Any] = {}
    for key, members in sorted(groups.items()):
        counts = {str(c): 0 for c in (1, 2, 3, 4)}
        labeled = post = errors = 0
        classes: dict[str, int] = {}
        for cell in members:
            classes[cell["class"]] = classes.get(cell["class"], 0) + 1
            if "summary" not in cell:
                errors += 1
                continue
            for code, n in cell["summary"]["status_counts"].items():
                counts[code] += n
            labeled += cell["summary"]["labeled_rows"]
            post += cell["post_boundary_rows"]
        attempted = sum(counts.values())
        skipped = {c: counts[c] for c in ("2", "3", "4")}
        pooled[key] = {
            "cells": len(members),
            "errors": errors,
            "status_counts": counts,
            "attempted": attempted,
            "skip_fraction": None if attempted == 0 else (attempted - counts["1"]) / attempted,
            "dominant_skip_status": (
                max(skipped, key=lambda c: skipped[c]) if any(skipped.values()) else None
            ),
            "labeled_rows": labeled,
            "post_boundary_rows": post,
            "labeled_fraction_after_first_boundary": None if post == 0 else labeled / post,
            "classes": classes,
        }
    return pooled


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO_ROOT, check=True
    ).stdout.strip()


def _epoch_ns(timestamps: list) -> np.ndarray:
    return np.array([int(t.timestamp()) * 1_000_000_000 for t in timestamps], dtype=np.int64)


def fetch_bars(conn: Any, symbol: str, tf: str) -> dict[str, np.ndarray] | None:
    """(ts, close, volume) of one series from `market_data_ohlcv_tradeable`, or None. Read only."""
    conn.commit()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT timestamp, close, volume FROM market_data_ohlcv_tradeable "
            "WHERE symbol = %s AND timeframe = %s ORDER BY timestamp ASC",
            (symbol, tf),
        )
        rows = cur.fetchall()
    conn.commit()
    if not rows:
        return None
    ts, close, volume = zip(*rows, strict=True)
    return {
        "ts": _epoch_ns(list(ts)),
        "close": np.array(close, dtype=float),
        "volume": np.array(volume, dtype=float),
    }


def resolve_symbols(conn: Any, symbols: list[str], limit: int | None) -> list[str]:
    """`@compute_eligible_1d` expands to the 1d-eligible names; `limit` keeps the first N in
    sha256(symbol) order (a fixed, unbiased sample)."""
    if symbols == [UNIVERSE_1D]:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT symbol FROM instruments WHERE compute_eligible_1d ORDER BY symbol"
            )
            names = [row[0] for row in cur.fetchall()]
        conn.commit()
    else:
        names = list(symbols)
    if limit is not None:
        names = sorted(names, key=lambda s: hashlib.sha256(s.encode()).hexdigest())[:limit]
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbols", nargs="+", required=True, help=f"names, or {UNIVERSE_1D}")
    parser.add_argument("--limit", type=int, help="first N names in sha256(symbol) order")
    parser.add_argument("--tfs", nargs="+", default=list(WALK_FORWARD_TIMEFRAMES))
    parser.add_argument("--families", nargs="+", default=list(FAMILIES), choices=FAMILIES)
    parser.add_argument("--override", action="append", default=[], help="HmmConfig field=value")
    parser.add_argument("--sweep", action="append", default=[], help="HmmConfig field=v1,v2,...")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    import psycopg

    from services._batch_utils import load_config_service_sync, make_worker_pool
    from src.config.settings import Settings

    bad_tfs = [tf for tf in args.tfs if tf not in WALK_FORWARD_TIMEFRAMES]
    if bad_tfs:
        raise SystemExit(f"unknown timeframes {bad_tfs}")
    started = time.monotonic()
    sets = override_sets(parse_override(args.override), args.sweep)
    with psycopg.connect(Settings().database_url) as conn:
        conn.read_only = True
        cfg = load_config_service_sync(conn)
        base_hmm = HmmConfig.from_values(cfg.get_sync)
        symbols = resolve_symbols(conn, args.symbols, args.limit)
        hmm_by_label = {override_label(s): apply_overrides(base_hmm, s) for s in sets}
        cells: list[dict[str, Any]] = []
        pending: set[Future] = set()

        def drain_one() -> None:
            nonlocal pending
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            cells.extend(future.result() for future in done)

        with make_worker_pool(args.workers, blas_threads_per_worker=1) as pool:
            for i, symbol in enumerate(symbols):
                for tf in args.tfs:
                    bars = fetch_bars(conn, symbol, tf)
                    if bars is None:
                        cells.append(
                            {
                                "symbol": symbol,
                                "tf": tf,
                                "family": "-",
                                "overrides": "base",
                                "n_bars": 0,
                                "error": "no bars in market_data_ohlcv_tradeable",
                                "class": CLASS_DEFECT,
                            }
                        )
                        continue
                    for family, (label, hmm) in itertools.product(
                        args.families, hmm_by_label.items()
                    ):
                        while len(pending) >= 2 * args.workers:
                            drain_one()
                        pending.add(
                            pool.submit(
                                _run_cell,
                                {
                                    "symbol": symbol,
                                    "tf": tf,
                                    "family": family,
                                    "hmm": hmm,
                                    "override_label": label,
                                    **bars,
                                },
                            )
                        )
                if (i + 1) % 25 == 0:
                    print(
                        f"{i + 1}/{len(symbols)} names submitted, {len(cells)} cells done",
                        flush=True,
                    )
            while pending:
                drain_one()

    cells.sort(key=lambda c: (c["symbol"], c["tf"], c["family"], c["overrides"]))
    report: dict[str, Any] = {
        "run": {
            "commit": _git_head(),
            "started_utc": datetime.now(UTC).isoformat(),
            "elapsed_seconds": round(time.monotonic() - started, 1),
            "symbols": symbols,
            "tfs": args.tfs,
            "families": args.families,
            "override_sets": [override_label(s) for s in sets],
            "workers": args.workers,
        },
        "apr_snapshot": dataclasses.asdict(base_hmm),
        "pooled": pool_cells(cells),
        "cells": cells,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True, default=str) + "\n")
    print(f"wrote {args.out}: {len(cells)} cells in {report['run']['elapsed_seconds']} s")


if __name__ == "__main__":
    main()
