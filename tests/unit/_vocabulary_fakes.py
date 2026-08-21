"""Shared test double for src.config.vocabulary_service.VocabularyService.

`FakeVocabularyService` was independently copy-pasted, byte-for-byte identical
apart from its `active_codes()` return value, across 4 test files exercising
`vocabulary_access.prewarm()` call sites (bar_writer, feature_vector_pipeline,
signal_auditor, feature_validation_analyzer -- todo 327). Extracted here during
the /simplify pass that followed todo 327's merge.

Patch target: `src.core.vocabulary_access.VocabularyService` -- every real
call site now goes through `vocabulary_access.prewarm()`, which constructs
`VocabularyService` inside that module, not inside the daemon's own module.
"""

from __future__ import annotations


class FakeVocabularyService:
    """Stands in for VocabularyService -- records initialize() and reports
    whatever `codes` the caller supplies for the "timeframe" namespace.

    `groups`, if given, is `{group_name: [codes]}` for the "timeframe" namespace --
    backs `group_codes()` calls (todo 329's `intraday_plus_hourly` group).
    """

    def __init__(self, codes: list[str], groups: dict[str, list[str]] | None = None) -> None:
        self._codes = codes
        self._groups = groups or {}
        self.initialized = False

    def __call__(self, database_url, pool=None) -> FakeVocabularyService:
        """Matches VocabularyService's `(database_url, pool=None)` constructor
        signature -- lets `FakeVocabularyService(codes)` itself be passed
        wherever the real class name is expected (`monkeypatch.setattr(...,
        VocabularyService)` / `patch(..., VocabularyService)`)."""
        self.database_url = database_url
        self.pool = pool
        return self

    async def initialize(self) -> None:
        self.initialized = True

    def active_codes(self, namespace: str) -> list[str]:
        assert namespace == "timeframe"
        return self._codes

    def group_codes(self, namespace: str, group_name: str) -> frozenset[str]:
        assert namespace == "timeframe"
        return frozenset(self._groups.get(group_name, []))
