"""The research runner (architecture step 4): no real-data number outside a recorded run.

Real mode, in order (D-02, D-03):

1. Gate, before any ledger row or data: the spec is committed and unchanged at HEAD (parsed
   from the HEAD blob), its declared memory matches the member definition, every member
   resolves inside the families package, no checked code or spec is dirty or untracked, and
   the ledger holds no real run for the spec hash. Any failure raises RunRefused.
2. The ledger writes one `started` row per member (and the identity rows), before any data is
   read. From here every outcome is recorded; a crash leaves the rows started, which counts.
3. S0 snapshot (content hash verified), S1 residual bar returns and residual forward target,
   S2 members, S3 guards (real-data split, D-25), the shift-floor refusal (evidence runs are
   never refused on power, D-21), S5 per member with R1 and R2, the evidence record, and the
   terminal update.

A guard failure ends every row guard_failed; a refusal ends them refused; any other error
ends the unfinished rows failed and re-raises. Synthetic mode (D-04) runs the same pipeline
on a given panel with no git check, no ledger and no snapshot, so tests exercise the real code.

S3 on real data (D-25): S1 costs minutes per call on the full panel, so it is probed once on a
sub-panel of the spec's first s1_probe_sessions sessions, and the members are probed on the
fixed full-size residual array with the array guards.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import importlib
import math
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

import numpy as np

from src.intelligence.research import (
    guards,
    power,
    provenance,
    snapshot,
    store,
    synthetic,
    transforms,
)
from src.intelligence.research import panel as panel_mod
from src.intelligence.research.book import book_memory_rows, book_timing
from src.intelligence.research.combiner import RidgeSpec
from src.intelligence.research.evaluate import (
    PoolFactory,
    evaluate,
    session_shifts,
    trade_mask,
)
from src.intelligence.research.evidence import (
    coverage_summary,
    evidence_record,
    turnover_per_session,
)
from src.intelligence.research.factors import VINTAGE_1, FactorSpec
from src.intelligence.research.families.common import declared_memory_rows
from src.intelligence.research.ledger import Identity, LedgerRefusal, RunRequest
from src.intelligence.research.panel import Panel, fwd_span
from src.intelligence.research.portfolio import (
    rank_vol_neutral_returns,
    rank_vol_neutral_weights,
    trailing_vol,
)
from src.intelligence.research.spec import (
    TIMING_STATISTIC,
    BookSpec,
    FamilySpec,
    LoadedSpec,
    resolve_member,
)
from src.intelligence.research.timing import timing_test
from src.intelligence.research.transforms import PanelTransform

FACTOR_SPECS = {"vintage_1": VINTAGE_1}


@dataclasses.dataclass(frozen=True)
class BudgetConfig:
    vintage_id: str
    budget_m: int
    screen_alpha: float


class RunRefused(Exception):
    """A real run refused before any ledger row exists (D-02, or a ledger refusal)."""


class LedgerPort(Protocol):
    async def has_real_run(self, spec_hash: str) -> bool: ...

    async def start_runs(self, request, identities, run_concepts) -> dict[str, str]: ...

    async def finish_run(self, run_id, *, status, snapshot_hash, evidence) -> None: ...


async def _default_build(dsn: str, out_dir: Path, spec: FamilySpec) -> Path:
    symbols = await snapshot.universe_symbols(dsn, spec.panel.universe)
    return await snapshot.build_panel(
        dsn,
        out_dir,
        symbols=symbols,
        tf=spec.panel.tf,
        start=spec.panel.start,
        end_exclusive=spec.panel.end_exclusive,
        manifest_extra={"universe": spec.panel.universe},
    )


@dataclasses.dataclass
class RunContext:
    root: Path
    budget: BudgetConfig
    workers: int = 1
    pool_factory: PoolFactory | None = None
    ledger: LedgerPort | None = None
    dsn: str | None = None
    snapshot_dir: Path | None = None
    snapshot: Path | None = None
    build_snapshot: Callable[..., Awaitable[Path]] | None = None


@dataclasses.dataclass(frozen=True)
class Residuals:
    bar: np.ndarray  # S1 residual bar returns [n, m]
    fwd: np.ndarray  # S1 residual forward target [n, m]


def compute_residuals(
    panel: Panel,
    *,
    horizon: int,
    factor_spec: FactorSpec,
    transform: PanelTransform = transforms.IDENTITY,
) -> Residuals:
    """S1 twice, as the panel's transform defines it: residual bar returns (the members' input)
    and the residual forward target."""
    return Residuals(
        bar=transform.s1_bar(panel, factor_spec),
        fwd=transform.s1_target(panel, horizon, factor_spec),
    )


def _member_fn(spec: FamilySpec, member, bars_per_session: int):
    return functools.partial(
        resolve_member(member.signal),
        bars_per_session=bars_per_session,
        coverage_floor=spec.construction.coverage_floor,
        **member.params,
    )


def compute_members(
    spec: FamilySpec, resid_bar: np.ndarray, *, bars_per_session: int
) -> dict[str, np.ndarray]:
    """S2: every member on the same residual bar returns."""
    return {m.name: _member_fn(spec, m, bars_per_session)(resid_bar) for m in spec.members}


def _sub_panel(panel: Panel, sessions: int) -> Panel:
    rows = slice(0, min(sessions, panel.n_sessions) * panel.bars_per_session)
    return dataclasses.replace(
        panel,
        timestamps=panel.timestamps[rows],
        valid=panel.valid[rows],
        open=np.asarray(panel.open[rows]),
        close=np.asarray(panel.close[rows]),
        volume=np.asarray(panel.volume[rows]),
    )


def _probe_rows(panel: Panel, g, transform: PanelTransform) -> np.ndarray:
    """guards.probe_rows plus the rows the transform says S3 must always probe."""
    rows = guards.probe_rows(panel, n_random=g.n_random, seed=g.seed, max_rows=g.max_rows)
    return np.unique(np.concatenate([rows, transform.extra_probe_rows(panel)]))


def real_guards(
    panel: Panel,
    spec: FamilySpec,
    members: dict[str, np.ndarray],
    residuals: Residuals,
    *,
    factor_spec: FactorSpec,
    transform: PanelTransform = transforms.IDENTITY,
    source_probe: Panel | None = None,
) -> dict:
    """S3 split per D-25; raises guards.GuardFailure. Returns the integrity reports (for
    coverage) and a summary for the evidence record. `source_probe`, for a transformed panel,
    is the S0 source sub-panel the transform's own causality probe runs on."""
    bps, n = panel.bars_per_session, len(panel.timestamps)
    g = spec.guards
    reports = {name: guards.integrity(panel, alpha) for name, alpha in members.items()}
    rows = _probe_rows(panel, g, transform)
    reach = {}
    for m in spec.members:
        fn = _member_fn(spec, m, bps)
        declared = m.slot_history_sessions * bps
        guards.causality_probe_array(fn, residuals.bar, rows, seed=g.seed)
        reach[m.name] = guards.memory_check_array(
            fn, residuals.bar, rows[rows < n - declared - 1], declared=declared
        )

    sub = _sub_panel(panel, g.s1_probe_sessions)
    h = spec.horizon

    bar_fn = functools.partial(transform.s1_bar, factor_spec=factor_spec)

    def target_fn(p: Panel) -> np.ndarray:
        return transform.s1_target(p, h, factor_spec)

    sub_rows = _probe_rows(sub, g, transform)
    if transform.probe is not None:
        if source_probe is None:
            raise ValueError(f"transform {transform.name!r} needs its source sub-panel to probe")
        transform.probe(source_probe, sub_rows, g.seed)
    guards.causality_probe(bar_fn, sub, sub_rows, seed=g.seed)
    guards.causality_probe(target_fn, sub, sub_rows, seed=g.seed, reach=fwd_span(h))
    s1_declared = (factor_spec.window_sessions + factor_spec.refit_sessions) * bps
    n_sub = len(sub.timestamps)
    s1_reach = guards.memory_check(
        bar_fn, sub, sub_rows[sub_rows < n_sub - s1_declared - 1], declared=s1_declared
    )
    summary = {
        "probe_rows": len(rows),
        "member_memory_reach": reach,
        "s1_probe_sessions": sub.n_sessions,
        "s1_probe_rows": len(sub_rows),
        "s1_memory_reach": s1_reach,
    }
    return {"reports": reports, "summary": summary}


