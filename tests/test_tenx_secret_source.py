"""Unit tests for tenx_secret_source (botocore Stubber; no live AWS)."""

import hashlib
import json
import logging

import boto3
import pytest
from botocore.stub import Stubber

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'utils'))

import tenx_secret_source as tss  # noqa: E402

NAME = "tenx/env/vars"
PREFIX = "/tenx/env/vars/"


def _canon_hash(obj):
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]


def _meta(obj, fmt="json", **extra):
    meta = {"source": NAME, "format": fmt, "sha256": _canon_hash(obj)}
    if fmt == "json":
        meta["keys"] = len(obj)
    meta.update(extra)
    return json.dumps(meta)


def _param(key, value):
    return {"Name": PREFIX + key, "Value": value, "Type": "SecureString"}


def _clients():
    ssm = boto3.client("ssm", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
    sm = boto3.client("secretsmanager", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
    return ssm, sm, Stubber(ssm), Stubber(sm)


def _expect_tree(stub, pages):
    for i, params in enumerate(pages):
        expected = {"Path": PREFIX, "Recursive": True, "WithDecryption": True}
        if i:
            expected["NextToken"] = f"t{i}"
        response = {"Parameters": params}
        if i < len(pages) - 1:
            response["NextToken"] = f"t{i + 1}"
        stub.add_response("get_parameters_by_path", response, expected)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv("TENX_SECRET_SOURCE", raising=False)
    tss._logged_sources.clear()


def test_auto_reads_ssm_tree_across_pages():
    original = {"API_KEY": "sk-1", "PORT": 5432, "NESTED": {"a": 1}}
    ssm, sm, s_ssm, s_sm = _clients()
    _expect_tree(
        s_ssm,
        [
            [_param("API_KEY", "sk-1"), _param("PORT", "5432")],
            [_param("NESTED", '{"a": 1}')],
            [{"Name": PREFIX + "_meta", "Value": _meta(original), "Type": "String"}],
        ],
    )
    with s_ssm, s_sm:
        assert json.loads(tss.get_secret_string(NAME, ssm_client=ssm, sm_client=sm)) == original
    s_ssm.assert_no_pending_responses()


def test_ambiguous_mixed_types_without_json_keys_fall_back():
    # A real int next to a numeric string: neither reading matches the hash, so
    # auto refuses to guess and reads Secrets Manager instead.
    original = {"PORT": 5432, "client_id": "1234567890"}
    ssm, sm, s_ssm, s_sm = _clients()
    params = [_param("PORT", "5432"), _param("client_id", "1234567890")]
    _expect_tree(s_ssm, [params + [{"Name": PREFIX + "_meta", "Value": _meta(original)}]])
    s_sm.add_response("get_secret_value", {"SecretString": json.dumps(original)}, {"SecretId": NAME})
    with s_ssm, s_sm:
        assert tss.get_secret_dict(NAME, ssm_client=ssm, sm_client=sm) == original
    s_sm.assert_no_pending_responses()


def test_auto_ssm_all_strings_keeps_numeric_strings():
    original = {"API_KEY": "sk-1", "DB_PORT": "5432", "FLAG": "true"}
    ssm, sm, s_ssm, s_sm = _clients()
    _expect_tree(
        s_ssm,
        [[_param(k, v) for k, v in original.items()] + [{"Name": PREFIX + "_meta", "Value": _meta(original)}]],
    )
    with s_ssm, s_sm:
        text = tss.get_secret_string(NAME, ssm_client=ssm, sm_client=sm)
    assert json.loads(text) == original
    s_sm.assert_no_pending_responses()


def test_auto_ssm_decodes_non_string_values():
    original = {"STRAPI_PGDB_PORT": 5432, "openai/x": {"keys": ["a"]}, "NAME": "db"}
    ssm, sm, s_ssm, s_sm = _clients()
    params = [_param("STRAPI_PGDB_PORT", "5432"), _param("openai/x", '{"keys":["a"]}'), _param("NAME", "db")]
    _expect_tree(s_ssm, [params + [{"Name": PREFIX + "_meta", "Value": _meta(original)}]])
    with s_ssm:
        assert tss.get_secret_dict(NAME, ssm_client=ssm, sm_client=sm) == original


def test_json_keys_in_meta_resolves_mixed_types():
    original = {"PORT": 5432, "client_id": "1234567890"}
    ssm, sm, s_ssm, _ = _clients()
    params = [_param("PORT", "5432"), _param("client_id", "1234567890")]
    meta = _meta(original, json_keys=["PORT"])
    _expect_tree(s_ssm, [params + [{"Name": PREFIX + "_meta", "Value": meta}]])
    with s_ssm:
        assert tss.get_secret_dict(NAME, ssm_client=ssm, sm_client=sm) == original


def test_plain_secret_returns_value_text():
    ssm, sm, s_ssm, _ = _clients()
    raw = "KEY=value\nOTHER=1\n"
    _expect_tree(s_ssm, [[_param("_value", raw), {"Name": PREFIX + "_meta", "Value": _meta(raw, fmt="plain")}]])
    with s_ssm:
        assert tss.get_secret_string(NAME, ssm_client=ssm, sm_client=sm) == raw


def test_auto_falls_back_to_secretsmanager_without_meta(caplog):
    ssm, sm, s_ssm, s_sm = _clients()
    _expect_tree(s_ssm, [[]])
    s_sm.add_response("get_secret_value", {"SecretString": '{"A": "1"}'}, {"SecretId": NAME})
    caplog.set_level(logging.INFO, logger="tenx.secret_source")
    with s_ssm, s_sm:
        assert tss.get_secret_string(NAME, ssm_client=ssm, sm_client=sm) == '{"A": "1"}'
    assert "secretsmanager" in caplog.text
    assert '"1"' not in caplog.text  # never log values


def test_auto_falls_back_on_incomplete_tree():
    original = {"A": "1", "B": "2"}
    ssm, sm, s_ssm, s_sm = _clients()
    _expect_tree(s_ssm, [[_param("A", "1"), {"Name": PREFIX + "_meta", "Value": _meta(original)}]])
    s_sm.add_response("get_secret_value", {"SecretString": json.dumps(original)}, {"SecretId": NAME})
    with s_ssm, s_sm:
        assert json.loads(tss.get_secret_string(NAME, ssm_client=ssm, sm_client=sm)) == original


def test_auto_falls_back_on_ssm_access_denied():
    ssm, sm, s_ssm, s_sm = _clients()
    s_ssm.add_client_error("get_parameters_by_path", service_error_code="AccessDeniedException")
    s_sm.add_response("get_secret_value", {"SecretString": "plain"}, {"SecretId": NAME})
    with s_ssm, s_sm:
        assert tss.get_secret_string(NAME, ssm_client=ssm, sm_client=sm) == "plain"


def test_ssm_mode_raises_when_tree_missing(monkeypatch):
    monkeypatch.setenv("TENX_SECRET_SOURCE", "ssm")
    ssm, sm, s_ssm, s_sm = _clients()
    _expect_tree(s_ssm, [[]])
    with s_ssm, s_sm, pytest.raises(tss.SecretSourceError):
        tss.get_secret_string(NAME, ssm_client=ssm, sm_client=sm)


def test_ssm_mode_raises_on_hash_mismatch(monkeypatch):
    monkeypatch.setenv("TENX_SECRET_SOURCE", "ssm")
    ssm, sm, s_ssm, _ = _clients()
    _expect_tree(s_ssm, [[_param("A", "changed"), {"Name": PREFIX + "_meta", "Value": _meta({"A": "1"})}]])
    with s_ssm, pytest.raises(tss.SecretSourceError):
        tss.get_secret_string(NAME, ssm_client=ssm, sm_client=sm)


def test_secretsmanager_mode_skips_ssm(monkeypatch):
    monkeypatch.setenv("TENX_SECRET_SOURCE", "secretsmanager")
    ssm, sm, s_ssm, s_sm = _clients()
    s_sm.add_response("get_secret_value", {"SecretString": "x"}, {"SecretId": NAME})
    with s_ssm, s_sm:
        assert tss.get_secret_string(NAME, ssm_client=ssm, sm_client=sm) == "x"
    s_ssm.assert_no_pending_responses()


def test_nested_secret_tree_is_excluded():
    original = {"A": "1"}
    ssm, sm, s_ssm, _ = _clients()
    params = [
        _param("A", "1"),
        {"Name": PREFIX + "_meta", "Value": _meta(original)},
        _param("child/X", "2"),
        {"Name": PREFIX + "child/_meta", "Value": "{}"},
    ]
    _expect_tree(s_ssm, [params])
    with s_ssm:
        assert tss.get_secret_dict(NAME, ssm_client=ssm, sm_client=sm) == original


def test_invalid_source_value(monkeypatch):
    monkeypatch.setenv("TENX_SECRET_SOURCE", "vault")
    with pytest.raises(tss.SecretSourceError):
        tss.get_secret_string(NAME)
