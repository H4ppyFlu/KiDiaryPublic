from datetime import datetime

from fastapi.testclient import TestClient


def test_health_reports_a_round_trip_through_the_api_to_the_database(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()

    # Neither of these could have come from anywhere but Postgres itself.
    assert body["database_version"].startswith("PostgreSQL ")
    assert datetime.fromisoformat(body["database_time"]).tzinfo is not None