def family_identities(loaded: LoadedSpec) -> list[Identity]:
    spec = loaded.model
    family = f"family.{spec.family}"
    ids = [
        Identity(
            family,
            "family",
            f"Research family {spec.family} ({spec.prior_source})",
            {"prior_source": spec.prior_source, "spec_path": loaded.path},
        )
    ]
    for m in spec.members:
        ids.append(
            Identity(
                f"member.{spec.family}.{m.name}",
                "member",
                f"Member {m.name} of family {spec.family}",
                {"signal": m.signal, "params": dict(m.params)},
                parents=(family,),
            )
        )
    return ids


def _check_spec(spec: FamilySpec) -> None:
    bps = spec.panel.analysis_bars_per_session
    factor_spec = FACTOR_SPECS[spec.factor_spec]
    for m in spec.members:
        want = declared_memory_rows(m.slot_history_sessions, bps, factor_spec)
        if m.declared_memory_rows != want:
            raise RunRefused(
                f"member {m.name}: declared_memory_rows {m.declared_memory_rows} != {want} "
                f"(slot history {m.slot_history_sessions} sessions plus S1's reach)"
            )
        resolve_member(m.signal)


async def _gate(loaded: LoadedSpec, ctx: RunContext) -> tuple[Path, str]:
    root = provenance.repo_root(ctx.root)
    try:
        blob = provenance.require_committed(root, loaded.path)
        if loaded.blob_sha is not None and blob != loaded.blob_sha:
            raise RunRefused(f"spec blob {blob} is not the loaded blob {loaded.blob_sha}")
        for fam in loaded.families:
            provenance.require_committed(root, fam.path)
        _check_spec_tree(loaded)
        provenance.require_clean(root)
    except provenance.ProvenanceRefusal as error:
        raise RunRefused(str(error)) from error
    if await ctx.ledger.has_real_run(loaded.spec_hash):
        raise RunRefused(f"spec already run: {loaded.spec_hash}")
    return root, provenance.head_commit(root)


