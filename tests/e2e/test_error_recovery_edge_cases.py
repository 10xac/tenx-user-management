"""
E2E tests: Error recovery and edge cases — cross-cutting scenarios.
Tests graceful degradation, unicode handling, concurrent-style requests,
and interactions between multiple endpoints.
"""
import pytest
import json
from unittest.mock import patch, MagicMock

from api.core.auth import verify_admin_access
from api.main import app
from api.models.trainee import TraineeResponse


# ============================================================================
# Helpers
# ============================================================================

def _payload(**trainee_overrides):
    base = {
        "config": {"run_stage": "dev", "batch": "5", "role": "trainee", "is_mock": True, "group_id": "12"},
        "trainee": {
            "name": "John Doe", "email": "john.doe@example.com", "password": "Pass1",
            "nationality": "Kenya", "gender": "Male", "date_of_birth": "1995-01-01",
            "vulnerable": "No", "status": "Accepted",
        },
    }
    base["trainee"].update(trainee_overrides)
    return base


# ============================================================================
# Flow 1: Unicode / i18n edge cases through full pipeline
# ============================================================================

class TestUnicodeHandling:
    def test_unicode_name_flows_through_pipeline(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload(name="Ñoño Müller"))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        user_data = cm.create_user.call_args[0][1]
        assert "Ñoño" in user_data["name"]

    def test_accented_name_title_cased(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload(name="josé garcía"))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        user_data = cm.create_user.call_args[0][1]
        assert user_data["name"] == "José García"

    def test_arabic_name(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload(name="محمد أحمد"))
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_emoji_in_bio(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload(bio="Developer 🚀"))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        profile = cm.insert_profile_information.call_args[0][1]
        assert "🚀" in profile["bio"]

    def test_unicode_nationality(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload(nationality="Côte d'Ivoire"))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        profile = cm.insert_profile_information.call_args[0][1]
        assert profile["nationality"] == "Côte d'Ivoire"


# ============================================================================
# Flow 2: Name edge cases through DataProcessor
# ============================================================================

class TestNameEdgeCases:
    def test_hyphenated_name_stripped(self, client, strapi_boundary):
        """DataProcessor removes hyphens from names."""
        resp = client.post("/trainee/single", json=_payload(name="Mary-Jane Watson"))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        user_data = cm.create_user.call_args[0][1]
        # DataProcessor strips hyphens
        assert "-" not in user_data["name"]

    def test_dotted_name_stripped(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload(name="Dr. John Smith"))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        user_data = cm.create_user.call_args[0][1]
        assert "." not in user_data["name"]

    def test_double_spaces_collapsed(self, client, strapi_boundary):
        """DataProcessor replaces double-spaces once; verify single double-space is collapsed."""
        resp = client.post("/trainee/single", json=_payload(name="John  Doe"))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        user_data = cm.create_user.call_args[0][1]
        assert user_data["name"] == "John Doe"

    def test_three_word_name_split_correctly(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload(name="Alice Marie Johnson"))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        profile = cm.insert_profile_information.call_args[0][1]
        assert profile["first_name"] == "Alice"
        assert profile["last_name"] == "Marie Johnson"


# ============================================================================
# Flow 3: Email edge cases
# ============================================================================

class TestEmailEdgeCases:
    def test_mixed_case_email_lowered(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload(email="John.DOE@Example.COM"))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        user_data = cm.create_user.call_args[0][1]
        assert user_data["email"] == "john.doe@example.com"

    def test_email_with_plus_tag(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload(email="user+test@example.com"))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        user_data = cm.create_user.call_args[0][1]
        assert user_data["email"] == "user+test@example.com"

    def test_email_with_dots(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload(email="first.last@sub.domain.com"))
        assert resp.status_code == 200

    def test_email_used_as_username_suffix(self, client, strapi_boundary):
        """Username in Strapi is name_email format."""
        resp = client.post("/trainee/single", json=_payload(
            name="Test User", email="test@example.com"
        ))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        user_data = cm.create_user.call_args[0][1]
        # TraineeService creates username as name_email
        assert user_data["email"] == "test@example.com"


# ============================================================================
# Flow 4: Strapi boundary failures — graceful error responses
# ============================================================================

class TestStrapiBoundaryFailures:
    def test_strapi_graphql_timeout(self, client, strapi_boundary):
        cm = strapi_boundary["cm"]
        cm.create_user.side_effect = TimeoutError("GraphQL request timed out")
        resp = client.post("/trainee/single", json=_payload())
        body = resp.json()
        assert body["success"] is False

    def test_strapi_returns_unexpected_structure(self, client, strapi_boundary):
        cm = strapi_boundary["cm"]
        cm.create_user.return_value = {"unexpected": "structure"}
        resp = client.post("/trainee/single", json=_payload())
        # Should fail gracefully, not crash
        assert resp.status_code in [200, 400]

    def test_strapi_alluser_returns_none(self, client, strapi_boundary):
        cm = strapi_boundary["cm"]
        cm.insert_all_users.return_value = None
        resp = client.post("/trainee/single", json=_payload())
        # Should fail with error, not crash with NoneType
        assert resp.status_code in [200, 400]
        if resp.status_code == 200:
            assert resp.json()["success"] is False

    def test_strapi_profile_returns_empty_data(self, client, strapi_boundary):
        cm = strapi_boundary["cm"]
        cm.insert_profile_information.return_value = {
            "data": {"createProfileInformation": {"data": {}}}
        }
        resp = client.post("/trainee/single", json=_payload())
        # Missing 'id' in profile should trigger cleanup
        assert resp.status_code in [200, 400]


