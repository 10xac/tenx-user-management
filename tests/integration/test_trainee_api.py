"""
API integration tests for trainee endpoints: POST /trainee/single, POST /trainee/admin-single.
Tests full HTTP request → middleware → route → controller → (mocked) service → response cycle.
"""
import pytest
from unittest.mock import patch, MagicMock
from api.models.trainee import TraineeResponse
from api.core.auth import verify_admin_access
from api.main import app


# ============================================================================
# Helper
# ============================================================================

def _payload(**overrides):
    """Build a valid /trainee/single payload with optional overrides."""
    base = {
        "config": {
            "run_stage": "dev",
            "batch": "5",
            "role": "trainee",
            "is_mock": True,
            "group_id": "12",
        },
        "trainee": {
            "name": "John Doe",
            "email": "john.doe@example.com",
            "password": "SecureP@ss1",
            "nationality": "Kenya",
            "gender": "Male",
            "date_of_birth": "1995-01-01",
            "vulnerable": "No",
            "status": "Accepted",
        },
    }
    for key, val in overrides.items():
        if key in base:
            base[key].update(val)
        else:
            base[key] = val
    return base


# ============================================================================
# POST /trainee/single — Happy Path
# ============================================================================

class TestCreateTraineeSingle:
    def test_success_returns_200(self, client, mock_trainee_service_success):
        resp = client.post("/trainee/single", json=_payload())
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["message"] == "Trainee created successfully"
        assert "data" in body
        assert body["data"]["alluser_id"] == "200"

    def test_response_contains_profile_and_trainee(self, client, mock_trainee_service_success):
        body = client.post("/trainee/single", json=_payload()).json()
        assert "profile" in body["data"]
        assert "trainee" in body["data"]

    def test_service_receives_correct_data(self, client, mock_trainee_service_success):
        client.post("/trainee/single", json=_payload(
            trainee={"name": "Jane Smith", "email": "jane@test.com"}
        ))
        call_args = mock_trainee_service_success.call_args
        tc = call_args[0][0]  # first positional arg = TraineeCreate
        assert tc.trainee.name == "Jane Smith"
        assert tc.trainee.email == "jane@test.com"
        assert tc.config.run_stage == "dev"

    def test_minimal_payload(self, client, mock_trainee_service_success):
        payload = {
            "config": {"run_stage": "dev"},
            "trainee": {"name": "Min User", "email": "min@test.com"},
        }
        resp = client.post("/trainee/single", json=payload)
        assert resp.status_code == 200

    def test_optional_fields_default(self, client, mock_trainee_service_success):
        payload = {
            "config": {"run_stage": "prod"},
            "trainee": {"name": "A B", "email": "a@b.com"},
        }
        resp = client.post("/trainee/single", json=payload)
        assert resp.status_code == 200


# ============================================================================
# POST /trainee/single — Validation Errors (422)
# ============================================================================

class TestCreateTraineeSingleValidation:
    def test_empty_name_returns_422(self, client):
        resp = client.post("/trainee/single", json=_payload(trainee={"name": ""}))
        assert resp.status_code == 422

    def test_whitespace_name_returns_422(self, client):
        resp = client.post("/trainee/single", json=_payload(trainee={"name": "   "}))
        assert resp.status_code == 422

    def test_numeric_only_name_returns_422(self, client):
        resp = client.post("/trainee/single", json=_payload(trainee={"name": "12345"}))
        assert resp.status_code == 422

    def test_empty_email_returns_422(self, client):
        resp = client.post("/trainee/single", json=_payload(trainee={"email": ""}))
        assert resp.status_code == 422

    def test_invalid_email_returns_422(self, client):
        resp = client.post("/trainee/single", json=_payload(trainee={"email": "not-an-email"}))
        assert resp.status_code == 422

    def test_missing_trainee_key_returns_422(self, client):
        resp = client.post("/trainee/single", json={"config": {"run_stage": "dev"}})
        assert resp.status_code == 422

    def test_missing_config_key_returns_422(self, client):
        resp = client.post("/trainee/single", json={"trainee": {"name": "A", "email": "a@b.com"}})
        assert resp.status_code == 422

    def test_missing_run_stage_returns_422(self, client):
        resp = client.post("/trainee/single", json={
            "config": {},
            "trainee": {"name": "A B", "email": "a@b.com"},
        })
        assert resp.status_code == 422

    def test_empty_body_returns_422(self, client):
        resp = client.post("/trainee/single", json={})
        assert resp.status_code == 422

    def test_no_body_returns_422(self, client):
        resp = client.post("/trainee/single")
        assert resp.status_code == 422

    def test_validation_error_body_format(self, client):
        resp = client.post("/trainee/single", json=_payload(trainee={"email": "bad"}))
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["error_type"] == "VALIDATION_ERROR"
        assert "error_message" in body["error"]
        assert "error_location" in body["error"]


