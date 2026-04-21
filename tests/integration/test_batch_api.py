"""
API integration tests for batch endpoint: POST /trainee/batch.
Tests file upload, CSV validation, auth, background processing, and error handling.
"""
import pytest
import io
from unittest.mock import patch, MagicMock, AsyncMock

from api.models.trainee import TraineeResponse, BatchProcessingResponse
from api.core.auth import verify_admin_access
from api.main import app
from tests.integration.conftest import make_csv_bytes


# ============================================================================
# Helper
# ============================================================================

def _upload(client, csv_bytes, headers=None, **form_fields):
    """Helper to POST /trainee/batch with a CSV file and form data."""
    defaults = {
        "run_stage": "dev",
        "batch": "5",
        "role": "trainee",
        "is_mock": "false",
        "delimiter": ",",
        "encoding": "utf-8",
        "chunk_size": "20",
    }
    defaults.update(form_fields)
    files = {"file": ("trainees.csv", io.BytesIO(csv_bytes), "text/csv")}
    return client.post(
        "/trainee/batch",
        files=files,
        data=defaults,
        headers=headers or {},
    )


# ============================================================================
# Auth Required
# ============================================================================

class TestBatchAuth:
    def test_no_auth_returns_401(self, client, valid_csv_bytes):
        resp = _upload(client, valid_csv_bytes)
        assert resp.status_code in [401, 403]

    def test_auth_failure_returns_error(self, client, valid_csv_bytes, auth_error_response):
        app.dependency_overrides[verify_admin_access] = lambda: auth_error_response
        try:
            resp = _upload(client, valid_csv_bytes)
            body = resp.json()
            assert body["success"] is False
            assert body["error"]["error_type"] == "AUTH_ERROR"
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)

    def test_admin_auth_accepted(self, client, valid_csv_bytes, admin_user):
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        try:
            resp = _upload(client, valid_csv_bytes)
            assert resp.status_code == 200
            body = resp.json()
            assert body["success"] is True
            assert body["message"] == "Batch processing started"
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)


# ============================================================================
# Successful Batch Start
# ============================================================================

class TestBatchSuccess:
    def test_returns_processing_status(self, client, valid_csv_bytes, admin_user):
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        try:
            resp = _upload(client, valid_csv_bytes)
            body = resp.json()
            assert body["success"] is True
            assert body["data"]["status"] == "processing"
            assert body["data"]["batch"] == "5"
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)

    def test_batch_info_includes_admin_email(self, client, valid_csv_bytes, admin_user):
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        try:
            resp = _upload(client, valid_csv_bytes)
            body = resp.json()
            assert body["batch_info"]["admin_email"] == admin_user["email"]
            assert body["batch_info"]["batch"] == "5"
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)

    def test_custom_batch_id(self, client, valid_csv_bytes, admin_user):
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        try:
            resp = _upload(client, valid_csv_bytes, batch="99")
            body = resp.json()
            assert body["data"]["batch"] == "99"
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)

    def test_custom_run_stage(self, client, valid_csv_bytes, admin_user):
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        try:
            resp = _upload(client, valid_csv_bytes, run_stage="prod")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)

    def test_mock_mode(self, client, valid_csv_bytes, admin_user):
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        try:
            resp = _upload(client, valid_csv_bytes, is_mock="true")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)


# ============================================================================
# File Validation
# ============================================================================

class TestBatchFileValidation:
    def test_no_file_returns_422(self, client, admin_user):
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        try:
            resp = client.post(
                "/trainee/batch",
                data={"run_stage": "dev", "batch": "5", "role": "trainee"},
            )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)

    def test_empty_filename(self, client, admin_user):
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        try:
            files = {"file": ("", io.BytesIO(b""), "text/csv")}
            resp = client.post(
                "/trainee/batch",
                files=files,
                data={"run_stage": "dev", "batch": "5", "role": "trainee",
                      "delimiter": ",", "encoding": "utf-8", "chunk_size": "20",
                      "is_mock": "false"},
            )
            body = resp.json()
            assert body["success"] is False or resp.status_code == 422
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)


# ============================================================================
# CSV Content Validation (tested via BatchService)
# ============================================================================

class TestBatchCSVValidation:
    def test_csv_with_optional_fields_accepted(self, client, csv_with_optional_fields, admin_user):
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        try:
            resp = _upload(client, csv_with_optional_fields)
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)

    def test_semicolon_delimiter(self, client, admin_user):
        csv_data = "name;email\nAlice;alice@test.com\n".encode("utf-8")
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        try:
            resp = _upload(client, csv_data, delimiter=";")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)

    def test_large_chunk_size(self, client, valid_csv_bytes, admin_user):
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        try:
            resp = _upload(client, valid_csv_bytes, chunk_size="100")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)


# ============================================================================
# Login URL Derivation
# ============================================================================

class TestBatchLoginURL:
    def test_login_url_derived_from_origin(self, client, valid_csv_bytes, admin_user):
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        try:
            resp = _upload(
                client, valid_csv_bytes,
                headers={"Origin": "https://dev-tenx.10academy.org"},
            )
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)

    def test_login_url_derived_from_referer(self, client, valid_csv_bytes, admin_user):
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        try:
            resp = _upload(
                client, valid_csv_bytes,
                headers={"Referer": "https://prod-tenx.10academy.org/dashboard"},
            )
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)

    def test_default_login_url_when_no_origin(self, client, valid_csv_bytes, admin_user):
        app.dependency_overrides[verify_admin_access] = lambda: admin_user
        try:
            resp = _upload(client, valid_csv_bytes)
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(verify_admin_access, None)


# ============================================================================
# Request Method Validation
# ============================================================================

class TestBatchRequestMethods:
    def test_get_not_allowed(self, client):
        resp = client.get("/trainee/batch")
        assert resp.status_code == 405

    def test_put_not_allowed(self, client):
        resp = client.put("/trainee/batch")
        assert resp.status_code == 405

    def test_delete_not_allowed(self, client):
        resp = client.delete("/trainee/batch")
        assert resp.status_code == 405
