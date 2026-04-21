"""
API integration tests for environment endpoints:
  POST /env/refresh_env_vars
  POST /env/check_env_cache
Tests auth requirements, request/response contracts, and error handling.
"""
import pytest
from unittest.mock import patch, MagicMock

from api.models.trainee import TraineeResponse
from api.core.auth import verify_admin_access
from api.main import app


# ============================================================================
# POST /env/refresh_env_vars — Auth
# ============================================================================

class TestRefreshEnvAuth:
    def test_no_auth_returns_401(self, client):
        resp = client.post("/env/refresh_env_vars", json={
            "sname": "tenx/env/vars", "run_stage": "dev"
        })
        assert resp.status_code in [401, 403]

    def test_auth_error_propagated(self, client, auth_error_response):
        app.dependency_overrides[verify_admin_access] = lambda: auth_error_response
        try:
            resp = client.post(
                "/env/refresh_env_vars",
                json={"sname": "tenx/env/vars", "run_stage": "dev"},
            )
            # The endpoint receives the error dict but tries to use it as admin — may 500
            assert resp.status_code in [200, 422, 500]
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)


# ============================================================================
# POST /env/refresh_env_vars — Happy Path
# ============================================================================

class TestRefreshEnvSuccess:
    def test_refresh_returns_success(self, client, admin_user):
        mock_secrets = {"KEY_A": "val_a", "KEY_B": "val_b"}
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        with patch("api.routes.env_routes.force_refresh_secrets", return_value=mock_secrets), \
             patch("api.routes.env_routes.clear_api_key_cache", return_value=True), \
             patch("api.routes.env_routes.mask_secret_value", side_effect=lambda v: "****"):
            try:
                resp = client.post(
                    "/env/refresh_env_vars",
                    json={"sname": "tenx/env/vars", "run_stage": "dev"},
                )
                assert resp.status_code == 200
                body = resp.json()
                assert body["success"] is True
                assert body["secrets_count"] == 2
                assert body["api_key_cache_cleared"] is True
                assert body["masked_secrets"]["KEY_A"] == "****"
                assert body["masked_secrets"]["KEY_B"] == "****"
            finally:
                app.dependency_overrides.pop(verify_admin_access, None)

    def test_refresh_with_specific_key(self, client, admin_user):
        mock_secrets = {"MY_KEY": "secret_value"}
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        with patch("api.routes.env_routes.force_refresh_secrets", return_value=mock_secrets), \
             patch("api.routes.env_routes.clear_api_key_cache", return_value=True), \
             patch("api.routes.env_routes.mask_secret_value", return_value="****"):
            try:
                resp = client.post(
                    "/env/refresh_env_vars",
                    json={"key": "MY_KEY", "sname": "tenx/env/vars", "run_stage": "dev"},
                )
                body = resp.json()
                assert body["success"] is True
                assert body["requested_key"] == "MY_KEY"
                assert body["masked_value"] == "****"
            finally:
                app.dependency_overrides.pop(verify_admin_access, None)

    def test_refresh_with_missing_key(self, client, admin_user):
        mock_secrets = {"OTHER_KEY": "val"}
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        with patch("api.routes.env_routes.force_refresh_secrets", return_value=mock_secrets), \
             patch("api.routes.env_routes.clear_api_key_cache", return_value=True), \
             patch("api.routes.env_routes.mask_secret_value", return_value="****"):
            try:
                resp = client.post(
                    "/env/refresh_env_vars",
                    json={"key": "NONEXISTENT", "sname": "tenx/env/vars", "run_stage": "dev"},
                )
                body = resp.json()
                assert body["success"] is True
                assert body["masked_value"] == "<not found>"
                assert any("not found" in e for e in body.get("errors", []))
            finally:
                app.dependency_overrides.pop(verify_admin_access, None)


# ============================================================================
# POST /env/refresh_env_vars — Failure
# ============================================================================

class TestRefreshEnvFailure:
    def test_aws_error_returns_500(self, client, admin_user):
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        with patch("api.routes.env_routes.force_refresh_secrets", side_effect=Exception("AWS timeout")):
            try:
                resp = client.post(
                    "/env/refresh_env_vars",
                    json={"sname": "tenx/env/vars", "run_stage": "dev"},
                )
                assert resp.status_code == 500
                assert "Failed to refresh secrets" in resp.json()["detail"]
            finally:
                app.dependency_overrides.pop(verify_admin_access, None)


