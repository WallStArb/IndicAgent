"""The corpus rerun's APR snapshot (migration 579, todo 593).

One frozen read of every infra.corpus_rerun.* key, taken once per run: the data gate
(services/corpus_rerun_data_gate.py) judges with the data_gate tolerances, and the step runner
(186-31) budgets disk and checks the blocking timers with the rest, so every step of a run sees
the same values.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.config.config_service import ConfigService

# The scope of a data gate run (the runner's `--data-gate-scope`, recorded in the run): `1d` gates
# on the 1d term alone and never unlocks the intraday stages; `all` gates on 1d and 5m. A choice
# of the operator for the run, not a tunable number (it is not an APR key).
SCOPE_1D = "1d"
SCOPE_ALL = "all"
DATA_GATE_SCOPES = (SCOPE_1D, SCOPE_ALL)

MAX_DISK_FRACTION_KEY = "infra.corpus_rerun.max_disk_fraction"
DISK_RESERVE_BYTES_KEY = "infra.corpus_rerun.disk_reserve_bytes"
BYTES_PER_ROW_UNCOMPRESSED_KEY = "infra.corpus_rerun.bytes_per_row_uncompressed"
COMPRESSION_RATIO_KEY = "infra.corpus_rerun.compression_ratio"
STORED_BYTES_PER_SPOOL_BYTE_KEY = "infra.corpus_rerun.stored_bytes_per_spool_byte"
MAX_MISSING_SESSION_FRACTION_KEY = "infra.corpus_rerun.data_gate.max_missing_session_fraction"
MAX_MISSING_1D_SESSION_FRACTION_KEY = "infra.corpus_rerun.data_gate.max_missing_1d_session_fraction"
MIN_SESSION_BAR_FRACTION_KEY = "infra.corpus_rerun.data_gate.min_session_bar_fraction"
# Behavioral list (migration 607): name-years the 1d term holds with their evidence, a JSON list of
# {symbol, year, evidence}. Seeded with the two POWI years of the 2026-11-21b ledger entry.
HELD_NAME_YEARS_KEY = "infra.corpus_rerun.data_gate.held_name_years"
# Behavioral list (migration 610): names the gate holds when they have no proven start, a JSON list
# of {symbol, evidence}; the compute reads no session of a name without a start (ledger 2026-11-21g).
HELD_NAMES_KEY = "infra.corpus_rerun.data_gate.held_names"
BLOCKING_TIMERS_KEY = "infra.corpus_rerun.blocking_timers"
MAX_NULL_FRACTION_KEY = "infra.corpus_rerun.max_null_fraction"  # migration 582 (186-31)

# Operator-command keys (migration 593): read by `corpus_rerun --quiesce`, not pinned in a run.
QUIESCE_WAIT_SECONDS_KEY = "infra.corpus_rerun.quiesce.wait_seconds"
QUIESCE_POLL_SECONDS_KEY = "infra.corpus_rerun.quiesce.poll_seconds"

# Every key the snapshot reads: the runner pins their values in corpus_run.apr_hash.
APR_KEYS: tuple[str, ...] = (
    MAX_DISK_FRACTION_KEY,
    DISK_RESERVE_BYTES_KEY,
    BYTES_PER_ROW_UNCOMPRESSED_KEY,
    COMPRESSION_RATIO_KEY,
    STORED_BYTES_PER_SPOOL_BYTE_KEY,
    MAX_MISSING_SESSION_FRACTION_KEY,
    MAX_MISSING_1D_SESSION_FRACTION_KEY,
    MIN_SESSION_BAR_FRACTION_KEY,
    HELD_NAME_YEARS_KEY,
    HELD_NAMES_KEY,
    BLOCKING_TIMERS_KEY,
    MAX_NULL_FRACTION_KEY,
)


@dataclass(frozen=True)
class HeldNameYear:
    """One named exception of the data gate: the name-year does not gate, and the result reports
    it as held with this evidence (docs/plans/methodology-change-ledger.md, 2026-11-21b)."""

    symbol: str
    year: int
    evidence: str


@dataclass(frozen=True)
class HeldName:
    """A name the data gate holds when it has no proven start: neither judged nor refused, and the
    result reports it with this evidence (ledger 2026-11-21g)."""

    symbol: str
    evidence: str


@dataclass(frozen=True)
class CorpusRerunApr:
    max_disk_fraction: float
    disk_reserve_bytes: int
    bytes_per_row_uncompressed: int
    compression_ratio: float
    stored_bytes_per_spool_byte: float
    max_missing_session_fraction: float
    max_missing_1d_session_fraction: float
    min_session_bar_fraction: float
    blocking_timers: tuple[str, ...]
    max_null_fraction: float
    held_name_years: tuple[HeldNameYear, ...] = ()
    held_names: tuple[HeldName, ...] = ()


def load_held_name_years(raw: Any) -> tuple[HeldNameYear, ...]:
    """Parse the held list (a JSON document or the list the config service already parsed). An
    entry without a symbol, an integer year and an evidence string is a loud error, never skipped.
    """
    entries = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(entries, list):
        raise ValueError(f"{HELD_NAME_YEARS_KEY} must be a JSON list, got {type(entries).__name__}")
    held = []
    for entry in entries:
        if not (
            isinstance(entry, dict)
            and isinstance(entry.get("symbol"), str)
            and type(entry.get("year")) is int
            and isinstance(entry.get("evidence"), str)
            and entry["evidence"]
        ):
            raise ValueError(f"{HELD_NAME_YEARS_KEY}: bad entry {entry!r} (symbol, year, evidence)")
        held.append(HeldNameYear(entry["symbol"], entry["year"], entry["evidence"]))
    return tuple(held)


def load_held_names(raw: Any) -> tuple[HeldName, ...]:
    """Parse the held-name list (a JSON document or an already parsed list); an entry without a
    symbol and an evidence string is a loud error, never skipped."""
    entries = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(entries, list):
        raise ValueError(f"{HELD_NAMES_KEY} must be a JSON list, got {type(entries).__name__}")
    held = []
    for entry in entries:
        if not (
            isinstance(entry, dict)
            and isinstance(entry.get("symbol"), str)
            and isinstance(entry.get("evidence"), str)
            and entry["evidence"]
        ):
            raise ValueError(f"{HELD_NAMES_KEY}: bad entry {entry!r} (symbol, evidence)")
        held.append(HeldName(entry["symbol"], entry["evidence"]))
    return tuple(held)


def load_corpus_rerun_apr(cfg: ConfigService) -> CorpusRerunApr:
    """Every rerun key, read with no default: a key migrations 579 and 582 did not seed is a
    KeyError, never a silent fallback value. The held list (migration 607) is the one behavioral
    list: unseeded it is empty, which is the strict side (no name-year is excused)."""

    def value(key: str) -> Any:
        seeded = cfg.get_sync(key)
        if seeded is None:
            raise KeyError(f"APR key {key} is not seeded (migrations 579, 582)")
        return seeded

    return CorpusRerunApr(
        max_disk_fraction=float(value(MAX_DISK_FRACTION_KEY)),
        disk_reserve_bytes=int(value(DISK_RESERVE_BYTES_KEY)),
        bytes_per_row_uncompressed=int(value(BYTES_PER_ROW_UNCOMPRESSED_KEY)),
        compression_ratio=float(value(COMPRESSION_RATIO_KEY)),
        stored_bytes_per_spool_byte=float(value(STORED_BYTES_PER_SPOOL_BYTE_KEY)),
        max_missing_session_fraction=float(value(MAX_MISSING_SESSION_FRACTION_KEY)),
        max_missing_1d_session_fraction=float(value(MAX_MISSING_1D_SESSION_FRACTION_KEY)),
        min_session_bar_fraction=float(value(MIN_SESSION_BAR_FRACTION_KEY)),
        blocking_timers=tuple(json.loads(str(value(BLOCKING_TIMERS_KEY)))),
        max_null_fraction=float(value(MAX_NULL_FRACTION_KEY)),
        held_name_years=load_held_name_years(cfg.get_sync(HELD_NAME_YEARS_KEY, "[]")),
        held_names=load_held_names(cfg.get_sync(HELD_NAMES_KEY, "[]")),
    )


@dataclass(frozen=True)
class QuiesceApr:
    wait_seconds: float
    poll_seconds: float


def load_quiesce_apr(cfg: ConfigService) -> QuiesceApr:
    """The `--quiesce` wait and poll seconds, read with no default (migration 593)."""
    values = {}
    for key in (QUIESCE_WAIT_SECONDS_KEY, QUIESCE_POLL_SECONDS_KEY):
        seeded = cfg.get_sync(key)
        if seeded is None:
            raise KeyError(f"APR key {key} is not seeded (migration 593)")
        values[key] = float(seeded)
    return QuiesceApr(values[QUIESCE_WAIT_SECONDS_KEY], values[QUIESCE_POLL_SECONDS_KEY])
