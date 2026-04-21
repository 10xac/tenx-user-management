"""
E2E tests: Webhook notification flow — full pipeline.
Tests the webhook endpoint receiving batch results, and the WebhookService sending
outbound notifications with HMAC signatures, retries, and payload sanitization.
"""
import pytest
import json
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

from api.services.webhook_service import WebhookService
from api.models.trainee import BatchConfig


# ============================================================================
# Flow 1: Inbound webhook — receiving batch results
# ============================================================================

class TestInboundWebhookFlow:
    """POST /webhook — simulate batch completion notifications arriving."""

    def test_successful_batch_notification(self, client):
        payload = {
            "status": "success",
            "batch": "5",
            "total_processed": 10,
            "successful": 10,
            "failed": 0,
            "errors": [],
            "timestamp": "2025-01-01T12:00:00",
        }
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "received"
        assert body["data"]["status"] == "success"
        assert body["data"]["total_processed"] == 10

    def test_partial_success_notification(self, client):
        payload = {
            "status": "partial_success",
            "batch": "7",
            "total_processed": 5,
            "successful": 3,
            "failed": 2,
            "errors": [
                {"email": "fail1@test.com", "reason": "duplicate"},
                {"email": "fail2@test.com", "reason": "invalid email"},
            ],
        }
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["status"] == "partial_success"
        assert len(body["data"]["errors"]) == 2

    def test_failed_batch_notification(self, client):
        payload = {
            "status": "failed",
            "batch": "9",
            "total_processed": 0,
            "successful": 0,
            "failed": 3,
            "errors": [
                {"email": "a@b.com", "reason": "Strapi timeout"},
                {"email": "c@d.com", "reason": "Strapi timeout"},
                {"email": "e@f.com", "reason": "Strapi timeout"},
            ],
        }
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["status"] == "failed"
        assert body["data"]["failed"] == 3

    def test_webhook_preserves_metadata(self, client):
        payload = {
            "status": "success",
            "batch": "1",
            "errors": [],
            "metadata": {
                "run_stage": "prod",
                "role": "trainee",
                "group_id": "12",
                "duration_seconds": 45.3,
            },
        }
        resp = client.post("/webhook", json=payload)
        body = resp.json()
        assert body["data"]["metadata"]["run_stage"] == "prod"
        assert body["data"]["metadata"]["duration_seconds"] == 45.3

    def test_webhook_with_batch_trainee_details(self, client):
        payload = {
            "status": "partial_success",
            "batch": "3",
            "errors": [{"email": "fail@test.com", "reason": "dup"}],
            "successful_trainees": [
                {"name": "Alice", "email": "alice@test.com", "status": "Success"},
            ],
            "failed_trainees": [
                {"name": "Bob", "email": "fail@test.com", "status": "Failed"},
            ],
        }
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]["successful_trainees"]) == 1
        assert len(body["data"]["failed_trainees"]) == 1

    def test_invalid_json_rejected(self, client):
        resp = client.post(
            "/webhook",
            content=b"not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert "Invalid JSON" in resp.json()["detail"]


# ============================================================================
# Flow 2: Outbound WebhookService — HMAC signature, retries, sanitization
# ============================================================================

class TestOutboundWebhookService:
    """Test WebhookService as an E2E unit — initialization → signature → send."""

    def _make_config(self, callback_url="https://webhook.example.com/batch",
                     webhook_secret="test-secret-key", retry_count=3, retry_delay=1):
        return BatchConfig(
            run_stage="dev", batch="5", role="trainee", is_mock=True,
            delimiter=",", encoding="utf-8", chunk_size=20,
            login_url="https://dev-tenx.10academy.org/login",
            callback_url=callback_url,
            webhook_secret=webhook_secret,
            webhook_retry_count=retry_count,
            webhook_retry_delay=retry_delay,
        )

    def test_webhook_service_initialization(self):
        config = self._make_config()
        svc = WebhookService(config)
        assert svc.callback_url == "https://webhook.example.com/batch"
        assert svc.webhook_secret == "test-secret-key"
        assert svc.retry_count == 3

    def test_signature_generation(self):
        config = self._make_config()
        svc = WebhookService(config)
        payload = {"event": "batch.processed", "status": "completed"}
        sig = svc._generate_webhook_signature(payload)
        assert isinstance(sig, str)
        assert len(sig) == 64  # SHA-256 hex digest

    def test_signature_is_deterministic(self):
        config = self._make_config()
        svc = WebhookService(config)
        payload = {"key": "value", "count": 5}
        sig1 = svc._generate_webhook_signature(payload)
        sig2 = svc._generate_webhook_signature(payload)
        assert sig1 == sig2

    def test_signature_changes_with_payload(self):
        config = self._make_config()
        svc = WebhookService(config)
        sig1 = svc._generate_webhook_signature({"status": "success"})
        sig2 = svc._generate_webhook_signature({"status": "failed"})
        assert sig1 != sig2

    def test_payload_sanitization(self):
        import pandas as pd
        config = self._make_config()
        svc = WebhookService(config)
        payload = {
            "status": "completed",
            "nan_value": float("nan"),
            "none_value": None,
            "series": pd.Series({"a": 1, "b": 2}),
            "nested": {"inner": [1, "two", None]},
        }
        sanitized = svc._sanitize_payload(payload)
        assert sanitized["nan_value"] is None
        assert sanitized["none_value"] is None
        assert isinstance(sanitized["series"], dict)
        # Must be JSON-serializable
        json.dumps(sanitized)

    def test_notify_callback_sends_to_url(self, mock_webhook_http):
        config = self._make_config()
        svc = WebhookService(config)
        results = {
            "status": "completed",
            "total_processed": 3,
            "successful": 3,
            "failed": 0,
            "errors": [],
            "batch": "5",
            "metadata": {"run_stage": "dev"},
        }
        asyncio.get_event_loop().run_until_complete(svc.notify_callback(results))
        mock_webhook_http.post.assert_called_once()
        call_args = mock_webhook_http.post.call_args
        assert "https://webhook.example.com/batch" in str(call_args)
        # Should include signature header
        headers = call_args[1].get("headers", call_args.kwargs.get("headers", {}))
        assert "X-Webhook-Signature" in headers

    def test_retry_on_failure(self, mock_webhook_http):
        """Service retries on non-200 responses."""
        mock_fail = MagicMock()
        mock_fail.status_code = 500
        mock_fail.text = "Internal Server Error"
        mock_webhook_http.post.return_value = mock_fail

        config = self._make_config(retry_count=3, retry_delay=0)
        svc = WebhookService(config)
        # Override retry_delay to 0 to avoid waiting
        svc.retry_delay = 0
        results = {"status": "completed", "batch": "5", "errors": []}
        asyncio.get_event_loop().run_until_complete(svc.notify_callback(results))
        assert mock_webhook_http.post.call_count == 3

    def test_timeout_triggers_retry(self, mock_webhook_http):
        import httpx
        mock_webhook_http.post.side_effect = httpx.TimeoutException("timed out")

        config = self._make_config(retry_count=2, retry_delay=0)
        svc = WebhookService(config)
        svc.retry_delay = 0
        results = {"status": "completed", "batch": "5", "errors": []}
        asyncio.get_event_loop().run_until_complete(svc.notify_callback(results))
        assert mock_webhook_http.post.call_count == 2

    def test_no_callback_url_raises(self):
        with pytest.raises(ValueError, match="callback_url is required"):
            config = BatchConfig(
                run_stage="dev", batch="5", role="trainee", is_mock=True,
                delimiter=",", encoding="utf-8", chunk_size=20,
                login_url="https://dev-tenx.10academy.org/login",
                callback_url=None,
            )
            WebhookService(config)
