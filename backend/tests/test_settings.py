import pytest
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.core.config import settings

client = TestClient(app)

def test_settings_config_api():
    # 1. 获取配置
    res = client.get("/api/v1/settings/config")
    assert res.status_code == 200
    data = res.json()
    assert "llm_api_key" in data
    assert "llm_base_url" in data
    assert "llm_model" in data
    assert "iwencai_api_key" in data

    # 2. 更新配置
    update_payload = {
        "llm_model": "test-deepseek-model",
        "llm_base_url": "https://api.test-deepseek.com",
    }
    update_res = client.post("/api/v1/settings/config", json=update_payload)
    assert update_res.status_code == 200
    assert settings.LLM_MODEL == "test-deepseek-model"
    assert settings.LLM_BASE_URL == "https://api.test-deepseek.com"

    # 3. 恢复默认
    reset_res = client.post("/api/v1/settings/reset")
    assert reset_res.status_code == 200
    assert settings.LLM_MODEL == "deepseek-v4-flash"
