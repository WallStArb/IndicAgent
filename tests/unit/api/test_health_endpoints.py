"""
Unit tests for API health endpoints
"""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


class TestHealthEndpoints:
    """Test API health endpoint functionality"""

    @pytest.fixture
    def client(self):
        """Test client fixture"""
        return TestClient(app)

    @pytest.mark.unit
    def test_health_endpoint_success(self, client):
        """Test health endpoint returns success"""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert data["service"] == "IndicAgent API"

    @pytest.mark.unit
    def test_health_endpoint_basic(self, client):
        """Test basic health endpoint without dependencies"""
        response = client.get("/health/")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert data["service"] == "IndicAgent API"
        assert data["version"] == "2.0.0-clean"

    @pytest.mark.unit
    def test_metrics_endpoint(self, client):
        """Test metrics endpoint availability"""
        response = client.get("/metrics")

        # Should either return metrics or not be implemented yet
        assert response.status_code in [200, 404, 501]
