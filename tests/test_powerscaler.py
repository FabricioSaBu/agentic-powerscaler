import pytest
from fastapi.testclient import TestClient
from src.main import app


def test_evaluate_matchup_endpoint():
    payload = {
        "contender_a": "Goku (Ultra Instinct)",
        "contender_b": "Superman (Prime One Million)",
        "battle_environment": "Neutral Multiversal Void",
        "include_cinematic_script": True
    }
    with TestClient(app) as client:
        response = client.post("/api/v1/matchup/evaluate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "report_id" in data
    assert "verdict" in data
    assert data["verdict"]["winner"] in [payload["contender_a"], payload["contender_b"]]
    assert len(data["cinematic_battle_script"]) > 0
