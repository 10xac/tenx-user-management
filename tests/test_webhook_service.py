"""
Unit tests for api.services.webhook_service.WebhookService.
"""
import pytest
import json
import math
from unittest.mock import MagicMock, AsyncMock, patch
import pandas as pd

from api.services.webhook_service import WebhookService
from api.models.trainee import BatchConfig


def _make_config(**overrides):
    defaults = {
        "run_stage": "dev",
        "login_url": "https://dev.10academy.org/login",
        "callback_url": "https://example.com/webhook",
        "webhook_secret": "test-secret",
        "webhook_headers": {"X-Custom": "value"},
        "webhook_retry_count": 2,
        "webhook_retry_delay": 1,
    }
    defaults.update(overrides)
    return BatchConfig(**defaults)


@pytest.fixture
def webhook_service():
    config = _make_config()
    return WebhookService(config)


# ============================================================================
# Init
# ============================================================================

class TestWebhookServiceInit:
    def test_requires_callback_url(self):
        config = _make_config(callback_url=None)
        with pytest.raises(ValueError, match="callback_url is required"):
            WebhookService(config)

    def test_retry_count_clamped(self):
        config = _make_config(webhook_retry_count=100)
        ws = WebhookService(config)
        assert ws.retry_count == 10  # clamped to max 10

    def test_retry_delay_clamped(self):
        config = _make_config(webhook_retry_delay=999)
        ws = WebhookService(config)
        assert ws.retry_delay == 60  # clamped to max 60


# ============================================================================
# _generate_webhook_signature
# ============================================================================

class TestGenerateSignature:
    def test_signature_is_hex(self, webhook_service):
        sig = webhook_service._generate_webhook_signature({"key": "value"})
        assert isinstance(sig, str)
        assert len(sig) == 64  # sha256 hex length

    def test_consistent_signature(self, webhook_service):
        payload = {"a": 1, "b": 2}
        sig1 = webhook_service._generate_webhook_signature(payload)
        sig2 = webhook_service._generate_webhook_signature(payload)
        assert sig1 == sig2

    def test_different_payloads_different_signatures(self, webhook_service):
        sig1 = webhook_service._generate_webhook_signature({"a": 1})
        sig2 = webhook_service._generate_webhook_signature({"a": 2})
        assert sig1 != sig2

    def test_empty_secret_returns_empty(self):
        config = _make_config(webhook_secret=None)
        ws = WebhookService(config)
        ws.webhook_secret = ""
        sig = ws._generate_webhook_signature({"a": 1})
        assert sig == ""


# ============================================================================
# _sanitize_payload
# ============================================================================

class TestSanitizePayload:
    def test_basic_dict(self, webhook_service):
        result = webhook_service._sanitize_payload({"a": 1, "b": "hello"})
        assert result == {"a": 1, "b": "hello"}

    def test_nan_becomes_none(self, webhook_service):
        result = webhook_service._sanitize_payload({"val": float("nan")})
        assert result["val"] is None

    def test_none_stays_none(self, webhook_service):
        result = webhook_service._sanitize_payload({"val": None})
        assert result["val"] is None

    def test_pandas_series(self, webhook_service):
        s = pd.Series({"x": 1, "y": 2})
        result = webhook_service._sanitize_payload({"data": s})
        assert isinstance(result["data"], dict)
        assert result["data"]["x"] == 1

    def test_nested_structure(self, webhook_service):
        payload = {"a": {"b": [1, 2, {"c": "d"}]}}
        result = webhook_service._sanitize_payload(payload)
        assert result["a"]["b"][2]["c"] == "d"

    def test_non_serializable_converted_to_string(self, webhook_service):
        result = webhook_service._sanitize_payload({"obj": object()})
        assert isinstance(result["obj"], str)


# ============================================================================
# _send_webhook_with_retry
# ============================================================================

class TestSendWebhookWithRetry:
    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self, webhook_service):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"

        with patch("api.services.webhook_service.httpx.AsyncClient") as MockClient:
            mock_client_instance = AsyncMock()
            mock_client_instance.post.return_value = mock_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await webhook_service._send_webhook_with_retry(
                {"event": "test"}, {"Content-Type": "application/json"}
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_no_callback_url_returns_false(self, webhook_service):
        webhook_service.callback_url = None
        result = await webhook_service._send_webhook_with_retry({}, {})
        assert result is False


# ============================================================================
# notify_callback
# ============================================================================

class TestNotifyCallback:
    @pytest.mark.asyncio
    async def test_notify_callback_calls_send(self, webhook_service):
        webhook_service._send_webhook_with_retry = AsyncMock(return_value=True)
        await webhook_service.notify_callback({
            "status": "success",
            "total_processed": 10,
            "successful": 10,
            "failed": 0,
            "batch": "5",
        })
        webhook_service._send_webhook_with_retry.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_notify_callback_handles_exception(self, webhook_service):
        webhook_service._send_webhook_with_retry = AsyncMock(side_effect=Exception("fail"))
        # Should not raise
        await webhook_service.notify_callback({"status": "error"})
