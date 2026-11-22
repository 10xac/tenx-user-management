"""Secret source selection: SSM Parameter Store tree first, Secrets Manager fallback.

Implements the Tenx "Secrets Manager -> SSM Parameter Store" loader contract:

* A Secrets Manager secret ``<name>`` whose value is a JSON object lives in SSM
  as one SecureString per key at ``/<name>/<KEY>``; a non-object secret lives at
  ``/<name>/_value``. A plain String marker ``/<name>/_meta`` holds
  ``{"source", "format": "json"|"plain", "keys": N, "sha256": <10-char prefix>}``
  and is what tells a reader the tree is complete.
* ``TENX_SECRET_SOURCE`` selects the backend:
  ``auto`` (default) SSM tree when ``_meta`` exists, else Secrets Manager;
  ``ssm`` SSM only (raise when missing); ``secretsmanager`` old behaviour.

The public helpers return exactly what Secrets Manager used to return
(``SecretString`` text, or the parsed object), so existing callers keep working.
Values are never logged; only the secret name and the source used, once per name.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger("tenx.secret_source")

DEFAULT_REGION = "us-east-1"
SOURCE_ENV = "TENX_SECRET_SOURCE"
VALID_SOURCES = ("auto", "ssm", "secretsmanager")

_logged_sources: Dict[str, str] = {}


class SecretSourceError(RuntimeError):
    """Raised when the requested secret cannot be read from the selected source."""


def secret_source() -> str:
    """Return the configured source (``auto`` when unset); reject unknown values."""
    value = (os.environ.get(SOURCE_ENV) or "auto").strip().lower()
    if value not in VALID_SOURCES:
        raise SecretSourceError(
            f"{SOURCE_ENV}={value!r} is invalid; expected one of {', '.join(VALID_SOURCES)}"
        )
    return value


def _region(region: Optional[str]) -> str:
    return region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or DEFAULT_REGION


def _client(service: str, region: Optional[str]):
    import boto3  # imported lazily so importing this module never needs AWS

    return boto3.session.Session().client(service_name=service, region_name=_region(region))


def _log_source_once(name: str, source: str) -> None:
    if _logged_sources.get(name) != source:
        _logged_sources[name] = source
        logger.info("secret %s loaded from %s", name, source)


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]


def _hash_candidates(obj: Any) -> set:
    """Hashes of the plausible canonical-JSON spellings of ``obj``."""
    spellings = {
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
    }
    if isinstance(obj, str):
        spellings.add(obj)
    return {_short_hash(s) for s in spellings}


def _decode_non_string(raw: Dict[str, str]) -> Dict[str, Any]:
    """Decode values that are JSON text for a non-string (number, bool, null, object, array)."""
    out: Dict[str, Any] = {}
    for key, text in raw.items():
        try:
            decoded = json.loads(text)
        except (TypeError, ValueError):
            decoded = text
        out[key] = text if isinstance(decoded, str) else decoded
    return out


def _fetch_tree(name: str, ssm_client) -> Dict[str, str]:
    """All parameters under ``/<name>/`` keyed by their path relative to it."""
    prefix = "/" + name.strip("/") + "/"
    params: Dict[str, str] = {}
    kwargs = {"Path": prefix, "Recursive": True, "WithDecryption": True}
    while True:
        page = ssm_client.get_parameters_by_path(**kwargs)
        for param in page.get("Parameters", []):
            params[param["Name"][len(prefix):]] = param["Value"]
        token = page.get("NextToken")
        if not token:
            return params
        kwargs["NextToken"] = token


def _rebuild(name: str, params: Dict[str, str]) -> Tuple[Any, str]:
    """Rebuild the original secret from its tree. Returns (object, SecretString text)."""
    meta = json.loads(params["_meta"])
    # A deeper "_meta" marks a nested secret (e.g. "<name>/child"); its keys are not ours.
    nested = [p[: -len("/_meta")] + "/" for p in params if p.endswith("/_meta")]
    values = {
        k: v
        for k, v in params.items()
        if k != "_meta" and not any(k.startswith(n) for n in nested)
    }
    fmt = meta.get("format")
    expected = meta.get("sha256")

    if fmt == "plain":
        if "_value" not in values:
            raise SecretSourceError(f"SSM tree /{name}/ is incomplete (no _value)")
        text = values["_value"]
        if expected and expected not in _hash_candidates(text):
            raise SecretSourceError(f"SSM tree /{name}/ does not match its _meta hash")
        return text, text

    if fmt != "json":
        raise SecretSourceError(f"SSM tree /{name}/ has unknown format {fmt!r}")
    if meta.get("keys") is not None and int(meta["keys"]) != len(values):
        raise SecretSourceError(
            f"SSM tree /{name}/ is incomplete ({len(values)} of {meta['keys']} keys)"
        )

    json_keys = meta.get("json_keys")
    if isinstance(json_keys, list):
        # Writer recorded which keys held non-string JSON: no guessing needed.
        obj = {k: (json.loads(v) if k in json_keys else v) for k, v in values.items()}
        candidates = [obj]
    else:
        # A stored "5432" may have been the string "5432" or the number 5432; the
        # _meta hash of the original object tells which reading is the real one.
        candidates = [dict(values), _decode_non_string(values)]

    for obj in candidates:
        if not expected or expected in _hash_candidates(obj):
            return obj, json.dumps(obj)
    raise SecretSourceError(f"SSM tree /{name}/ does not match its _meta hash")


def _from_ssm(name: str, ssm_client) -> Optional[Tuple[Any, str]]:
    """The secret from SSM, or None when no complete tree (no ``_meta``) exists."""
    params = _fetch_tree(name, ssm_client)
    if "_meta" not in params:
        return None
    return _rebuild(name, params)


def _from_secretsmanager(name: str, sm_client) -> Any:
    """Secrets Manager value exactly as before: SecretString text or decoded binary."""
    response = sm_client.get_secret_value(SecretId=name)
    if "SecretString" in response:
        return response["SecretString"]
    if "SecretBinary" in response:
        import base64

        return base64.b64decode(response["SecretBinary"])
    return response


def get_secret_string(
    name: str,
    *,
    region: Optional[str] = None,
    ssm_client=None,
    sm_client=None,
    client_factory: Optional[Callable[[str, Optional[str]], Any]] = None,
):
    """Return the secret as Secrets Manager's ``SecretString`` would have.

    JSON-object secrets come back as JSON text (``json.loads`` gives the original
    dict); plain secrets as the raw string. A Secrets Manager binary secret keeps
    returning decoded bytes.
    """
    source = secret_source()
    factory = client_factory or _client

    if source in ("auto", "ssm"):
        ssm = ssm_client or factory("ssm", region)
        try:
            found = _from_ssm(name, ssm)
        except SecretSourceError:
            if source == "ssm":
                raise
            logger.warning("secret %s: SSM tree unusable, falling back to Secrets Manager", name)
            found = None
        except Exception as exc:  # AccessDenied, throttling, no credentials, ...
            if source == "ssm":
                raise SecretSourceError(f"secret {name}: SSM read failed: {type(exc).__name__}") from exc
            logger.warning(
                "secret %s: SSM read failed (%s), falling back to Secrets Manager",
                name,
                type(exc).__name__,
            )
            found = None
        if found is not None:
            _log_source_once(name, "ssm")
            return found[1]
        if source == "ssm":
            raise SecretSourceError(f"secret {name}: no SSM tree at /{name.strip('/')}/ (_meta missing)")

    sm = sm_client or factory("secretsmanager", region)
    value = _from_secretsmanager(name, sm)
    _log_source_once(name, "secretsmanager")
    return value


def get_secret_dict(name: str, **kwargs) -> Any:
    """Return the secret parsed as JSON (a dict for JSON-object secrets)."""
    value = get_secret_string(name, **kwargs)
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return json.loads(value)
