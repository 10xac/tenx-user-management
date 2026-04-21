"""
E2E tests: Environment management flow — full pipeline.
Route → Auth → AWS Secrets Manager (mocked at boundary) → response.
Tests secret refresh, cache checking, key masking, and error propagation.
"""
import pytest
from unittest.mock import patch


# ============================================================================
# Flow 1: Refresh secrets — full pipeline
# ============================================================================

class TestRefreshSecretsFlow:
    def test_refresh_all_secrets(self, authed_client, mock_secrets):
        resp = authed_client.post("/env/refresh_env_vars", json={
            "sname": "tenx/env/vars", "run_stage": "dev"
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["secrets_count"] == 3
        assert body["api_key_cache_cleared"] is True
        assert "STRAPI_API_KEY" in body["masked_secrets"]
        assert "DB_PASSWORD" in body["masked_secrets"]
        # Values should be masked (first 2 chars + ****)
        for key, val in body["masked_secrets"].items():
            assert "****" in val

    def test_refresh_specific_key_found(self, authed_client, mock_secrets):
        resp = authed_client.post("/env/refresh_env_vars", json={
            "key": "STRAPI_API_KEY", "sname": "tenx/env/vars", "run_stage": "dev"
        })
        body = resp.json()
        assert body["success"] is True
        assert body["requested_key"] == "STRAPI_API_KEY"
        assert "****" in body["masked_value"]

    def test_refresh_specific_key_not_found(self, authed_client, mock_secrets):
        resp = authed_client.post("/env/refresh_env_vars", json={
            "key": "NONEXISTENT_KEY", "sname": "tenx/env/vars", "run_stage": "dev"
        })
        body = resp.json()
        assert body["success"] is True
        assert body["masked_value"] == "<not found>"
        assert any("not found" in e for e in body.get("errors", []))

    def test_refresh_with_custom_sname(self, authed_client, mock_secrets):
        resp = authed_client.post("/env/refresh_env_vars", json={
            "sname": "tenx/prod/vars", "run_stage": "prod"
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_refresh_without_auth_rejected(self, client):
        resp = client.post("/env/refresh_env_vars", json={
            "sname": "tenx/env/vars", "run_stage": "dev"
        })
        assert resp.status_code in [401, 403]


# ============================================================================
# Flow 2: Check cache — full pipeline
# ============================================================================

class TestCheckCacheFlow:
    def test_check_cache_metadata(self, authed_client, mock_secrets):
        resp = authed_client.post("/env/check_env_cache", json={
            "sname": "tenx/env/vars", "run_stage": "dev"
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        meta = body["cache_metadata"]
        assert meta["memory_cache_exists"] is True
        assert meta["is_fresh"] is True
        assert meta["cache_age_seconds"] == 120
        assert meta["num_keys"] == 3

    def test_check_cache_sample_keys(self, authed_client, mock_secrets):
        resp = authed_client.post("/env/check_env_cache", json={
            "sname": "tenx/env/vars", "run_stage": "dev"
        })
        body = resp.json()
        assert "sample_keys" in body
        assert "STRAPI_API_KEY" in body["sample_keys"]
        assert "AWS_SES_KEY" in body["sample_keys"]
        assert "DB_PASSWORD" in body["sample_keys"]

    def test_check_specific_key_found(self, authed_client, mock_secrets):
        resp = authed_client.post("/env/check_env_cache", json={
            "key": "AWS_SES_KEY", "sname": "tenx/env/vars", "run_stage": "dev"
        })
        body = resp.json()
        assert body["requested_key"] == "AWS_SES_KEY"
        assert "****" in body["masked_value"]

    def test_check_specific_key_not_found(self, authed_client, mock_secrets):
        resp = authed_client.post("/env/check_env_cache", json={
            "key": "MISSING_KEY", "sname": "tenx/env/vars", "run_stage": "dev"
        })
        body = resp.json()
        assert body["masked_value"] == "<not found>"

    def test_check_cache_without_auth_rejected(self, client):
        resp = client.post("/env/check_env_cache", json={
            "sname": "tenx/env/vars", "run_stage": "dev"
        })
        assert resp.status_code in [401, 403]


# ============================================================================
# Flow 3: Error propagation
# ============================================================================

class TestEnvErrorPropagation:
    def test_aws_failure_on_refresh(self, authed_client):
        with patch("api.routes.env_routes.force_refresh_secrets",
                    side_effect=Exception("AWS Secrets Manager unreachable")):
            resp = authed_client.post("/env/refresh_env_vars", json={
                "sname": "tenx/env/vars", "run_stage": "dev"
            })
            assert resp.status_code == 500
            assert "Failed to refresh secrets" in resp.json()["detail"]

    def test_aws_failure_on_cache_check(self, authed_client):
        with patch("api.routes.env_routes.get_cache_metadata",
                    side_effect=Exception("Cache corrupted")):
            resp = authed_client.post("/env/check_env_cache", json={
                "sname": "tenx/env/vars", "run_stage": "dev"
            })
            assert resp.status_code == 500
            assert "Failed to check cache" in resp.json()["detail"]

    def test_partial_secrets_failure_on_cache_check(self, authed_client):
        """get_all_secrets fails but get_cache_metadata succeeds — graceful degradation."""
        with patch("api.routes.env_routes.get_cache_metadata", return_value={
                "memory_cache_exists": True, "is_fresh": False, "num_keys": 0,
             }), \
             patch("api.routes.env_routes.get_all_secrets",
                    side_effect=Exception("Secrets fetch failed")):
            resp = authed_client.post("/env/check_env_cache", json={
                "sname": "tenx/env/vars", "run_stage": "dev"
            })
            assert resp.status_code == 200
            body = resp.json()
            assert body["success"] is True
            # sample_keys should be absent or empty since get_all_secrets failed
            assert "sample_keys" not in body or body.get("sample_keys") is None


# ============================================================================
# Flow 4: Refresh → Check round-trip
# ============================================================================

class TestRefreshThenCheck:
    def test_refresh_then_check_consistent(self, authed_client, mock_secrets):
        # Refresh
        r1 = authed_client.post("/env/refresh_env_vars", json={
            "sname": "tenx/env/vars", "run_stage": "dev"
        })
        assert r1.status_code == 200
        assert r1.json()["secrets_count"] == 3

        # Check
        r2 = authed_client.post("/env/check_env_cache", json={
            "sname": "tenx/env/vars", "run_stage": "dev"
        })
        assert r2.status_code == 200
        assert r2.json()["cache_metadata"]["memory_cache_exists"] is True
        assert len(r2.json()["sample_keys"]) == 3
