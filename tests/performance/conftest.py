"""
Performance test fixtures — shared across load, stress, soak, and related tests.
Provides TestClient, auth overrides, auto-mocked Strapi boundary, and timing helpers.
"""
import pytest
import time
import statistics
import io
from unittest.mock import MagicMock, patch, AsyncMock
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
# Auto-mock Strapi (prevent real external calls during perf tests)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_strapi_boundary():
    """Auto-mock Strapi to prevent real external calls."""
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
        cm.delete_user.return_value = None
        cm.delete_alluser.return_value = None
        cm.delete_profile.return_value = None
        cm.delete_trainee.return_value = None
        MockCM.return_value = cm
        yield {"sg": sg, "sm": sm, "cm": cm}


# ---------------------------------------------------------------------------
# Timing / stats helpers
# ---------------------------------------------------------------------------

class ResponseTimer:
    """Collect response times and compute percentile stats."""

    def __init__(self):
        self.times = []
        self.status_codes = []
        self.errors = 0

    def record(self, elapsed_sec, status_code):
        self.times.append(elapsed_sec)
        self.status_codes.append(status_code)
        if status_code >= 500:
            self.errors += 1

    @property
    def count(self):
        return len(self.times)

    @property
    def p50(self):
        return self._percentile(50) if self.times else 0

    @property
    def p95(self):
        return self._percentile(95) if self.times else 0

    @property
    def p99(self):
        return self._percentile(99) if self.times else 0

    @property
    def mean(self):
        return statistics.mean(self.times) if self.times else 0

    @property
    def max_time(self):
        return max(self.times) if self.times else 0

    @property
    def min_time(self):
        return min(self.times) if self.times else 0

    @property
    def error_rate(self):
        return (self.errors / self.count * 100) if self.count else 0

    @property
    def success_count(self):
        return sum(1 for sc in self.status_codes if sc < 500)

    def _percentile(self, p):
        sorted_t = sorted(self.times)
        idx = int(len(sorted_t) * p / 100)
        idx = min(idx, len(sorted_t) - 1)
        return sorted_t[idx]

    def summary(self):
        return {
            "count": self.count,
            "mean_ms": round(self.mean * 1000, 2),
            "p50_ms": round(self.p50 * 1000, 2),
            "p95_ms": round(self.p95 * 1000, 2),
            "p99_ms": round(self.p99 * 1000, 2),
            "max_ms": round(self.max_time * 1000, 2),
            "min_ms": round(self.min_time * 1000, 2),
            "error_rate_pct": round(self.error_rate, 2),
        }


@pytest.fixture
def timer():
    return ResponseTimer()


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------

def trainee_payload(index=0):
    return {
        "config": {"run_stage": "dev", "batch": "5", "role": "trainee", "is_mock": True},
        "trainee": {
            "name": f"Load User {index}",
            "email": f"loaduser{index}@example.com",
            "password": "TestPass1!",
        },
    }


def webhook_payload(index=0):
    return {
        "status": "success",
        "batch": str(index),
        "errors": [],
    }


def make_csv(num_rows):
    """Generate CSV bytes with num_rows trainee records."""
    lines = ["name,email"]
    for i in range(num_rows):
        lines.append(f"Batch User {i},batchuser{i}@example.com")
    return "\n".join(lines).encode("utf-8")
