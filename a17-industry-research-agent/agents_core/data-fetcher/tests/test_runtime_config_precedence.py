import importlib.util
import os
import sys
from pathlib import Path


def test_env_file_does_not_overwrite_ui_runtime_configuration(tmp_path, monkeypatch):
    from data_fetcher import config
    target = tmp_path / "agents_core/data-fetcher/data_fetcher/config.py"
    target.parent.mkdir(parents=True)
    target.write_text(Path(config.__file__).read_text())
    (tmp_path / ".env").write_text("LLM_MODEL=disk-old-model\n")
    spec = importlib.util.spec_from_file_location("audit_config_precedence", target)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setenv("LLM_MODEL", "ui-new-model")
    assert module.Settings.from_env().llm_model == "ui-new-model"
    assert os.environ["LLM_MODEL"] == "ui-new-model"
