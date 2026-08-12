from fastapi.testclient import TestClient


def _run_payload() -> dict:
    return {
        "project_id": "project-api-1",
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


def test_frontend_can_start_review_and_read_a_workflow(api_client: TestClient) -> None:
    api_client.headers["Authorization"] = "Bearer test-bearer-token"
    started = api_client.post("/api/v1/runs", json=_run_payload())

    assert started.status_code == 201
    snapshot = started.json()
    assert snapshot["current_stage"] == "data_interpret"
    assert snapshot["status"] == "waiting_review"
    run_id = snapshot["run_id"]

    reviewed = api_client.post(
        f"/api/v1/runs/{run_id}/reviews",
        json={
            "run_id": run_id,
            "stage": "data_interpret",
            "action": "approve",
            "expected_revision": 1,
            "comment": "同意进入图表阶段",
            "edited_data": None,
        },
    )

    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "completed"

    fetched = api_client.get(f"/api/v1/runs/{run_id}")
    assert fetched.status_code == 200
    assert fetched.json()["stage_results"]["data_interpret"]["data"]["quality"]["passed"]


def test_frontend_can_revise_agent1_collection_scope(api_client: TestClient) -> None:
    api_client.headers["Authorization"] = "Bearer test-bearer-token"
    payload = _run_payload()
    payload["review_stages"] = ["data_fetch"]
    started = api_client.post("/api/v1/runs", json=payload)

    assert started.status_code == 201
    snapshot = started.json()
    assert snapshot["current_stage"] == "data_fetch"
    assert snapshot["status"] == "waiting_review"
    run_id = snapshot["run_id"]

    revised = api_client.post(
        f"/api/v1/runs/{run_id}/reviews",
        json={
            "run_id": run_id,
            "stage": "data_fetch",
            "action": "revise",
            "expected_revision": 1,
            "comment": "补充长时储能并改为2022—2025年数据。",
            "edited_data": {
                "data_fetch_options": {
                    "keywords": ["长时储能"],
                    "industry_scope": ["中国新型储能"],
                    "time_range": ["2022-01-01", "2025-12-31"],
                    "data_sources": ["官方公告"],
                    "metrics": ["新增装机量"],
                }
            },
        },
    )

    assert revised.status_code == 200
    revised_state = revised.json()
    assert revised_state["revision"] == 2
    assert revised_state["current_stage"] == "data_fetch"
    assert revised_state["status"] == "waiting_review"
    plan = revised_state["stage_results"]["data_fetch"]["data"]["retrieval_plan"]
    assert plan["applied_review_feedback"] == "补充长时储能并改为2022—2025年数据。"
    assert all(task["time_range"] == "2022-01-01至2025-12-31" for task in plan["tasks"])
    assert all(task["market_scope"] == ["中国新型储能"] for task in plan["tasks"])

    approved = api_client.post(
        f"/api/v1/runs/{run_id}/reviews",
        json={
            "run_id": run_id,
            "stage": "data_fetch",
            "action": "approve",
            "expected_revision": 2,
            "comment": "采集范围确认。",
            "edited_data": None,
        },
    )

    assert approved.status_code == 200
    assert approved.json()["status"] == "completed"


def test_frontend_can_review_and_regenerate_one_chapter(api_client: TestClient) -> None:
    api_client.headers["Authorization"] = "Bearer test-bearer-token"
    payload = _run_payload()
    payload["review_stages"] = ["chapter_write"]
    started = api_client.post("/api/v1/runs", json=payload)

    assert started.status_code == 201
    snapshot = started.json()
    assert snapshot["current_stage"] == "chapter_write"
    assert snapshot["status"] == "waiting_review"
    assert len(snapshot["stage_results"]["chapter_write"]["data"]["chapters"]) == 7
    run_id = snapshot["run_id"]

    regenerated = api_client.post(
        f"/api/v1/runs/{run_id}/reviews",
        json={
            "run_id": run_id,
            "stage": "chapter_write",
            "action": "revise",
            "expected_revision": 1,
            "comment": "仅修改第四章的竞争格局表达。",
            "edited_data": {
                "chapter_write_options": {
                    "target_chapter_ids": ["CH-04"],
                    "instruction": "保留证据边界并精简表达。",
                }
            },
        },
    )

    assert regenerated.status_code == 200
    revised = regenerated.json()
    assert revised["current_stage"] == "chapter_write"
    assert revised["status"] == "waiting_review"
    assert revised["revision"] == 2
    assert revised["stage_results"]["chapter_write"]["data"]["chapters"][3]["revision"] == 2

    approved = api_client.post(
        f"/api/v1/runs/{run_id}/reviews",
        json={
            "run_id": run_id,
            "stage": "chapter_write",
            "action": "approve",
            "expected_revision": 2,
            "comment": "章节修订通过。",
            "edited_data": None,
        },
    )

    assert approved.status_code == 200
    assert approved.json()["status"] == "completed"


def test_frontend_can_review_and_regenerate_chart_configuration(
    api_client: TestClient,
) -> None:
    api_client.headers["Authorization"] = "Bearer test-bearer-token"
    payload = _run_payload()
    payload["review_stages"] = ["chart_generate"]
    started = api_client.post("/api/v1/runs", json=payload)

    assert started.status_code == 201
    snapshot = started.json()
    assert snapshot["current_stage"] == "chart_generate"
    assert snapshot["status"] == "waiting_review"
    assert snapshot["stage_results"]["chart_generate"]["data"]["quality"]["passed"]
    run_id = snapshot["run_id"]

    revised_response = api_client.post(
        f"/api/v1/runs/{run_id}/reviews",
        json={
            "run_id": run_id,
            "stage": "chart_generate",
            "action": "revise",
            "expected_revision": 1,
            "comment": "改用横向柱状图并调整标题。",
            "edited_data": {
                "chart_generate_options": {
                    "title": "组件产量增速对比",
                    "bar_variant": "horizontal",
                    "color_theme": "colorblind_safe",
                }
            },
        },
    )

    assert revised_response.status_code == 200
    revised = revised_response.json()
    assert revised["status"] == "waiting_review"
    assert revised["revision"] == 2
    chart_data = revised["stage_results"]["chart_generate"]["data"]
    assert chart_data["chart_specs"][0]["title"] == "组件产量增速对比"
    assert chart_data["chart_specs"][0]["variant"] == "horizontal"
    assert revised["stage_results"]["chart_generate"]["artifacts"][0]["revision"] == 2
    decision_package = chart_data["decision_package"]

    approved = api_client.post(
        f"/api/v1/runs/{run_id}/reviews",
        json={
            "run_id": run_id,
            "stage": "chart_generate",
            "action": "approve",
            "expected_revision": 2,
            "comment": "图表审核通过。",
            "edited_data": None,
            "decision_id": decision_package["decision_id"],
            "risk_snapshot_sha256": decision_package["risk_snapshot_sha256"],
        },
    )

    assert approved.status_code == 200
    assert approved.json()["status"] == "completed"