def _check_spec_tree(loaded: LoadedSpec) -> None:
    specs = [f.model for f in loaded.families] or [loaded.model]
    for spec in specs:
        if isinstance(spec, FamilySpec):
            _check_spec(spec)
    # A real record's spec hash names its decision statistic (E17): a spec written before E17
    # never runs, and re-scoring one under E17 is a new spec hash, not the old one reused.
    for spec in {id(s): s for s in [loaded.model, *specs]}.values():
        if spec.scoring.timing_statistic != TIMING_STATISTIC:
            raise RunRefused(
                f"spec predates {TIMING_STATISTIC}: scoring.timing_statistic must be "
                f"{TIMING_STATISTIC!r} (methodology-change-ledger E17)"
            )


def _prepare_panel(
    spec: FamilySpec, source: Panel, *, source_hash: str | None, symbols: list[str] | None
) -> tuple[Panel, Panel | None]:
    """The analysis panel from the S0 source: narrowed to the members' universe when the spec
    pins one (B3), then transformed when it names a transform (B1). Returns it with the source
    sub-panel the transform's causality probe runs on (None without a transform)."""
    if symbols is not None:
        source = panel_mod.select_symbols(source, symbols)
        digest = hashlib.sha256("\n".join(source.symbols).encode()).hexdigest()
        source = dataclasses.replace(
            source,
            manifest={
                **source.manifest,
                "members_universe": spec.panel.members_universe,
                "members_universe_hash": digest,
                "members_universe_size": len(source.symbols),
            },
        )
    transform = transforms.resolve(spec.panel.transform)
    probe = None if transform.probe is None else _sub_panel(source, spec.guards.s1_probe_sessions)
    return transform.apply(source, source_hash), probe


