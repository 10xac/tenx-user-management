"""
E2E test fixtures — mocks only at external boundaries (Strapi CMS, AWS SES, HTTP).
The full internal pipeline (route → controller → service → data processor) runs for real.
"""
import pytest
import io
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient

from api.main import app
from api.core.auth import verify_admin_access


# ---------------------------------------------------------------------------
# TestClient
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """FastAPI TestClient for E2E tests."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Admin auth override
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_user():
    """Simulated admin user returned by verify_admin_access."""
    return {
        "id": "1",
        "email": "admin@10academy.org",
        "username": "admin_admin@10academy.org",
        "role": "Staff",
    }


@pytest.fixture
def authed_client(client, admin_user):
    """Client with admin auth dependency overridden."""
    app.dependency_overrides[verify_admin_access] = lambda: admin_user
    yield client
    app.dependency_overrides.pop(verify_admin_access, None)


# ---------------------------------------------------------------------------
# Strapi external boundary mocks
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_strapi_graphql():
    """Mock StrapiGraphql at the boundary — used by TraineeService & BatchService."""
    with patch("api.services.trainee_service.StrapiGraphql") as MockSG:
        instance = MagicMock()
        instance.apiroot = "https://mock-strapi.10academy.org/graphql"
        MockSG.return_value = instance
        yield instance


@pytest.fixture
def mock_strapi_methods():
    """Mock StrapiMethods at the boundary — used by TraineeService & BatchService."""
    with patch("api.services.trainee_service.StrapiMethods") as MockSM:
        instance = MagicMock()
        instance.apiroot = "https://mock-strapi.10academy.org"
        instance.token = "mock-strapi-token"
        # insert_data returns trainee record
        instance.insert_data.return_value = {
            "id": "trainee-500",
            "email": "test@example.com",
            "trainee_id": "uuid-trainee",
            "Status": "Accepted",
        }
        MockSM.return_value = instance
        yield instance


@pytest.fixture
def mock_communication_manager():
    """Mock CommunicationManager at the boundary — handles Strapi CRUD."""
    with patch("api.services.trainee_service.CommunicationManager") as MockCM:
        instance = MagicMock()

        # create_user (mock user) returns GraphQL response
        instance.create_user.return_value = {
            "data": {
                "register": {
                    "user": {"id": "user-100"}
                }
            }
        }

        # insert_all_users returns alluser record
        instance.insert_all_users.return_value = {
            "data": {
                "createAllUser": {
                    "data": {"id": "alluser-200"}
                }
            }
        }

        # insert_profile_information returns profile record
        instance.insert_profile_information.return_value = {
            "data": {
                "createProfileInformation": {
                    "data": {"id": "profile-300"}
                }
            }
        }

        # Cleanup methods
        instance.delete_user.return_value = None
        instance.delete_alluser.return_value = None
        instance.delete_profile.return_value = None
        instance.delete_trainee.return_value = None

        MockCM.return_value = instance
        yield instance


@pytest.fixture
def mock_requests_post():
    """Mock requests.post for create_unconfirmed_user (real user flow)."""
    with patch("api.services.trainee_service.requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "user": {"id": "user-real-100"},
            "jwt": "mock-jwt-token",
        }
        mock_post.return_value = mock_response
        yield mock_post


@pytest.fixture
def strapi_boundary(mock_strapi_graphql, mock_strapi_methods, mock_communication_manager):
    """Bundle all Strapi boundary mocks together for convenience."""
    return {
        "sg": mock_strapi_graphql,
        "sm": mock_strapi_methods,
        "cm": mock_communication_manager,
    }


# ---------------------------------------------------------------------------
# Batch-level Strapi boundary mocks (BatchService creates its own instances)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_batch_strapi():
    """Mock Strapi classes at both batch_service AND trainee_service import levels.
    BatchService creates TraineeService internally, which imports its own copies."""
    with patch("api.services.batch_service.StrapiGraphql") as MockSG_B, \
         patch("api.services.batch_service.StrapiMethods") as MockSM_B, \
         patch("api.services.batch_service.CommunicationManager") as MockCM_B, \
         patch("api.services.trainee_service.StrapiGraphql") as MockSG_T, \
         patch("api.services.trainee_service.StrapiMethods") as MockSM_T, \
         patch("api.services.trainee_service.CommunicationManager") as MockCM_T:

        # Batch-level Strapi mocks
        sg_inst = MagicMock()
        sg_inst.apiroot = "https://mock-strapi.10academy.org/graphql"
        MockSG_B.return_value = sg_inst
        MockSG_T.return_value = sg_inst

        sm_inst = MagicMock()
        sm_inst.apiroot = "https://mock-strapi.10academy.org"
        sm_inst.token = "mock-strapi-token"
        sm_inst.insert_data.return_value = {
            "id": "trainee-batch-500",
            "email": "batch@example.com",
            "trainee_id": "uuid-batch-trainee",
            "Status": "Accepted",
        }
        MockSM_B.return_value = sm_inst
        MockSM_T.return_value = sm_inst

        cm_inst = MagicMock()
        cm_inst.create_user.return_value = {
            "data": {"register": {"user": {"id": "user-batch-100"}}}
        }
        cm_inst.insert_all_users.return_value = {
            "data": {"createAllUser": {"data": {"id": "alluser-batch-200"}}}
        }
        cm_inst.insert_profile_information.return_value = {
            "data": {"createProfileInformation": {"data": {"id": "profile-batch-300"}}}
        }
        cm_inst.delete_user.return_value = None
        cm_inst.delete_alluser.return_value = None
        cm_inst.delete_profile.return_value = None
        cm_inst.delete_trainee.return_value = None
        MockCM_B.return_value = cm_inst
        MockCM_T.return_value = cm_inst

        yield {"sg": sg_inst, "sm": sm_inst, "cm": cm_inst}


# ---------------------------------------------------------------------------
# AWS SES boundary mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_ses():
    """Mock boto3 SES client at the boundary."""
    with patch("api.services.email_service.boto3") as mock_boto:
        ses_client = MagicMock()
        ses_client.send_email.return_value = {"MessageId": "mock-msg-id-001"}
        ses_client.send_raw_email.return_value = {"MessageId": "mock-raw-msg-id-001"}
        mock_boto.client.return_value = ses_client
        yield ses_client


# ---------------------------------------------------------------------------
# Webhook HTTP boundary mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_webhook_http():
    """Mock httpx.AsyncClient for webhook outbound calls."""
    with patch("api.services.webhook_service.httpx.AsyncClient") as MockClient:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"

        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        MockClient.return_value = mock_client_instance
        yield mock_client_instance


# ---------------------------------------------------------------------------
# Secrets boundary mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_secrets():
    """Mock AWS Secrets Manager utilities at the boundary."""
    secrets_data = {
        "STRAPI_API_KEY": "sk-mock-strapi-key",
        "AWS_SES_KEY": "mock-ses-key",
        "DB_PASSWORD": "mock-db-pass",
    }
    with patch("api.routes.env_routes.force_refresh_secrets", return_value=secrets_data), \
         patch("api.routes.env_routes.clear_api_key_cache", return_value=True), \
         patch("api.routes.env_routes.get_cache_metadata", return_value={
             "memory_cache_exists": True,
             "cache_age_seconds": 120,
             "is_fresh": True,
             "num_keys": 3,
         }), \
         patch("api.routes.env_routes.get_all_secrets", return_value=secrets_data), \
         patch("api.routes.env_routes.mask_secret_value", side_effect=lambda v: v[:2] + "****"):
        yield secrets_data


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def make_csv(rows, header="name,email"):
    """Build CSV bytes from header + row strings."""
    return "\n".join([header] + rows).encode("utf-8")
