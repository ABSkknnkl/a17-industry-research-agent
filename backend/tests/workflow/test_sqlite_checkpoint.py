from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def _run_payload() -> dict:
    return {
        "project_id": "persistent-project",
        "input_data": {
            "industry_topic": "中国光伏制造行业",
            "market_scope": ["中国内地"],
            "security_types": ["普通股"],
            "reporting_currency": "CNY",
            "research_as_of": "2026-06-30",
            "focus_questions": ["行业供需是否改善？"],
            "evidence_items": [
                {
                    "evidence_id": "E-001",
                    "metric_name": "组件产量同比增速",
                    "value": 18.2,
                    "unit": "%",
                    "period_end": "2026-05-31",
                    "available_at": "2026-06-20",
                    "audit_status": "not_applicable",
                    "restatement_status": "not_applicable",
                    "scope": "中国光伏组件行业汇总口径",
                    "market": "中国内地",
                    "exchange": "不适用",
                    "security_type": "行业汇总",
                    "currency": "不适用",
                    "accounting_standard": "不适用",
                    "corporate_action_adjustment": "not_applicable",
                    "source_name": "行业协会月报",
                    "source_locator": "2026年5月月报表2",
                    "grade": "C",
                }
            ],
        },
        "review_stages": ["data_interpret"],
    }


def test_workflow_survives_application_restart(
    tmp_path: Path,
) -> None:
    checkpoint_path = tmp_path / "checkpoints.sqlite"
    headers = {"Authorization": "Bearer test-bearer-token"}

    with TestClient(
        create_app(checkpoint_database_path=checkpoint_path), headers=headers
    ) as client:
        started = client.post("/api/v1/runs", json=_run_payload())
        assert started.status_code == 201
        run_id = started.json()["run_id"]
        assert started.json()["status"] == "waiting_review"

    with TestClient(
        create_app(checkpoint_database_path=checkpoint_path), headers=headers
    ) as client:
        restored = client.get(f"/api/v1/runs/{run_id}")
        assert restored.status_code == 200
        assert restored.json()["status"] == "waiting_review"

        reviewed = client.post(
            f"/api/v1/runs/{run_id}/reviews",
            json={
                "run_id": run_id,
                "stage": "data_interpret",
                "action": "approve",
                "expected_revision": 1,
                "comment": "重启后继续进入图表阶段。",
                "edited_data": None,
            },
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["status"] == "completed"
