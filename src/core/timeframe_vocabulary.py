"""Timeframe vocabulary - cached read-side accessor over CVR's `timeframe` namespace.

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
"""

from __future__ import annotations

from typing import Any

import structlog

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


def standard_timeframes(default: tuple[str, ...] = _DEFAULT_TIMEFRAMES) -> tuple[str, ...]:
    """All registered, non-deprecated `timeframe` codes, in CVR sort_order.

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
    codes = _vocab_service.active_codes("timeframe")
    if not codes:
        logger.warning(
            "timeframe_vocabulary.empty_registry_fallback",
            default=default,
        )
        return default
    return tuple(codes)


def assert_known_subset(timeframes: tuple[str, ...], *, context: str) -> None:
    """Raise if any of `timeframes` isn't a registered CVR `timeframe` code.

    For call sites that deliberately use a subset of all registered timeframes (e.g.
    `signal_auditor.py`'s coverage check intentionally excludes `1d`) rather than the
    full dynamic set - keeps the subset as an explicit literal (preserving whatever
    intentional scoping it encodes) while still closing the actual drift risk D-07
    exists to prevent: a hardcoded subset silently referencing a timeframe that no
    longer exists (or never did). A no-op if no `VocabularyService` is registered -
    matches `standard_timeframes()`'s same fallback-permissive contract for scripts/
    tests running outside daemon startup.
    """
    if _vocab_service is None:
        return
    known = set(_vocab_service.active_codes("timeframe"))
    unknown = [tf for tf in timeframes if tf not in known]
    if unknown:
        raise ValueError(
            f"{context}: timeframe(s) {unknown} not registered in CVR's `timeframe` "
            f"namespace (known: {sorted(known)})"
        )