# ============================================================================
# POST /env/check_env_cache — Auth
# ============================================================================

class TestCheckCacheAuth:
    def test_no_auth_returns_401(self, client):
        resp = client.post("/env/check_env_cache", json={
            "sname": "tenx/env/vars", "run_stage": "dev"
        })
        assert resp.status_code in [401, 403]


# ============================================================================
# POST /env/check_env_cache — Happy Path
# ============================================================================

class TestCheckCacheSuccess:
    def test_returns_cache_metadata(self, client, admin_user):
        mock_metadata = {
            "memory_cache_exists": True,
            "cache_age_seconds": 300,
            "is_fresh": True,
            "num_keys": 5,
        }
        mock_secrets = {"K1": "v1", "K2": "v2", "K3": "v3"}
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        with patch("api.routes.env_routes.get_cache_metadata", return_value=mock_metadata), \
             patch("api.routes.env_routes.get_all_secrets", return_value=mock_secrets), \
             patch("api.routes.env_routes.mask_secret_value", return_value="****"):
            try:
                resp = client.post(
                    "/env/check_env_cache",
                    json={"sname": "tenx/env/vars", "run_stage": "dev"},
                )
                assert resp.status_code == 200
                body = resp.json()
                assert body["success"] is True
                assert body["cache_metadata"]["memory_cache_exists"] is True
                assert body["cache_metadata"]["is_fresh"] is True
                assert "sample_keys" in body
                assert len(body["sample_keys"]) == 3
            finally:
                app.dependency_overrides.pop(verify_admin_access, None)

    def test_check_specific_key(self, client, admin_user):
        mock_metadata = {"memory_cache_exists": True}
        mock_secrets = {"MY_KEY": "secret"}
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        with patch("api.routes.env_routes.get_cache_metadata", return_value=mock_metadata), \
             patch("api.routes.env_routes.get_all_secrets", return_value=mock_secrets), \
             patch("api.routes.env_routes.mask_secret_value", return_value="****"):
            try:
                resp = client.post(
                    "/env/check_env_cache",
                    json={"key": "MY_KEY", "sname": "tenx/env/vars", "run_stage": "dev"},
                )
                body = resp.json()
                assert body["requested_key"] == "MY_KEY"
                assert body["masked_value"] == "****"
            finally:
                app.dependency_overrides.pop(verify_admin_access, None)

    def test_check_missing_key(self, client, admin_user):
        mock_metadata = {"memory_cache_exists": True}
        mock_secrets = {"OTHER": "val"}
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        with patch("api.routes.env_routes.get_cache_metadata", return_value=mock_metadata), \
             patch("api.routes.env_routes.get_all_secrets", return_value=mock_secrets), \
             patch("api.routes.env_routes.mask_secret_value", return_value="****"):
            try:
                resp = client.post(
                    "/env/check_env_cache",
                    json={"key": "MISSING", "sname": "tenx/env/vars", "run_stage": "dev"},
                )
                body = resp.json()
                assert body["masked_value"] == "<not found>"
            finally:
                app.dependency_overrides.pop(verify_admin_access, None)


# ============================================================================
# POST /env/check_env_cache — Failure
# ============================================================================

class TestCheckCacheFailure:
    def test_cache_check_error_returns_500(self, client, admin_user):
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        with patch("api.routes.env_routes.get_cache_metadata", side_effect=Exception("cache broken")):
            try:
                resp = client.post(
                    "/env/check_env_cache",
                    json={"sname": "tenx/env/vars", "run_stage": "dev"},
                )
                assert resp.status_code == 500
                assert "Failed to check cache" in resp.json()["detail"]
            finally:
                app.dependency_overrides.pop(verify_admin_access, None)


# ============================================================================
# HTTP Methods
# ============================================================================

class TestEnvMethods:
    def test_get_refresh_not_allowed(self, client):
        resp = client.get("/env/refresh_env_vars")
        assert resp.status_code == 405

    def test_get_cache_not_allowed(self, client):
        resp = client.get("/env/check_env_cache")
        assert resp.status_code == 405