# ============================================================================
# POST /trainee/single — Service-Level Failures
# ============================================================================

class TestCreateTraineeSingleServiceFailures:
    def test_service_error_response_propagated(self, client, mock_trainee_service_failure):
        resp = client.post("/trainee/single", json=_payload())
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["error_type"] == "USER_CREATION_ERROR"

    def test_service_exception_returns_400(self, client, mock_trainee_service_exception):
        resp = client.post("/trainee/single", json=_payload())
        assert resp.status_code == 400
        body = resp.json()
        assert "Strapi connection refused" in body["detail"]


# ============================================================================
# POST /trainee/admin-single — Auth Flow
# ============================================================================

class TestAdminTraineeAuth:
    def test_no_auth_header_returns_401(self, client):
        resp = client.post("/trainee/admin-single", json=_payload())
        assert resp.status_code in [401, 403]

    def test_invalid_token_format_returns_401(self, client):
        resp = client.post(
            "/trainee/admin-single",
            json=_payload(),
            headers={"Authorization": "InvalidScheme token123"},
        )
        assert resp.status_code in [401, 403]

    def test_auth_failure_returns_error_in_body(self, client, auth_error_response):
        app.dependency_overrides[verify_admin_access] = lambda: auth_error_response
        try:
            resp = client.post("/trainee/admin-single", json=_payload())
            body = resp.json()
            assert body["success"] is False
            assert body["error"]["error_type"] == "AUTH_ERROR"
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)

    def test_non_admin_role_returns_auth_error(self, client):
        error_resp = TraineeResponse.error_response(
            error_type="AUTH_ERROR",
            error_message="Insufficient permissions. Admin access required.",
            error_location="admin_verification",
            error_data={"user_role": "trainee"},
        )
        app.dependency_overrides[verify_admin_access] = lambda: error_resp
        try:
            resp = client.post("/trainee/admin-single", json=_payload())
            body = resp.json()
            assert body["success"] is False
            assert "Insufficient permissions" in body["error"]["error_message"]
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)

    def test_admin_success(self, client, admin_user, mock_trainee_service_success):
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        try:
            resp = client.post("/trainee/admin-single", json=_payload())
            assert resp.status_code == 200
            body = resp.json()
            assert body["success"] is True
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)


# ============================================================================
# POST /trainee/admin-single — Mock vs Real Users
# ============================================================================

class TestAdminTraineeMockVsReal:
    def test_mock_user_creation(self, client, admin_user, mock_trainee_service_success):
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        try:
            resp = client.post("/trainee/admin-single", json=_payload(config={"is_mock": True}))
            assert resp.status_code == 200
            assert resp.json()["success"] is True
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)

    def test_real_user_creation(self, client, admin_user, mock_trainee_service_success):
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        try:
            resp = client.post(
                "/trainee/admin-single",
                json=_payload(config={"is_mock": False, "login_url": "https://dev.10academy.org/login"}),
            )
            assert resp.status_code == 200
            assert resp.json()["success"] is True
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)


# ============================================================================
# Content-Type / Method Tests
# ============================================================================

class TestRequestFormats:
    def test_get_method_not_allowed(self, client):
        resp = client.get("/trainee/single")
        assert resp.status_code == 405

    def test_put_method_not_allowed(self, client):
        resp = client.put("/trainee/single", json=_payload())
        assert resp.status_code == 405

    def test_non_json_content_type_returns_422(self, client):
        resp = client.post(
            "/trainee/single",
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 422

    def test_malformed_json_returns_422(self, client):
        resp = client.post(
            "/trainee/single",
            content=b"{broken json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422