async def _analysis_panel(
    spec: FamilySpec, ctx: RunContext, *, real: bool, panel: Panel | None
) -> tuple[Panel, str | None, Panel | None]:
    """(analysis panel, snapshot hash, transform probe source): the S0 snapshot in real mode,
    the given panel in synthetic mode (which applies the transform but no universe filter:
    there is no database)."""
    if real:
        return await _load_panel(spec, ctx)
    prepared, source_probe = _prepare_panel(spec, panel, source_hash=None, symbols=None)
    return prepared, None, source_probe


async def _load_panel(spec: FamilySpec, ctx: RunContext) -> tuple[Panel, str, Panel | None]:
    path = ctx.snapshot
    if path is None:
        build = ctx.build_snapshot or _default_build
        path = await build(ctx.dsn, ctx.snapshot_dir, spec)
    digest = store.verify(path)
    panel = panel_mod.load(path)
    manifest = panel.manifest
    expected = {
        "tf": (panel.tf, spec.panel.tf),
        "bars_per_session": (panel.bars_per_session, spec.panel.bars_per_session),
        "start": (manifest.get("start"), spec.panel.start),
        "end_exclusive": (manifest.get("end_exclusive"), spec.panel.end_exclusive),
        "universe": (manifest.get("universe"), spec.panel.universe),
    }
    wrong = {k: v for k, v in expected.items() if v[0] != v[1]}
    if wrong:
        raise ValueError(f"snapshot does not match the spec: {wrong}")
    symbols = None
    if spec.panel.members_universe == "us_session_equity":
        symbols = await snapshot.us_session_equity_symbols(ctx.dsn)
    panel, source_probe = _prepare_panel(spec, panel, source_hash=digest, symbols=symbols)
    return panel, digest, source_probe


def _vol(spec: FamilySpec | BookSpec, resid_bar: np.ndarray, bps: int) -> np.ndarray:
    c = spec.construction
    window = c.vol_window_sessions * bps
    return trailing_vol(
        resid_bar, window_rows=window, min_finite=math.ceil(c.vol_min_finite_fraction * window)
    )


def _shift_diagnostic(
    alpha: np.ndarray,
    memory: int,
    spec: FamilySpec | BookSpec,
    horizon: int,
    panel: Panel,
    residuals: Residuals,
    vol: np.ndarray,
    ctx: RunContext,
):
    """The whole-session shift null of alpha under R1 and session scoring, a diagnostic since
    E16. (None, 0) when the panel admits no shift for this memory: the diagnostic is then
    absent, which never blocks a record."""
    c, s = spec.construction, spec.scoring
    n, bps = len(panel.timestamps), panel.bars_per_session
    try:
        shifts = session_shifts(n, bps, s.min_shift, memory)
    except ValueError:
        return None, 0
    res = evaluate(
        alpha,
        residuals.fwd,
        panel.close,
        panel.timestamps,
        s.evaluation_config(),
        mv_condition_max=s.mv_condition_max,
        ic_shrinkage_k=s.ic_shrinkage_k,
        shifts=shifts,
        workers=ctx.workers,
        construction=functools.partial(
            rank_vol_neutral_returns,
            vol=vol,
            direction=float(c.direction),
            coverage_floor=c.coverage_floor,
        ),
        memory=memory,
        bars_per_session=bps,
        valid=panel.valid,
        embargo=fwd_span(horizon),
        pool_factory=ctx.pool_factory,
        session_scoring=s.session_scoring,
    )
    return res, len(shifts)


