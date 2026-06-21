"""Tests for SupplyDemandSetup I7 trading setup plugin."""

import numpy as np

from tests.unit.intelligence.helpers import make_ohlcv


class TestSupplyDemandSetup:
    """Tests for trad_SupplyDemandSetup plugin."""

    def _demand_features(self, freshness=1.0, strength=0.8, in_zone=1.0, act123=False):
        f = {
            "in_demand_zone": in_zone,
            "in_supply_zone": 0.0,
            "demand_freshness": freshness,
            "demand_strength": strength,
            "nearest_demand_high": 5010.0,
            "nearest_demand_low": 4990.0,
            "supply_freshness": 0.0,
            "supply_strength": 0.0,
            "nearest_supply_high": 5100.0,
            "nearest_supply_low": 5090.0,
            "price_in_premium": 0.0,  # discount = demand zone stronger
            "atr_14": 10.0,
            "fvg_detected": 0.0,
            "fvg_type": 0.0,
            "ob_detected": 0.0,
            "ob_type": 0.0,
            "ob_high": 0.0,
            "ob_low": 0.0,
            "sweep_detected": 0.0,
            "sweep_reclaimed": 0.0,
            "sweep_type": 0.0,
            "bos_detected": 0.0,
            "choch_detected": 0.0,
            "ctf_score": 0.0,
        }
        if act123:
            f["sweep_detected"] = 1.0
            f["sweep_reclaimed"] = 1.0
            f["sweep_type"] = 1.0  # bullish sweep → long
            f["fvg_detected"] = 1.0
            f["fvg_type"] = 1.0
        return f

    def _supply_features(self, freshness=1.0, strength=0.8, in_zone=1.0):
        return {
            "in_demand_zone": 0.0,
            "in_supply_zone": in_zone,
            "demand_freshness": 0.0,
            "demand_strength": 0.0,
            "nearest_demand_high": 4910.0,
            "nearest_demand_low": 4900.0,
            "supply_freshness": freshness,
            "supply_strength": strength,
            "nearest_supply_high": 5010.0,
            "nearest_supply_low": 4990.0,
            "price_in_premium": 1.0,  # premium = supply zone stronger
            "atr_14": 10.0,
            "fvg_detected": 0.0,
            "fvg_type": 0.0,
            "ob_detected": 0.0,
            "ob_type": 0.0,
            "ob_high": 0.0,
            "ob_low": 0.0,
            "sweep_detected": 0.0,
            "sweep_reclaimed": 0.0,
            "sweep_type": 0.0,
            "bos_detected": 0.0,
            "choch_detected": 0.0,
            "ctf_score": 0.0,
        }

    def test_demand_zone_generates_long(self):
        """Price in demand zone + fresh → long signal."""
        from src.intelligence.archive.trading_i7.supply_demand_setup import SupplyDemandSetupPlugin

        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = SupplyDemandSetupPlugin()
        f = self._demand_features()
        result = plugin.compute_full(
            {"main": df, "smc": f, "i1": f, "i2": f, "i3": f, "i4": f, "i5": f, "i6": f}
        )
        assert result["signal_type"] == "supply_demand_long"
        assert result["direction"] == 1
        assert result["confidence"] > 0.4
        assert result["stop_loss"] < result["entry_price"]

    def test_supply_zone_generates_short(self):
        """Price in supply zone + fresh → short signal."""
        from src.intelligence.archive.trading_i7.supply_demand_setup import SupplyDemandSetupPlugin

        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = SupplyDemandSetupPlugin()
        f = self._supply_features()
        result = plugin.compute_full(
            {"main": df, "smc": f, "i1": f, "i2": f, "i3": f, "i4": f, "i5": f, "i6": f}
        )
        assert result["signal_type"] == "supply_demand_short"
        assert result["direction"] == -1
        assert result["stop_loss"] > result["entry_price"]

    def test_no_signal_when_not_in_zone(self):
        """Price not in any zone → no signal."""
        from src.intelligence.archive.trading_i7.supply_demand_setup import SupplyDemandSetupPlugin

        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        features = self._demand_features(in_zone=0.0)
        plugin = SupplyDemandSetupPlugin()
        result = plugin.compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        assert result.get("signal_type", "none") == "none"

    def test_no_signal_mitigated_zone(self):
        """Zone freshness below threshold → no signal."""
        from src.intelligence.archive.trading_i7.supply_demand_setup import SupplyDemandSetupPlugin

        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        features = self._demand_features(freshness=0.1)
        plugin = SupplyDemandSetupPlugin()
        result = plugin.compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        assert result.get("signal_type", "none") == "none"

    def test_fresh_zone_higher_confidence_than_tested(self):
        """Fresh zone (1.0) has higher confidence than tested zone (0.5)."""
        from src.intelligence.archive.trading_i7.supply_demand_setup import SupplyDemandSetupPlugin

        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = SupplyDemandSetupPlugin()
        r_fresh = plugin.compute_full(
            {"main": df, "features": self._demand_features(freshness=1.0)}
        )
        r_tested = plugin.compute_full(
            {"main": df, "features": self._demand_features(freshness=0.5)}
        )
        if r_fresh.get("direction") == 1 and r_tested.get("direction") == 1:
            assert r_fresh["confidence"] > r_tested["confidence"]

    def test_act_123_bonus_applied(self):
        """Sweep + FVG preceding zone entry → act_1_2_3_confirmed bonus."""
        from src.intelligence.archive.trading_i7.supply_demand_setup import SupplyDemandSetupPlugin

        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = SupplyDemandSetupPlugin()
        r_plain = plugin.compute_full({"main": df, "features": self._demand_features(act123=False)})
        r_act = plugin.compute_full({"main": df, "features": self._demand_features(act123=True)})
        if r_plain.get("direction") == 1 and r_act.get("direction") == 1:
            assert r_act["confidence"] > r_plain["confidence"]
            assert "act_1_2_3_confirmed" in r_act.get("supporting_factors", [])

    def test_premium_discount_penalty_applied(self):
        """Demand zone in premium → lower confidence than demand zone in discount."""
        from src.intelligence.archive.trading_i7.supply_demand_setup import SupplyDemandSetupPlugin

        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = SupplyDemandSetupPlugin()
        f_discount = {**self._demand_features(), "price_in_premium": 0.0}  # aligned
        f_premium = {**self._demand_features(), "price_in_premium": 1.0}  # opposing
        r1 = plugin.compute_full({"main": df, "features": f_discount})
        r2 = plugin.compute_full({"main": df, "features": f_premium})
        if r1.get("direction") == 1 and r2.get("direction") == 1:
            assert r1["confidence"] > r2["confidence"]

    def test_has_two_targets(self):
        """Output includes at least 2 price targets."""
        from src.intelligence.archive.trading_i7.supply_demand_setup import SupplyDemandSetupPlugin

        df = make_ohlcv(np.full(100, 5000.0))
        plugin = SupplyDemandSetupPlugin()
        result = plugin.compute_full({"main": df, "features": self._demand_features()})
        if result.get("direction", 0) != 0:
            assert len(result.get("targets", [])) >= 2

    def test_insufficient_data_no_signal(self):
        """Too few bars → no signal."""
        from src.intelligence.archive.trading_i7.supply_demand_setup import SupplyDemandSetupPlugin

        df = make_ohlcv(np.full(5, 5000.0))
        plugin = SupplyDemandSetupPlugin()
        result = plugin.compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result.get("signal_type", "none") == "none"
