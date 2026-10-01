"""Read-only coverage sweep of the walk-forward HMM regime kernels over stored bars (186-18).

For each (symbol, tf, family) cell the sweep reads the bars from `market_data_ohlcv_tradeable`
(through regime_writer's own `_fetch_bars`), builds the family's observation matrix once, runs the
walk-forward kernel and reports how many refit segments were written, degenerate, not converged or
gated for another reason, taken from the kernel's own per-segment events. It reads no returns, so
it adds nothing to any vintage count, and it writes nothing to the database: the only output is
one JSON report.

Used for todo 341 (why five symbols have no regime label at all: classify each cell) and todo 289
(which `hmm_refit_every_bars_1d` gives the fewest skipped segments, decided by
`decide_refit_schedule`). Parameters come from APR through `HmmConfig.from_values`;
`--override field=value` replaces `HmmConfig` fields for the whole run, and one
`--sweep field=v1,v2,...` axis over a schedule field measures candidate schedules without touching
APR.

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
import json
import re
import sys
import time
from concurrent.futures import FIRST_COMPLETED, Future, wait
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.infrastructure._capture_common import git_head  # noqa: E402
from src.intelligence.features.kernels._hmm import (  # noqa: E402
    _GATE_REASON_STATUS,
    EVENT_CONVERGENCE,
    EVENT_SEGMENT_SKIPPED,
    FAMILY_SPECS,
    STATUS_DEGENERATE_OCCUPATION,
    STATUS_NOT_CONVERGED,
    STATUS_OTHER_GATE,
    STATUS_WRITTEN,
    WALK_FORWARD_TIMEFRAMES,
    HmmConfig,
    RegimeEventRecord,
    walk_forward_family_arrays,
)

FAMILIES = ("trend", "volatility")
UNIVERSE_1D = "@compute_eligible_1d"
_SCHEDULE_FIELD = re.compile(r"^hmm_(refit_every_bars|initial_warmup_bars)_(5m|15m|1h|1d)$")

# cell classes of todo 341, decided by `classify_cell` (the rule was written before the run)
CLASS_HISTORY_SHORT = "a_history_short"
CLASS_DEGENERATE = "b_degenerate"
CLASS_NOT_CONVERGED = "c_not_converged"
CLASS_LABELS_UNDER_KERNEL = "d_labels_under_kernel"
CLASS_DEFECT = "e_other_or_error"

# The todo 289 decision rule, exactly as committed in 81c22910c before the measurement run.
REFIT_RULE_TEXT = (
    "Metric: the pooled 1d segment skip fraction per family, (degenerate + not converged + other "
    "gate reason) / attempted segments, at each hmm_refit_every_bars_1d in {126, 252, 504}. "
    "Deciding value per schedule: the larger of the two families' pooled skip fractions. "
    "Rule: keep 252 if its deciding value is within 0.02 of the smallest deciding value across "
    "the three schedules; otherwise pick the schedule with the smallest deciding value."
)
REFIT_TOLERANCE = 0.02


def skip_fraction(status_counts: dict[str, int]) -> float | None:
    """(degenerate + not converged + other gate) / attempted; None when nothing was attempted."""
    attempted = sum(status_counts.values())
    return None if attempted == 0 else (attempted - status_counts["1"]) / attempted


def summarize_segments(events: tuple[RegimeEventRecord, ...]) -> dict[str, Any]:
    """Segment counts of one cell from the kernel's own events (one `EVENT_CONVERGENCE` per
    segment it laid out, one `EVENT_SEGMENT_SKIPPED` per segment it did not write).

    Returns counts per status (keys "1" written, "2" degenerate occupation, "3" not converged,
    "4" other gate reason), `attempted`, `skip_fraction` and `labeled_rows` (rows of written
    segments)."""
    skipped = {
        e.fields["seg_start"]: _GATE_REASON_STATUS.get(e.fields.get("reason"), STATUS_OTHER_GATE)
        for e in events
        if e.kind == EVENT_SEGMENT_SKIPPED
    }
    counts = {str(int(code)): 0 for code in (1.0, 2.0, 3.0, 4.0)}
    labeled = 0
    for e in events:
        if e.kind != EVENT_CONVERGENCE:
            continue
        start, end = e.fields["seg_start"], e.fields["seg_end"]
        if start in skipped:
            counts[str(int(skipped[start]))] += 1
        else:
            counts[str(int(STATUS_WRITTEN))] += 1
            labeled += end - start
    return {
        "status_counts": counts,
        "attempted": sum(counts.values()),
        "skip_fraction": skip_fraction(counts),
        "labeled_rows": labeled,
    }


def classify_cell(cell: dict[str, Any]) -> str:
    """The todo 341 class of one cell result (rule fixed before the run):
    (a) no segment attempted and the series has no row past the first boundary (a segment needs at
    least one observation at or after it, so n_obs equal to the boundary counts);
    (b) attempts exist and every one is degenerate occupation; (c) every one is not converged;
    (d) at least one segment is written (the stored NULLs come from the old writer);
    (e) anything else, including an error, is a defect."""
    if cell.get("error"):
        return CLASS_DEFECT
    counts = cell["summary"]["status_counts"]
    attempted = cell["summary"]["attempted"]
    if counts["1"] > 0:
        return CLASS_LABELS_UNDER_KERNEL
    if attempted == 0:
        return CLASS_HISTORY_SHORT if cell["n_obs"] <= cell["first_boundary_obs"] else CLASS_DEFECT
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


def parse_sweep(item: str | None) -> tuple[str, list[Any]] | None:
    """`field=v1,v2,...` to (field, values). Only a per-tf schedule field may be swept: the
    observation matrix is built once per family and shared by every sweep point."""
    if item is None:
        return None
    name, sep, raw = item.partition("=")
    if not sep or not raw:
        raise ValueError(f"sweep must be field=v1,v2,..., got {item!r}")
    if not _SCHEDULE_FIELD.match(name):
        raise ValueError(f"only a per-tf schedule field can be swept, got {name!r}")
    return name, [parse_override([f"{name}={v}"])[name] for v in raw.split(",")]


def decide_refit_schedule(
    skip_by_schedule: dict[int, dict[str, float]],
    current: int,
    tolerance: float = REFIT_TOLERANCE,
) -> dict[str, Any]:
    """The pre-registered todo 289 rule (`REFIT_RULE_TEXT`). `skip_by_schedule` maps each schedule
    to its pooled skip fraction per family. The deciding value is the larger family; keep
    `current` when its deciding value is within `tolerance` of the smallest (exactly at the
    tolerance counts as within), else take the schedule with the smallest deciding value (the
    smaller schedule on a tie)."""
    deciding = {sched: max(by_family.values()) for sched, by_family in skip_by_schedule.items()}
    smallest = min(deciding.values())
    keep = deciding[current] <= smallest + tolerance
    chosen = current if keep else min(sorted(deciding), key=lambda s: deciding[s])
    return {
        "deciding_values": {str(s): deciding[s] for s in sorted(deciding)},
        "smallest_deciding_value": smallest,
        "keep_current": keep,
        "chosen": chosen,
        "rule": REFIT_RULE_TEXT,
    }


def _run_series(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Worker: every family and sweep point of one (symbol, tf) over bars handed over once.
    Compute only, no database. The observation matrix of a family is built once and shared by the
    sweep points (a swept schedule field does not change it)."""
    out: list[dict[str, Any]] = []
    close, volume, tf = job["close"], job["volume"], job["tf"]
    for family in job["families"]:
        spec = FAMILY_SPECS[family]
        try:
            obs, valid_start = spec.build_observations(close, volume, job["points"][0][1], None)
        except Exception as error:
            obs, valid_start, obs_error = np.empty((0, 0)), 0, f"{type(error).__name__}: {error}"
        else:
            obs_error = ""
        for label, hmm in job["points"]:
            cell: dict[str, Any] = {
                "symbol": job["symbol"],
                "tf": tf,
                "family": family,
                "overrides": label,
                "n_bars": int(len(close)),
                "n_obs": int(len(obs)),
            }
            try:
                if obs_error:
                    raise RuntimeError(obs_error)
                refit, warmup = hmm.walk_forward_schedule(tf)
                n_components, _cov = spec.model_fields(hmm)
                cell["first_boundary_obs"] = int(max(warmup, n_components * hmm.hmm_min_obs_factor))
                cell["refit_every_bars"] = refit
                events: tuple[RegimeEventRecord, ...] = ()
                if len(obs):
                    events = walk_forward_family_arrays(
                        obs, valid_start + 1, len(close), hmm, tf, spec
                    ).events
                cell["summary"] = summarize_segments(events)
                cell["post_boundary_rows"] = max(0, cell["n_obs"] - cell["first_boundary_obs"])
            except Exception as error:
                cell["error"] = f"{type(error).__name__}: {error}"
            cell["class"] = classify_cell(cell)
            out.append(cell)
    return out


