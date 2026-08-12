from fastapi.testclient import TestClient


def test_health_check(api_client: TestClient) -> None:
    response = api_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["version"] == "0.1.0"


def test_readiness_reports_test_adapters_without_exposing_secrets(
    api_client: TestClient,
) -> None:
    response = api_client.get("/health/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is True
    assert payload["environment"] == "test"
    assert payload["mock_components"] == ["agent_1", "agent_2", "agent_4"]
    assert "api_key" not in str(payload).lower()
    assert "bearer" not in str(payload).lower()


def test_versioned_ping(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/ping")

    assert response.status_code == 200
    assert response.json() == {"message": "pong"}
