"""Pod books (design 4.1, plan 187-10): families on different clocks combine only at the P&L
level. A pod's series is the session-level sum of its member books' recorded E17 D_s series on
the sessions every member tested: never recomputed, never filled. A session one member lacks is
dropped and counted per member, so a pod over disjoint calendars has no series and is refused,
not zero-filled.

Each member is pinned in the pod spec by run_id and `series_sha256`, the content hash of the
recorded series, so a later rerun of a member book cannot change the pod's inputs.

`pod_series` and `series_sha256` are pure. `run_pod` records a pod as its own counted attempt
(kind pod_book) through S6: every refusal (a pin that does not resolve to a completed,
powered book test of the member spec's current hash on this vintage with exactly the pinned
series, or no common session) comes before the ledger counts anything.

Statistic: hac.hac_mean_test on the pod series, E17's decision statistic, with the series'
annualized Sharpe. A pod adds no fitted part and no new data, so its power is inherited: each
member attempt carries a passing power block.
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
from collections.abc import Sequence
from typing import Literal

import numpy as np

from src.intelligence.research.evaluate import SESSIONS_PER_YEAR
from src.intelligence.research.evidence import SCHEMA
from src.intelligence.research.ledger import AttemptSeries, Identity, LedgerRefusal, RunRequest
from src.intelligence.research.provenance import git_author
from src.intelligence.research.recipe import pod_recipes
from src.intelligence.research.runner import RunContext, RunRefused, _gate
from src.intelligence.research.spec import LoadedSpec, PodBookSpec
from src.intelligence.statistics.hac import hac_mean_test


def series_sha256(series: AttemptSeries) -> str:
    """Content hash of a recorded series: sha256 of its sessions (int64 days since the epoch,
    little-endian) followed by its D_s values (float64, little-endian)."""
    sessions = np.asarray(series.sessions, dtype="datetime64[D]").astype("<i8")
    values = np.asarray(series.values, dtype="<f8")
    if sessions.shape != values.shape:
        raise ValueError(f"{sessions.shape} sessions for {values.shape} values")
    return hashlib.sha256(sessions.tobytes() + values.tobytes()).hexdigest()


@dataclasses.dataclass(frozen=True)
class PodSeries:
    series: AttemptSeries | None  # None when the members share no tested session
    dropped: tuple[int, ...]  # per member, its tested sessions outside the common set


def pod_series(members: Sequence[AttemptSeries]) -> PodSeries:
    """The sum of the members' D_s on the sessions every member tested, in session order."""
    if len(members) < 2:
        raise ValueError(f"a pod needs at least two member series, got {len(members)}")
    sessions = [np.asarray(m.sessions, dtype="datetime64[D]") for m in members]
    for s, m in zip(sessions, members, strict=True):
        if s.shape != np.shape(m.values):
            raise ValueError(f"{s.shape} sessions for {np.shape(m.values)} values")
        if np.any(s[1:] <= s[:-1]):
            raise ValueError("a member series must be in strictly increasing session order")
        if not np.all(np.isfinite(m.values)):
            raise ValueError("a recorded series holds tested (finite) sessions only")
    common = sessions[0]
    for s in sessions[1:]:
        common = np.intersect1d(common, s, assume_unique=True)
    dropped = tuple(len(s) - len(common) for s in sessions)
    if common.size == 0:
        return PodSeries(None, dropped)
    total = np.zeros(common.size, dtype=np.float64)
    for s, m in zip(sessions, members, strict=True):
        total += np.asarray(m.values, dtype=np.float64)[np.searchsorted(s, common)]
    return PodSeries(AttemptSeries(sessions=common, values=total), dropped)


# The member attempts' decision statistic, and so the pod's (E17).
POD_STATISTIC = "hac_timing_t_e17"


def pod_identity(loaded: LoadedSpec) -> Identity:
    """The pod's construction identity; its parents are the member book versions."""
    pod = loaded.model
    return Identity(
        f"pod.{pod.pod}",
        "pod",
        f"Pod book {pod.pod} ({pod.prior_source})",
        {"spec_path": loaded.path, "books": [b.book for b in pod.books]},
        parents=tuple(f"book.{b.model.book}" for b in loaded.books),
    )


