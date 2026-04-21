"""
Unit tests for api.utils.password_generator and api.core modules.
"""
import pytest
import string
import json
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from api.utils.password_generator import generate_secure_password
from api.core.config import Settings, get_settings, get_strapi_params
from api.core.logging_config import JSONFormatter, setup_logging
from api.core.error_handlers import (
    validation_exception_handler,
    pydantic_validation_exception_handler,
)


# ============================================================================
# Password Generator
# ============================================================================

class TestGenerateSecurePassword:
    def test_default_length(self):
        pw = generate_secure_password()
        assert len(pw) == 12

    def test_custom_length(self):
        pw = generate_secure_password(length=20)
        assert len(pw) == 20

    def test_contains_uppercase(self):
        pw = generate_secure_password(length=50)
        assert any(c in string.ascii_uppercase for c in pw)

    def test_contains_lowercase(self):
        pw = generate_secure_password(length=50)
        assert any(c in string.ascii_lowercase for c in pw)

    def test_contains_digit(self):
        pw = generate_secure_password(length=50)
        assert any(c in string.digits for c in pw)

    def test_contains_special(self):
        special = "!@#$%^&*()_+-=[]{}|;:,.<>?"
        pw = generate_secure_password(length=50)
        assert any(c in special for c in pw)

    def test_minimum_length(self):
        pw = generate_secure_password(length=4)
        assert len(pw) == 4

    def test_randomness(self):
        passwords = {generate_secure_password() for _ in range(20)}
        assert len(passwords) > 1  # extremely unlikely all 20 are the same


# ============================================================================
# Settings / Config
# ============================================================================

class TestSettings:
    def test_defaults(self):
        s = Settings()
        assert s.APP_NAME == "10 Academy Trainee API"
        assert s.RUN_STAGE == "dev"
        assert s.DEFAULT_ROLE == "trainee"
        assert s.MAX_FILE_SIZE == 10 * 1024 * 1024
        assert "text/csv" in s.ALLOWED_FILE_TYPES
        assert "name" in s.REQUIRED_COLUMNS
        assert "email" in s.REQUIRED_COLUMNS

    def test_get_settings_returns_settings(self):
        s = get_settings()
        assert isinstance(s, Settings)


class TestGetStrapiParams:
    @pytest.mark.parametrize(
        "stage, expected_root, expected_key",
        [
            ("dev", "dev-cms", "TENX_DEV_STRAPI_TOKEN"),
            ("devapply", "dev-apply-cms", "APPLY_DEV_STRAPI_TOKEN"),
            ("apply", "apply-cms", "APPLY_PROD_STRAPI_TOKEN"),
            ("devu2j", "dev-u2jcms", "U2J_DEV_STRAPI_TOKEN"),
            ("u2j", "u2jcms", "U2J_PROD_STRAPI_TOKEN"),
            ("kaim", "kaimcms", "KAIM_PROD_STRAPI_TOKEN"),
            ("prod", "cms", "TENX_PROD_STRAPI_TOKEN"),
            ("simulation", "simulation-cms", "TENX_SIMULATION_STRAPI_TOKEN"),
            ("tenacious", "tenaciouscms", "TENACIOUS_PROD_STRAPI_TOKEN"),
            ("demo", "democms", "DEMO_PROD_STRAPI_TOKEN"),
            ("shared", "sharedcms", "SHARED_PROD_STRAPI_TOKEN"),
            ("kepler", "keplercms", "KEPLER_PROD_STRAPI_TOKEN"),
            ("unknown_stage", "dev-cms", "TENX_DEV_STRAPI_TOKEN"),
        ],
    )
    def test_stage_mapping(self, stage, expected_root, expected_key):
        root, ssmkey = get_strapi_params(stage)
        assert root == expected_root
        assert ssmkey == expected_key


# ============================================================================
# JSONFormatter / Logging
# ============================================================================

class TestJSONFormatter:
    def test_format_produces_valid_json(self):
        import logging

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["message"] == "hello"
        assert data["level"] == "INFO"
        assert "timestamp" in data

    def test_extra_data_included(self):
        import logging

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="msg",
            args=(),
            exc_info=None,
        )
        record.extra_data = {"custom_key": "custom_value"}
        output = formatter.format(record)
        data = json.loads(output)
        assert data["custom_key"] == "custom_value"


# ============================================================================
# Error Handlers
# ============================================================================

class TestErrorHandlers:
    @pytest.mark.asyncio
    async def test_validation_exception_handler(self):
        mock_request = MagicMock(spec=Request)
        exc = RequestValidationError(
            errors=[
                {
                    "loc": ("body", "trainee", "email"),
                    "msg": "Invalid email",
                    "type": "value_error",
                    "input": "bad",
                }
            ]
        )
        response = await validation_exception_handler(mock_request, exc)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        body = json.loads(response.body)
        assert body["success"] is False
        assert body["error"]["error_type"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_pydantic_validation_exception_handler(self):
        mock_request = MagicMock(spec=Request)
        # Create a real ValidationError by trying to instantiate with bad data
        from api.models.trainee import TraineeInfo

        try:
            TraineeInfo(name="", email="bad")
        except Exception as exc:
            response = await pydantic_validation_exception_handler(mock_request, exc)
            assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
