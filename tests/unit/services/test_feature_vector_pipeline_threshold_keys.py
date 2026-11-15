"""Regression guard: every feature.* key read while building FeatureFactoryConfig
must actually be in _THRESHOLD_KEYS.

Root cause this prevents (todo 103, found 2026-07-12, fixed 2026-07-27):
_THRESHOLD_KEYS prewarmed feature.momentum.window_short/window_long -- keys that
don't exist anywhere in config_state -- while FeatureFactoryConfig's construction
actually read feature.momentum.window_fast/mid/slow via ConfigService.get_sync(),
which only serves the prewarmed cache. Every read of the three real keys silently
cache-missed and fell through to the hardcoded Python default, so tuning those
APR keys in config_state had zero effect on the running pipeline -- invisible
because the seeded defaults happened to match the hardcoded fallback.

No DB, no Kafka. Pure source introspection via regex over the live source file,
same technique as test_feature_vector_persistence_completeness.py.
"""

from __future__ import annotations

import re
from pathlib import Path

_SOURCE = (
    Path(__file__).parent.parent.parent.parent / "services" / "feature_vector_pipeline.py"
).read_text()


def _threshold_keys() -> set[str]:
    from services.feature_vector_pipeline import FeatureVectorPipeline

    return {key for key, _default in FeatureVectorPipeline._THRESHOLD_KEYS}


def _prewarm_source() -> str:
    match = re.search(
        r"async def _prewarm_threshold_config\(self\).*?\n    async def ",
        _SOURCE,
        re.DOTALL,
    )
    assert match, "Could not parse _prewarm_threshold_config() from feature_vector_pipeline.py"
    return match.group(0)


def test_every_key_read_building_feature_factory_config_is_prewarmed():
    """FeatureFactoryConfig.from_values reads exactly the keys of FEATURE_APR_FIELDS, and
    _THRESHOLD_KEYS is built from the same table, so a key read there cannot miss the prewarm
    (the silent cache-miss fall-through of todo 103). The method must also not grow a second,
    hand-written key list."""
    from src.intelligence.features.feature_factory_config import FEATURE_APR_FIELDS

    missing = sorted({key for _f, key, _c, _d in FEATURE_APR_FIELDS} - _threshold_keys())
    assert not missing, (
        f"{len(missing)} FeatureFactoryConfig key(s) are missing from _THRESHOLD_KEYS "
        f"and will silently ignore config_state: {missing}"
    )
    source = _prewarm_source()
    assert "FeatureFactoryConfig.from_values(" in source
    assert not re.search(r'_(?:int|float|dict|str|bool)\(\s*"', source)


def test_momentum_window_keys_specifically_fixed():
    """Direct regression pin for todo 103's exact reported symptom."""
    prewarmed = _threshold_keys()
    assert "feature.momentum.window_fast" in prewarmed
    assert "feature.momentum.window_mid" in prewarmed
    assert "feature.momentum.window_slow" in prewarmed
    assert (
        "feature.momentum.window_short" not in prewarmed
    ), "dead key still present -- should have been replaced by window_fast/mid/slow"
    assert (
        "feature.momentum.window_long" not in prewarmed
    ), "dead key still present -- should have been replaced by window_fast/mid/slow"


# ---------------------------------------------------------------------------
# The regime kernels' HmmConfig is wired through the pipeline's config path (186-13 review, R2)
# ---------------------------------------------------------------------------


class _FakeConfigService:
    """Async `get` warms the cache from `values`; `get_sync` serves only what was warmed."""

    def __init__(self, values):
        self._values = values
        self._cache: dict = {}

    async def get(self, key, default=None):
        if key in self._values:
            self._cache[key] = self._values[key]
        return self._cache.get(key, default)

    def get_sync(self, key, default=None):
        return self._cache.get(key, default)


def _pipeline_with(values):
    from services.feature_vector_pipeline import FeatureVectorPipeline

    pipeline = FeatureVectorPipeline.__new__(FeatureVectorPipeline)
    pipeline._config_service = _FakeConfigService(values)
    return pipeline


def test_pipeline_loads_the_hmm_config_from_apr_not_defaults():
    import asyncio

    from tests.unit.intelligence.regime_kernel_fixtures import SMALL_HMM_APR

    values = {**SMALL_HMM_APR, "feature.hmm.n_components": 5}
    hmm = asyncio.run(_pipeline_with(values)._load_hmm_config())
    assert hmm.hmm_n_components == 5  # the APR value, not a default
    assert hmm.hmm_refit_every_bars_1d == 300


def test_pipeline_hmm_config_raises_on_a_missing_key():
    import asyncio

    import pytest

    from tests.unit.intelligence.regime_kernel_fixtures import SMALL_HMM_APR

    values = {k: v for k, v in SMALL_HMM_APR.items() if k != "alpha.hmm.random_state"}
    with pytest.raises(KeyError, match="alpha.hmm.random_state"):
        asyncio.run(_pipeline_with(values)._load_hmm_config())


def test_prewarm_prewarms_the_hmm_keys_and_builds_the_config_from_one_table():
    """The HMM keys are prewarmed by `_load_hmm_config`, and `from_values` reads them (with
    every other key) from that warm cache; it builds the hmm block itself."""
    source = _prewarm_source()
    assert "await self._load_hmm_config()" in source
    assert "FeatureFactoryConfig.from_values(" in source
