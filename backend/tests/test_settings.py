import pytest
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.core.config import Settings, settings

client = TestClient(app)


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    """测试隔离（2026-10-02 排查 backend/tests 非确定性失败时补的护栏）：

    1. user_settings_file 重定向到 tmp——update/reset 原本直接写项目
       data/user_settings.json，会把 .env 的真实 API key 落盘并跨 pytest run 残留，
       后续 run 加载后结果随文件存在与否漂移。
    2. 置空 IWENCAI_API_KEY——路由对空请求串有 ``req or settings.IWENCAI_API_KEY``
       兜底，不置空时 .env 的真实 key 会让"空 key 拒绝"用例变成真实外呼，
       断言随网络/凭证状态波动。
    """
    monkeypatch.setattr(
        Settings,
        "user_settings_file",
        property(lambda self: tmp_path / "user_settings.json"),
    )
    monkeypatch.setattr(settings, "IWENCAI_API_KEY", "")
    return settings


def test_settings_config_api(isolated_settings):
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


def test_iwencai_empty_key_rejected(isolated_settings):
    res = client.post("/api/v1/settings/test-iwencai", json={"iwencai_api_key": ""})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is False
    assert "不能为空" in data["message"]
