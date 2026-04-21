"""
Unit tests for api.services.email_service.EmailService.
"""
import pytest
from unittest.mock import MagicMock, patch


from api.services.email_service import EmailService


@pytest.fixture
def email_service():
    mock_client = MagicMock()
    svc = EmailService.__new__(EmailService)
    svc.client = mock_client
    svc.source_email = "noreply@10academy.org"
    svc.logger = MagicMock()
    yield svc


# ============================================================================
# _send_email
# ============================================================================

class TestSendEmail:
    def test_success(self, email_service):
        email_service.client.send_email.return_value = {"MessageId": "abc123"}
        result = email_service._send_email("to@x.com", "Subject", "Body")
        assert result is True
        email_service.client.send_email.assert_called_once()

    def test_no_source_email(self):
        svc = EmailService.__new__(EmailService)
        svc.source_email = None
        svc.logger = MagicMock()
        svc.client = MagicMock()
        result = svc._send_email("to@x.com", "Sub", "Body")
        assert result is False

    def test_client_error(self, email_service):
        from botocore.exceptions import ClientError
        email_service.client.send_email.side_effect = ClientError(
            {"Error": {"Code": "400", "Message": "bad"}}, "SendEmail"
        )
        result = email_service._send_email("to@x.com", "Sub", "Body")
        assert result is False

    def test_unexpected_error(self, email_service):
        email_service.client.send_email.side_effect = RuntimeError("boom")
        result = email_service._send_email("to@x.com", "Sub", "Body")
        assert result is False


# ============================================================================
# _format_error_details
# ============================================================================

class TestFormatErrorDetails:
    def test_empty_list(self, email_service):
        assert email_service._format_error_details([]) == ""

    def test_none(self, email_service):
        assert email_service._format_error_details(None) == ""

    def test_with_errors(self, email_service):
        errors = [
            {"email": "a@b.com", "reason": "duplicate"},
            {"email": "c@d.com", "reason": "invalid"},
        ]
        result = email_service._format_error_details(errors)
        assert "a@b.com" in result
        assert "duplicate" in result
        assert "c@d.com" in result


# ============================================================================
# _format_successful_details
# ============================================================================

class TestFormatSuccessfulDetails:
    def test_empty_list(self, email_service):
        assert email_service._format_successful_details([]) == ""

    def test_none(self, email_service):
        assert email_service._format_successful_details(None) == ""

    def test_with_trainees(self, email_service):
        trainees = [
            {"name": "John", "email": "john@x.com", "credentials": {"username": "john", "password": "pass"}},
            {"name": "Jane", "email": "jane@x.com"},
        ]
        result = email_service._format_successful_details(trainees)
        assert "John" in result
        assert "john@x.com" in result
        assert "Username: john" in result
        assert "Jane" in result
