"""
Unit tests for api.controllers.trainee_controller.TraineeController.
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi import BackgroundTasks

from api.models.trainee import TraineeCreate, TraineeResponse
from api.controllers.trainee_controller import TraineeController


def _build_trainee_create(**overrides):
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
    }
    config_data.update(overrides.get("config", {}))
    trainee_data.update(overrides.get("trainee", {}))
    return TraineeCreate(config=config_data, trainee=trainee_data)


@pytest.fixture
def controller():
    with patch("api.controllers.trainee_controller.EmailService"):
        return TraineeController()


# ============================================================================
# create_trainee_controller
# ============================================================================

class TestCreateTraineeController:
    @pytest.mark.asyncio
    async def test_success(self, controller):
        mock_result = TraineeResponse.success_response(
            message="Trainee created successfully",
            data={"alluser_id": "200"},
        )
        with patch("api.controllers.trainee_controller.TraineeService") as MockService:
            MockService.return_value.create_trainee_services.return_value = mock_result
            tc = _build_trainee_create()
            response = await controller.create_trainee_controller(tc)
            assert response.success is True

    @pytest.mark.asyncio
    async def test_exception_raises_http(self, controller):
        with patch("api.controllers.trainee_controller.TraineeService") as MockService:
            MockService.return_value.create_trainee_services.side_effect = Exception("boom")
            tc = _build_trainee_create()
            with pytest.raises(Exception):
                await controller.create_trainee_controller(tc)


# ============================================================================
# create_admin_trainee_controller
# ============================================================================

class TestCreateAdminTraineeController:
    @pytest.mark.asyncio
    async def test_success_non_mock(self, controller):
        mock_result = TraineeResponse.success_response(
            message="ok",
            data={"alluser_id": "200"},
        )
        with patch("api.controllers.trainee_controller.TraineeService") as MockService:
            MockService.return_value.create_trainee_services.return_value = mock_result
            tc = _build_trainee_create(config={"is_mock": False, "login_url": "https://dev.10academy.org/login"})
            bg = BackgroundTasks()
            response = await controller.create_admin_trainee_controller(tc, bg)
            assert response.success is True

    @pytest.mark.asyncio
    async def test_success_mock_user(self, controller):
        mock_result = TraineeResponse.success_response(
            message="ok",
            data={"alluser_id": "200"},
        )
        with patch("api.controllers.trainee_controller.TraineeService") as MockService:
            MockService.return_value.create_trainee_services.return_value = mock_result
            tc = _build_trainee_create(config={"is_mock": True})
            bg = BackgroundTasks()
            response = await controller.create_admin_trainee_controller(tc, bg)
            assert response.success is True

    @pytest.mark.asyncio
    async def test_exception_raises_http(self, controller):
        with patch("api.controllers.trainee_controller.TraineeService") as MockService:
            MockService.return_value.create_trainee_services.side_effect = Exception("fail")
            tc = _build_trainee_create()
            bg = BackgroundTasks()
            with pytest.raises(Exception):
                await controller.create_admin_trainee_controller(tc, bg)


# ============================================================================
# _send_welcome_email
# ============================================================================

class TestSendWelcomeEmail:
    @pytest.mark.asyncio
    async def test_send_email_calls_service(self, controller):
        controller.email_service.send_trainee_welcome_email = AsyncMock(return_value=True)
        await controller._send_welcome_email(
            "test@example.com", "testuser", "pass", "https://login.url"
        )
        controller.email_service.send_trainee_welcome_email.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_email_handles_exception(self, controller):
        controller.email_service.send_trainee_welcome_email = AsyncMock(side_effect=Exception("ses down"))
        # Should not raise
        await controller._send_welcome_email(
            "test@example.com", "testuser", "pass", "https://login.url"
        )
