#!/usr/bin/env python3
"""IC sweep recorder: every measured level 1 IC cell becomes counted attempts (todo 671, E21).

E21 (methodology-change-ledger, adopted 2026-11-13; rulings 2026-11-24i): a level 1 cell is
(feature, timeframe, horizon). Its attempt series is the per-session rank IC across names
(`measure.session_ic.session_rank_ic`), recorded as one `research_run` attempt (kind `evidence`,
mode `real`, `concept_id` the feature's own concept row) with the series in
`research_run_series`, written only through the S6 ledger (`PostgresLedger.record_sweep_block`).
Each cell is recorded as two attempts, the long (the measured IC) and the mirrored short (its
negation), each tested one-sided positive by the shipped StepM: no sign is fitted or chosen.
`feature_ic_scores` is never written here and is never the selection universe.

One block is one (timeframe, horizon, direction): one spec (the canonical JSON of everything
that defines its cells), one spec hash, one transaction. A block already recorded is skipped, so
the run resumes; a crash leaves no half-written block. The block's cells are computed in full
before its transaction opens.

What is measured is every numeric feature column that has a `feature`-domain concept row;
columns without one are reported and never measured (a measured cell must be countable). A
column with no tested session at all (not applicable at the timeframe, or constant) is reported
as unmeasured and records nothing.

A real run needs `--declared-n-looks`, the attempt count the ledger line declares before the
batch (E21 rule 6), and refuses unless it equals the attempts this run will record. The code
commit recorded is HEAD, and a real run refuses a dirty tree and a HEAD that is not an
ancestor of origin/main (run it from a detached worktree at a pushed commit). Targets come from
the kernel (`panel.forward_returns`) on panels ending at `alpha.validation.oos_start`, so no
series reaches the forward span.

Usage:
    python services/ic_sweep_recorder.py --tf 1d --dry-run
    python services/ic_sweep_recorder.py --tf 1d --horizons 1 --declared-n-looks 554
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import structlog

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services.batch_support.bulk_load import parse_run_id  # noqa: E402
from services.batch_support.db import load_config_service_sync, short_lived_conn  # noqa: E402
from services.ic_measure import (  # noqa: E402
    IcMeasure,
    TfSession,
    apr_keys_read,
    column_digest,
    feature_blocks,
    features_digest,
    panels_digest,
    parse_oos,
)
from src.config.settings import Settings  # noqa: E402
from src.core.canonical_json import canonical_json  # noqa: E402
from src.core.service_utils import format_iso_ts, setup_service_logging  # noqa: E402
from src.intelligence.features.contract.registry import (  # noqa: E402
    KernelRegistry,
    KernelRegistryError,
    default_registry,
)
from src.intelligence.measure.ic import existing_rows  # noqa: E402
from src.intelligence.measure.session_ic import session_rank_ic  # noqa: E402
from src.intelligence.research import provenance  # noqa: E402
from src.intelligence.research.feature_inputs import (  # noqa: E402
    FeatureInputRefused,
    refuse_builder_path_dependent,
    refuse_path_dependent,
)
from src.intelligence.research.ledger import (  # noqa: E402
    SWEEP_SPEC_PATH_PREFIX,
    AttemptSeries,
    LedgerRefusal,
    PostgresLedger,
    RunRequest,
)
from src.intelligence.statistics.hac import hac_mean_test  # noqa: E402
from src.observability.metrics import (  # noqa: E402
    IC_SWEEP_BLOCKS_RECORDED_TOTAL,
    IC_SWEEP_CELLS_RECORDED_TOTAL,
    JOB_COMPLETED_TOTAL,
    flush_and_shutdown_metrics,
)
from src.observability.otel import OTelInitError, init_otel_providers  # noqa: E402
from src.observability.spans import observed_span  # noqa: E402

_logger = structlog.get_logger(__name__)

# Service identity and schema identifiers: APR-exempt.
_JOB = "ic-sweep-recorder"
SPEC_VERSION = "ic-sweep-cell-v1"
DIRECTIONS = ("long", "short")  # ledger 2026-11-24i: two attempts per cell, never a fitted sign
_BLOCK_COLUMNS_KEY = "alpha.ic.feature_block_columns"
_OOS_START_KEY = "alpha.validation.oos_start"
_VINTAGE_KEY = "alpha.research.vintage_id"
MIN_NAMES_KEY = "alpha.ic_sweep.min_names_per_session"


# ---------------------------------------------------------------------------
# Pure pieces (tested without a database)
# ---------------------------------------------------------------------------


def block_spec(
    *,
    tf: str,
    horizon: int,
    direction: str,
    min_names: int,
    oos_start: datetime,
    panels_key: str,
    features_key: str,
    feature_names: Sequence[str],
) -> tuple[str, str, str]:
    """(spec_path, spec_blob, spec_hash) of one block. The blob is the canonical JSON of every
    input that defines its cells' series, so a changed panel, feature column, floor or horizon is
    a different spec; E18's no-silent-repeat rule then refuses only a true repeat."""
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}, got {direction!r}")
    blob = canonical_json(
        {
            "version": SPEC_VERSION,
            "tf": tf,
            "horizon": horizon,
            "direction": direction,
            "target": "panel.forward_returns (open to open, executable)",
            "statistic": "per-session Spearman IC across names, finite pairs, min_names floor",
            "min_names": min_names,
            "oos_start": format_iso_ts(oos_start),
            "panels": panels_key,
            "features": features_key,
            "feature_names": sorted(feature_names),
        }
    )
    digest = hashlib.sha256(blob.encode()).hexdigest()
    return f"{SWEEP_SPEC_PATH_PREFIX}/{tf}_h{horizon}_{direction}_{digest[:12]}.json", blob, digest


