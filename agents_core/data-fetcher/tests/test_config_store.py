import json
import stat

from data_fetcher.config import Settings
from data_fetcher.config_store import LocalConfigStore


def test_local_config_store_roundtrip_and_permissions(tmp_path):
    path = tmp_path / "private" / "config.json"
    store = LocalConfigStore(path)
    configured = Settings(
        llm_api_key="llm-secret",
        llm_base_url="https://llm.example/v1",
        llm_model="test-model",
        iwencai_api_key="iwencai-secret",
        iwencai_base_url="https://iwencai.example",
    )
    store.save(configured)
    loaded = store.load(Settings())
    assert loaded.llm_api_key == "llm-secret"
    assert loaded.iwencai_api_key == "iwencai-secret"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert json.loads(path.read_text())["llm_model"] == "test-model"