async def run_family(
    loaded: LoadedSpec,
    ctx: RunContext,
    *,
    mode: Literal["real", "synthetic"],
    panel: Panel | None = None,
) -> dict[str, dict]:
    spec = loaded.model
    if not isinstance(spec, FamilySpec):
        raise TypeError("run_family needs a family spec")
    real = mode == "real"
    run_ids: dict[str, str | None] = {m.name: None for m in spec.members}
    code_commit = None
    if real:
        if ctx.ledger is None:
            raise RunRefused("real mode needs a ledger")
        _, code_commit = await _gate(loaded, ctx)
        identities = family_identities(loaded)
        concept = {m.name: f"member.{spec.family}.{m.name}" for m in spec.members}
        request = RunRequest(
            kind="evidence",
            spec_path=loaded.path,
            spec_hash=loaded.spec_hash,
            spec_blob=loaded.blob_sha,
            code_commit=code_commit,
            vintage=ctx.budget.vintage_id,
        )
        try:
            started = await ctx.ledger.start_runs(request, identities, list(concept.values()))
        except LedgerRefusal as error:
            raise RunRefused(str(error)) from error
        run_ids = {name: started[concept[name]] for name in concept}
    else:
        _check_spec(spec)
        if panel is None:
            raise ValueError("synthetic mode needs a panel")

    results: dict[str, dict] = {}
    snapshot_hash: str | None = None

    async def finish(name: str, status: str, evidence: dict) -> None:
        results[name] = {"status": status, "run_id": run_ids[name], "evidence": evidence}
        if real:
            await ctx.ledger.finish_run(
                run_ids[name], status=status, snapshot_hash=snapshot_hash, evidence=evidence
            )

    async def finish_all(status: str, evidence: dict) -> None:
        for m in spec.members:
            if m.name not in results:
                await finish(m.name, status, evidence)

    try:
        panel, snapshot_hash, source_probe = await _analysis_panel(
            spec, ctx, real=real, panel=panel
        )
        factor_spec = FACTOR_SPECS[spec.factor_spec]
        transform = transforms.resolve(spec.panel.transform)
        bps = panel.bars_per_session
        residuals = compute_residuals(
            panel, horizon=spec.horizon, factor_spec=factor_spec, transform=transform
        )
        members = compute_members(spec, residuals.bar, bars_per_session=bps)
        try:
            checked = real_guards(
                panel,
                spec,
                members,
                residuals,
                factor_spec=factor_spec,
                transform=transform,
                source_probe=source_probe,
            )
        except guards.GuardFailure as error:
            await finish_all("guard_failed", {"stage": "S3", "error": str(error)})
            return results
        vol = _vol(spec, residuals.bar, bps)
        cfg = spec.scoring.evaluation_config()
        trade = trade_mask(panel.timestamps, cfg) & panel.valid
        hashes = {
            "spec_hash": loaded.spec_hash,
            "spec_blob": loaded.blob_sha,
            "snapshot_hash": snapshot_hash,
            "code_commit": code_commit,
            **{
                k: panel.manifest[k]
                for k in ("transform", "members_universe", "members_universe_hash")
                if k in panel.manifest
            },
        }
        for m in spec.members:
            alpha = members[m.name]
            weights, has_position = rank_vol_neutral_weights(
                alpha,
                vol=vol,
                direction=float(spec.construction.direction),
                coverage_floor=spec.construction.coverage_floor,
            )
            timing = timing_test(
                weights,
                residuals.fwd,
                has_position,
                trade,
                bars_per_session=bps,
                warmup_sessions=cfg.warmup_sessions,
                memory_sessions=m.slot_history_sessions,
            )
            res, n_shifts = _shift_diagnostic(
                alpha,
                m.declared_memory_rows + fwd_span(spec.horizon),
                spec,
                spec.horizon,
                panel,
                residuals,
                vol,
                ctx,
            )
            record = evidence_record(
                timing,
                res,
                kind="evidence",
                subject=f"member.{spec.family}.{m.name}",
                n_shifts=n_shifts,
                power=None,
                coverage=coverage_summary(checked["reports"][m.name], alpha, trade),
                turnover=turnover_per_session(weights, has_position, trade, bps),
                costs=spec.costs,
                hashes=hashes,
                guards={**checked["summary"], "member": m.name},
                sub_periods=cfg.sub_periods,
            )
            await finish(m.name, "completed", record)
        return results
    except Exception as error:
        unfinished = [m.name for m in spec.members if m.name not in results]
        if unfinished:
            try:
                await finish_all(
                    "failed", {"stage": "run", "error": f"{type(error).__name__}: {error}"}
                )
            except Exception:  # noqa: BLE001 - the original error is the one to raise
                pass
        raise


