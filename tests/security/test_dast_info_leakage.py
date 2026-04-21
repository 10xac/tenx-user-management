"""
DAST — Information Leakage & Error Handling Security Testing.
Tests that error responses don't expose sensitive internal details,
stack traces, database schemas, or infrastructure information.

Aligned with OWASP Top 10:
  - A09:2021 Security Logging and Monitoring Failures
  - A05:2021 Security Misconfiguration
CWE:
  - CWE-209: Generation of Error Message Containing Sensitive Info
  - CWE-532: Insertion of Sensitive Info into Log File
  - CWE-200: Exposure of Sensitive Information
"""
import pytest


# ============================================================================
# CWE-209: Error Messages Should Not Expose Internal Details
# ============================================================================

SENSITIVE_PATTERNS = [
    "Traceback (most recent call last)",
    "File \"/",
    "site-packages/",
    "psycopg2",
    "sqlalchemy",
    "pymongo",
    "password=",
    "DATABASE_URL",
    "SECRET_KEY",
    "AWS_ACCESS_KEY",
    "STRAPI_TOKEN",
    "/home/",
    "/usr/",
    "C:\\Users\\",
    ".pyc",
]


class TestErrorMessageLeakage:
    """Verify error responses don't leak sensitive internal information."""

    def test_invalid_json_error_safe(self, client):
        resp = client.post(
            "/trainee/single",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        body = resp.text
        for pattern in SENSITIVE_PATTERNS:
            assert pattern not in body, \
                f"Sensitive info '{pattern}' leaked in invalid JSON error response"

    def test_validation_error_safe(self, client):
        resp = client.post("/trainee/single", json={
            "config": {"run_stage": "dev"},
            "trainee": {"name": "", "email": "invalid"},
        })
        body = resp.text
        for pattern in SENSITIVE_PATTERNS:
            assert pattern not in body, \
                f"Sensitive info '{pattern}' leaked in validation error"

    def test_404_error_safe(self, client):
        resp = client.get("/nonexistent/endpoint/with/path")
        body = resp.text
        for pattern in SENSITIVE_PATTERNS:
            assert pattern not in body, \
                f"Sensitive info '{pattern}' leaked in 404 response"

    def test_method_not_allowed_error_safe(self, client):
        resp = client.get("/trainee/single")
        body = resp.text
        for pattern in SENSITIVE_PATTERNS:
            assert pattern not in body, \
                f"Sensitive info '{pattern}' leaked in 405 response"

    def test_webhook_invalid_payload_safe(self, client):
        resp = client.post(
            "/webhook",
            content=b"<xml>not json</xml>",
            headers={"Content-Type": "application/json"},
        )
        body = resp.text
        for pattern in SENSITIVE_PATTERNS:
            assert pattern not in body, \
                f"Sensitive info '{pattern}' leaked in webhook error"

    def test_deeply_malformed_request_safe(self, client):
        resp = client.post(
            "/trainee/single",
            content=b"\x00\x01\x02\x03",
            headers={"Content-Type": "application/json"},
        )
        body = resp.text
        for pattern in SENSITIVE_PATTERNS:
            assert pattern not in body

    def test_oversized_payload_safe(self, client):
        """Large payload should not reveal memory info."""
        large_name = "A" * 100000
        resp = client.post("/trainee/single", json={
            "config": {"run_stage": "dev"},
            "trainee": {"name": large_name, "email": "test@example.com"},
        })
        body = resp.text
        for pattern in SENSITIVE_PATTERNS:
            assert pattern not in body


# ============================================================================
# CWE-200: API Schema / OpenAPI Exposure Analysis
# ============================================================================

class TestAPISchemaExposure:
    """Analyze OpenAPI schema for information leakage."""

    def test_openapi_schema_accessible(self, client):
        """OpenAPI schema is accessible — verify it doesn't contain secrets."""
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        body = resp.text
        # Schema should not contain actual secrets
        assert "AKIA" not in body
        assert "Bearer " not in body or "Bearer {" in body  # template is OK
        for pattern in ["password=", "secret=", "token="]:
            # These in example values are OK, but not as hardcoded real values
            assert pattern not in body.lower() or "example" in body.lower()

    def test_docs_endpoint_available(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_redoc_endpoint_available(self, client):
        resp = client.get("/redoc")
        assert resp.status_code == 200

    def test_schema_does_not_expose_internal_paths(self, client):
        resp = client.get("/openapi.json")
        body = resp.text
        assert "/etc/" not in body
        assert "/home/" not in body
        assert "C:\\" not in body


# ============================================================================
# CWE-200: Response Header Information Leakage
# ============================================================================

class TestResponseHeaderLeakage:
    def test_no_powered_by_header(self, client):
        resp = client.get("/openapi.json")
        xpb = resp.headers.get("x-powered-by", "")
        assert not xpb, f"X-Powered-By header reveals technology: {xpb}"

    def test_server_header_minimal(self, client):
        resp = client.get("/openapi.json")
        server = resp.headers.get("server", "")
        # Should not reveal detailed version info
        if server:
            assert not any(c.isdigit() and server.count(".") >= 2 for c in server), \
                f"Server header reveals version: {server}"

    def test_no_debug_headers(self, client):
        resp = client.post("/trainee/single", json={
            "config": {"run_stage": "dev", "is_mock": True},
            "trainee": {"name": "Test", "email": "t@e.com"},
        })
        debug_headers = ["x-debug", "x-debug-token", "x-stack-trace",
                         "x-sql-query", "x-internal-error"]
        for h in debug_headers:
            assert h not in resp.headers, f"Debug header found: {h}"


# ============================================================================
# Error Response Consistency
# ============================================================================

class TestErrorResponseConsistency:
    """All errors should use a consistent format that doesn't reveal internals."""

    def test_validation_error_format(self, client):
        resp = client.post("/trainee/single", json={
            "config": {"run_stage": "dev"},
            "trainee": {"name": "", "email": "bad"},
        })
        assert resp.status_code == 422
        body = resp.json()
        # Should use standardized error format
        assert "success" in body
        assert body["success"] is False
        assert "error" in body
        assert "error_type" in body["error"]
        assert "error_message" in body["error"]

    def test_webhook_error_format(self, client):
        resp = client.post(
            "/webhook",
            content=b"invalid",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert "detail" in body
        # Should not contain stack traces
        assert "Traceback" not in body["detail"]

    def test_404_error_format(self, client):
        resp = client.get("/nonexistent")
        assert resp.status_code == 404
        body = resp.json()
        assert "detail" in body

    def test_error_does_not_include_request_body(self, client):
        """Error responses should not echo back the full request body."""
        sensitive_payload = {
            "config": {"run_stage": "dev"},
            "trainee": {
                "name": "",  # invalid
                "email": "bad",  # invalid
                "password": "SuperSecretPassword123!",
            },
        }
        resp = client.post("/trainee/single", json=sensitive_payload)
        body = resp.text
        assert "SuperSecretPassword123!" not in body, \
            "Error response should not echo back passwords"


# ============================================================================
# Rate Limiting / DoS Resilience Indicators
# ============================================================================

class TestDoSResilience:
    """Basic tests for DoS resilience (not true load tests)."""

    def test_rapid_sequential_requests(self, client):
        """Application should handle rapid sequential requests without crashing."""
        for i in range(20):
            resp = client.post("/trainee/single", json={
                "config": {"run_stage": "dev", "is_mock": True},
                "trainee": {"name": f"User{i}", "email": f"user{i}@test.com"},
            })
            assert resp.status_code in [200, 422], \
                f"Request {i} failed with status {resp.status_code}"

    def test_rapid_webhook_requests(self, client):
        for i in range(20):
            resp = client.post("/webhook", json={
                "status": "success", "batch": str(i), "errors": []
            })
            assert resp.status_code == 200

    def test_large_json_payload(self, client):
        """Very large JSON payload should not cause OOM."""
        large_info = {f"key_{i}": f"value_{i}" * 100 for i in range(100)}
        resp = client.post("/trainee/single", json={
            "config": {"run_stage": "dev", "is_mock": True},
            "trainee": {
                "name": "Test", "email": "t@e.com",
                "other_info": large_info,
            },
        })
        assert resp.status_code in [200, 422]
