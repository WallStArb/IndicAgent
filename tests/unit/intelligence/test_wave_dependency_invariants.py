"""Tests proving wave dependency structure is correct and mtf_volatility is independent."""

from src.intelligence.archive.i5_patterns.mtf_volatility import MTFVolatilityPlugin
from src.intelligence.register_plugins import (
    I2_WAVE_A,
    I2_WAVE_B,
    I4_WAVE_A,
    I4_WAVE_B,
    SMC_WAVE_A,
    SMC_WAVE_B,
    TIER_I2,
    TIER_I4,
    TIER_SMC,
)


class TestWaveListInvariants:
    """Wave sub-lists must exactly partition their parent TIER list."""

    def test_i2_wave_union(self):
        assert set(I2_WAVE_A) | set(I2_WAVE_B) == set(TIER_I2)

    def test_i4_wave_union(self):
        assert set(I4_WAVE_A) | set(I4_WAVE_B) == set(TIER_I4)

    def test_smc_wave_union(self):
        assert set(SMC_WAVE_A) | set(SMC_WAVE_B) == set(TIER_SMC)

    def test_i2_waves_disjoint(self):
        assert set(I2_WAVE_A) & set(I2_WAVE_B) == set()

    def test_i4_waves_disjoint(self):
        assert set(I4_WAVE_A) & set(I4_WAVE_B) == set()

    def test_smc_waves_disjoint(self):
        assert set(SMC_WAVE_A) & set(SMC_WAVE_B) == set()


class TestMTFVolatilityIndependence:
    """mtf_volatility must not depend on bollinger_squeeze output (same-wave violation)."""

    def test_no_squeeze_active_key_needed(self):
        """compute_full with no squeeze_active key returns valid output."""
        plugin = MTFVolatilityPlugin()
        frames = {
            "i1": {},
            "i2": {},
            "i3": {},
            "i4": {},
            "i5": {},
            "smc": {},
            "i6": {},
            "intel_15m": {},
            "intel_1h": {},
        }
        result = plugin.compute_full(frames)
        assert result["squeeze_within_expansion"] == 0.0
        assert "mtf_vol_expansion_15m" in result
        assert "mtf_vol_expansion_1h" in result
        assert "vol_divergence_score" in result

    def test_independent_squeeze_from_bb_kc(self):
        """Detects squeeze from BB/KC bands directly, not squeeze_active."""
        plugin = MTFVolatilityPlugin()
        # BB inside KC = squeeze condition
        frames = {
            "i1": {
                "bb_20_2_upper": 100.5,
                "bb_20_2_lower": 99.5,
                "keltner_upper": 101.0,
                "keltner_lower": 99.0,
            },
            "i2": {
                "bb_20_2_upper": 100.5,
                "bb_20_2_lower": 99.5,
                "keltner_upper": 101.0,
                "keltner_lower": 99.0,
            },
            "i3": {
                "bb_20_2_upper": 100.5,
                "bb_20_2_lower": 99.5,
                "keltner_upper": 101.0,
                "keltner_lower": 99.0,
            },
            "i4": {
                "bb_20_2_upper": 100.5,
                "bb_20_2_lower": 99.5,
                "keltner_upper": 101.0,
                "keltner_lower": 99.0,
            },
            "i5": {
                "bb_20_2_upper": 100.5,
                "bb_20_2_lower": 99.5,
                "keltner_upper": 101.0,
                "keltner_lower": 99.0,
            },
            "smc": {
                "bb_20_2_upper": 100.5,
                "bb_20_2_lower": 99.5,
                "keltner_upper": 101.0,
                "keltner_lower": 99.0,
            },
            "i6": {
                "bb_20_2_upper": 100.5,
                "bb_20_2_lower": 99.5,
                "keltner_upper": 101.0,
                "keltner_lower": 99.0,
            },
            "intel_15m": {"vol_expansion": 1.0},
            "intel_1h": {"vol_expansion": 1.0},
        }
        result = plugin.compute_full(frames)
        assert result["squeeze_within_expansion"] > 0.0  # Continuous gradient, not binary
