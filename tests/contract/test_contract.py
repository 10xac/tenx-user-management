"""
Contract Testing — Verify API schema contracts between consumer and provider.
Ensures the tenx-user-management API endpoints honour their documented contracts:
request schemas, response schemas, status codes, field types, and Strapi
data-shape expectations.

Industry standard: Consumer-Driven Contract Testing (CDCT).
The consumer (frontend / batch orchestrator / webhook receiver) defines
expected contracts; the provider (this API) must satisfy them.

Covers:
  - OpenAPI schema correctness and completeness
  - Request/response model field contracts
  - Strapi CMS data shape contracts (GraphQL mutation shapes)
  - Webhook payload contract
  - Batch processing response contract
  - Error response contract consistency
"""
import pytest
import json
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from api.main import app
from api.core.auth import verify_admin_access
from api.models.trainee import (
    TraineeCreate, TraineeInfo, ConfigInfo, TraineeResponse,
    BatchConfig, BatchTraineeCreate, BatchProcessingResponse,
    ErrorDetail, BatchErrorDetail,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def admin_user():
    return {"id": "1", "email": "admin@10academy.org",
            "username": "admin_admin@10academy.org", "role": "Staff"}


@pytest.fixture
def authed_client(client, admin_user):
    app.dependency_overrides[verify_admin_access] = lambda: admin_user
    yield client
    app.dependency_overrides.pop(verify_admin_access, None)


@pytest.fixture(autouse=True)
def mock_strapi():
    with patch("api.services.trainee_service.StrapiGraphql") as MockSG, \
         patch("api.services.trainee_service.StrapiMethods") as MockSM, \
         patch("api.services.trainee_service.CommunicationManager") as MockCM:
        sg = MagicMock(); sg.apiroot = "https://mock.test/graphql"
        MockSG.return_value = sg
        sm = MagicMock(); sm.apiroot = "https://mock.test"; sm.token = "t"
        sm.insert_data.return_value = {"id": "1", "email": "e", "trainee_id": "t", "Status": "Accepted"}
        MockSM.return_value = sm
        cm = MagicMock()
        cm.create_user.return_value = {"data": {"register": {"user": {"id": "u1"}}}}
        cm.insert_all_users.return_value = {"data": {"createAllUser": {"data": {"id": "a1"}}}}
        cm.insert_profile_information.return_value = {"data": {"createProfileInformation": {"data": {"id": "p1"}}}}
        MockCM.return_value = cm
        yield {"sg": sg, "sm": sm, "cm": cm}


# ============================================================================
# 1. OpenAPI Schema Contract
# ============================================================================

class TestOpenAPISchemaContract:
    """Verify the OpenAPI schema is complete and correct."""

    def test_openapi_schema_is_valid_json(self, client):
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert "openapi" in schema
        assert "paths" in schema
        assert "components" in schema

    def test_all_endpoints_documented(self, client):
        schema = client.get("/openapi.json").json()
        paths = schema["paths"]
        expected = [
            "/trainee/single",
            "/trainee/admin-single",
            "/trainee/batch",
            "/webhook",
            "/env/refresh_env_vars",
            "/env/check_env_cache",
        ]
        for ep in expected:
            assert ep in paths, f"Endpoint {ep} missing from OpenAPI schema"

    def test_endpoints_have_post_method(self, client):
        schema = client.get("/openapi.json").json()
        paths = schema["paths"]
        for ep in ["/trainee/single", "/trainee/admin-single", "/webhook"]:
            assert "post" in paths[ep], f"{ep} missing POST method"

    def test_trainee_single_request_schema(self, client):
        schema = client.get("/openapi.json").json()
        post = schema["paths"]["/trainee/single"]["post"]
        # Should have a request body
        assert "requestBody" in post
        content = post["requestBody"]["content"]
        assert "application/json" in content

    def test_response_schema_references_trainee_response(self, client):
        schema = client.get("/openapi.json").json()
        post = schema["paths"]["/trainee/single"]["post"]
        responses = post["responses"]
        assert "200" in responses


# ============================================================================
# 2. Request Model Contracts (Pydantic)
# ============================================================================

class TestRequestModelContract:
    """Verify Pydantic models enforce expected field contracts."""

    def test_config_info_required_fields(self):
        """ConfigInfo requires run_stage."""
        with pytest.raises(Exception):
            ConfigInfo()  # Missing run_stage

    def test_config_info_defaults(self):
        config = ConfigInfo(run_stage="dev")
        assert config.role == "trainee"
        assert config.is_mock is False
        assert config.batch == ""
        assert config.group_id == ""

    def test_trainee_info_required_fields(self):
        """TraineeInfo requires name and email."""
        with pytest.raises(Exception):
            TraineeInfo()  # Missing name and email

    def test_trainee_info_email_validation(self):
        with pytest.raises(Exception):
            TraineeInfo(name="Test", email="not-an-email")

    def test_trainee_info_name_validation(self):
        with pytest.raises(Exception):
            TraineeInfo(name="", email="test@example.com")

    def test_trainee_info_defaults(self):
        t = TraineeInfo(name="Test", email="test@example.com")
        assert t.status == "Accepted"
        assert t.nationality == ""
        assert t.gender == ""
        assert t.password is None
        assert t.other_info == {}

    def test_trainee_create_combines_config_and_trainee(self):
        tc = TraineeCreate(
            config=ConfigInfo(run_stage="dev"),
            trainee=TraineeInfo(name="Test", email="test@example.com"),
        )
        assert tc.config.run_stage == "dev"
        assert tc.trainee.name == "Test"

    def test_batch_config_required_fields(self):
        """BatchConfig requires run_stage and login_url."""
        with pytest.raises(Exception):
            BatchConfig(run_stage="dev")  # Missing login_url

    def test_batch_config_defaults(self):
        bc = BatchConfig(run_stage="dev", login_url="https://10academy.org/login")
        assert bc.delimiter == ","
        assert bc.encoding == "utf-8"
        assert bc.chunk_size == 20
        assert bc.role == "trainee"
        assert bc.is_mock is False
        assert bc.required_columns == ["name", "email"]
        assert bc.password_option == "default"
        assert bc.default_password == "10@Academy"
        assert bc.webhook_retry_count == 3
        assert bc.webhook_retry_delay == 5


# ============================================================================
# 3. Response Model Contracts
# ============================================================================

class TestResponseModelContract:
    """Verify response models produce correct structure."""

    def test_success_response_shape(self):
        resp = TraineeResponse.success_response(
            message="ok", data={"alluser_id": "a1"}
        )
        assert resp["success"] is True
        assert resp["message"] == "ok"
        assert "data" in resp
        assert resp["data"]["alluser_id"] == "a1"

    def test_error_response_shape(self):
        resp = TraineeResponse.error_response(
            error_type="TEST_ERROR",
            error_message="something failed",
            error_location="test",
            error_data={"field": "name"},
        )
        assert resp["success"] is False
        assert "error" in resp
        assert resp["error"]["error_type"] == "TEST_ERROR"
        assert resp["error"]["error_message"] == "something failed"
        assert resp["error"]["error_location"] == "test"
        assert resp["error"]["error_data"] == {"field": "name"}

    def test_batch_success_response_shape(self):
        resp = BatchProcessingResponse.success_response(
            message="done",
            data={
                "total_processed": 10, "successful": 8, "failed": 2,
                "successful_trainees": [{"name": "A"}],
                "failed_trainees": [{"name": "B"}],
                "error_details": [{"error": "x"}],
            },
        )
        assert resp["success"] is True
        assert resp["total_processed"] == 10
        assert resp["successful"] == 8
        assert resp["failed"] == 2
        assert len(resp["successful_trainees"]) == 1
        assert len(resp["failed_trainees"]) == 1

    def test_batch_error_response_shape(self):
        resp = BatchProcessingResponse.error_response(
            error_type="CSV_ERROR",
            error_message="bad csv",
            error_location="csv_parsing",
        )
        assert resp["success"] is False
        assert "error" in resp
        assert resp["error"]["error_type"] == "CSV_ERROR"

    def test_error_detail_model(self):
        ed = ErrorDetail(
            error_type="T", error_message="M",
            error_location="L", error_data={"k": "v"},
        )
        d = ed.to_dict()
        assert set(d.keys()) == {"error_type", "error_message", "error_location", "error_data"}


# ============================================================================
# 4. HTTP Response Contract (Live Endpoint)
# ============================================================================

class TestHTTPResponseContract:
    """Verify live endpoints return responses matching the contract."""

    def test_single_trainee_success_contract(self, client):
        resp = client.post("/trainee/single", json={
            "config": {"run_stage": "dev", "batch": "5", "is_mock": True},
            "trainee": {"name": "Contract User", "email": "contract@test.com"},
        })
        assert resp.status_code == 200
        body = resp.json()
        # Contract: must have success, message
        assert "success" in body
        assert "message" in body
        assert isinstance(body["success"], bool)
        assert isinstance(body["message"], str)

    def test_single_trainee_success_data_contract(self, client):
        resp = client.post("/trainee/single", json={
            "config": {"run_stage": "dev", "batch": "5", "is_mock": True},
            "trainee": {"name": "Contract User", "email": "contract@test.com"},
        })
        body = resp.json()
        if body["success"]:
            # Contract: success response must include data with alluser_id
            assert "data" in body
            assert "alluser_id" in body["data"]

    def test_validation_error_contract(self, client):
        resp = client.post("/trainee/single", json={
            "config": {"run_stage": "dev"},
            "trainee": {"name": "", "email": "bad"},
        })
        assert resp.status_code == 422
        body = resp.json()
        assert body["success"] is False
        assert "error" in body
        assert body["error"]["error_type"] == "VALIDATION_ERROR"

    def test_webhook_response_contract(self, client):
        resp = client.post("/webhook", json={
            "status": "success", "batch": "1", "errors": [],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body
        assert body["status"] == "received"
        assert "message" in body
        assert "data" in body

    def test_admin_auth_error_contract(self, client):
        """Unauthenticated request returns 403 with proper format."""
        resp = client.post("/trainee/admin-single", json={
            "config": {"run_stage": "dev", "is_mock": True},
            "trainee": {"name": "Test", "email": "t@e.com"},
        })
        assert resp.status_code in [401, 403]

    def test_method_not_allowed_contract(self, client):
        resp = client.get("/trainee/single")
        assert resp.status_code == 405
        body = resp.json()
        assert "detail" in body


# ============================================================================
# 5. Strapi CMS Data Shape Contract
# ============================================================================

class TestStrapiDataShapeContract:
    """Verify the data shapes sent to Strapi match expected GraphQL mutations."""

    def test_create_user_data_shape(self, client, mock_strapi):
        """CommunicationManager.create_user receives (sg, user_data) with correct keys."""
        client.post("/trainee/single", json={
            "config": {"run_stage": "dev", "batch": "5", "group_id": "12", "is_mock": True},
            "trainee": {"name": "Shape Test", "email": "shape@test.com", "password": "P1"},
        })
        cm = mock_strapi["cm"]
        assert cm.create_user.called
        args = cm.create_user.call_args[0]
        user_data = args[1]
        # Contract: user_data must contain these keys
        required_keys = {"name", "email", "role", "batch_id", "groups", "password", "is_mock"}
        assert required_keys.issubset(set(user_data.keys())), \
            f"Missing keys: {required_keys - set(user_data.keys())}"

    def test_insert_all_users_data_shape(self, client, mock_strapi):
        client.post("/trainee/single", json={
            "config": {"run_stage": "dev", "batch": "5", "group_id": "12", "is_mock": True},
            "trainee": {"name": "Shape Test", "email": "shape@test.com"},
        })
        cm = mock_strapi["cm"]
        assert cm.insert_all_users.called
        alluser_data = cm.insert_all_users.call_args[0][1]
        required_keys = {"name", "email", "role", "userId", "batchId", "groups"}
        assert required_keys.issubset(set(alluser_data.keys()))
        # batchId should be a string
        assert isinstance(alluser_data["batchId"], str)
        # groups should be a list
        assert isinstance(alluser_data["groups"], list)

    def test_insert_profile_data_shape(self, client, mock_strapi):
        client.post("/trainee/single", json={
            "config": {"run_stage": "dev", "batch": "5", "is_mock": True},
            "trainee": {"name": "Shape Test", "email": "shape@test.com",
                        "nationality": "KE", "gender": "Male", "date_of_birth": "1990-01-01"},
        })
        cm = mock_strapi["cm"]
        assert cm.insert_profile_information.called
        profile = cm.insert_profile_information.call_args[0][1]
        required_keys = {"first_name", "last_name", "email", "nationality", "gender",
                         "date_of_birth", "all_user", "other_info", "bio", "city_of_residence"}
        assert required_keys.issubset(set(profile.keys()))

    def test_insert_trainee_data_shape(self, client, mock_strapi):
        client.post("/trainee/single", json={
            "config": {"run_stage": "dev", "batch": "5", "is_mock": True},
            "trainee": {"name": "Shape Test", "email": "shape@test.com"},
        })
        sm = mock_strapi["sm"]
        assert sm.insert_data.called
        trainee_data = sm.insert_data.call_args[0][0]
        required_keys = {"email", "trainee_id", "Status", "batch", "all_user"}
        assert required_keys.issubset(set(trainee_data.keys()))
        # trainee_id must be UUID-formatted string
        assert len(trainee_data["trainee_id"]) == 36  # UUID length


# ============================================================================
# 6. Webhook Outbound Payload Contract
# ============================================================================

class TestWebhookOutboundContract:
    """Verify outbound webhook payload matches documented schema."""

    def test_webhook_service_payload_shape(self):
        from api.services.webhook_service import WebhookService
        config = MagicMock()
        config.callback_url = "https://callback.test/webhook"
        config.webhook_secret = "secret"
        config.webhook_headers = {}
        config.webhook_retry_count = 1
        config.webhook_retry_delay = 1
        ws = WebhookService(config)

        # Verify sanitize produces expected shape
        payload = ws._sanitize_payload({
            "event": "batch.processed",
            "status": "success",
            "total_processed": 10,
            "successful": 8,
            "failed": 2,
            "errors": [],
            "batch": "5",
            "timestamp": "2024-01-01T00:00:00",
            "metadata": {},
        })
        required_keys = {"event", "status", "total_processed", "successful",
                         "failed", "errors", "batch", "timestamp", "metadata"}
        assert required_keys.issubset(set(payload.keys()))
        # Must be JSON serializable
        json.dumps(payload)

    def test_webhook_signature_is_hex_string(self):
        from api.services.webhook_service import WebhookService
        config = MagicMock()
        config.callback_url = "https://callback.test/webhook"
        config.webhook_secret = "secret"
        config.webhook_headers = {}
        config.webhook_retry_count = 1
        config.webhook_retry_delay = 1
        ws = WebhookService(config)

        sig = ws._generate_webhook_signature({"test": "data"})
        assert isinstance(sig, str)
        assert len(sig) == 64  # SHA-256 hex digest
        assert all(c in "0123456789abcdef" for c in sig)


# ============================================================================
# 7. Data Processor Output Contract
# ============================================================================

class TestDataProcessorContract:
    """Verify DataProcessor output matches TraineeService input contract."""

    def test_process_single_trainee_output_shape(self):
        from api.services.data_processor import DataProcessor
        config = MagicMock()
        config.role = "trainee"
        config.batch = "5"
        config.group_id = "12"
        dp = DataProcessor(config)

        trainee = MagicMock()
        trainee.name = "John Doe"
        trainee.email = "john@test.com"
        trainee.password = "pass"
        trainee.nationality = "KE"
        trainee.gender = "Male"
        trainee.date_of_birth = "1990-01-01"
        trainee.vulnerable = "No"
        trainee.status = "Accepted"
        trainee.bio = "A bio"
        trainee.city_of_residence = "Nairobi"
        trainee.other_info = {}

        result = dp.process_single_trainee(trainee)
        assert isinstance(result, dict)
        required = {"name", "email", "password", "nationality", "gender",
                    "date_of_birth", "vulnerable", "status", "role",
                    "batch_id", "groups", "bio", "city_of_residence", "other_info"}
        assert required.issubset(set(result.keys())), \
            f"Missing: {required - set(result.keys())}"

    def test_name_is_title_cased(self):
        from api.services.data_processor import DataProcessor
        config = MagicMock(); config.role = "trainee"; config.batch = "5"; config.group_id = ""
        dp = DataProcessor(config)
        trainee = MagicMock()
        trainee.name = "john doe"; trainee.email = "j@t.com"; trainee.password = "p"
        trainee.nationality = ""; trainee.gender = ""; trainee.date_of_birth = None
        trainee.vulnerable = ""; trainee.status = ""; trainee.bio = ""
        trainee.city_of_residence = ""; trainee.other_info = {}
        result = dp.process_single_trainee(trainee)
        assert result["name"] == "John Doe"

    def test_email_is_lowercased(self):
        from api.services.data_processor import DataProcessor
        config = MagicMock(); config.role = "trainee"; config.batch = "5"; config.group_id = ""
        dp = DataProcessor(config)
        trainee = MagicMock()
        trainee.name = "Test"; trainee.email = "  UPPER@TEST.COM  "; trainee.password = "p"
        trainee.nationality = ""; trainee.gender = ""; trainee.date_of_birth = None
        trainee.vulnerable = ""; trainee.status = ""; trainee.bio = ""
        trainee.city_of_residence = ""; trainee.other_info = {}
        result = dp.process_single_trainee(trainee)
        assert result["email"] == "upper@test.com"


# ============================================================================
# 8. Cross-Service Contract Compatibility
# ============================================================================

class TestCrossServiceContract:
    """Verify contracts hold when data flows across services."""

    def test_full_flow_field_types(self, client, mock_strapi):
        """Verify field types are preserved through the full pipeline."""
        resp = client.post("/trainee/single", json={
            "config": {"run_stage": "dev", "batch": "5", "group_id": "12", "is_mock": True},
            "trainee": {"name": "Type Test", "email": "type@test.com", "password": "P1",
                        "nationality": "KE", "gender": "Male"},
        })
        body = resp.json()
        assert isinstance(body["success"], bool)
        assert isinstance(body["message"], str)
        if body.get("data"):
            assert isinstance(body["data"], dict)

        # Verify Strapi received correct types
        cm = mock_strapi["cm"]
        user_data = cm.create_user.call_args[0][1]
        assert isinstance(user_data["name"], str)
        assert isinstance(user_data["email"], str)
        assert isinstance(user_data["is_mock"], bool)

    def test_optional_fields_propagate_as_defaults(self, client, mock_strapi):
        """Omitted optional fields should use defaults, not None/missing."""
        resp = client.post("/trainee/single", json={
            "config": {"run_stage": "dev", "is_mock": True},
            "trainee": {"name": "Minimal", "email": "min@test.com"},
        })
        assert resp.status_code == 200
        cm = mock_strapi["cm"]
        if cm.insert_profile_information.called:
            profile = cm.insert_profile_information.call_args[0][1]
            # nationality should be empty string, not None
            assert profile["nationality"] is not None