def cell_series(
    sessions: np.ndarray, ic: np.ndarray, *, direction: str, oos_start: datetime
) -> AttemptSeries | None:
    """The attempt series of one cell and direction: the sessions with a finite IC (the short is
    the negated IC). None when no session was tested. Refuses a session at or after oos_start."""
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}, got {direction!r}")
    days = np.asarray(sessions, dtype="datetime64[D]")
    series = AttemptSeries.from_timing(days, ic if direction == "long" else -ic)
    if series is not None and series.sessions[-1] >= np.datetime64(oos_start.date()):
        raise ValueError(
            f"series reaches {series.sessions[-1]}, at or after oos_start {oos_start.date()}"
        )
    return series


def cell_evidence(
    *, feature: str, tf: str, horizon: int, direction: str, series: AttemptSeries
) -> dict[str, Any]:
    """The attempt's evidence: its coordinates and the E17 HAC mean test of the series (a
    disclosure; the selection statistic is StepM's, over the whole universe)."""
    decision: dict[str, Any] = {"n_sessions": int(len(series.values))}
    try:
        test = hac_mean_test(series.values)
    except ValueError:  # fewer than 2 sessions or no variance: a disclosure that is not defined
        test = None
    if test is not None:
        decision |= {"t": float(test.t), "p": float(test.p)}
    return {
        "cell": {"feature": feature, "tf": tf, "horizon": horizon, "direction": direction},
        "decision": decision,
        "mean_ic": float(series.values.mean()),
    }


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Measurement:
    """Everything the blocks are built from: IC [n, F] per horizon on the session grid."""

    sessions: np.ndarray  # [n] datetime64[D]
    names: tuple[str, ...]  # measured feature columns, column order of the IC arrays
    ic: Mapping[int, np.ndarray]  # horizon -> [n, F]
    panels_key: str
    features_key: str
    excluded_no_concept: tuple[str, ...]
    excluded_inadmissible: tuple[str, ...]


