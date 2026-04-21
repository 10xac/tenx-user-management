"""
E2E tests: Single trainee creation — full pipeline.
Route → Controller → TraineeService → DataProcessor → Strapi CMS (mocked at boundary).
Verifies data transformation, resource creation order, cleanup on failure, and response shape.
"""
import pytest
from unittest.mock import patch, MagicMock
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


def _payload_config(**config_overrides):
    p = _payload()
    p["config"].update(config_overrides)
    return p


# ============================================================================
# Flow 1: Mock user creation — full pipeline success
# ============================================================================

class TestMockTraineeCreationFlow:
    """Complete E2E flow: POST /trainee/single → mock user created in Strapi."""

    def test_full_pipeline_success(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload())
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["message"] == "Trainee created successfully"
        assert body["data"]["alluser_id"] == "alluser-200"
        assert body["data"]["profile"]["data"]["createProfileInformation"]["data"]["id"] == "profile-300"
        assert body["data"]["trainee"]["id"] == "trainee-500"

    def test_data_processor_transforms_name(self, client, strapi_boundary):
        """DataProcessor should title-case and strip the name."""
        resp = client.post("/trainee/single", json=_payload(name="  jane smith  "))
        assert resp.status_code == 200
        # Verify CommunicationManager received processed name
        cm = strapi_boundary["cm"]
        call_args = cm.create_user.call_args
        user_data = call_args[0][1]  # second positional arg
        assert user_data["name"] == "Jane Smith"

    def test_data_processor_lowercases_email(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload(email="JOHN.DOE@Example.COM"))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        user_data = cm.create_user.call_args[0][1]
        assert user_data["email"] == "john.doe@example.com"

    def test_password_passed_through(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload(password="MyCustomPwd123"))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        user_data = cm.create_user.call_args[0][1]
        assert user_data["password"] == "MyCustomPwd123"

    def test_default_password_uses_email(self, client, strapi_boundary):
        """When no password provided, DataProcessor falls back to email."""
        payload = _payload()
        payload["trainee"]["password"] = None
        resp = client.post("/trainee/single", json=payload)
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        user_data = cm.create_user.call_args[0][1]
        assert user_data["password"] == "john.doe@example.com"

    def test_profile_receives_split_name(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload(name="Alice Marie Johnson"))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        profile_data = cm.insert_profile_information.call_args[0][1]
        assert profile_data["first_name"] == "Alice"
        assert profile_data["last_name"] == "Marie Johnson"

    def test_single_name_has_empty_last_name(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload(name="Madonna"))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        profile_data = cm.insert_profile_information.call_args[0][1]
        assert profile_data["first_name"] == "Madonna"
        assert profile_data["last_name"] == ""

    def test_alluser_receives_batch_and_group(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload())
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        alluser_data = cm.insert_all_users.call_args[0][1]
        # trainee_service line 222: batch_id = self.config.batch (string)
        assert alluser_data["batchId"] == "5"
        # _insert_user_and_alluser wraps groups in a list
        assert alluser_data["groups"] == ["12"]

    def test_trainee_record_receives_email(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload())
        assert resp.status_code == 200
        sm = strapi_boundary["sm"]
        trainee_data = sm.insert_data.call_args[0][0]
        assert trainee_data["email"] == "john.doe@example.com"
        assert trainee_data["Status"] == "Accepted"

    def test_resource_creation_order(self, client, strapi_boundary):
        """Verify: user → alluser → profile → trainee."""
        cm = strapi_boundary["cm"]
        sm = strapi_boundary["sm"]
        manager = MagicMock()
        cm.create_user.side_effect = lambda *a, **kw: (
            manager.step1(),
            {"data": {"register": {"user": {"id": "u1"}}}}
        )[-1]
        cm.insert_all_users.side_effect = lambda *a, **kw: (
            manager.step2(),
            {"data": {"createAllUser": {"data": {"id": "a1"}}}}
        )[-1]
        cm.insert_profile_information.side_effect = lambda *a, **kw: (
            manager.step3(),
            {"data": {"createProfileInformation": {"data": {"id": "p1"}}}}
        )[-1]
        sm.insert_data.side_effect = lambda *a, **kw: (
            manager.step4(),
            {"id": "t1", "email": "e", "trainee_id": "tid", "Status": "A"}
        )[-1]

        resp = client.post("/trainee/single", json=_payload())
        assert resp.status_code == 200
        calls = [c[0] for c in manager.method_calls]
        assert calls == ["step1", "step2", "step3", "step4"]


# ============================================================================
# Flow 2: Real user creation (is_mock=False)
# ============================================================================

