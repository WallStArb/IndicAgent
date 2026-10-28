"""Pod books (design 4.1, plan 187-10): families on different clocks combine only at the P&L
level. A pod's series is the session-level sum of its member books' recorded E17 D_s series on
the sessions every member tested: never recomputed, never filled. A session one member lacks is
dropped and counted per member, so a pod over disjoint calendars has no series and is refused,
not zero-filled.

Each member is pinned in the pod spec by run_id and `series_sha256`, the content hash of the
recorded series, so a later rerun of a member book cannot change the pod's inputs.

Pure functions over arrays; the ledger reads and the run live with the runner (Task 2).
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Sequence

import numpy as np

from src.intelligence.research.ledger import AttemptSeries


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
