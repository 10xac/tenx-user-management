"""
Stress Testing — Push the system beyond normal capacity to find breaking points.
Unlike load testing (normal traffic), stress testing intentionally exceeds
expected limits to observe degradation behaviour, error handling under pressure,
and recovery characteristics.

Industry standard: Verify the system degrades gracefully (no crashes, no data
corruption, no unhandled exceptions) when pushed past its designed capacity.

Targets:
  - System must NOT crash (500) under extreme concurrency
  - Error rate must stay below 5% even under 200 concurrent requests
  - System must recover after stress is removed (cool-down verification)
  - Large payloads must not cause OOM or hangs
"""
import time
import pytest
import gc
from concurrent.futures import ThreadPoolExecutor, as_completed

from tests.performance.conftest import trainee_payload, webhook_payload, make_csv, ResponseTimer


# ============================================================================
# 1. Extreme Concurrency Stress
# ============================================================================

class TestExtremeConcurrency:
    """Push concurrent connections far beyond normal operating levels."""

    def test_100_concurrent_trainee_requests(self, client, timer):
        """100 simultaneous users — well beyond normal expected concurrency."""
        def make_request(idx):
            start = time.perf_counter()
            resp = client.post("/trainee/single", json=trainee_payload(idx))
            return time.perf_counter() - start, resp.status_code

        with ThreadPoolExecutor(max_workers=100) as pool:
            futures = [pool.submit(make_request, i) for i in range(100)]
            for f in as_completed(futures):
                elapsed, status = f.result()
                timer.record(elapsed, status)

        summary = timer.summary()
        assert timer.error_rate < 5.0, \
            f"Error rate {summary['error_rate_pct']}% exceeds 5% under extreme concurrency"
        assert timer.count == 100

    def test_200_concurrent_webhook_requests(self, client, timer):
        """200 simultaneous webhook deliveries — simulates burst notification scenario."""
        def send_webhook(idx):
            start = time.perf_counter()
            resp = client.post("/webhook", json=webhook_payload(idx))
            return time.perf_counter() - start, resp.status_code

        with ThreadPoolExecutor(max_workers=200) as pool:
            futures = [pool.submit(send_webhook, i) for i in range(200)]
            for f in as_completed(futures):
                elapsed, status = f.result()
                timer.record(elapsed, status)

        summary = timer.summary()
        assert timer.error_rate < 2.0, \
            f"Webhook error rate {summary['error_rate_pct']}% exceeds 2% under stress"
        assert timer.count == 200

    def test_mixed_endpoints_150_concurrent(self, client, timer):
        """150 concurrent requests spread across all endpoint types."""
        import random
        random.seed(99)

        def mixed_request(idx):
            roll = random.random()
            start = time.perf_counter()
            if roll < 0.5:
                resp = client.post("/trainee/single", json=trainee_payload(idx))
            elif roll < 0.8:
                resp = client.post("/webhook", json=webhook_payload(idx))
            else:
                resp = client.get("/openapi.json")
            return time.perf_counter() - start, resp.status_code

        with ThreadPoolExecutor(max_workers=150) as pool:
            futures = [pool.submit(mixed_request, i) for i in range(150)]
            for f in as_completed(futures):
                elapsed, status = f.result()
                timer.record(elapsed, status)

        summary = timer.summary()
        assert timer.error_rate < 5.0, f"Mixed stress error rate too high: {summary}"
        assert timer.count == 150


# ============================================================================
# 2. Rapid Fire / Burst Stress
# ============================================================================

class TestRapidFireStress:
    """Send maximum requests in minimum time to stress the request pipeline."""

    def test_300_sequential_rapid_fire(self, client, timer):
        """300 sequential requests as fast as possible — stresses serialization."""
        for i in range(300):
            start = time.perf_counter()
            resp = client.post("/trainee/single", json=trainee_payload(i))
            timer.record(time.perf_counter() - start, resp.status_code)

        summary = timer.summary()
        assert timer.error_rate < 1.0, f"Rapid fire errors: {summary}"
        assert timer.count == 300

    def test_500_webhook_rapid_fire(self, client, timer):
        """500 webhook requests — lightweight endpoint should handle volume."""
        for i in range(500):
            start = time.perf_counter()
            resp = client.post("/webhook", json=webhook_payload(i))
            timer.record(time.perf_counter() - start, resp.status_code)

        summary = timer.summary()
        assert timer.error_rate == 0, f"Webhook rapid fire errors: {summary}"
        assert timer.count == 500


