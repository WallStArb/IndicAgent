"""Unit tests for the 4 Tier-1 cross-TF confluence plugins (Plan 64-02).

Tests cover:
- Plugin instantiation and output field declaration
- Gradient output range [-1, +1] via np.tanh()
- Regime label correctness
- Missing data fallback (all-empty frames)
"""

import pandas as pd
import pytest

from src.intelligence.archive.confluence.cross_tf_orderflow_alignment import (
    CrossTFOrderFlowAlignmentPlugin,
)
from src.intelligence.archive.confluence.cross_tf_orderflow_alignment import (
    plugin as orderflow_plugin,
)
from src.intelligence.archive.confluence.cross_tf_regime_agreement import (
    CrossTFRegimeAgreementPlugin,
)
from src.intelligence.archive.confluence.cross_tf_regime_agreement import (
    plugin as regime_plugin,
)
from src.intelligence.archive.confluence.cross_tf_sr_confluence import (
    CrossTFSRConfluencePlugin,
)
from src.intelligence.archive.confluence.cross_tf_sr_confluence import (
    plugin as sr_plugin,
)
from src.intelligence.archive.confluence.squeeze_expansion_divergence import (
    SqueezeExpansionDivergencePlugin,
)
from src.intelligence.archive.confluence.squeeze_expansion_divergence import (
    plugin as squeeze_plugin,
)

# ---------------------------------------------------------------------------
# CrossTFSRConfluencePlugin
# ---------------------------------------------------------------------------


class TestCrossTFSRConfluencePlugin:
    @pytest.fixture
    def p(self) -> CrossTFSRConfluencePlugin:
        return CrossTFSRConfluencePlugin()

    def test_module_instance_exists(self) -> None:
        assert isinstance(sr_plugin, CrossTFSRConfluencePlugin)

    def test_plugin_name(self, p: CrossTFSRConfluencePlugin) -> None:
        assert p.name == "i6_CrossTFSRConfluence"

    def test_plugin_outputs_declared(self, p: CrossTFSRConfluencePlugin) -> None:
        assert "ctf_sr_confluence" in p.outputs
        assert "ctf_sr_regime" in p.outputs

    def test_missing_data_returns_fallback(self, p: CrossTFSRConfluencePlugin) -> None:
        result = p.compute_full({})
        assert result["ctf_sr_confluence"] == 0.0
        assert result["ctf_sr_regime"] == "no_confluence"

    def test_gradient_range(self, p: CrossTFSRConfluencePlugin) -> None:
        """Output must be in [-1, +1]."""
        frames = {
            "main": pd.DataFrame(
                {"close": [100.4], "high": [100.4], "low": [100.4], "volume": [1000]}
            ),
            "intel_1h": {"nearest_resistance": 100.5, "nearest_support": 99.5, "atr_14": 0.5},
            "intel_4h": {"nearest_resistance": 101.0, "nearest_support": 99.0, "atr_14": 1.0},
            "intel_5m": {"nearest_resistance": 100.1, "nearest_support": 99.9, "atr_14": 0.1},
            "intel_15m": {"nearest_resistance": 100.2, "nearest_support": 99.8, "atr_14": 0.2},
        }
        result = p.compute_full(frames)
        assert -1.0 <= result["ctf_sr_confluence"] <= 1.0

    def test_near_resistance_positive(self, p: CrossTFSRConfluencePlugin) -> None:
        """Price near resistance on all TFs -> positive confluence."""
        frames = {
            "main": pd.DataFrame(
                {"close": [100.1], "high": [100.1], "low": [100.1], "volume": [1000]}
            ),
            "intel_1h": {"nearest_resistance": 100.2, "nearest_support": 98.0, "atr_14": 1.0},
            "intel_4h": {"nearest_resistance": 100.3, "nearest_support": 97.0, "atr_14": 1.5},
            "intel_5m": {"nearest_resistance": 100.15, "nearest_support": 99.0, "atr_14": 0.5},
            "intel_15m": {"nearest_resistance": 100.2, "nearest_support": 99.5, "atr_14": 0.5},
        }
        result = p.compute_full(frames)
        assert result["ctf_sr_confluence"] > 0

    def test_compute_next_delegates(self, p: CrossTFSRConfluencePlugin) -> None:
        result_full = p.compute_full({})
        result_next = p.compute_next({})
        assert result_full == result_next