def _inadmissible(names: Sequence[str], registry: KernelRegistry) -> set[str]:
    """Columns S0 refuses as members (todo 674 R2, B1g, B1j): path dependent, a pass-through of
    a path-dependent builder, or regime origin (its walk-forward provenance check needs the
    covering batches, which a sweep does not read, so the column is left out and disclosed).
    Names the registry does not know pass through, as they did before."""
    out: set[str] = set()
    for name in names:
        try:
            origin = registry.by_output(name).origin
            refuse_path_dependent(name, registry)
            refuse_builder_path_dependent(name, registry)
        except KernelRegistryError:
            continue
        except FeatureInputRefused:
            out.add(name)
            continue
        if origin == "regime":
            out.add(name)
    return out


def measure(
    session: TfSession,
    concept_names: set[str],
    min_names: int,
    registry: KernelRegistry | None = None,
) -> Measurement:
    """Per-session rank IC of every registered feature column at every horizon of the run, on
    the session's one grid (one panel, one slot map, one feature family: the same inputs as the
    proposer's cells). Blocks of columns bound memory only; no value depends on them."""
    ctx, run = session.ctx, session.run
    if ctx.panels[0].bars_per_session != 1:
        raise ValueError("a level 1 sweep cell series is per session: run it on the 1d clock")
    registered = [n for n in session.names if n in concept_names]
    refused = _inadmissible(registered, registry if registry is not None else default_registry())
    names = [n for n in registered if n not in refused]
    excluded = tuple(sorted(set(session.names) - concept_names))
    exists = existing_rows(ctx.grid.valid_grid(), ctx.present)
    block_size = max(int(run.apr[_BLOCK_COLUMNS_KEY]), 1)
    targets = {h: ctx.stack(h).targets for h in run.horizons}
    parts: dict[int, list[np.ndarray]] = {h: [] for h in run.horizons}
    digests: dict[str, str] = {}
    for block in feature_blocks(names, block_size):
        grid = session.fetch(block)
        for i, name in enumerate(block):
            digests[name] = column_digest(name, grid[:, :, i])
        for h in run.horizons:
            parts[h].append(session_rank_ic(grid, targets[h], exists, min_names=min_names))
    return Measurement(
        sessions=ctx.grid.timestamps.astype("datetime64[D]"),
        names=tuple(names),
        ic={h: np.concatenate(parts[h], axis=1) for h in run.horizons},
        panels_key=panels_digest(ctx.grid, ctx.panels),
        features_key=features_digest(digests, ctx.present),
        excluded_no_concept=excluded,
        excluded_inadmissible=tuple(sorted(refused)),
    )


def measured_cells(
    m: Measurement, horizon: int, *, direction: str, oos_start: datetime
) -> tuple[dict[str, AttemptSeries], list[str]]:
    """({feature: series} for the cells with a tested session, the unmeasured feature names)."""
    cells: dict[str, AttemptSeries] = {}
    unmeasured: list[str] = []
    for f, name in enumerate(m.names):
        series = cell_series(
            m.sessions, m.ic[horizon][:, f], direction=direction, oos_start=oos_start
        )
        if series is None:
            unmeasured.append(name)
        else:
            cells[name] = series
    return cells, unmeasured


