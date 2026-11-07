from fastapi.testclient import TestClient
import pytest
from backend.app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_list_skills_catalog(client: TestClient):
    response = client.get("/api/v1/skills")
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "agents" in data
    assert data["total"] == 66
    assert len(data["agents"]) == 5

    # 验证五大智能体分别存在且各自拥有独立的 skills
    agents_by_stage = {a["stage_id"]: a for a in data["agents"]}
    assert "data_fetch" in agents_by_stage
    assert "data_interpret" in agents_by_stage
    assert "chart_generate" in agents_by_stage
    assert "chapter_write" in agents_by_stage
    assert "report_fusion" in agents_by_stage

    assert agents_by_stage["data_fetch"]["skills_count"] == 25
    assert agents_by_stage["data_interpret"]["skills_count"] == 20
    assert agents_by_stage["chart_generate"]["skills_count"] == 6
    assert agents_by_stage["chapter_write"]["skills_count"] == 10
    assert agents_by_stage["report_fusion"]["skills_count"] == 5

    # 验证字段完整性
    sample_skill = agents_by_stage["data_fetch"]["skills"][0]
    assert "id" in sample_skill
    assert "name" in sample_skill
    assert "description" in sample_skill
    assert "category" in sample_skill


def test_get_skill_detail(client: TestClient):
    response = client.get("/api/v1/skills/data_fetch/hithink-finance-query")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "hithink-finance-query"
    assert "财务" in data["name"]
    assert len(data["full_doc"]) > 50

    # 404 测试
    resp_404 = client.get("/api/v1/skills/data_fetch/non-existent-skill")
    assert resp_404.status_code == 404
