"""
Test suite for LLM configuration settings.

Tests for Ollama context window configuration and other LLM provider settings.
"""

from __future__ import annotations

from src.config.settings import Settings


class TestOllamaSettings:
    """Tests for Ollama-specific settings."""

    def test_ollama_num_ctx_default(self):
        """Verify default OLLAMA_NUM_CTX is 16384."""
        settings = Settings()
        assert settings.ollama_num_ctx == 16384

    def test_ollama_num_ctx_env_override(self, monkeypatch):
        """Verify OLLAMA_NUM_CTX can be overridden via environment variable."""
        monkeypatch.setenv("OLLAMA_NUM_CTX", "8192")
        settings = Settings()
        assert settings.ollama_num_ctx == 8192

    def test_ollama_num_ctx_custom_value(self, monkeypatch):
        """Verify OLLAMA_NUM_CTX can be set to custom values."""
        monkeypatch.setenv("OLLAMA_NUM_CTX", "32768")
        settings = Settings()
        assert settings.ollama_num_ctx == 32768

    def test_ollama_model_default(self):
        """Verify default Ollama model is qwen3.5:4b."""
        settings = Settings()
        assert settings.ollama_model == "qwen3.5:4b"

    def test_ollama_base_url_default(self):
        """Verify default Ollama base URL."""
        settings = Settings()
        assert settings.ollama_base_url == "http://localhost:11434"

    def test_ollama_num_ctx_is_integer(self, monkeypatch):
        """Verify OLLAMA_NUM_CTX is stored as an integer."""
        monkeypatch.setenv("OLLAMA_NUM_CTX", "4096")
        settings = Settings()
        assert isinstance(settings.ollama_num_ctx, int)
        assert settings.ollama_num_ctx == 4096