def _log(stage: str) -> None:
    """Progress to stderr, so a run of several hours can be followed from its log."""
    print(f"{datetime.now(UTC).isoformat(timespec='seconds')} {stage}", file=sys.stderr, flush=True)


def book_identities(loaded: LoadedSpec) -> list[Identity]:
    """Every family's identities plus the book version, whose parents are its families."""
    book = loaded.model
    ids: list[Identity] = []
    for fam in loaded.families:
        ids.extend(family_identities(fam))
    ids.append(
        Identity(
            f"book.{book.book}",
            "book_version",
            f"Book version {book.book} ({book.prior_source})",
            {"spec_path": loaded.path, "families": list(book.families)},
            parents=tuple(f"family.{f.model.family}" for f in loaded.families),
        )
    )
    return ids


def family_module(spec: FamilySpec):
    """The one module a family's members live in; it also owns the family's power plant."""
    modules = {m.signal.rsplit(".", 1)[0] for m in spec.members}
    if len(modules) != 1:
        raise RunRefused(f"family {spec.family}: members span modules {sorted(modules)}")
    return importlib.import_module(modules.pop())


def check_family_plant(families: list[FamilySpec], power_spec):
    """Every refusal the book's plant can raise without real data, run before the ledger so a
    misconfigured book is never charged: one family (a book over several would need one plant
    planting all of them, which no family module defines yet), members in one module that
    defines `validate_plant` and `make_plant`, and the module's own static checks against the
    book's power settings. Returns the module."""
    if len(families) != 1:
        raise RunRefused(f"no power plant spans {len(families)} families")
    fam = families[0]
    module = family_module(fam)
    for name in ("validate_plant", "make_plant"):
        if not callable(getattr(module, name, None)):
            raise RunRefused(f"{module.__name__} defines no {name}")
    try:
        module.validate_plant(power_spec, fam.panel.analysis_bars_per_session)
    except ValueError as error:
        raise RunRefused(f"{module.__name__}: {error}") from error
    return module


def family_plant(families: list[FamilySpec], power_spec, residuals: Residuals, bps: int):
    """The book's synthetic plant, from its family's `make_plant` and the real residuals."""
    return check_family_plant(families, power_spec).make_plant(power_spec, residuals, bps)


def _power_problem(
    book: BookSpec,
    families,
    panel: Panel,
    residuals: Residuals,
    bar: float,
    members,
    ridge,
    memory_sessions: int,
):
    """Synthetic replicates planted on the real test's availability: members read S1 residual
    bar returns, which are missing wherever S1 cannot fit (each name's loading warm-up, not
    only its missing bars), and the target has its own pattern. Planting on the close mask
    would widen the synthetic cross-sections and overstate power, the one error the refusal
    exists to prevent. The masks carry availability only, no return values."""
    p = book.power
    bps = panel.bars_per_session
    plant_gen = family_plant(families, p, residuals, bps)
    finite_mask = np.isfinite(residuals.bar)
    target_mask = np.isfinite(residuals.fwd)
    plant = synthetic.calibrate_plant(
        plant_gen,
        finite_mask,
        members=members,
        coverage_floor=book.construction.coverage_floor,
        target_ic=p.planted_rank_ic,
        tolerance=p.calibration_tolerance,
        n_panels=p.calibration_panels,
        seed=p.calibration_seed,
        target_mask=target_mask,
    )
    c = book.construction
    window = c.vol_window_sessions * bps
    problem = power.PowerProblem(
        plant=plant_gen,
        plant_coef=plant.plant_coef,
        finite_mask=finite_mask,
        target_mask=target_mask,
        dates=np.asarray(panel.timestamps),
        valid=np.asarray(panel.valid),
        members=tuple(members),
        coverage_floor=c.coverage_floor,
        direction=float(c.direction),
        ridge=ridge,
        vol_window_rows=window,
        vol_min_finite=math.ceil(c.vol_min_finite_fraction * window),
        cfg=book.scoring.evaluation_config(),
        memory_sessions=memory_sessions,
        bar=bar,
    )
    return problem, plant


