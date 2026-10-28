"""Admission of fitted books: a ridge combiner or a horizon rule with kappa < 1 (plan 187-08).

A book whose combiner is fitted (ridge) or whose positions are smoothed (kappa < 1) changes the
E17 statistic's memory, so it is admitted for a real run only when the E17 H0 battery has shown
its cells hold size. The evidence is a committed certificate (`CERTIFICATE_PATH`), written by
scripts/research/certify_fitted_books.py from a battery record: per cell, the book arm's
rejections against the bound at each level, the panel length, and a fingerprint of the code the
battery exercised. The fingerprint is a hash per function or class, read from source, so an
unrelated edit to a file does not void the certificate, while any edit to the statistic, the
combiner, the horizon rule, book_memory or the battery itself does.

Pure decisions plus file reads; the runner calls `fitted_book_refusal` before the ledger, and
the mode is a plain argument so other admission checks (phase 184's route check) reuse it.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Callable
from pathlib import Path

CERTIFICATE_PATH = "research/certificates/e17_fitted_books.json"
SCHEMA = "e17_fitted_book_certificate_v1"
# The panel length a battery is judged at (the owner's StepM decision of 2026-10-27, applied to
# the fitted-book cells: on 1,500-session panels E17 runs slightly above nominal everywhere).
REAL_SESSIONS = 4000
# The levels each certified cell's book arm must hold at (187-08 review amendment: 0.00167 is
# not resolvable at 1,000 simulations and is disclosed, not gated).
GATED_LEVELS = ("0.05", "0.01")

# Every top-level definition that sets a fitted book's statistic, its L or the battery that
# certifies it: (path, top-level name, a function, class or module-level constant), None for
# the whole module. The battery module is whole: any edit to it voids the certificate.
CERTIFIED_CODE = (
    ("src/intelligence/research/horizon.py", "REACH_CUTOFF"),
    ("src/intelligence/research/horizon.py", "_read_only"),
    ("src/intelligence/research/horizon.py", "HorizonRule"),
    ("src/intelligence/research/combiner.py", "EqualWeight"),
    ("src/intelligence/research/combiner.py", "RidgeSpec"),
    ("src/intelligence/research/combiner.py", "refit_positions"),
    ("src/intelligence/research/combiner.py", "_EXCHANGE"),
    ("src/intelligence/research/combiner.py", "exchange_sessions"),
    ("src/intelligence/research/combiner.py", "anchored_refit_positions"),
    ("src/intelligence/research/combiner.py", "_prefix_moments"),
    ("src/intelligence/research/combiner.py", "_row_moments_kernel"),
    ("src/intelligence/research/combiner.py", "walk_forward_ridge"),
    ("src/intelligence/research/combiner.py", "_subset_forecast"),
    ("src/intelligence/research/timing.py", "MIN_HISTORY_SESSIONS"),
    ("src/intelligence/research/timing.py", "e17_memory"),
    ("src/intelligence/research/timing.py", "timing_series"),
    ("src/intelligence/research/timing.py", "timing_test"),
    ("src/intelligence/statistics/hac.py", "newey_west_lag"),
    ("src/intelligence/statistics/hac.py", "hac_mean_test"),
    ("src/intelligence/research/book.py", "BookMemory"),
    ("src/intelligence/research/book.py", "book_memory"),
    ("src/intelligence/research/book.py", "book_memory_rows"),
    ("src/intelligence/research/panel.py", "fwd_span"),
    ("src/intelligence/research/portfolio.py", "_check_r1_args"),
    ("src/intelligence/research/portfolio.py", "_rank_vol_neutral_rows"),
    ("src/intelligence/research/portfolio.py", "rank_vol_neutral_weights"),
    ("src/intelligence/research/portfolio.py", "average_ranks"),
    ("src/intelligence/research/portfolio.py", "trailing_vol"),
    ("src/intelligence/research/null_battery.py", None),
)


def _defines(node: ast.stmt, name: str) -> bool:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return node.name == name
    if isinstance(node, ast.Assign):
        return any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
    if isinstance(node, ast.AnnAssign):
        return isinstance(node.target, ast.Name) and node.target.id == name
    return False


def _segment(text: str, name: str | None) -> str:
    """The source of one top-level definition, decorators included."""
    if name is None:
        return text
    lines = text.splitlines()
    for node in ast.parse(text).body:
        if _defines(node, name):
            first = min([d.lineno for d in getattr(node, "decorator_list", [])] + [node.lineno])
            return "\n".join(lines[first - 1 : node.end_lineno])
    raise LookupError(f"{name} not found")


def ridge_config(battery_module) -> dict:
    """The one ridge configuration the battery's ridge cells ran (null_battery's book_v1 pins)."""
    return {
        "window_sessions": battery_module._RIDGE_WINDOW_SESSIONS,
        "refit_sessions": battery_module._RIDGE_REFIT_SESSIONS,
        "penalty": battery_module._RIDGE_PENALTY,
        "min_obs": battery_module._RIDGE_MIN_OBS,
    }


def code_fingerprint(read: Callable[[str], str]) -> dict[str, str]:
    """{"path:name": sha256 of its source} for every CERTIFIED_CODE entry; `read(path)` returns a
    file's text (the working tree, or a commit through git show)."""
    out = {}
    for path, name in CERTIFIED_CODE:
        out[f"{path}:{name or '*'}"] = hashlib.sha256(
            _segment(read(path), name).encode()
        ).hexdigest()
    return out


