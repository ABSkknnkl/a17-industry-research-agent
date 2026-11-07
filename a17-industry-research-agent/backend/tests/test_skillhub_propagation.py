import pytest
from pathlib import Path
from backend.app.core.storage import storage
from backend.app.engine.state_machine import WorkflowEngine
from backend.app.schemas.workflow import RunCreateRequest, ResearchInput

@pytest.mark.anyio
async def test_selected_skills_propagation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    engine = WorkflowEngine()

    req = RunCreateRequest(
        project_id="proj-test-skills",
        input_data=ResearchInput(
            industry_topic="光模块",
            selected_skills=["竞争格局分析", "产业链全景拆解", "财务报表与杜邦分析"],
        ),
        review_stages=["data_fetch"],
    )
    state = await engine.create_run(req)
    assert state.run_id is not None

    # 检查 input_data.json 中是否完整持久化 selected_skills
    input_file = storage.get_run_dir(state.run_id) / "input_data.json"
    assert input_file.exists()
    loaded_req = RunCreateRequest.model_validate_json(input_file.read_text(encoding="utf-8"))
    assert loaded_req.input_data.selected_skills == ["竞争格局分析", "产业链全景拆解", "财务报表与杜邦分析"]