# ---------------------------------------------------------------------------
# CrossTFRegimeAgreementPlugin
# ---------------------------------------------------------------------------


class TestCrossTFRegimeAgreementPlugin:
    @pytest.fixture
    def p(self) -> CrossTFRegimeAgreementPlugin:
        return CrossTFRegimeAgreementPlugin()

    def test_module_instance_exists(self) -> None:
        assert isinstance(regime_plugin, CrossTFRegimeAgreementPlugin)

    def test_plugin_name(self, p: CrossTFRegimeAgreementPlugin) -> None:
        assert p.name == "i6_CrossTFRegimeAgreement"

    def test_plugin_outputs_declared(self, p: CrossTFRegimeAgreementPlugin) -> None:
        assert "ctf_hmm_regime_agreement" in p.outputs
        assert "ctf_hmm_regime_label" in p.outputs

    def test_missing_data_returns_fallback(self, p: CrossTFRegimeAgreementPlugin) -> None:
        result = p.compute_full({})
        assert result["ctf_hmm_regime_agreement"] == 0.0
        assert result["ctf_hmm_regime_label"] == "mixed"

    def test_all_trending_positive(self, p: CrossTFRegimeAgreementPlugin) -> None:
        """All TFs in trending regime -> positive agreement, all_trending label."""
        frames = {
            "intel_5m": {"hmm_regime": 1},
            "intel_15m": {"hmm_regime": 1},
            "intel_1h": {"hmm_regime": 2},
            "intel_4h": {"hmm_regime": 1},
        }
        result = p.compute_full(frames)
        assert result["ctf_hmm_regime_agreement"] > 0
        assert result["ctf_hmm_regime_label"] == "all_trending"

    def test_all_ranging_negative(self, p: CrossTFRegimeAgreementPlugin) -> None:
        """All TFs ranging -> negative agreement, all_ranging label."""
        frames = {
            "intel_5m": {"hmm_regime": 0},
            "intel_15m": {"hmm_regime": 0},
            "intel_1h": {"hmm_regime": 0},
            "intel_4h": {"hmm_regime": 0},
        }
        result = p.compute_full(frames)
        assert result["ctf_hmm_regime_agreement"] < 0
        assert result["ctf_hmm_regime_label"] == "all_ranging"

    def test_gradient_range(self, p: CrossTFRegimeAgreementPlugin) -> None:
        for regimes in [
            {"5m": 1, "15m": 2, "1h": 0, "4h": 1},
            {"5m": 0, "15m": 0, "1h": 1, "4h": 2},
        ]:
            frames = {f"intel_{tf}": {"hmm_regime": r} for tf, r in regimes.items()}
            result = p.compute_full(frames)
            assert -1.0 <= result["ctf_hmm_regime_agreement"] <= 1.0


# ---------------------------------------------------------------------------
# SqueezeExpansionDivergencePlugin
# ---------------------------------------------------------------------------


class TestSqueezeExpansionDivergencePlugin:
    @pytest.fixture
    def p(self) -> SqueezeExpansionDivergencePlugin:
        return SqueezeExpansionDivergencePlugin()

    def test_module_instance_exists(self) -> None:
        assert isinstance(squeeze_plugin, SqueezeExpansionDivergencePlugin)

    def test_plugin_name(self, p: SqueezeExpansionDivergencePlugin) -> None:
        assert p.name == "i6_SqueezeExpansionDivergence"

    def test_plugin_outputs_declared(self, p: SqueezeExpansionDivergencePlugin) -> None:
        assert "ctf_volatility_divergence" in p.outputs
        assert "ctf_volatility_regime" in p.outputs

    def test_missing_data_returns_fallback(self, p: SqueezeExpansionDivergencePlugin) -> None:
        result = p.compute_full({})
        assert result["ctf_volatility_divergence"] == 0.0
        assert result["ctf_volatility_regime"] == "mixed"

    def test_gradient_range(self, p: SqueezeExpansionDivergencePlugin) -> None:
        frames = {
            "intel_1h": {"atr_14": 0.03, "shannon_entropy": 0.8},
            "intel_4h": {"atr_14": 0.04, "shannon_entropy": 0.9},
            "intel_5m": {"atr_14": 0.005, "shannon_entropy": 0.2},
            "intel_15m": {"atr_14": 0.008, "shannon_entropy": 0.3},
        }
        result = p.compute_full(frames)
        assert -1.0 <= result["ctf_volatility_divergence"] <= 1.0

    def test_htf_expanding_ltf_squeezing_positive(
        self, p: SqueezeExpansionDivergencePlugin
    ) -> None:
        """HTF high vol, LTF low vol -> positive divergence (coiling signal)."""
        frames = {
            "intel_1h": {"atr_14": 0.05, "shannon_entropy": 1.0},
            "intel_4h": {"atr_14": 0.06, "shannon_entropy": 1.1},
            "intel_5m": {"atr_14": 0.001, "shannon_entropy": 0.1},
            "intel_15m": {"atr_14": 0.002, "shannon_entropy": 0.15},
        }
        result = p.compute_full(frames)
        assert result["ctf_volatility_divergence"] > 0


