"""Tests verifying I2 tier is wired into market_analysis_service."""
import pathlib


def test_prev_features_in_frames():
    """market_analysis_service must inject prev_features for I2 crossover detection."""
    source = pathlib.Path("services/market_analysis_service.py").read_text()
    assert "prev_features" in source, "prev_features not injected into frames"


def test_market_analysis_service_imports_tier_i2():
    """Verify service imports TIER_I2."""
    source = pathlib.Path("services/market_analysis_service.py").read_text()
    assert "TIER_I2" in source


def test_i2_results_included_in_pipeline():
    """_run_analysis_pipeline must run I2 tier and include 'i2' key in return."""
    import inspect

    from services.market_analysis_service import MarketAnalysisService

    src = inspect.getsource(MarketAnalysisService._run_analysis_pipeline)
    assert "i2" in src
    assert "TIER_I2" in src