# ============================================================================
# 3. Large Payload Stress
# ============================================================================

class TestLargePayloadStress:
    """Push payload sizes to extremes to test memory and parsing limits."""

    def test_trainee_with_massive_bio(self, client):
        """10KB bio field — tests JSON parsing under large input."""
        payload = trainee_payload(0)
        payload["trainee"]["bio"] = "A" * 10_000
        resp = client.post("/trainee/single", json=payload)
        assert resp.status_code in [200, 422], f"Unexpected status: {resp.status_code}"

    def test_trainee_with_massive_other_info(self, client):
        """Large nested other_info dict — tests deep JSON processing."""
        payload = trainee_payload(0)
        payload["trainee"]["other_info"] = {
            f"key_{i}": f"value_{'x' * 500}" for i in range(100)
        }
        resp = client.post("/trainee/single", json=payload)
        assert resp.status_code in [200, 422]

    def test_webhook_with_massive_errors_list(self, client):
        """Webhook payload with 1000 error entries."""
        errors = [{"row": i, "error": f"Error message for row {i}" * 10}
                  for i in range(1000)]
        resp = client.post("/webhook", json={
            "status": "partial_success", "batch": "stress", "errors": errors
        })
        assert resp.status_code == 200

    def test_batch_csv_100_rows(self, authed_client):
        """100-row CSV upload — tests CSV parsing under volume."""
        csv_data = make_csv(100)
        resp = authed_client.post(
            "/trainee/batch",
            files={"file": ("large.csv", csv_data, "text/csv")},
            data={"run_stage": "dev", "batch": "stress", "is_mock": "true",
                  "login_url": "https://10academy.org/login"},
        )
        assert resp.status_code != 500

    def test_batch_csv_500_rows(self, authed_client):
        """500-row CSV — larger batch stress test."""
        csv_data = make_csv(500)
        resp = authed_client.post(
            "/trainee/batch",
            files={"file": ("huge.csv", csv_data, "text/csv")},
            data={"run_stage": "dev", "batch": "stress", "is_mock": "true",
                  "login_url": "https://10academy.org/login"},
        )
        assert resp.status_code != 500

    def test_csv_with_very_long_names(self, authed_client):
        """CSV with 1000-character names — tests name processing under extreme input."""
        lines = ["name,email"]
        for i in range(10):
            long_name = f"Name{'A' * 1000} User{i}"
            lines.append(f"{long_name},longname{i}@test.com")
        csv_data = "\n".join(lines).encode("utf-8")
        resp = authed_client.post(
            "/trainee/batch",
            files={"file": ("longnames.csv", csv_data, "text/csv")},
            data={"run_stage": "dev", "batch": "stress", "is_mock": "true",
                  "login_url": "https://10academy.org/login"},
        )
        assert resp.status_code != 500


# ============================================================================
# 4. Error Cascade Stress
# ============================================================================