def required_cells(
    combiner_kind: str, kappa: float | None, features: tuple[str, ...] = ()
) -> tuple[str, ...]:
    """The gating battery cells a fitted book needs; () for a plain equal-weight, unsmoothed
    book. `features` are the combiner's optional rules in use (plan 187-09: min_members,
    refit_anchor, in_fold_signs); each needs its own cell, `<kind>_<feature>`."""
    extra = tuple(f"{combiner_kind}_{f}" for f in features)
    return _base_cells(combiner_kind, kappa) + extra


def _base_cells(combiner_kind: str, kappa: float | None) -> tuple[str, ...]:
    if combiner_kind == "ridge" and kappa is not None:
        # Only a diagnostic cell (ridge_kappa_hostile) combines the two; nothing certifies it.
        return ("ridge_kappa",)
    if combiner_kind == "ridge":
        return ("ridge", "ridge_static")
    if kappa is not None:
        return (f"kappa_{kappa:g}", f"kappa_{kappa:g}_static")
    return ()


def fitted_book_refusal(
    combiner_kind: str,
    kappa: float | None,
    mode: str,
    certificate: dict | None,
    fingerprint: dict[str, str],
    ridge: dict | None = None,
    features: tuple[str, ...] = (),
) -> str | None:
    """Why a book may not run in `mode`, or None. Synthetic mode is always open, so the battery
    itself and power checks run. `ridge` is the book's ridge settings (window_sessions,
    refit_sessions, penalty, min_obs); a ridge book is admitted only at the configuration the
    battery certified."""
    cells = required_cells(combiner_kind, kappa, features)
    if not cells or mode == "synthetic":
        return None
    what = f"combiner {combiner_kind}, kappa {kappa if kappa is not None else 1}"
    if features:
        what += f", {', '.join(features)}"
    if certificate is None:
        return f"{what}: no E17 fitted-book certificate ({CERTIFICATE_PATH})"
    if certificate.get("schema") != SCHEMA:
        return f"{what}: certificate schema {certificate.get('schema')!r} is not {SCHEMA}"
    if certificate.get("sessions") != REAL_SESSIONS:
        return f"{what}: certificate battery ran at {certificate.get('sessions')} sessions"
    if certificate.get("code") != fingerprint:
        return f"{what}: the certified code has changed since the battery ran; rerun and recertify"
    if combiner_kind == "ridge" and ridge != certificate.get("ridge"):
        return f"{what}: ridge settings {ridge} are not the certified {certificate.get('ridge')}"
    for cell in cells:
        levels = certificate.get("cells", {}).get(cell)
        if levels is None:
            return f"{what}: no certified battery cell {cell}"
        failing = [a for a in GATED_LEVELS if not levels.get(a, {}).get("holds")]
        if failing:
            return f"{what}: battery cell {cell} exceeds size at {', '.join(failing)}"
    return None


# The checkout this module runs from: the code that executes, and the certificate committed
# beside it (never the spec's repository, which a test may point elsewhere).
CODE_ROOT = Path(__file__).resolve().parents[3]


def load_certificate(root: Path = CODE_ROOT) -> dict | None:
    path = root / CERTIFICATE_PATH
    return json.loads(path.read_text()) if path.exists() else None


def working_tree_fingerprint(root: Path = CODE_ROOT) -> dict[str, str]:
    return code_fingerprint(lambda p: (root / p).read_text())


def admission_refusal(
    combiner_kind: str,
    kappa: float | None,
    mode: str,
    ridge: dict | None = None,
    features: tuple[str, ...] = (),
) -> str | None:
    """fitted_book_refusal against the running code's certificate and fingerprint, read only
    when a fitted book asks for a non-synthetic run."""
    if not required_cells(combiner_kind, kappa, features) or mode == "synthetic":
        return None
    return fitted_book_refusal(
        combiner_kind,
        kappa,
        mode,
        load_certificate(),
        working_tree_fingerprint(),
        ridge,
        features,
    )