def pool_cells(cells: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals per (tf, family, sweep point): segments by status, the pooled skip fraction, the
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
        skipped = {c: counts[c] for c in ("2", "3", "4")}
        pooled[key] = {
            "cells": len(members),
            "errors": errors,
            "status_counts": counts,
            "attempted": sum(counts.values()),
            "skip_fraction": skip_fraction(counts),
            "dominant_skip_status": (
                max(skipped, key=lambda c: skipped[c]) if any(skipped.values()) else None
            ),
            "labeled_rows": labeled,
            "post_boundary_rows": post,
            "labeled_fraction_after_first_boundary": None if post == 0 else labeled / post,
            "classes": classes,
        }
    return pooled


def refit_decision(
    pooled: dict[str, Any], field: str, values: list[int], families: list[str], current: int
) -> dict[str, Any] | None:
    """`decide_refit_schedule` over a sweep of a `hmm_refit_every_bars_<tf>` field, from the
    pooled report; None for any other swept field or when a family is not in the run."""
    match = _SCHEDULE_FIELD.match(field)
    if not match or match.group(1) != "refit_every_bars" or current not in values:
        return None
    tf = match.group(2)
    skips: dict[int, dict[str, float]] = {}
    for value in values:
        by_family = {}
        for family in families:
            fraction = pooled.get(f"{tf}|{family}|{field}={value}", {}).get("skip_fraction")
            if fraction is None:
                return None
            by_family[family] = fraction
        skips[value] = by_family
    return decide_refit_schedule(skips, current)


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
    parser.add_argument("--sweep", help="one schedule field: hmm_refit_every_bars_1d=126,252,504")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    import psycopg

    from services._batch_utils import load_config_service_sync, make_worker_pool
    from services.regime_writer import _fetch_bars
    from src.config.settings import Settings

    bad_tfs = [tf for tf in args.tfs if tf not in WALK_FORWARD_TIMEFRAMES]
    if bad_tfs:
        raise SystemExit(f"unknown timeframes {bad_tfs}")
    started = time.monotonic()
    overrides = parse_override(args.override)
    sweep = parse_sweep(args.sweep)
    with psycopg.connect(Settings().database_url) as conn:
        conn.set_read_only(True)
        cfg = load_config_service_sync(conn)
        base_hmm = dataclasses.replace(HmmConfig.from_values(cfg.get_sync), **overrides)
        points = [("base", base_hmm)]
        if sweep:
            field, values = sweep
            points = [(f"{field}={v}", dataclasses.replace(base_hmm, **{field: v})) for v in values]
        symbols = resolve_symbols(conn, args.symbols, args.limit)
        cells: list[dict[str, Any]] = []
        pending: set[Future] = set()

        def drain_one() -> None:
            nonlocal pending
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                cells.extend(future.result())

        with make_worker_pool(args.workers, blas_threads_per_worker=1) as pool:
            for i, symbol in enumerate(symbols):
                for tf in args.tfs:
                    bars = _fetch_bars(conn, symbol, tf)
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
                    while len(pending) >= 2 * args.workers:
                        drain_one()
                    pending.add(
                        pool.submit(
                            _run_series,
                            {
                                "symbol": symbol,
                                "tf": tf,
                                "families": args.families,
                                "points": points,
                                "close": bars["close"],
                                "volume": bars["volume"],
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
    pooled = pool_cells(cells)
    report: dict[str, Any] = {
        "run": {
            "commit": git_head(),
            "started_utc": datetime.now(UTC).isoformat(),
            "elapsed_seconds": round(time.monotonic() - started, 1),
            "symbols": symbols,
            "tfs": args.tfs,
            "families": args.families,
            "sweep": args.sweep,
            "overrides": args.override,
            "workers": args.workers,
        },
        "apr_snapshot": dataclasses.asdict(base_hmm),
        "pooled": pooled,
        "cells": cells,
    }
    if sweep:
        field, values = sweep
        current = getattr(base_hmm, field)
        decision = refit_decision(pooled, field, values, args.families, current)
        if decision:
            report["refit_decision"] = decision
            print("rule:", decision["rule"])
            print("decision:", json.dumps({k: v for k, v in decision.items() if k != "rule"}))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True, default=str) + "\n")
    print(f"wrote {args.out}: {len(cells)} cells in {report['run']['elapsed_seconds']} s")


if __name__ == "__main__":
    main()
