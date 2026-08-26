"""Functional tests for run history listing and revision snapshots."""

from fastapi.testclient import TestClient


def _run_payload(*, project_id: str, topic: str) -> dict:
    return {
        "project_id": project_id,
        "input_data": {
            "industry_topic": topic,
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


def _start_run(api_client: TestClient, *, project_id: str, topic: str) -> str:
    started = api_client.post(
        "/api/v1/runs", json=_run_payload(project_id=project_id, topic=topic)
    )
    assert started.status_code == 201
    return started.json()["run_id"]


def test_list_runs_returns_started_runs_newest_first(api_client: TestClient) -> None:
    api_client.headers["Authorization"] = "Bearer test-bearer-token"
    first_id = _start_run(
        api_client, project_id="project-history-1", topic="中国光伏制造行业"
    )
    second_id = _start_run(
        api_client, project_id="project-history-2", topic="中国新能源汽车行业"
    )

    listed = api_client.get("/api/v1/runs")

    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 2
    assert body["offset"] == 0
    assert body["limit"] == 20
    assert len(body["items"]) == 2
    # Newest run first.
    assert body["items"][0]["run_id"] == second_id
    assert body["items"][1]["run_id"] == first_id
    summaries = {item["run_id"]: item for item in body["items"]}
    assert summaries[first_id]["title"] == "中国光伏制造行业"
    assert summaries[first_id]["project_id"] == "project-history-1"
    assert summaries[first_id]["status"] == "waiting_review"
    assert summaries[first_id]["current_stage"] == "data_interpret"
    assert summaries[first_id]["revision"] == 1
    assert summaries[first_id]["created_at"]
    assert summaries[first_id]["updated_at"]


def test_list_runs_supports_pagination(api_client: TestClient) -> None:
    api_client.headers["Authorization"] = "Bearer test-bearer-token"
    _start_run(api_client, project_id="project-page-1", topic="中国光伏制造行业")
    _start_run(api_client, project_id="project-page-2", topic="中国新能源汽车行业")

    paged = api_client.get("/api/v1/runs", params={"offset": 1, "limit": 1})

    assert paged.status_code == 200
    body = paged.json()
    assert body["total"] == 2
    assert body["offset"] == 1
    assert body["limit"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["project_id"] == "project-page-1"

    invalid = api_client.get("/api/v1/runs", params={"limit": 0})
    assert invalid.status_code == 422


def test_revisions_list_and_snapshot_after_revise(api_client: TestClient) -> None:
    api_client.headers["Authorization"] = "Bearer test-bearer-token"
    run_id = _start_run(
        api_client, project_id="project-revision-1", topic="中国光伏制造行业"
    )

    revised = api_client.post(
        f"/api/v1/runs/{run_id}/reviews",
        json={
            "run_id": run_id,
            "stage": "data_interpret",
            "action": "revise",
            "expected_revision": 1,
            "comment": "提升分析深度。",
            "edited_data": {
                "analysis_depth": "deep",
                "risk_preference": "conservative",
            },
        },
    )
    assert revised.status_code == 200
    assert revised.json()["revision"] == 2

    revisions = api_client.get(f"/api/v1/runs/{run_id}/revisions")
    assert revisions.status_code == 200
    revision_body = revisions.json()
    assert revision_body["run_id"] == run_id
    assert revision_body["current_revision"] == 2
    assert [item["revision"] for item in revision_body["revisions"]] == [2, 1]

    snapshot_one = api_client.get(f"/api/v1/runs/{run_id}/revisions/1")
    assert snapshot_one.status_code == 200
    assert snapshot_one.json()["revision"] == 1
    assert snapshot_one.json()["status"] == "waiting_review"

    snapshot_two = api_client.get(f"/api/v1/runs/{run_id}/revisions/2")
    assert snapshot_two.status_code == 200
    assert snapshot_two.json()["revision"] == 2

    missing = api_client.get(f"/api/v1/runs/{run_id}/revisions/999")
    assert missing.status_code == 404


def test_history_unknown_run_returns_404(api_client: TestClient) -> None:
    api_client.headers["Authorization"] = "Bearer test-bearer-token"

    assert (
        api_client.get("/api/v1/runs/run-does-not-exist").status_code == 404
    )
    assert (
        api_client.get("/api/v1/runs/run-does-not-exist/revisions").status_code == 404
    )
    assert (
        api_client.get("/api/v1/runs/run-does-not-exist/revisions/1").status_code == 404
    )