async def record_blocks(
    ledger: PostgresLedger,
    m: Measurement,
    *,
    tf: str,
    horizons: Sequence[int],
    min_names: int,
    oos_start: datetime,
    vintage: str,
    code_commit: str,
    declared_n_looks: int | None,
    dry_run: bool,
) -> dict[str, Any]:
    """Record every block not already recorded; returns the report. The attempt count of the
    blocks it would write must equal `declared_n_looks` (E21 rule 6) before the first write."""
    plan: list[tuple[int, str, str, str, str, dict[str, AttemptSeries]]] = []
    unmeasured: dict[int, list[str]] = {}
    already = 0
    for horizon in horizons:
        for direction in DIRECTIONS:
            cells, unmeasured[horizon] = measured_cells(
                m, horizon, direction=direction, oos_start=oos_start
            )
            path, blob, digest = block_spec(
                tf=tf,
                horizon=horizon,
                direction=direction,
                min_names=min_names,
                oos_start=oos_start,
                panels_key=m.panels_key,
                features_key=m.features_key,
                feature_names=list(cells),
            )
            if await ledger.has_real_run(digest):
                already += len(cells)
                continue
            plan.append((horizon, direction, path, blob, digest, cells))
    to_record = sum(len(cells) for *_head, cells in plan)
    batch = to_record + already  # the whole batch the ledger line declares, recorded or not
    report: dict[str, Any] = {
        "tf": tf,
        "horizons": list(horizons),
        "batch_attempts": batch,  # the n_looks the ledger line declares; unmeasured cells add none
        "declared_n_looks": declared_n_looks,
        "attempts_to_record": to_record,
        "attempts_already_recorded": already,
        "excluded_no_concept": list(m.excluded_no_concept),
        "excluded_inadmissible": list(m.excluded_inadmissible),
        "unmeasured": {str(h): v for h, v in unmeasured.items()},
        "recorded": 0,
        "dry_run": dry_run,
    }
    if dry_run:
        return report
    if to_record == 0:
        return report
    if declared_n_looks != batch:
        raise LedgerRefusal(
            f"declared n_looks {declared_n_looks} != the batch of {batch} attempts "
            f"({to_record} to record, {already} already recorded; E21 rule 6: declare the batch "
            "in the ledger first)"
        )
    for horizon, direction, path, blob, digest, cells in plan:
        request = RunRequest(
            kind="evidence",
            spec_path=path,
            spec_hash=digest,
            spec_blob=blob,
            code_commit=code_commit,
            vintage=vintage,
        )
        payload = {
            name: (
                series,
                cell_evidence(
                    feature=name, tf=tf, horizon=horizon, direction=direction, series=series
                ),
            )
            for name, series in cells.items()
        }
        attrs = {"tf": tf, "horizon": horizon, "direction": direction}
        async with observed_span("ic_sweep_recorder.record_block", cells=len(cells), **attrs):
            await ledger.record_sweep_block(request, payload)
        IC_SWEEP_BLOCKS_RECORDED_TOTAL.add(1, attrs)
        IC_SWEEP_CELLS_RECORDED_TOTAL.add(len(cells), attrs)
        report["recorded"] += len(cells)
        _logger.info(
            "ic_sweep_recorder.block_recorded",
            tf=tf,
            horizon=horizon,
            direction=direction,
            cells=len(cells),
        )
    return report


async def _measure_observed(
    session: TfSession, concepts: set[str], min_names: int, tf: str
) -> Measurement:
    """`measure` inside its span (the hours-long step of a run); a sync body in a one-shot loop."""
    async with observed_span(
        "ic_sweep_recorder.measure",
        tf=tf,
        horizons=",".join(str(h) for h in session.run.horizons),
        features=len(concepts),
    ):
        return measure(session, concepts, min_names)


def _horizons(requested: Sequence[int] | None, available: Sequence[int]) -> tuple[int, ...]:
    if not requested:
        return tuple(available)
    unknown = sorted(set(requested) - set(available))
    if unknown:
        raise ValueError(f"horizons {unknown} are not in the tf's APR horizons {list(available)}")
    return tuple(dict.fromkeys(requested))


def _concept_names(read_conn: Any) -> set[str]:
    with read_conn.cursor() as cur:
        cur.execute("SELECT name FROM concept_registry WHERE domain = 'feature'")
        return {name for (name,) in cur.fetchall()}


