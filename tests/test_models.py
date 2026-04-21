"""
Unit tests for api.models.trainee — Pydantic models and validators.
"""
import pytest
import json
from api.models.trainee import (
    ConfigInfo,
    TraineeInfo,
    TraineeCreate,
    TraineeResponse,
    ErrorDetail,
    BatchConfig,
    BatchTraineeCreate,
    BatchProcessingResponse,
    BatchErrorDetail,
)


# ============================================================================
# ConfigInfo
# ============================================================================

class TestConfigInfo:
    def test_defaults(self):
        cfg = ConfigInfo(run_stage="dev")
        assert cfg.run_stage == "dev"
        assert cfg.batch == ""
        assert cfg.role == "trainee"
        assert cfg.is_mock is False
        assert cfg.group_id == ""
        assert cfg.sheet_id is None
        assert cfg.sheet_name is None
        assert cfg.login_url is None

    def test_custom_values(self):
        cfg = ConfigInfo(
            run_stage="prod",
            batch="10",
            role="admin",
            is_mock=True,
            group_id="42",
            login_url="https://prod.10academy.org/login",
        )
        assert cfg.run_stage == "prod"
        assert cfg.batch == "10"
        assert cfg.role == "admin"
        assert cfg.is_mock is True
        assert cfg.group_id == "42"
        assert cfg.login_url == "https://prod.10academy.org/login"


# ============================================================================
# TraineeInfo — validators
# ============================================================================

class TestTraineeInfo:
    # --- name ---
    def test_valid_name(self):
        t = TraineeInfo(name="John Doe", email="john@example.com")
        assert t.name == "John Doe"

    def test_name_stripped(self):
        t = TraineeInfo(name="  Alice  ", email="alice@example.com")
        assert t.name == "Alice"

    def test_name_empty_raises(self):
        with pytest.raises(Exception):
            TraineeInfo(name="", email="a@b.com")

    def test_name_whitespace_only_raises(self):
        with pytest.raises(Exception):
            TraineeInfo(name="   ", email="a@b.com")

    def test_name_no_letters_raises(self):
        with pytest.raises(Exception):
            TraineeInfo(name="1234", email="a@b.com")

    # --- email ---
    def test_valid_email(self):
        t = TraineeInfo(name="A B", email="Test@Example.COM")
        assert t.email == "test@example.com"

    def test_email_stripped_and_lowered(self):
        t = TraineeInfo(name="A B", email="  JOE@TEST.IO  ")
        assert t.email == "joe@test.io"

    def test_email_invalid_format_raises(self):
        with pytest.raises(Exception):
            TraineeInfo(name="A B", email="not-an-email")

    def test_email_empty_raises(self):
        with pytest.raises(Exception):
            TraineeInfo(name="A B", email="")

    # --- status ---
    def test_status_default(self):
        t = TraineeInfo(name="X Y", email="x@y.com")
        assert t.status == "Accepted"

    def test_status_empty_falls_back(self):
        t = TraineeInfo(name="X Y", email="x@y.com", status="")
        assert t.status == "Accepted"

    def test_status_custom(self):
        t = TraineeInfo(name="X Y", email="x@y.com", status="Pending")
        assert t.status == "Pending"

    # --- nationality / gender / vulnerable / city_of_residence / bio ---
    def test_optional_strings_stripped(self):
        t = TraineeInfo(
            name="X Y",
            email="x@y.com",
            nationality="  Kenya ",
            gender=" Male ",
            vulnerable=" No ",
            city_of_residence="  Nairobi ",
            bio=" Some bio ",
        )
        assert t.nationality == "Kenya"
        assert t.gender == "Male"
        assert t.vulnerable == "No"
        assert t.city_of_residence == "Nairobi"
        assert t.bio == "Some bio"

    def test_optional_strings_empty(self):
        t = TraineeInfo(name="X Y", email="x@y.com", nationality="", gender="")
        assert t.nationality == ""
        assert t.gender == ""

    # --- date_of_birth ---
    def test_date_of_birth_none(self):
        t = TraineeInfo(name="X Y", email="x@y.com", date_of_birth=None)
        assert t.date_of_birth is None

    def test_date_of_birth_empty_string(self):
        t = TraineeInfo(name="X Y", email="x@y.com", date_of_birth="")
        assert t.date_of_birth is None

    def test_date_of_birth_valid(self):
        t = TraineeInfo(name="X Y", email="x@y.com", date_of_birth="1990-05-15")
        assert t.date_of_birth == "1990-05-15"

    # --- other_info ---
    def test_other_info_dict(self):
        t = TraineeInfo(name="X Y", email="x@y.com", other_info={"key": "val"})
        assert t.other_info == {"key": "val"}

    def test_other_info_json_string(self):
        t = TraineeInfo(name="X Y", email="x@y.com", other_info='{"a": 1}')
        assert t.other_info == {"a": 1}

    def test_other_info_invalid_json_string(self):
        t = TraineeInfo(name="X Y", email="x@y.com", other_info="not json")
        assert t.other_info == {}

    def test_other_info_none(self):
        t = TraineeInfo(name="X Y", email="x@y.com", other_info=None)
        assert t.other_info == {}


