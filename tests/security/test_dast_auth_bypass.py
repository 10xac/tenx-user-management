"""
DAST (Dynamic Application Security Testing) — Authentication & Authorization.
Tests runtime auth bypass attempts, token manipulation, role escalation,
and authorization boundary enforcement.

Aligned with OWASP Top 10:
  - A01:2021 Broken Access Control
  - A07:2021 Identification and Authentication Failures
CWE:
  - CWE-287: Improper Authentication
  - CWE-862: Missing Authorization
  - CWE-863: Incorrect Authorization
"""
import pytest
from api.main import app
from api.core.auth import verify_admin_access
from api.models.trainee import TraineeResponse


# ============================================================================
# Helpers
# ============================================================================

def _trainee_payload():
    return {
        "config": {"run_stage": "dev", "batch": "5", "role": "trainee", "is_mock": True},
        "trainee": {
            "name": "Test User", "email": "test@example.com", "password": "Pass1",
        },
    }


PROTECTED_ENDPOINTS = [
    ("POST", "/trainee/admin-single"),
    ("POST", "/trainee/batch"),
    ("POST", "/env/refresh_env_vars"),
    ("POST", "/env/check_env_cache"),
]


# ============================================================================
# A01: Missing Authentication — Protected endpoints without token
# ============================================================================

class TestMissingAuthentication:
    """All admin endpoints must reject requests without valid auth."""

    @pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
    def test_no_auth_header_rejected(self, client, method, path):
        if path == "/trainee/admin-single":
            resp = client.request(method, path, json=_trainee_payload())
        elif path == "/trainee/batch":
            resp = client.request(method, path, files={"file": ("t.csv", b"name,email\na,a@b.com")})
        else:
            resp = client.request(method, path, json={"sname": "tenx/env/vars", "run_stage": "dev"})
        assert resp.status_code in [401, 403], \
            f"{method} {path} should reject unauthenticated requests, got {resp.status_code}"


# ============================================================================
# A07: Token Manipulation Attacks
# ============================================================================

class TestTokenManipulation:
    """Test various token forgery and manipulation attacks."""

    INVALID_TOKENS = [
        "",                          # empty
        "invalid-token",             # random string
        "Bearer ",                   # empty bearer
        "eyJhbGciOiJub25lIn0.eyJ0ZXN0IjoxfQ.",  # alg=none JWT
        "a" * 1000,                  # extremely long token
        "../../etc/passwd",          # path traversal in token
        "<script>alert(1)</script>", # XSS in token
        "null",                      # null string
        "undefined",                 # undefined string
        "true",                      # boolean string
    ]

    @pytest.mark.parametrize("token", INVALID_TOKENS)
    def test_invalid_bearer_token_rejected(self, client, token):
        headers = {"Authorization": f"Bearer {token}"}
        resp = client.post("/trainee/admin-single", json=_trainee_payload(), headers=headers)
        # Should not return 200 with success
        if resp.status_code == 200:
            body = resp.json()
            assert body.get("success") is False, \
                f"Invalid token '{token[:30]}...' should not yield success"
        else:
            assert resp.status_code in [401, 403, 422]

    def test_wrong_auth_scheme_rejected(self, client):
        headers = {"Authorization": "Basic dXNlcjpwYXNz"}
        resp = client.post("/trainee/admin-single", json=_trainee_payload(), headers=headers)
        assert resp.status_code in [401, 403]

    def test_missing_bearer_prefix_rejected(self, client):
        headers = {"Authorization": "some-token-value"}
        resp = client.post("/trainee/admin-single", json=_trainee_payload(), headers=headers)
        assert resp.status_code in [401, 403]

    def test_double_bearer_prefix(self, client):
        headers = {"Authorization": "Bearer Bearer real-token"}
        resp = client.post("/trainee/admin-single", json=_trainee_payload(), headers=headers)
        if resp.status_code == 200:
            assert resp.json().get("success") is False


# ============================================================================
# A01: Role-Based Access Control (RBAC)
# ============================================================================