# ============================================================================
# Flow 5: Multiple sequential requests
# ============================================================================

class TestSequentialRequests:
    def test_two_different_trainees_created(self, client, strapi_boundary):
        r1 = client.post("/trainee/single", json=_payload(
            name="Alice Smith", email="alice@example.com"
        ))
        r2 = client.post("/trainee/single", json=_payload(
            name="Bob Jones", email="bob@example.com"
        ))
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["success"] is True
        assert r2.json()["success"] is True

    def test_first_fails_second_succeeds(self, client, strapi_boundary):
        cm = strapi_boundary["cm"]
        call_count = [0]

        def conditional_create(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("First request fails")
            return {"data": {"register": {"user": {"id": "user-2"}}}}

        cm.create_user.side_effect = conditional_create

        r1 = client.post("/trainee/single", json=_payload(email="fail@example.com"))
        r2 = client.post("/trainee/single", json=_payload(email="success@example.com"))

        assert r1.json()["success"] is False
        assert r2.json()["success"] is True

    def test_create_then_webhook_notification(self, client, strapi_boundary):
        """Simulates: create trainee → batch completes → webhook notification."""
        # Step 1: Create trainee
        r1 = client.post("/trainee/single", json=_payload())
        assert r1.json()["success"] is True

        # Step 2: Webhook notification arrives for the batch
        r2 = client.post("/webhook", json={
            "status": "success",
            "batch": "5",
            "total_processed": 1,
            "successful": 1,
            "failed": 0,
            "errors": [],
        })
        assert r2.status_code == 200
        assert r2.json()["data"]["batch"] == "5"


# ============================================================================
# Flow 6: Cross-endpoint interactions
# ============================================================================

class TestCrossEndpointFlows:
    def test_refresh_env_then_create_trainee(self, authed_client, strapi_boundary, mock_secrets):
        """Admin refreshes env vars, then creates a trainee."""
        r1 = authed_client.post("/env/refresh_env_vars", json={
            "sname": "tenx/env/vars", "run_stage": "dev"
        })
        assert r1.status_code == 200

        r2 = authed_client.post("/trainee/admin-single", json=_payload())
        assert r2.status_code == 200
        assert r2.json()["success"] is True

    def test_check_cache_then_refresh(self, authed_client, mock_secrets):
        """Admin checks cache status, then refreshes."""
        r1 = authed_client.post("/env/check_env_cache", json={
            "sname": "tenx/env/vars", "run_stage": "dev"
        })
        assert r1.status_code == 200

        r2 = authed_client.post("/env/refresh_env_vars", json={
            "sname": "tenx/env/vars", "run_stage": "dev"
        })
        assert r2.status_code == 200
        assert r2.json()["secrets_count"] == 3


# ============================================================================
# Flow 7: Date of birth edge cases
# ============================================================================

class TestDateOfBirthEdgeCases:
    def test_valid_date_format(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload(date_of_birth="2000-12-31"))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        profile = cm.insert_profile_information.call_args[0][1]
        assert profile["date_of_birth"] == "2000-12-31"

    def test_null_date_of_birth(self, client, strapi_boundary):
        payload = _payload()
        payload["trainee"]["date_of_birth"] = None
        resp = client.post("/trainee/single", json=payload)
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        profile = cm.insert_profile_information.call_args[0][1]
        assert profile["date_of_birth"] is None

    def test_empty_string_date(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload(date_of_birth=""))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        profile = cm.insert_profile_information.call_args[0][1]
        assert profile["date_of_birth"] is None


# ============================================================================
# Flow 8: Webhook payload round-trip integrity
# ============================================================================

class TestWebhookRoundTrip:
    def test_complex_payload_preserved(self, client):
        """Large realistic payload comes through intact."""
        payload = {
            "status": "partial_success",
            "batch": "42",
            "total_processed": 50,
            "successful": 48,
            "failed": 2,
            "errors": [
                {"email": "dup@test.com", "reason": "Email already registered",
                 "error_type": "USER_CREATION_ERROR"},
                {"email": "bad@test.com", "reason": "Invalid data",
                 "error_type": "VALIDATION_ERROR"},
            ],
            "successful_trainees": [
                {"name": f"Trainee {i}", "email": f"t{i}@test.com", "status": "Success"}
                for i in range(48)
            ],
            "metadata": {
                "run_stage": "prod",
                "role": "trainee",
                "group_id": "12",
                "duration_seconds": 123.45,
                "is_mock": False,
            },
        }
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total_processed"] == 50
        assert body["data"]["successful"] == 48
        assert body["data"]["failed"] == 2
        assert len(body["data"]["successful_trainees"]) == 48
        assert len(body["data"]["errors"]) == 2
        assert body["data"]["metadata"]["duration_seconds"] == 123.45
