from fastapi.testclient import TestClient


def test_health_check(api_client: TestClient) -> None:
    response = api_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["version"] == "0.1.0"


def test_versioned_ping(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/ping")

    assert response.status_code == 200
    assert response.json() == {"message": "pong"}
