"""Tests for market_analysis_service — I3→I6 analysis consuming indicators stream."""

import pandas as pd


def test_market_analysis_service_imports():
    """Ensure market_analysis_service exists and has the right class."""
    from services.market_analysis_service import MarketAnalysisService

    svc = MarketAnalysisService()
    assert hasattr(svc, "_run_analysis_pipeline")


def test_run_analysis_pipeline_requires_features():
    """Pipeline must return a dict when called with minimal frames."""
    from services.market_analysis_service import MarketAnalysisService

    svc = MarketAnalysisService()
    frames = {
        "main": pd.DataFrame(
            [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 500}] * 30
        ),
        "features": {},
    }

    result = svc._run_analysis_pipeline("ES", "1m", frames)
    assert isinstance(result, dict)
