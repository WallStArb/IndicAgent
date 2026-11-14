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

MAX_DISK_FRACTION_KEY = "infra.corpus_rerun.max_disk_fraction"
DISK_RESERVE_BYTES_KEY = "infra.corpus_rerun.disk_reserve_bytes"
BYTES_PER_ROW_UNCOMPRESSED_KEY = "infra.corpus_rerun.bytes_per_row_uncompressed"
COMPRESSION_RATIO_KEY = "infra.corpus_rerun.compression_ratio"
STORED_BYTES_PER_SPOOL_BYTE_KEY = "infra.corpus_rerun.stored_bytes_per_spool_byte"
MAX_MISSING_SESSION_FRACTION_KEY = "infra.corpus_rerun.data_gate.max_missing_session_fraction"
MAX_MISSING_1D_SESSION_FRACTION_KEY = "infra.corpus_rerun.data_gate.max_missing_1d_session_fraction"
MIN_SESSION_BAR_FRACTION_KEY = "infra.corpus_rerun.data_gate.min_session_bar_fraction"
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
    BLOCKING_TIMERS_KEY,
    MAX_NULL_FRACTION_KEY,
)


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


def load_corpus_rerun_apr(cfg: ConfigService) -> CorpusRerunApr:
    """Every rerun key, read with no default: a key migrations 579 and 582 did not seed is a
    KeyError, never a silent fallback value."""

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
