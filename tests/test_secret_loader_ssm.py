"""utils secret.get_ssm_secret reads SSM first and keeps returning SecretString text."""

import hashlib
import json
import sys
from pathlib import Path

import boto3
import pytest
from botocore.stub import Stubber

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'utils'))

import secret as legacy  # noqa: E402  (loaded top-level, shares tenx_secret_source below)
import tenx_secret_source as tss  # noqa: E402


def _client(service):
    return boto3.client(service, region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")


@pytest.fixture
def stubs(monkeypatch):
    monkeypatch.delenv("TENX_SECRET_SOURCE", raising=False)
    tss._logged_sources.clear()
    clients = {"ssm": _client("ssm"), "secretsmanager": _client("secretsmanager")}
    monkeypatch.setattr(tss, "_client", lambda service, region: clients[service])
    with Stubber(clients["ssm"]) as ssm, Stubber(clients["secretsmanager"]) as sm:
        yield ssm, sm


def test_get_ssm_secret_prefers_ssm_tree(stubs):
    ssm, sm = stubs
    original = {"TENX_PROD_STRAPI_TOKEN": "tok", "STRAPI_PGDB_PORT": 5432}
    canon = json.dumps(original, sort_keys=True, separators=(",", ":"))
    meta = {"source": "tenx/env/vars", "format": "json", "keys": 2,
            "sha256": hashlib.sha256(canon.encode()).hexdigest()[:10]}
    ssm.add_response(
        "get_parameters_by_path",
        {"Parameters": [
            {"Name": "/tenx/env/vars/TENX_PROD_STRAPI_TOKEN", "Value": "tok"},
            {"Name": "/tenx/env/vars/STRAPI_PGDB_PORT", "Value": "5432"},
            {"Name": "/tenx/env/vars/_meta", "Value": json.dumps(meta)},
        ]},
        {"Path": "/tenx/env/vars/", "Recursive": True, "WithDecryption": True},
    )
    text = legacy.get_ssm_secret("tenx/env/vars")
    assert isinstance(text, str)
    assert json.loads(text) == original
    sm.assert_no_pending_responses()


def test_get_ssm_secret_falls_back_to_secretsmanager(stubs):
    ssm, sm = stubs
    ssm.add_response("get_parameters_by_path", {"Parameters": []},
                     {"Path": "/gspread/config/", "Recursive": True, "WithDecryption": True})
    sm.add_response("get_secret_value", {"SecretString": '{"client_id": "123"}'}, {"SecretId": "gspread/config"})
    assert legacy.get_ssm_secret("gspread/config") == '{"client_id": "123"}'
