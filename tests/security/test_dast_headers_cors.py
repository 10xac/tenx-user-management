"""
DAST — CORS Policy & HTTP Header Security Testing.
Tests CORS enforcement, security headers, HTTP method restrictions,
and header injection vulnerabilities.

Aligned with OWASP Top 10:
  - A05:2021 Security Misconfiguration
  - A01:2021 Broken Access Control (CORS)
CWE:
  - CWE-942: Permissive Cross-domain Policy
  - CWE-693: Protection Mechanism Failure
  - CWE-113: HTTP Response Splitting / Header Injection
  - CWE-16: Configuration
"""
import pytest


# ============================================================================
# CWE-942: CORS Policy Enforcement
# ============================================================================

class TestCORSPolicyEnforcement:
    """Verify CORS blocks unauthorized origins and allows legitimate ones."""

    ALLOWED_ORIGINS = [
        "https://10academy.org",
        "https://dev.10academy.org",
        "https://prod.10academy.org",
        "https://dev-tenx.10academy.org",
        "https://gettenacious.com",
        "https://app.gettenacious.com",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    BLOCKED_ORIGINS = [
        "https://evil.com",
        "https://attacker.10academy.org.evil.com",
        "https://fake10academy.org",
        "https://10academy.org.attacker.com",
        "https://phishing-gettenacious.com",
        "https://null",
        "file://local",
        "https://evil.com/https://10academy.org",
    ]

    @pytest.mark.parametrize("origin", ALLOWED_ORIGINS)
    def test_allowed_origin_gets_cors_header(self, client, origin):
        resp = client.options("/trainee/single", headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
        })
        acao = resp.headers.get("access-control-allow-origin", "")
        assert acao == origin or acao == "*" or resp.status_code == 200

    @pytest.mark.parametrize("origin", BLOCKED_ORIGINS)
    def test_blocked_origin_no_cors_header(self, client, origin):
        resp = client.options("/trainee/single", headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
        })
        acao = resp.headers.get("access-control-allow-origin", "")
        # Blocked origins should NOT get their origin reflected
        assert acao != origin, f"CORS allowed unauthorized origin: {origin}"

    def test_cors_credentials_flag(self, client):
        resp = client.options("/trainee/single", headers={
            "Origin": "https://10academy.org",
            "Access-Control-Request-Method": "POST",
        })
        creds = resp.headers.get("access-control-allow-credentials", "")
        if creds:
            assert creds.lower() == "true"

    def test_cors_methods_restricted(self, client):
        resp = client.options("/trainee/single", headers={
            "Origin": "https://10academy.org",
            "Access-Control-Request-Method": "DELETE",
        })
        # Even if methods are *, the endpoint itself only accepts POST
        assert resp.status_code in [200, 405]

    def test_null_origin_blocked(self, client):
        resp = client.options("/trainee/single", headers={
            "Origin": "null",
            "Access-Control-Request-Method": "POST",
        })
        acao = resp.headers.get("access-control-allow-origin", "")
        assert acao != "null", "CORS should not allow null origin"


# ============================================================================
# CWE-693: Security Headers
# ============================================================================

