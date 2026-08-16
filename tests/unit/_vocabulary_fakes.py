"""Shared test double for src.config.vocabulary_service.VocabularyService.

`FakeVocabularyService` was independently copy-pasted, byte-for-byte identical
apart from its `active_codes()` return value, across 4 test files exercising
`timeframe_vocabulary.prewarm()` call sites (bar_writer, feature_vector_pipeline,
signal_auditor, feature_validation_analyzer -- todo 327). Extracted here during
the /simplify pass that followed todo 327's merge.

Patch target: `src.core.timeframe_vocabulary.VocabularyService` -- every real
call site now goes through `timeframe_vocabulary.prewarm()`, which constructs
`VocabularyService` inside that module, not inside the daemon's own module.
"""

from __future__ import annotations


class FakeVocabularyService:
    """Stands in for VocabularyService -- records initialize() and reports
    whatever `codes` the caller supplies for the "timeframe" namespace.

    Pass a set that's a strict superset of the caller's own subset to prove a
    passing assertion actually consulted CVR (not the no-VocabularyService-
    registered no-op path); pass a set that omits one of the caller's codes to
    prove `assert_known_subset` genuinely raises on a real drift case.
    """

    def __init__(self, codes: list[str]) -> None:
        self._codes = codes
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