# ---------------------------------------------------------------------------
# CrossTFOrderFlowAlignmentPlugin
# ---------------------------------------------------------------------------


class TestCrossTFOrderFlowAlignmentPlugin:
    @pytest.fixture
    def p(self) -> CrossTFOrderFlowAlignmentPlugin:
        return CrossTFOrderFlowAlignmentPlugin()

    def test_module_instance_exists(self) -> None:
        assert isinstance(orderflow_plugin, CrossTFOrderFlowAlignmentPlugin)

    def test_plugin_name(self, p: CrossTFOrderFlowAlignmentPlugin) -> None:
        assert p.name == "i6_CrossTFOrderFlowAlignment"

    def test_plugin_outputs_declared(self, p: CrossTFOrderFlowAlignmentPlugin) -> None:
        assert "ctf_orderflow_alignment" in p.outputs
        assert "ctf_orderflow_regime" in p.outputs

    def test_missing_data_returns_fallback(self, p: CrossTFOrderFlowAlignmentPlugin) -> None:
        result = p.compute_full({})
        assert result["ctf_orderflow_alignment"] == 0.0
        assert result["ctf_orderflow_regime"] == "missing_data"

    def test_aligned_bull_positive(self, p: CrossTFOrderFlowAlignmentPlugin) -> None:
        """Strong buying pressure across all TFs -> positive alignment.

        ofi_ewma_5 is normalized by _OFI_NORM=1000 and cvd by _CVD_NORM=5000.
        Use values >> norm to ensure per-TF scores exceed _STRONG_THRESHOLD=0.3.
        """
        frames = {
            "intel_5m": {"ofi_ewma_5": 800.0, "cvd": 2000.0},
            "intel_15m": {"ofi_ewma_5": 700.0, "cvd": 1800.0},
            "intel_1h": {"ofi_ewma_5": 900.0, "cvd": 2500.0},
            "intel_4h": {"ofi_ewma_5": 850.0, "cvd": 2200.0},
        }
        result = p.compute_full(frames)
        assert result["ctf_orderflow_alignment"] > 0
        assert result["ctf_orderflow_regime"] == "aligned_bull"

    def test_aligned_bear_negative(self, p: CrossTFOrderFlowAlignmentPlugin) -> None:
        """Strong selling pressure across all TFs -> negative alignment."""
        frames = {
            "intel_5m": {"ofi_ewma_5": -800.0, "cvd": -2000.0},
            "intel_15m": {"ofi_ewma_5": -700.0, "cvd": -1800.0},
            "intel_1h": {"ofi_ewma_5": -900.0, "cvd": -2500.0},
            "intel_4h": {"ofi_ewma_5": -850.0, "cvd": -2200.0},
        }
        result = p.compute_full(frames)
        assert result["ctf_orderflow_alignment"] < 0
        assert result["ctf_orderflow_regime"] == "aligned_bear"

    def test_gradient_range(self, p: CrossTFOrderFlowAlignmentPlugin) -> None:
        frames = {
            "intel_5m": {"ofi_ewma_5": 500.0, "cvd": 200.0},
            "intel_15m": {"ofi_ewma_5": -300.0, "cvd": -100.0},
            "intel_1h": {"ofi_ewma_5": 800.0, "cvd": 500.0},
            "intel_4h": {"ofi_ewma_5": 100.0, "cvd": 50.0},
        }
        result = p.compute_full(frames)
        assert -1.0 <= result["ctf_orderflow_alignment"] <= 1.0
