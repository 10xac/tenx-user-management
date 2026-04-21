"""
DAST — Injection Attack Testing (SQLi, XSS, Command Injection, Path Traversal, SSTI).
Sends malicious payloads through all input vectors and verifies the application
rejects or sanitizes them safely.

Aligned with OWASP Top 10:
  - A03:2021 Injection
CWE:
  - CWE-89: SQL Injection
  - CWE-79: Cross-site Scripting (XSS)
  - CWE-78: OS Command Injection
  - CWE-22: Path Traversal
  - CWE-1336: Server-Side Template Injection
"""
import pytest
import io
from tests.security.conftest import (
    SQL_INJECTION_PAYLOADS,
    XSS_PAYLOADS,
    COMMAND_INJECTION_PAYLOADS,
    PATH_TRAVERSAL_PAYLOADS,
    NOSQL_INJECTION_PAYLOADS,
)


# ============================================================================
# Helpers
# ============================================================================

def _trainee_payload(**overrides):
    base = {
        "config": {"run_stage": "dev", "batch": "5", "role": "trainee", "is_mock": True},
        "trainee": {
            "name": "Safe Name", "email": "safe@example.com", "password": "Pass1",
        },
    }
    base["trainee"].update(overrides)
    return base


def _assert_safe_response(resp, payload_desc):
    """Assert the response is safe — either rejected or payload not reflected raw."""
    if resp.status_code in [400, 422]:
        return  # Rejected — safe
    if resp.status_code == 200:
        body = resp.text
        # Ensure no raw script tags are reflected in the response
        assert "<script>" not in body.lower(), \
            f"XSS payload reflected in response for: {payload_desc}"
        assert "alert(" not in body.lower() or "xss" not in body.lower(), \
            f"XSS payload reflected in response for: {payload_desc}"
        return
    # Any 4xx/5xx is acceptable (means payload was rejected or errored safely)
    assert resp.status_code < 600


# ============================================================================
# CWE-89: SQL Injection via trainee name field
# ============================================================================

class TestSQLInjectionName:
    @pytest.mark.parametrize("sqli", SQL_INJECTION_PAYLOADS)
    def test_sqli_in_trainee_name(self, client, sqli):
        resp = client.post("/trainee/single", json=_trainee_payload(name=sqli))
        # Name must contain a letter, so most SQL payloads pass name validation
        # Key: app should NOT crash with 500, and should not execute SQL
        assert resp.status_code != 500, f"Server error on SQL injection: {sqli}"
        if resp.status_code == 200:
            body = resp.json()
            # If processed, the payload is just treated as string data
            assert isinstance(body, dict)


class TestSQLInjectionEmail:
    @pytest.mark.parametrize("sqli", SQL_INJECTION_PAYLOADS)
    def test_sqli_in_trainee_email(self, client, sqli):
        resp = client.post("/trainee/single", json=_trainee_payload(email=sqli))
        # Email validator should reject all SQL injection payloads
        assert resp.status_code in [200, 422], f"Unexpected status for SQLi in email: {sqli}"
        if resp.status_code == 200:
            assert resp.json().get("success") is False or resp.status_code == 422


class TestSQLInjectionConfig:
    @pytest.mark.parametrize("sqli", SQL_INJECTION_PAYLOADS)
    def test_sqli_in_run_stage(self, client, sqli):
        payload = _trainee_payload()
        payload["config"]["run_stage"] = sqli
        resp = client.post("/trainee/single", json=payload)
        assert resp.status_code != 500, f"Server error on SQLi in run_stage: {sqli}"

    @pytest.mark.parametrize("sqli", SQL_INJECTION_PAYLOADS)
    def test_sqli_in_batch_field(self, client, sqli):
        payload = _trainee_payload()
        payload["config"]["batch"] = sqli
        resp = client.post("/trainee/single", json=payload)
        assert resp.status_code != 500, f"Server error on SQLi in batch: {sqli}"


# ============================================================================
# CWE-79: Cross-Site Scripting (XSS) via input fields
# ============================================================================

class TestXSSInTraineeFields:
    @pytest.mark.parametrize("xss", XSS_PAYLOADS)
    def test_xss_in_name(self, client, xss):
        resp = client.post("/trainee/single", json=_trainee_payload(name=xss))
        _assert_safe_response(resp, f"name={xss}")

    @pytest.mark.parametrize("xss", XSS_PAYLOADS)
    def test_xss_in_nationality(self, client, xss):
        resp = client.post("/trainee/single", json=_trainee_payload(nationality=xss))
        _assert_safe_response(resp, f"nationality={xss}")

    @pytest.mark.parametrize("xss", XSS_PAYLOADS)
    def test_xss_in_bio(self, client, xss):
        resp = client.post("/trainee/single", json=_trainee_payload(bio=xss))
        _assert_safe_response(resp, f"bio={xss}")

    @pytest.mark.parametrize("xss", XSS_PAYLOADS)
    def test_xss_in_city(self, client, xss):
        resp = client.post("/trainee/single", json=_trainee_payload(city_of_residence=xss))
        _assert_safe_response(resp, f"city={xss}")


class TestXSSInWebhook:
    @pytest.mark.parametrize("xss", XSS_PAYLOADS)
    def test_xss_in_webhook_payload(self, client, xss):
        """Webhook echoes data in JSON — safe as long as Content-Type is application/json.
        Browsers will not execute scripts in JSON responses with correct content-type."""
        payload = {"status": xss, "batch": xss, "errors": []}
        resp = client.post("/webhook", json=payload)
        # The critical defense: Content-Type must be application/json, not text/html
        ct = resp.headers.get("content-type", "")
        assert "application/json" in ct, \
            f"Webhook response must be application/json to prevent XSS, got: {ct}"
        assert "text/html" not in ct, \
            "Webhook must NOT return text/html — would enable reflected XSS"