async def _member_series(loaded: LoadedSpec, ctx: RunContext) -> list[dict]:
    """Each member's pinned attempt, checked; RunRefused on the first pin that fails."""
    out = []
    for pin, book in zip(loaded.model.books, loaded.books, strict=True):
        run = await ctx.ledger.pinned_run(pin.run_id)
        where = f"pod member {pin.book} run {pin.run_id}"
        if run is None:
            raise RunRefused(f"{where}: no such run")
        if run.kind != "book_test" or run.status != "completed":
            raise RunRefused(f"{where}: a {run.status} {run.kind}, not a completed book_test")
        if run.spec_hash != book.spec_hash:
            raise RunRefused(f"{where}: spec hash {run.spec_hash} is not {book.spec_hash}")
        if run.vintage != ctx.budget.vintage_id:
            raise RunRefused(f"{where}: vintage {run.vintage} is not {ctx.budget.vintage_id}")
        if run.series is None:
            raise RunRefused(f"{where}: no stored series")
        if series_sha256(run.series) != pin.series_sha256:
            raise RunRefused(f"{where}: stored series does not hash to the pin")
        if not (run.evidence.get("power") or {}).get("powered"):
            raise RunRefused(f"{where}: no passing power block")
        statistic = (run.evidence.get("decision") or {}).get("statistic")
        if statistic != POD_STATISTIC:
            raise RunRefused(f"{where}: scored by {statistic!r}, not {POD_STATISTIC}")
        out.append({"pin": pin, "book": book, "run": run})
    return out


async def run_pod(
    loaded: LoadedSpec, ctx: RunContext, *, mode: Literal["real", "exploration"]
) -> dict:
    """The pod's one counted attempt: sum the pinned member series, HAC-test the sum, record it
    with its series through S6. Real mode runs a spec once; exploration may repeat it."""
    pod = loaded.model
    if not isinstance(pod, PodBookSpec):
        raise TypeError("run_pod needs a pod_book spec")
    if ctx.ledger is None:
        raise RunRefused(f"{mode} mode needs a ledger")
    run_ids = [b.run_id for b in pod.books]
    if len(set(run_ids)) != len(run_ids):
        raise RunRefused(f"pod {pod.pod}: two members pin the same run {run_ids}")
    members = await _member_series(loaded, ctx)
    combined = pod_series([m["run"].series for m in members])
    if combined.series is None:
        raise RunRefused(f"pod {pod.pod}: the member books share no tested session")
    # The statistic before the ledger: a pod it cannot score is refused, never counted (E18).
    values = combined.series.values
    try:
        hac = hac_mean_test(values)
    except ValueError as error:
        raise RunRefused(f"pod {pod.pod}: {error}") from error
    sd = float(np.std(values, ddof=1))
    sharpe = float(np.mean(values)) / sd * math.sqrt(SESSIONS_PER_YEAR) if sd > 0 else None
    turnover = [m["run"].evidence.get("turnover_per_session") for m in members]
    root, code_commit = await _gate(loaded, ctx, once=mode == "real")
    subject = f"pod.{pod.pod}"
    request = RunRequest(
        kind="pod_book",
        spec_path=loaded.path,
        spec_hash=loaded.spec_hash,
        spec_blob=loaded.blob_sha,
        code_commit=code_commit,
        vintage=ctx.budget.vintage_id,
        mode=mode,
        recipes=pod_recipes(loaded),
        informed_by=ctx.informed_by,
        author=git_author(root),
    )
    try:
        started = await ctx.ledger.start_runs(request, [pod_identity(loaded)], [subject])
    except LedgerRefusal as error:
        raise RunRefused(str(error)) from error
    run_id = started[subject]
    evidence = {
        "schema": SCHEMA,
        "kind": "pod_book",
        "subject": subject,
        "decision": {
            "statistic": POD_STATISTIC,
            "mean_session_pnl": hac.mean,
            "se": hac.se,
            "t": hac.t,
            "p": hac.p,
            "lag": hac.lag,
            "n_sessions": hac.n,
            "annualized_sharpe": sharpe,
        },
        # The members' gross turnover adds: each book trades its own positions.
        "turnover_per_session": None if None in turnover else float(sum(turnover)),
        "power": {"inherited": True, "members_powered": len(members)},
        "members": [
            {
                "spec_path": m["book"].path,
                "spec_hash": m["book"].spec_hash,
                "run_id": m["pin"].run_id,
                "series_sha256": m["pin"].series_sha256,
                "sessions_dropped": dropped,
            }
            for m, dropped in zip(members, combined.dropped, strict=True)
        ],
        "hashes": {
            "spec_hash": loaded.spec_hash,
            "spec_blob": loaded.blob_sha,
            "code_commit": code_commit,
            "book_specs": {b.path: b.spec_hash for b in loaded.books},
        },
    }
    try:
        await ctx.ledger.finish_run(
            run_id,
            status="completed",
            snapshot_hash=None,
            evidence=evidence,
            series=combined.series,
        )
    except Exception as error:
        try:  # a started row always reaches a terminal status
            await ctx.ledger.finish_run(
                run_id,
                status="failed",
                snapshot_hash=None,
                evidence={"stage": "run", "error": f"{type(error).__name__}: {error}"},
                series=combined.series,
            )
        except Exception:  # noqa: BLE001 - the original error is the one to raise
            pass
        raise
    return {"status": "completed", "run_id": run_id, "evidence": evidence}
