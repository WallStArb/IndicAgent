import os

from src.config.settings import Settings


def test_zai_settings_defaults():
    """ZAI settings have correct defaults when no env vars are set."""
    # Temporarily clear any ZAI env vars that might be set in the dev environment
    _saved = {}
    for key in ("ZAI_API_KEY", "ZAI_BASE_URL", "ZAI_MODEL", "ZAI_TIMEOUT_SEC"):
        if key in os.environ:
            _saved[key] = os.environ.pop(key)
    try:
        settings = Settings(_env_file=None)
        assert settings.zai_api_key == ""
        assert settings.zai_base_url == "https://api.z.ai/api/paas/v4"
        assert settings.zai_model == "glm-5"
        assert settings.zai_timeout_sec == 30.0
    finally:
        os.environ.update(_saved)


def test_zai_settings_from_env():
    """ZAI settings load from environment variables."""
    os.environ["ZAI_API_KEY"] = "test-key"
    os.environ["ZAI_BASE_URL"] = "https://custom.z.ai/v4"
    os.environ["ZAI_MODEL"] = "glm-5-custom"
    os.environ["ZAI_TIMEOUT_SEC"] = "45.0"
    settings = Settings()
    assert settings.zai_api_key == "test-key"
    assert settings.zai_base_url == "https://custom.z.ai/v4"
    assert settings.zai_model == "glm-5-custom"
    assert settings.zai_timeout_sec == 45.0
    # Cleanup
    del os.environ["ZAI_API_KEY"]
    del os.environ["ZAI_BASE_URL"]
    del os.environ["ZAI_MODEL"]
    del os.environ["ZAI_TIMEOUT_SEC"]
