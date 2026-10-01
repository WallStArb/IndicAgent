#!/usr/bin/env python3
"""Regime Coverage Auditor — oneshot canary for todo 169.

Checks that every corpus symbol has AT LEAST ONE non-null feature_vectors.regime row
(per-symbol HMM label, written by regime_writer.py). A symbol with 100% NULL regime is
a silent gap: regime_writer.py can degenerate-skip a symbol for every (tf) cell forever
without anything else in the pipeline noticing (found by accident, todo 168, 7 symbols
affected for years). This canary exists so the NEXT such gap is caught immediately
instead of by accident during an unrelated investigation.

A gap is alert-worthy unless it is a registered exception. APR key
`alpha.regime.coverage_auditor.known_exceptions` is a JSON list of `{symbol, kind, reason,
clears_on, expires, todo}`: a symbol whose stored regime is all NULL for a diagnosed reason
(history shorter than the walk-forward warmup, a degenerate fit; 186-18, todo 341). `kind` is
`rebuild_pending` (needs `expires` and `clears_on`, the trigger that ends it, for example "186-26
rebuild") or `permanent_degenerate` (needs a reason, no expiry; capped by APR
`alpha.regime.coverage_auditor.max_permanent_exceptions` and listed in the log on every run).
The job fails only on an unregistered gap or an exception past its `expires` date, so the nightly
unit carries information again. Gauges `regime_coverage_auditor_exceptions_live` and
`regime_coverage_auditor_days_to_earliest_expiry` carry the unexpired count and the days left. An
exception is added by an operator after a diagnosis (`scripts/infrastructure/
features_regime_kernel_coverage_sweep.py` classifies the cell), always with an expiry: it is a
review date, renewed with a fresh diagnosis or removed. A listed symbol that is no longer a gap
logs a `stale_exception` warning and does not fail. A malformed list (missing symbol, reason or
expires, or an unparseable date) fails the job at startup rather than hiding gaps.

Usage:
    python services/regime_coverage_auditor.py
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import psycopg
import structlog
from opentelemetry import metrics as _otel_metrics
from psycopg.rows import dict_row

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import load_config_service_sync
from src.config.settings import Settings
from src.core.service_utils import setup_service_logging
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers

setup_service_logging("logs/regime_coverage_auditor.log")

_logger = structlog.get_logger(__name__)

_JOB = "regime-coverage-auditor"
_EXCEPTIONS_KEY = "alpha.regime.coverage_auditor.known_exceptions"
_MAX_PERMANENT_KEY = "alpha.regime.coverage_auditor.max_permanent_exceptions"

KIND_REBUILD = "rebuild_pending"
KIND_PERMANENT = "permanent_degenerate"
_KINDS = (KIND_REBUILD, KIND_PERMANENT)

# Per-service instruments, the repo's pattern for service-owned metrics (src/observability/metrics.py
# is Ring 0 and takes no domain-named instruments, todo 465).
_meter = _otel_metrics.get_meter("indicagent")
_EXCEPTIONS_LIVE = _meter.create_gauge(
    "regime_coverage_auditor_exceptions_live",
    description="Registered coverage exceptions that have not expired",
)
_DAYS_TO_EARLIEST_EXPIRY = _meter.create_gauge(
    "regime_coverage_auditor_days_to_earliest_expiry",
    description="Days until the earliest expiry among live exceptions (unset when none expires)",
)

_COVERAGE_GAP_SQL = """
    SELECT symbol, count(*) AS total_rows, count(regime) AS non_null_regime_rows
    FROM feature_vectors
    GROUP BY symbol
    HAVING count(regime) = 0
    ORDER BY symbol