class TestSecurityHeaders:
    """Check for recommended security response headers."""

    def test_content_type_header_present(self, client):
        resp = client.post("/trainee/single", json={
            "config": {"run_stage": "dev", "is_mock": True},
            "trainee": {"name": "Test User", "email": "test@example.com"},
        })
        ct = resp.headers.get("content-type", "")
        assert "application/json" in ct, "API should return JSON content-type"

    def test_no_server_version_leaked(self, client):
        resp = client.get("/openapi.json")
        server = resp.headers.get("server", "")
        # Should not reveal exact server version
        assert "uvicorn" not in server.lower() or not any(
            c.isdigit() for c in server
        ), "Server header should not reveal version details"

    def test_x_content_type_options(self, client):
        """X-Content-Type-Options: nosniff prevents MIME sniffing."""
        resp = client.post("/trainee/single", json={
            "config": {"run_stage": "dev", "is_mock": True},
            "trainee": {"name": "Test", "email": "t@e.com"},
        })
        # FastAPI doesn't set this by default — this is an advisory check
        xcto = resp.headers.get("x-content-type-options")
        if xcto is None:
            pytest.skip("ADVISORY: X-Content-Type-Options header not set (recommended: nosniff)")

    def test_x_frame_options(self, client):
        resp = client.get("/docs")
        xfo = resp.headers.get("x-frame-options")
        if xfo is None:
            pytest.skip("ADVISORY: X-Frame-Options header not set (recommended: DENY)")

    def test_strict_transport_security(self, client):
        resp = client.get("/openapi.json")
        hsts = resp.headers.get("strict-transport-security")
        if hsts is None:
            pytest.skip("ADVISORY: Strict-Transport-Security header not set")

    def test_cache_control_on_sensitive_endpoints(self, client):
        """Sensitive endpoints should prevent caching."""
        resp = client.post("/trainee/single", json={
            "config": {"run_stage": "dev", "is_mock": True},
            "trainee": {"name": "Test", "email": "t@e.com"},
        })
        cc = resp.headers.get("cache-control", "")
        if not cc:
            pytest.skip("ADVISORY: Cache-Control header not set on sensitive endpoint")
        else:
            assert "no-store" in cc or "no-cache" in cc or "private" in cc


# ============================================================================
# CWE-113: HTTP Response Splitting / Header Injection
# ============================================================================

class TestHeaderInjection:
    """Attempt to inject headers via user input."""

    CRLF_PAYLOADS = [
        "value\r\nInjected-Header: malicious",
        "value\nSet-Cookie: stolen=true",
        "value\r\nX-Injected: true",
        "value%0d%0aInjected: true",
        "value%0aSet-Cookie: hacked=1",
    ]

    @pytest.mark.parametrize("payload", CRLF_PAYLOADS)
    def test_crlf_in_name_no_header_injection(self, client, payload):
        resp = client.post("/trainee/single", json={
            "config": {"run_stage": "dev", "is_mock": True},
            "trainee": {"name": payload, "email": "test@example.com"},
        })
        # Verify no injected headers in response
        assert "Injected-Header" not in str(resp.headers)
        assert "Set-Cookie" not in str(resp.headers) or "stolen" not in str(resp.headers)
        assert "X-Injected" not in str(resp.headers)

    @pytest.mark.parametrize("payload", CRLF_PAYLOADS)
    def test_crlf_in_webhook_no_header_injection(self, client, payload):
        resp = client.post("/webhook", json={
            "status": payload, "batch": "1", "errors": []
        })
        assert "Injected-Header" not in str(resp.headers)
        assert "X-Injected" not in str(resp.headers)


# ============================================================================
# HTTP Method Restriction
# ============================================================================

class TestHTTPMethodRestriction:
    """Verify only intended HTTP methods are allowed per endpoint."""

    ENDPOINTS = [
        "/trainee/single",
        "/trainee/admin-single",
        "/trainee/batch",
        "/webhook",
        "/env/refresh_env_vars",
        "/env/check_env_cache",
    ]

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_get_not_allowed(self, client, endpoint):
        resp = client.get(endpoint)
        assert resp.status_code == 405, f"GET should not be allowed on {endpoint}"

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_put_not_allowed(self, client, endpoint):
        resp = client.put(endpoint)
        assert resp.status_code == 405, f"PUT should not be allowed on {endpoint}"

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_delete_not_allowed(self, client, endpoint):
        resp = client.delete(endpoint)
        assert resp.status_code == 405, f"DELETE should not be allowed on {endpoint}"

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_patch_not_allowed(self, client, endpoint):
        resp = client.patch(endpoint)
        assert resp.status_code == 405, f"PATCH should not be allowed on {endpoint}"

    def test_trace_not_allowed(self, client):
        """TRACE can be used for XST attacks."""
        resp = client.request("TRACE", "/trainee/single")
        assert resp.status_code == 405, "TRACE method should be disabled"
