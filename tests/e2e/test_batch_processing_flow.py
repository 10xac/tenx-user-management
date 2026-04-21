"""
E2E tests: Batch processing — full pipeline.
Route → Auth → BatchService → CSV parsing → TraineeService (per row) → Strapi (mocked).
Tests the complete batch upload, background processing, CSV validation, and result compilation.
"""
import pytest
import io
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

from api.core.auth import verify_admin_access
from api.main import app
from api.services.batch_service import BatchService
from api.models.trainee import BatchConfig, BatchTraineeCreate
from tests.e2e.conftest import make_csv


# ============================================================================
# Helpers
# ============================================================================

def _upload(client, csv_bytes, headers=None, **form_fields):
    defaults = {
        "run_stage": "dev",
        "batch": "5",
        "role": "trainee",
        "is_mock": "true",
        "delimiter": ",",
        "encoding": "utf-8",
        "chunk_size": "20",
    }
    defaults.update(form_fields)
    files = {"file": ("trainees.csv", io.BytesIO(csv_bytes), "text/csv")}
    return client.post("/trainee/batch", files=files, data=defaults, headers=headers or {})


def _run_batch_background(csv_bytes, is_mock=True, admin_email="admin@10academy.org",
                          delimiter=",", encoding="utf-8", batch="5"):
    """Directly instantiate and run BatchService.process_batch_trainees for E2E testing."""
    config = BatchConfig(
        run_stage="dev",
        batch=batch,
        role="trainee",
        is_mock=is_mock,
        delimiter=delimiter,
        encoding=encoding,
        chunk_size=20,
        login_url="https://dev-tenx.10academy.org/login",
        admin_email=admin_email,
    )
    batch_create = BatchTraineeCreate(config=config, file_content=csv_bytes)
    service = BatchService(batch_create)
    return service, asyncio.get_event_loop().run_until_complete(service.process_batch_trainees())


# ============================================================================
# Flow 1: Batch route acceptance — returns immediate "processing" response
# ============================================================================

class TestBatchRouteAcceptance:
    def test_batch_accepted_returns_processing(self, authed_client):
        csv = make_csv(["Alice Smith,alice@test.com", "Bob Jones,bob@test.com"])
        resp = _upload(authed_client, csv)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["message"] == "Batch processing started"
        assert body["data"]["status"] == "processing"
        assert body["data"]["batch"] == "5"
        assert body["batch_info"]["admin_email"] == "admin@10academy.org"

    def test_batch_custom_params(self, authed_client):
        csv = make_csv(["Alice Smith,alice@test.com"])
        resp = _upload(authed_client, csv, batch="42", run_stage="prod", role="mentor")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["batch"] == "42"

    def test_batch_login_url_from_origin(self, authed_client):
        csv = make_csv(["Alice Smith,alice@test.com"])
        resp = _upload(authed_client, csv, headers={"Origin": "https://prod-tenx.10academy.org"})
        assert resp.status_code == 200


# ============================================================================
# Flow 2: Background batch processing — full pipeline per record
# ============================================================================

