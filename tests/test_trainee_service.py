"""
Unit tests for api.services.trainee_service.TraineeService.
All external dependencies (Strapi, CommunicationManager) are mocked.
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from api.models.trainee import TraineeCreate, ConfigInfo, TraineeInfo
from api.services.trainee_service import TraineeService


def _build_trainee_create(**overrides):
    """Helper to build a TraineeCreate with sensible defaults."""
    config_data = {
        "run_stage": "dev",
        "batch": "5",
        "role": "trainee",
        "is_mock": True,
        "group_id": "12",
    }
    trainee_data = {
        "name": "John Doe",
        "email": "john@example.com",
        "password": "pass123",
        "nationality": "Kenya",
        "gender": "Male",
        "status": "Accepted",
    }
    config_data.update(overrides.get("config", {}))
    trainee_data.update(overrides.get("trainee", {}))
    return TraineeCreate(config=config_data, trainee=trainee_data)


@pytest.fixture
def service(mock_strapi, mock_communication_manager, mock_strapi_methods):
    """Create a TraineeService with mocked externals."""
    tc = _build_trainee_create()
    with patch("api.services.trainee_service.StrapiGraphql", return_value=mock_strapi), \
         patch("api.services.trainee_service.StrapiMethods", return_value=mock_strapi_methods), \
         patch("api.services.trainee_service.CommunicationManager", return_value=mock_communication_manager):
        svc = TraineeService(tc)
    return svc


# ============================================================================
# _cleanup_resources
# ============================================================================

class TestCleanupResources:
    def test_cleanup_alluser_step(self, service, mock_communication_manager):
        service.created_resources["user_id"] = "100"
        service._cleanup_resources("alluser")
        mock_communication_manager.delete_user.assert_called_once()

    def test_cleanup_profile_step(self, service, mock_communication_manager):
        service.created_resources["user_id"] = "100"
        service.created_resources["alluser_id"] = "200"
        service._cleanup_resources("profile")
        mock_communication_manager.delete_alluser.assert_called_once()
        mock_communication_manager.delete_user.assert_called_once()

    def test_cleanup_trainee_step(self, service, mock_communication_manager):
        service.created_resources["user_id"] = "100"
        service.created_resources["alluser_id"] = "200"
        service.created_resources["profile_id"] = "300"
        service.created_resources["trainee_id"] = "400"
        service._cleanup_resources("trainee")
        mock_communication_manager.delete_trainee.assert_called_once()
        mock_communication_manager.delete_profile.assert_called_once()
        mock_communication_manager.delete_alluser.assert_called_once()
        mock_communication_manager.delete_user.assert_called_once()

    def test_cleanup_swallows_exceptions(self, service, mock_communication_manager):
        service.created_resources["user_id"] = "100"
        mock_communication_manager.delete_user.side_effect = Exception("boom")
        # Should not raise
        service._cleanup_resources("alluser")


# ============================================================================
# _insert_user_and_alluser
# ============================================================================

class TestInsertUserAndAlluser:
    def test_mock_user_success(self, service, mock_communication_manager):
        user_data = {
            "name": "John Doe",
            "email": "john@example.com",
            "role": "trainee",
            "batch_id": ["5"],
            "groups": ["12"],
            "password": "pass123",
            "is_mock": True,
        }
        result = service._insert_user_and_alluser(user_data)
        assert isinstance(result, tuple)
        user_id, alluser_id = result
        assert user_id == "100"
        assert alluser_id == "200"

    def test_user_creation_error_returns_error_dict(self, service, mock_communication_manager):
        mock_communication_manager.create_user.side_effect = Exception("Strapi down")
        user_data = {
            "name": "John Doe",
            "email": "john@example.com",
            "role": "trainee",
            "batch_id": ["5"],
            "groups": ["12"],
            "password": "pass123",
            "is_mock": True,
        }
        result = service._insert_user_and_alluser(user_data)
        assert isinstance(result, dict)
        assert result["success"] is False
        assert result["error"]["error_type"] == "USER_CREATION_ERROR"

    def test_alluser_creation_error_triggers_cleanup(self, service, mock_communication_manager):
        mock_communication_manager.insert_all_users.side_effect = Exception("fail")
        user_data = {
            "name": "John Doe",
            "email": "john@example.com",
            "role": "trainee",
            "batch_id": ["5"],
            "groups": ["12"],
            "password": "pass123",
            "is_mock": True,
        }
        result = service._insert_user_and_alluser(user_data)
        assert isinstance(result, dict)
        assert result["error"]["error_type"] == "ALLUSER_CREATION_ERROR"


# ============================================================================
# _insert_profile
# ============================================================================

class TestInsertProfile:
    def test_success(self, service, mock_communication_manager):
        profile_data = {"first_name": "John", "last_name": "Doe", "email": "j@e.com", "all_user": "200"}
        result = service._insert_profile(profile_data)
        assert "data" in result
        assert service.created_resources["profile_id"] == "300"

    def test_failure_returns_error(self, service, mock_communication_manager):
        mock_communication_manager.insert_profile_information.side_effect = Exception("fail")
        result = service._insert_profile({"email": "x"})
        assert isinstance(result, dict)
        assert result["error"]["error_type"] == "PROFILE_CREATION_ERROR"


# ============================================================================
# _insert_trainee
# ============================================================================

class TestInsertTrainee:
    def test_success(self, service, mock_strapi_methods):
        trainee_data = {"email": "j@e.com", "trainee_id": "uuid", "Status": "Accepted", "batch": ["5"], "all_user": "200"}
        result = service._insert_trainee(trainee_data)
        assert result["id"] == "400"
        assert service.created_resources["trainee_id"] == "400"

    def test_failure_returns_error(self, service, mock_strapi_methods):
        mock_strapi_methods.insert_data.side_effect = Exception("fail")
        result = service._insert_trainee({"email": "x"})
        assert isinstance(result, dict)
        assert result["error"]["error_type"] == "TRAINEE_CREATION_ERROR"


# ============================================================================
# create_trainee_services (full pipeline)
# ============================================================================

class TestCreateTraineeServices:
    def test_full_success(self, service):
        result = service.create_trainee_services()
        assert result["success"] is True
        assert result["message"] == "Trainee created successfully"
        assert "data" in result
        assert "alluser_id" in result["data"]

    def test_returns_error_on_user_failure(self, service, mock_communication_manager):
        mock_communication_manager.create_user.side_effect = Exception("fail")
        result = service.create_trainee_services()
        assert result["success"] is False

    def test_returns_error_on_profile_failure(self, service, mock_communication_manager):
        mock_communication_manager.insert_profile_information.side_effect = Exception("fail")
        result = service.create_trainee_services()
        assert result["success"] is False

    def test_returns_error_on_trainee_failure(self, service, mock_strapi_methods):
        mock_strapi_methods.insert_data.side_effect = Exception("fail")
        result = service.create_trainee_services()
        assert result["success"] is False
