"""Column-backed vocabulary drift audit (Phase 161, Controlled Vocabulary System).

A live source column (e.g. `feature_vectors.regime`, `market_regimes.regime_label`) can
emit a code the Controlled Vocabulary registry (`VocabularyService`) never heard of --
silent taxonomy drift. This module makes that loud instead of silent (D-09; "never drop
data that could contain signal" applies just as much to a code the registry doesn't know
about yet as to a row).

Pure comparison logic (`unregistered_codes`, `unregistered_groups`, `extract_regime_codes`,
`classify_namespace_drift`) is fully unit-testable with no DB. All DB I/O is confined to
`run_drift_audit` (the async runner) and the thin oneshot CLI entrypoint at the bottom of
this file.

Recent-window length is APR-sourced (`infra.vocabulary_drift.window_days`, migration 241)
-- never a hardcoded interval literal (CLAUDE.md APR mandate) -- and bound as an asyncpg `$1`
parameter on every bounded per-namespace query (T-161-02: never a full-hypertable scan).

Not wired into any systemd daemon/timer (D-09) -- chained as a non-blocking step into
`scripts/ops/corpus/ops_corpus_pipeline_run.sh` after `alpha_publisher` instead.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import asyncpg
import structlog

from src.config.config_service import ConfigService
from src.config.settings import Settings
from src.config.vocabulary_service import VocabularyService
from src.core.agent.base_batch import BaseBatch
from src.core.integrity_monitor import emit_integrity_fact_async
from src.observability.metrics import counter
from src.observability.otel import OTelInitError, init_otel_providers

logger = structlog.get_logger(__name__)

# D-06: no systemd unit consumes this label today (this rides a bash script, not a
# timer) -- still emitted for OTel consistency, per 161-PATTERNS.md's recommendation.
_JOB_LABEL = "vocabulary-drift-audit"

_WINDOW_DEFAULT = 30

# The regime_group qualifiers the registry knows about (V2 guard) -- the namespace
# suffixes of regime_cross_sectional_equity / regime_cross_sectional_rates.
_REGISTERED_REGIME_GROUPS: frozenset[str] = frozenset({"equity", "rates"})

VOCABULARY_DRIFT_UNREGISTERED_TOTAL = counter(
    "vocabulary_drift_unregistered_total",
    "Namespaces where the vocabulary drift audit found a live code the registry does "
    "not know about, labeled by namespace.",
)

# ---------------------------------------------------------------------------
# Pure comparison logic -- no IO, fully unit-testable against literal fixtures.
# ---------------------------------------------------------------------------


def unregistered_codes(observed: Iterable[str], registered: Iterable[str]) -> set[str]:
    """The data-superset: observed codes NOT present in the registered set."""
    return set(observed) - set(registered)


def unregistered_groups(
    observed_groups: Iterable[str], registered_groups: Iterable[str]
) -> set[str]:
    """V2 regime_group guard: observed `market_regimes.regime_group` values NOT in the
    registered qualifier set (`{'equity', 'rates'}`) -- catches a future third group
    drifting past both `regime_cross_sectional_*` namespace-specific queries silently."""
    return set(observed_groups) - set(registered_groups)


def extract_regime_codes(raw_codes: Iterable[str | None]) -> list[str]:
    """Drop the empty-string placeholder ('') from a list of raw regime codes
    (Finding 3: '' is a placeholder for "no regime yet assigned", never a real code).

    Column-agnostic -- applies identically to `regime_hmm` (feature_vectors.regime)
    and `regime_volatility` (feature_vectors.regime_volatility, Phase 172): both
    columns use the same '' sentinel for "not yet labeled." Defense-in-depth
    alongside each namespace's SQL-level `<> ''` filter -- kept as a pure,
    independently testable step rather than relying solely on the query. Renamed
    from `extract_regime_hmm_codes` (Phase 172 plan 02) -- referenced only inside
    this module and its own test file at rename time (verified via
    `grep -rn extract_regime_hmm_codes src/ services/ scripts/ tests/`), so this is
    an outright rename, not an aliased extension.
    """
    return [code for code in raw_codes if code]


@dataclass(frozen=True)
class NamespaceDriftResult:
    """Pure decision core for one namespace's (or the regime_group guard's) drift check.

    `idle=True` means the observed set was empty this window -- source-idle, must be
    skipped (log info, no integrity_monitor write), never misread as mass deprecation
    (V5). `idle=False` carries the (possibly empty) `unregistered` data-superset.
    """

    idle: bool
    unregistered: frozenset[str]


def assert_namespace_coverage(
    queried_namespaces: Iterable[str], known_namespaces: Iterable[str]
) -> None:
    """Fail loud, not silently, if this module's hardcoded namespace-query dicts
    (_WINDOWED_NAMESPACE_QUERIES / _UNWINDOWED_NAMESPACE_QUERIES) drift out of sync
    with the controlled_vocabulary registry VocabularyService actually loaded (todo 132).

    Without this, a namespace renamed or retired in the DB would silently stop being
    checked (or -- the sharper failure -- keep querying a namespace whose registered
    codes VocabularyService no longer has cached, so every observed code reads as
    "unregistered," a false-positive drift alert) with no signal that the two have
    diverged.
    """
    unknown = set(queried_namespaces) - set(known_namespaces)
    if unknown:
        raise RuntimeError(
            f"vocabulary_drift.py queries namespace(s) {sorted(unknown)} that "
            "VocabularyService has no registered codes for -- this module's "
            "namespace-query dicts have drifted out of sync with the "
            "controlled_vocabulary registry (todo 132)"
        )


def classify_namespace_drift(
    observed: Iterable[str],
    registered: Iterable[str],
    diff_fn: Callable[[Iterable[str], Iterable[str]], set[str]] = unregistered_codes,
) -> NamespaceDriftResult:
    """Classify one namespace's observed-vs-registered comparison.

    An empty observed set is source-idle (skip), never treated as "every registered
    code got deprecated." `diff_fn` defaults to `unregistered_codes`; pass
    `unregistered_groups` for the regime_group guard's comparison.
    """
    observed_list = list(observed)
    if not observed_list:
        return NamespaceDriftResult(idle=True, unregistered=frozenset())
    return NamespaceDriftResult(
        idle=False, unregistered=frozenset(diff_fn(observed_list, registered))
    )


# ---------------------------------------------------------------------------
# Bounded, column-backed source queries.
#
# Every query binds the APR-sourced recent-window as $1 (`($1 || ' days')::interval`)
# -- never a hardcoded interval literal, never a full-hypertable distinct scan (T-161-02).
# ---------------------------------------------------------------------------

_WINDOWED_NAMESPACE_QUERIES: dict[str, str] = {
    # regime_hmm and regime_volatility are both audited on purpose during Phase
    # 172's cutover window (172-RESEARCH.md Open Question 1: phased cutover, legacy
    # `regime` stays readable and audited through at least one full corpus cycle
    # after `regime_volatility` ships). What would justify removing the regime_hmm
    # entry later: the legacy `regime` column no longer being written or read by
    # any live path.
    "regime_hmm": (
        "SELECT DISTINCT regime FROM feature_vectors "
        "WHERE bar_ts > now() - ($1 || ' days')::interval AND regime <> ''"
    ),
    "regime_volatility": (
        "SELECT DISTINCT regime_volatility FROM feature_vectors "
        "WHERE bar_ts > now() - ($1 || ' days')::interval AND regime_volatility <> ''"
    ),
    "regime_cross_sectional_equity": (
        "SELECT DISTINCT regime_label FROM market_regimes "
        "WHERE ts > now() - ($1 || ' days')::interval AND regime_group = 'equity'"
    ),
    "regime_cross_sectional_rates": (
        "SELECT DISTINCT regime_label FROM market_regimes "
        "WHERE ts > now() - ($1 || ' days')::interval AND regime_group = 'rates'"
    ),
    "timeframe": (
        "SELECT DISTINCT timeframe FROM market_data_ohlcv_tradeable "
        "WHERE timestamp > now() - ($1 || ' days')::interval"
    ),
}

# asset_class / tier have no natural time column bounding their source tables
# (instruments.is_active, concept_registry.metadata->>'tier'), both small,
# non-hypertable, operator-facing dimension tables, not append-only event streams,
# so no recent-window bound applies (nothing to bound: a full scan of ~60 instruments
# or concept_registry's ~256 rows -- domain='feature' plus domain='ensemble_strategy'
# plus migration 284's 2 gate-less tombstone rows, Phase 170 Plan 07's cutover from
# the retired feature-only ~249-row predecessor table -- is not the DoS surface
# T-161-02 targets).
_UNWINDOWED_NAMESPACE_QUERIES: dict[str, str] = {
    "asset_class": "SELECT DISTINCT contract_details->>'asset_class' FROM instruments WHERE is_active = true",
    # metadata ? 'tier' excludes domain='ensemble_strategy' rows (no tier key) and
    # the 2 gate-less tombstones (also no tier key) -- without this guard, a NULL
    # tier would enter the observed vocabulary set and the drift audit would
    # report a spurious unregistered code every single run. Live-verified
    # (Phase 170 Plan 07): identical to the predecessor table's own 3-value
    # (0_atomic, 1_interaction, 2_theory) result.
    "tier": "SELECT DISTINCT metadata->>'tier' FROM concept_registry WHERE domain = 'feature' AND metadata ? 'tier'",
}

_REGIME_GROUP_GUARD_SQL = (
    "SELECT DISTINCT regime_group FROM market_regimes WHERE ts > now() - ($1 || ' days')::interval"
)


async def _evaluate_and_persist(
    conn: asyncpg.Connection,
    subject: str,
    observed: Iterable[str],
    registered: Iterable[str],
    diff_fn: Callable[[Iterable[str], Iterable[str]], set[str]] = unregistered_codes,
) -> int:
    """Classify one namespace/guard's drift, persist an `integrity_monitor` row when
    the observed set is non-idle, and emit a loud alert on any data-superset.

    Uses the shared emit_integrity_fact_async helper (todo 150). No
    idempotency_check: unlike ic_engine.py's ic_lifecycle facts, this audit
    intentionally records one fact per run for calibration history rather than
    being idempotent per training_window_end (training_window_end is always NULL
    here -- this isn't scoped to a corpus training window at all).

    Returns 1 if drift was flagged this run, 0 otherwise (idle or clean).
    """
    result = classify_namespace_drift(observed, registered, diff_fn=diff_fn)
    if result.idle:
        logger.info("vocabulary_drift.source_idle", subject=subject)
        return 0

    unregistered = result.unregistered
    passed = len(unregistered) == 0
    await emit_integrity_fact_async(
        conn,
        "vocabulary_drift",
        subject,
        "unregistered_code_count",
        float(len(unregistered)),
        0.0,
        passed,
        None,
    )

    if passed:
        return 0

    VOCABULARY_DRIFT_UNREGISTERED_TOTAL.add(1, {"namespace": subject})
    logger.error(
        "vocabulary_drift.unregistered_codes_detected",
        subject=subject,
        unregistered=sorted(unregistered),
    )
    return 1


async def run_drift_audit(pool: asyncpg.Pool, vocab: VocabularyService, window_days: int) -> int:
    """Run the full column-backed drift audit once. Returns the number of
    namespaces/guards flagged with unregistered (data-superset) codes this run."""
    window_param = str(window_days)
    drift_count = 0

    # (namespace, sql, params) -- windowed queries bind window_param as $1, unwindowed
    # queries (small non-hypertable dimension tables) take no params.
    namespace_queries: list[tuple[str, str, tuple[str, ...]]] = [
        (namespace, sql, (window_param,)) for namespace, sql in _WINDOWED_NAMESPACE_QUERIES.items()
    ] + [(namespace, sql, ()) for namespace, sql in _UNWINDOWED_NAMESPACE_QUERIES.items()]

    async with pool.acquire() as conn:
        for namespace, sql, params in namespace_queries:
            rows = await conn.fetch(sql, *params)
            observed = [row[0] for row in rows if row[0] is not None]
            if namespace in ("regime_hmm", "regime_volatility"):
                observed = extract_regime_codes(observed)
            drift_count += await _evaluate_and_persist(
                conn, namespace, observed, vocab.codes(namespace)
            )

        # V2 regime_group guard -- catches a future third regime_group value drifting
        # past both regime_cross_sectional_equity/_rates namespace-specific queries.
        group_rows = await conn.fetch(_REGIME_GROUP_GUARD_SQL, window_param)
        observed_groups = [row[0] for row in group_rows if row[0] is not None]
        drift_count += await _evaluate_and_persist(
            conn,
            "regime_group",
            observed_groups,
            _REGISTERED_REGIME_GROUPS,
            diff_fn=unregistered_groups,
        )

    return drift_count


# ---------------------------------------------------------------------------
# BaseBatch oneshot (todo 131). Observability-only (see 161-PATTERNS.md): a detected
# drift is reported via integrity_monitor + the loud alert in _evaluate_and_persist,
# never via a failing exit code -- only an actual runtime error propagates (BaseBatch's
# own D-06 contract: an uncaught exception in execute() re-raises after recording the
# failure, same as every other batch oneshot in this codebase).
# ---------------------------------------------------------------------------


class VocabularyDriftAuditor(BaseBatch):
    """Column-backed vocabulary drift audit, run as a chained step in
    scripts/ops/corpus/ops_corpus_pipeline_run.sh (not a systemd timer, D-09)."""

    job_name = _JOB_LABEL
    compute_version = "1.0.0"

    async def execute(self, pool: asyncpg.Pool) -> None:
        # Not services._batch_utils.load_apr_dict_async/cfg (the pattern every
        # services/-resident BaseBatch sibling uses) -- this file lives in src/config/
        # (Ring 1), and services/ is Ring 2; Ring 1 may only import Ring 0
        # (naming-system.md's Ring rule). ConfigService lives in src/config/ itself
        # (same ring), so it's the correct-altitude choice here despite the extra
        # object-lifecycle ceremony for a single scalar read.
        config_service = ConfigService(database_url=self._db_dsn, pool=pool)
        await config_service.initialize()
        window_days = int(
            await config_service.get("infra.vocabulary_drift.window_days", _WINDOW_DEFAULT)
        )

        vocab = VocabularyService(self._db_dsn, pool=pool)
        await vocab.initialize()
        try:
            queried = set(_WINDOWED_NAMESPACE_QUERIES) | set(_UNWINDOWED_NAMESPACE_QUERIES)
            assert_namespace_coverage(queried, vocab.known_namespaces())

            drift_count = await run_drift_audit(pool, vocab, window_days)
            self.logger.info(
                "vocabulary_drift.report",
                window_days=window_days,
                drift_count=drift_count,
            )
            print("# Vocabulary Drift Audit Report\n")
            print(f"Recent window: {window_days} days (infra.vocabulary_drift.window_days)")
            print(f"Namespaces/guards flagged with unregistered codes: {drift_count}")
            print("\nPASS -- audit complete (observability-only, never a hard gate).")
        finally:
            await vocab.close()


if __name__ == "__main__":
    try:
        init_otel_providers("indicagent-vocabulary-drift-audit")
    except OTelInitError as error:
        logger.warning("vocabulary_drift.otel_init_failed", error=str(error))

    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(VocabularyDriftAuditor(db_dsn=db_dsn).run())
