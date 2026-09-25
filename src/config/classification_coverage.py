"""Classification coverage drift audit (Phase 182, D-09 point 3).

Reports every active instrument without a current `indicagent_v1` assignment. D-09 has
three enforcement points for "every active instrument is classified": the seed migration's
guard (one moment in time), the `onboard_instrument()` gate (one write path), and this
audit. Only this one catches a raw `UPDATE instruments SET is_active = true` or a row added
outside onboarding after the seed ran. GitHub CI cannot see the live DB, which is why this
check runs against it nightly instead of living in a unit test.

Observability-only, same contract as `VocabularyDriftAuditor`: a gap is reported loudly
(one `integrity_monitor` row, an OTel counter, `logger.error` naming the symbols), never
through a failing exit code. Only a runtime error propagates (BaseBatch D-06).

Coverage is measured through `ClassificationService` (its first production consumer, D-08)
rather than a second hand-written SQL definition of "covered": a symbol is uncovered when
its level-1 node as of today is the scheme-qualified unclassified label. The audit also
reports the size of the unclassified stratum at every level, so D-08's explicit stratum is
countable (an ETF assigned at level 2 is legitimately unclassified at levels 3-4).

No numeric threshold exists here (the pass condition is zero uncovered by definition), so
no APR key applies. Chained as a non-blocking step in
`scripts/ops/corpus/ops_corpus_pipeline_run.sh`, not a systemd timer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import UTC, date, datetime

import asyncpg
import structlog

from src.config.classification_service import (
    DEFAULT_SCHEME,
    ClassificationService,
    unclassified_code,
)
from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.core.integrity_monitor import emit_integrity_fact_async
from src.observability.metrics import counter
from src.observability.otel import OTelInitError, init_otel_providers

logger = structlog.get_logger(__name__)

# D-06: no systemd unit consumes this label (the audit rides a bash script, not a timer);
# still emitted for OTel consistency with the vocabulary drift audit.
_JOB_LABEL = "classification-coverage-audit"

_MONITOR_TYPE = "classification_coverage"

CLASSIFICATION_COVERAGE_UNCOVERED_TOTAL = counter(
    "classification_coverage_uncovered_total",
    "Runs where the classification coverage audit found active instruments without a "
    "current assignment",
)

# ---------------------------------------------------------------------------
# Pure coverage logic -- no IO, unit-testable against a cache-populated service.
# ---------------------------------------------------------------------------


def uncovered_symbols(
    active_symbols: Iterable[str],
    service: ClassificationService,
    as_of: date,
    scheme: str = DEFAULT_SCHEME,
) -> list[str]:
    """Sorted symbols with no assignment applying as of `as_of` (level 1 unclassified)."""
    unclassified = unclassified_code(scheme)
    return sorted(
        symbol
        for symbol in set(active_symbols)
        if service.node_at_level(symbol, 1, scheme=scheme, as_of=as_of) == unclassified
    )


def unclassified_counts_by_level(
    active_symbols: Iterable[str],
    service: ClassificationService,
    as_of: date,
    scheme: str = DEFAULT_SCHEME,
) -> dict[int, int]:
    """Unclassified stratum size at each level 1..max_level (D-08). Empty when the
    scheme has no loaded nodes."""
    symbols = set(active_symbols)
    unclassified = unclassified_code(scheme)
    return {
        level: sum(
            1
            for symbol in symbols
            if service.node_at_level(symbol, level, scheme=scheme, as_of=as_of) == unclassified
        )
        for level in range(1, service.max_level(scheme) + 1)
    }


# ---------------------------------------------------------------------------
# BaseBatch oneshot. A detected gap never raises; a runtime error propagates.
# ---------------------------------------------------------------------------


class ClassificationCoverageAuditor(BaseBatch):
    """Classification coverage drift audit, chained in ops_corpus_pipeline_run.sh."""

    job_name = _JOB_LABEL
    compute_version = "1.0.0"

    async def execute(self, pool: asyncpg.Pool) -> None:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT symbol FROM instruments WHERE is_active = true ORDER BY symbol"
            )
        active = [row["symbol"] for row in rows]

        # Built on the BaseBatch pool; close() leaves an injected pool open.
        service = ClassificationService(self._db_dsn, pool=pool)
        await service.initialize()
        try:
            as_of = datetime.now(UTC).date()
            uncovered = uncovered_symbols(active, service, as_of)
            counts = unclassified_counts_by_level(active, service, as_of)
        finally:
            await service.close()

        n_uncovered = len(uncovered)
        async with pool.acquire() as conn:
            await emit_integrity_fact_async(
                conn,
                _MONITOR_TYPE,
                DEFAULT_SCHEME,
                "uncovered_active_count",
                float(n_uncovered),
                0.0,
                n_uncovered == 0,
                None,
            )
            # The stratum size is informational, never a failure.
            for level, count in counts.items():
                await emit_integrity_fact_async(
                    conn,
                    _MONITOR_TYPE,
                    DEFAULT_SCHEME,
                    f"unclassified_at_level_{level}",
                    float(count),
                    None,
                    True,
                    None,
                )

        if uncovered:
            CLASSIFICATION_COVERAGE_UNCOVERED_TOTAL.add(1, {"scheme": DEFAULT_SCHEME})
            logger.error(
                "classification_coverage.uncovered_active_instruments",
                symbols=uncovered,
                count=n_uncovered,
            )

        self.logger.info(
            "classification_coverage.report",
            scheme=DEFAULT_SCHEME,
            as_of=as_of.isoformat(),
            active_count=len(active),
            uncovered_count=n_uncovered,
            unclassified_by_level=counts,
        )
        print("# Classification Coverage Audit Report\n")
        print(f"Scheme: {DEFAULT_SCHEME} (as of {as_of.isoformat()})")
        print(f"Active instruments: {len(active)}")
        print(f"Uncovered active instruments: {n_uncovered}")
        for level, count in counts.items():
            print(f"Unclassified at level {level}: {count}")
        status = "PASS" if n_uncovered == 0 else "GAP"
        print(f"\n{status} -- audit complete (observability-only, never a hard gate).")


if __name__ == "__main__":
    try:
        init_otel_providers("indicagent-classification-coverage-audit")
    except OTelInitError as error:
        logger.warning("classification_coverage.otel_init_failed", error=str(error))

    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(ClassificationCoverageAuditor(db_dsn=db_dsn).run())