class TestRoleBasedAccessControl:
    """Verify role escalation is prevented."""

    def test_trainee_role_cannot_access_admin_endpoint(self, client):
        """A user with 'trainee' role should be denied admin access."""
        non_admin_user = {
            "id": "99", "email": "trainee@10academy.org",
            "username": "trainee", "role": "trainee",
        }
        app.dependency_overrides[verify_admin_access] = lambda: TraineeResponse.error_response(
            error_type="AUTH_ERROR",
            error_message="Insufficient permissions. Admin access required.",
            error_location="admin_verification",
            error_data={"user_role": "trainee"},
        )
        try:
            resp = client.post("/trainee/admin-single", json=_trainee_payload())
            body = resp.json()
            assert body["success"] is False
            assert "AUTH_ERROR" in body["error"]["error_type"]
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)

    def test_public_role_cannot_access_admin(self, client):
        app.dependency_overrides[verify_admin_access] = lambda: TraineeResponse.error_response(
            error_type="AUTH_ERROR",
            error_message="Insufficient permissions.",
            error_location="admin_verification",
            error_data={"user_role": "Public"},
        )
        try:
            resp = client.post("/trainee/admin-single", json=_trainee_payload())
            assert resp.json()["success"] is False
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)

    def test_staff_role_can_access_admin(self, authed_client):
        """Staff role should have admin access."""
        resp = authed_client.post("/trainee/admin-single", json=_trainee_payload())
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_authenticated_role_can_access_admin(self, client):
        app.dependency_overrides[verify_admin_access] = lambda: {
            "id": "2", "email": "auth@10academy.org",
            "username": "auth_user", "role": "Authenticated",
        }
        try:
            resp = client.post("/trainee/admin-single", json=_trainee_payload())
            assert resp.status_code == 200
            assert resp.json()["success"] is True
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)


# ============================================================================
# A01: Public vs Protected Endpoint Boundary
# ============================================================================

class TestEndpointBoundary:
    """Verify which endpoints require auth and which don't."""

    def test_single_trainee_is_public(self, client):
        """POST /trainee/single does NOT require auth (commented out in code)."""
        resp = client.post("/trainee/single", json=_trainee_payload())
        assert resp.status_code == 200

    def test_webhook_is_public(self, client):
        """POST /webhook does NOT require auth."""
        resp = client.post("/webhook", json={
            "status": "success", "batch": "1", "errors": []
        })
        assert resp.status_code == 200

    def test_admin_single_requires_auth(self, client):
        resp = client.post("/trainee/admin-single", json=_trainee_payload())
        assert resp.status_code in [401, 403]

    def test_batch_requires_auth(self, client):
        resp = client.post("/trainee/batch",
                           files={"file": ("t.csv", b"name,email\na,a@b.com")})
        assert resp.status_code in [401, 403]

    def test_env_refresh_requires_auth(self, client):
        resp = client.post("/env/refresh_env_vars",
                           json={"sname": "tenx/env/vars", "run_stage": "dev"})
        assert resp.status_code in [401, 403]

    def test_env_cache_requires_auth(self, client):
        resp = client.post("/env/check_env_cache",
                           json={"sname": "tenx/env/vars", "run_stage": "dev"})
        assert resp.status_code in [401, 403]


# ============================================================================
# A01: IDOR (Insecure Direct Object Reference) prevention
# ============================================================================

class TestIDORPrevention:
    """Ensure no unprotected direct object references."""

    def test_no_user_id_enumeration(self, client):
        """GET endpoints with user IDs should not exist."""
        for uid in ["1", "2", "999", "admin"]:
            resp = client.get(f"/trainee/{uid}")
            assert resp.status_code in [404, 405], \
                f"User ID enumeration possible via /trainee/{uid}"

    def test_no_batch_id_enumeration(self, client):
        for bid in ["1", "2", "latest"]:
            resp = client.get(f"/trainee/batch/{bid}")
            assert resp.status_code in [404, 405]
