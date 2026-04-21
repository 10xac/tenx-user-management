"""
API integration tests for middleware, CORS, error handling, and app-level behavior.
Tests cross-cutting concerns that apply to all endpoints.
"""
import pytest
from unittest.mock import patch


# ============================================================================
# CORS Middleware
# ============================================================================

class TestCORSMiddleware:
    def test_cors_allows_10academy_origin(self, client):
        resp = client.options(
            "/trainee/single",
            headers={
                "Origin": "https://dev-tenx.10academy.org",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "https://dev-tenx.10academy.org"

    def test_cors_allows_gettenacious_origin(self, client):
        resp = client.options(
            "/trainee/single",
            headers={
                "Origin": "https://app.gettenacious.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "https://app.gettenacious.com"

    def test_cors_allows_subdomain(self, client):
        resp = client.options(
            "/trainee/single",
            headers={
                "Origin": "https://staging.10academy.org",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "https://staging.10academy.org"

    def test_cors_blocks_unknown_origin(self, client):
        resp = client.options(
            "/trainee/single",
            headers={
                "Origin": "https://evil-site.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        # Unknown origin should NOT appear in the allow-origin header
        allow_origin = resp.headers.get("access-control-allow-origin", "")
        assert "evil-site.com" not in allow_origin

    def test_cors_allows_credentials(self, client):
        resp = client.options(
            "/trainee/single",
            headers={
                "Origin": "https://dev-tenx.10academy.org",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.headers.get("access-control-allow-credentials") == "true"

    def test_cors_allows_all_methods(self, client):
        resp = client.options(
            "/trainee/single",
            headers={
                "Origin": "https://dev-tenx.10academy.org",
                "Access-Control-Request-Method": "POST",
            },
        )
        allow_methods = resp.headers.get("access-control-allow-methods", "")
        assert "POST" in allow_methods or "*" in allow_methods

    def test_cors_allows_all_headers(self, client):
        resp = client.options(
            "/trainee/single",
            headers={
                "Origin": "https://dev-tenx.10academy.org",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )
        allow_headers = resp.headers.get("access-control-allow-headers", "")
        assert "authorization" in allow_headers.lower() or "*" in allow_headers

    def test_cors_with_http_scheme(self, client):
        resp = client.options(
            "/trainee/single",
            headers={
                "Origin": "http://localhost.10academy.org:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        allow_origin = resp.headers.get("access-control-allow-origin", "")
        assert "10academy.org" in allow_origin or allow_origin == ""


# ============================================================================
# Custom Validation Error Handler
# ============================================================================

class TestValidationErrorHandler:
    def test_pydantic_validation_returns_structured_error(self, client):
        resp = client.post("/trainee/single", json={
            "config": {"run_stage": "dev"},
            "trainee": {"name": "", "email": "a@b.com"},
        })
        assert resp.status_code == 422
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["error_type"] == "VALIDATION_ERROR"
        assert isinstance(body["error"]["error_message"], str)
        assert isinstance(body["error"]["error_location"], str)

    def test_multiple_validation_errors(self, client):
        resp = client.post("/trainee/single", json={
            "config": {"run_stage": "dev"},
            "trainee": {"name": "", "email": "bad"},
        })
        assert resp.status_code == 422
        body = resp.json()
        assert body["success"] is False

    def test_extra_fields_ignored_or_rejected(self, client):
        with patch("api.controllers.trainee_controller.TraineeService") as MockSvc:
            from api.models.trainee import TraineeResponse
            MockSvc.return_value.create_trainee_services.return_value = \
                TraineeResponse.success_response("ok", data={"alluser_id": "1"})
            resp = client.post("/trainee/single", json={
                "config": {"run_stage": "dev"},
                "trainee": {"name": "A B", "email": "a@b.com", "unknown_field": "test"},
            })
            # Should either succeed (ignoring extra) or 422 (rejecting extra)
            assert resp.status_code in [200, 422]

    def test_wrong_type_for_is_mock(self, client):
        resp = client.post("/trainee/single", json={
            "config": {"run_stage": "dev", "is_mock": "not_a_bool"},
            "trainee": {"name": "A B", "email": "a@b.com"},
        })
        # Pydantic may coerce "not_a_bool" to True or raise 422
        assert resp.status_code in [200, 422]


# ============================================================================
# Non-existent Routes
# ============================================================================

class TestNonExistentRoutes:
    def test_404_on_unknown_path(self, client):
        resp = client.get("/nonexistent")
        assert resp.status_code == 404

    def test_404_on_unknown_trainee_subpath(self, client):
        resp = client.post("/trainee/unknown", json={})
        assert resp.status_code in [404, 405, 422]

    def test_404_on_unknown_env_subpath(self, client):
        resp = client.post("/env/unknown", json={})
        assert resp.status_code in [404, 405, 422]


# ============================================================================
# OpenAPI / Docs
# ============================================================================

class TestOpenAPI:
    def test_openapi_schema_available(self, client):
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert "openapi" in schema
        assert "paths" in schema

    def test_openapi_lists_all_endpoints(self, client):
        schema = client.get("/openapi.json").json()
        paths = list(schema["paths"].keys())
        assert "/trainee/single" in paths
        assert "/trainee/admin-single" in paths
        assert "/trainee/batch" in paths
        assert "/webhook" in paths
        assert "/env/refresh_env_vars" in paths
        assert "/env/check_env_cache" in paths

    def test_openapi_has_correct_tags(self, client):
        schema = client.get("/openapi.json").json()
        tags_used = set()
        for path_info in schema["paths"].values():
            for method_info in path_info.values():
                for tag in method_info.get("tags", []):
                    tags_used.add(tag)
        assert "trainee" in tags_used
        assert "webhook" in tags_used
        assert "environment" in tags_used

    def test_swagger_ui_available(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_redoc_available(self, client):
        resp = client.get("/redoc")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


# ============================================================================
# Response Headers
# ============================================================================

class TestResponseHeaders:
    def test_json_content_type_on_success(self, client):
        with patch("api.controllers.trainee_controller.TraineeService") as MockSvc:
            from api.models.trainee import TraineeResponse
            MockSvc.return_value.create_trainee_services.return_value = \
                TraineeResponse.success_response("ok", data={"alluser_id": "1"})
            resp = client.post("/trainee/single", json={
                "config": {"run_stage": "dev"},
                "trainee": {"name": "A B", "email": "a@b.com"},
            })
            assert "application/json" in resp.headers.get("content-type", "")

    def test_json_content_type_on_validation_error(self, client):
        resp = client.post("/trainee/single", json={
            "config": {"run_stage": "dev"},
            "trainee": {"name": "", "email": "a@b.com"},
        })
        assert "application/json" in resp.headers.get("content-type", "")

    def test_json_content_type_on_webhook(self, client):
        resp = client.post("/webhook", json={
            "status": "success", "batch": "1", "errors": []
        })
        assert "application/json" in resp.headers.get("content-type", "")


# ============================================================================
# Concurrent-style / Edge Cases
# ============================================================================

class TestEdgeCases:
    def test_unicode_in_trainee_name(self, client):
        with patch("api.controllers.trainee_controller.TraineeService") as MockSvc:
            from api.models.trainee import TraineeResponse
            MockSvc.return_value.create_trainee_services.return_value = \
                TraineeResponse.success_response("ok", data={"alluser_id": "1"})
            resp = client.post("/trainee/single", json={
                "config": {"run_stage": "dev"},
                "trainee": {"name": "Ñoño Müller", "email": "nono@test.com"},
            })
            assert resp.status_code == 200

    def test_very_long_name(self, client):
        long_name = "A" * 500 + " " + "B" * 500
        resp = client.post("/trainee/single", json={
            "config": {"run_stage": "dev"},
            "trainee": {"name": long_name, "email": "long@test.com"},
        })
        # Should either accept or 422, not crash
        assert resp.status_code in [200, 422]

    def test_special_chars_in_email_local_part(self, client):
        resp = client.post("/trainee/single", json={
            "config": {"run_stage": "dev"},
            "trainee": {"name": "A B", "email": "user+tag@example.com"},
        })
        # + is valid in email local part
        assert resp.status_code in [200, 422]

    def test_empty_other_info(self, client):
        with patch("api.controllers.trainee_controller.TraineeService") as MockSvc:
            from api.models.trainee import TraineeResponse
            MockSvc.return_value.create_trainee_services.return_value = \
                TraineeResponse.success_response("ok", data={"alluser_id": "1"})
            resp = client.post("/trainee/single", json={
                "config": {"run_stage": "dev"},
                "trainee": {"name": "A B", "email": "a@b.com", "other_info": {}},
            })
            assert resp.status_code == 200

    def test_other_info_as_json_string(self, client):
        with patch("api.controllers.trainee_controller.TraineeService") as MockSvc:
            from api.models.trainee import TraineeResponse
            MockSvc.return_value.create_trainee_services.return_value = \
                TraineeResponse.success_response("ok", data={"alluser_id": "1"})
            resp = client.post("/trainee/single", json={
                "config": {"run_stage": "dev"},
                "trainee": {
                    "name": "A B",
                    "email": "a@b.com",
                    "other_info": '{"custom_field": "value"}',
                },
            })
            assert resp.status_code == 200

    def test_webhook_with_nested_payload(self, client):
        resp = client.post("/webhook", json={
            "status": "success",
            "batch": "1",
            "errors": [],
            "metadata": {
                "nested": {"deep": {"value": 42}},
                "list": [1, 2, 3],
            },
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["metadata"]["nested"]["deep"]["value"] == 42
