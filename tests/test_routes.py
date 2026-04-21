"""
Integration tests for API routes using FastAPI TestClient.
All external services are mocked; these test the HTTP layer.
"""
import pytest
import json
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


# ============================================================================
# POST /trainee/single
# ============================================================================

class TestTraineeSingleRoute:
    def test_valid_request(self, client):
        payload = {
            "config": {
                "run_stage": "dev",
                "batch": "5",
                "role": "trainee",
                "is_mock": True,
                "group_id": "12",
            },
            "trainee": {
                "name": "John Doe",
                "email": "john@example.com",
                "password": "pass123",
            },
        }
        with patch("api.controllers.trainee_controller.TraineeService") as MockService:
            from api.models.trainee import TraineeResponse
            MockService.return_value.create_trainee_services.return_value = (
                TraineeResponse.success_response("ok", data={"alluser_id": "1"})
            )
            response = client.post("/trainee/single", json=payload)
            assert response.status_code == 200
            body = response.json()
            assert body["success"] is True

    def test_missing_name_returns_422(self, client):
        payload = {
            "config": {"run_stage": "dev"},
            "trainee": {"name": "", "email": "john@example.com"},
        }
        response = client.post("/trainee/single", json=payload)
        assert response.status_code == 422

    def test_invalid_email_returns_422(self, client):
        payload = {
            "config": {"run_stage": "dev"},
            "trainee": {"name": "John Doe", "email": "not-an-email"},
        }
        response = client.post("/trainee/single", json=payload)
        assert response.status_code == 422

    def test_missing_config_returns_422(self, client):
        payload = {
            "trainee": {"name": "John Doe", "email": "john@example.com"},
        }
        response = client.post("/trainee/single", json=payload)
        assert response.status_code == 422


# ============================================================================
# POST /webhook
# ============================================================================

class TestWebhookRoute:
    def test_valid_webhook(self, client):
        payload = {
            "status": "success",
            "batch": "5",
            "errors": [],
        }
        response = client.post("/webhook", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "received"

    def test_partial_success_webhook(self, client):
        payload = {
            "status": "partial_success",
            "batch": "5",
            "errors": [{"email": "x@y.com", "reason": "dup"}],
        }
        response = client.post("/webhook", json=payload)
        assert response.status_code == 200

    def test_failed_webhook(self, client):
        payload = {
            "status": "failed",
            "batch": "5",
            "errors": [{"email": "x@y.com", "reason": "fail"}],
        }
        response = client.post("/webhook", json=payload)
        assert response.status_code == 200

    def test_invalid_json(self, client):
        response = client.post(
            "/webhook",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400


# ============================================================================
# App-level checks
# ============================================================================

class TestAppSetup:
    def test_cors_middleware_present(self):
        middleware_classes = [m.cls.__name__ for m in app.user_middleware]
        assert "CORSMiddleware" in middleware_classes

    def test_all_routers_registered(self, client):
        openapi = client.get("/openapi.json").json()
        paths = list(openapi["paths"].keys())
        assert any("/trainee/single" in p for p in paths)
        assert any("/trainee/batch" in p for p in paths)
        assert any("/webhook" in p for p in paths)
        assert any("/env/" in p for p in paths)