class TestRealTraineeCreationFlow:
    """POST /trainee/single with is_mock=False uses requests.post to Strapi REST."""

    def test_real_user_creation_pipeline(self, client, strapi_boundary, mock_requests_post):
        payload = _payload_config(is_mock=False)
        resp = client.post("/trainee/single", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        # requests.post should have been called for unconfirmed user
        mock_requests_post.assert_called_once()
        call_kwargs = mock_requests_post.call_args
        assert "john.doe@example.com" in str(call_kwargs)

    def test_real_user_strapi_rest_failure(self, client, strapi_boundary, mock_requests_post):
        mock_requests_post.return_value.status_code = 400
        mock_requests_post.return_value.text = "Email already taken"
        payload = _payload_config(is_mock=False)
        resp = client.post("/trainee/single", json=payload)
        body = resp.json()
        assert body["success"] is False
        assert "USER_CREATION_ERROR" in body["error"]["error_type"]


# ============================================================================
# Flow 3: Cleanup on partial failure
# ============================================================================

class TestCleanupOnFailure:
    """When a step fails, previously created resources should be cleaned up."""

    def test_cleanup_after_alluser_failure(self, client, strapi_boundary):
        cm = strapi_boundary["cm"]
        cm.insert_all_users.side_effect = Exception("alluser insert failed")
        resp = client.post("/trainee/single", json=_payload())
        body = resp.json()
        assert body["success"] is False
        assert "ALLUSER_CREATION_ERROR" in body["error"]["error_type"] or \
               "alluser" in body["error"]["error_message"].lower()
        # Cleanup should delete the created user
        cm.delete_user.assert_called()

    def test_cleanup_after_profile_failure(self, client, strapi_boundary):
        cm = strapi_boundary["cm"]
        cm.insert_profile_information.side_effect = Exception("profile insert failed")
        resp = client.post("/trainee/single", json=_payload())
        body = resp.json()
        assert body["success"] is False
        # Cleanup should delete alluser and user
        cm.delete_alluser.assert_called()
        cm.delete_user.assert_called()

    def test_cleanup_after_trainee_failure(self, client, strapi_boundary):
        sm = strapi_boundary["sm"]
        sm.insert_data.side_effect = Exception("trainee insert failed")
        resp = client.post("/trainee/single", json=_payload())
        body = resp.json()
        assert body["success"] is False
        cm = strapi_boundary["cm"]
        # Should clean up profile, alluser, and user
        cm.delete_profile.assert_called()
        cm.delete_alluser.assert_called()
        cm.delete_user.assert_called()


# ============================================================================
# Flow 4: Optional fields flow through the pipeline
# ============================================================================

class TestOptionalFieldsPipeline:
    def test_nationality_and_gender_in_profile(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload(
            nationality="Ethiopia", gender="Female"
        ))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        profile_data = cm.insert_profile_information.call_args[0][1]
        assert profile_data["nationality"] == "Ethiopia"
        assert profile_data["gender"] == "Female"

    def test_date_of_birth_in_profile(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload(date_of_birth="2000-06-15"))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        profile_data = cm.insert_profile_information.call_args[0][1]
        assert profile_data["date_of_birth"] == "2000-06-15"

    def test_bio_and_city_in_profile(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload(
            bio="Software developer", city_of_residence="Addis Ababa"
        ))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        profile_data = cm.insert_profile_information.call_args[0][1]
        assert profile_data["bio"] == "Software developer"
        assert profile_data["city_of_residence"] == "Addis Ababa"

    def test_other_info_as_dict_in_profile(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload(
            other_info={"scholarship": True, "source": "referral"}
        ))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        profile_data = cm.insert_profile_information.call_args[0][1]
        assert "scholarship" in profile_data["other_info"]

    def test_other_info_as_json_string(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload(
            other_info='{"note": "special case"}'
        ))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        profile_data = cm.insert_profile_information.call_args[0][1]
        assert "note" in profile_data["other_info"]

    def test_vulnerable_in_profile_other_info(self, client, strapi_boundary):
        resp = client.post("/trainee/single", json=_payload(vulnerable="Yes"))
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        profile_data = cm.insert_profile_information.call_args[0][1]
        assert profile_data["other_info"]["vulnerable"] == "Yes"

    def test_empty_optional_fields(self, client, strapi_boundary):
        payload = {
            "config": {"run_stage": "dev", "is_mock": True},
            "trainee": {"name": "Test User", "email": "test@example.com"},
        }
        resp = client.post("/trainee/single", json=payload)
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ============================================================================
# Flow 5: Config variations
# ============================================================================

class TestConfigVariations:
    def test_no_batch_id(self, client, strapi_boundary):
        payload = _payload_config(batch="")
        resp = client.post("/trainee/single", json=payload)
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        alluser_data = cm.insert_all_users.call_args[0][1]
        assert alluser_data["batchId"] == []

    def test_no_group_id(self, client, strapi_boundary):
        payload = _payload_config(group_id="")
        resp = client.post("/trainee/single", json=payload)
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        alluser_data = cm.insert_all_users.call_args[0][1]
        assert alluser_data["groups"] == []

    def test_prod_run_stage(self, client, strapi_boundary):
        payload = _payload_config(run_stage="prod")
        resp = client.post("/trainee/single", json=payload)
        assert resp.status_code == 200

    def test_custom_role(self, client, strapi_boundary):
        payload = _payload_config(role="mentor")
        resp = client.post("/trainee/single", json=payload)
        assert resp.status_code == 200
        cm = strapi_boundary["cm"]
        alluser_data = cm.insert_all_users.call_args[0][1]
        assert alluser_data["role"] == "mentor"