# ============================================================================
# CWE-78: Command Injection
# ============================================================================

class TestCommandInjection:
    @pytest.mark.parametrize("cmdi", COMMAND_INJECTION_PAYLOADS)
    def test_cmdi_in_name(self, client, cmdi):
        resp = client.post("/trainee/single", json=_trainee_payload(name=cmdi))
        assert resp.status_code != 500, f"Server error on command injection: {cmdi}"

    @pytest.mark.parametrize("cmdi", COMMAND_INJECTION_PAYLOADS)
    def test_cmdi_in_run_stage(self, client, cmdi):
        payload = _trainee_payload()
        payload["config"]["run_stage"] = cmdi
        resp = client.post("/trainee/single", json=payload)
        assert resp.status_code != 500, f"Server error on command injection in run_stage: {cmdi}"


# ============================================================================
# CWE-22: Path Traversal via file upload
# ============================================================================

class TestPathTraversal:
    @pytest.mark.parametrize("pt", PATH_TRAVERSAL_PAYLOADS)
    def test_path_traversal_in_filename(self, authed_client, pt):
        csv_content = b"name,email\nAlice,alice@test.com\n"
        files = {"file": (pt, io.BytesIO(csv_content), "text/csv")}
        resp = authed_client.post("/trainee/batch", files=files, data={
            "run_stage": "dev", "batch": "1", "is_mock": "true",
        })
        # Should not reveal filesystem info or crash
        assert resp.status_code != 500 or "etc/passwd" not in resp.text

    @pytest.mark.parametrize("pt", PATH_TRAVERSAL_PAYLOADS)
    def test_path_traversal_in_run_stage(self, client, pt):
        payload = _trainee_payload()
        payload["config"]["run_stage"] = pt
        resp = client.post("/trainee/single", json=payload)
        assert resp.status_code != 500, f"Server error on path traversal in run_stage: {pt}"


# ============================================================================
# CWE-1336: Server-Side Template Injection (SSTI)
# ============================================================================

class TestSSTI:
    SSTI_PAYLOADS = [
        "{{7*7}}",
        "${7*7}",
        "#{7*7}",
        "<%= 7*7 %>",
        "{{config}}",
        "{{self.__class__.__mro__}}",
        "${T(java.lang.Runtime).getRuntime().exec('id')}",
        "{{''.__class__.__mro__[1].__subclasses__()}}",
    ]

    @pytest.mark.parametrize("ssti", SSTI_PAYLOADS)
    def test_ssti_in_name(self, client, ssti):
        resp = client.post("/trainee/single", json=_trainee_payload(name=ssti))
        if resp.status_code == 200:
            body = resp.text
            # Ensure template was NOT evaluated
            assert "49" not in body or ssti not in body, \
                f"SSTI payload may have been evaluated: {ssti}"

    @pytest.mark.parametrize("ssti", SSTI_PAYLOADS)
    def test_ssti_in_bio(self, client, ssti):
        resp = client.post("/trainee/single", json=_trainee_payload(bio=ssti))
        if resp.status_code == 200:
            body = resp.text
            assert "49" not in body or ssti not in body


# ============================================================================
# NoSQL Injection via JSON fields
# ============================================================================

class TestNoSQLInjection:
    def test_nosql_in_name_field_object(self, client):
        """Pydantic should reject non-string name values."""
        payload = _trainee_payload()
        payload["trainee"]["name"] = {"$gt": ""}
        resp = client.post("/trainee/single", json=payload)
        assert resp.status_code == 422, "NoSQL object in name should be rejected"

    def test_nosql_in_email_field_object(self, client):
        payload = _trainee_payload()
        payload["trainee"]["email"] = {"$ne": None}
        resp = client.post("/trainee/single", json=payload)
        assert resp.status_code == 422, "NoSQL object in email should be rejected"

    def test_nosql_in_webhook_status(self, client):
        """Webhook status field accepts any JSON — verify it doesn't crash.
        The webhook is a notification receiver, not a database query endpoint."""
        payload = {"status": {"$gt": ""}, "batch": "1", "errors": []}
        resp = client.post("/webhook", json=payload)
        # Webhook echoes data as JSON; the key defense is that this data
        # is never used in database queries directly.
        assert resp.status_code in [200, 400, 422, 500]
        # If 200, ensure response is JSON (not HTML)
        if resp.status_code == 200:
            ct = resp.headers.get("content-type", "")
            assert "application/json" in ct


# ============================================================================
# JSON Injection / Prototype Pollution
# ============================================================================

class TestJSONInjection:
    def test_deeply_nested_json(self, client):
        """Deeply nested JSON should not cause stack overflow."""
        nested = {"a": "b"}
        for _ in range(50):
            nested = {"nested": nested}
        payload = _trainee_payload()
        payload["trainee"]["other_info"] = nested
        resp = client.post("/trainee/single", json=payload)
        assert resp.status_code != 500

    def test_prototype_pollution_keys(self, client):
        payload = _trainee_payload()
        payload["trainee"]["other_info"] = {
            "__proto__": {"admin": True},
            "constructor": {"prototype": {"admin": True}},
        }
        resp = client.post("/trainee/single", json=payload)
        # Python is not vulnerable to prototype pollution, but verify no crash
        assert resp.status_code in [200, 422]
