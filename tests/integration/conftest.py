"""
Integration test fixtures — provides TestClient and helpers for full API testing.
"""
import pytest
import io
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient

from api.main import app
from api.models.trainee import TraineeResponse, BatchProcessingResponse


# ---------------------------------------------------------------------------
# TestClient
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """FastAPI TestClient for synchronous integration tests."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Auth mocks
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_user():
    """Simulated admin user dict returned by verify_admin_access."""
    return {
        "id": "1",
        "email": "admin@10academy.org",
        "username": "admin_admin@10academy.org",
        "role": "Staff",
    }


@pytest.fixture
def non_admin_user():
    """Simulated non-admin user."""
    return {
        "id": "2",
        "email": "trainee@10academy.org",
        "username": "trainee_trainee@10academy.org",
        "role": "trainee",
    }


@pytest.fixture
def auth_error_response():
    """Simulated auth error response (mimics what verify_admin_access returns on failure)."""
    return TraineeResponse.error_response(
        error_type="AUTH_ERROR",
        error_message="Invalid authentication credentials",
        error_location="token_validation",
        error_data={"status_code": 401},
    )


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def make_csv_bytes(rows, header="name,email", encoding="utf-8"):
    """Create CSV file bytes from a list of row strings."""
    lines = [header] + rows
    content = "\n".join(lines)
    return content.encode(encoding)


@pytest.fixture
def valid_csv_bytes():
    """A valid CSV with 3 trainees."""
    return make_csv_bytes([
        "Alice Smith,alice@example.com",
        "Bob Jones,bob@example.com",
        "Carol White,carol@example.com",
    ])


@pytest.fixture
def csv_missing_columns():
    """CSV missing the required 'email' column."""
    return make_csv_bytes(
        ["Alice Smith", "Bob Jones"],
        header="name",
    )


@pytest.fixture
def csv_empty_fields():
    """CSV with empty required fields."""
    return make_csv_bytes([
        "Alice Smith,alice@example.com",
        ",bob@example.com",
        "Carol White,",
    ])


@pytest.fixture
def csv_with_optional_fields():
    """CSV with all optional fields populated."""
    return make_csv_bytes(
        [
            "Alice Smith,alice@example.com,Kenya,Female,1990-01-15,No,Software dev,Nairobi",
        ],
        header="name,email,nationality,gender,date_of_birth,vulnerable,bio,city_of_residence",
    )


# ---------------------------------------------------------------------------
# Service mock helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_trainee_service_success():
    """Patch TraineeService to return a success response."""
    with patch("api.controllers.trainee_controller.TraineeService") as MockSvc:
        MockSvc.return_value.create_trainee_services.return_value = \
            TraineeResponse.success_response(
                message="Trainee created successfully",
                data={
                    "alluser_id": "200",
                    "profile": {"data": {"createProfileInformation": {"data": {"id": "300"}}}},
                    "trainee": {"id": "400"},
                },
            )
        yield MockSvc


@pytest.fixture
def mock_trainee_service_failure():
    """Patch TraineeService to return an error response."""
    with patch("api.controllers.trainee_controller.TraineeService") as MockSvc:
        MockSvc.return_value.create_trainee_services.return_value = \
            TraineeResponse.error_response(
                error_type="USER_CREATION_ERROR",
                error_message="Email already exists",
                error_location="user_creation",
                error_data={"email": "dup@example.com"},
            )
        yield MockSvc


@pytest.fixture
def mock_trainee_service_exception():
    """Patch TraineeService to raise an exception."""
    with patch("api.controllers.trainee_controller.TraineeService") as MockSvc:
        MockSvc.return_value.create_trainee_services.side_effect = \
            Exception("Strapi connection refused")
        yield MockSvc