class TestErrorCascadeStress:
    """Verify the system handles cascading errors without crashing."""

    def test_100_validation_errors_in_sequence(self, client, timer):
        """100 requests that all fail validation — tests error path performance."""
        for i in range(100):
            start = time.perf_counter()
            resp = client.post("/trainee/single", json={
                "config": {"run_stage": "dev"},
                "trainee": {"name": "", "email": "invalid"},
            })
            timer.record(time.perf_counter() - start, resp.status_code)

        assert timer.count == 100
        # All should be 422 (validation error), none should be 500
        assert all(sc in [200, 422] for sc in timer.status_codes), \
            "Validation errors should never cause 500"

    def test_50_concurrent_validation_errors(self, client, timer):
        """50 concurrent invalid requests — tests error path under concurrency."""
        def bad_request(idx):
            start = time.perf_counter()
            resp = client.post("/trainee/single", json={
                "config": {"run_stage": "dev"},
                "trainee": {"name": "", "email": "bad"},
            })
            return time.perf_counter() - start, resp.status_code

        with ThreadPoolExecutor(max_workers=50) as pool:
            futures = [pool.submit(bad_request, i) for i in range(50)]
            for f in as_completed(futures):
                elapsed, status = f.result()
                timer.record(elapsed, status)

        assert all(sc != 500 for sc in timer.status_codes), \
            "Concurrent validation errors must not cause 500"

    def test_mixed_valid_and_invalid_requests(self, client, timer):
        """Alternating valid/invalid requests — tests state isolation."""
        for i in range(100):
            start = time.perf_counter()
            if i % 2 == 0:
                resp = client.post("/trainee/single", json=trainee_payload(i))
            else:
                resp = client.post("/trainee/single", json={
                    "config": {"run_stage": "dev"},
                    "trainee": {"name": "", "email": "bad"},
                })
            timer.record(time.perf_counter() - start, resp.status_code)

        # No 500 errors — errors from one request must not affect the next
        assert all(sc != 500 for sc in timer.status_codes), \
            "Error contamination detected between requests"

    def test_malformed_json_burst(self, client, timer):
        """Burst of malformed JSON payloads — tests parser resilience."""
        for i in range(50):
            start = time.perf_counter()
            resp = client.post(
                "/webhook",
                content=b"{broken json" + str(i).encode(),
                headers={"Content-Type": "application/json"},
            )
            timer.record(time.perf_counter() - start, resp.status_code)

        # All should be 400 (bad JSON), never 500
        assert all(sc in [400, 422] for sc in timer.status_codes), \
            "Malformed JSON must return 400, not 500"


# ============================================================================
# 5. Recovery After Stress
# ============================================================================

class TestRecoveryAfterStress:
    """Verify the system recovers to normal performance after stress is removed."""

    def test_performance_recovery_after_burst(self, client):
        """After a burst of 200 requests, verify latency returns to baseline."""
        # Measure baseline (5 requests)
        baseline_times = []
        for i in range(5):
            start = time.perf_counter()
            client.post("/trainee/single", json=trainee_payload(i))
            baseline_times.append(time.perf_counter() - start)
        avg_baseline = sum(baseline_times) / len(baseline_times)

        # Apply stress: 200 concurrent requests
        with ThreadPoolExecutor(max_workers=50) as pool:
            futures = [pool.submit(
                lambda idx: client.post("/trainee/single", json=trainee_payload(idx)),
                i
            ) for i in range(200)]
            for f in as_completed(futures):
                f.result()

        # Measure recovery (5 requests after stress)
        recovery_times = []
        for i in range(5):
            start = time.perf_counter()
            client.post("/trainee/single", json=trainee_payload(1000 + i))
            recovery_times.append(time.perf_counter() - start)
        avg_recovery = sum(recovery_times) / len(recovery_times)

        # Recovery should be within 5x of baseline (generous margin)
        assert avg_recovery < avg_baseline * 5, (
            f"Recovery too slow: baseline={avg_baseline*1000:.1f}ms, "
            f"recovery={avg_recovery*1000:.1f}ms"
        )

    def test_correct_responses_after_error_storm(self, client):
        """After 100 error-inducing requests, valid requests still succeed."""
        # Error storm
        for i in range(100):
            client.post("/trainee/single", json={
                "config": {"run_stage": "dev"},
                "trainee": {"name": "", "email": "bad"},
            })

        # Recovery: 10 valid requests must all succeed
        for i in range(10):
            resp = client.post("/trainee/single", json=trainee_payload(i))
            assert resp.status_code == 200
            assert resp.json()["success"] is True, \
                f"Request {i} failed after error storm"

    def test_gc_collection_after_stress(self, client):
        """Verify garbage collection works after stress — no leaked objects."""
        gc.collect()
        pre_count = len(gc.get_objects())

        # Stress: 100 requests
        for i in range(100):
            client.post("/trainee/single", json=trainee_payload(i))

        gc.collect()
        post_count = len(gc.get_objects())

        # Object count should not grow unboundedly (allow some growth)
        growth = post_count - pre_count
        # Very generous: less than 1000 new objects per request on average
        assert growth < 100_000, \
            f"Object count grew by {growth} after 100 requests (possible leak)"