# ============================================================================
# TraineeCreate
# ============================================================================

class TestTraineeCreate:
    def test_valid_creation(self, valid_trainee_payload):
        tc = TraineeCreate(**valid_trainee_payload)
        assert tc.config.run_stage == "dev"
        assert tc.trainee.name == "John Doe"
        assert tc.trainee.email == "john.doe@example.com"


# ============================================================================
# ErrorDetail
# ============================================================================

class TestErrorDetail:
    def test_to_dict(self):
        e = ErrorDetail(
            error_type="TEST",
            error_message="msg",
            error_location="loc",
            error_data={"k": "v"},
        )
        d = e.to_dict()
        assert d["error_type"] == "TEST"
        assert d["error_message"] == "msg"
        assert d["error_location"] == "loc"
        assert d["error_data"] == {"k": "v"}


# ============================================================================
# TraineeResponse
# ============================================================================

class TestTraineeResponse:
    def test_success_response(self):
        resp = TraineeResponse.success_response(
            message="ok", data={"alluser_id": "1"}
        )
        assert resp["success"] is True
        assert resp["message"] == "ok"
        assert resp["data"]["alluser_id"] == "1"

    def test_error_response(self):
        resp = TraineeResponse.error_response(
            error_type="FAIL",
            error_message="bad",
            error_location="here",
            error_data={"x": 1},
        )
        assert resp["success"] is False
        assert resp["error"]["error_type"] == "FAIL"

    def test_to_dict_includes_optional_fields(self):
        r = TraineeResponse(
            success=True,
            message="ok",
            alluser_id="123",
            profile={"id": "1"},
            trainee={"id": "2"},
            batch_info={"batch": "5"},
        )
        d = r.to_dict()
        assert d["alluser_id"] == "123"
        assert d["profile"]["id"] == "1"
        assert d["trainee"]["id"] == "2"
        assert d["batch_info"]["batch"] == "5"

    def test_to_dict_excludes_none_fields(self):
        r = TraineeResponse(success=True, message="ok")
        d = r.to_dict()
        assert "alluser_id" not in d
        assert "profile" not in d
        assert "error" not in d


# ============================================================================
# BatchConfig
# ============================================================================

class TestBatchConfig:
    def test_defaults(self):
        bc = BatchConfig(run_stage="dev", login_url="https://x.com/login")
        assert bc.role == "trainee"
        assert bc.delimiter == ","
        assert bc.encoding == "utf-8"
        assert bc.chunk_size == 20
        assert bc.is_mock is False
        assert bc.password_option == "default"
        assert bc.default_password == "10@Academy"
        assert bc.webhook_retry_count == 3
        assert bc.webhook_retry_delay == 5

    def test_required_columns(self):
        bc = BatchConfig(run_stage="dev", login_url="https://x.com/login")
        assert "name" in bc.required_columns
        assert "email" in bc.required_columns


# ============================================================================
# BatchProcessingResponse
# ============================================================================

class TestBatchProcessingResponse:
    def test_success_response(self):
        data = {
            "total_processed": 10,
            "successful": 8,
            "failed": 2,
            "failed_trainees": [{"name": "X"}],
            "successful_trainees": [{"name": "Y"}],
            "error_details": [],
        }
        resp = BatchProcessingResponse.success_response(
            message="done", data=data, batch_info={"batch": "5"}
        )
        assert resp["success"] is True
        assert resp["total_processed"] == 10
        assert resp["successful"] == 8
        assert resp["failed"] == 2

    def test_error_response(self):
        resp = BatchProcessingResponse.error_response(
            error_type="FAIL",
            error_message="nope",
            error_location="batch",
            error_data={"name": "bad"},
            batch_info={"batch": "1"},
        )
        assert resp["success"] is False
        assert resp["error"]["error_type"] == "FAIL"
        assert len(resp["failed_trainees"]) == 1

    def test_to_dict(self):
        r = BatchProcessingResponse(
            success=True,
            message="ok",
            total_processed=5,
            successful=5,
            failed=0,
        )
        d = r.to_dict()
        assert d["total_processed"] == 5
        assert d["successful"] == 5
