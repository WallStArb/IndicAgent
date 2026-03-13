# tests/unit/intelligence/test_plugin_asset_class_guard.py
from typing import ClassVar
from src.core.models import AssetClass


class TestPluginProtocolHasValidAssetClasses:
    def test_indicator_plugin_has_valid_asset_classes(self):
        from src.intelligence.plugins import IndicatorPlugin
        # ClassVar annotations live in __annotations__, not accessible via hasattr on Protocol
        assert "valid_asset_classes" in IndicatorPlugin.__annotations__

    def test_pattern_plugin_has_valid_asset_classes(self):
        from src.intelligence.plugins import PatternPlugin
        assert "valid_asset_classes" in PatternPlugin.__annotations__


class TestPluginDefaultIsAllAssetClasses:
    """A plugin without valid_asset_classes declared gets all asset classes by default."""

    def test_getattr_default_is_all(self):
        from src.intelligence.plugins import IndicatorPlugin
        from src.core.models import AssetClass

        class MinimalPlugin:
            name = "test_plugin"
            outputs = frozenset()
            min_lookback = 1
            supports_incremental = False
            capability_tags = frozenset()
            inputs = []
            _state = {}

            def compute_full(self, frames): return {}
            def compute_next(self, windows): return {}

        plugin = MinimalPlugin()
        allowed = getattr(plugin, "valid_asset_classes", frozenset(AssetClass))
        assert AssetClass.FUTURES in allowed
        assert AssetClass.EQUITY in allowed
        assert AssetClass.CRYPTO in allowed

    def test_restricted_plugin_skips_wrong_asset_class(self):
        from src.core.models import AssetClass

        class FuturesOnlyPlugin:
            name = "futures_only"
            outputs = frozenset({"fut_signal"})
            min_lookback = 1
            supports_incremental = False
            capability_tags = frozenset()
            inputs = []
            valid_asset_classes: ClassVar[frozenset] = frozenset({AssetClass.FUTURES})
            _state = {}

            def compute_full(self, frames): return {"fut_signal": 1.0}
            def compute_next(self, windows): return {}

        plugin = FuturesOnlyPlugin()
        allowed = getattr(plugin, "valid_asset_classes", frozenset(AssetClass))
        assert AssetClass.EQUITY not in allowed
        assert AssetClass.FUTURES in allowed