async def run_book(
    loaded: LoadedSpec,
    ctx: RunContext,
    *,
    mode: Literal["real", "synthetic"],
    panel: Panel | None = None,
    power_replicates: int | None = None,
) -> dict:
    """The book test (S8) of one book version, budget-charged in real mode (D-08, D-11)."""
    book = loaded.model
    if not isinstance(book, BookSpec):
        raise TypeError("run_book needs a book spec")
    real = mode == "real"
    if real and power_replicates is not None:
        raise ValueError("power_replicates overrides the spec in synthetic mode only")
    families = [f.model for f in loaded.families]
    fam0 = families[0]
    check_family_plant(families, book.power)  # before the ledger: a refusal is never charged
    subject = f"book.{book.book}"
    run_id = None
    code_commit = None
    if real:
        if ctx.ledger is None:
            raise RunRefused("real mode needs a ledger")
        _, code_commit = await _gate(loaded, ctx)
        request = RunRequest(
            kind="book_test",
            spec_path=loaded.path,
            spec_hash=loaded.spec_hash,
            spec_blob=loaded.blob_sha,
            code_commit=code_commit,
            vintage=ctx.budget.vintage_id,
            budget_m=ctx.budget.budget_m,
            screen_alpha=ctx.budget.screen_alpha,
        )
        try:
            started = await ctx.ledger.start_runs(request, book_identities(loaded), [subject])
        except LedgerRefusal as error:
            raise RunRefused(str(error)) from error
        run_id = started[subject]
    else:
        for fam in families:
            _check_spec(fam)
        if panel is None:
            raise ValueError("synthetic mode needs a panel")

    result: dict = {}
    snapshot_hash: str | None = None

    async def finish(status: str, evidence: dict) -> dict:
        result.update(status=status, run_id=run_id, evidence=evidence)
        if real:
            await ctx.ledger.finish_run(
                run_id, status=status, snapshot_hash=snapshot_hash, evidence=evidence
            )
        return result

    try:
        _log("S0 snapshot")
        panel, snapshot_hash, source_probe = await _analysis_panel(
            fam0, ctx, real=real, panel=panel
        )
        factor_spec = FACTOR_SPECS[fam0.factor_spec]
        bps, n = panel.bars_per_session, len(panel.timestamps)
        _log("S1 residuals")
        transform = transforms.resolve(fam0.panel.transform)
        residuals = compute_residuals(
            panel, horizon=fam0.horizon, factor_spec=factor_spec, transform=transform
        )
        _log("S2 members")
        columns, members, memories, slot_histories = [], [], [], []
        for fam in families:
            fam_members = compute_members(fam, residuals.bar, bars_per_session=bps)
            _log(f"S3 guards {fam.family}")
            try:
                real_guards(
                    panel,
                    fam,
                    fam_members,
                    residuals,
                    factor_spec=factor_spec,
                    transform=transform,
                    source_probe=source_probe,
                )
            except guards.GuardFailure as error:
                return await finish(
                    "guard_failed", {"stage": "S3", "family": fam.family, "error": str(error)}
                )
            for m in fam.members:
                columns.append(fam_members[m.name])
                members.append((resolve_member(m.signal), dict(m.params)))
                memories.append(m.declared_memory_rows)
                slot_histories.append(m.slot_history_sessions)
            del fam_members
        stack = np.stack(columns, axis=2).astype(np.float32)
        del columns

        alpha_level, budget_m = ctx.budget.screen_alpha, ctx.budget.budget_m
        bar = alpha_level / budget_m
        ridge = RidgeSpec(
            window_rows=book.combiner.window_sessions * bps,
            refit_rows=book.combiner.refit_sessions * bps,
            penalty=book.combiner.penalty,
            embargo=fwd_span(fam0.horizon),
            min_obs=book.combiner.min_obs,
        )

        # Refusal before any real-data statistic (E16 (d)): synthetic power at the bar.
        _log("power: calibrating the plant")
        problem, plant = _power_problem(
            book, families, panel, residuals, bar, members, ridge, max(slot_histories)
        )
        _log(f"power: plant {plant.plant_coef:.6g} (IC {plant.achieved_ic:.6g}); replicates")
        run = power.estimate_power(
            problem,
            replicates=power_replicates or book.power.replicates,
            min_power=guards.MIN_POWER,
            seed=book.power.seed,
            workers=ctx.workers,
            pool_factory=ctx.pool_factory,
        )
        del problem
        d = run.decision
        power_record = {
            "powered": d.powered,
            "passes": d.passes,
            "failures": d.failures,
            "replicates": d.replicates,
            "decided_after": d.decided_after,
            "min_power": d.min_power,
            "bar": bar,
            "planted_rank_ic": book.power.planted_rank_ic,
            "plant_coef": plant.plant_coef,
            "achieved_ic": plant.achieved_ic,
            "ic_se": plant.ic_se,
            "calibration_iterations": plant.iterations,
            "participation_ratio": book.power.participation_ratio,
            "seconds": run.seconds,
        }
        _log(f"power: {'powered' if d.powered else 'underpowered'} ({d.passes}/{d.decided_after})")
        try:
            guards.require_testable(power=float(d.powered))
        except guards.GuardFailure:
            return await finish(
                "refused",
                {
                    "stage": "refusal",
                    "refusal": f"underpowered at IC {book.power.planted_rank_ic}",
                    "power": power_record,
                },
            )

        _log("S8 book test")
        vol = _vol(book, residuals.bar, bps)
        cfg = book.scoring.evaluation_config()
        c = book.construction
        trade = trade_mask(panel.timestamps, cfg) & panel.valid
        booked = book_timing(
            stack,
            residuals.fwd,
            vol,
            trade,
            ridge=ridge,
            direction=float(c.direction),
            coverage_floor=c.coverage_floor,
            bars_per_session=bps,
            warmup_sessions=cfg.warmup_sessions,
            memory_sessions=max(slot_histories),
        )
        del stack
        _log("S8 shift-null diagnostic")
        res, n_shifts = _shift_diagnostic(
            booked.combined,
            book_memory_rows(memories, fam0.horizon, ridge),
            book,
            fam0.horizon,
            panel,
            residuals,
            vol,
            ctx,
        )
        p_value = booked.timing.hac.p
        record = evidence_record(
            booked.timing,
            res,
            kind="book_test",
            subject=subject,
            n_shifts=n_shifts,
            power=power_record,
            coverage=coverage_summary(
                guards.integrity(panel, booked.combined), booked.combined, trade
            ),
            turnover=turnover_per_session(booked.weights, booked.has_position, trade, bps),
            costs=book.costs,
            hashes={
                "spec_hash": loaded.spec_hash,
                "spec_blob": loaded.blob_sha,
                "snapshot_hash": snapshot_hash,
                "code_commit": code_commit,
                "family_specs": {f.path: f.spec_hash for f in loaded.families},
            },
            guards={"families": [f.family for f in families]},
            sub_periods=cfg.sub_periods,
            screen={
                "statistic": "hac_timing_t_e17",
                "alpha": alpha_level,
                "budget_m": budget_m,
                "bar": bar,
                "p": p_value,
                "p_below_bar": p_value < bar,
            },
        )
        _log("done")
        return await finish("completed", record)
    except Exception as error:
        if not result:
            try:
                await finish(
                    "failed", {"stage": "run", "error": f"{type(error).__name__}: {error}"}
                )
            except Exception:  # noqa: BLE001 - the original error is the one to raise
                pass
        raise
