"""Snapshot read and integrity check that need no database.

Source: scripts/analysis/sleeve_walk_forward/snapshot.py lines 249-299, promoted verbatim
(phase 186-03, D-11). Carries no database imports: it reads only content-hashed .npy files and
meta.json from disk, and delegates the integrity check to src.intelligence.research.store
(pure file hashing, no driver), so the determinism tool imports no asyncpg, no
src.config.settings, no services.* and no src.intelligence.research.snapshot.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from scripts.research.determinism.results import GroupArrays, Snapshot
from src.intelligence.research import store


def verify_snapshot(path: Path) -> None:
    """Recompute the content hash and compare it with the directory name."""
    store.verify(path)


def load_snapshot(path: Path) -> Snapshot:
    path = Path(path)
    meta = json.loads((path / "meta.json").read_text())

    def a(name: str) -> np.ndarray:
        return np.load(path / f"{name}.npy", mmap_mode="r", allow_pickle=False)

    sessions = a("sessions")
    group_of = a("all_group")
    labels = {g: a(f"labels_{g}") for g in meta["manifest"]["groups"]}
    session_idx = a("all_session_idx")

    def rows(mask: np.ndarray | None, label_by_session: np.ndarray) -> GroupArrays:
        """mask=None keeps the memory-mapped arrays as they are (no copy)."""
        idx = session_idx if mask is None else session_idx[mask]

        def pick(x: np.ndarray) -> np.ndarray:
            return x if mask is None else x[mask]

        return GroupArrays(
            symbols=pick(a("all_symbol")),
            bar_ts=pick(a("all_bar_ts")),
            session_idx=idx,
            X=pick(a("all_X")),
            returns=pick(a("all_returns")),
            complete=pick(a("all_complete")),
            labels=label_by_session[idx],
        )

    has_fr = a("all_has_fr")
    equity = labels.get("equity", np.full(len(sessions), ""))
    return Snapshot(
        sessions=sessions,
        groups={g: rows((group_of == g) & has_fr, labels[g]) for g in labels},
        all_1d=rows(None, equity),
        sleeve_features=a("sleeve_features"),
        sleeve_has_row=a("sleeve_has_row"),
        sleeve_opens=a("sleeve_opens"),
        sleeve_closes=a("sleeve_closes"),
        equity_labels=equity,
        feature_names=meta["manifest"]["feature_names"],
        broadcast_mask=a("broadcast_mask"),
        feature_to_group=meta["feature_to_group"],
        apr={k: tuple(v) for k, v in meta["apr"].items()},
        manifest=meta["manifest"],
    )
