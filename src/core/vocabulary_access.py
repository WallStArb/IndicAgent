"""Vocabulary access - cached read-side accessor over CVR namespaces.

Ring 0 (`src/core/`). Mirrors the module-level `ConfigService` consumer pattern
documented in CLAUDE.md's "Migrate-as-you-go" section (`_config_service: Any | None
= None` + `set_config_service()` + `get_sync()` wrapper), applied to
`VocabularyService` instead. Prewarm once, during whichever daemon's existing async
setup phase initializes its DB pool, then read synchronously everywhere else in that
process - `VocabularyService` itself is already fully cached at `initialize()` with
zero further DB calls (docs/foundation/controlled-vocabulary-registry.md), so this
wrapper adds no additional caching of its own, just a well-known Ring 0 access point
so callers don't need a `VocabularyService` instance threaded through every
constructor (todo 327).

Originally `timeframe_vocabulary.py`, scoped to CVR's `timeframe` namespace only.
Generalized to any CVR namespace (todo 330) so a second consumer (todo 324's
`gradient_scale` namespace) doesn't need its own copy of this same registration/
fallback/logging shape - one registered `VocabularyService` per process, read via
`codes(namespace, ...)`. `standard_timeframes()` is kept as a thin convenience
wrapper so `timeframe`'s existing call sites need no change beyond the import path.
"""

from __future__ import annotations

from typing import Any

import asyncpg
import structlog

from src.config.vocabulary_service import VocabularyService

logger = structlog.get_logger(__name__)

_vocab_service: Any | None = None

# Literal copy of CVR's registered `timeframe` codes as of migration 317 (todo 327).
# Used only as the fallback when no VocabularyService has been registered in this
# process (a script or test running outside daemon startup) - keep in sync with the
# registry by hand if a future migration adds/removes a code, same maintenance
# contract as any other cached-default fallback in this codebase.
_DEFAULT_TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h", "1d")


def set_vocabulary_service(vocab: Any) -> None:
    """Register the process's initialized `VocabularyService` instance.

    Call once, from whichever daemon's async setup routine initializes
    `VocabularyService` - same call-site shape as
    `FeatureVectorPipeline._prewarm_threshold_config()` registering `ConfigService`.
    A second call in the same process (e.g. a test replacing it with a fake) simply
    replaces the reference.
    """
    global _vocab_service
    _vocab_service = vocab


def reset_vocabulary_service_for_test() -> None:
    """Test-only: clear the registered service so tests don't leak state."""
    global _vocab_service
    _vocab_service = None


async def prewarm(database_url: str, pool: asyncpg.Pool | None) -> VocabularyService:
    """Create, initialize, and register a `VocabularyService` for this process.

    Collapses the construct/initialize/register triplet every daemon that reads
    this module used to repeat inline (5 call sites, byte-for-byte identical
    apart from the pool argument -- todo 327 /simplify pass) into one call. Pass
    the daemon's already-open pool (e.g. `self._db.pool`) so `VocabularyService`
    reuses it instead of opening a second one. Returns the instance so a caller
    that also wants to hold it as an attribute still can.
    """
    vocab = VocabularyService(database_url, pool=pool)
    await vocab.initialize()
    set_vocabulary_service(vocab)
    return vocab


def codes(namespace: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """All registered, non-deprecated codes for `namespace`, in CVR sort_order.

    Falls back to `default` if no `VocabularyService` has been registered yet (silent -
    documented, intentional fallback for a script/test running outside daemon startup),
    or if the registered service has zero codes for the namespace (logged - a genuine
    gap: an unseeded DB, a migration never replayed, or a namespace-name typo, not a
    normal operating condition). Never silently returns an empty tuple - every known
    caller loops over this and an empty result would be a silent no-op, worse than a
    stale-but-nonempty fallback.
    """
    if _vocab_service is None:
        return default
    result = _vocab_service.active_codes(namespace)
    if not result:
        logger.warning(
            "vocabulary_access.empty_registry_fallback",
            namespace=namespace,
            default=default,
        )
        return default
    return tuple(result)


def standard_timeframes(default: tuple[str, ...] = _DEFAULT_TIMEFRAMES) -> tuple[str, ...]:
    """All registered, non-deprecated `timeframe` codes, in CVR sort_order.

    Thin convenience wrapper over `codes("timeframe", default)` - kept so
    `timeframe`'s existing call sites don't need to spell out the namespace.
    """
    return codes("timeframe", default)


def assert_known_subset(namespace: str, values: tuple[str, ...], *, context: str) -> None:
    """Raise if any of `values` isn't a registered CVR code for `namespace`.

    For call sites that deliberately use a subset of all registered codes (e.g.
    `signal_auditor.py`'s coverage check intentionally excludes `1d`) rather than the
    full dynamic set - keeps the subset as an explicit literal (preserving whatever
    intentional scoping it encodes) while still closing the actual drift risk D-07
    exists to prevent: a hardcoded subset silently referencing a code that no longer
    exists (or never did). A no-op if no `VocabularyService` is registered - matches
    `codes()`'s same fallback-permissive contract for scripts/tests running outside
    daemon startup.
    """
    if _vocab_service is None:
        return
    known = set(_vocab_service.active_codes(namespace))
    unknown = [v for v in values if v not in known]
    if unknown:
        raise ValueError(
            f"{context}: {namespace} value(s) {unknown} not registered in CVR's "
            f"`{namespace}` namespace (known: {sorted(known)})"
        )
