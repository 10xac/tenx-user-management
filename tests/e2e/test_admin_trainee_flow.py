"""
E2E tests: Admin trainee creation — full pipeline with auth.
Route → Auth → Controller → TraineeService → DataProcessor → Strapi (mocked at boundary).
Verifies admin-specific behaviour: auth checks, background email tasks, mock vs real users.
"""
import pytest
from unittest.mock import patch, MagicMock, call
from api.core.auth import verify_admin_access
from api.main import app
from api.models.trainee import TraineeResponse


# ============================================================================
# Helpers
# ============================================================================

def _payload(**trainee_overrides):
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
    base["trainee"].update(trainee_overrides)
    return base


def _config_payload(**config_overrides):
    p = _payload()
    p["config"].update(config_overrides)
    return p


# ============================================================================
# Flow 1: Admin mock user creation — full pipeline
# ============================================================================

class TestAdminMockUserFlow:
    """Admin creates a mock trainee — full pipeline runs, no email sent."""

    def test_admin_mock_user_success(self, authed_client, strapi_boundary):
        resp = authed_client.post("/trainee/admin-single", json=_payload())
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["message"] == "Trainee created successfully"
        assert body["data"]["alluser_id"] == "alluser-200"

    def test_mock_user_uses_graphql_create(self, authed_client, strapi_boundary):
        """is_mock=True should use CommunicationManager.create_user (GraphQL)."""
        authed_client.post("/trainee/admin-single", json=_payload())
        cm = strapi_boundary["cm"]
        cm.create_user.assert_called_once()

    def test_mock_user_does_not_use_rest_register(self, authed_client, strapi_boundary):
        """is_mock=True should NOT call requests.post (REST register)."""
        with patch("api.services.trainee_service.requests.post") as mock_post:
            authed_client.post("/trainee/admin-single", json=_payload())
            mock_post.assert_not_called()

    def test_data_flows_through_full_pipeline(self, authed_client, strapi_boundary):
        authed_client.post("/trainee/admin-single", json=_payload(
            name="alice smith", email="ALICE@Test.COM"
        ))
        cm = strapi_boundary["cm"]
        user_data = cm.create_user.call_args[0][1]
        assert user_data["name"] == "Alice Smith"
        assert user_data["email"] == "alice@test.com"

    def test_profile_creation_receives_correct_data(self, authed_client, strapi_boundary):
        authed_client.post("/trainee/admin-single", json=_payload(
            name="Bob Jones", nationality="Nigeria", gender="Male"
        ))
        cm = strapi_boundary["cm"]
        profile = cm.insert_profile_information.call_args[0][1]
        assert profile["first_name"] == "Bob"
        assert profile["last_name"] == "Jones"
        assert profile["nationality"] == "Nigeria"
        assert profile["gender"] == "Male"


# ============================================================================
# Flow 2: Admin real user creation — full pipeline
# ============================================================================

class TestAdminRealUserFlow:
    """Admin creates a real trainee (is_mock=False) — uses REST register."""

    def test_real_user_uses_rest_register(self, authed_client, strapi_boundary, mock_requests_post):
        payload = _config_payload(is_mock=False)
        resp = authed_client.post("/trainee/admin-single", json=payload)
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        mock_requests_post.assert_called_once()

    def test_real_user_rest_failure_propagates(self, authed_client, strapi_boundary, mock_requests_post):
        mock_requests_post.return_value.status_code = 400
        mock_requests_post.return_value.text = "Email already registered"
        payload = _config_payload(is_mock=False)
        resp = authed_client.post("/trainee/admin-single", json=payload)
        body = resp.json()
        assert body["success"] is False
        assert "USER_CREATION_ERROR" in body["error"]["error_type"]

    def test_real_user_network_error_propagates(self, authed_client, strapi_boundary):
        import requests as req
        with patch("api.services.trainee_service.requests.post",
                    side_effect=req.exceptions.ConnectionError("Connection refused")):
            payload = _config_payload(is_mock=False)
            resp = authed_client.post("/trainee/admin-single", json=payload)
            body = resp.json()
            assert body["success"] is False
            assert "REQUEST_ERROR" in body["error"]["error_type"]


# ============================================================================
# Flow 3: Auth boundary enforcement
# ============================================================================

class TestAdminAuthEnforcement:
    def test_unauthenticated_request_rejected(self, client):
        """Without auth override, HTTPBearer returns 401/403."""
        resp = client.post("/trainee/admin-single", json=_payload())
        assert resp.status_code in [401, 403]

    def test_auth_error_response_propagated(self, client, strapi_boundary):
        error_resp = TraineeResponse.error_response(
            error_type="AUTH_ERROR",
            error_message="Token expired",
            error_location="token_validation",
            error_data={"reason": "jwt expired"},
        )
        app.dependency_overrides[verify_admin_access] = lambda: error_resp
        try:
            resp = client.post("/trainee/admin-single", json=_payload())
            body = resp.json()
            assert body["success"] is False
            assert body["error"]["error_type"] == "AUTH_ERROR"
            assert "Token expired" in body["error"]["error_message"]
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)

    def test_non_admin_role_rejected(self, client, strapi_boundary):
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

    def test_pipeline_does_not_run_on_auth_failure(self, client, strapi_boundary):
        """On auth failure, TraineeService should NOT be called."""
        error_resp = TraineeResponse.error_response(
            error_type="AUTH_ERROR",
            error_message="Invalid token",
            error_location="token_validation",
            error_data={},
        )
        app.dependency_overrides[verify_admin_access] = lambda: error_resp
        try:
            client.post("/trainee/admin-single", json=_payload())
            cm = strapi_boundary["cm"]
            cm.create_user.assert_not_called()
            cm.insert_all_users.assert_not_called()
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)


# ============================================================================
# Flow 4: Error handling through the pipeline
# ============================================================================

class TestAdminErrorHandling:
    def test_service_exception_returns_error_response(self, authed_client, strapi_boundary):
        cm = strapi_boundary["cm"]
        cm.create_user.side_effect = Exception("Strapi unreachable")
        resp = authed_client.post("/trainee/admin-single", json=_payload())
        # create_trainee_services catches exceptions and returns error dict
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "USER_CREATION_ERROR" in body["error"]["error_type"]

    def test_validation_error_returns_422(self, authed_client, strapi_boundary):
        resp = authed_client.post("/trainee/admin-single", json={
            "config": {"run_stage": "dev"},
            "trainee": {"name": "", "email": "bad"},
        })
        assert resp.status_code == 422
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["error_type"] == "VALIDATION_ERROR"

    def test_cleanup_on_profile_failure(self, authed_client, strapi_boundary):
        cm = strapi_boundary["cm"]
        cm.insert_profile_information.side_effect = Exception("Profile table locked")
        resp = authed_client.post("/trainee/admin-single", json=_payload())
        body = resp.json()
        assert body["success"] is False
        cm.delete_alluser.assert_called()
        cm.delete_user.assert_called()