class TestBatchBackgroundProcessing:
    """Run BatchService.process_batch_trainees directly to test full pipeline."""

    def test_all_trainees_created_successfully(self, mock_batch_strapi, mock_ses):
        csv = make_csv([
            "Alice Smith,alice@test.com",
            "Bob Jones,bob@test.com",
            "Carol White,carol@test.com",
        ])
        service, results = _run_batch_background(csv)
        assert results["status"] == "completed"
        assert results["total_processed"] == 3
        assert results["successful"] == 3
        assert results["failed"] == 0
        assert len(results["successful_trainees"]) == 3

    def test_successful_trainee_records_have_correct_data(self, mock_batch_strapi, mock_ses):
        csv = make_csv(["Alice Smith,alice@test.com"])
        service, results = _run_batch_background(csv)
        trainee = results["successful_trainees"][0]
        assert trainee["name"] == "Alice Smith"
        assert trainee["email"] == "alice@test.com"
        assert trainee["status"] == "Success"

    def test_mock_mode_includes_password(self, mock_batch_strapi, mock_ses):
        csv = make_csv(["Alice Smith,alice@test.com"])
        service, results = _run_batch_background(csv, is_mock=True)
        trainee = results["successful_trainees"][0]
        # In mock mode, password should be included
        assert trainee["password"] is not None

    def test_real_mode_excludes_password(self, mock_batch_strapi, mock_ses):
        # For real mode, need to mock requests.post for unconfirmed user
        with patch("api.services.trainee_service.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"user": {"id": "real-user-1"}, "jwt": "jwt"}
            mock_post.return_value = mock_resp

            csv = make_csv(["Alice Smith,alice@test.com"])
            service, results = _run_batch_background(csv, is_mock=False)
            trainee = results["successful_trainees"][0]
            assert trainee["password"] is None

    def test_partial_failure_tracked(self, mock_batch_strapi, mock_ses):
        """When some records fail, results reflect partial_success."""
        cm = mock_batch_strapi["cm"]
        call_count = [0]
        original_create = cm.create_user.return_value

        def fail_second_call(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                raise Exception("Duplicate email")
            return {"data": {"register": {"user": {"id": f"user-{call_count[0]}"}}}}

        cm.create_user.side_effect = fail_second_call
        csv = make_csv([
            "Alice Smith,alice@test.com",
            "Bob Jones,bob@test.com",
            "Carol White,carol@test.com",
        ])
        service, results = _run_batch_background(csv)
        assert results["status"] == "partial_success"
        assert results["successful"] == 2
        assert results["failed"] == 1
        assert len(results["failed_trainees"]) == 1
        assert results["failed_trainees"][0]["email"] == "bob@test.com"

    def test_all_records_fail(self, mock_batch_strapi, mock_ses):
        cm = mock_batch_strapi["cm"]
        cm.create_user.side_effect = Exception("Strapi down")
        csv = make_csv(["Alice,alice@a.com", "Bob,bob@b.com"])
        service, results = _run_batch_background(csv)
        assert results["status"] == "failed"
        assert results["successful"] == 0
        assert results["failed"] == 2

    def test_empty_csv_returns_zero(self, mock_batch_strapi, mock_ses):
        csv = "name,email\n".encode("utf-8")
        service, results = _run_batch_background(csv)
        assert results["total_processed"] == 0
        assert results["successful"] == 0


# ============================================================================
# Flow 3: CSV validation in the batch pipeline
# ============================================================================

class TestBatchCSVValidation:
    def test_missing_required_columns(self, mock_batch_strapi, mock_ses):
        csv = "fullname,mail\nAlice,alice@test.com\n".encode("utf-8")
        service, results = _run_batch_background(csv)
        assert results["status"] == "failed"
        assert "Missing required columns" in results.get("error", "")

    def test_empty_name_in_row_fails(self, mock_batch_strapi, mock_ses):
        csv = make_csv([",alice@test.com", "Bob,bob@test.com"])
        service, results = _run_batch_background(csv)
        assert results["status"] == "failed"
        # CSV validation catches empty fields before processing

    def test_empty_email_in_row_fails(self, mock_batch_strapi, mock_ses):
        csv = make_csv(["Alice Smith,", "Bob,bob@test.com"])
        service, results = _run_batch_background(csv)
        assert results["status"] == "failed"

    def test_semicolon_delimiter(self, mock_batch_strapi, mock_ses):
        csv = "name;email\nAlice;alice@test.com\n".encode("utf-8")
        service, results = _run_batch_background(csv, delimiter=";")
        assert results["total_processed"] == 1
        assert results["successful"] == 1

    def test_csv_with_optional_columns(self, mock_batch_strapi, mock_ses):
        csv = make_csv(
            ["Alice Smith,alice@test.com,Kenya,Female,1990-01-15,No,Dev,Nairobi"],
            header="name,email,nationality,gender,date_of_birth,vulnerable,bio,city_of_residence",
        )
        service, results = _run_batch_background(csv)
        assert results["total_processed"] == 1
        assert results["successful"] == 1

    def test_csv_with_password_column(self, mock_batch_strapi, mock_ses):
        csv = make_csv(
            ["Alice Smith,alice@test.com,MyCustomPwd"],
            header="name,email,password",
        )
        service, results = _run_batch_background(csv)
        assert results["total_processed"] == 1
        assert results["successful"] == 1


# ============================================================================
# Flow 4: Batch result compilation
# ============================================================================

class TestBatchResultCompilation:
    def test_result_includes_metadata(self, mock_batch_strapi, mock_ses):
        csv = make_csv(["Alice,alice@a.com"])
        service, results = _run_batch_background(csv)
        assert results["batch"] == "5"
        assert "timestamp" in results
        assert results["metadata"]["run_stage"] == "dev"
        assert results["metadata"]["role"] == "trainee"

    def test_result_counts_match(self, mock_batch_strapi, mock_ses):
        csv = make_csv(["A,a@a.com", "B,b@b.com", "C,c@c.com"])
        service, results = _run_batch_background(csv)
        assert results["total_processed"] == 3
        assert results["successful"] + results["failed"] == 3
        assert len(results["successful_trainees"]) + len(results["failed_trainees"]) == 3


# ============================================================================
# Flow 5: Notification dispatch after batch
# ============================================================================

class TestBatchNotifications:
    def test_email_notification_sent_after_success(self, mock_batch_strapi, mock_ses):
        csv = make_csv(["Alice,alice@a.com"])
        service, results = _run_batch_background(csv)
        # Email service should have been called
        mock_ses.send_raw_email.assert_called()

    def test_email_skipped_when_no_admin_email(self, mock_batch_strapi, mock_ses):
        csv = make_csv(["Alice,alice@a.com"])
        service, results = _run_batch_background(csv, admin_email=None)
        # No email should be sent
        mock_ses.send_raw_email.assert_not_called()
        mock_ses.send_email.assert_not_called()

    def test_webhook_sent_when_callback_configured(self, mock_batch_strapi, mock_ses, mock_webhook_http):
        config = BatchConfig(
            run_stage="dev", batch="5", role="trainee", is_mock=True,
            delimiter=",", encoding="utf-8", chunk_size=20,
            login_url="https://dev-tenx.10academy.org/login",
            admin_email="admin@10academy.org",
            callback_url="https://webhook.example.com/callback",
        )
        csv = make_csv(["Alice,alice@a.com"])
        batch_create = BatchTraineeCreate(config=config, file_content=csv)
        service = BatchService(batch_create)
        results = asyncio.get_event_loop().run_until_complete(service.process_batch_trainees())
        # Webhook should have been called
        mock_webhook_http.post.assert_called()
        call_kwargs = mock_webhook_http.post.call_args
        assert "https://webhook.example.com/callback" in str(call_kwargs)
