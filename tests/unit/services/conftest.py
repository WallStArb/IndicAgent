"""The corpus rerun tests run small fake universes: shrink the pilot's pre-registered judged-name
floor (ledger 2026-11-22d, 65) so they need two names. The sample rule's own tests keep the
real constants, and a test that checks the floor sets it itself."""

import pytest

from services import corpus_pilot_sample


@pytest.fixture(autouse=True)
def _small_pilot_floor(request, monkeypatch):
    if request.module.__name__.endswith("test_corpus_pilot_sample"):
        return
    monkeypatch.setattr(corpus_pilot_sample, "PILOT_MIN_JUDGED_NAMES", 2)
