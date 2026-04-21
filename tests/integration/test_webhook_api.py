"""
API integration tests for webhook endpoint: POST /webhook.
Tests payload handling, status routing, JSON validation, and edge cases.
"""
import pytest
import json
from fastapi.testclient import TestClient
from api.main import app


# ============================================================================
# POST /webhook — Happy Paths
# ============================================================================

class TestWebhookSuccess:
    def test_success_status(self, client):
        payload = {"status": "success", "batch": "5", "errors": []}
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "received"
        assert body["message"] == "Webhook processed successfully"
        assert body["data"]["status"] == "success"
        assert body["data"]["batch"] == "5"

    def test_partial_success_status(self, client):
        payload = {
            "status": "partial_success",
            "batch": "10",
            "errors": [{"email": "fail@test.com", "reason": "duplicate"}],
        }
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["status"] == "partial_success"
        assert len(body["data"]["errors"]) == 1

    def test_failed_status(self, client):
        payload = {
            "status": "failed",
            "batch": "7",
            "errors": [
                {"email": "a@b.com", "reason": "Strapi down"},
                {"email": "c@d.com", "reason": "timeout"},
            ],
        }
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["status"] == "failed"
        assert len(body["data"]["errors"]) == 2

    def test_response_echoes_full_payload(self, client):
        payload = {
            "status": "success",
            "batch": "99",
            "errors": [],
            "extra_field": "preserved",
        }
        resp = client.post("/webhook", json=payload)
        body = resp.json()
        assert body["data"]["extra_field"] == "preserved"

    def test_large_error_list(self, client):
        errors = [{"email": f"user{i}@test.com", "reason": "fail"} for i in range(100)]
        payload = {"status": "partial_success", "batch": "1", "errors": errors}
        resp = client.post("/webhook", json=payload)
        assert resp.status_code == 200
        assert len(resp.json()["data"]["errors"]) == 100


# ============================================================================
# POST /webhook — No Auth Required
# ============================================================================

class TestWebhookNoAuth:
    def test_no_auth_header_accepted(self, client):
        resp = client.post("/webhook", json={"status": "success", "batch": "1", "errors": []})
        assert resp.status_code == 200

    def test_with_signature_header_accepted(self, client):
        resp = client.post(
            "/webhook",
            json={"status": "success", "batch": "1", "errors": []},
            headers={"X-Webhook-Signature": "abc123"},
        )
        assert resp.status_code == 200


# ============================================================================
# POST /webhook — Invalid Payloads
# ============================================================================

class TestWebhookInvalidPayloads:
    def test_invalid_json_returns_400(self, client):
        resp = client.post(
            "/webhook",
            content=b"not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert "Invalid JSON" in resp.json()["detail"]

    def test_empty_body_returns_400(self, client):
        resp = client.post(
            "/webhook",
            content=b"",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code in [400, 422]

    def test_missing_status_field_raises_error(self, client):
        # The webhook handler accesses data["status"] directly — KeyError
        with pytest.raises(KeyError):
            client.post("/webhook", json={"batch": "1", "errors": []})

    def test_missing_batch_on_success_raises_error(self, client):
        # The webhook handler accesses data["batch"] directly — KeyError
        with pytest.raises(KeyError):
            client.post("/webhook", json={"status": "success", "errors": []})


# ============================================================================
# POST /webhook — HTTP Methods
# ============================================================================

class TestWebhookMethods:
    def test_get_not_allowed(self, client):
        resp = client.get("/webhook")
        assert resp.status_code == 405

    def test_put_not_allowed(self, client):
        resp = client.put("/webhook", json={"status": "success"})
        assert resp.status_code == 405

    def test_delete_not_allowed(self, client):
        resp = client.delete("/webhook")
        assert resp.status_code == 405
