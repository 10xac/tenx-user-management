"""
Shared fixtures for tenx-user-management tests.
"""
import sys
import os
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

# Ensure project root is on sys.path so `api` and `utils` packages resolve
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Stub heavy external dependencies BEFORE any project imports so that modules
# which perform top-level imports (e.g. review_scripts, utils.secret) don't
# fail in the test environment.
# ---------------------------------------------------------------------------

# review_scripts stubs
_review_scripts = MagicMock()
sys.modules.setdefault("review_scripts", _review_scripts)
sys.modules.setdefault("review_scripts.strapi_graphql", _review_scripts)
sys.modules.setdefault("review_scripts.strapi_methods", _review_scripts)
sys.modules.setdefault("review_scripts.communication_manager", _review_scripts)

# utils.secret stub (used by env_routes and security)
_utils_secret = MagicMock()
_utils_secret.get_auth = MagicMock(return_value="fake-token")
_utils_secret.force_refresh_secrets = MagicMock(return_value={})
_utils_secret.get_cache_metadata = MagicMock(return_value={})
_utils_secret.get_all_secrets = MagicMock(return_value={})
_utils_secret.mask_secret_value = MagicMock(side_effect=lambda v: "****")
_utils_secret.clear_api_key_cache = MagicMock(return_value=True)
sys.modules.setdefault("utils.secret", _utils_secret)
sys.modules.setdefault("utils", MagicMock())

# utils.gdrive stub
sys.modules.setdefault("utils.gdrive", MagicMock())

# pathfig stub
sys.modules.setdefault("pathfig", MagicMock())

# boto3 / botocore — only stub if not installed
try:
    import boto3  # noqa: F401
    import botocore  # noqa: F401
except ImportError:
    _mock_botocore = MagicMock()
    # Provide a real-ish ClientError so except clauses work
    class _FakeClientError(Exception):
        def __init__(self, error_response, operation_name):
            self.response = error_response
            self.operation_name = operation_name
            super().__init__(str(error_response))
    _mock_botocore.exceptions.ClientError = _FakeClientError
    sys.modules.setdefault("boto3", MagicMock())
    sys.modules.setdefault("botocore", _mock_botocore)
    sys.modules.setdefault("botocore.exceptions", _mock_botocore.exceptions)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_trainee_payload():
    """Return a valid TraineeCreate-compatible dict."""
    return {
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


@pytest.fixture
def valid_batch_config_payload():
    """Return a valid BatchConfig-compatible dict."""
    return {
        "run_stage": "dev",
        "batch": "5",
        "role": "trainee",
        "is_mock": False,
        "group_id": "12",
        "delimiter": ",",
        "encoding": "utf-8",
        "chunk_size": 20,
        "login_url": "https://dev-tenx.10academy.org/login",
        "admin_email": "admin@10academy.org",
    }


@pytest.fixture
def mock_strapi():
    """Return a mock StrapiGraphql instance."""
    mock = MagicMock()
    mock.apiroot = "https://dev-cms.10academy.org/graphql"
    return mock


@pytest.fixture
def mock_communication_manager():
    """Return a mock CommunicationManager."""
    mock = MagicMock()
    mock.create_user.return_value = {
        "data": {"register": {"user": {"id": "100"}}}
    }
    mock.insert_all_users.return_value = {
        "data": {"createAllUser": {"data": {"id": "200"}}}
    }
    mock.insert_profile_information.return_value = {
        "data": {"createProfileInformation": {"data": {"id": "300"}}}
    }
    mock.delete_user.return_value = True
    mock.delete_alluser.return_value = True
    mock.delete_profile.return_value = True
    mock.delete_trainee.return_value = True
    return mock


@pytest.fixture
def mock_strapi_methods():
    """Return a mock StrapiMethods instance."""
    mock = MagicMock()
    mock.apiroot = "https://dev-cms.10academy.org"
    mock.token = "fake-token"
    mock.insert_data.return_value = {"id": "400"}
    return mock
