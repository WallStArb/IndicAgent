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
import math
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal, Protocol

import numpy as np

from src.intelligence.research import guards, provenance, snapshot, store
from src.intelligence.research import panel as panel_mod
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
from src.intelligence.research.factors import VINTAGE_1, FactorSpec, residual_returns
from src.intelligence.research.families.common import declared_memory_rows
from src.intelligence.research.ledger import Identity, LedgerRefusal, RunRequest
from src.intelligence.research.panel import Panel, bar_returns, forward_returns, fwd_span
from src.intelligence.research.portfolio import (
    rank_vol_neutral_returns,
    rank_vol_neutral_weights,
    trailing_vol,
)
from src.intelligence.research.spec import FamilySpec, LoadedSpec, resolve_member

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

    async def charged_book_tests(self, vintage: str) -> int: ...

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


def compute_residuals(panel: Panel, *, horizon: int, factor_spec: FactorSpec) -> Residuals:
    """S1 twice: residual bar returns (the members' input) and the residual forward target
    (enter at the next open, exit `horizon` bars later or at the session close)."""
    bps = panel.bars_per_session
    bar = residual_returns(bar_returns(panel), bars_per_session=bps, spec=factor_spec).residual
    raw = forward_returns(panel.open, horizon, panel.session, closes=panel.close)
    fwd = residual_returns(raw, bars_per_session=bps, horizon=horizon, spec=factor_spec).residual
    return Residuals(bar=bar, fwd=fwd)


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


def real_guards(
    panel: Panel,
    spec: FamilySpec,
    members: dict[str, np.ndarray],
    residuals: Residuals,
    *,
    factor_spec: FactorSpec,
) -> dict:
    """S3 split per D-25; raises guards.GuardFailure. Returns the integrity reports (for
    coverage) and a summary for the evidence record."""
    bps, n = panel.bars_per_session, len(panel.timestamps)
    g = spec.guards
    reports = {name: guards.integrity(panel, alpha) for name, alpha in members.items()}
    rows = guards.probe_rows(panel, n_random=g.n_random, seed=g.seed, max_rows=g.max_rows)
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

    def s1_bar(p: Panel) -> np.ndarray:
        return residual_returns(
            bar_returns(p), bars_per_session=p.bars_per_session, spec=factor_spec
        ).residual

    def s1_target(p: Panel) -> np.ndarray:
        raw = forward_returns(p.open, h, p.session, closes=p.close)
        return residual_returns(
            raw, bars_per_session=p.bars_per_session, horizon=h, spec=factor_spec
        ).residual

    sub_rows = guards.probe_rows(sub, n_random=g.n_random, seed=g.seed, max_rows=g.max_rows)
    guards.causality_probe(s1_bar, sub, sub_rows, seed=g.seed)
    guards.causality_probe(s1_target, sub, sub_rows, seed=g.seed, reach=fwd_span(h))
    s1_declared = (factor_spec.window_sessions + factor_spec.refit_sessions) * bps
    n_sub = len(sub.timestamps)
    s1_reach = guards.memory_check(
        s1_bar, sub, sub_rows[sub_rows < n_sub - s1_declared - 1], declared=s1_declared
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
    bps = spec.panel.bars_per_session
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


async def _load_panel(spec: FamilySpec, ctx: RunContext) -> tuple[Panel, str]:
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
    return panel, digest


def _vol(spec: FamilySpec, resid_bar: np.ndarray, bps: int) -> np.ndarray:
    c = spec.construction
    window = c.vol_window_sessions * bps
    return trailing_vol(
        resid_bar, window_rows=window, min_finite=math.ceil(c.vol_min_finite_fraction * window)
    )


def _evaluate_member(
    spec: FamilySpec,
    member,
    alpha: np.ndarray,
    panel: Panel,
    residuals: Residuals,
    vol: np.ndarray,
    shifts: np.ndarray,
    ctx: RunContext,
):
    c, s = spec.construction, spec.scoring
    construction = functools.partial(
        rank_vol_neutral_returns,
        vol=vol,
        direction=float(c.direction),
        coverage_floor=c.coverage_floor,
    )
    return evaluate(
        alpha,
        residuals.fwd,
        panel.close,
        panel.timestamps,
        s.evaluation_config(),
        mv_condition_max=s.mv_condition_max,
        ic_shrinkage_k=s.ic_shrinkage_k,
        shifts=shifts,
        workers=ctx.workers,
        construction=construction,
        memory=member.declared_memory_rows + fwd_span(spec.horizon),
        bars_per_session=panel.bars_per_session,
        valid=panel.valid,
        embargo=fwd_span(spec.horizon),
        pool_factory=ctx.pool_factory,
        session_scoring=s.session_scoring,
    )


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
        if real:
            panel, snapshot_hash = await _load_panel(spec, ctx)
        factor_spec = FACTOR_SPECS[spec.factor_spec]
        bps = panel.bars_per_session
        residuals = compute_residuals(panel, horizon=spec.horizon, factor_spec=factor_spec)
        members = compute_members(spec, residuals.bar, bars_per_session=bps)
        try:
            checked = real_guards(panel, spec, members, residuals, factor_spec=factor_spec)
        except guards.GuardFailure as error:
            await finish_all("guard_failed", {"stage": "S3", "error": str(error)})
            return results
        n = len(panel.timestamps)
        shift_sets = {}
        try:
            for m in spec.members:
                shifts = session_shifts(
                    n, bps, spec.scoring.min_shift, m.declared_memory_rows + fwd_span(spec.horizon)
                )
                shift_sets[m.name] = shifts
                guards.require_testable(
                    n_shifts=len(shifts),
                    alpha_level=ctx.budget.screen_alpha,
                    budget_m=ctx.budget.budget_m,
                    power=None,
                )
        except guards.GuardFailure as error:
            counts = {k: len(v) for k, v in shift_sets.items()}
            await finish_all(
                "refused", {"stage": "refusal", "error": str(error), "n_shifts": counts}
            )
            return results

        vol = _vol(spec, residuals.bar, bps)
        cfg = spec.scoring.evaluation_config()
        trade = trade_mask(panel.timestamps, cfg) & panel.valid
        hashes = {
            "spec_hash": loaded.spec_hash,
            "spec_blob": loaded.blob_sha,
            "snapshot_hash": snapshot_hash,
            "code_commit": code_commit,
        }
        for m in spec.members:
            alpha = members[m.name]
            res = _evaluate_member(spec, m, alpha, panel, residuals, vol, shift_sets[m.name], ctx)
            weights, has_position = rank_vol_neutral_weights(
                alpha,
                vol=vol,
                direction=float(spec.construction.direction),
                coverage_floor=spec.construction.coverage_floor,
            )
            record = evidence_record(
                res,
                kind="evidence",
                subject=f"member.{spec.family}.{m.name}",
                n_shifts=len(shift_sets[m.name]),
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