"""


@dataclass(frozen=True)
class KnownException:
    """One registered coverage gap: why it is expected, what ends it (`clears_on`), the todo that
    tracks it, and the last day it is honored (`expires`, None for a permanent entry)."""

    symbol: str
    kind: str
    reason: str
    expires: date | None
    clears_on: str | None
    todo: str | None


@dataclass(frozen=True)
class AuditResult:
    """`unregistered` and `expired` fail the job; `excepted` and `stale_exceptions` do not."""

    unregistered: list[str]
    expired: list[str]
    excepted: list[KnownException]
    stale_exceptions: list[KnownException]

    @property
    def failed(self) -> bool:
        return bool(self.unregistered or self.expired)


def _text(entry: dict[str, Any], key: str) -> str:
    return str(entry.get(key) or "").strip()


def parse_known_exceptions(raw: Any, max_permanent: int = 5) -> list[KnownException]:
    """The APR value (a JSON string, or the list a json-typed key already parsed to) as
    `KnownException`s. Raises ValueError on anything malformed: a missing or empty symbol, kind or
    reason, an unknown kind, a `rebuild_pending` entry without an ISO `expires` and a `clears_on`,
    a `permanent_degenerate` entry with an expiry, a duplicate symbol, or more than
    `max_permanent` permanent entries."""
    entries = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(entries, list):
        raise ValueError(f"{_EXCEPTIONS_KEY} must be a JSON list, got {type(entries).__name__}")
    parsed: list[KnownException] = []
    for index, entry in enumerate(entries):
        where = f"{_EXCEPTIONS_KEY}[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} must be an object")

        missing = [k for k in ("symbol", "kind", "reason") if not _text(entry, k)]
        if missing:
            raise ValueError(f"{where} is missing {missing}")
        kind = _text(entry, "kind")
        if kind not in _KINDS:
            raise ValueError(f"{where} kind {kind!r} is not one of {_KINDS}")
        expires: date | None = None
        if kind == KIND_REBUILD:
            missing = [k for k in ("expires", "clears_on") if not _text(entry, k)]
            if missing:
                raise ValueError(f"{where} ({kind}) is missing {missing}")
            try:
                expires = date.fromisoformat(_text(entry, "expires"))
            except ValueError as error:
                raise ValueError(
                    f"{where} expires {entry['expires']!r} is not an ISO date"
                ) from error
        elif _text(entry, "expires"):
            raise ValueError(f"{where} ({kind}) must not carry an expiry")
        parsed.append(
            KnownException(
                symbol=_text(entry, "symbol"),
                kind=kind,
                reason=_text(entry, "reason"),
                expires=expires,
                clears_on=_text(entry, "clears_on") or None,
                todo=_text(entry, "todo") or None,
            )
        )
    symbols = [e.symbol for e in parsed]
    if len(set(symbols)) != len(symbols):
        raise ValueError(f"{_EXCEPTIONS_KEY} lists a symbol more than once")
    n_permanent = sum(e.kind == KIND_PERMANENT for e in parsed)
    if n_permanent > max_permanent:
        raise ValueError(
            f"{_EXCEPTIONS_KEY} has {n_permanent} permanent entries, above the cap {max_permanent}"
        )
    return parsed


def evaluate_gaps(
    gap_symbols: list[str], exceptions: list[KnownException], today: date
) -> AuditResult:
    """Split the gap symbols into unregistered, expired (an exception whose `expires` is before
    `today`), and excepted; exceptions for symbols that are no longer gaps are stale."""
    by_symbol = {e.symbol: e for e in exceptions}
    unregistered: list[str] = []
    expired: list[str] = []
    excepted: list[KnownException] = []
    for symbol in gap_symbols:
        entry = by_symbol.get(symbol)
        if entry is None:
            unregistered.append(symbol)
        elif entry.expires is not None and entry.expires < today:
            expired.append(symbol)
        else:
            excepted.append(entry)
    gaps = set(gap_symbols)
    stale = [e for e in exceptions if e.symbol not in gaps]
    return AuditResult(unregistered, expired, excepted, stale)


def _connect_db(settings: Settings) -> psycopg.Connection:
    conn = psycopg.connect(
        settings.database_url, options="-c idle_in_transaction_session_timeout=0"
    )
    conn.autocommit = True
    return conn


def _fetch_coverage_gaps(cur: psycopg.Cursor) -> list[str]:
    """Pure-ish helper — exported for unit tests. Takes an open cursor, returns the
    list of symbols with zero non-null feature_vectors.regime rows."""
    cur.execute(_COVERAGE_GAP_SQL)
    return [row["symbol"] for row in cur.fetchall()]


def main() -> None:
    try:
        init_otel_providers(service_name=_JOB)
    except OTelInitError as error:
        _logger.warning("regime_coverage_auditor.otel_init_failed", error=str(error))

    t0 = time.monotonic()
    status = "success"
    exit_code = 0
    conn = None

    try:
        settings = Settings()
        conn = _connect_db(settings)
        cfg = load_config_service_sync(conn)
        exceptions = parse_known_exceptions(
            cfg.get_sync(_EXCEPTIONS_KEY, "[]"), int(cfg.get_sync(_MAX_PERMANENT_KEY, 5))
        )
        with conn.cursor(row_factory=dict_row) as cur:
            gap_symbols = _fetch_coverage_gaps(cur)

        today = datetime.now(UTC).date()
        result = evaluate_gaps(gap_symbols, exceptions, today)
        live = [e for e in exceptions if e.expires is None or e.expires >= today]
        _EXCEPTIONS_LIVE.set(len(live))
        expiring = [(e.expires - today).days for e in live if e.expires is not None]
        if expiring:
            _DAYS_TO_EARLIEST_EXPIRY.set(min(expiring))
        permanent = [e for e in exceptions if e.kind == KIND_PERMANENT]
        if permanent:
            _logger.info(
                "regime_coverage_auditor.permanent_exceptions",
                symbols=[e.symbol for e in permanent],
                reasons={e.symbol: e.reason for e in permanent},
            )
        if result.excepted:
            _logger.info(
                "regime_coverage_auditor.gap_excepted",
                n_symbols=len(result.excepted),
                excepted={
                    e.symbol: f"{e.kind}: {e.reason} (todo {e.todo}, until {e.expires}, clears on {e.clears_on})"
                    for e in result.excepted
                },
            )
        for entry in result.stale_exceptions:
            _logger.warning(
                "regime_coverage_auditor.stale_exception",
                symbol=entry.symbol,
                reason=entry.reason,
                note="listed as a gap but feature_vectors.regime now has labels for it; "
                "remove the entry from APR",
            )
        if result.failed:
            _logger.warning(
                "regime_coverage_auditor.gap_found",
                n_symbols=len(result.unregistered) + len(result.expired),
                unregistered=result.unregistered,
                expired=result.expired,
                note="feature_vectors.regime is 100% NULL for these symbols and no live "
                "exception covers them. Diagnose with "
                "scripts/infrastructure/features_regime_kernel_coverage_sweep.py, then register "
                "an exception (with an expiry) or fix the cause. See todo 168 for the "
                "fix-direction precedent (near-miss vs true degenerate-collapse split).",
            )
            status = "gap_found"
            exit_code = 1
        elif result.excepted:
            _logger.info("regime_coverage_auditor.no_unregistered_gap_found")
        else:
            _logger.info("regime_coverage_auditor.no_gap_found")

        elapsed = time.monotonic() - t0
        _logger.info(
            "regime_coverage_auditor.complete",
            elapsed_s=round(elapsed, 2),
            status=status,
        )

    except Exception as error:
        _logger.error("regime_coverage_auditor.run_failed", error=str(error))
        status = "failure"
        exit_code = 1
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
