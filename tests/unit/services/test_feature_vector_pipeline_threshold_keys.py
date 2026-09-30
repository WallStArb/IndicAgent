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
    match = re.search(
        r"_THRESHOLD_KEYS: tuple\[tuple\[str, Any\], \.\.\.\] = \((.*?)\n    \)\n",
        _SOURCE,
        re.DOTALL,
    )
    assert match, "Could not parse _THRESHOLD_KEYS from feature_vector_pipeline.py"
    # \(\s*" (not \("): several entries wrap onto their own line, e.g.
    #     (
    #         "feature.sr.lookback_by_tf",
    #         {...},
    #     ),
    # -- a bare \("  would silently miss these, the same multi-line blind spot fixed
    # in _keys_read_building_feature_factory_config() below (found together, todo 242
    # code review, 2026-08-07: fixing only one side made the other side's pre-existing
    # gap visible as new false-positive "missing" entries).
    return set(re.findall(r'\(\s*"([a-zA-Z0-9_.]+)",', match.group(1)))


def _keys_read_building_feature_factory_config() -> set[str]:
    match = re.search(
        r"async def _prewarm_threshold_config\(self\).*?\n    async def ",
        _SOURCE,
        re.DOTALL,
    )
    assert match, "Could not parse _prewarm_threshold_config() from feature_vector_pipeline.py"
    return set(re.findall(r'_(?:int|float|dict|str|bool)\(\s*"([a-zA-Z0-9_.]+)"', match.group(0)))


def test_every_key_read_building_feature_factory_config_is_prewarmed():
    """A key read via _int()/_float()/_dict() here but absent from _THRESHOLD_KEYS
    silently cache-misses and falls through to the hardcoded default forever --
    config_state edits to that key have zero effect on the running pipeline."""
    used = _keys_read_building_feature_factory_config()
    prewarmed = _threshold_keys()
    missing = sorted(used - prewarmed)
    assert not missing, (
        f"{len(missing)} feature.* key(s) read while building FeatureFactoryConfig "
        f"are missing from _THRESHOLD_KEYS and will silently ignore config_state: {missing}"
    )


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


def test_prewarm_passes_the_hmm_config_into_feature_factory_config():
    match = re.search(
        r"async def _prewarm_threshold_config\(self\).*?\n    async def ", _SOURCE, re.DOTALL
    )
    assert match and "hmm=hmm_config" in match.group(0)
    assert "await self._load_hmm_config()" in match.group(0)