def run(args: argparse.Namespace, dsn: str) -> dict[str, Any]:
    if args.tf != "1d":
        raise ValueError("a level 1 sweep cell is per session: --tf 1d only (E21)")
    root = provenance.repo_root(project_root)
    code_commit = "dry-run"
    if not args.dry_run:
        provenance.require_clean(root)
        code_commit = provenance.head_commit(root)
        provenance.require_published(root, code_commit)
    measure_args = argparse.Namespace(
        symbols=args.symbols,
        start=args.start,
        feature_table=args.feature_table,
        dry_run=args.dry_run,
        allow_absent_digests=args.allow_absent_digests,
        run_id=args.run_id,
    )
    t0 = time.monotonic()
    with short_lived_conn(dsn) as read_conn:
        read_conn.autocommit = True
        cfg = load_config_service_sync(read_conn)
        missing = object()
        keys = {_OOS_START_KEY, _VINTAGE_KEY, MIN_NAMES_KEY, *apr_keys_read(args.tf)}
        apr = {k: v for k in keys if (v := cfg.get_sync(k, missing)) is not missing}
        absent = sorted(k for k in (_OOS_START_KEY, _VINTAGE_KEY, MIN_NAMES_KEY) if k not in apr)
        if absent:
            raise ValueError(f"APR keys missing: {absent}")
        oos_start = parse_oos(apr[_OOS_START_KEY])
        min_names = int(apr[MIN_NAMES_KEY])
        concepts = _concept_names(read_conn)
        if args.features:
            unknown = sorted(set(args.features) - concepts)
            if unknown:
                raise ValueError(f"--features {unknown} have no feature concept row")
            concepts = set(args.features)
        runner = IcMeasure(measure_args, dsn)
        with runner.open_tf(read_conn, apr, args.tf, oos_start) as session:
            horizons = _horizons(args.horizons, session.run.horizons)
            session = dataclasses.replace(
                session, run=dataclasses.replace(session.run, horizons=horizons)
            )
            measurement = asyncio.run(_measure_observed(session, concepts, min_names, args.tf))
    _logger.info(
        "ic_sweep_recorder.measured",
        tf=args.tf,
        features=len(measurement.names),
        horizons=list(horizons),
        seconds=round(time.monotonic() - t0, 1),
    )
    if not args.dry_run:
        # The tree was clean and at code_commit when the run started; the measurement took hours.
        provenance.require_clean(root)
        if provenance.head_commit(root) != code_commit:
            raise RuntimeError(f"HEAD moved during the measurement: {code_commit} is stale")
    return asyncio.run(
        record_blocks(
            PostgresLedger(dsn),
            measurement,
            tf=args.tf,
            horizons=horizons,
            min_names=min_names,
            oos_start=oos_start,
            vintage=str(apr[_VINTAGE_KEY]),
            code_commit=code_commit,
            declared_n_looks=args.declared_n_looks,
            dry_run=args.dry_run,
        )
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record IC sweep cells as counted attempts (E21)")
    parser.add_argument("--tf", default="1d", help="timeframe; level 1 cells are 1d only")
    parser.add_argument(
        "--horizons",
        type=lambda v: [int(h) for h in v.split(",") if h],
        default=None,
        help="comma list, a subset of the tf's APR horizons (default: all); a first block is "
        "the E21 volume pilot",
    )
    parser.add_argument(
        "--declared-n-looks",
        type=int,
        default=None,
        help="the attempt count the ledger line declares; must equal what this run records",
    )
    parser.add_argument(
        "--features",
        type=lambda v: [f for f in v.split(",") if f],
        default=None,
        help="measure only these feature columns (a later batch after new features register: "
        "re-sweeping the whole family would record every earlier cell again under a new spec)",
    )
    parser.add_argument("--symbols", nargs="+", help="override the universe (tests and smoke)")
    parser.add_argument("--start", help="ISO 8601 start with a Z or offset")
    parser.add_argument("--feature-table", default="feature_vectors")
    parser.add_argument("--dry-run", action="store_true", help="compute and report, write nothing")
    parser.add_argument("--run-id", type=parse_run_id, default=None)
    parser.add_argument("--allow-absent-digests", action="store_true")
    parser.add_argument("--report", type=Path, default=None, help="write the report as JSON")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    setup_service_logging("logs/ic_sweep_recorder.log")
    args = _parse_args(argv)
    try:
        init_otel_providers(service_name=_JOB)
    except OTelInitError as error:
        _logger.warning("ic_sweep_recorder.otel_init_failed", error=str(error))
    status = "success"
    try:
        report = run(args, Settings().database_url)
        print(canonical_json(report))
        if args.report is not None:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(canonical_json(report))
    except Exception as error:
        status = "failure"
        _logger.error("ic_sweep_recorder.fatal_error", error=str(error))
        raise
    finally:
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    main()
