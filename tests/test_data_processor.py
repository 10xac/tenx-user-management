"""
Unit tests for api.services.data_processor.DataProcessor.
"""
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch

from api.models.trainee import ConfigInfo, TraineeInfo
from api.services.data_processor import DataProcessor


@pytest.fixture
def config():
    return ConfigInfo(run_stage="dev", batch="5", role="trainee", group_id="10")


@pytest.fixture
def processor(config):
    return DataProcessor(config)


# ============================================================================
# process_single_trainee
# ============================================================================

class TestProcessSingleTrainee:
    def test_basic_processing(self, processor):
        trainee = TraineeInfo(
            name="john doe",
            email="John@Example.COM",
            password="pass123",
            nationality="Kenya",
            gender="Male",
            status="Accepted",
        )
        result = processor.process_single_trainee(trainee)
        assert result["name"] == "John Doe"  # title-cased
        assert result["email"] == "john@example.com"  # lowered
        assert result["password"] == "pass123"
        assert result["nationality"] == "Kenya"
        assert result["gender"] == "Male"
        assert result["role"] == "trainee"

    def test_password_defaults_to_email(self, processor):
        trainee = TraineeInfo(name="A B", email="a@b.com", password=None)
        result = processor.process_single_trainee(trainee)
        assert result["password"] == "a@b.com"

    def test_empty_password_defaults_to_email(self, processor):
        trainee = TraineeInfo(name="A B", email="a@b.com", password="")
        result = processor.process_single_trainee(trainee)
        assert result["password"] == "a@b.com"

    def test_batch_id_from_config(self, processor):
        trainee = TraineeInfo(name="A B", email="a@b.com")
        result = processor.process_single_trainee(trainee)
        assert result["batch_id"] == ["5"]

    def test_batch_id_empty_when_no_batch(self):
        config = ConfigInfo(run_stage="dev", batch="", role="trainee")
        proc = DataProcessor(config)
        trainee = TraineeInfo(name="A B", email="a@b.com")
        result = proc.process_single_trainee(trainee)
        assert result["batch_id"] == []

    def test_groups_from_config(self, processor):
        trainee = TraineeInfo(name="A B", email="a@b.com")
        result = processor.process_single_trainee(trainee)
        assert result["groups"] == ["10"]

    def test_groups_empty_when_no_group(self):
        config = ConfigInfo(run_stage="dev", batch="5", group_id="")
        proc = DataProcessor(config)
        trainee = TraineeInfo(name="A B", email="a@b.com")
        result = proc.process_single_trainee(trainee)
        assert result["groups"] == []

    def test_name_cleans_special_chars(self, processor):
        trainee = TraineeInfo(name="John-Paul.Smith  Jr", email="j@s.com")
        result = processor.process_single_trainee(trainee)
        # hyphens and dots removed, double spaces collapsed
        assert "-" not in result["name"]
        assert "." not in result["name"]

    def test_date_of_birth_valid(self, processor):
        trainee = TraineeInfo(name="A B", email="a@b.com", date_of_birth="1990-06-15")
        result = processor.process_single_trainee(trainee)
        assert result["date_of_birth"] == "1990-06-15"

    def test_date_of_birth_none(self, processor):
        trainee = TraineeInfo(name="A B", email="a@b.com", date_of_birth=None)
        result = processor.process_single_trainee(trainee)
        assert result["date_of_birth"] is None

    def test_date_of_birth_invalid_format(self, processor):
        trainee = TraineeInfo(name="A B", email="a@b.com", date_of_birth="not-a-date")
        result = processor.process_single_trainee(trainee)
        assert result["date_of_birth"] is None

    def test_status_default(self, processor):
        trainee = TraineeInfo(name="A B", email="a@b.com")
        result = processor.process_single_trainee(trainee)
        assert result["status"] == "Accepted"

    def test_other_info_dict(self, processor):
        trainee = TraineeInfo(name="A B", email="a@b.com", other_info={"key": "val"})
        result = processor.process_single_trainee(trainee)
        assert result["other_info"] == {"key": "val"}

    def test_other_info_filters_additional_prop(self, processor):
        trainee = TraineeInfo(
            name="A B",
            email="a@b.com",
            other_info={"additionalProp1": {}, "real_key": "val"},
        )
        result = processor.process_single_trainee(trainee)
        assert "additionalProp1" not in result["other_info"]
        assert result["other_info"]["real_key"] == "val"

    def test_bio_and_city(self, processor):
        trainee = TraineeInfo(
            name="A B", email="a@b.com", bio="My bio", city_of_residence="Nairobi"
        )
        result = processor.process_single_trainee(trainee)
        assert result["bio"] == "My bio"
        assert result["city_of_residence"] == "Nairobi"

    def test_role_empty_defaults_to_trainee(self):
        config = ConfigInfo(run_stage="dev", batch="5", role="")
        proc = DataProcessor(config)
        trainee = TraineeInfo(name="A B", email="a@b.com")
        result = proc.process_single_trainee(trainee)
        assert result["role"] == "trainee"


# ============================================================================
# change_name_fullname (static)
# ============================================================================

class TestChangeNameFullname:
    def test_single_word_first_name(self):
        row = pd.Series({"firstname": "john", "familyname": "doe smith"})
        result = DataProcessor.change_name_fullname(row)
        assert result == "John Doe"

    def test_multi_word_first_name(self):
        row = pd.Series({"firstname": "john paul", "familyname": "doe"})
        result = DataProcessor.change_name_fullname(row)
        assert result == "John Paul"


# ============================================================================
# process_dataframe
# ============================================================================

class TestProcessDataframe:
    def test_rename_and_clean(self, processor):
        df = pd.DataFrame(
            {
                "Full Name": ["  john doe  ", "ALICE SMITH"],
                "Email": [" John@X.com ", " ALICE@Y.COM "],
            }
        )
        result = processor.process_dataframe(df)
        assert "Name" in result.columns
        assert result.iloc[0]["Name"] == "John Doe"
        assert result.iloc[0]["Email"] == "john@x.com"
        assert (result["Batch"] == "5").all()


# ============================================================================
# find_duplicates
# ============================================================================

class TestFindDuplicates:
    def test_no_duplicates(self, processor):
        df = pd.DataFrame(
            {"name": ["A", "B"], "email": ["a@x.com", "b@x.com"]}
        )
        result = processor.find_duplicates(df)
        assert result["found"] is False
        assert result["count"] == 0

    def test_with_duplicates(self, processor):
        df = pd.DataFrame(
            {
                "name": ["Alice", "alice", "Bob"],
                "email": ["alice@x.com", "ALICE@x.com", "bob@x.com"],
            }
        )
        result = processor.find_duplicates(df)
        assert result["found"] is True
        assert result["count"] == 2
